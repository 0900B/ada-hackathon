"""The dispatch model: ambulances are emergency units dispatched on availability and proximity,
vans do the scheduled day, the helicopter flies only when it is clearly faster.

Run from backend/:  python tests/test_dispatch_rules.py   (or: python -m pytest tests)
Offline: road routing off, no automatic agent runs, no Claude.
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
from app.engine.actions import MAX_QUEUED_EMERGENCY_UNIT, assign_trip, can_serve  # noqa: E402
from app.engine.candidates import find_candidates, greedy_plan, is_free  # noqa: E402
from app.engine.projection import project_all, route_trip_ids  # noqa: E402
from app.geo import haversine_km  # noqa: E402
from app.models import Trip  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402
from app.sim.simulator import tick  # noqa: E402
from app.vehicles import vehicle_detail  # noqa: E402

for noisy in ("httpx", "httpx2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
client = TestClient(main.app)
W = main.sim
AMBULANCES = ("A1", "A2", "A3")


def fresh() -> None:
    seed_world(W, config.RANDOM_SEED)
    W.auto_analyze = False


def post_event(ev: dict, status: int = 200) -> dict:
    r = client.post("/sim/events", json=ev)
    assert r.status_code == status, (r.status_code, r.text)
    return r.json()


def run_until(cond, minutes: float, step_s: float = 15):
    for _ in range(int(minutes * 60 / step_s)):
        tick(W, step_s)
        project_all(W)
        if found := cond():
            return found
    return None


def new_trip(tid: str, priority: str, pickup: str, dropoff: str = "ukc", needs: str = "stretcher", ready_min: float = 0) -> Trip:
    t = Trip(id=tid, patient=f"P-{tid}", priority=priority, needs=needs, pickup_id=pickup, dropoff_id=dropoff,  # type: ignore[arg-type]
             pickup_after=W.sim_time + timedelta(minutes=ready_min), due_by=W.sim_time + timedelta(minutes=ready_min + 120))
    W.trips[tid] = t
    return t


# --- The seeded day -----------------------------------------------------------------------------


def test_seeded_day_vans_plan_emergency_units_free():
    fresh()
    s = client.get("/sim/state").json()
    assert s["kpis"]["late_trips"] == 0 and sum(s["kpis"]["unassigned"].values()) == 0
    vehicles = {v["id"]: v for v in s["vehicles"]}
    for vid in (*AMBULANCES, "H1"):
        v = vehicles[vid]
        assert v["queue"] == [] and v["current_trip_id"] is None and v["status"] == "idle", v
        assert vehicle_detail(W, W.vehicles[vid])["stops"] == [], "an emergency unit has no stops planned"
    for t in s["trips"]:
        assert vehicles[t["vehicle_id"]]["type"] == "transport", t
    assert any(t["needs"] == "stretcher" for t in s["trips"]), "vans carry the scheduled stretcher patients"
    assert max(len(v["queue"]) for v in s["vehicles"]) <= 7, "the day is spread over the vans"


def test_vehicle_rules():
    fresh()
    stretcher = new_trip("TX-S", "scheduled", "home_moste", needs="stretcher")
    emergency = new_trip("TX-E", "emergency", "home_moste")
    equipment = next(t for t in W.trips.values() if t.kind == "equipment")
    van, amb, heli = W.vehicles["T1"], W.vehicles["A1"], W.vehicles["H1"]
    assert can_serve(van, stretcher)[0], "vans carry stretcher patients"
    ok, why = can_serve(van, emergency)
    assert not ok and "emergencies need an ambulance" in why
    ok, why = can_serve(heli, stretcher)
    assert not ok and "scheduled trips go by road" in why
    assert not can_serve(heli, equipment)[0] and can_serve(heli, emergency)[0]
    # An ambulance holds its current job plus at most one queued trip.
    assert MAX_QUEUED_EMERGENCY_UNIT == 1
    a, b = new_trip("TX-1", "urgent", "home_vic"), new_trip("TX-2", "urgent", "home_siska")
    assign_trip(W, a.id, "A1")
    assign_trip(W, b.id, "A1")
    ok, why = can_serve(amb, emergency)
    assert not ok and "at most its current job plus 1 queued trip" in why, why
    r = client.post("/sim/plans/simulate", json={"steps": [{"trip_id": emergency.id, "vehicle_id": "A1"}]})
    assert not r.json()["feasible"] and "at most its current job" in r.json()["errors"][0]


# --- New calls are dispatched at once -----------------------------------------------------------


def test_new_emergency_goes_to_nearest_free_ambulance():
    fresh()
    run_until(lambda: False, 5)
    rec = post_event({"type": "urgent_request", "pickup_id": "home_siska", "priority": "emergency", "note": "fall"})
    t = W.trips[rec["affected_trip_ids"][0]]
    v = W.vehicles[t.vehicle_id]
    assert v.type == "ambulance" and t.status == "assigned" and t.dispatched_at == W.sim_time
    assert route_trip_ids(v) == [t.id], "it goes now"
    pickup = W.places[t.pickup_id]
    nearest = min((W.vehicles[a] for a in AMBULANCES), key=lambda a: haversine_km(a.lat, a.lon, pickup.lat, pickup.lon))
    assert v.id == nearest.id == "A3", (v.id, nearest.id)  # A3 is based in the west, next to Šiška
    assert f"dispatched {v.id} (nearest free ambulance): at the patient" in rec["summary"], rec["summary"]
    assert run_until(lambda: t.status == "onboard", 20) and t.vehicle_id == v.id


def test_busy_ambulance_turns_around_but_never_with_a_patient_on_board():
    fresh()
    W.vehicles["A3"].status = "out_of_service"
    post_event({"type": "fog", "duration_min": 120})  # H1 grounded
    far = new_trip("TX-NM", "urgent", "home_moste", "sb_novo_mesto")
    assign_trip(W, far.id, "A2")
    assert run_until(lambda: far.status == "onboard", 30), "A2 has a patient on board"
    call = new_trip("TX-U", "urgent", "home_vrhnika")
    assign_trip(W, call.id, "A1")
    run_until(lambda: W.vehicles["A1"].current_trip_id == call.id, 2)
    rec = post_event({"type": "urgent_request", "pickup_id": "home_bezigrad", "priority": "emergency"})
    e = W.trips[rec["affected_trip_ids"][0]]
    assert e.vehicle_id == "A1" and "turns around" in rec["summary"], rec["summary"]
    assert W.vehicles["A2"].current_trip_id == far.id and far.status == "onboard", "never diverted with a patient on board"
    assert run_until(lambda: e.status == "onboard", 30)
    assert call.status in ("assigned", "en_route_pickup") and call.vehicle_id == "A1", "the urgent call waits, it is not lost"


def test_no_unit_at_all_escalates():
    fresh()
    for vid in AMBULANCES:
        W.vehicles[vid].status = "out_of_service"
    post_event({"type": "fog", "duration_min": 60})
    rec = post_event({"type": "urgent_request", "pickup_id": "home_polje", "priority": "emergency"})
    t = W.trips[rec["affected_trip_ids"][0]]
    assert t.status == "unassigned" and "neighbouring station" in rec["summary"], rec["summary"]


def test_urgent_city_call_does_not_fly_but_a_remote_one_does():
    fresh()
    rec = post_event({"type": "urgent_request", "pickup_id": "home_crnuce", "priority": "urgent"})
    assert W.vehicles[W.trips[rec["affected_trip_ids"][0]].vehicle_id].type == "ambulance", rec["summary"]
    rec = post_event({"type": "urgent_request", "pickup_id": "home_polje", "priority": "emergency"})
    assert W.vehicles[W.trips[rec["affected_trip_ids"][0]].vehicle_id].type == "ambulance", "in-city emergencies stay on the road"
    lat, lon = demo.REMOTE_CALL
    rec = post_event({"type": "urgent_request", "lat": lat, "lon": lon, "priority": "emergency", "place_name": "Remote"})
    t = W.trips[rec["affected_trip_ids"][0]]
    assert t.vehicle_id == "H1" and "helicopter" in rec["summary"] and "sooner than" in rec["summary"], rec["summary"]
    assert W.places[t.pickup_id].name == "Remote"


def test_remote_emergency_scenario_helicopter_flies_lands_and_delivers():
    fresh()
    records = demo.SCENARIOS["remote_emergency"][1](W)
    t = W.trips[records[0].affected_trip_ids[0]]
    h = W.vehicles["H1"]
    assert t.vehicle_id == "H1", records[0].summary
    site, ukc = W.places[t.pickup_id], W.places["ukc"]
    seen = []

    def step():
        seen.append((h.status, t.status, round(h.lat, 4), round(h.lon, 4)))
        return t.status == "completed" and h.status == "idle"

    assert run_until(step, 60)
    statuses = [s[0] for s in seen]
    assert statuses.index("to_pickup") < statuses.index("loading") < statuses.index("with_patient")
    loading = next(s for s in seen if s[0] == "loading")
    assert (loading[2], loading[3]) == (round(site.lat, 4), round(site.lon, 4)), "landed at the call location"
    assert (h.lat, h.lon) == (ukc.lat, ukc.lon) and h.base_id == "ukc", "delivered at UKC, its base"
    flying = [s for s in seen if s[0] == "to_pickup"]
    assert len({(s[2], s[3]) for s in flying}) > 3, "it moves across the map while flying"
    assert t.delay_min == 0


def test_fog_released_emergency_goes_to_an_ambulance_at_once():
    fresh()
    lat, lon = demo.REMOTE_CALL
    rec = post_event({"type": "urgent_request", "lat": lat, "lon": lon, "priority": "emergency"})
    t = W.trips[rec["affected_trip_ids"][0]]
    assert t.vehicle_id == "H1"
    rec = post_event({"type": "fog", "duration_min": 60})
    assert t.vehicle_id in AMBULANCES and t.status == "assigned", rec["summary"]
    assert f"{t.id}: dispatched {t.vehicle_id}" in rec["summary"], rec["summary"]


# --- Scheduled work: vans first, ambulances only when needed now, never H1 ---------------------


def test_booking_goes_to_a_van():
    fresh()
    rec = post_event({"type": "task_request", "pickup_id": "ukc", "dropoff_id": "home_rudnik", "needs": "stretcher", "ready_in_min": 45})
    t = W.trips[rec["affected_trip_ids"][0]]
    assert t.vehicle_id and W.vehicles[t.vehicle_id].type == "transport", rec["summary"]
    # Previously this one was flown by the helicopter: a booking never flies.
    rec = post_event({"type": "task_request", "pickup_id": "home_vrhnika", "dropoff_id": "sb_novo_mesto", "ready_in_min": 0, "due_in_min": 40})
    t = W.trips[rec["affected_trip_ids"][0]]
    assert t.vehicle_id != "H1", rec["summary"]
    assert all(is_free(W, W.vehicles[a]) for a in AMBULANCES if a != t.vehicle_id)


def test_ambulances_are_not_tied_up_by_routine_trips_hours_ahead():
    fresh()
    later = new_trip("TX-L", "scheduled", "home_moste", ready_min=120)
    assert not any(c["vehicle_type"] in ("ambulance", "helicopter") for c in find_candidates(W, later.id, limit=100))
    soon = new_trip("TX-N", "scheduled", "home_moste", ready_min=10)
    assert any(c["vehicle_type"] == "ambulance" for c in find_candidates(W, soon.id, limit=100))


def test_engine_plan_after_a_van_breakdown_keeps_ambulances_short_and_one_free():
    fresh()
    van = run_until(lambda: next((v for v in W.vehicles.values() if v.type == "transport" and v.status == "with_patient"), None), 60)
    post_event({"type": "breakdown", "vehicle_id": van.id})
    plan, _ = greedy_plan(W)
    assert plan
    r = client.post("/sim/plans/apply", json={"steps": [s.model_dump() for s in plan.steps]})
    assert r.status_code == 200, r.text
    for a in AMBULANCES:
        assert len(route_trip_ids(W.vehicles[a])) <= 1 + MAX_QUEUED_EMERGENCY_UNIT
    assert any(is_free(W, W.vehicles[a]) for a in AMBULANCES), "one ambulance stays free for the next emergency"
    assert not W.vehicles["H1"].queue and W.vehicles["H1"].current_trip_id is None


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
