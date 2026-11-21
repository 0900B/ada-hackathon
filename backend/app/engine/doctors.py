"""Doctor cars and reserve units (docs/DISPATCH_PRIORITIES.md).

Doctor cars (VUZ, Slovenia: an emergency physician and a nurse) drive separately and join the
ambulance crew on scene for the red calls that need a doctor (severity.DOCTOR_CONDITIONS); they never
transport a patient. For such a call the engine sends the ambulance by the dispatch rules and the
doctor car that reaches the scene first (a free one; a doctor car is never pulled off a scene). If the
helicopter serves the call, its doctor is on board and no doctor car goes. A doctor car stays on scene
while the crew works, escorts the ambulance to hospital (the doctor rides along, the car follows) and
then returns to its base (sim/simulator.py).

Reserve units (a neighbouring station's ambulance, a private ambulance) are not part of the world
until a dispatcher requests one: an approved plan step that names it activates it (actions.assign_trip).
When no own unit reaches a red call within 15 min, the options offer them (reserve_options).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ..models import Trip, Vehicle
from ..routing import flies, travel_minutes, vehicle_leg_minutes
from .severity import DOCTOR_TARGET_MIN, RED_REFERENCE_MIN

if TYPE_CHECKING:
    from ..state import WorldState

LJ = ZoneInfo("Europe/Ljubljana")
DONE = ("completed", "cancelled")


def _hhmm(dt: datetime | None) -> str:
    return dt.astimezone(LJ).strftime("%H:%M") if dt else "?"


def _mins(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds() / 60


def doctor_cars(state: WorldState) -> list[Vehicle]:
    return [v for v in state.vehicles.values() if v.type == "doctor"]


def is_doctor_free(v: Vehicle) -> bool:
    return v.type == "doctor" and v.status in ("idle", "returning") and v.current_trip_id is None


def doctor_arrival(state: WorldState, v: Vehicle, trip: Trip) -> datetime:
    """When doctor car v would reach the patient of trip, leaving now (or when its handover ends)."""
    p = state.places[trip.pickup_id]
    start = max(state.sim_time, v.busy_until) if v.busy_until else state.sim_time
    if v.current_trip_id == trip.id and v.status == "to_pickup":
        minutes = vehicle_leg_minutes(state, v, p.lat, p.lon, True)
    else:
        minutes = travel_minutes(state, v.lat, v.lon, p.lat, p.lon, v.type, True)
    return start + timedelta(minutes=minutes)


def release(state: WorldState, trip: Trip) -> str | None:
    """Stand down the doctor car of trip if it has not reached the scene yet; returns its id."""
    v = state.vehicles.get(trip.doctor_vehicle_id) if trip.doctor_vehicle_id else None
    if v is None or v.type != "doctor" or v.current_trip_id != trip.id:
        return None
    if v.status == "to_pickup":
        v.current_trip_id, v.status = None, "returning"
    return v.id


def send_doctor(state: WorldState, trip: Trip, unit_id: str | None = None, unit_reach: datetime | None = None) -> str:
    """Make sure a call that needs a doctor gets one. Returns a clause for the summary ("" if nothing
    to say). unit_id/unit_reach: the unit just dispatched and when it reaches the patient."""
    if not trip.needs_doctor or trip.status in DONE:
        return ""
    unit = state.vehicles.get(unit_id or trip.vehicle_id or "")
    reach = unit_reach or trip.eta_pickup
    current = state.vehicles.get(trip.doctor_vehicle_id) if trip.doctor_vehicle_id else None
    free = [v for v in doctor_cars(state) if is_doctor_free(v)]
    if unit is not None and flies(unit.type):
        # The helicopter's doctor is enough when it is there within the reference; otherwise a doctor
        # car that gets there sooner goes too (first doctor on scene).
        heli_wait = _mins(max(reach, trip.pickup_after), trip.pickup_after) if reach else 0.0
        faster = [v for v in free if reach and doctor_arrival(state, v, trip) < reach]
        if current is not None and current.type == "doctor" and current.current_trip_id == trip.id and heli_wait > DOCTOR_TARGET_MIN:
            return ""  # keeps its doctor car
        if heli_wait <= DOCTOR_TARGET_MIN or not faster:
            released = release(state, trip)
            trip.doctor_vehicle_id, trip.doctor_eta = unit.id, reach
            return f" (doctor on board{f'; {released} stood down' if released else ''})"
    if current is not None and current.type == "doctor" and current.current_trip_id == trip.id:
        return ""  # already has its doctor car
    if not free:
        trip.doctor_vehicle_id, trip.doctor_eta = None, None
        busy = [v.id for v in doctor_cars(state) if v.status != "out_of_service"]
        why = f"no doctor car free ({', '.join(busy)} busy)" if busy else "no doctor car in service"
        return f"; {why}: consider the helicopter (doctor on board)"
    best = min(free, key=lambda v: doctor_arrival(state, v, trip))
    at = doctor_arrival(state, best, trip)
    best.current_trip_id, best.queue, best.status, best.waiting_until = trip.id, [], "to_pickup", None
    trip.doctor_vehicle_id, trip.doctor_eta = best.id, at
    if reach is None:
        rel = ""
    elif abs(_mins(at, reach)) < 1:
        rel = ", with the ambulance"
    else:
        what = "the helicopter" if unit is not None and flies(unit.type) else "the ambulance"
        rel = f", {_mins(at, reach):.0f} min after {what}" if at > reach else f", {_mins(reach, at):.0f} min before {what}"
    from .candidates import nearest_place_name  # local import: candidates imports this module

    clause = f" + doctor {best.id} ({nearest_place_name(state, best.lat, best.lon)}, at {_who(trip)} {_hhmm(at)}{rel})"
    wait = _mins(max(at, trip.pickup_after), trip.pickup_after)
    if wait > (trip.doctor_target_min or DOCTOR_TARGET_MIN):
        heli = "" if unit is not None and flies(unit.type) else ": consider the helicopter"
        clause += f"; the doctor arrives {wait:.0f} min after the call (reference {DOCTOR_TARGET_MIN:.0f} min){heli}"
    return clause


def _who(trip: Trip) -> str:
    return "the patient" if trip.kind == "patient" else "the pickup"


def ensure_after_plan(state: WorldState, trip_ids: list[str]) -> list[str]:
    """After an approved plan: a call that moved to the helicopter stands its doctor car down; one that
    moved from the helicopter to an ambulance gets a doctor car. Returns summary clauses."""
    out = []
    for tid in dict.fromkeys(trip_ids):
        trip = state.trips.get(tid)
        if trip is None or not trip.needs_doctor or trip.status in DONE:
            continue
        unit = state.vehicles.get(trip.vehicle_id) if trip.vehicle_id else None
        holder = state.vehicles.get(trip.doctor_vehicle_id) if trip.doctor_vehicle_id else None
        if holder is not None and flies(holder.type) and holder.id != trip.vehicle_id:
            trip.doctor_vehicle_id = trip.doctor_eta = None  # the helicopter no longer serves it
        if unit is None:
            continue
        clause = send_doctor(state, trip, unit.id)
        if clause:
            out.append(f"{trip.id}{clause}")
    return out


def project_doctors(state: WorldState) -> None:
    """Doctor arrival times: a doctor car on its way, or the helicopter serving the call."""
    for v in doctor_cars(state):
        trip = state.trips.get(v.current_trip_id) if v.current_trip_id else None
        if trip is not None and v.status == "to_pickup" and trip.doctor_vehicle_id == v.id:
            trip.doctor_eta = doctor_arrival(state, v, trip)
    for trip in state.trips.values():
        if not trip.needs_doctor or trip.status in DONE:
            continue
        unit = state.vehicles.get(trip.vehicle_id) if trip.vehicle_id else None
        if unit is not None and flies(unit.type) and trip.doctor_vehicle_id in (None, unit.id):
            trip.doctor_vehicle_id, trip.doctor_eta = unit.id, trip.eta_pickup
        elif unit is not None and flies(unit.type) and trip.status == "onboard":
            trip.doctor_vehicle_id = unit.id  # lifted off: the helicopter's doctor takes over (the car goes home)


# --- Reserve units: mutual aid and private ambulances ------------------------------------------


def activate_reserve(state: WorldState, vehicle_id: str) -> Vehicle:
    """Bring a requested reserve unit into the world, free at its base."""
    v = state.reserve_vehicles.pop(vehicle_id)
    base = state.places[v.base_id]
    v.lat, v.lon, v.status = base.lat, base.lon, "idle"
    v.current_trip_id, v.queue, v.busy_until, v.waiting_until = None, [], None, None
    v.path_from = v.path_to = v.path_avoid = v.snap_offset = None
    v.path_progress, v.on_road = 0.0, False
    state.vehicles[v.id] = v
    return v


def stand_down_reserve(state: WorldState, v: Vehicle) -> None:
    """A reserve unit back at its base with nothing to do leaves the world again."""
    state.vehicles.pop(v.id, None)
    v.status, v.current_trip_id, v.queue = "idle", None, []
    state.reserve_vehicles[v.id] = v


def reserve_area(state: WorldState, v: Vehicle) -> str:
    """Where a reserve unit comes from, e.g. "Domžale" (the last word of its base's name)."""
    return state.places[v.base_id].name.rsplit(" ", 1)[-1]


def origin_label(state: WorldState, v: Vehicle) -> str:
    area = reserve_area(state, v)
    return {"mutual_aid": f"mutual aid from {area}", "private": f"private ambulance, {area}"}.get(v.origin, area)


def reserve_options(state: WorldState) -> list[dict]:
    """For every red call no own unit reaches within the 15-min reference: what each reserve unit
    would do, simulated. [{trip_id, vehicle_id, origin, title, reach, wait_min, now_wait_min, steps, step_details}]"""
    from ..models import Plan, PlanStep
    from .plans import simulate_plan
    from .projection import red_wait_min

    out = []
    slow = [(t, w) for t in state.trips.values() if (w := red_wait_min(t)) is not None and w > RED_REFERENCE_MIN]
    for trip, now_wait in sorted(slow, key=lambda x: -x[1])[:2]:
        for r in state.reserve_vehicles.values():
            step = PlanStep(trip_id=trip.id, vehicle_id=r.id)
            result = simulate_plan(state, Plan(steps=[step]))
            if not result["feasible"] or not result["step_details"]:
                continue
            d = result["step_details"][0]
            reach = d["pickup_at"]
            wait = _mins(max(reach, trip.pickup_after), trip.pickup_after)
            if wait >= now_wait - 1:
                continue  # no faster than what is already sent
            where = reserve_area(state, r)
            out.append(
                {
                    "trip_id": trip.id,
                    "vehicle_id": r.id,
                    "origin": r.origin,
                    "title": f"Request mutual aid: {r.id} from {where}, at the patient {_hhmm(reach)}"
                    if r.origin == "mutual_aid"
                    else f"Private ambulance {r.id} ({where}), at the patient {_hhmm(reach)}",
                    "reach": reach,
                    "wait_min": round(wait, 1),
                    "now_wait_min": round(now_wait, 1),
                    "steps": [PlanStep(**s) for s in result["steps"]],
                    "step_details": result["step_details"],
                }
            )
    return out
