"""Actions that change assignments. Used by the operator (approve) and by what-if simulation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ..models import Trip, Vehicle
from .projection import free_capacity

if TYPE_CHECKING:
    from ..state import WorldState

LJ = ZoneInfo("Europe/Ljubljana")
EQUIPMENT_CARRIERS = ("ambulance", "transport")  # equipment goes by road; the helicopter stays free for patients


class ActionError(ValueError):
    """An action that cannot be applied; the message is safe to show to the operator."""


def can_serve(v: Vehicle, trip: Trip) -> tuple[bool, str | None]:
    if v.status == "out_of_service":
        return False, f"{v.name} is out of service"
    if v.grounded_until is not None:  # cleared by the simulator when the fog lifts
        until = v.grounded_until.astimezone(LJ).strftime("%H:%M")
        return False, f"{v.name} is grounded by fog until {until} and cannot take new flights"
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


PRIORITY_RANK = {"emergency": 0, "urgent": 1, "scheduled": 2}


@dataclass
class Placement:
    """What assign_trip actually did (positions are normalised, see assign_trip)."""

    in_place: bool = False  # only the destination changed; the trip kept its place
    interrupted: str | None = None  # the current trip the vehicle turned away from (back to its queue)
    position: int | None = None  # index the trip was inserted at in the queue


def _anchor_to_position(
    state: WorldState, v: Vehicle, current_id: str | None, queue: list[str], anchor: str, fallback: int | None
) -> tuple[int | None, bool]:
    """Turn 'right before trip <anchor>' into (position, interrupt_current) for the route as it is now.

    The anchor is the trip that followed this one when the engine checked the plan. If the vehicle has
    started on the anchor meanwhile (popped it from its queue), the trip still goes before it: the
    vehicle turns around, unless the anchor is already on board.
    """
    if anchor in queue:
        return queue.index(anchor), False
    if anchor == current_id:
        return 0, state.trips[anchor].status != "onboard"
    return (None if fallback is None else 0), False  # the anchor is gone (done or moved): as planned, else next


def assign_trip(
    state: WorldState,
    trip_id: str,
    vehicle_id: str,
    position: int | None = None,
    interrupt_current: bool = False,
    dropoff_id: str | None = None,
    before_trip_id: str | None = None,
) -> Placement:
    """Put a trip on a vehicle (or redirect it). Raises ActionError, changing nothing, if it can't.

    Ordering rules, so that what a plan says is what the vehicle does:
    - before_trip_id (set by the engine when it checks a plan) replaces position/interrupt_current.
    - An emergency always goes first: before every trip not yet picked up (the vehicle turns around
      if it is driving to a non-emergency pickup). It never waits behind work it has not started.
    - No trip is placed ahead of a queued trip with a higher priority, and a vehicle is never
      diverted from a trip of higher priority or from an emergency.
    """
    trip = state.trips.get(trip_id)
    if trip is None:
        raise ActionError(f"Unknown trip {trip_id}")
    v = state.vehicles.get(vehicle_id)
    if v is None:
        raise ActionError(f"Unknown vehicle {vehicle_id}")
    redirect = dropoff_id is not None and dropoff_id != trip.dropoff_id
    # Redirect in place: same vehicle, no new position -> only the destination changes. This is
    # the one change allowed for a trip with its patient on board (the vehicle is diverted).
    in_place = (
        redirect and trip.vehicle_id == v.id and position is None and not interrupt_current and before_trip_id is None
    )
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

    if not in_place:
        # The vehicle's route without this trip (it may already be on it, e.g. a re-order).
        current_id = v.current_trip_id if v.current_trip_id != trip.id else None
        queue = [t for t in v.queue if t != trip.id]
        current = state.trips.get(current_id) if current_id else None
        if before_trip_id is not None:
            position, interrupt_current = _anchor_to_position(state, v, current_id, queue, before_trip_id, position)
        rank = PRIORITY_RANK[trip.priority]
        if trip.priority == "emergency" and not interrupt_current:
            # Emergencies go first: turn around from a non-emergency pickup, else right after the
            # current job (with a patient on board it is finished first), behind earlier emergencies.
            if current and current.status != "onboard" and current.priority != "emergency" and not any(
                state.trips[t].priority == "emergency" for t in queue
            ):
                interrupt_current = True
            else:
                position = next((i for i, t in enumerate(queue) if state.trips[t].priority != "emergency"), len(queue))
        if interrupt_current and current:
            if current.status == "onboard":
                load = "a patient" if current.kind == "patient" else f"equipment ({current.cargo})"
                raise ActionError(f"{v.name} has {load} on board and cannot be diverted")
            if current.priority == "emergency" or PRIORITY_RANK[current.priority] < rank:
                raise ActionError(
                    f"{v.name} is on its way to {current.priority} trip {current.id} and cannot be diverted "
                    f"for {trip.priority} trip {trip.id}"
                )
        if interrupt_current and not current:
            interrupt_current, position = False, 0  # nothing to turn away from: simply next
        # Never ahead of a queued trip with a higher priority.
        first_ok = 1 + max((i for i, t in enumerate(queue) if PRIORITY_RANK[state.trips[t].priority] < rank), default=-1)
        wanted = 0 if interrupt_current else position
        if wanted is not None and min(wanted, len(queue)) < first_ok:
            blocker = state.trips[queue[first_ok - 1]]
            raise ActionError(
                f"{trip.id} ({trip.priority}) cannot go before {blocker.id} ({blocker.priority}) in {v.name}'s queue: "
                f"higher priority goes first (use position {first_ok} or later)"
            )

    # All checks passed: from here on nothing raises.
    if redirect:
        old = state.places.get(trip.dropoff_id)
        trip.dropoff_id = dropoff_id  # type: ignore[assignment]
        trip.note = "; ".join(filter(None, [trip.note, f"redirected from {old.name if old else '?'}"]))
        if in_place:
            return Placement(in_place=True)

    detach_trip(state, trip)
    interrupted = None
    if interrupt_current and v.current_trip_id:
        current = state.trips[v.current_trip_id]
        current.status = "assigned"
        v.queue.insert(0, current.id)
        v.current_trip_id = None
        interrupted = current.id
        position = 0

    pos = len(v.queue) if position is None else max(0, min(position, len(v.queue)))
    v.queue.insert(pos, trip.id)
    trip.vehicle_id = v.id
    trip.status = "assigned"
    return Placement(interrupted=interrupted, position=pos)


def anchor_of(v: Vehicle, trip_id: str) -> str | None:
    """The trip right after trip_id in v's route (current + queue), None if it is last."""
    route = ([v.current_trip_id] if v.current_trip_id else []) + list(v.queue)
    i = route.index(trip_id)
    return route[i + 1] if i + 1 < len(route) else None
