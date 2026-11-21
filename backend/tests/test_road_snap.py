"""A vehicle whose road route arrives mid-leg must not jump onto it.

Regression: every live call goes to a new address with no cached road route, so the vehicle drives a
straight line until OSRM answers, then was put at the same fraction of the (longer, curved) road
route. On a long leg that was a jump of up to a kilometre on the map.
Run: cd backend && python tests/test_road_snap.py
"""
from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("ROAD_ROUTING", "0")
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.disable(logging.WARNING)

from app import config, main  # noqa: E402
from app.geo import haversine_km  # noqa: E402
from app.roads import ROADS, key, make_route, nearest_fraction, point_along  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402
from app.sim.simulator import MERGE_M, _move_towards  # noqa: E402

W = main.sim
DT_MIN = 10 / 60  # one simulation tick: 2 s at 5x speed


def fresh():
    seed_world(W, config.RANDOM_SEED, scheduled_day=False)
    W.calls.enabled = False
    ROADS.routes.clear()
    ROADS.detours.clear()


def drive_straight_then_get_route(curve_east_deg: float):
    """A1 drives towards Domžale in a straight line, then a curved road route for the leg arrives."""
    fresh()
    v = W.vehicles["A1"]
    target = W.places["home_domzale"]
    for _ in range(12):  # about two minutes of straight-line driving, no route cached
        _move_towards(W, v, target.lat, target.lon, DT_MIN, True)
    assert not v.on_road
    a, b = key(*v.path_from), key(target.lat, target.lon)
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + curve_east_deg)  # the road bends east of the straight line
    km = haversine_km(*a, *mid) + haversine_km(*mid, *b)
    ROADS.routes[(a, b)] = make_route(km / 50 * 3600, km * 1000, [a, mid, b], a, b, "osrm")
    return v, target


def test_no_jump_when_the_road_route_arrives_mid_leg():
    v, target = drive_straight_then_get_route(0.02)
    before = (v.lat, v.lon)
    _move_towards(W, v, target.lat, target.lon, DT_MIN, True)
    assert v.on_road
    step_km = haversine_km(*before, v.lat, v.lon)
    assert step_km < 0.35, f"jumped {step_km:.2f} km onto the road route"


def test_merges_onto_the_road_within_a_few_ticks():
    v, target = drive_straight_then_get_route(0.02)
    for i in range(30):
        prev = (v.lat, v.lon)
        _move_towards(W, v, target.lat, target.lon, DT_MIN, True)
        assert haversine_km(*prev, v.lat, v.lon) < 0.35, f"tick {i}: jumped"
        if v.snap_offset is None:
            break
    assert v.snap_offset is None, "still not on the road after 30 ticks"
    route = ROADS.routes[(key(*v.path_from), key(target.lat, target.lon))]
    on_road = point_along(route, v.path_progress)
    assert haversine_km(v.lat, v.lon, *on_road) < 0.01, "not on the road geometry after merging"


def test_nearest_fraction_projects_onto_the_route():
    a, b = (46.0, 14.5), (46.1, 14.5)
    route = make_route(600, 11_000, [a, b], a, b, "osrm")
    f = nearest_fraction(route, 46.05, 14.51)  # beside the middle of a straight north-south road
    assert abs(f - 0.5) < 0.02, f
    assert nearest_fraction(route, 45.9, 14.5) == 0.0
    assert abs(nearest_fraction(route, 46.2, 14.5) - 1.0) < 1e-9
    assert MERGE_M > 0


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
