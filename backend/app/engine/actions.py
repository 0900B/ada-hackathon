"""Actions that change assignments. Used by the operator (approve) and by what-if simulation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .. import hems
from ..models import Trip, Vehicle
from .projection import free_capacity
from .severity import NEAR_PATIENT_MIN, SEVERITY_RANK, WEIGHT_CLEARLY_HIGHER

if TYPE_CHECKING:
    from ..state import WorldState

LJ = ZoneInfo("Europe/Ljubljana")
EQUIPMENT_CARRIERS = ("ambulance", "transport")  # equipment goes by road; the helicopter stays free for patients
# Dispatch model (a fictional independent EMS operator, close to how Slovenian EMS works):
# - ambulances (A*) are the emergency units: emergencies and urgent calls, dispatched on
#   availability and proximity. They start the day free and never hold a long queue.
# - transport vans (T*) do the scheduled day (seated, wheelchair and stretcher patients,
#   equipment) and urgent non-emergency trips; never emergencies.
# - the helicopter (H1) only flies emergencies and urgent trips (never routine work or cargo).
EMERGENCY_UNITS = ("ambulance", "helicopter")
MAX_QUEUED_EMERGENCY_UNIT = 1  # an emergency unit holds its current job plus at most this many queued
# Ambulances take emergencies and urgent trips only; every scheduled pickup/transfer goes to a van.
# (Team decision for now; set True to let the engine use a free ambulance for a scheduled trip again.)
AMBULANCES_TAKE_SCHEDULED = False


class ActionError(ValueError):
    """An action that cannot be applied; the message is safe to show to the operator."""


def can_serve(v: Vehicle, trip: Trip, now: datetime | None = None) -> tuple[bool, str | None]:
    """Can v take trip? now (the world clock): the helicopter takes new calls only in its operating
    hours (app/hems.py); a trip it already has (a mission under way) stays with it."""
    if v.type == "doctor":
        return False, f"{v.name} is a doctor car: it joins the ambulance crew on scene and never transports patients"
    if v.status == "out_of_service":
        return False, f"{v.name} is out of service"
    if v.contract_ended:
        return False, f"{v.name}'s contract has ended: it finishes its current job and leaves"
    if v.grounded_until is not None:  # cleared by the simulator when the fog lifts
        until = v.grounded_until.astimezone(LJ).strftime("%H:%M")
        return False, f"{v.name} is grounded by fog until {until} and cannot take new flights"
    if (
        now is not None
        and hems.off_duty_until(v, now) is not None
        and trip.id != v.current_trip_id
        and trip.id not in v.queue
    ):
        return False, hems.night_reason(v, now)
    if trip.needs == "equipment" and v.type not in EQUIPMENT_CARRIERS:
        return False, f"{v.name} cannot carry equipment transfers"
    if v.type == "transport" and trip.priority == "emergency":
        return False, f"{v.name} is a transport van; emergencies need an ambulance"
    if v.type == "helicopter" and trip.priority == "scheduled":
        return False, f"{v.name} only flies emergencies and urgent trips; scheduled trips go by road"
    if v.type == "ambulance" and trip.priority == "scheduled" and not AMBULANCES_TAKE_SCHEDULED:
        return False, f"{v.name} is an emergency ambulance; scheduled transports go to the transport vans"
    if v.type in EMERGENCY_UNITS:
        jobs = [t for t in ([v.current_trip_id] if v.current_trip_id else []) + list(v.queue) if t != trip.id]
        if len(jobs) > MAX_QUEUED_EMERGENCY_UNIT:
            return False, (
                f"{v.name} already has {len(jobs)} jobs ({', '.join(jobs)}); an emergency unit takes at most "
                f"its current job plus {MAX_QUEUED_EMERGENCY_UNIT} queued trip"
            )
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


def level(trip: Trip) -> int:
    """Severity rank: 0 critical, 1 serious, 2 urgent, 3 routine (see engine/severity.py)."""
    return SEVERITY_RANK.get(trip.severity or "", PRIORITY_RANK[trip.priority] + 1)


def goes_before(a: Trip, b: Trip) -> bool:
    """a should be served before b: a higher level, or the same level and clearly more time-critical."""
    return level(a) < level(b) or (level(a) == level(b) and a.time_weight >= b.time_weight + WEIGHT_CLEARLY_HIGHER)


def near_current_patient(state: WorldState, v: Vehicle, current: Trip | None) -> float | None:
    """Minutes v still needs to reach its current (not yet loaded) patient if that is at most
    NEAR_PATIENT_MIN (0 = on scene, e.g. waiting there); None if it is farther or has no such job."""
    from ..routing import vehicle_leg_minutes  # local import: routing is heavier and not needed elsewhere here

    if current is None or current.status == "onboard" or v.current_trip_id != current.id or v.status != "to_pickup":
        return None
    p = state.places[current.pickup_id]
    minutes = vehicle_leg_minutes(state, v, p.lat, p.lon, current.priority == "emergency")
    return minutes if minutes <= NEAR_PATIENT_MIN else None


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
    reserve = v is None and vehicle_id in state.reserve_vehicles  # mutual aid / private: activated below
    if reserve:
        from .doctors import PER_CALL_RESERVE

        v = state.reserve_vehicles[vehicle_id]
        if vehicle_id not in PER_CALL_RESERVE:
            raise ActionError(f"{v.name} is contracted surge capacity: activate surge capacity first")
        if trip.priority != "emergency":
            raise ActionError(f"{v.name} is a reserve unit: requested only for red (critical or serious) calls")
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
        ok, why = can_serve(v, trip, state.sim_time)
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
        rank = level(trip)
        near = near_current_patient(state, v, current)
        if trip.priority == "emergency" and not interrupt_current:
            # Critical and serious calls go first: before every queued trip they rank above (a lower
            # level, or the same level and clearly less time-critical), turning the unit around from a
            # lower-level pickup unless it is already at or next to that patient. With a patient on
            # board the current job is finished first.
            behind = [goes_before(trip, state.trips[t]) for t in queue]
            if current and current.status != "onboard" and level(current) > rank and near is None and all(behind):
                interrupt_current = True
            else:
                position = next((i for i, b in enumerate(behind) if b), len(queue))
        if interrupt_current and current:
            if current.status == "onboard":
                load = "a patient" if current.kind == "patient" else f"equipment ({current.cargo})"
                raise ActionError(f"{v.name} has {load} on board and cannot be diverted")
            if near is not None:
                where = "is on scene with" if near < 0.5 else f"is {near:.0f} min from"
                raise ActionError(f"{v.name} {where} the patient of {current.id} and is not diverted")
            # A higher-level job is never given up. A same-level one only by an explicit step (a swap:
            # the plan gives that patient to another unit); the engine never does it by itself.
            if level(current) < rank:
                raise ActionError(
                    f"{v.name} is on its way to {current.severity} call {current.id} and cannot be diverted "
                    f"for {trip.severity} call {trip.id}"
                )
        if interrupt_current and not current:
            interrupt_current, position = False, 0  # nothing to turn away from: simply next
        # Never ahead of a queued trip with a higher level.
        first_ok = 1 + max((i for i, t in enumerate(queue) if level(state.trips[t]) < rank), default=-1)
        wanted = 0 if interrupt_current else position
        if wanted is not None and min(wanted, len(queue)) < first_ok:
            blocker = state.trips[queue[first_ok - 1]]
            raise ActionError(
                f"{trip.id} ({trip.priority}) cannot go before {blocker.id} ({blocker.priority}) in {v.name}'s queue: "
                f"higher priority goes first (use position {first_ok} or later)"
            )

    # All checks passed: from here on nothing raises.
    if reserve:
        from .doctors import activate_reserve  # local import: doctors imports routing

        v = activate_reserve(state, v.id)
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
