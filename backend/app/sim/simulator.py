"""Moves vehicles along their routes each tick. Stands in for a live GPS/AVL feed."""
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from ..engine.projection import LOAD_MIN, UNLOAD_MIN
from ..models import Vehicle
from ..routing import travel_minutes

if TYPE_CHECKING:
    from ..state import WorldState


def tick(state: WorldState, dt_s: float) -> None:
    state.sim_time += timedelta(seconds=dt_s)
    for v in state.vehicles.values():
        if v.status == "out_of_service":
            continue
        if v.busy_until and state.sim_time < v.busy_until:
            continue
        v.busy_until = None
        _advance(state, v, dt_s / 60)


def _move_towards(state: WorldState, v: Vehicle, lat: float, lon: float, dt_min: float, emergency: bool) -> bool:
    """Move v towards (lat, lon); True when it has arrived."""
    remaining = travel_minutes(state, v.lat, v.lon, lat, lon, v.type, emergency)
    if remaining <= dt_min:
        v.lat, v.lon = lat, lon
        return True
    frac = dt_min / remaining
    v.lat += (lat - v.lat) * frac
    v.lon += (lon - v.lon) * frac
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
        v.current_trip_id = None
        v.status = "returning"
        v.busy_until = state.sim_time + timedelta(minutes=UNLOAD_MIN)
    elif v.status == "returning":
        v.status = "idle"
