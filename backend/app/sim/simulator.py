"""Moves vehicles along their routes each tick. Stands in for a live GPS/AVL feed."""
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from ..engine.projection import LOAD_MIN, UNLOAD_MIN
from ..models import Vehicle
from ..roads import ROADS, key, point_along
from ..geo import haversine_km
from .fleet_details import fuel_rate
from ..routing import flies, leg_route, reroute_if_blocked, travel_minutes

if TYPE_CHECKING:
    from ..state import WorldState


def tick(state: WorldState, dt_s: float) -> None:
    state.sim_time += timedelta(seconds=dt_s)
    for v in state.vehicles.values():
        if v.grounded_until and state.sim_time >= v.grounded_until:
            v.grounded_until = None  # the fog has lifted: the helicopter can fly again
        if v.status == "out_of_service":
            continue
        if v.busy_until and state.sim_time < v.busy_until:
            continue
        v.busy_until = None
        before = (v.lat, v.lon)
        _advance(state, v, dt_s / 60)
        _account_distance(state, v, before)


def _account_distance(state: WorldState, v: Vehicle, before: tuple[float, float]) -> None:
    """Odometer and fuel: burn fuel for the distance moved this tick; refuel when parked at base."""
    km = haversine_km(before[0], before[1], v.lat, v.lon)
    if km > 0:
        v.km_today = round(v.km_today + km, 2)
        v.fuel_pct = max(0.0, round(v.fuel_pct - km * fuel_rate(v.type), 2))
    base = state.places.get(v.base_id)
    if v.status == "idle" and base and haversine_km(v.lat, v.lon, base.lat, base.lon) < 0.05 and v.fuel_pct < 99:
        v.fuel_pct = 100.0  # refuelled at the base


def _move_towards(state: WorldState, v: Vehicle, lat: float, lon: float, dt_min: float, emergency: bool) -> bool:
    """Drive v towards (lat, lon) along the road route (or a straight line if none is cached yet).

    Progress is a fraction of the leg; the leg's duration is re-evaluated every tick, so changes
    in traffic, weather or incidents speed the vehicle up or slow it down mid-leg.
    """
    target = key(lat, lon)
    flying = flies(v.type)  # helicopters fly straight and never use (or request) road routes
    if v.path_to is None or tuple(v.path_to) != target:  # a new leg starts here
        v.path_from, v.path_to, v.path_progress, v.path_avoid = (v.lat, v.lon), target, 0.0, None
        v.on_road = not flying and ROADS.route(v.lat, v.lon, lat, lon) is not None
        if not v.on_road and not flying:
            ROADS.want_route(v.lat, v.lon, lat, lon)  # later legs on this pair will follow the road
    if v.path_progress >= 1.0:
        return True
    assert v.path_from is not None
    if not flying:
        reroute_if_blocked(state, v)  # a closure ahead: re-plan the rest of the leg around it
        if not v.on_road:
            if leg_route(state, v) is not None:
                v.on_road = True  # the road route (or detour) arrived mid-leg: snap onto it
            elif v.path_avoid and not ROADS.detours_available():
                ROADS.want_route(v.path_from[0], v.path_from[1], lat, lon)  # no detour possible: plain route
    total = travel_minutes(state, v.path_from[0], v.path_from[1], lat, lon, v.type, emergency)
    v.path_progress = 1.0 if total <= dt_min else min(1.0, v.path_progress + dt_min / total)
    if v.path_progress >= 1.0:
        v.lat, v.lon = lat, lon
        v.on_road = False
        v.path_avoid = None
        return True
    route = leg_route(state, v) if v.on_road else None
    if route is not None:
        v.lat, v.lon = point_along(route, v.path_progress)
    else:
        v.lat = v.path_from[0] + (lat - v.path_from[0]) * v.path_progress
        v.lon = v.path_from[1] + (lon - v.path_from[1]) * v.path_progress
    return False


def _advance(state: WorldState, v: Vehicle, dt_min: float) -> None:
    if v.status == "loading":
        v.status = "with_patient"

    if v.current_trip_id is None and v.status != "with_patient":
        if v.queue:
            v.current_trip_id = v.queue.pop(0)
            state.trips[v.current_trip_id].status = "en_route_pickup"
            v.status = "to_pickup"
        elif v.status != "idle":
            v.status = "returning"

    trip = state.trips[v.current_trip_id] if v.current_trip_id else None
    if v.status == "to_pickup" and trip:
        target = state.places[trip.pickup_id]
    elif v.status == "with_patient" and trip:
        target = state.places[trip.dropoff_id]
    elif v.status == "returning":
        target = state.places[v.base_id]
    else:
        return

    emergency = bool(trip and trip.priority == "emergency")
    if not _move_towards(state, v, target.lat, target.lon, dt_min, emergency):
        return

    if v.status == "to_pickup" and trip:
        if state.sim_time < trip.pickup_after:
            return  # early: wait at the pickup
        trip.status = "onboard"
        trip.eta_pickup = state.sim_time
        v.status = "loading"
        v.busy_until = state.sim_time + timedelta(minutes=LOAD_MIN)
    elif v.status == "with_patient" and trip:
        trip.status = "completed"
        trip.eta_dropoff = state.sim_time
        trip.delay_min = round(max(0.0, (state.sim_time - trip.due_by).total_seconds() / 60), 1)
        dest = state.places[trip.dropoff_id]
        if dest.capacity is not None and trip.kind == "patient":
            dest.capacity = max(0, dest.capacity - 1)  # one admission used
        v.current_trip_id = None
        v.status = "returning"
        v.busy_until = state.sim_time + timedelta(minutes=UNLOAD_MIN)
    elif v.status == "returning":
        v.status = "idle"
