"""Audit of the ambulance assignment logic: concrete scenarios, each asserting the sensible outcome.

Run from backend/:  python tests/test_assignment_audit.py
Offline: road routing off, no automatic agent runs, no Claude.
"""
from __future__ import annotations

import logging
import os
import re
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

from app import config, main  # noqa: E402
from app.engine import units  # noqa: E402
from app.engine.actions import MAX_QUEUED_EMERGENCY_UNIT, assign_trip, near_current_patient  # noqa: E402
from app.engine.candidates import find_candidates  # noqa: E402
from app.engine.dispatch import decide  # noqa: E402
from app.engine.events import apply_event  # noqa: E402
from app.engine.projection import project_all, route_trip_ids  # noqa: E402
from app.engine.severity import BUSY_UNIT_MIN_GAIN_MIN  # noqa: E402
from app.models import Trip, UrgentRequestEvent  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402
from app.sim.simulator import tick  # noqa: E402

for noisy in ("httpx", "httpx2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
client = TestClient(main.app)
W = main.sim
LJ = ZoneInfo("Europe/Ljubljana")
DAY = datetime(2026, 11, 23, 9, 0, tzinfo=LJ)
NIGHT = datetime(2026, 11, 23, 22, 0, tzinfo=LJ)
AMBULANCES = ("A1", "A2", "A3")


def fresh(start: datetime = DAY) -> None:
    seed_world(W, config.RANDOM_SEED, scheduled_day=False, start=start)
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
    priority = "urgent" if severity == "urgent" else "emergency"
    rec = apply_event(W, UrgentRequestEvent(type="urgent_request", lat=lat, lon=lon, place_name="call", priority=priority,  # type: ignore[arg-type]
                                            severity=severity, condition=condition))  # type: ignore[arg-type]
    return rec, W.trips[rec.affected_trip_ids[0]]


def near(place: str, dlat: float = 0.0, dlon: float = 0.0) -> tuple[float, float]:
    p = W.places[place]
    return round(p.lat + dlat, 5), round(p.lon + dlon, 5)


def new_trip(tid: str, priority: str, pickup: str, dropoff: str = "ukc", severity: str | None = None) -> Trip:
    t = Trip(id=tid, patient=f"P-{tid}", priority=priority, needs="stretcher", pickup_id=pickup, dropoff_id=dropoff,  # type: ignore[arg-type]
             pickup_after=W.sim_time, due_by=W.sim_time + timedelta(minutes=120), severity=severity)  # type: ignore[arg-type]
    W.trips[tid] = t
    return t


def out(*vids: str) -> None:
    for v in vids:
        W.vehicles[v].status = "out_of_service"


def no_double_booking() -> None:
    seen: dict[str, str] = {}
    for v in W.vehicles.values():
        if v.type == "doctor":
            continue  # a doctor car joins the crew: trip.doctor_vehicle_id, not the transporting unit
        jobs = route_trip_ids(v)
        if v.type in ("ambulance", "helicopter"):
            assert len(jobs) <= 1 + MAX_QUEUED_EMERGENCY_UNIT, (v.id, jobs)
        for t in jobs:
            assert t not in seen, f"{t} on both {seen[t]} and {v.id}"
            seen[t] = v.id
            assert W.trips[t].vehicle_id == v.id, (t, W.trips[t].vehicle_id, v.id)


# --- 1. Patient on board ------------------------------------------------------------------------


def test_unit_with_patient_on_board_is_not_taken():
    fresh()
    far = new_trip("TX-FAR", "urgent", "home_siska", "sb_novo_mesto", "urgent")
    assign_trip(W, far.id, "A3")
    assert run(40, lambda: far.status == "onboard")
    rec, t = call(*near("home_siska"), "critical", "cardiac_arrest")
    print("  onboard:", rec.summary)
    assert t.vehicle_id in ("A1", "A2", "H1"), rec.summary
    assert W.vehicles["A3"].current_trip_id == far.id and far.status == "onboard"
    no_double_booking()


def test_available_soon_only_when_clearly_sooner():
    fresh()
    # A1 carries a patient to UKC; the call is next to UKC; A2 and A3 are far out of town.
    trip = new_trip("TX-UKC", "urgent", "home_bezigrad", "ukc", "urgent")
    assign_trip(W, trip.id, "A1")
    assert run(30, lambda: trip.status == "onboard")
    for vid, place in (("A2", "home_vrhnika"), ("A3", "home_grosuplje")):
        W.vehicles[vid].lat, W.vehicles[vid].lon = W.places[place].lat, W.places[place].lon
        W.vehicles[vid].status = "idle"
    out("H1")
    project_all(W)
    tr = new_trip("TX-NEW", "emergency", "ukc", "ukc", "serious")
    d = decide(W, tr)
    a1 = next(o for o in d.options if o.vehicle_id == "A1")
    print("  soon:", [(o.vehicle_id, o.kind, round(o.rank, 1)) for o in d.options], "->", d.chosen.vehicle_id)
    assert a1.kind == "soon"
    if a1.rank <= d.best_free.rank - BUSY_UNIT_MIN_GAIN_MIN:
        assert d.chosen.vehicle_id == "A1"
    else:
        assert d.chosen.vehicle_id != "A1"
    del W.trips[tr.id]
    # The free ones far out of town: A1, finishing at UKC, is clearly sooner and goes.
    for vid in ("A2", "A3"):
        W.vehicles[vid].lat, W.vehicles[vid].lon = 46.32, 14.05
    project_all(W)
    rec, t = call(*near("ukc", 0.002), "serious", "breathing_difficulty")
    print("  soon (clearly sooner):", rec.summary)
    assert t.vehicle_id == "A1" and "available soon" in rec.summary and trip.vehicle_id == "A1", rec.summary
    assert route_trip_ids(W.vehicles["A1"]) == [trip.id, t.id], "after its drop-off, never diverted"
    no_double_booking()


def test_held_up_unit_reason_says_delay_not_handover():
    fresh()
    out("H1")
    for vid in ("A1", "A2"):
        W.vehicles[vid].lat, W.vehicles[vid].lon = 46.32, 14.05
    W.vehicles["A3"].busy_until = W.sim_time + timedelta(minutes=10)
    W.vehicles["A3"].busy_reason = "delay"
    project_all(W)
    rec, t = call(*near("home_siska"), "critical", "cardiac_arrest")
    print("  held up:", rec.summary)
    assert t.vehicle_id == "A3" and "held up until" in rec.summary and "handover" not in rec.summary, rec.summary


# --- 2. Override of a lower-level call ----------------------------------------------------------


def _a1_to_urgent_far():
    fresh()
    out("A2")
    W.vehicles["H1"].status = "out_of_service"
    u = new_trip("TX-URG", "urgent", "home_vrhnika", "ukc", "urgent")
    assign_trip(W, u.id, "A1")
    run(4)
    assert W.vehicles["A1"].current_trip_id == u.id and W.vehicles["A1"].status == "to_pickup"
    return u


def test_critical_call_next_to_a_unit_on_an_urgent_call_diverts_it():
    u = _a1_to_urgent_far()
    a1 = W.vehicles["A1"]
    rec, t = call(round(a1.lat, 5), round(a1.lon, 5), "critical", "cardiac_arrest")
    print("  override:", rec.summary)
    assert t.vehicle_id == "A1" and f"diverted from {u.id} (urgent)" in rec.summary, rec.summary
    assert u.times_displaced == 1 and u.vehicle_id is not None and u.status != "unassigned"
    no_double_booking()


def test_not_diverted_within_2_min_of_its_patient():
    u = _a1_to_urgent_far()
    a1, p = W.vehicles["A1"], W.places[u.pickup_id]
    assert run(60, lambda: near_current_patient(W, a1, u) is not None), "A1 gets within 2 min of its patient"
    rec, t = call(round(p.lat + 0.006, 5), round(p.lon, 5), "critical", "cardiac_arrest")
    print("  near patient:", rec.summary)
    assert W.vehicles["A1"].current_trip_id == u.id and u.vehicle_id == "A1"
    assert "diverted from" not in rec.summary
    no_double_booking()


def test_dispatcher_assigned_unit_is_not_diverted():
    u = _a1_to_urgent_far()
    units.note(W, u, "A1", "dispatcher's choice", by="dispatcher")
    a1 = W.vehicles["A1"]
    rec, t = call(round(a1.lat, 5), round(a1.lon, 5), "critical", "cardiac_arrest")
    print("  held:", rec.summary)
    assert W.vehicles["A1"].current_trip_id == u.id and t.vehicle_id != "A1"
    assert "not diverted: assigned by the dispatcher" in rec.summary, rec.summary
    no_double_booking()


# --- 3. Same level: no automatic swap -----------------------------------------------------------


def test_same_level_no_automatic_swap():
    fresh()
    out("A2", "H1")
    s = new_trip("TX-SER", "emergency", "home_vrhnika", "ukc", "serious")
    assign_trip(W, s.id, "A1")
    run(4)
    a1 = W.vehicles["A1"]
    rec, t = call(round(a1.lat, 5), round(a1.lon, 5), "serious", "major_trauma")
    print("  same level:", rec.summary)
    assert s.vehicle_id == "A1" and W.vehicles["A1"].current_trip_id == s.id and s.times_displaced == 0
    assert "diverted from" not in rec.summary
    no_double_booking()


# --- 4. Out of service, delayed, queued ---------------------------------------------------------


def test_out_of_service_or_delayed_unit_not_chosen():
    fresh()
    out("A3", "H1")
    rec, t = call(*near("home_siska"), "critical", "cardiac_arrest")
    assert t.vehicle_id in ("A1", "A2"), rec.summary
    fresh()
    out("H1")
    W.vehicles["A3"].busy_until = W.sim_time + timedelta(minutes=30)  # held up (jam / delay)
    W.vehicles["A3"].busy_reason = "delay"
    rec, t = call(*near("home_siska"), "critical", "cardiac_arrest")
    print("  delayed:", rec.summary)
    assert t.vehicle_id in ("A1", "A2"), rec.summary


def test_busy_unit_queue_counted_no_unit_gets_two_queued():
    fresh()
    out("H1")
    for i, place in enumerate(("home_siska", "home_moste", "home_bezigrad", "home_vic", "home_crnuce", "home_polje", "home_rudnik")):
        rec, t = call(*near(place), "serious", "major_trauma")
        print(f"  call {i}: {t.vehicle_id}")
        no_double_booking()


# --- 5. Vans and the helicopter -----------------------------------------------------------------


def test_vans_never_take_emergencies():
    fresh()
    out(*AMBULANCES, "H1")
    for sev, cond in (("critical", "cardiac_arrest"), ("serious", "stemi")):
        rec, t = call(*near("home_moste"), sev, cond)
        assert t.vehicle_id is None or W.vehicles[t.vehicle_id].type not in ("transport",), rec.summary
        assert not any(c["vehicle_type"] == "transport" for c in find_candidates(W, t.id, limit=100))


def test_helicopter_city_by_day_only_if_sooner_and_never_at_night():
    fresh()
    rec, t = call(*near("home_moste"), "serious", "major_trauma")
    assert t.vehicle_id in AMBULANCES, rec.summary
    fresh(NIGHT)
    lat, lon = 46.32, 14.05  # remote, far from any ambulance
    rec, t = call(lat, lon, "critical", "cardiac_arrest")
    print("  night:", rec.summary)
    assert t.vehicle_id != "H1" and "night" in rec.summary, rec.summary


# --- 6. Doctor cars -----------------------------------------------------------------------------


def test_doctor_car_added_and_busy_one_not_stolen():
    fresh()
    out("D2")
    rec, t1 = call(*near("home_moste"), "critical", "cardiac_arrest")
    assert t1.needs_doctor and t1.doctor_vehicle_id == "D1", rec.summary
    rec, t2 = call(*near("home_siska"), "critical", "cardiac_arrest")
    print("  doctor 2:", rec.summary)
    assert t1.doctor_vehicle_id == "D1" and W.vehicles["D1"].current_trip_id == t1.id
    assert t2.doctor_vehicle_id != "D1" and "no doctor car free" in rec.summary, rec.summary


# --- 6b. Follow-up: a faster free unit takes over a delayed unit's call, not a dispatcher's choice


def test_followup_switches_delayed_unit_but_keeps_dispatcher_choice():
    from app.engine import followup

    for by_dispatcher in (False, True):
        fresh()
        out("H1", "A2")
        rec, t = call(*near("home_moste"), "serious", "major_trauma")
        first = t.vehicle_id
        other = "A3" if first == "A1" else "A1"
        if by_dispatcher:
            units.note(W, t, first, "dispatcher's choice", by="dispatcher")
        W.vehicles[first].busy_until = W.sim_time + timedelta(minutes=20)  # held up
        W.vehicles[first].busy_reason = "delay"
        o = W.vehicles[other]
        o.lat, o.lon = W.places["home_moste"].lat + 0.01, W.places["home_moste"].lon
        project_all(W)
        done = followup._faster_free_unit(W, t)  # (check() runs it for calls with a 112 record)
        print(f"  follow-up (dispatcher={by_dispatcher}):", done)
        if by_dispatcher:
            assert done is None and t.vehicle_id == first, done
            done = followup._faster_free_unit(W, t, release_hold=True)  # a disruption pushed it back >= 3 min
        assert done and t.vehicle_id == other and "sooner than" in done[1], done
        no_double_booking()


# --- 7. Determinism and consistency -------------------------------------------------------------


def test_ties_deterministic_and_eta_in_text_matches_card():
    fresh()
    out("H1")
    # A1 and A2 share a base: equal ETAs. The pick must be the same on every run.
    picks = set()
    for _ in range(3):
        fresh()
        out("H1", "A3")
        tr = new_trip("TX-TIE", "emergency", "home_bezigrad", "ukc", "serious")
        picks.add(decide(W, tr).chosen.vehicle_id)
    assert len(picks) == 1, picks
    fresh()
    rec, t = call(*near("home_polje"), "serious", "major_trauma")
    m = re.search(r"at the patient (\d\d:\d\d) \(in (\d+) min\)", rec.summary)
    assert m, rec.summary
    card = t.eta_pickup.astimezone(LJ).strftime("%H:%M")
    mins = (t.eta_pickup - W.sim_time).total_seconds() / 60
    print("  eta:", m.group(1), m.group(2), "card:", card, round(mins, 1))
    assert m.group(1) == card and abs(int(m.group(2)) - mins) <= 1, (rec.summary, card, mins)


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
