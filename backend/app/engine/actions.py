"""Actions that change assignments. Used by the operator (approve) and by what-if simulation."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Trip, Vehicle
from .projection import free_capacity

if TYPE_CHECKING:
    from ..state import WorldState

EQUIPMENT_CARRIERS = ("ambulance", "transport")  # vehicle types that may carry equipment transfers


class ActionError(ValueError):
    """An action that cannot be applied; the message is safe to show to the operator."""


def can_serve(v: Vehicle, trip: Trip) -> tuple[bool, str | None]:
    if v.status == "out_of_service":
        return False, f"{v.name} is out of service"
    if trip.needs == "equipment" and v.type not in EQUIPMENT_CARRIERS:
        return False, f"{v.name} cannot carry equipment transfers"
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


def check_redirect(state: WorldState, trip: Trip, dropoff_id: str) -> None:
    """A redirect must take a patient to a general hospital that can still admit them."""
    place = state.places.get(dropoff_id)
    if place is None:
        raise ActionError(f"Unknown place {dropoff_id}")
    if trip.kind != "patient":
        raise ActionError(f"Trip {trip.id} carries equipment; only patients are redirected to another hospital")
    if place.kind != "hospital":
        raise ActionError(f"{place.name} is not a hospital")
    if place.specialty:
        raise ActionError(f"{place.name} is a specialised ({place.specialty}) hospital; redirect to a general hospital")
    free = free_capacity(state, place.id, exclude_trip=trip.id)
    if free is not None and free < 1:
        raise ActionError(f"{place.name} has no free capacity (can admit {place.capacity}, {place.capacity - free} incoming)")


def assign_trip(
    state: WorldState,
    trip_id: str,
    vehicle_id: str,
    position: int | None = None,
    interrupt_current: bool = False,
    dropoff_id: str | None = None,
) -> None:
    trip = state.trips.get(trip_id)
    if trip is None:
        raise ActionError(f"Unknown trip {trip_id}")
    v = state.vehicles.get(vehicle_id)
    if v is None:
        raise ActionError(f"Unknown vehicle {vehicle_id}")
    redirect = dropoff_id is not None and dropoff_id != trip.dropoff_id
    # Redirect in place: same vehicle, no new position -> only the destination changes. This is
    # the one change allowed for a trip with its patient on board (the vehicle is diverted).
    in_place = redirect and trip.vehicle_id == v.id and position is None and not interrupt_current
    if trip.status in ("completed", "cancelled"):
        raise ActionError(f"Trip {trip_id} is {trip.status} and cannot be reassigned")
    if trip.status == "onboard" and not in_place:
        hint = " (to redirect it, keep its vehicle and use position null)" if redirect else ""
        raise ActionError(f"Trip {trip_id} is onboard and cannot be reassigned{hint}")
    if trip.status != "onboard":
        ok, why = can_serve(v, trip)
        if not ok:
            raise ActionError(why or "Vehicle cannot serve this trip")
    if redirect:
        assert dropoff_id is not None
        check_redirect(state, trip, dropoff_id)
    current = state.trips.get(v.current_trip_id) if v.current_trip_id else None
    if interrupt_current and current and current.id != trip.id and current.status == "onboard":
        load = "a patient" if current.kind == "patient" else f"equipment ({current.cargo})"
        raise ActionError(f"{v.name} has {load} on board and cannot be diverted")

    # All checks passed: from here on nothing raises.
    if redirect:
        old = state.places.get(trip.dropoff_id)
        trip.dropoff_id = dropoff_id  # type: ignore[assignment]
        trip.note = "; ".join(filter(None, [trip.note, f"redirected from {old.name if old else '?'}"]))
        if in_place:
            return

    detach_trip(state, trip)
    if interrupt_current and v.current_trip_id:
        current = state.trips[v.current_trip_id]
        current.status = "assigned"
        v.queue.insert(0, current.id)
        v.current_trip_id = None
        position = 0

    pos = len(v.queue) if position is None else max(0, min(position, len(v.queue)))
    v.queue.insert(pos, trip.id)
    trip.vehicle_id = v.id
    trip.status = "assigned"
