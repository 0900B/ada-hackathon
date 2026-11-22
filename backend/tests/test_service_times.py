"""Service times (engine/service_times.py, docs/SERVICE_TIMES.md): turnout, on scene, handover,
cleaning, and that the predictions (projection, dispatch) match what the simulator does.

Run from backend/:  python tests/test_service_times.py   (or: python -m pytest tests)
Offline: road routing off, no Claude. Live-calls mode, calls generator off.
"""
from __future__ import annotations

import logging
import os
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

from app import config, hems, main  # noqa: E402
from app.engine import service_times as st  # noqa: E402
from app.engine.actions import assign_trip  # noqa: E402
from app.engine.candidates import is_free  # noqa: E402
from app.engine.events import apply_event  # noqa: E402
from app.engine.projection import project_all  # noqa: E402
from app.engine.severity import grade  # noqa: E402
from app.models import Trip, UrgentRequestEvent  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402
from app.sim.simulator import tick  # noqa: E402

for noisy in ("httpx", "httpx2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
W = main.sim
STEP_S = 15


DAY = datetime(2026, 11, 23, 9, 0, tzinfo=ZoneInfo("Europe/Ljubljana"))  # fixed clock, by day: the helicopter flies 08:00-16:30


def fresh() -> None:
    seed_world(W, config.RANDOM_SEED, scheduled_day=False, start=DAY)
    W.auto_analyze = False
    W.calls.enabled = False


def run(minutes: float, until=None) -> bool:
    for _ in range(int(minutes * 60 / STEP_S)):
        tick(W, STEP_S)
        project_all(W)
        if until and until():
            return True
    return False


def job(tid: str, vid: str, pickup: str, severity: str, condition: str | None, dropoff: str = "ukc", cargo: str | None = None) -> Trip:
    priority = {"critical": "emergency", "serious": "emergency", "urgent": "urgent", "routine": "scheduled"}[severity]
    t = Trip(id=tid, kind="equipment" if cargo else "patient", patient=None if cargo else f"P-{tid}", cargo=cargo,
             priority=priority, severity=severity, condition=condition, needs="equipment" if cargo else "stretcher",  # type: ignore[arg-type]
             pickup_id=pickup, dropoff_id=dropoff, pickup_after=W.sim_time, due_by=W.sim_time + timedelta(minutes=240))
    grade(W, t)
    W.trips[tid] = t
    assign_trip(W, tid, vid)
    return t


def minutes(a, b) -> float:
    return (a - b).total_seconds() / 60


def test_the_values():
    # The helicopter's turnout is its call-to-take-off time at Brnik (app/hems.py, HNMP 2025 average).
    assert st.TURNOUT_MIN == {"ambulance": 1.0, "doctor": 5.0, "helicopter": 13.0}
    assert (hems.HEMS_ACTIVATION_MIN, hems.HEMS_SCENE_LANDING_MIN, hems.HEMS_HELIPAD_LANDING_MIN) == (13.0, 3.0, 2.0)
    assert st.ON_SCENE_MIN == {"critical": 20.0, "serious": 15.0, "urgent": 12.0, "routine": 8.0}
    assert st.ON_SCENE_CONDITION_MIN == {"cardiac_arrest": 25.0, "stroke": 12.0}
    assert (st.VAN_PATIENT_PICKUP_MIN, st.EQUIPMENT_PICKUP_MIN) == (8.0, 5.0)
    assert (st.HANDOVER_MIN, st.VAN_UNLOAD_MIN, st.EQUIPMENT_DROPOFF_MIN) == (15.0, 5.0, 5.0)
    assert st.CLEANING_MIN["ambulance"] == 10.0 and st.CLEANING_MIN["transport"] == 5.0
    assert config.CALLS_PER_HOUR == 5.0


def test_ambulance_turnout_on_scene_handover_and_cleaning_as_predicted():
    fresh()
    t = job("C1", "A1", "home_moste", "critical", "cardiac_arrest")
    a1 = W.vehicles["A1"]
    project_all(W)
    predicted_pickup, predicted_dropoff = t.eta_pickup, t.eta_dropoff
    start = W.sim_time
    tick(W, STEP_S)  # it takes the job from rest: one minute before it moves
    assert a1.status == "to_pickup" and a1.busy_until is not None
    assert abs(minutes(a1.busy_until, start) - (STEP_S / 60 + 1)) < 0.05
    assert run(30, until=lambda: t.status == "onboard")
    assert abs(minutes(t.eta_pickup, predicted_pickup)) <= 0.5, (t.eta_pickup, predicted_pickup)
    assert a1.status == "loading" and abs(minutes(a1.busy_until, t.eta_pickup) - 25) < 0.01  # resuscitation on scene
    assert run(60, until=lambda: t.status == "completed")
    assert abs(minutes(t.eta_dropoff, predicted_dropoff)) <= 0.5, (t.eta_dropoff, predicted_dropoff)
    assert a1.status == "returning" and abs(minutes(a1.busy_until, t.eta_dropoff) - 25) < 0.01  # 15 handover + 10 cleaning
    assert not is_free(W, a1), "handing over and cleaning: not available"
    run(24.5)
    assert not is_free(W, a1)
    run(1)
    assert is_free(W, a1), "free again after cleaning"


def test_on_scene_by_severity_and_unit():
    fresh()
    cases = [
        ("S1", "A1", "serious", "stemi", None, 15), ("S2", "A2", "serious", "stroke", None, 12),
        ("U1", "A3", "urgent", "fall", None, 12), ("V1", "T1", "urgent", "transfer", None, 8),
        ("E1", "T2", "urgent", "equipment", "blood products", 5),
    ]
    trips = {tid: job(tid, vid, "zd_center", sev, cond, cargo=cargo) for tid, vid, sev, cond, cargo, _ in cases}
    for tid, vid, _, _, _, expect in cases:
        t, v = trips[tid], W.vehicles[vid]
        assert run(30, until=lambda: t.status == "onboard"), tid
        assert abs(minutes(v.busy_until, t.eta_pickup) - expect) < 0.01, (tid, minutes(v.busy_until, t.eta_pickup))


def test_after_the_drop_off_van_and_equipment():
    fresh()
    p = job("V1", "T1", "zd_center", "urgent", "transfer")
    e = job("E1", "T2", "zd_center", "urgent", "equipment", dropoff="onko", cargo="blood products")
    for t, vid, expect in ((p, "T1", 10), (e, "T2", 5)):  # van: 5 unloading + 5 cleaning; equipment: 5 drop-off
        v = W.vehicles[vid]
        assert run(90, until=lambda: t.status == "completed")
        assert abs(minutes(v.busy_until, t.eta_dropoff) - expect) < 0.01, (vid, minutes(v.busy_until, t.eta_dropoff))


def test_doctor_car_turnout_from_rest():
    fresh()
    rec = apply_event(W, UrgentRequestEvent(type="urgent_request", pickup_id="home_bezigrad", priority="emergency",
                                            severity="serious", condition="stemi"))
    t = W.trips[rec.affected_trip_ids[0]]
    d = W.vehicles[t.doctor_vehicle_id]
    assert d.busy_until is not None and abs(minutes(d.busy_until, W.sim_time) - 5) < 0.01, "5 min to get going"
    predicted = t.doctor_eta
    assert run(30, until=lambda: d.status == "loading")
    assert abs(minutes(t.doctor_eta, predicted)) <= 0.5, (t.doctor_eta, predicted)


def test_a_unit_finishing_its_cleaning_is_available_soon():
    fresh()
    for vid in ("A2", "A3", "H1"):
        W.vehicles[vid].status = "out_of_service"
    t = job("X1", "A1", "home_bezigrad", "serious", "sepsis")
    a1 = W.vehicles["A1"]
    assert run(90, until=lambda: t.status == "completed" and a1.busy_until and minutes(a1.busy_until, W.sim_time) <= 5)
    rec = apply_event(W, UrgentRequestEvent(type="urgent_request", pickup_id="home_moste", priority="emergency",
                                            severity="serious", condition="seizure"))
    new = W.trips[rec.affected_trip_ids[0]]
    assert new.vehicle_id == "A1" and "available soon: ready" in rec.summary and "after handover and cleaning" in rec.summary, rec.summary
    assert new.eta_pickup >= a1.busy_until


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
