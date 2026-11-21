"""HTTP routes for the clinical log and the ER board.

Run from backend/:  python tests/test_clinical_api.py   (or: python -m pytest tests)
Offline and self-contained: every test builds its own world and its own FastAPI app with
mount(app, {"sim": w}); none of them imports app.main or touches main.sim / main.live.
"""
from __future__ import annotations

import clinical_helpers  # noqa: F401  (must be first: sets the offline env, puts backend/ on sys.path)

import inspect
import json
import os
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.clinical.api import _invalid, mount
from app.clinical.models import ENTRY_IN
from app.clinical.projection import board, build_case
from app.clinical.store import get_log
from app.engine.events import apply_event
from app.models import TaskRequestEvent
from clinical_helpers import drive, entry, er_trip, fresh_world

EXPECTED_ROUTES = {
    ("POST", "/{world}/clinical/entries"),
    ("GET", "/{world}/clinical/entries"),
    ("POST", "/{world}/clinical/entries/{seq}/confirm"),
    ("GET", "/{world}/er/board"),
    ("GET", "/{world}/er/cases/{case_id}"),
    ("POST", "/{world}/er/cases/{case_id}/actions"),
}


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


def make():
    """(client, world) for a fresh world mounted as "sim" on its own app."""
    w = fresh_world()
    app = FastAPI()
    with clinical_env("1"):
        mount(app, {"sim": w})
    return TestClient(app), w


def mark(w):
    """What a rejected request must leave alone: the log's length and the world version."""
    return len(get_log(w)), w.version


def non_er_trip(w):
    """A patient transport to the oncology institute: a real trip, but not an ER case."""
    record = apply_event(
        w, TaskRequestEvent(type="task_request", pickup_id="home_polje", dropoff_id="onko", needs="stretcher", auto_assign=False)
    )
    t = w.trips[record.affected_trip_ids[0]]
    assert t.dropoff_id == "onko"
    return t


# --- Mounting ----------------------------------------------------------------------------------

def test_mount_adds_exactly_the_six_routes_and_every_one_is_a_coroutine():
    w = fresh_world()
    app = FastAPI()
    base = len(app.routes)
    with clinical_env("1"):
        mount(app, {"sim": w})
    routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/{world}/")]
    assert {(m, r.path) for r in routes for m in r.methods} == EXPECTED_ROUTES
    assert len(app.routes) == base + len(EXPECTED_ROUTES)
    for r in routes:  # a sync def would run in the threadpool and could race on seq assignment
        assert inspect.iscoroutinefunction(r.endpoint), r.path
        assert all(inspect.iscoroutinefunction(d.call) for d in r.dependant.dependencies), r.path


def test_disabled_mounts_nothing():
    app = FastAPI()
    n = len(app.routes)
    with clinical_env("0"):
        mount(app, {})
        assert len(app.routes) == n
        w = fresh_world()
        mount(app, {"sim": w})
        assert len(app.routes) == n
    assert TestClient(app).get("/sim/er/board").status_code == 404


def test_enabled_is_read_when_mount_is_called():
    app = FastAPI()
    n = len(app.routes)
    with clinical_env("0"):
        mount(app, {})
    assert len(app.routes) == n
    with clinical_env("1"):
        mount(app, {"sim": fresh_world()})
    assert len(app.routes) == n + len(EXPECTED_ROUTES)


def test_unknown_world_is_404_on_every_route():
    c, w = make()
    t = er_trip(w)
    before = mark(w)
    assert c.get("/nope/er/board").status_code == 404
    assert c.get("/nope/clinical/entries").status_code == 404
    assert c.get(f"/nope/er/cases/{t.id}").status_code == 404
    assert c.post("/nope/clinical/entries", json=entry(t)).status_code == 404
    assert c.post("/nope/clinical/entries/1/confirm", json={"unit": t.vehicle_id}).status_code == 404
    assert c.post(f"/nope/er/cases/{t.id}/actions", json={"action": "acknowledge"}).status_code == 404
    assert mark(w) == before


def test_each_world_is_served_by_its_own_path():
    w1, w2 = fresh_world(), fresh_world()
    app = FastAPI()
    with clinical_env("1"):
        mount(app, {"sim": w1, "live": w2})
    c = TestClient(app)
    t = er_trip(w2)
    assert c.post("/live/clinical/entries", json=entry(t)).status_code == 201
    assert len(get_log(w2)) == 1 and len(get_log(w1)) == 0
    assert c.get("/sim/clinical/entries").json() == []
    assert [e["seq"] for e in c.get("/live/clinical/entries").json()] == [1]
    assert [x["case_id"] for x in c.get("/live/er/board").json()["cases"]] == [t.id]
    assert c.get("/sim/er/board").json()["cases"] == []


# --- POST /clinical/entries --------------------------------------------------------------------

def test_post_entry_201_then_duplicate_200():
    c, w = make()
    t = er_trip(w)
    p = entry(t, client_entry_id="tap-1")
    r1 = c.post("/sim/clinical/entries", json=p)
    assert r1.status_code == 201, r1.text
    version = w.version
    r2 = c.post("/sim/clinical/entries", json=p)
    assert r2.status_code == 200, r2.text
    assert r1.json()["seq"] == r2.json()["seq"] == 1
    assert r1.json() == r2.json()  # the replay returns the original entry, not a new one
    assert len(get_log(w)) == 1 and w.version == version  # and writes nothing
    body = r1.json()
    assert body["case_id"] == t.id and body["unit"] == t.vehicle_id and body["type"] == "vitals"
    assert body["content"]["hr"] == 80 and body["state"] == "heard" and body["entry_id"] == "CE-00001"
    json.dumps(body)  # plain JSON all the way down


def test_without_a_client_id_every_post_is_a_new_entry():
    c, w = make()
    t = er_trip(w)
    assert c.post("/sim/clinical/entries", json=entry(t)).status_code == 201
    assert c.post("/sim/clinical/entries", json=entry(t)).status_code == 201
    assert len(get_log(w)) == 2


def test_wrong_vehicle_409_unknown_trip_404_bad_body_422():
    c, w = make()
    t = er_trip(w)
    now = w.sim_time
    cases = [
        (entry(t, unit="NOT-" + t.vehicle_id), 409),  # a crew entry from a vehicle that is not on the case
        (entry(t, case_id="TR-9999"), 404),
        (entry(t, observed_t="2026-01-01T12:00:00"), 422),  # naive time: never guessed, never a 500
        (entry(t, observed_t=(now + timedelta(hours=1)).isoformat()), 422),  # future (rule in the service)
        (entry(t, type="nonsense"), 422),
        ({k: v for k, v in entry(t).items() if k != "content"}, 422),
        (entry(t, content={"hr": 80, "colour": "red"}), 422),  # unknown content key is refused, not dropped
        (entry(t, supersedes="CE-00099"), 422),
        (entry(t, type="er_action", content={"action": "acknowledge"}), 422),  # crew cannot record reception actions
    ]
    for payload, expected in cases:
        before = mark(w)
        r = c.post("/sim/clinical/entries", json=payload)
        assert r.status_code == expected, (payload, r.status_code, r.text)
        assert mark(w) == before, payload  # a rejected request takes no seq and does not bump the version
    assert c.post("/sim/clinical/entries", content=b"{not json", headers={"content-type": "application/json"}).status_code == 422
    assert len(get_log(w)) == 0


def test_422_names_the_field_and_the_type_discriminator_survives_fastapi():
    c, w = make()
    t = er_trip(w)
    r = c.post("/sim/clinical/entries", json=entry(t, observed_t="2026-01-01T12:00:00"))
    assert r.status_code == 422
    # One error, inside the entry type that was named: a `= Body(...)` default would drop the
    # discriminator and report an error for each of the eleven entry types instead.
    assert [item["loc"] for item in r.json()["detail"]] == [["body", "vitals", "observed_t"]], r.json()
    r = c.post("/sim/clinical/entries", json=entry(t, type="nonsense"))
    assert r.status_code == 422
    assert [item["type"] for item in r.json()["detail"]] == ["union_tag_invalid"], r.json()
    r = c.post("/sim/clinical/entries", json=entry(t, content={"hr": 80, "colour": "red"}))
    assert [item["loc"] for item in r.json()["detail"]] == [["body", "vitals", "content", "colour"]], r.json()


def test_aware_observed_t_is_kept_and_wrong_vehicle_409_says_which_vehicle():
    c, w = make()
    t = er_trip(w)
    drive(w, 2)
    observed = t.dispatched_at + timedelta(seconds=10)  # after the case began, before now
    assert observed < w.sim_time
    r = c.post("/sim/clinical/entries", json=entry(t, observed_t=observed.isoformat()))
    assert r.status_code == 201, r.text
    assert datetime.fromisoformat(r.json()["observed_t"]) == observed  # kept, never moved to now
    r = c.post("/sim/clinical/entries", json=entry(t, unit="OTHER"))
    assert r.status_code == 409 and t.vehicle_id in r.json()["detail"]


# --- GET /clinical/entries ---------------------------------------------------------------------

def test_since_seq_catch_up_and_validation():
    c, w = make()
    t = er_trip(w)
    assert c.post("/sim/clinical/entries", json=entry(t)).status_code == 201
    assert c.post("/sim/clinical/entries", json=entry(t, content={"hr": 90})).status_code == 201
    assert [e["seq"] for e in c.get("/sim/clinical/entries?since_seq=1").json()] == [2]
    assert [e["seq"] for e in c.get("/sim/clinical/entries").json()] == [1, 2]
    assert [e["seq"] for e in c.get("/sim/clinical/entries?since_seq=2").json()] == []
    assert c.get("/sim/clinical/entries?since_seq=-1").status_code == 422
    assert c.get("/sim/clinical/entries?since_seq=abc").status_code == 422


def test_list_entries_filters_by_case_and_caps_with_limit():
    c, w = make()
    t1 = er_trip(w)
    t2 = er_trip(w)
    assert t1.id != t2.id
    for t in (t1, t2, t1, t2):
        assert c.post("/sim/clinical/entries", json=entry(t)).status_code == 201
    only_t2 = c.get(f"/sim/clinical/entries?case_id={t2.id}").json()
    assert [e["seq"] for e in only_t2] == [2, 4] and {e["case_id"] for e in only_t2} == {t2.id}
    assert [e["seq"] for e in c.get(f"/sim/clinical/entries?case_id={t2.id}&since_seq=2").json()] == [4]
    assert c.get("/sim/clinical/entries?case_id=TR-9999").json() == []
    assert [e["seq"] for e in c.get("/sim/clinical/entries?limit=3").json()] == [1, 2, 3]
    assert len(c.get("/sim/clinical/entries?limit=2000").json()) == 4
    for bad in ("limit=0", "limit=-1", "limit=2001", "limit=x"):
        assert c.get(f"/sim/clinical/entries?{bad}").status_code == 422, bad


def test_reads_change_nothing():
    c, w = make()
    t = er_trip(w)
    assert c.post("/sim/clinical/entries", json=entry(t)).status_code == 201
    before = mark(w)
    assert c.get("/sim/clinical/entries").status_code == 200
    assert c.get("/sim/er/board").status_code == 200
    assert c.get(f"/sim/er/cases/{t.id}").status_code == 200
    assert mark(w) == before


# --- GET /er/board and GET /er/cases/{id} ------------------------------------------------------

def test_board_endpoint_equals_projection():
    c, w = make()
    assert c.get("/sim/er/board").json() == json.loads(json.dumps(board(w)))  # an empty world too
    t = er_trip(w)
    assert c.post("/sim/clinical/entries", json=entry(t)).status_code == 201
    assert c.post(f"/sim/er/cases/{t.id}/actions", json={"action": "bay_assigned", "bay": "A-3"}).status_code == 201
    r = c.get("/sim/er/board")
    assert r.status_code == 200
    assert r.json() == json.loads(json.dumps(board(w)))
    [card] = r.json()["cases"]
    assert card["case_id"] == t.id and card["bay"] == "A-3" and card["vitals"]["hr"]["value"] == 80
    assert r.json()["seq"] == 2 and len(r.json()["entries_tail"]) == 2


def test_case_detail_has_timeline_and_non_er_trip_404():
    c, w = make()
    t = er_trip(w)
    assert c.post("/sim/clinical/entries", json=entry(t)).status_code == 201
    assert c.post("/sim/clinical/entries", json=entry(t, type="note", content={"text": "x"})).status_code == 201
    other = er_trip(w)
    assert c.post("/sim/clinical/entries", json=entry(other)).status_code == 201  # another case: not in this timeline
    assert c.post("/sim/clinical/entries/1/confirm", json={"unit": t.vehicle_id}).status_code == 200
    r = c.get(f"/sim/er/cases/{t.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"case", "timeline"}
    assert [e["seq"] for e in body["timeline"]] == [1, 2, 4]  # seq order, replaced entry 1 still listed
    assert {e["case_id"] for e in body["timeline"]} == {t.id}
    assert body["case"] == json.loads(json.dumps(build_case(w, t, get_log(w).for_case(t.id))))
    assert body["case"] == next(x for x in c.get("/sim/er/board").json()["cases"] if x["case_id"] == t.id)

    onko = non_er_trip(w)
    assert c.get(f"/sim/er/cases/{onko.id}").status_code == 404
    assert c.get("/sim/er/cases/TR-9999").status_code == 404


def test_case_with_no_entries_still_has_a_card_and_an_empty_timeline():
    c, w = make()
    t = er_trip(w)
    body = c.get(f"/sim/er/cases/{t.id}").json()
    assert body["timeline"] == [] and body["case"]["case_id"] == t.id


# --- POST /er/cases/{id}/actions ---------------------------------------------------------------

def test_actions_endpoint_records_er_action():
    c, w = make()
    t = er_trip(w)
    r = c.post(f"/sim/er/cases/{t.id}/actions", json={"action": "bay_assigned", "bay": "A-3"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["type"] == "er_action" and body["source"] == "er_reception" and body["unit"] == "er"
    assert body["state"] == "confirmed" and body["case_id"] == t.id
    assert body["content"] == {"action": "bay_assigned", "bay": "A-3", "team": None}
    assert get_log(w).get(body["seq"]).type == "er_action"

    r = c.post(f"/sim/er/cases/{t.id}/actions", json={"action": "team_activated", "team": "stroke", "note": "CT free"})
    assert r.status_code == 201, r.text
    assert r.json()["content"] == {"action": "team_activated", "bay": None, "team": "stroke"}
    assert r.json()["verbatim"] == "CT free"  # the note is the entry's verbatim text

    assert c.post(f"/sim/er/cases/{t.id}/actions", json={"action": "acknowledge"}).status_code == 201
    card = c.get(f"/sim/er/cases/{t.id}").json()["case"]
    assert card["bay"] == "A-3" and card["teams_activated"] == ["stroke"] and card["acknowledged"] is True


def test_actions_rejects_bad_combinations_with_422_not_500():
    c, w = make()
    t = er_trip(w)
    bad = [
        {"action": "bay_assigned"},  # no bay
        {"action": "bay_assigned", "bay": ""},
        {"action": "team_activated"},  # no team
        {"action": "team_activated", "team": "surgery"},  # not a known team
        {"action": "acknowledge", "team": "surgery"},  # an invalid team is refused whatever the action
        {"action": "dance"},
        {},
        {"action": "acknowledge", "note": "x" * 501},
        {"action": "acknowledge", "client_entry_id": "x" * 65},
    ]
    for body in bad:
        before = mark(w)
        r = c.post(f"/sim/er/cases/{t.id}/actions", json=body)
        assert r.status_code == 422, (body, r.status_code, r.text)
        assert isinstance(r.json()["detail"], list) and r.json()["detail"], body
        assert mark(w) == before, body
    r = c.post(f"/sim/er/cases/{t.id}/actions", json={"action": "bay_assigned"})
    assert any("bay" in item["msg"] for item in r.json()["detail"]), r.json()


def test_a_validation_error_inside_the_handler_becomes_a_422_in_fastapis_shape():
    # The body model already enforces these rules, so this guard is not reachable over HTTP today;
    # pin it directly so a rule added to the stored model but not to the body cannot become a 500.
    base = {"case_id": "TR-1", "unit": "er", "source": "er_reception", "type": "er_action", "state": "confirmed"}
    try:
        ENTRY_IN.validate_python({**base, "content": {"action": "bay_assigned", "bay": None, "team": None}})
    except ValidationError as exc:
        err = _invalid(exc)
    else:
        raise AssertionError("bay_assigned without a bay must not validate")
    assert err.status_code == 422
    assert err.detail == [{"loc": ["body"], "msg": "Value error, bay is required for bay_assigned", "type": "value_error"}]
    json.dumps(err.detail)


def test_actions_on_a_non_er_or_unknown_case_is_404_and_writes_nothing():
    c, w = make()
    onko = non_er_trip(w)
    er_trip(w)
    before = mark(w)
    assert c.post(f"/sim/er/cases/{onko.id}/actions", json={"action": "acknowledge"}).status_code == 404
    assert c.post("/sim/er/cases/TR-9999/actions", json={"action": "acknowledge"}).status_code == 404
    assert mark(w) == before


def test_actions_are_idempotent_per_client_entry_id():
    c, w = make()
    t = er_trip(w)
    body = {"action": "bay_assigned", "bay": "A-3", "client_entry_id": "er-1"}
    r1 = c.post(f"/sim/er/cases/{t.id}/actions", json=body)
    version = w.version
    r2 = c.post(f"/sim/er/cases/{t.id}/actions", json=body)
    assert (r1.status_code, r2.status_code) == (201, 200)
    assert r1.json() == r2.json() and len(get_log(w)) == 1 and w.version == version


# --- POST /clinical/entries/{seq}/confirm ------------------------------------------------------

def test_confirm_endpoint():
    c, w = make()
    t = er_trip(w)
    first = c.post("/sim/clinical/entries", json=entry(t)).json()
    assert first["state"] == "heard"
    r = c.post(f"/sim/clinical/entries/{first['seq']}/confirm", json={"unit": t.vehicle_id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "confirmed" and body["source"] == "crew_tap" and body["unit"] == t.vehicle_id
    assert body["supersedes"] == first["entry_id"] and body["seq"] == 2
    assert body["content"] == first["content"] and body["observed_t"] == first["observed_t"]
    before = mark(w)
    r2 = c.post(f"/sim/clinical/entries/{first['seq']}/confirm", json={"unit": t.vehicle_id})
    assert r2.status_code == 409, r2.text  # already replaced
    assert mark(w) == before
    assert [e["seq"] for e in c.get("/sim/clinical/entries").json()] == [1, 2]


def test_confirm_refuses_unknown_seq_wrong_unit_and_bad_body():
    c, w = make()
    t = er_trip(w)
    first = c.post("/sim/clinical/entries", json=entry(t)).json()
    before = mark(w)
    assert c.post("/sim/clinical/entries/99/confirm", json={"unit": t.vehicle_id}).status_code == 404
    assert c.post("/sim/clinical/entries/0/confirm", json={"unit": t.vehicle_id}).status_code == 404
    assert c.post("/sim/clinical/entries/-1/confirm", json={"unit": t.vehicle_id}).status_code == 404
    assert c.post("/sim/clinical/entries/abc/confirm", json={"unit": t.vehicle_id}).status_code == 422
    assert c.post(f"/sim/clinical/entries/{first['seq']}/confirm", json={"unit": "OTHER"}).status_code == 409
    assert c.post(f"/sim/clinical/entries/{first['seq']}/confirm", json={}).status_code == 422
    assert c.post(f"/sim/clinical/entries/{first['seq']}/confirm", json={"unit": ""}).status_code == 422
    assert c.post(f"/sim/clinical/entries/{first['seq']}/confirm", json={"unit": t.vehicle_id, "source": "bogus"}).status_code == 422
    assert mark(w) == before


def test_confirm_takes_an_explicit_source():
    c, w = make()
    t = er_trip(w)
    first = c.post("/sim/clinical/entries", json=entry(t)).json()
    r = c.post(f"/sim/clinical/entries/{first['seq']}/confirm", json={"unit": t.vehicle_id, "source": "crew_voice"})
    assert r.status_code == 200 and r.json()["source"] == "crew_voice" and r.json()["state"] == "confirmed"


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
