"""Doctor cars (VUZ) and reserve units (mutual aid, private ambulances).

Run from backend/:  python tests/test_doctors.py   (or: python -m pytest tests)
Offline: road routing off, no Claude. Live-calls mode, calls generator off.

- Red calls with a condition that needs a doctor get the ambulance by the dispatch rules and the doctor
  car that reaches the scene first; the doctor car never transports a patient, stays on scene with the
  crew, escorts the ambulance to hospital, then returns home.
- The helicopter has a doctor on board: a call it serves needs no doctor car (unless the helicopter is
  over the 15-min reference and a car is there sooner; it stands down when the helicopter lifts off).
- Reserve units (M1 mutual aid, P1 private) are not in the world until an approved plan requests one;
  then they serve the call and leave again once home.
"""
from __future__ import annotations

import logging
import os
import random
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ["ROAD_ROUTING"] = "0"
os.environ["AGENT_AUTO"] = "0"
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, demo, main  # noqa: E402
from app.agent import runner  # noqa: E402
from app.agent.context import build_situation, tool_find_candidates  # noqa: E402
from app.engine.actions import ActionError, assign_trip, can_serve  # noqa: E402
from app.engine.candidates import find_candidates  # noqa: E402
from app.engine.events import apply_event  # noqa: E402
from app.engine.projection import project_all  # noqa: E402
from app.engine.severity import CONDITIONS, DOCTOR_CONDITIONS, needs_doctor  # noqa: E402
from app.models import AgentRun, BreakdownEvent, Plan, PlanStep, Trip, UrgentRequestEvent, utcnow  # noqa: E402
from app.sim.calls import build_call  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402
from app.sim.simulator import tick  # noqa: E402

for noisy in ("httpx", "httpx2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
client = TestClient(main.app)
W = main.sim


DAY = datetime(2026, 11, 23, 9, 0, tzinfo=ZoneInfo("Europe/Ljubljana"))  # fixed clock, by day: the helicopter flies 08:00-16:30


def fresh() -> None:
    seed_world(W, config.RANDOM_SEED, scheduled_day=False, start=DAY)
    W.auto_analyze = False
    W.calls.enabled = False


def run(minutes: float, until=None, step_s: float = 15) -> bool:
    for _ in range(int(minutes * 60 / step_s)):
        tick(W, step_s)
        project_all(W)
        if until and until():
            return True
    return False


def call(lat: float, lon: float, severity: str, condition: str, modifiers: list[str] | None = None):
    priority = "urgent" if severity == "urgent" else "emergency"
    rec = apply_event(W, UrgentRequestEvent(type="urgent_request", lat=lat, lon=lon, place_name="call", priority=priority,  # type: ignore[arg-type]
                                            severity=severity, condition=condition, modifiers=modifiers or []))  # type: ignore[arg-type]
    return rec, W.trips[rec.affected_trip_ids[0]]


def near(place: str, dlat: float = 0.0, dlon: float = 0.0) -> tuple[float, float]:
    p = W.places[place]
    return round(p.lat + dlat, 5), round(p.lon + dlon, 5)


# --- Who needs a doctor -------------------------------------------------------------------------


def test_needs_doctor_by_condition_and_generator_share():
    yes = {"cardiac_arrest", "choking", "catastrophic_bleeding", "anaphylaxis", "stemi", "breathing_difficulty", "major_trauma"}
    assert DOCTOR_CONDITIONS == yes
    for code, (_, level, _, _) in CONDITIONS.items():
        assert needs_doctor("patient", level, code) == (code in yes), code
    assert not needs_doctor("equipment", "serious", "stemi")  # cargo never needs a doctor
    fresh()
    t = Trip(id="X", patient="P", priority="emergency", condition="stemi", needs="stretcher", pickup_id="home_moste",
             dropoff_id="ukc", pickup_after=W.sim_time, due_by=W.sim_time + timedelta(minutes=60))
    assert t.needs_doctor and t.doctor_target_min == 15 and t.doctor_vehicle_id is None
    s = Trip(id="Y", patient="P", priority="emergency", condition="stroke", needs="stretcher", pickup_id="home_moste",
             dropoff_id="ukc", pickup_after=W.sim_time, due_by=W.sim_time + timedelta(minutes=60))
    assert not s.needs_doctor and s.doctor_target_min is None  # stroke: the stroke centre matters more
    # The generated calls: about a quarter of the red calls need a doctor (Slovenian dispatch: 10-30 %).
    rng, red, doctor = random.Random(3), 0, 0
    for _ in range(6000):
        ev = build_call(W, rng)
        if ev.type == "urgent_request" and ev.severity in ("critical", "serious"):
            red += 1
            doctor += needs_doctor("patient", ev.severity, ev.condition)
    assert 0.18 <= doctor / red <= 0.32, doctor / red


def test_catalogue_messages_are_graded_and_chest_pain_gets_a_doctor():
    """Field messages from the catalogue (docs/SURGE_EVENTS.md section 4 on branch Metelko): the keyword
    grading fills what the model leaves out, and a chest-pain call gets a doctor car."""
    from app.agent.messages import ParsedMessage, grade_text, to_operator_events

    assert grade_text("Še en nujen klic: bolečina v prsih v Črnučah.")[:2] == ("stemi", "serious")
    assert grade_text("Klic: padec na ledu v Šiški, sum na zlom kolka.")[:2] == ("fracture", "urgent")
    assert grade_text("Zaradi kolone zamujamo približno petindvajset minut.") == (None, None, [])
    fresh()
    text = "Še en nujen klic: bolečina v prsih v Črnučah."
    raw = {"type": "urgent_request", "pickup_place_id": "home_crnuce", "lat": None, "lon": None, "dropoff_id": "",
           "needs": "stretcher", "priority": "emergency", "severity": None, "condition": None, "modifiers": [], "note": ""}
    (ev,) = to_operator_events(W, ParsedMessage(understood_sl="x", understood_en="x", events=[raw]), text)
    assert (ev.severity, ev.condition) == ("serious", "stemi")
    rec = apply_event(W, ev)
    t = W.trips[rec.affected_trip_ids[0]]
    assert t.needs_doctor and t.doctor_vehicle_id in ("D1", "D2") and "+ doctor" in rec.summary, rec.summary


# --- Doctor car dispatch and cycle ---------------------------------------------------------------


def test_doctor_car_goes_with_the_ambulance_and_escorts_then_returns():
    fresh()
    rec, t = call(*near("home_bezigrad", 0.004, 0.002), "serious", "stemi")
    assert t.vehicle_id in ("A1", "A2", "A3") and t.doctor_vehicle_id in ("D1", "D2"), rec.summary
    d = W.vehicles[t.doctor_vehicle_id]
    assert f"+ doctor {d.id} (" in rec.summary, rec.summary
    assert any(f"{x} the ambulance" in rec.summary for x in ("after", "before", "with")), rec.summary
    assert d.status == "to_pickup" and d.current_trip_id == t.id and t.doctor_eta is not None
    assert not d.queue and t.vehicle_id != d.id  # it supports the call; the ambulance carries the patient
    nav = client.get(f"/sim/vehicles/{d.id}/navigation").json()  # the tablet in the doctor car
    assert nav["target"]["kind"] == "pickup" and nav["target"]["trip_id"] == t.id, nav
    seen = []
    def follow():
        if not seen or seen[-1] != d.status:
            seen.append(d.status)
        return t.status == "completed" and d.status == "idle"
    assert run(120, until=follow), (seen, t.status, d.status)
    assert seen[:1] == ["to_pickup"] and "with_patient" in seen and seen[-1] == "idle", seen
    assert "loading" in seen or seen.index("with_patient") == 1, seen  # on scene with the crew (unless it came late)
    assert t.vehicle_id != d.id and d.current_trip_id is None
    base = W.places[d.base_id]
    assert abs(d.lat - base.lat) < 1e-4 and abs(d.lon - base.lon) < 1e-4  # back at its base


def test_doctor_car_is_never_a_transport_unit():
    fresh()
    _, t = call(*near("home_moste", 0.002, 0.002), "critical", "cardiac_arrest")
    d = W.vehicles[t.doctor_vehicle_id]
    ok, why = can_serve(d, t)
    assert not ok and "never transports" in why
    assert all(c["vehicle_type"] != "doctor" for c in find_candidates(W, t.id, limit=50))
    try:
        assign_trip(W, t.id, d.id)
        raise AssertionError("a doctor car took a patient")
    except ActionError:
        pass


def test_a_doctor_car_on_scene_is_not_pulled_away():
    fresh()
    _, first = call(*near("home_moste", 0.002, 0.002), "serious", "breathing_difficulty")
    d = W.vehicles[first.doctor_vehicle_id]
    assert run(30, until=lambda: d.status == "loading"), d.status  # on scene with the crew
    other = next(v for v in W.vehicles.values() if v.type == "doctor" and v.id != d.id)
    other.status = "out_of_service"
    rec, second = call(*near("home_siska", 0.002, 0.002), "critical", "choking", ["child"])
    assert second.doctor_vehicle_id is None and d.current_trip_id == first.id, rec.summary
    assert "no doctor car free" in rec.summary and "helicopter" in rec.summary, rec.summary
    alert = next(a for a in W.alerts if a.kind == "doctor_response_over_15_min")  # the UI shows it per call
    assert alert.trip_id == second.id and "No doctor" in alert.message, alert


def test_no_doctor_car_for_calls_that_do_not_need_one():
    fresh()
    rec, t = call(*near("home_polje"), "serious", "stroke")
    assert not t.needs_doctor and t.doctor_vehicle_id is None and "doctor" not in rec.summary, rec.summary
    assert all(v.current_trip_id is None for v in W.vehicles.values() if v.type == "doctor")


def test_helicopter_has_a_doctor_on_board():
    fresh()
    rec, t = call(46.3085, 14.5910, "serious", "major_trauma")  # Kamniška Bistrica: H1 flies
    assert t.vehicle_id == "H1" and t.doctor_vehicle_id == "H1", rec.summary
    assert "doctor on board" in rec.summary and "+ doctor D" not in rec.summary, rec.summary
    assert all(v.current_trip_id is None for v in W.vehicles.values() if v.type == "doctor")
    assert t.doctor_eta == t.eta_pickup


def test_plan_moving_a_call_to_the_helicopter_stands_the_doctor_car_down():
    # A remote call sent by road (the helicopter was out of service): the doctor car needs ~45 min.
    fresh()
    W.vehicles["H1"].status = "out_of_service"
    _, t = call(46.3085, 14.5910, "serious", "major_trauma")  # Kamniška Bistrica
    d = W.vehicles[t.doctor_vehicle_id]
    W.vehicles["H1"].status = "idle"  # back at Brnik: about 20 min with its activation
    record = main.apply_plan(W, Plan(steps=[PlanStep(trip_id=t.id, vehicle_id="H1")]))
    assert t.vehicle_id == "H1" and t.doctor_vehicle_id == "H1", record.summary
    assert d.current_trip_id is None and d.status == "returning"
    # In the city the helicopter needs 13 min to take off at Brnik alone, so it is past the 15-min
    # doctor reference: the doctor car that is there sooner stays.
    fresh()
    _, t = call(*near("home_bezigrad", 0.004, 0.002), "serious", "stemi")
    d = W.vehicles[t.doctor_vehicle_id]
    record = main.apply_plan(W, Plan(steps=[PlanStep(trip_id=t.id, vehicle_id="H1")]))
    assert t.vehicle_id == "H1" and t.doctor_vehicle_id == d.id and d.current_trip_id == t.id, record.summary


def test_doctor_car_breakdown_sends_another_and_the_ambulance_keeps_the_call():
    fresh()
    _, t = call(*near("home_bezigrad", 0.004, 0.002), "serious", "stemi")
    amb, first = t.vehicle_id, t.doctor_vehicle_id
    rec = apply_event(W, BreakdownEvent(type="breakdown", vehicle_id=first, note="flat tyre"))
    assert t.vehicle_id == amb and t.status != "unassigned", rec.summary
    assert t.doctor_vehicle_id not in (None, first) and "+ doctor" in rec.summary, rec.summary


# --- Reserve units: mutual aid, private ambulance -----------------------------------------------


def test_nothing_free_offers_mutual_aid_and_a_private_ambulance():
    r = client.post("/sim/admin/scenario/nothing_free")
    assert r.status_code == 200, r.text
    summary = W.events[-1].summary
    t = W.trips[W.events[-1].affected_trip_ids[0]]
    assert t.severity == "critical" and "can request M1" in summary and "P1" in summary, summary
    assert t.doctor_vehicle_id in ("D1", "D2") and "+ doctor" in summary, summary  # the doctor car goes at once
    snap = client.get("/sim/state").json()
    assert not {"M1", "P1"} & {v["id"] for v in snap["vehicles"]}  # not in the world before a request
    assert any(a["kind"] == "red_response_over_15_min" and a["trip_id"] == t.id for a in snap["alerts"])
    situation = build_situation(W)
    assert {u["id"] for u in situation["reserve_units"]} == {"M1", "P1"}
    trip_view = next(x for x in situation["open_trips"] if x["id"] == t.id)
    assert trip_view["needs_doctor"] and trip_view["doctor"] == t.doctor_vehicle_id
    cands = tool_find_candidates(W, t.id)["candidates"]
    assert any(c["vehicle_id"] == "M1" and c["vehicle_origin"] == "mutual_aid" for c in cands)
    assert all(c["vehicle_id"] not in ("M1", "P1") for c in find_candidates(W, t.id, limit=50))  # the engine never does
    rec = runner._engine_recommendation(W, W.events[-1], "test", W.pending_question)
    titles = [o.title for o in rec.options]
    assert any(x.startswith("Request mutual aid: M1 from Domžale, at the patient") for x in titles), titles
    assert any(x.startswith("Private ambulance P1 (Brezovica), at the patient") for x in titles), titles


def test_approving_mutual_aid_activates_the_unit_which_leaves_once_home():
    client.post("/sim/admin/scenario/nothing_free")
    t = W.trips[W.events[-1].affected_trip_ids[0]]
    rec = runner._engine_recommendation(W, W.events[-1], "test", W.pending_question)
    i = next(i for i, o in enumerate(rec.options) if o.title.startswith("Request mutual aid: M1"))
    run_ = AgentRun(id=W.new_id("RUN"), trigger="test", started_at=utcnow())
    W.agent_runs.append(run_)
    runner._finish(W, run_, rec, engine="engine")
    assert rec.options[i].feasible and "M1 (mutual aid, requested) goes now" in rec.options[i].step_details[0]["text"]
    r = client.post(f"/sim/agent/runs/{run_.id}/approve", json={"option_index": i})
    assert r.status_code == 200, r.text
    m1 = W.vehicles["M1"]
    assert "M1" not in W.reserve_vehicles and m1.origin == "mutual_aid" and t.vehicle_id == "M1"
    assert any(v["id"] == "M1" and v["origin"] == "mutual_aid" for v in client.get("/sim/state").json()["vehicles"])
    assert t.doctor_vehicle_id in ("D1", "D2")  # the doctor car stays with the call
    assert run(120, until=lambda: t.status == "completed"), t.status
    assert run(90, until=lambda: "M1" not in W.vehicles), W.vehicles["M1"].status  # home: it leaves our fleet
    assert "M1" in W.reserve_vehicles


def test_reserve_units_only_for_red_calls():
    fresh()
    _, t = call(*near("home_vic", 0.002), "urgent", "fall")
    try:
        assign_trip(W, t.id, "P1")
        raise AssertionError("a private ambulance was requested for an urgent call")
    except ActionError as e:
        assert "red" in str(e)
    assert "P1" in W.reserve_vehicles and "P1" not in W.vehicles
    assert all(c["vehicle_id"] not in ("M1", "P1") for c in tool_find_candidates(W, t.id)["candidates"])


# --- Scenarios ------------------------------------------------------------------------------------


def test_doctor_rendezvous_scenario():
    r = client.post("/sim/admin/scenario/doctor_rendezvous")
    assert r.status_code == 200, r.text
    summary = W.events[-1].summary
    t = W.trips[W.events[-1].affected_trip_ids[0]]
    assert t.condition == "stemi" and t.vehicle_id in ("A1", "A2") and t.doctor_vehicle_id == "D1", summary
    assert "+ doctor D1 (" in summary and "after the ambulance" in summary, summary
    assert W.vehicles["D2"].current_trip_id not in (None, t.id)  # D2 is with the other crew
    detail = client.get("/sim/vehicles/D1").json()
    assert [s["kind"] for s in detail["stops"]] == ["pickup", "dropoff", "base"], detail["stops"]
    assert "Never transports patients" in detail["capabilities"]


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
