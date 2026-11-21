"""Equipment transport, priority changes and hospital capacity, end to end against /sim/...

Run from backend/:  python tests/test_ops_events.py   (or: python -m pytest tests)
Offline: road routing off, no agent auto-runs, no Claude (the engine fallback is used).
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
from app.agent.context import build_situation, describe_call, execute_tool  # noqa: E402
from app.agent.prompts import OUTPUT_SCHEMA, TOOLS, _STEP  # noqa: E402
from app.engine.actions import EQUIPMENT_CARRIERS, assign_trip, can_serve  # noqa: E402
from app.engine.candidates import greedy_plan  # noqa: E402
from app.engine.events import EMERGENCY_SLACK_MIN  # noqa: E402
from app.engine.projection import DONE, LOAD_MIN, over_capacity, project_all  # noqa: E402
from app.models import AgentRun, PlanStep, Trip, Vehicle, utcnow  # noqa: E402
from app.routing import travel_minutes  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402
from app.sim.simulator import tick  # noqa: E402

for noisy in ("httpx", "httpx2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
client = TestClient(main.app)  # no `with`: no lifespan, so no background loops; we tick by hand
W = main.sim


def fresh() -> None:
    seed_world(W, config.RANDOM_SEED, scheduled_day=True)  # these tests plan around a pre-planned day


def post_event(ev: dict, status: int = 200) -> dict:
    r = client.post("/sim/events", json=ev)
    assert r.status_code == status, (r.status_code, r.text)
    return r.json()


def simulate(steps: list[dict]) -> dict:
    r = client.post("/sim/plans/simulate", json={"steps": steps})
    assert r.status_code == 200, r.text
    return r.json()


def run_until(cond, minutes: float, step_s: float = 15):
    for _ in range(int(minutes * 60 / step_s)):
        tick(W, step_s)
        project_all(W)
        if found := cond():
            return found
    return None


def loaded(kind: str, vehicle_type: str | None = None):
    """A vehicle whose current trip of this kind is on board."""
    for v in W.vehicles.values():
        t = W.trips.get(v.current_trip_id) if v.current_trip_id else None
        if t and t.kind == kind and t.status == "onboard" and (vehicle_type is None or v.type == vehicle_type):
            return v
    return None


def step(trip_id: str, vehicle_id: str, position=None, interrupt=False, dropoff_id=None) -> dict:
    return {
        "trip_id": trip_id,
        "vehicle_id": vehicle_id,
        "position": position,
        "interrupt_current": interrupt,
        "dropoff_id": dropoff_id,
    }


# --- Equipment transport -----------------------------------------------------------------


def test_seed_has_equipment_and_alternative_hospitals():
    fresh()
    s = client.get("/sim/state").json()
    places = {p["id"]: p for p in s["places"]}
    vehicles = {v["id"]: v for v in s["vehicles"]}
    equipment = [t for t in s["trips"] if t["kind"] == "equipment"]
    assert len(equipment) == 4, equipment
    for t in equipment:
        assert t["patient"] is None and t["cargo"] and t["needs"] == "equipment"
        assert t["label"] == f"equipment: {t['cargo']}"
        assert places[t["pickup_id"]]["kind"] in ("hospital", "health_centre")
        assert places[t["dropoff_id"]]["kind"] in ("hospital", "health_centre")
        assert t["status"] == "assigned" and vehicles[t["vehicle_id"]]["type"] in EQUIPMENT_CARRIERS
        assert t["pickup_after"] < t["due_by"]
    patients = [t for t in s["trips"] if t["kind"] == "patient"]
    assert len(patients) == 24 and all(t["patient"] and t["label"] == t["patient"] for t in patients)
    hospitals = {pid: p for pid, p in places.items() if p["kind"] == "hospital"}
    assert {"sb_trbovlje", "sb_novo_mesto"} <= set(hospitals)
    assert all(p["capacity"] is None for p in hospitals.values())
    assert hospitals["onko"]["specialty"] == "oncology" and hospitals["ukc"]["specialty"] is None
    assert s["kpis"]["over_capacity"] == 0
    assert s["kpis"]["late_trips"] == 0, "the pre-planned day should start on time"


def test_trip_kind_and_needs_stay_consistent():
    base = dict(id="X", priority="scheduled", pickup_id="ukc", dropoff_id="onko", pickup_after=utcnow(), due_by=utcnow())
    assert Trip(**base, kind="equipment", needs="seated", cargo="ventilator").needs == "equipment"
    assert Trip(**base, needs="equipment", cargo="ventilator").kind == "equipment"
    assert Trip(**base, needs="seated", patient="P-1").kind == "patient"


def test_can_serve_equipment():
    fresh()
    trip = next(t for t in W.trips.values() if t.kind == "equipment")
    assert all(can_serve(v, trip)[0] for v in W.vehicles.values() if v.type != "helicopter")  # every van and ambulance
    ok, why = can_serve(W.vehicles["H1"], trip)
    assert not ok and "cannot carry equipment" in why  # equipment goes by road
    trip.priority = "emergency"  # emergencies still need an ambulance (lights and sirens)
    van = W.vehicles["T1"]
    assert not can_serve(van, trip)[0] and can_serve(W.vehicles["A1"], trip)[0]


def test_breakdown_with_equipment_on_board_is_collected_then_delivered():
    fresh()
    v = run_until(lambda: loaded("equipment"), 120)
    assert v, "no vehicle loaded equipment within 2 h"
    tid = v.current_trip_id
    trip = W.trips[tid]
    priority, cargo, dropoff = trip.priority, trip.cargo, trip.dropoff_id

    rec = post_event({"type": "breakdown", "vehicle_id": v.id})
    assert f"equipment ({cargo}) stranded in {v.id}" in rec["summary"], rec["summary"]
    assert "patient" not in rec["summary"]
    assert tid in rec["affected_trip_ids"]
    trip = W.trips[tid]
    site = W.places[trip.pickup_id]
    assert site.kind == "incident_site" and (site.lat, site.lon) == (v.lat, v.lon)
    assert trip.status == "unassigned" and trip.vehicle_id is None and trip.dropoff_id == dropoff
    assert trip.priority == priority, "equipment keeps its priority (only stranded patients are bumped)"
    assert "stranded" in trip.note
    alert = next(a for a in W.alerts if a.id == f"trip_unassigned:{tid}")
    assert f"equipment: {cargo}" in alert.message and "patient" not in alert.message.lower()
    assert v.status == "out_of_service" and not v.queue and v.current_trip_id is None

    plan, unresolved = greedy_plan(W)
    assert plan and tid in [s.trip_id for s in plan.steps] and not unresolved
    body = {"steps": [s.model_dump() for s in plan.steps]}
    sim = client.post("/sim/plans/simulate", json=body).json()
    assert sim["feasible"], sim["errors"]
    assert client.post("/sim/plans/apply", json=body).status_code == 200
    carrier = W.vehicles[W.trips[tid].vehicle_id]
    assert carrier.id != v.id and carrier.type in EQUIPMENT_CARRIERS

    # Another vehicle must first collect it at the breakdown site, then deliver it.
    picked_up_at = []

    def delivered():
        t = W.trips[tid]
        if t.status == "onboard" and not picked_up_at:
            c = W.vehicles[t.vehicle_id]
            picked_up_at.append((c.id, c.lat, c.lon))
        return t.status == "completed"

    assert run_until(delivered, 300), W.trips[tid]
    assert picked_up_at and picked_up_at[0] == (carrier.id, site.lat, site.lon)
    drop = W.places[dropoff]
    assert W.trips[tid].delay_min is not None
    assert (carrier.lat, carrier.lon) == (drop.lat, drop.lon)  # delivered at its original destination


def test_onboard_equipment_vehicle_cannot_be_diverted():
    fresh()
    v = run_until(lambda: loaded("equipment"), 120)
    assert v
    other = next(t for t in W.trips.values() if t.status == "unassigned" or (t.status == "assigned" and t.vehicle_id != v.id))
    other.priority = "urgent"
    r = simulate([step(other.id, v.id, 0, True)])
    assert not r["feasible"] and "equipment" in r["errors"][0] and "patient" not in r["errors"][0]


# --- Priority change ------------------------------------------------------------------------


def _van_trip(min_ahead: float = 60) -> Trip:
    return next(
        t
        for t in sorted(W.trips.values(), key=lambda t: t.id)
        if t.kind == "patient"
        and t.status == "assigned"
        and W.vehicles[t.vehicle_id].type == "transport"
        and t.pickup_after > W.sim_time + timedelta(minutes=min_ahead)
    )


def test_priority_change_to_emergency_releases_a_van_trip():
    """A van can't take an emergency: the trip is released and (new dispatch model) the engine sends
    the nearest free emergency unit at once, like for a new emergency call."""
    fresh()
    trip = _van_trip()
    van, old_due = trip.vehicle_id, trip.due_by
    rec = post_event({"type": "priority_change", "trip_id": trip.id, "priority": "emergency", "note": "chest pain"})
    t = W.trips[trip.id]
    assert t.priority == "emergency" and t.status == "assigned" and t.vehicle_id != van
    assert W.vehicles[t.vehicle_id].type in ("ambulance", "helicopter")  # never a van
    assert t.dispatched_at == W.sim_time
    assert trip.id not in W.vehicles[van].queue
    assert t.pickup_after <= W.sim_time, "an emergency is collected now"
    pickup, drop = W.places[t.pickup_id], W.places[t.dropoff_id]
    direct = travel_minutes(W, pickup.lat, pickup.lon, drop.lat, drop.lon, "ambulance", True)
    expected = W.sim_time + timedelta(minutes=direct + LOAD_MIN + EMERGENCY_SLACK_MIN)
    assert abs((t.due_by - expected).total_seconds()) < 2 and t.due_by < old_due
    assert f"released from {van}" in rec["summary"] and "due-by" in rec["summary"], rec["summary"]
    assert f"dispatched {t.vehicle_id}" in rec["summary"], rec["summary"]
    assert trip.id in rec["affected_trip_ids"]
    assert not any(a.id == f"trip_unassigned:{trip.id}" for a in W.alerts)

    bad = simulate([step(trip.id, van)])
    assert not bad["feasible"] and "emergencies need an ambulance" in bad["errors"][0]
    assert client.post("/sim/plans/apply", json={"steps": [step(trip.id, van)]}).status_code == 400
    plan, _ = greedy_plan(W)
    assert plan is None or trip.id not in [s.trip_id for s in plan.steps]  # already dispatched


def test_priority_change_keeps_a_compatible_vehicle():
    """An ambulance driving to an urgent call has a second urgent call queued; the second patient
    becomes an emergency: it stays on that ambulance and goes first (the ambulance turns around)."""
    fresh()
    first = post_event({"type": "urgent_request", "pickup_id": "home_skofljica", "priority": "urgent"})["affected_trip_ids"][0]
    amb = W.vehicles[W.trips[first].vehicle_id]
    assert amb.type == "ambulance"
    run_until(lambda: amb.current_trip_id == first, 2)
    second = Trip(id="TR-X2", patient="P-X2", priority="urgent", needs="stretcher", pickup_id="home_rudnik",
                  dropoff_id="ukc", pickup_after=W.sim_time, due_by=W.sim_time + timedelta(minutes=90))
    W.trips[second.id] = second
    assign_trip(W, second.id, amb.id)
    assert amb.queue == [second.id]
    # Raising a level re-evaluates the dispatch (doctrine): with another ambulance free and closer, that
    # one would take it. Here amb is the only emergency unit, so the call stays and goes first.
    for v in W.vehicles.values():
        if v.type in ("ambulance", "helicopter") and v.id != amb.id:
            v.status = "out_of_service"
    rec = post_event({"type": "priority_change", "trip_id": second.id, "priority": "emergency"})
    assert W.trips[second.id].vehicle_id == amb.id and W.trips[second.id].status == "assigned"
    assert "released" not in rec["summary"] and f"moved to the front of {amb.id}'s route" in rec["summary"], rec["summary"]
    assert amb.current_trip_id is None and amb.queue == [second.id, first]  # turned around: the emergency first

    van_trip = _van_trip(30)
    rec = post_event({"type": "priority_change", "trip_id": van_trip.id, "priority": "urgent"})
    assert W.trips[van_trip.id].status == "assigned" and W.trips[van_trip.id].vehicle_id == van_trip.vehicle_id


def test_priority_change_on_board_keeps_vehicle():
    fresh()
    v = run_until(lambda: loaded("patient", "transport"), 120)
    assert v
    tid = v.current_trip_id
    old_due = W.trips[tid].due_by
    rec = post_event({"type": "priority_change", "trip_id": tid, "priority": "emergency"})
    t = W.trips[tid]
    assert t.status == "onboard" and t.vehicle_id == v.id and v.current_trip_id == tid
    assert f"stays on {v.id}" in rec["summary"]
    drop = W.places[t.dropoff_id]
    expected = W.sim_time + timedelta(minutes=travel_minutes(W, v.lat, v.lon, drop.lat, drop.lon, v.type, True) + EMERGENCY_SLACK_MIN)
    assert t.due_by == min(old_due, expected.replace(microsecond=0)) or abs((t.due_by - min(old_due, expected)).total_seconds()) < 2


def test_lowering_priority_never_loosens_the_deadline():
    fresh()
    blood = next(t for t in W.trips.values() if t.cargo == "blood products")
    assert blood.priority == "urgent"
    due = blood.due_by
    rec = post_event({"type": "priority_change", "trip_id": blood.id, "priority": "scheduled"})
    assert blood.due_by == due and blood.status == "assigned"
    assert "equipment: blood products" in rec["summary"] and "patient" not in rec["summary"]


def test_priority_change_errors():
    fresh()
    post_event({"type": "priority_change", "trip_id": "TR-999", "priority": "urgent"}, 400)
    post_event({"type": "priority_change", "trip_id": "TR-001", "priority": "scheduled"}, 400)  # unchanged
    post_event({"type": "priority_change", "trip_id": "TR-001", "priority": "critical"}, 422)
    done = run_until(lambda: next((t for t in W.trips.values() if t.status == "completed"), None), 120)
    assert done
    post_event({"type": "priority_change", "trip_id": done.id, "priority": "urgent"}, 400)


# --- Hospital capacity --------------------------------------------------------------------


def _incoming_ukc() -> list[Trip]:
    return [t for t in W.trips.values() if t.dropoff_id == "ukc" and t.kind == "patient" and t.status not in DONE]


def test_hospital_capacity_alert_and_redirect():
    fresh()
    incoming = _incoming_ukc()
    assert len(incoming) >= 3
    rec = post_event({"type": "hospital_capacity", "place_id": "ukc", "capacity": 1})
    assert f"{len(incoming)} incoming" in rec["summary"] and f"{len(incoming) - 1} must be redirected" in rec["summary"]
    overflow = rec["affected_trip_ids"]
    assert len(overflow) == len(incoming) - 1
    s = client.get("/sim/state").json()
    alert = next(a for a in s["alerts"] if a["id"] == "hospital_over_capacity:ukc")
    assert alert["kind"] == "hospital_over_capacity" and alert["severity"] == "high"
    assert all(tid in alert["message"] for tid in overflow)
    assert s["kpis"]["over_capacity"] == len(overflow)
    assert next(p for p in s["places"] if p["id"] == "ukc")["capacity"] == 1
    hospitals = {h["id"]: h for h in build_situation(W)["hospitals"]}
    assert hospitals["ukc"]["can_admit"] == 1 and hospitals["ukc"]["over_capacity_redirect"] == overflow

    tid = overflow[0]
    t = W.trips[tid]
    vid = t.vehicle_id
    queue_before = list(W.vehicles[vid].queue)
    redirect = [step(tid, vid, dropoff_id="sb_trbovlje")]
    sim = simulate(redirect)
    assert sim["feasible"], sim["errors"]
    assert sim["kpis_after"]["over_capacity"] == sim["kpis_before"]["over_capacity"] - 1
    change = next(c for c in sim["trip_changes"] if c["trip_id"] == tid)
    assert change["redirected_to"] == "sb_trbovlje" and change["vehicle_after"] == vid
    assert W.trips[tid].dropoff_id == "ukc", "simulate must not change the real world"

    r = client.post("/sim/plans/apply", json={"steps": redirect, "rationale": "UKC full"})
    assert r.status_code == 200, r.text
    t = W.trips[tid]
    assert t.dropoff_id == "sb_trbovlje" and t.vehicle_id == vid and W.vehicles[vid].queue == queue_before
    assert "redirected from UKC Ljubljana" in t.note
    assert W.trips[tid].eta_dropoff is not None
    alert = next(a for a in W.alerts if a.id == "hospital_over_capacity:ukc")
    assert tid not in alert.message

    rec = post_event({"type": "hospital_capacity", "place_id": "ukc", "capacity": None})
    assert "lifted" in rec["summary"]
    assert not any(a.kind == "hospital_over_capacity" for a in W.alerts)


def test_invalid_redirects_are_rejected():
    fresh()
    overflow = post_event({"type": "hospital_capacity", "place_id": "ukc", "capacity": 1})["affected_trip_ids"]
    a, b = overflow[:2]
    va = W.trips[a].vehicle_id
    cases = [
        ("zd_vic", "not a hospital"),
        ("onko", "specialised"),
        ("nowhere", "Unknown place"),
    ]
    post_event({"type": "hospital_capacity", "place_id": "sb_trbovlje", "capacity": 0})
    cases.append(("sb_trbovlje", "no free capacity"))
    for dest, msg in cases:
        r = simulate([step(a, va, dropoff_id=dest)])
        assert not r["feasible"] and msg in r["errors"][0], (dest, r["errors"])
        bad = client.post("/sim/plans/apply", json={"steps": [step(a, va, dropoff_id=dest)]})
        assert bad.status_code == 400 and msg in bad.json()["detail"]
        assert W.trips[a].dropoff_id == "ukc"

    # Capacity is counted across the steps of one plan.
    post_event({"type": "hospital_capacity", "place_id": "sb_novo_mesto", "capacity": 1})
    vb = W.trips[b].vehicle_id
    r = simulate([step(a, va, dropoff_id="sb_novo_mesto"), step(b, vb, dropoff_id="sb_novo_mesto")])
    assert not r["feasible"] and r["errors"][0].startswith("step 2:") and "no free capacity" in r["errors"][0]

    eq = next(t for t in W.trips.values() if t.kind == "equipment" and t.status == "assigned")
    r = simulate([step(eq.id, eq.vehicle_id, dropoff_id="sb_novo_mesto")])
    assert not r["feasible"] and "carries equipment" in r["errors"][0]

    post_event({"type": "hospital_capacity", "place_id": "zd_vic", "capacity": 2}, 400)
    post_event({"type": "hospital_capacity", "place_id": "nowhere", "capacity": 2}, 400)
    post_event({"type": "hospital_capacity", "place_id": "ukc", "capacity": -1}, 422)


def test_redirect_with_patient_on_board():
    fresh()

    def heading_to_ukc():
        return next(
            (t for t in W.trips.values() if t.dropoff_id == "ukc" and t.kind == "patient" and t.status == "onboard"), None
        )

    t = run_until(heading_to_ukc, 300)
    assert t, "no patient on board towards UKC within 5 h"
    v = W.vehicles[t.vehicle_id]
    post_event({"type": "hospital_capacity", "place_id": "ukc", "capacity": 0})
    assert t.id in [x.id for x in over_capacity(W)["ukc"]]
    other = next(x for x in W.vehicles.values() if x.id != v.id and x.status != "out_of_service")
    r = simulate([step(t.id, other.id, dropoff_id="sb_trbovlje")])
    assert not r["feasible"] and "keep its vehicle" in r["errors"][0]
    r = client.post("/sim/plans/apply", json={"steps": [step(t.id, v.id, dropoff_id="sb_trbovlje")]})
    assert r.status_code == 200, r.text
    assert t.status == "onboard" and v.current_trip_id == t.id and t.dropoff_id == "sb_trbovlje"
    assert run_until(lambda: t.status == "completed", 300)
    drop = W.places["sb_trbovlje"]
    assert (v.lat, v.lon) == (drop.lat, drop.lon)
    assert W.places["ukc"].capacity == 0


def test_capacity_counts_down_on_delivery():
    fresh()
    post_event({"type": "hospital_capacity", "place_id": "ukc", "capacity": 10})
    before = {t.id for t in W.trips.values() if t.status == "completed"}

    def patient_delivered_to_ukc():
        return [t for t in W.trips.values() if t.status == "completed" and t.id not in before and t.dropoff_id == "ukc"]

    done = run_until(patient_delivered_to_ukc, 300)
    assert done
    patients = [t for t in done if t.kind == "patient"]
    assert W.places["ukc"].capacity == 10 - len(patients)


def test_engine_fallback_resolves_over_capacity():
    fresh()
    overflow = post_event({"type": "hospital_capacity", "place_id": "ukc", "capacity": 1})["affected_trip_ids"]
    plan, unresolved = greedy_plan(W)
    assert plan and not unresolved
    redirects = {s.trip_id: s.dropoff_id for s in plan.steps if s.dropoff_id}
    assert set(redirects) == set(overflow)
    assert all(W.places[d].kind == "hospital" and W.places[d].specialty is None for d in redirects.values())
    sim = simulate([s.model_dump() for s in plan.steps])
    assert sim["feasible"] and sim["kpis_after"]["over_capacity"] == 0

    rec = runner._engine_recommendation(W, None, "test")
    run = AgentRun(id="RUN-test", trigger="test", started_at=utcnow())
    runner._finish(W, run, rec, engine="engine_fallback")
    opt = run.recommendation.options[0]
    assert opt.feasible and opt.kpis_after["over_capacity"] == 0
    assert any(c["redirected_to"] for c in opt.trip_changes)

    # Only one free bed elsewhere: the most urgent overflow trip gets it, the alert stays for the rest.
    fresh()
    overflow = post_event({"type": "hospital_capacity", "place_id": "ukc", "capacity": 1})["affected_trip_ids"]
    post_event({"type": "hospital_capacity", "place_id": "sb_trbovlje", "capacity": 1})
    post_event({"type": "hospital_capacity", "place_id": "sb_novo_mesto", "capacity": 0})
    plan, _ = greedy_plan(W)
    redirects = [s for s in plan.steps if s.dropoff_id]
    first = min((W.trips[t] for t in overflow), key=lambda t: ({"emergency": 0, "urgent": 1, "scheduled": 2}[t.priority], t.due_by))
    assert [(s.trip_id, s.dropoff_id) for s in redirects] == [(first.id, "sb_trbovlje")]
    assert simulate([s.model_dump() for s in plan.steps])["kpis_after"]["over_capacity"] == len(overflow) - 1


def test_hospital_full_scenario_engine_plan():
    """The live-calls scenario: five patients heading to UKC, one becomes an emergency, UKC admits two more."""
    records = demo.prepare(W, "hospital_full")
    assert not W.scheduled_day
    escalated = records[0].affected_trip_ids[0]
    t = W.trips[escalated]
    # New dispatch model: the emergency is released from its van and an ambulance is sent at once.
    assert t.priority == "emergency" and t.status == "assigned" and W.vehicles[t.vehicle_id].type == "ambulance"
    assert "released from" in records[0].summary and "dispatched" in records[0].summary
    assert "must be redirected" in records[1].summary
    overflow = {t.id for t in over_capacity(W)["ukc"]}
    assert escalated not in overflow, "the emergency keeps the last admission"
    plan, unresolved = greedy_plan(W)
    assert not unresolved
    assert escalated not in {s.trip_id for s in plan.steps}  # already dispatched: the plan is the redirects
    assert {s.trip_id for s in plan.steps if s.dropoff_id} == overflow
    k = simulate([s.model_dump() for s in plan.steps])["kpis_after"]
    assert k["over_capacity"] == 0 and sum(k["unassigned"].values()) == 0
    # A distant general hospital costs the redirected (urgent) patients some lateness, but only them,
    # and nobody is parked for hours at the end of a queue.
    assert k["late_trips"] <= len(overflow) and k["max_delay_min"] < 90, k
    assert W.trips[escalated].dropoff_id == "ukc", "the emergency keeps its UKC admission"
    # Scheduled redirects go by van; in live calls the redirected patients are urgent, so an urgent
    # long-distance redirect may also fly (H1) or take a free ambulance.
    assert all(
        W.trips[s.trip_id].priority != "scheduled" or W.vehicles[s.vehicle_id].type == "transport" for s in plan.steps
    ), "scheduled redirects go by van"


# --- Agent plumbing -------------------------------------------------------------------------


def test_agent_context_and_tools():
    fresh()
    post_event({"type": "hospital_capacity", "place_id": "ukc", "capacity": 1})
    situation = build_situation(W)
    trips = {t["id"]: t for t in situation["open_trips"]}
    for t in W.trips.values():
        if t.kind == "equipment" and t.id in trips:
            assert trips[t.id]["equipment"] == t.cargo and "patient" not in trips[t.id]
    v = run_until(lambda: (x := loaded("equipment")) and x.status == "with_patient" and x, 120)  # driving it
    assert v and next(x for x in build_situation(W)["vehicles"] if x["id"] == v.id)["status"] == "with_equipment"

    overflow = [t.id for t in over_capacity(W)["ukc"]]
    tid = overflow[0]
    import json

    out = json.loads(execute_tool(W, "find_candidates", {"trip_id": tid, "dropoff_id": "sb_trbovlje"}))
    assert out["trip"]["to"].startswith("General Hospital Trbovlje") and out["candidates"]
    own = next(c for c in out["candidates"] if c["vehicle_id"] == W.trips[tid].vehicle_id)
    assert own["insertion"] == "keeps its place" and own["step"]["dropoff_id"] == "sb_trbovlje"
    out = json.loads(execute_tool(W, "simulate_plan", {"steps": [own["step"]]}))
    assert out["feasible"] and out["kpis_after"]["over_capacity"] < out["kpis_before"]["over_capacity"]
    out = json.loads(execute_tool(W, "find_candidates", {"trip_id": tid, "dropoff_id": None}))
    assert all(c["step"]["dropoff_id"] is None for c in out["candidates"])
    assert "⇒sb_trbovlje" in describe_call("simulate_plan", {"steps": [own["step"]]})

    # Strict schemas: every property is required, and a model-shaped step is a valid PlanStep.
    assert set(_STEP["required"]) == set(_STEP["properties"])
    fc = next(t for t in TOOLS if t["name"] == "find_candidates")["input_schema"]
    assert set(fc["required"]) == set(fc["properties"])
    PlanStep(**{"trip_id": "TR-001", "vehicle_id": "T1", "position": None, "interrupt_current": False, "dropoff_id": None})
    assert OUTPUT_SCHEMA["properties"]["options"]["items"]["properties"]["steps"]["items"] is _STEP


# --- Existing behaviour ---------------------------------------------------------------------


def test_existing_events_unchanged():
    fresh()
    v = run_until(lambda: loaded("patient", "transport"), 120)
    tid = v.current_trip_id
    was = W.trips[tid].priority
    rec = post_event({"type": "breakdown", "vehicle_id": v.id, "note": "flat tyre"})
    assert f"patient of {tid} stranded on board" in rec["summary"]
    t = W.trips[tid]
    assert t.status == "unassigned" and W.places[t.pickup_id].kind == "incident_site"
    assert t.priority == ("urgent" if was == "scheduled" else was)

    rec = post_event({"type": "urgent_request", "pickup_id": "home_polje", "priority": "emergency"})
    new = W.trips[rec["affected_trip_ids"][0]]
    assert new.id == f"TR-{len(W.trips):03d}" and new.kind == "patient" and new.patient
    # New dispatch model: the engine sends the nearest free emergency unit at once.
    assert new.status == "assigned" and W.vehicles[new.vehicle_id].type in ("ambulance", "helicopter")
    assert f"dispatched {new.vehicle_id}" in rec["summary"], rec["summary"]
    post_event({"type": "delay", "vehicle_id": "T2", "minutes": 10})
    inc = post_event({"type": "road_closure", "lat": 46.0563, "lon": 14.5232})
    assert inc["type"] == "road_closure"
    post_event({"type": "clear_incident", "incident_id": next(iter(W.incidents))})
    post_event({"type": "weather_override", "snowfall_cm": 2})
    plan, unresolved = greedy_plan(W)
    assert plan and tid in [s.trip_id for s in plan.steps]  # the stranded patient (left for the plan)
    r = client.post("/sim/plans/apply", json={"steps": [s.model_dump() for s in plan.steps]})
    assert r.status_code == 200
    assert client.get("/sim/state").status_code == 200
    r = client.post("/sim/plans/apply", json={"steps": [{"trip_id": "TR-001", "vehicle_id": "T1"}]})  # old shape
    assert r.status_code in (200, 400)


def test_demo_scenarios_build():
    for name in demo.SCENARIOS:
        records = demo.prepare(W, name)  # scenarios run in live-calls mode
        assert not W.scheduled_day, name
        if name == "equipment_en_route":  # preparation only: no events, but T1 now carries equipment
            v = demo._loaded_with_equipment(W)
            assert records == [] and v is not None and v.id == "T1", v
            continue
        assert records, name
        if name == "stranded_patient":
            assert "patient of" in records[0].summary
        if name == "stranded_equipment":
            assert "equipment (" in records[0].summary and "patient" not in records[0].summary.split("(")[0]


def test_end_to_end_with_lifespan_and_engine_fallback():
    """Starts the real app (seeding, simulation loop), runs a scenario and approves the engine's plan."""
    with TestClient(main.app) as c:
        assert c.get("/sim/state").json()["mode"] == "live_calls", "live calls by default"
        r = c.post("/sim/admin/scenario/hospital_full")
        assert r.status_code == 200, r.text
        assert r.json()["run_id"] is None, "auto-analyse is off by default: no tokens spent"
        assert c.post("/sim/agent/auto", json={"enabled": True}).json()["auto"] is True
        c.post("/sim/admin/reset")
        r = c.post("/sim/admin/scenario/hospital_full")
        run_id = r.json()["run_id"]
        deadline = time.time() + 30
        while time.time() < deadline:
            run = c.get(f"/sim/agent/runs/{run_id}").json()
            if run["status"] != "running":
                break
            time.sleep(0.2)
        assert run["status"] == "done" and run["engine"] == "engine_fallback", run
        opt = run["recommendation"]["options"][0]
        assert opt["feasible"] and any(s["dropoff_id"] for s in opt["steps"])
        r = c.post(f"/sim/agent/runs/{run_id}/approve", json={"option_index": 0})
        assert r.status_code == 200, r.text
        assert c.get("/sim/state").json()["kpis"]["over_capacity"] == 0


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
