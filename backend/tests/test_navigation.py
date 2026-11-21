"""In-vehicle tablet navigation: where the vehicle is heading, without calling OSRM.

Run: cd backend && python tests/test_navigation.py
"""
from __future__ import annotations

import logging
import os
import sys
import traceback
from datetime import timedelta
from pathlib import Path

os.environ.setdefault("ROAD_ROUTING", "0")
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.disable(logging.WARNING)

from app import config, main, navigation  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402

W = main.sim


def fresh():
    seed_world(W, config.RANDOM_SEED, scheduled_day=True)
    W.calls.enabled = False


def test_target_follows_the_current_trip():
    fresh()
    v = next(v for v in W.vehicles.values() if v.queue)
    trip = W.trips[v.queue[0]]
    v.current_trip_id, v.queue = v.queue[0], v.queue[1:]
    v.status = "to_pickup"
    t = navigation._target(W, v)
    assert t and t["kind"] == "pickup" and t["place_id"] == trip.pickup_id and t["trip_id"] == trip.id, t
    v.status = "with_patient"
    t = navigation._target(W, v)
    assert t and t["kind"] == "dropoff" and t["place_id"] == trip.dropoff_id, t


def test_unloading_with_a_queued_job_heads_to_its_pickup_not_to_base():
    """After a drop-off the vehicle is "returning" for the unloading minutes; with a job queued it
    then drives straight to that pickup, so the tablet must show that, not "back to base"."""
    fresh()
    v = next(v for v in W.vehicles.values() if v.queue)
    nxt = W.trips[v.queue[0]]
    v.current_trip_id, v.status = None, "returning"
    v.busy_until = W.sim_time + timedelta(minutes=3)
    t = navigation._target(W, v)
    assert t and t["kind"] == "pickup" and t["place_id"] == nxt.pickup_id and t["trip_id"] == nxt.id, t


def test_returning_with_nothing_queued_goes_to_base():
    fresh()
    v = next(v for v in W.vehicles.values() if v.queue)
    v.current_trip_id, v.queue, v.status = None, [], "returning"
    t = navigation._target(W, v)
    assert t and t["kind"] == "base" and t["place_id"] == v.base_id, t


def test_idle_and_out_of_service_have_no_leg():
    fresh()
    v = next(v for v in W.vehicles.values() if not v.queue and v.type == "ambulance")
    v.status = "idle"
    assert navigation.navigation(W, v)["status"] == "no_leg"
    v.status = "out_of_service"
    assert navigation.navigation(W, v)["status"] == "out_of_service"


def test_helicopter_gets_bearing_and_distance():
    fresh()
    h = next(v for v in W.vehicles.values() if v.type == "helicopter")
    trip = next(t for t in W.trips.values() if t.status == "assigned")
    h.current_trip_id, h.status, h.queue = trip.id, "to_pickup", []
    nav = navigation.navigation(W, h)
    assert nav["mode"] == "flight" and nav["steps"] == [], nav
    assert 0 <= nav["bearing_deg"] < 360 and nav["remaining_m"] > 0, nav


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception:
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
