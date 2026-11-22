"""The seam: the clinical section in the shared snapshot and the clinical routes on the real app.

Run from backend/:  python tests/test_clinical_integration.py   (or: python -m pytest tests)
Unlike the other clinical tests these use the REAL app and the shared worlds (main.sim / main.live),
exactly as test_live_calls.py does, so they check the seam itself: WorldState.reset_simulation,
WorldState.snapshot and the mount in main.py. TestClient is used without `with`, so the lifespan
(background loops) never runs. Offline: no routing, no Claude.

Hygiene: both worlds are re-seeded at the start and at the end of every test (the shared worlds
must not carry a log or trips from one test into the next, or into another file). These tests never
touch calls.enabled / calls.per_hour, and they put CLINICAL_ENABLED back exactly as they found it.
"""
from __future__ import annotations

import clinical_helpers  # noqa: F401  (must be first: sets the offline env, puts backend/ on sys.path)

import functools
import json
import os
import sys
import time
import traceback
from contextlib import contextmanager
from unittest import mock

from fastapi.testclient import TestClient

import app.clinical.projection as projection
from app import config, main
from app.clinical.store import ClinicalLog, get_log
from app.sim.seed import seed_world
from clinical_helpers import drive, entry, er_trip

W = main.sim
L = main.live
client = TestClient(main.app)

# The twenty top-level keys WorldState.snapshot() carried before the clinical section existed.
# Hard-coded on purpose: deriving it from snapshot() would make the check circular. It is a FLOOR, not
# the full list: upstream keeps adding keys (surge, epoch, ai_mode ...), so "nothing was removed" is
# checked against this set and "only `clinical` was added" is checked against the same world with the
# kill switch on (see assert_only_clinical_added).
EXPECTED_KEYS = {
    "world", "hypothetical", "speedup", "version", "sim_time", "real_time", "mode", "calls", "places",
    "vehicles", "trips", "incidents", "weather", "traffic", "roads", "sources", "alerts", "kpis",
    "events", "agent",
}


def reseed() -> None:
    for world in (W, L):
        seed_world(world, config.RANDOM_SEED, scheduled_day=False)


def clean_worlds(fn):
    """Run a test between two re-seeds of both shared worlds, whether it passes or fails."""

    @functools.wraps(fn)
    def wrapper() -> None:
        reseed()
        try:
            fn()
        finally:
            reseed()

    return wrapper


@contextmanager
def clinical_env(value: str):
    """Set CLINICAL_ENABLED for a block and put back exactly what was there (the suite shares os.environ)."""
    before = os.environ.get("CLINICAL_ENABLED")
    os.environ["CLINICAL_ENABLED"] = value
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("CLINICAL_ENABLED", None)
        else:
            os.environ["CLINICAL_ENABLED"] = before


def post(path: str, payload: dict, status: int = 201) -> dict:
    r = client.post(path, json=payload)
    assert r.status_code == status, (r.status_code, r.text)
    return r.json()


def assert_only_clinical_added(keys: set) -> None:
    """`keys` (a snapshot's top-level keys) must hold every original key, plus `clinical`, plus nothing
    that the same world does not already emit with the kill switch on (so upstream's own new keys pass)."""
    assert EXPECTED_KEYS <= keys, f"snapshot lost keys: {sorted(EXPECTED_KEYS - keys)}"
    assert "clinical" in keys
    with clinical_env("0"):
        without = set(W.snapshot())
    assert keys - {"clinical"} == without, f"snapshot differs beyond `clinical`: {sorted(keys ^ without)}"


# --- snapshot compatibility -----------------------------------------------------------------------

@clean_worlds
def test_snapshot_keeps_every_existing_key_and_adds_clinical():
    s = W.snapshot()
    assert_only_clinical_added(set(s))
    json.dumps(s)  # the SSE stream does exactly this: the whole snapshot must be plain JSON


@clean_worlds
def test_state_endpoint_carries_clinical():
    body = client.get("/sim/state").json()
    assert_only_clinical_added(set(body))
    assert body["clinical"]["world"] == "sim" and body["clinical"]["seq"] == 0 and body["clinical"]["cases"] == []
    legacy = client.get("/state").json()  # the un-prefixed alias points at the sim world
    assert legacy["clinical"]["world"] == "sim"


# --- fail-safe and kill switch --------------------------------------------------------------------

@clean_worlds
def test_failure_in_clinical_never_breaks_state():
    with mock.patch.object(projection, "board", side_effect=RuntimeError("boom")):
        r = client.get("/sim/state")
        assert r.status_code == 200
        body = r.json()
        assert body["clinical"]["error"].startswith("RuntimeError"), body["clinical"]
        assert_only_clinical_added(set(body))  # every other section is still there
        assert W.snapshot()["clinical"]["error"].startswith("RuntimeError")
    assert "error" not in client.get("/sim/state").json()["clinical"]  # and it recovers on its own


@clean_worlds
def test_kill_switch_removes_the_section():
    with clinical_env("0"):
        assert "clinical" not in W.snapshot()
        r = client.get("/sim/state")
        assert r.status_code == 200
        assert "clinical" not in r.json() and EXPECTED_KEYS <= set(r.json())  # exactly today's snapshot
    assert "clinical" in W.snapshot()  # switched back on at once: the switch is read on every call


# --- a world reset clears the log -----------------------------------------------------------------

@clean_worlds
def test_world_reset_clears_the_log_and_idempotency():
    t = er_trip(W)
    first = post("/sim/clinical/entries", entry(t, client_entry_id="x"))
    assert first["seq"] == 1
    old_log = get_log(W)
    assert len(old_log) == 1

    r = client.post("/sim/admin/reset", json={"scheduled_day": False})
    assert r.status_code == 200 and r.json()["trips"] == 0, r.text
    assert get_log(W) is not old_log and len(get_log(W)) == 0
    assert client.get("/sim/clinical/entries").json() == []
    assert client.get("/sim/er/board").json()["seq"] == 0

    # The reset removed every trip, so the old payload would now be a 404: make a new case and reuse the
    # same client id. A cleared idempotency map answers 201 with seq 1, not a replay of the old entry.
    t2 = er_trip(W)
    again = post("/sim/clinical/entries", entry(t2, client_entry_id="x"))
    assert again["seq"] == 1 and again["case_id"] == t2.id
    assert [e["seq"] for e in client.get("/sim/clinical/entries").json()] == [1]


# --- the three views cannot disagree --------------------------------------------------------------

@clean_worlds
def test_three_views_are_identical_after_mixed_writes():
    t = er_trip(W)
    drive(W, 1)  # some sim time passes: the board is a live projection, not a fixed snapshot
    vehicle = t.vehicle_id

    vitals = post("/sim/clinical/entries", entry(t, client_entry_id="v1"))  # entry via POST
    post(f"/sim/clinical/entries/{vitals['seq']}/confirm", {"unit": vehicle}, status=200)  # a confirm
    post(f"/sim/er/cases/{t.id}/actions", {"action": "acknowledge", "note": "bay free soon"})  # a reception action
    second = post("/sim/clinical/entries", entry(t, content={"hr": 130, "spo2": 90}))  # a new reading ...
    fixed = post(  # ... and its correction
        "/sim/clinical/entries",
        entry(t, content={"hr": 103, "spo2": 90}, supersedes=second["entry_id"]),
    )
    assert fixed["supersedes"] == second["entry_id"]

    board = client.get("/sim/er/board").json()
    in_state = client.get("/sim/state").json()["clinical"]
    in_snapshot = json.loads(json.dumps(W.snapshot()["clinical"]))
    assert board == in_state == in_snapshot

    # not an empty-equals-empty pass: the board carries this case and every write
    assert board["seq"] == 5 and [c["case_id"] for c in board["cases"]] == [t.id]
    assert [e["seq"] for e in board["entries_tail"]] == [1, 2, 3, 4, 5]


@clean_worlds
def test_entry_bumps_version_so_the_stream_pushes_it():
    t = er_trip(W)
    v = W.version
    post("/sim/clinical/entries", entry(t))
    after_entry = W.version
    assert after_entry > v
    post(f"/sim/er/cases/{t.id}/actions", {"action": "acknowledge"})
    assert W.version > after_entry
    assert W.snapshot()["version"] == W.version  # the number the stream compares is the one it sends


# --- the two worlds keep separate logs ------------------------------------------------------------

@clean_worlds
def test_live_and_sim_logs_are_independent():
    assert isinstance(W.clinical, ClinicalLog) and isinstance(L.clinical, ClinicalLog)
    assert W.clinical is not L.clinical

    t = er_trip(W)
    post("/sim/clinical/entries", entry(t))
    assert [e["case_id"] for e in client.get("/sim/clinical/entries").json()] == [t.id]
    assert client.get("/live/clinical/entries").json() == []
    live_board = client.get("/live/er/board").json()
    assert live_board["world"] == "live" and live_board["seq"] == 0 and live_board["cases"] == []
    assert L.snapshot()["clinical"]["seq"] == 0

    # and the other way round: an entry in the live world never shows up in the sim world
    lt = er_trip(L)
    post("/live/clinical/entries", entry(lt))
    assert [e["case_id"] for e in client.get("/live/clinical/entries").json()] == [lt.id]
    assert [e["case_id"] for e in client.get("/sim/clinical/entries").json()] == [t.id]
    assert client.get("/sim/er/board").json()["seq"] == 1


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        t0 = time.time()
        try:
            fn()
            print(f"PASS {name} ({time.time() - t0:.1f}s)")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
