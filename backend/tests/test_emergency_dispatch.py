"""Emergency dispatch by severity level and time sensitivity (docs/DISPATCH_PRIORITIES.md, section 3).

Run from backend/:  python tests/test_emergency_dispatch.py   (or: python -m pytest tests)
Offline: road routing off, no Claude. Each test builds its own small situation in live-calls mode.

The user's cases:
(a) same level: an ambulance on its way to one serious call, a second serious call appears next to
    it -> no automatic change; a swap is proposed when it clearly helps (weight, or worst wait);
(b) an ambulance finishing a drop-off near the new patient -> it goes next if clearly sooner than
    the free one, else the free one goes;
(c) a life-threatening call next to an ambulance heading to a non-life-threatening one, only a far
    free ambulance -> the close one is diverted and the displaced call re-dispatched within target.
"""
from __future__ import annotations

import logging
import os
import sys
import time
import traceback
from datetime import timedelta
from pathlib import Path

os.environ["ROAD_ROUTING"] = "0"
os.environ["AGENT_AUTO"] = "0"
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, demo, main  # noqa: E402
from app.agent import runner  # noqa: E402
from app.agent.messages import ParsedMessage, grade_text, to_operator_events  # noqa: E402
from app.engine.actions import ActionError, assign_trip  # noqa: E402
from app.engine.dispatch import decide, swap_options  # noqa: E402
from app.engine.events import apply_event  # noqa: E402
from app.engine.projection import project_all, route_trip_ids  # noqa: E402
from app.engine.severity import grade  # noqa: E402
from app.models import Trip, UrgentRequestEvent  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402
from app.sim.simulator import tick  # noqa: E402

for noisy in ("httpx", "httpx2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
client = TestClient(main.app)
W = main.sim


def fresh(in_service=("A1", "A2", "A3", "H1", "T1", "T2", "T3", "T4", "T5")) -> None:
    seed_world(W, config.RANDOM_SEED, scheduled_day=False)
    W.auto_analyze = False
    W.calls.enabled = False
    for v in W.vehicles.values():
        if v.id not in in_service:
            v.status = "out_of_service"


def park(vid: str, place: str, status: str = "returning") -> None:
    v, p = W.vehicles[vid], W.places[place]
    v.lat, v.lon, v.status, v.path_from, v.path_to = p.lat, p.lon, status, None, None


def run(minutes: float, until=None, step_s: float = 15):
    for _ in range(int(minutes * 60 / step_s)):
        tick(W, step_s)
        project_all(W)
        if until and until():
            return True
    return False


def job(tid: str, vid: str | None, pickup: str, severity: str, condition: str | None = None, dropoff: str = "ukc",
        modifiers: list[str] | None = None) -> Trip:
    priority = {"critical": "emergency", "serious": "emergency", "urgent": "urgent"}[severity]
    t = Trip(id=tid, patient=f"P-{tid}", priority=priority, severity=severity, condition=condition,  # type: ignore[arg-type]
             modifiers=modifiers or [], needs="stretcher", pickup_id=pickup, dropoff_id=dropoff,
             pickup_after=W.sim_time, due_by=W.sim_time + timedelta(minutes=90))
    grade(W, t)
    W.trips[tid] = t
    if vid:
        assign_trip(W, tid, vid)
        t.dispatched_at = W.sim_time
    return t


def call(lat: float, lon: float, severity: str, condition: str | None = None, modifiers: list[str] | None = None):
    priority = "urgent" if severity == "urgent" else "emergency"
    rec = apply_event(W, UrgentRequestEvent(type="urgent_request", lat=lat, lon=lon, place_name="call", priority=priority,  # type: ignore[arg-type]
                                            severity=severity, condition=condition, modifiers=modifiers or []))  # type: ignore[arg-type]
    return rec, W.trips[rec.affected_trip_ids[0]]


def near(place: str, dlat: float = 0.0, dlon: float = 0.0) -> tuple[float, float]:
    p = W.places[place]
    return round(p.lat + dlat, 5), round(p.lon + dlon, 5)


# --- The contract -------------------------------------------------------------------------------


def test_severity_fields_and_defaults():
    fresh()
    base = dict(needs="stretcher", pickup_id="home_moste", dropoff_id="ukc", pickup_after=W.sim_time, due_by=W.sim_time)
    assert Trip(id="a", priority="emergency", **base).severity == "serious"
    assert Trip(id="b", priority="urgent", **base).severity == "urgent"
    assert Trip(id="c", priority="scheduled", **base).severity == "routine"
    t = Trip(id="d", priority="urgent", severity="critical", condition="cardiac_arrest", modifiers=["no_bystander_cpr"], **base)
    assert t.priority == "emergency" and t.condition_label == "Cardiac arrest" and t.time_weight == 11.0
    assert t.response_target_min == 8
    assert Trip(id="e", priority="emergency", condition="stroke", **base).severity == "serious"
    remote = job("R1", None, "home_vrhnika", "critical", "cardiac_arrest")
    assert remote.response_target_min == 15, "critical outside the city: 15 min"
    assert job("S1", None, "home_moste", "serious", "stemi").response_target_min == 18
    assert job("U1", None, "home_moste", "urgent", "fall").response_target_min == 60
    ev = UrgentRequestEvent(type="urgent_request", pickup_id="home_moste", priority="urgent", severity="critical")
    assert ev.priority == "emergency"
    snap = {x["id"]: x for x in W.snapshot()["trips"]}
    assert snap["d"] if "d" in snap else True
    s1 = snap["S1"]
    assert (s1["severity"], s1["condition"], s1["condition_label"], s1["time_weight"], s1["response_target_min"]) == (
        "serious", "stemi", "Suspected heart attack", 6.0, 18.0)


# --- (b) available soon ---------------------------------------------------------------------------


def _finishing_at_ukc() -> Trip:
    """A1 has handed over a serious patient at UKC and is finishing cleaning (ready in at most 3 min).
    (With a patient still on board it would need the 15-min handover and 10-min cleaning first.)"""
    t = job("X1", "A1", "home_bezigrad", "serious", "breathing_difficulty")
    a1 = W.vehicles["A1"]
    assert run(90, until=lambda: t.status == "completed" and a1.busy_until is not None
               and 0 < (a1.busy_until - W.sim_time).total_seconds() <= 180)
    return t


def test_case_b_unit_finishing_nearby_goes_when_clearly_sooner():
    fresh(("A1", "A3"))
    _finishing_at_ukc()
    park("A3", "home_medvode")  # the free one is far away
    rec, t = call(*near("zd_center"), "serious", "breathing_difficulty")
    assert t.vehicle_id == "A1" and "available soon: ready" in rec.summary and "after handover and cleaning" in rec.summary, rec.summary
    assert "sooner than A3" in rec.summary and "may deteriorate quickly" in rec.summary
    assert route_trip_ids(W.vehicles["A1"]) == [t.id]


def test_case_b_unit_with_a_patient_on_board_finishes_handover_and_cleaning_first():
    fresh(("A1", "A3"))
    x = job("X1", "A1", "home_bezigrad", "serious", "breathing_difficulty")
    assert run(30, until=lambda: x.status == "onboard" and W.vehicles["A1"].status == "with_patient")
    park("A3", "home_medvode")
    rec, t = call(*near("zd_center"), "serious", "breathing_difficulty")
    assert t.vehicle_id == "A3", rec.summary  # A1 needs drop-off + 15 min handover + 10 min cleaning
    assert W.vehicles["A1"].current_trip_id == x.id and x.status == "onboard", "never diverted with a patient on board"


def test_case_b_free_unit_goes_when_the_busy_one_is_not_clearly_sooner():
    fresh(("A1", "A3"))
    _finishing_at_ukc()
    park("A3", "zd_center", "idle")  # the free one is right there
    rec, t = call(*near("zd_center", 0.001, 0.001), "serious", "breathing_difficulty")
    assert t.vehicle_id == "A3" and "nearest free ambulance" in rec.summary, rec.summary


# --- (c) override a lower level, re-dispatch the displaced call -------------------------------------


def _a1_heading_to_fall(minutes: float = 2.0) -> Trip:
    fall = job("F1", "A1", "home_polje", "urgent", "fall")
    run(minutes)
    assert W.vehicles["A1"].current_trip_id == fall.id and fall.status == "en_route_pickup"
    return fall


def test_case_c_life_threatening_call_overrides_and_displaced_call_stays_within_target():
    fresh(("A1", "A3", "T1", "T2", "T3", "T4", "T5"))
    park("A3", "home_medvode")
    fall = _a1_heading_to_fall()
    a1 = W.vehicles["A1"]
    rec, t = call(round(a1.lat + 0.003, 5), round(a1.lon + 0.004, 5), "critical", "cardiac_arrest", ["no_bystander_cpr"])
    assert t.vehicle_id == "A1" and f"diverted from {fall.id} (urgent) to this critical call" in rec.summary, rec.summary
    assert "within its 60-min target" in rec.summary and "about 6% survival lost per minute" in rec.summary
    assert fall.vehicle_id and fall.vehicle_id != "A1" and fall.times_displaced == 1, (fall.vehicle_id, rec.summary)
    reach = max(fall.eta_pickup, fall.pickup_after) - fall.pickup_after  # type: ignore[type-var]
    assert reach <= timedelta(minutes=60)
    assert route_trip_ids(a1)[0] == t.id
    assert run(10, until=lambda: t.status == "onboard") and t.vehicle_id == "A1"


def test_case_c_no_override_when_the_displaced_patient_would_miss_their_target():
    fresh(("A1", "A3"))
    park("A3", "zd_vic")  # reaches the arrest within its 8-min target, A1 would still be clearly sooner
    fall = _a1_heading_to_fall()
    fall.response_target_min = 5.0  # (hypothetical) a target nobody else could meet
    a1 = W.vehicles["A1"]
    rec, t = call(round(a1.lat + 0.003, 5), round(a1.lon + 0.004, 5), "critical", "cardiac_arrest")
    assert t.vehicle_id == "A3" and "diverted" not in rec.summary, rec.summary
    assert W.vehicles["A1"].current_trip_id == fall.id and fall.times_displaced == 0
    assert (max(t.eta_pickup, t.pickup_after) - t.pickup_after) <= timedelta(minutes=8)


def test_case_c_higher_level_first_when_nothing_else_reaches_it_in_time():
    """The same, but the only other unit is far away: the arrest would miss its target, so the higher
    level goes first and the displaced call is re-dispatched even though it misses its own target."""
    fresh(("A1", "A3"))
    park("A3", "home_medvode")
    fall = _a1_heading_to_fall()
    fall.response_target_min = 5.0
    a1 = W.vehicles["A1"]
    rec, t = call(round(a1.lat + 0.003, 5), round(a1.lon + 0.004, 5), "critical", "cardiac_arrest")
    assert t.vehicle_id == "A1" and f"diverted from {fall.id}" in rec.summary, rec.summary
    assert "after its 5-min target: no unit can reach it sooner" in rec.summary, rec.summary
    assert fall.vehicle_id and fall.times_displaced == 1


def test_no_call_is_displaced_twice():
    fresh(("A1", "A3"))
    park("A3", "home_medvode")
    fall = _a1_heading_to_fall()
    fall.times_displaced = 1  # already displaced once before
    a1 = W.vehicles["A1"]
    trip = job("C2", None, "home_moste", "critical", "cardiac_arrest")
    trip.pickup_id = W.places["home_moste"].id
    d = decide(W, trip)
    a1_opt = next(o for o in d.options if o.vehicle_id == "A1")
    assert a1_opt.kind == "override" and not a1_opt.displaced_ok and "already displaced once" in (a1_opt.why_not or "")
    assert d.chosen is not None and d.chosen.vehicle_id != "A1"
    assert a1.current_trip_id == fall.id


def test_override_needs_a_clear_saving():
    fresh(("A1", "A3"))
    _a1_heading_to_fall()
    a1 = W.vehicles["A1"]
    # A3 free right next to the new call: diverting A1 would save nothing.
    W.places["spot"] = W.places["home_moste"].model_copy(update={"id": "spot", "lat": round(a1.lat + 0.003, 5), "lon": round(a1.lon + 0.004, 5)})
    park("A3", "spot", "idle")
    rec, t = call(round(a1.lat + 0.003, 5), round(a1.lon + 0.004, 5), "serious", "stemi")
    assert t.vehicle_id == "A3" and "diverted" not in rec.summary, rec.summary


# --- Never divert --------------------------------------------------------------------------------


def test_never_divert_on_scene_near_the_patient_or_with_a_patient_on_board():
    fresh(("A1", "A3"))
    park("A3", "home_medvode")
    fall = job("F1", "A1", "home_polje", "urgent", "fall")
    a1 = W.vehicles["A1"]
    p = W.places["home_polje"]
    a1.lat, a1.lon = p.lat + 0.003, p.lon  # about 300 m away: within 2 min of its patient
    run(0.25)
    assert a1.current_trip_id == fall.id
    emergency = job("E9", None, "home_moste", "critical", "cardiac_arrest")
    d = decide(W, emergency)
    assert next(o for o in d.options if o.vehicle_id == "A1").kind != "override", "not diverted near its patient"
    try:
        assign_trip(W, emergency.id, "A1", position=0, interrupt_current=True)
        raise AssertionError("an explicit divert near the patient must be refused")
    except ActionError as e:
        assert "the patient of F1" in str(e) and "not diverted" in str(e), e
    # With the patient on board: "available soon" at best, never diverted.
    run(10, until=lambda: fall.status == "onboard")
    d = decide(W, emergency)
    assert next(o for o in d.options if o.vehicle_id == "A1").kind == "soon"


# --- (a) same level: proposals, never automatic ----------------------------------------------------


def test_case_a_same_level_swap_is_proposed_not_applied():
    records = demo.prepare(W, "same_level")
    W.auto_analyze = False
    stemi = W.trips[records[0].affected_trip_ids[0]]
    seizure = next(t for t in W.trips.values() if t.condition == "seizure")
    assert seizure.vehicle_id == "A1" and stemi.vehicle_id == "A3", "same level: nothing changes automatically"
    swaps = swap_options(W)
    sw = next(s for s in swaps if s["trip_id"] == stemi.id)
    assert sw["other_trip_id"] == seizure.id and sw["vehicles"] == ["A3", "A1"]
    assert sw["text"].startswith(f"Swap: A1 takes {stemi.id}") and "still within its 18-min target" in sw["text"], sw["text"]
    assert "Suspected heart attack before ongoing seizure" in sw["reason"] and "catheter lab" in sw["reason"], sw["reason"]
    rec = runner._engine_recommendation(W, None, "test")
    assert any(o.title.startswith("Swap") for o in rec.options)
    # The 2-step plan works when approved: A1 turns to the heart attack, A3 takes the seizure.
    r = client.post("/sim/plans/apply", json={"steps": sw["steps"]})
    assert r.status_code == 200, r.text
    assert stemi.vehicle_id == "A1" and seizure.vehicle_id == "A3"
    assert run(10, until=lambda: stemi.status == "onboard") and stemi.vehicle_id == "A1"


def test_case_a_no_swap_when_it_does_not_clearly_help():
    fresh(("A1", "A3"))
    park("A3", "home_moste", "idle")
    first = job("S1", "A1", "home_polje", "serious", "seizure")
    run(1)
    rec, t = call(*near("home_moste", 0.001, 0.001), "serious", "seizure")  # same weight, next to free A3
    assert t.vehicle_id == "A3" and first.vehicle_id == "A1"
    assert not [s for s in swap_options(W) if t.id in (s["trip_id"], s["other_trip_id"])]


def test_same_level_higher_weight_goes_first_in_a_queue():
    fresh(("A1",))
    seizure = job("Q1", "A1", "home_moste", "serious", "seizure")  # weight 4, queued (no tick yet)
    stemi = job("Q2", "A1", "home_polje", "serious", "stemi")  # weight 6: clearly more time-critical
    assert route_trip_ids(W.vehicles["A1"]) == [stemi.id, seizure.id]
    fresh(("A1",))
    first = job("Q3", "A1", "home_moste", "serious", "breathing_difficulty")  # weight 5
    second = job("Q4", "A1", "home_polje", "serious", "stemi")  # weight 6: comparable, keeps the order
    assert route_trip_ids(W.vehicles["A1"]) == [first.id, second.id]


def test_severity_order_in_a_queue():
    fresh(("A1",))
    serious = job("O1", "A1", "home_moste", "serious", "sepsis")
    critical = job("O2", "A1", "home_polje", "critical", "choking")
    assert route_trip_ids(W.vehicles["A1"]) == [critical.id, serious.id], "critical before serious"
    fresh(("T1",))
    urgent = job("O3", "T1", "home_moste", "urgent", "fall")
    routine = Trip(id="O4", priority="scheduled", needs="seated", pickup_id="zd_vic", dropoff_id="ukc",
                   pickup_after=W.sim_time, due_by=W.sim_time + timedelta(minutes=90))
    W.trips[routine.id] = routine
    try:
        assign_trip(W, routine.id, "T1", position=0)
        raise AssertionError("a routine trip cannot go before an urgent one")
    except ActionError as e:
        assert "higher priority goes first" in str(e)
    assert route_trip_ids(W.vehicles["T1"]) == [urgent.id]


# --- Helicopter per level ------------------------------------------------------------------------------


def test_helicopter_rules_per_level():
    # Same place, same fleet: the only free ambulance is at the west base (about 9 min), H1 at UKC
    # (about 4 min): closer, but not 10 min faster.
    for severity, condition, expect_air in (("critical", "cardiac_arrest", True), ("serious", "stemi", False)):
        fresh(("A3", "H1"))
        rec, t = call(*near("home_moste", 0.002, 0.003), severity, condition)
        assert (t.vehicle_id == "H1") is expect_air, (severity, rec.summary)
        if expect_air:
            assert "the closest unit for a critical call" in rec.summary
        else:
            assert "H1 checked" in rec.summary and "not 10 min faster" in rec.summary, rec.summary
    fresh(("A1", "H1"))
    park("A1", "home_vrhnika")  # far away: H1 is far more than 10 min faster
    rec, t = call(*near("home_moste", 0.002, 0.003), "serious", "stemi")
    assert t.vehicle_id == "H1" and "min sooner at UKC than A1 by road" in rec.summary  # heart attack: compared at UKC, rec.summary
    fresh(("A1", "H1"))
    park("A1", "home_vrhnika")
    rec, t = call(*near("home_moste", 0.002, 0.003), "urgent", "fall")  # urgent in the city: never flies
    assert t.vehicle_id != "H1", rec.summary


# --- Slovenian practice: red reference, cover --------------------------------------------------------


def test_red_response_over_15_min_is_flagged_and_escalated():
    demo.prepare(W, "surge")
    alerts = [a for a in W.alerts if a.kind == "red_response_over_15_min"]
    assert alerts and "reference for red calls: 15 min" in alerts[0].message
    rec = runner._engine_recommendation(W, None, "test")
    assert rec.escalation and "neighbouring station" in rec.escalation


def test_protect_cover_sends_a_van_for_an_urgent_call():
    fresh(("A1", "T1", "T5"))  # A1 is the last free ambulance
    rec, t = call(*near("base_center", 0.004, 0.004), "urgent", "fall")
    assert W.vehicles[t.vehicle_id].type == "transport" and "protect cover: A1 is the last ambulance free" in rec.summary, rec.summary


# --- Field messages: severity and condition from the words -----------------------------------------------


def _urgent(**kw) -> dict:
    return {"type": "urgent_request", "pickup_place_id": "home_moste", "lat": None, "lon": None, "dropoff_id": None,
            "needs": "stretcher", "priority": "emergency", "severity": None, "condition": None, "modifiers": [], "note": None, **kw}


def _parse(text: str, *events: dict):
    parsed = ParsedMessage(understood_sl="x", understood_en="x", events=list(events))
    return to_operator_events(W, parsed, text)


def test_parser_extracts_severity_condition_and_modifiers():
    fresh()
    cases = [
        ("Moški ne diha, oživljajo ga.", "critical", "cardiac_arrest", []),
        ("Otrok se duši!", "critical", "choking", ["child"]),
        ("Močno krvavi iz noge.", "critical", "catastrophic_bleeding", []),
        ("Sum na kap, povešen ustni kot.", "serious", "stroke", []),
        ("Bolečina v prsih, poten.", "serious", "stemi", []),
        ("Težko diha, se slabša.", "serious", "breathing_difficulty", ["deteriorating"]),
    ]
    for text, severity, condition, mods in cases:
        (ev,) = _parse(text, _urgent())
        assert (ev.severity, ev.condition, ev.priority) == (severity, condition, "emergency"), (text, ev)
        assert set(mods) <= set(ev.modifiers), (text, ev.modifiers)
    (ev,) = _parse("Padec po stopnicah, sum na zlom kolka.", _urgent(priority="urgent"))
    assert (ev.severity, ev.condition, ev.priority) == ("urgent", "fracture", "urgent")
    (ev,) = _parse("Padel je, nezavesten.", _urgent())  # the model said emergency: a plain fall never downgrades it
    assert ev.priority == "emergency" and ev.severity == "serious"
    (ev,) = _parse("Ne diha.", _urgent(severity="serious", condition="breathing"))  # kept; "breathing" is an old alias
    assert ev.severity == "serious" and ev.condition == "breathing_difficulty"
    assert grade_text("Nihče ne oživlja.") == ("cardiac_arrest", "critical", ["no_bystander_cpr"])


def test_parser_raises_severity_when_the_patient_gets_worse():
    fresh()
    t = job("W1", "A1", "home_moste", "serious", "breathing_difficulty")
    (ev,) = _parse("Stanje se je poslabšalo, pacient se slabša.",
                   {"type": "priority_change", "trip_id": t.id, "priority": "emergency", "severity": None, "condition": None, "note": None})
    assert ev.severity == "critical" and ev.priority == "emergency"
    rec = client.post("/sim/events", json=ev.model_dump(mode="json")).json()
    assert W.trips[t.id].severity == "critical" and "serious → critical" in rec["summary"], rec["summary"]


def test_frontend_contract_codes_summary_and_severity_change():
    fresh(("A3", "H1"))
    # Codes the UI sends, old aliases still accepted; the summary uses the condition label and modifiers.
    rec = client.post("/sim/events", json={"type": "urgent_request", "lat": 46.0582, "lon": 14.5450, "priority": "emergency",
                                           "severity": "serious", "condition": "stemi", "modifiers": ["late_stroke_window", "child"],
                                           "note": "crushing chest pain"}).json()
    t = W.trips[rec["affected_trip_ids"][0]]
    assert rec["summary"].startswith(f"New serious call {t.id} (Suspected heart attack, late stroke window, child):"), rec["summary"]
    assert t.vehicle_id == "A3" and t.pickup_after == W.events[-1].sim_time, "response time counts from the call"
    assert Trip(id="z", priority="emergency", condition="breathing", modifiers=["stroke_window_end"], needs="stretcher",
                pickup_id="ukc", dropoff_id="ukc", pickup_after=W.sim_time, due_by=W.sim_time).condition == "breathing_difficulty"
    # serious -> critical keeps priority "emergency" (no 400) and re-evaluates: H1 is now the closest unit.
    r = client.post("/sim/events", json={"type": "priority_change", "trip_id": t.id, "severity": "critical", "condition": "cardiac_arrest"})
    assert r.status_code == 200, r.text
    assert t.severity == "critical" and t.priority == "emergency" and t.condition_label == "Cardiac arrest"
    assert t.vehicle_id == "H1" and "re-evaluated: dispatched H1" in r.json()["summary"], r.json()["summary"]
    assert client.post("/sim/events", json={"type": "priority_change", "trip_id": t.id, "severity": "critical"}).status_code == 400
    # The backend's own missed-target alert carries trip_id and a "response" kind.
    demo.prepare(W, "surge")
    assert all(a.trip_id and "response" in a.kind for a in W.alerts if a.kind == "red_response_over_15_min")


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
