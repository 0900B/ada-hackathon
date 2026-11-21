"""Moves vehicles along their routes each tick. Stands in for a live GPS/AVL feed."""
from __future__ import annotations

import math
from datetime import timedelta
from typing import TYPE_CHECKING

from ..engine.doctors import stand_down_reserve
from ..engine.service_times import HANDOVER_MIN, after_dropoff_min, on_scene_min, turnout_min
from ..models import Vehicle
from ..roads import ROADS, key, nearest_fraction, point_along
from ..geo import haversine_km
from .fleet_details import fuel_rate
from ..routing import flies, leg_route, reroute_if_blocked, travel_minutes

if TYPE_CHECKING:
    from ..state import WorldState


MERGE_M = 100.0  # a vehicle that snaps onto a road route mid-leg closes the gap by this much per tick


def tick(state: WorldState, dt_s: float) -> None:
    state.sim_time += timedelta(seconds=dt_s)
    for v in list(state.vehicles.values()):
        if v.grounded_until and state.sim_time >= v.grounded_until:
            v.grounded_until = None  # the fog has lifted: the helicopter can fly again
        if v.status == "out_of_service":
            v.waiting_until = None
            continue
        if v.busy_until and state.sim_time < v.busy_until:
            continue
        v.busy_until = None
        before = (v.lat, v.lon)
        if v.type == "doctor":
            _advance_doctor(state, v, dt_s / 60)
        else:
            _advance(state, v, dt_s / 60)
        _account_distance(state, v, before)
        if v.origin != "own" and v.status == "idle" and v.current_trip_id is None and not v.queue:
            stand_down_reserve(state, v)  # a mutual-aid or private unit is home again: it leaves our fleet


def _advance_doctor(state: WorldState, v: Vehicle, dt_min: float) -> None:
    """A doctor car: to the scene (to_pickup), on scene with the crew (loading) until the ambulance
    leaves with the patient, then escorting it to hospital (with_patient), then home."""
    trip = state.trips.get(v.current_trip_id) if v.current_trip_id else None
    if trip is not None and (trip.status in ("completed", "cancelled") or trip.doctor_vehicle_id != v.id):
        trip = None  # the call is over, or stood down (e.g. the helicopter took it)
    if trip is None:
        v.current_trip_id = None
        if v.status != "idle":
            v.status = "returning"
            base = state.places[v.base_id]
            if _move_towards(state, v, base.lat, base.lon, dt_min, False):
                v.status = "idle"
        return
    unit = state.vehicles.get(trip.vehicle_id) if trip.vehicle_id else None
    left_scene = trip.status == "onboard" and (unit is None or unit.status != "loading")  # the ambulance drove off
    if left_scene and unit is not None and flies(unit.type):
        trip.doctor_vehicle_id = unit.id  # the helicopter's doctor flies with the patient: the car goes home
        v.current_trip_id, v.status = None, "returning"
        return
    if v.status in ("idle", "returning"):
        v.status = "to_pickup"
    if v.status == "to_pickup":
        if left_scene:
            v.status = "with_patient"  # too late for the scene: meet them at the hospital
        else:
            scene = state.places[trip.pickup_id]
            if _move_towards(state, v, scene.lat, scene.lon, dt_min, True):
                v.status = "loading"  # on scene with the crew
                trip.doctor_eta = state.sim_time
            return
    if v.status == "loading":
        if not left_scene:
            return  # treating the patient with the crew
        v.status = "with_patient"  # the doctor rides along in the ambulance; the car follows
    dest = state.places[trip.dropoff_id]
    if _move_towards(state, v, dest.lat, dest.lon, dt_min, True):
        v.current_trip_id = None
        v.status = "returning"
        v.busy_until = state.sim_time + timedelta(minutes=HANDOVER_MIN)  # the doctor hands over with the crew


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
        v.snap_offset = None
        v.on_road = not flying and ROADS.route(v.lat, v.lon, lat, lon) is not None
        if not v.on_road and not flying:
            ROADS.want_route(v.lat, v.lon, lat, lon)  # later legs on this pair will follow the road
    if v.path_progress >= 1.0:
        return True
    assert v.path_from is not None
    if not flying:
        reroute_if_blocked(state, v)  # a closure ahead: re-plan the rest of the leg around it
        if not v.on_road:
            route = leg_route(state, v)
            if route is not None:
                # The road route (or detour) arrived mid-leg. Continue from the road point nearest to
                # where the vehicle is (not the same fraction of a longer road, which can be far
                # away) and merge the remaining gap over the next ticks, so the marker never jumps.
                v.on_road = True
                v.path_progress = nearest_fraction(route, v.lat, v.lon)
                rlat, rlon = point_along(route, v.path_progress)
                v.snap_offset = (v.lat - rlat, v.lon - rlon)
            elif v.path_avoid and not ROADS.detours_available():
                ROADS.want_route(v.path_from[0], v.path_from[1], lat, lon)  # no detour possible: plain route
    total = travel_minutes(state, v.path_from[0], v.path_from[1], lat, lon, v.type, emergency)
    v.path_progress = 1.0 if total <= dt_min else min(1.0, v.path_progress + dt_min / total)
    if v.path_progress >= 1.0:
        v.lat, v.lon = lat, lon
        v.on_road = False
        v.path_avoid = None
        v.snap_offset = None
        return True
    route = leg_route(state, v) if v.on_road else None
    if route is not None:
        v.lat, v.lon = point_along(route, v.path_progress)
        if v.snap_offset is not None:
            # close the gap to the road by at most MERGE_M per tick (about a tick's worth of driving)
            dlat, dlon = v.snap_offset
            gap_m = math.hypot(dlat * 110_540, dlon * 111_320 * math.cos(math.radians(v.lat)))
            left = max(0.0, gap_m - MERGE_M)
            v.snap_offset = None if left < 5 else (dlat * left / gap_m, dlon * left / gap_m)
            if v.snap_offset is not None:
                v.lat, v.lon = v.lat + v.snap_offset[0], v.lon + v.snap_offset[1]
    else:
        v.lat = v.path_from[0] + (lat - v.path_from[0]) * v.path_progress
        v.lon = v.path_from[1] + (lon - v.path_from[1]) * v.path_progress
    return False


def _advance(state: WorldState, v: Vehicle, dt_min: float) -> None:
    v.waiting_until = None  # set again below while it stands at a pickup that is not ready yet
    if v.status == "loading":
        v.status = "with_patient"

    if v.current_trip_id is None and v.status != "with_patient":
        if v.queue:
            turnout = turnout_min(v)  # from rest at its base: the crew gets going first
            v.current_trip_id = v.queue.pop(0)
            state.trips[v.current_trip_id].status = "en_route_pickup"
            v.status = "to_pickup"
            if turnout:
                v.busy_until = state.sim_time + timedelta(minutes=turnout)
                return
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
            v.waiting_until = trip.pickup_after  # early: wait at the pickup (visible on the map/card)
            return
        trip.status = "onboard"
        trip.eta_pickup = state.sim_time
        v.status = "loading"  # on scene: assessment, treatment, loading
        v.busy_until = state.sim_time + timedelta(minutes=on_scene_min(trip, v.type))
    elif v.status == "with_patient" and trip:
        trip.status = "completed"
        trip.eta_dropoff = state.sim_time
        trip.delay_min = round(max(0.0, (state.sim_time - trip.due_by).total_seconds() / 60), 1)
        dest = state.places[trip.dropoff_id]
        if dest.capacity is not None and trip.kind == "patient":
            dest.capacity = max(0, dest.capacity - 1)  # one admission used
        v.current_trip_id = None
        v.status = "returning"  # handover, then cleaning and restocking: not available until busy_until
        v.busy_until = state.sim_time + timedelta(minutes=after_dropoff_min(trip, v.type))
    elif v.status == "returning":
        v.status = "idle"
