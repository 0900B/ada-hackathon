"""Actions that change assignments. Used by the operator (approve) and by what-if simulation."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Trip, Vehicle

if TYPE_CHECKING:
    from ..state import WorldState


class ActionError(ValueError):
    """An action that cannot be applied; the message is safe to show to the operator."""


def can_serve(v: Vehicle, trip: Trip) -> tuple[bool, str | None]:
    if v.status == "out_of_service":
        return False, f"{v.name} is out of service"
    if v.type == "transport":
        if trip.needs == "stretcher":
            return False, f"{v.name} is a transport van and cannot carry stretcher patients"
        if trip.priority == "emergency":
            return False, f"{v.name} is a transport van; emergencies need an ambulance"
    return True, None


def detach_trip(state: WorldState, trip: Trip) -> None:
    if trip.vehicle_id and (v := state.vehicles.get(trip.vehicle_id)):
        if trip.id in v.queue:
            v.queue.remove(trip.id)
        if v.current_trip_id == trip.id:
            v.current_trip_id = None
    trip.vehicle_id = None


def assign_trip(
    state: WorldState,
    trip_id: str,
    vehicle_id: str,
    position: int | None = None,
    interrupt_current: bool = False,
) -> None:
    trip = state.trips.get(trip_id)
    if trip is None:
        raise ActionError(f"Unknown trip {trip_id}")
    v = state.vehicles.get(vehicle_id)
    if v is None:
        raise ActionError(f"Unknown vehicle {vehicle_id}")
    if trip.status in ("completed", "cancelled", "onboard"):
        raise ActionError(f"Trip {trip_id} is {trip.status} and cannot be reassigned")
    ok, why = can_serve(v, trip)
    if not ok:
        raise ActionError(why or "Vehicle cannot serve this trip")

    detach_trip(state, trip)
    if interrupt_current and v.current_trip_id:
        current = state.trips[v.current_trip_id]
        if current.status == "onboard":
            raise ActionError(f"{v.name} has a patient on board and cannot be diverted")
        current.status = "assigned"
        v.queue.insert(0, current.id)
        v.current_trip_id = None
        position = 0

    pos = len(v.queue) if position is None else max(0, min(position, len(v.queue)))
    v.queue.insert(pos, trip.id)
    trip.vehicle_id = v.id
    trip.status = "assigned"
