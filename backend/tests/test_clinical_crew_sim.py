"""The crew simulator: a client that plays a crew and the dispatcher's triage through the public API.

Run from backend/:  python tests/test_clinical_crew_sim.py   (or: python -m pytest tests)
Offline and self-contained. The planning tests feed hand-made snapshots to crew_sim.plan_entries; the
end-to-end tests give each test its own fresh world mounted as "sim" on its own FastAPI app, so none of
them imports app.main or touches main.sim / main.live. crew_sim itself imports nothing from app.*
(test_crew_sim_never_imports_the_server); only these tests do, to validate what it sends.
"""
from __future__ import annotations

import clinical_helpers  # noqa: F401  (must be first: sets the offline env, puts backend/ on sys.path)

import ast
import io
import json
import sys
import time
import traceback
import types
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))  # crew_sim is a script under backend/tools, not part of the app package

import crew_sim  # noqa: E402
from app.clinical.api import mount  # noqa: E402
from app.clinical.models import ENTRY_IN  # noqa: E402
from clinical_helpers import drive, er_trip, fresh_world  # noqa: E402

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
MIN = timedelta(minutes=1)


# --- hand-made snapshots -----------------------------------------------------------------------

def trip_dict(**overrides) -> dict:
    """A trip as the snapshot serialises it: an emergency stroke call on its way to the ER, onboard since T0."""
    trip = {
        "id": "TR-100",
        "kind": "patient",
        "priority": "emergency",
        "note": "suspected stroke",
        "status": "onboard",
        "vehicle_id": "A1",
        "dropoff_id": "ukc",
        "eta_pickup": T0.isoformat(),
        "eta_dropoff": (T0 + 20 * MIN).isoformat(),
    }
    trip.update(overrides)
    return trip


def snapshot(*trips: dict, now: datetime = T0) -> dict:
    return {"sim_time": now.isoformat(), "trips": list(trips), "vehicles": [], "clinical": {"cases": []}}


def types_of(plan: list[dict]) -> list[str]:
    return [item["json"]["type"] for item in plan]


def ids_of(plan: list[dict]) -> list[str]:
    return [item["json"]["client_entry_id"] for item in plan]


def a_busy_snapshot() -> dict:
    """Onboard, arrived and just-assigned ER trips together: every kind of entry shows up somewhere."""
    onboard = trip_dict(id="TR-1")
    urgent = trip_dict(id="TR-2", priority="urgent", note="fall on the stairs, hip pain", status="assigned", eta_pickup=None, eta_dropoff=None)
    arrived = trip_dict(id="TR-3", status="completed", eta_pickup=(T0 - 30 * MIN).isoformat(), eta_dropoff=(T0 - 20 * MIN).isoformat())
    return snapshot(onboard, urgent, arrived, now=T0 + 12 * MIN)


# --- the plan ----------------------------------------------------------------------------------

def test_plan_is_deterministic_and_every_payload_validates():
    snap = a_busy_snapshot()
    a = crew_sim.plan_entries(snap, set())
    b = crew_sim.plan_entries(snap, set())
    assert a and a == b
    assert all(i["path"] == "/clinical/entries" for i in a)
    assert all(ENTRY_IN.validate_python(i["json"]) for i in a)
    ids = ids_of(a)
    assert all(ids) and len(ids) == len(set(ids)), "every client_entry_id is present and unique"
    assert all("observed_t" not in i["json"] for i in a), "the server stamps observed_t"
    kinds = set(types_of(a))
    assert {"triage", "patient_info", "severity", "vitals", "drug_administered", "event", "handover", "free"} <= kinds


def test_already_sent_entries_are_not_planned_again():
    snap = a_busy_snapshot()
    plan = crew_sim.plan_entries(snap, set())
    assert crew_sim.plan_entries(snap, set(ids_of(plan))) == []
    first, rest = plan[0], plan[1:]
    assert crew_sim.plan_entries(snap, {ids_of(plan)[0]}) == rest and first not in rest


def test_simulator_posts_nothing_for_equipment_or_non_er_trips():
    equipment = trip_dict(id="EQ-1", kind="equipment", note="mobile ECG monitor")
    onko = trip_dict(id="TR-5", dropoff_id="onko", note="transfer")
    assert crew_sim.plan_entries(snapshot(equipment, onko, now=T0 + 30 * MIN), set()) == []


def test_simulator_posts_nothing_for_unassigned_cancelled_or_vehicleless_trips():
    unassigned = trip_dict(id="TR-6", status="unassigned", vehicle_id=None, eta_pickup=None, eta_dropoff=None)
    cancelled = trip_dict(id="TR-7", status="cancelled")  # a cancelled trip keeps the vehicle it had
    no_vehicle = trip_dict(id="TR-8", status="assigned", vehicle_id=None)
    assert crew_sim.plan_entries(snapshot(unassigned, cancelled, no_vehicle, now=T0 + 30 * MIN), set()) == []


def test_nothing_is_posted_for_a_trip_before_it_has_a_vehicle_and_triage_comes_first():
    waiting = trip_dict(status="unassigned", vehicle_id=None, eta_pickup=None, eta_dropoff=None)
    assert crew_sim.plan_entries(snapshot(waiting), set()) == []

    assigned = trip_dict(status="assigned", eta_pickup=(T0 + 6 * MIN).isoformat())  # vehicle named, not yet at the patient
    plan = crew_sim.plan_entries(snapshot(assigned), set())
    assert types_of(plan) == ["triage"], "before pickup only the dispatcher's triage is possible"
    triage = plan[0]["json"]
    assert (triage["unit"], triage["source"], triage["state"]) == ("dispatch", "dispatcher", "confirmed")
    assert triage["case_id"] == "TR-100" and triage["content"] == {"level": "red", "problem_type": "stroke"}
    assert triage["client_entry_id"] == "sim-TR-100-triage"

    onboard = crew_sim.plan_entries(snapshot(trip_dict(), now=T0 + 7 * MIN), set())
    assert types_of(onboard)[0] == "triage" and len(onboard) > 1, "triage leads, the crew entries follow"
    for item in onboard[1:]:
        j = item["json"]
        assert (j["unit"], j["source"], j["state"], j["case_id"]) == ("A1", "simulated_crew", "heard", "TR-100")


def test_triage_level_follows_priority():
    red = crew_sim.plan_entries(snapshot(trip_dict(priority="emergency", status="assigned")), set())
    yellow = crew_sim.plan_entries(snapshot(trip_dict(priority="urgent", status="assigned")), set())
    scheduled = crew_sim.plan_entries(snapshot(trip_dict(priority="scheduled", status="assigned")), set())
    assert red[0]["json"]["content"]["level"] == "red"
    assert yellow[0]["json"]["content"]["level"] == "yellow"
    assert scheduled == [], "no triage for a scheduled transport"


def test_problem_type_comes_from_a_keyword_table_over_the_note():
    expected = {
        "suspected stroke": "stroke",
        "face drooping, slurred speech": "stroke",
        "chest pain": "chest_pain",
        "crushing chest pain, sweating": "chest_pain",
        "severe breathing difficulty": "breathing_difficulty",
        "head injury": "severe_head_injury",
        "skier collision, head injury": "severe_head_injury",
        "traffic accident, injured driver": "polytrauma",
        "fall from height": "polytrauma",
        "unconscious, not breathing; caller instructed in CPR": "resuscitation",
        "allergic reaction": "other",
        "seizure still going on": "other",
        "unconscious": "other",
        "something nobody planned for": "other",
        "": "other",
        None: "other",
    }
    for note, problem in expected.items():
        plan = crew_sim.plan_entries(snapshot(trip_dict(status="assigned", note=note)), set())
        assert plan[0]["json"]["content"]["problem_type"] == problem, (note, problem)


# --- what the crew posts once the patient is onboard -------------------------------------------

def test_patient_info_and_severity_are_posted_once_with_deterministic_values():
    plan = crew_sim.plan_entries(snapshot(trip_dict(), now=T0 + 3 * MIN), set())
    info = [i["json"] for i in plan if i["json"]["type"] == "patient_info"]
    assert len(info) == 1 and info[0]["client_entry_id"] == "sim-TR-100-patient_info"
    assert 18 <= info[0]["content"]["age_years"] <= 90 and info[0]["content"]["sex"] in ("f", "m")
    sev = [i["json"]["content"]["value"] for i in plan if i["json"]["type"] == "severity"]
    assert sev == ["orange"]
    again = crew_sim.plan_entries(snapshot(trip_dict(), now=T0 + 3 * MIN), set())
    assert plan == again
    urgent = crew_sim.plan_entries(snapshot(trip_dict(priority="urgent", note="fall on the stairs, hip pain"), now=T0 + 3 * MIN), set())
    assert [i["json"]["content"]["value"] for i in urgent if i["json"]["type"] == "severity"] == ["green"]
    # Two trips differ: the values really come from the trip, not from a constant.
    infos = {
        tuple(sorted(j["content"].items()))
        for j in (
            next(i["json"] for i in crew_sim.plan_entries(snapshot(trip_dict(id=f"TR-{n}"), now=T0 + 3 * MIN), set()) if i["json"]["type"] == "patient_info")
            for n in range(20)
        )
    }
    assert len(infos) > 5


def test_vitals_follow_the_five_minute_schedule_since_pickup():
    assert crew_sim.VITALS_EVERY_MIN == 5

    def vitals_ids(minutes: float) -> list[str]:
        plan = crew_sim.plan_entries(snapshot(trip_dict(), now=T0 + minutes * MIN), set())
        return [i for i in ids_of(plan) if "-vitals-" in i]

    assert vitals_ids(0) == ["sim-TR-100-vitals-1"], "the first set is taken at pickup"
    assert vitals_ids(4.9) == ["sim-TR-100-vitals-1"]
    assert vitals_ids(5) == ["sim-TR-100-vitals-1", "sim-TR-100-vitals-2"]
    assert vitals_ids(12) == [f"sim-TR-100-vitals-{n}" for n in (1, 2, 3)]
    # Not while the unit is still driving to the patient, nor once the patient has arrived.
    assert vitals_ids(0) and not [i for i in ids_of(crew_sim.plan_entries(snapshot(trip_dict(status="en_route_pickup")), set())) if "-vitals-" in i]
    done = trip_dict(status="completed", eta_dropoff=(T0 + 8 * MIN).isoformat())
    assert not [i for i in ids_of(crew_sim.plan_entries(snapshot(done, now=T0 + 9 * MIN), set())) if "-vitals-" in i]


def test_vitals_drift_but_stay_plausible_and_in_the_server_schema():
    readings = []
    for n in range(1, 40):
        plan = crew_sim.plan_entries(snapshot(trip_dict(id="TR-9"), now=T0 + (n - 1) * 5 * MIN), set())
        vitals = [i["json"] for i in plan if i["json"]["client_entry_id"] == f"sim-TR-9-vitals-{n}"]
        assert len(vitals) == 1
        readings.append(vitals[0]["content"])
        assert set(vitals[0]["content"]) == {"hr", "sbp", "dbp", "spo2", "rr", "gcs"}
    from app.clinical import config

    for content in readings:
        for name, value in content.items():
            low, high = config.PLAUSIBLE[name]
            assert low <= value <= high, (name, value)
    assert len({tuple(sorted(c.items())) for c in readings}) > 20, "readings change from one set to the next"


def test_one_drug_for_emergencies_only_and_after_the_first_vitals():
    plan = crew_sim.plan_entries(snapshot(trip_dict(), now=T0 + 12 * MIN), set())
    drugs = [i["json"] for i in plan if i["json"]["type"] == "drug_administered"]
    assert len(drugs) == 1 and drugs[0]["client_entry_id"] == "sim-TR-100-drug"
    assert all(drugs[0]["content"][k] for k in ("drug", "dose", "route"))
    ids = ids_of(plan)
    assert ids.index("sim-TR-100-vitals-1") < ids.index("sim-TR-100-drug")
    assert not [i for i in types_of(crew_sim.plan_entries(snapshot(trip_dict(priority="urgent"), now=T0 + 12 * MIN), set())) if i == "drug_administered"]
    assert not [i for i in types_of(crew_sim.plan_entries(snapshot(trip_dict(priority="scheduled"), now=T0 + 12 * MIN), set())) if i == "drug_administered"]


def test_stroke_onset_is_forty_minutes_before_pickup_for_stroke_notes_only():
    plan = crew_sim.plan_entries(snapshot(trip_dict(), now=T0 + 1 * MIN), set())
    onsets = [i["json"] for i in plan if i["json"]["type"] == "event" and i["json"]["content"]["kind"] == "stroke_onset"]
    assert len(onsets) == 1 and onsets[0]["client_entry_id"] == "sim-TR-100-stroke_onset"
    onset = datetime.fromisoformat(onsets[0]["content"]["onset_t"])
    assert onset.tzinfo is not None and onset == T0 - 40 * MIN
    chest = crew_sim.plan_entries(snapshot(trip_dict(note="chest pain"), now=T0 + 1 * MIN), set())
    assert not [i for i in chest if i["json"]["type"] == "event" and i["json"]["content"]["kind"] == "stroke_onset"]


def arrest_kinds(trip_id: str, minutes: float, priority: str = "emergency") -> list[str]:
    """The event kinds planned for a trip id at `minutes` after pickup (stroke onset left out)."""
    plan = crew_sim.plan_entries(snapshot(trip_dict(id=trip_id, priority=priority, note="chest pain"), now=T0 + minutes * MIN), set())
    return [i["json"]["content"]["kind"] for i in plan if i["json"]["type"] == "event"]


def test_one_in_six_emergencies_arrest_then_rosc():
    ids = [f"TR-{n}" for n in range(600)]
    arresting = [t for t in ids if "arrest" in arrest_kinds(t, 12)]
    assert 70 <= len(arresting) <= 130, f"expected about one in six of 600, got {len(arresting)}"
    for trip_id in arresting[:10]:
        assert arrest_kinds(trip_id, 0) == ["arrest"], "the arrest comes with the first vitals"
        assert arrest_kinds(trip_id, 4.9) == ["arrest"], "and ROSC not before the second"
        assert arrest_kinds(trip_id, 5) == ["arrest", "rosc"]
        plan = crew_sim.plan_entries(snapshot(trip_dict(id=trip_id, note="chest pain"), now=T0 + 5 * MIN), set())
        found = [i["json"]["client_entry_id"] for i in plan if i["json"]["type"] == "event"]
        assert found == [f"sim-{trip_id}-arrest", f"sim-{trip_id}-rosc"]
        assert all(ENTRY_IN.validate_python(i["json"]) for i in plan), "arrest and rosc are valid server entries"
    assert all(arrest_kinds(t, 12) == [] for t in ids if t not in arresting)
    assert all("rosc" in arrest_kinds(t, 12) for t in arresting)
    assert not [t for t in ids if arrest_kinds(t, 12, priority="urgent")], "an arrest is for emergencies only"
    assert arrest_kinds(arresting[0], 12) == arrest_kinds(arresting[0], 12), "the same trip always decides the same way"


# --- after arrival -----------------------------------------------------------------------------

def test_handover_and_free_timing_constants():
    # assumption: handover takes 10-15 min, docs/OPERATIONS_DETAILS.md; all in world minutes
    assert (crew_sim.VITALS_EVERY_MIN, crew_sim.HANDOVER_AFTER_MIN, crew_sim.FREE_AFTER_MIN) == (5, 10, 15)
    arrived = trip_dict(status="completed", eta_pickup=(T0 - 15 * MIN).isoformat(), eta_dropoff=T0.isoformat())

    def after_arrival(minutes: float) -> list[str]:
        return types_of(crew_sim.plan_entries(snapshot(arrived, now=T0 + minutes * MIN), set()))

    assert after_arrival(0) == ["triage"]
    assert after_arrival(9) == ["triage"], "no handover yet at +9 minutes"
    assert after_arrival(9.9) == ["triage"]
    assert after_arrival(10) == ["triage", "handover"]
    assert after_arrival(14.9) == ["triage", "handover"], "free only at +15"
    assert after_arrival(15) == ["triage", "handover", "free"]
    plan = crew_sim.plan_entries(snapshot(arrived, now=T0 + 15 * MIN), set())
    assert ids_of(plan) == ["sim-TR-100-triage", "sim-TR-100-handover", "sim-TR-100-free"]
    for item in plan[1:]:
        assert (item["json"]["unit"], item["json"]["source"], item["json"]["state"]) == ("A1", "simulated_crew", "heard")
        assert item["json"]["content"]["note"]


# --- run_once and main -------------------------------------------------------------------------

def test_run_once_posts_in_order_counts_and_remembers_what_it_sent():
    snap = a_busy_snapshot()
    posted: list[tuple[str, dict]] = []
    sent: set[str] = set()
    asked: list[str] = []

    def get(path):
        asked.append(path)
        return snap

    n = crew_sim.run_once(get, lambda path, body: posted.append((path, body)), sent)
    assert asked == ["/state"]
    assert n == len(posted) == len(crew_sim.plan_entries(snap, set())) and n > 0
    assert sent == {body["client_entry_id"] for _, body in posted}
    assert all(path == "/clinical/entries" for path, _ in posted)
    assert crew_sim.run_once(get, lambda path, body: posted.append((path, body)), sent) == 0
    assert len(posted) == n


def test_a_failed_post_raises_and_is_planned_again_next_time():
    snap = snapshot(trip_dict(), now=T0 + 6 * MIN)
    sent: set[str] = set()
    calls = []

    def flaky(path, body):
        calls.append(body["client_entry_id"])
        if len(calls) == 3:
            raise RuntimeError("503 from the server")

    try:
        crew_sim.run_once(lambda p: snap, flaky, sent)
    except RuntimeError as exc:
        assert "503" in str(exc)
    else:
        raise AssertionError("a failed post must raise, not be swallowed")
    assert sent == set(calls[:2]), "only what was really posted is remembered"
    assert crew_sim.run_once(lambda p: snap, lambda path, body: None, sent) == len(crew_sim.plan_entries(snap, set())) - 2


def test_crew_sim_never_imports_the_server():
    tree = ast.parse((TOOLS / "crew_sim.py").read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(("." * node.level) + (node.module or ""))
    assert imported, "the script has imports"
    assert not [m for m in imported if m == "app" or m.startswith("app.") or m.startswith(".")], imported


# --- end to end through the real routes --------------------------------------------------------

def make():
    """(client, world) for a fresh world mounted as "sim" on its own app; never main.sim / main.live."""
    w = fresh_world()
    app = FastAPI()
    mount(app, {"sim": w})

    @app.get("/sim/state")  # stands in for main.py's /{world}/state route (same body: the world's snapshot)
    def state() -> dict:
        return w.snapshot()

    return TestClient(app), w


def wire(client: TestClient, w, statuses: list[int]):
    """The get/post callables run_once takes, over the world and the real routes."""

    def get(path):
        assert path == "/state"
        return json.loads(json.dumps(w.snapshot()))

    def post(path, body):
        response = client.post(f"/sim{path}", json=body)
        statuses.append(response.status_code)
        assert 200 <= response.status_code < 300, (response.status_code, response.text, body)

    return get, post


def test_end_to_end_through_the_real_routes():
    client, w = make()
    t = er_trip(w)  # an emergency call to the ER; a vehicle is dispatched at once
    assert t.vehicle_id and t.priority == "emergency" and t.dropoff_id == "ukc"
    statuses: list[int] = []
    get, post = wire(client, w, statuses)
    sent: set[str] = set()
    arrived_at = None
    for _ in range(120):
        drive(w, 1)
        crew_sim.run_once(get, post, sent)
        trip = w.trips[t.id]
        if arrived_at is None and trip.status == "completed":
            arrived_at = trip.eta_dropoff
        if arrived_at is not None and w.sim_time >= arrived_at + 20 * MIN:
            break
    else:
        raise AssertionError("the trip never completed and aged 20 minutes within two world-hours")

    assert statuses and all(s in (200, 201) for s in statuses)
    board = client.get("/sim/er/board").json()
    card = next(c for c in board["cases"] if c["case_id"] == t.id)
    assert card["vitals"], "the card shows vitals"
    assert all(isinstance(v["age_min"], (int, float)) for v in card["vitals"].values())
    assert card["treatments"], "an emergency has a recorded treatment"
    assert card["stage"] == "PROST" and card["stage_inferred"] is False
    assert card["level"]["inferred"] is False and card["level"]["value"] == "red" and card["level"]["source"] == "dispatcher"
    assert card["problem"]["type"] == "stroke"
    assert card["age_years"] is not None and card["sex"] in ("f", "m") and card["severity"] == "orange"
    assert "stroke_onset" in [e["kind"] for e in card["events"]]

    log = client.get("/sim/clinical/entries", params={"case_id": t.id, "limit": 2000}).json()
    assert len(log) == len(sent) == len(statuses)
    assert all(e["source"] in ("simulated_crew", "dispatcher") and not e["needs_check"] for e in log)
    assert crew_sim.run_once(get, post, sent) == 0, "everything is already sent"
    assert len(client.get("/sim/clinical/entries", params={"limit": 2000}).json()) == len(log)


def test_a_restarted_simulator_replays_harmlessly():
    client, w = make()
    t = er_trip(w)
    statuses: list[int] = []
    get, post = wire(client, w, statuses)
    drive(w, 1, until=lambda: w.trips[t.id].status == "onboard")
    drive(w, 6)
    first = crew_sim.run_once(get, post, set())
    assert first > 0 and set(statuses) == {201}
    statuses.clear()
    before = len(client.get("/sim/clinical/entries", params={"limit": 2000}).json())
    replay = crew_sim.run_once(get, post, set())  # a new process knows nothing about what the old one sent
    assert replay == first and set(statuses) == {200}, "the server answers 200 for each duplicate"
    assert len(client.get("/sim/clinical/entries", params={"limit": 2000}).json()) == before


def test_main_loops_prints_one_line_per_cycle_and_exits_cleanly_on_ctrl_c():
    client, w = make()
    t = er_trip(w)
    cycles = {"n": 0}
    naps: list[float] = []

    def nap(seconds):
        naps.append(seconds)
        cycles["n"] += 1
        if cycles["n"] >= 4:
            raise KeyboardInterrupt
        drive(w, 3)

    real_httpx, real_time = crew_sim.httpx, crew_sim.time
    crew_sim.httpx = types.SimpleNamespace(Client=lambda **kw: client, HTTPError=real_httpx.HTTPError)
    crew_sim.time = types.SimpleNamespace(sleep=nap)
    out = io.StringIO()
    try:
        with redirect_stdout(out):
            code = crew_sim.main(["--base", "http://testserver", "--world", "sim", "--interval", "0.5"])
    finally:
        crew_sim.httpx, crew_sim.time = real_httpx, real_time
    assert code in (0, None)
    assert naps == [0.5] * 4
    lines = [ln for ln in out.getvalue().splitlines() if ln.strip()]
    assert len(lines) >= 4, out.getvalue()
    assert len(client.get("/sim/clinical/entries", params={"case_id": t.id}).json()) > 0, "main really posted through the routes"
    assert any(ln.startswith("posted ") and ln.split()[1].isdigit() and int(ln.split()[1]) > 0 for ln in lines), out.getvalue()


def test_main_defaults_and_flags():
    import argparse

    parser = crew_sim.build_parser()
    assert isinstance(parser, argparse.ArgumentParser)
    args = parser.parse_args([])
    assert (args.base, args.world, args.interval) == ("http://localhost:8000", "sim", 2.0)
    args = parser.parse_args(["--base", "http://x:1", "--world", "live", "--interval", "5"])
    assert (args.base, args.world, args.interval) == ("http://x:1", "live", 5.0)


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
