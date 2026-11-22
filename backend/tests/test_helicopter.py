"""The helicopter (HNMP) as the real service runs it (app/hems.py, docs/SERVICE_TIMES.md).

Run from backend/:  python tests/test_helicopter.py   (or: python -m pytest tests)
Offline: road routing off, no Claude. Live-calls mode, calls generator off.

- Based at Brnik (Ljubljana airport), flies patients to UKC.
- From rest at its base: 13 min from the call to take-off (in every ETA); airborne it is re-tasked
  without it. Each flight leg ends with a landing: 3 min at the scene, 2 on a helipad.
- New calls only 08:00-16:30 local (world clock): at night it is "unavailable (night)", never
  dispatched, the summaries, the snapshot and the AI context say so; a mission under way at 16:30
  is finished.
- So it no longer wins typical city calls, but still wins the remote ones.
- The demo scenarios run at a daytime clock and keep their decisions.
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

from fastapi.testclient import TestClient  # noqa: E402

from app import config, demo, hems, main  # noqa: E402
from app.agent.context import build_situation  # noqa: E402
from app.agent.triage import triage_rules  # noqa: E402
from app.engine.actions import can_serve  # noqa: E402
from app.engine.candidates import find_candidates, is_free  # noqa: E402
from app.engine.events import apply_event  # noqa: E402
from app.engine.projection import project_all  # noqa: E402
from app.geo import haversine_km  # noqa: E402
from app.models import CallRecord, UrgentRequestEvent  # noqa: E402
from app.routing import HELICOPTER_SPEED_KMH, travel_minutes  # noqa: E402
from app.sim import calls  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402
from app.sim.simulator import tick  # noqa: E402

for noisy in ("httpx", "httpx2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
client = TestClient(main.app)
W = main.sim
LJ = ZoneInfo("Europe/Ljubljana")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 23, hour, minute, tzinfo=LJ)  # a Monday in the winter schedule


def fresh(hour: int = 9, minute: int = 0) -> None:
    seed_world(W, config.RANDOM_SEED, scheduled_day=False, start=at(hour, minute))
    W.auto_analyze = False
    W.calls.enabled = False


def run(minutes: float, until=None, step_s: float = 15) -> bool:
    for _ in range(int(minutes * 60 / step_s)):
        tick(W, step_s)
        project_all(W)
        if until and until():
            return True
    return False


def call(lat: float, lon: float, severity: str, condition: str):
    """A 112 call with its record (so the snapshot lists its units) through the normal event path."""
    record = CallRecord(call_id=calls.new_call_id(W, "112"), kind="112", received_at=W.sim_time, address="test address",
                        text_sl="test", text_en="test", triage=triage_rules("test", W.sim_time))
    priority = "urgent" if severity == "urgent" else "emergency"
    rec = apply_event(W, UrgentRequestEvent(type="urgent_request", lat=lat, lon=lon, place_name="call", priority=priority,  # type: ignore[arg-type]
                                            severity=severity, condition=condition), record)  # type: ignore[arg-type]
    return rec, W.trips[rec.affected_trip_ids[0]]


def minutes(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds() / 60


# --- Base, activation, landing ------------------------------------------------------------------


def test_based_at_brnik_and_flies_patients_to_ukc():
    fresh()
    h = W.vehicles["H1"]
    base = W.places[h.base_id]
    assert h.base_id == "brnik" and base.kind == "base" and "Brnik" in base.name
    assert (base.lat, base.lon) == (46.2237, 14.4576) and (h.lat, h.lon) == (base.lat, base.lon)
    assert 18 < haversine_km(base.lat, base.lon, W.places["ukc"].lat, W.places["ukc"].lon) < 21, "about 19 km from UKC"
    assert h.shift_end is not None and h.shift_end.astimezone(LJ).strftime("%H:%M") == "16:30"


def test_activation_delay_is_in_the_eta():
    fresh()
    h = W.vehicles["H1"]
    lat, lon = demo.REMOTE_CALL  # Kamniška Bistrica: the helicopter's call
    rec, t = call(lat, lon, "serious", "major_trauma")
    assert t.vehicle_id == "H1", rec.summary
    base = W.places["brnik"]
    flight = haversine_km(base.lat, base.lon, lat, lon) / HELICOPTER_SPEED_KMH * 60
    expected = hems.HEMS_ACTIVATION_MIN + flight + hems.HEMS_SCENE_LANDING_MIN
    assert abs(minutes(t.eta_pickup, W.sim_time) - expected) < 0.1, (minutes(t.eta_pickup, W.sim_time), expected)
    assert "take-off in 13 min" in rec.summary and "helicopter, " in rec.summary, rec.summary
    unit = next(u for u in W.snapshot()["trips"] if u["id"] == t.id)["units"][0]
    assert "take-off in 13 min" in unit["reason"] and "doctor on board" in unit["reason"], unit
    # The crew gets it ready: it does not move for 13 min, then flies and lands as predicted.
    predicted = t.eta_pickup
    run(12.5)
    assert (h.lat, h.lon) == (base.lat, base.lon) and h.status == "to_pickup", "still on the ground at Brnik"
    assert unit_status(t).startswith("crew to the aircraft, take-off "), unit_status(t)
    assert run(15, until=lambda: t.status == "onboard")
    assert abs(minutes(t.eta_pickup, predicted)) <= 0.5, (t.eta_pickup, predicted)
    # The landing on the UKC helipad is shorter than at the scene.
    ukc = W.places["ukc"]
    leg = travel_minutes(W, lat, lon, ukc.lat, ukc.lon, "helicopter")
    cruise = haversine_km(lat, lon, ukc.lat, ukc.lon) / HELICOPTER_SPEED_KMH * 60
    assert abs(leg - cruise - hems.HEMS_HELIPAD_LANDING_MIN) < 1e-6


def unit_status(t) -> str:
    return next(u for u in W.snapshot()["trips"] if u["id"] == t.id)["units"][0]["status_text"]


def test_an_airborne_helicopter_is_re_tasked_without_the_activation():
    fresh()
    h = W.vehicles["H1"]
    lat, lon = demo.REMOTE_CALL
    _, first = call(lat, lon, "serious", "major_trauma")
    assert first.vehicle_id == "H1"
    assert run(120, until=lambda: first.status == "completed")
    assert run(60, until=lambda: h.status == "returning" and not (h.busy_until and h.busy_until > W.sim_time))
    run(1)  # handed over and cleaned at UKC: flying home to Brnik
    assert h.status == "returning" and is_free(W, h) and hems.takeoff_in_min(h, W.sim_time) is None
    _, klat, klon, _ = calls.REMOTE[2]  # Sava valley near Litija
    rec, second = call(klat, klon, "critical", "catastrophic_bleeding")
    assert second.vehicle_id == "H1", rec.summary
    p = W.places[second.pickup_id]
    direct = travel_minutes(W, h.lat, h.lon, p.lat, p.lon, "helicopter")
    assert abs(minutes(second.eta_pickup, W.sim_time) - direct) < 0.5, "airborne: no 13-min activation"
    assert "take-off in" not in rec.summary, rec.summary


# --- Operating hours ------------------------------------------------------------------------------


def test_hours_08_00_to_16_30():
    assert not hems.on_duty(at(7, 59)) and hems.on_duty(at(8, 0)) and hems.on_duty(at(16, 29)) and not hems.on_duty(at(16, 30))
    assert hems.next_start(at(2, 0)) == at(8, 0) and hems.next_start(at(17, 0)) == at(8, 0) + timedelta(days=1)
    assert hems.next_start(at(9, 0)) == at(9, 0)


def test_unavailable_at_night_never_dispatched_and_says_so():
    fresh(2)
    h = W.vehicles["H1"]
    lat, lon = demo.REMOTE_CALL
    rec, t = call(lat, lon, "serious", "major_trauma")
    assert t.vehicle_id != "H1" and W.vehicles[t.vehicle_id].type == "ambulance", rec.summary
    assert "H1 not available: night (HNMP flies 08:00-16:30)" in rec.summary, rec.summary
    assert "consider the helicopter" not in rec.summary, "no advice to use a helicopter that cannot fly"
    ok, why = can_serve(h, t, W.sim_time)
    assert not ok and "unavailable (night)" in why and "until 08:00" in why, why
    assert not is_free(W, h) and all(c["vehicle_id"] != "H1" for c in find_candidates(W, t.id, limit=50))
    # The plan path refuses it too, with the reason.
    r = client.post("/sim/plans/simulate", json={"steps": [{"trip_id": t.id, "vehicle_id": "H1"}]})
    assert not r.json()["feasible"] and "unavailable (night)" in r.json()["errors"][0], r.json()
    # Snapshot and vehicle card: a clear status for the map.
    v = next(x for x in client.get("/sim/state").json()["vehicles"] if x["id"] == "H1")
    assert v["unavailable"] == "night" and v["unavailable_text"].startswith("Unavailable (night)"), v
    assert datetime.fromisoformat(v["off_duty_until"]) == at(8, 0) and v["hours"] == "08:00-16:30"
    card = client.get("/sim/vehicles/H1").json()["vehicle"]
    assert card["unavailable"] == "night"
    a1 = next(x for x in client.get("/sim/state").json()["vehicles"] if x["id"] == "A1")
    assert "unavailable" not in a1, "only helicopters carry these fields"
    # The AI's situation knows it.
    hv = next(x for x in build_situation(W)["vehicles"] if x["id"] == "H1")
    assert hv["unavailable"].startswith("night") and not hv["free"], hv
    # By day the same call flies.
    fresh(9)
    rec, t = call(lat, lon, "serious", "major_trauma")
    assert t.vehicle_id == "H1", rec.summary
    v = next(x for x in client.get("/sim/state").json()["vehicles"] if x["id"] == "H1")
    assert v["unavailable"] is None and v["off_duty_until"] is None


def test_a_mission_under_way_at_16_30_is_finished():
    fresh(16, 20)
    h = W.vehicles["H1"]
    lat, lon = demo.REMOTE_CALL
    rec, t = call(lat, lon, "serious", "major_trauma")
    assert t.vehicle_id == "H1", rec.summary
    assert run(90, until=lambda: t.status == "completed"), "flown in although it is now after 16:30"
    assert not hems.on_duty(W.sim_time)
    lat2, lon2 = calls.REMOTE[1][1], calls.REMOTE[1][2]
    rec2, t2 = call(lat2, lon2, "serious", "major_trauma")
    assert t2.vehicle_id != "H1" and "night" in rec2.summary, rec2.summary
    assert run(60, until=lambda: h.status == "idle"), "then it flies home to Brnik"
    assert (h.lat, h.lon) == (W.places["brnik"].lat, W.places["brnik"].lon)


# --- Who wins what ------------------------------------------------------------------------------------


def test_no_longer_wins_city_critical_calls_but_wins_remote_ones():
    city = []
    for pid in calls.CITY:
        fresh()
        lat, lon = W.places[pid].lat, W.places[pid].lon
        rec, t = call(lat, lon, "critical", "cardiac_arrest")
        city.append(t.vehicle_id)
        assert t.vehicle_id != "H1", (pid, rec.summary)
        assert "H1 checked" in rec.summary and "take-off in 13 min" in rec.summary and "not the closest" in rec.summary, rec.summary
    assert set(city) <= {"A1", "A2", "A3"}
    for name, lat, lon, _ in calls.REMOTE[:2]:  # Kamniška Bistrica, Krvavec: 45 min and more by road
        for severity, condition in (("critical", "cardiac_arrest"), ("serious", "major_trauma")):
            fresh()
            rec, t = call(lat, lon, severity, condition)
            assert t.vehicle_id == "H1", (name, severity, rec.summary)
            assert t.doctor_vehicle_id == "H1", "its doctor is on board, no doctor car drives 45 min"


def test_urgent_calls_fly_only_far_from_the_hospital():
    fresh()
    rec, t = call(*[W.places["home_crnuce"].lat, W.places["home_crnuce"].lon], "urgent", "fall")
    assert t.vehicle_id != "H1", "Črnuče is 5 km from UKC (though 15 km from Brnik)"


# --- Demo scenarios ----------------------------------------------------------------------------------


def test_scenarios_run_by_day_and_keep_their_decisions():
    assert demo.scenario_start("remote_emergency", at(13)) is None, "the demo at 13:00 keeps its clock"
    assert demo.scenario_start("surge", at(2)) == at(11)
    assert demo.scenario_start("nothing_free", at(15)) == at(11), "not enough of the day left: 11:00"
    for name in demo.SCENARIOS:
        records = demo.prepare(W, name)
        assert hems.on_duty(W.sim_time), (name, W.sim_time)
        if name == "remote_emergency":
            t = W.trips[records[0].affected_trip_ids[0]]
            assert t.vehicle_id == "H1" and "diverted from" in records[0].summary, records[0].summary
            assert "take-off in" in records[0].summary, records[0].summary
        elif name == "nothing_free":
            t = W.trips[records[0].affected_trip_ids[0]]
            assert t.vehicle_id == "H1" and "can request M1" in records[0].summary, records[0].summary
            assert t.doctor_vehicle_id and t.doctor_vehicle_id.startswith("D"), "the doctor car is there long before"
        elif name in ("stroke_rush_hour", "priority_override", "same_level", "doctor_rendezvous"):
            last = records[-1].summary
            assert "dispatched H1" not in last and "H1 checked" in last and "take-off in 13 min" in last, (name, last)


def test_benchmark_runs_a_day_shift():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import benchmark

    assert benchmark.START.astimezone(LJ).strftime("%H:%M") == "08:00" and hems.on_duty(benchmark.START)


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
