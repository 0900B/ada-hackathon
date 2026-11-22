"""The dispatcher intervenes in a case: the alternatives for one of its units, and assigning a unit by hand.

- alternatives(state, trip_id, role): GET /{world}/trips/{trip_id}/alternatives?role=ambulance|doctor|helicopter.
  Every unit of that role, ranked by when it would reach the patient, computed by the engine
  (find_candidates simulates each option on a copy of the world): eta, minutes sooner or later than the
  current unit (delta_min, negative = sooner), whether it is free, and what it costs ("free",
  "diverts TR-003 (urgent), which then waits 12 min longer", "helicopter, doctor on board",
  "private, needs surge capacity"). Units that cannot take the call now are listed as infeasible with why.
- assign(state, trip_id, vehicle_id, mode): POST /{world}/trips/{trip_id}/assign. "replace" swaps the
  transporting unit (or the doctor car, when vehicle_id is a doctor car); "add" adds a doctor car, or a
  further ambulance or the helicopter for another patient of the same call (a linked trip with the same
  call record, linked_to = the trip). The transporting unit goes through the plan path (simulated first,
  then applied and audited like an approved plan); timeline kind "override" by "dispatcher".
  Refused (OverrideError 400) with the reason when it cannot be done, e.g. a patient on board.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .audit import AUDIT
from .engine import timeline, units
from .engine.actions import ActionError, can_serve
from .engine.candidates import find_candidates, nearest_place_name
from .engine.doctors import (
    PER_CALL_RESERVE,
    dispatch_doctor_car,
    doctor_arrival,
    doctor_cars,
    is_doctor_free,
    release,
    reserve_area,
)
from .engine.plans import apply_plan, simulate_plan, simulate_steps
from .engine.projection import project_all
from .engine.service_times import on_scene_min, turnout_min
from .engine.severity import DOCTOR_TARGET_MIN, grade
from .engine.units import role_of, trip_view
from .models import Plan, PlanStep, Trip
from .routing import flies, travel_minutes

if TYPE_CHECKING:
    from .state import WorldState

ROLES = ("ambulance", "doctor", "helicopter")
DONE = ("completed", "cancelled")
LINKED_SLACK_MIN = 20  # a further unit's patient: at hospital within direct travel + on scene + this
DETAIL = "dispatcher override"


class OverrideError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def _trip(state: WorldState, trip_id: str) -> Trip:
    trip = state.trips.get(trip_id)
    if trip is None:
        raise OverrideError(404, f"Unknown trip {trip_id}")
    return trip


def _reach(trip: Trip) -> datetime | None:
    return max(trip.eta_pickup, trip.pickup_after) if trip.eta_pickup else None


def _mins(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds() / 60


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# --- Alternatives ---------------------------------------------------------------------------------


def alternatives(state: WorldState, trip_id: str, role: str) -> list[dict[str, Any]]:
    """Ranked alternatives for one role of a trip (feasible first, soonest at the patient first)."""
    if role not in ROLES:
        raise OverrideError(400, f"role must be one of {', '.join(ROLES)}")
    trip = _trip(state, trip_id)
    if trip.status in DONE:
        raise OverrideError(400, f"{trip.id} is {trip.status}")
    project_all(state)
    out = _doctor_alternatives(state, trip) if role == "doctor" else _unit_alternatives(state, trip, role)
    return sorted(out, key=lambda a: (not a["feasible"], a["eta_minutes"] if a["eta_minutes"] is not None else 1e9))


def _entry(state: WorldState, v, reach: datetime | None, current_reach: datetime | None, *, free: bool,
           cost: str, feasible: bool, note: str, current: bool) -> dict[str, Any]:
    return {
        "vehicle_id": v.id,
        "type": v.type,
        "role": role_of(v),
        "eta_scene": _iso(reach),
        "eta_minutes": round(_mins(reach, state.sim_time), 1) + 0.0 if reach else None,  # (+ 0.0: never -0.0)
        "delta_min": round(_mins(reach, current_reach), 1) + 0.0 if reach and current_reach else None,
        "free": free,
        "cost_text": cost,
        "feasible": feasible,
        "note": note,
        "current": current,
    }


def _availability(state: WorldState, trip: Trip, c: dict[str, Any]) -> str:
    """Free, or what taking this call costs the unit's other work."""
    v = state.vehicles[c["vehicle_id"]]
    if c["step"]["interrupt_current"] and v.current_trip_id:
        displaced = state.trips[v.current_trip_id]
        sim, errors, _ = simulate_steps(state, Plan(steps=[PlanStep(**c["step"])]))
        after = sim.trips[displaced.id]
        before_at, after_at = _reach(displaced), _reach(after) if not errors else None
        extra = f", which then waits {_mins(after_at, before_at):.0f} min longer" if before_at and after_at else ""
        return f"diverts {displaced.id} ({displaced.severity}){extra}"
    if c["vehicle_free"]:
        return "free"
    cur = state.trips.get(v.current_trip_id) if v.current_trip_id else None
    if cur is not None and cur.status == "onboard":
        return f"available soon: finishes at {state.places[cur.dropoff_id].name} first"
    if cur is None and v.busy_until and v.busy_until > state.sim_time:
        return f"available soon: free at {timeline.hhmm(v.busy_until)}"  # handover and cleaning, or held up
    return f"busy: {c['insertion']}"


def _cost(state: WorldState, trip: Trip, c: dict[str, Any]) -> str:
    v = state.vehicles.get(c["vehicle_id"]) or state.reserve_vehicles[c["vehicle_id"]]
    if c.get("requires_request"):
        what = "mutual aid" if v.origin == "mutual_aid" else "private ambulance"
        return f"{what} from {reserve_area(state, v)}: requested for this call"
    avail = _availability(state, trip, c)
    parts = []
    if flies(v.type):
        parts.append("helicopter, doctor on board")
    if v.origin == "private":
        parts.append("private (contracted surge unit)")
    if avail != "free" or not parts:
        parts.append(avail)
    if c["takes_last_free_ambulance"]:
        parts.append("the last free ambulance")
    return "; ".join(parts)


def _unit_alternatives(state: WorldState, trip: Trip, vtype: str) -> list[dict[str, Any]]:
    current_reach = _reach(trip) if trip.vehicle_id else None
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    if trip.status == "onboard":
        cands: list[dict[str, Any]] = []
    else:
        try:
            cands = find_candidates(state, trip.id, limit=100, include_reserve=True)
        except ActionError:
            cands = []
    for c in cands:  # ranked by the engine: the first option per unit is its best one
        if c["vehicle_type"] != vtype or c["vehicle_id"] in seen or not c["trip_eta_pickup"]:
            continue
        seen.add(c["vehicle_id"])
        v = state.vehicles.get(c["vehicle_id"]) or state.reserve_vehicles[c["vehicle_id"]]
        current = v.id == trip.vehicle_id
        reach = current_reach if current and current_reach else max(c["trip_eta_pickup"], trip.pickup_after)
        out.append(_entry(state, v, reach, current_reach, free=c["vehicle_free"],
                          cost="current unit" if current else _cost(state, trip, c), feasible=True,
                          note=c["insertion"], current=current))
    for v in state.vehicles.values():  # the units of this role that cannot take it now, and why
        if v.type != vtype or v.id in seen:
            continue
        current = v.id == trip.vehicle_id
        if current:  # e.g. the patient is on board
            out.append(_entry(state, v, current_reach, current_reach, free=False, cost="current unit", feasible=True,
                              note="the patient is on board" if trip.status == "onboard" else "", current=True))
            continue
        ok, why = can_serve(v, trip)
        if trip.status == "onboard":
            why = f"the patient is on board {trip.vehicle_id}: the unit cannot be replaced"
        elif ok:
            why = "cannot take this call now (it would leave a call of the same or a higher level, or is at its patient)"
        out.append(_entry(state, v, None, current_reach, free=False, cost="not available", feasible=False,
                          note=why or "", current=False))
    if vtype == "ambulance" and trip.priority == "emergency" and trip.status != "onboard":
        p = state.places[trip.pickup_id]
        for v in state.reserve_vehicles.values():  # contracted surge capacity not active: offered, not usable yet
            if v.type != "ambulance" or v.id in seen or v.id in PER_CALL_RESERVE:
                continue
            base = state.places[v.base_id]
            mins = turnout_min(v) + travel_minutes(state, base.lat, base.lon, p.lat, p.lon, v.type, True)
            reach = state.sim_time + timedelta(minutes=mins)
            out.append(_entry(state, v, reach, current_reach, free=True, cost="private, needs surge capacity",
                              feasible=False, note="activate contracted surge capacity first", current=False))
    return out


def _doctor_alternatives(state: WorldState, trip: Trip) -> list[dict[str, Any]]:
    if trip.kind != "patient":
        raise OverrideError(400, f"{trip.id} carries equipment: no doctor")
    current_reach = trip.doctor_eta if trip.doctor_vehicle_id else None
    out = []
    for v in doctor_cars(state):
        current = v.id == trip.doctor_vehicle_id and v.current_trip_id == trip.id
        if current:
            out.append(_entry(state, v, trip.doctor_eta, current_reach, free=False, cost="current unit", feasible=True,
                              note=units._doctor_status(state, v, trip), current=True))
        elif v.status == "out_of_service":
            out.append(_entry(state, v, None, current_reach, free=False, cost="not available", feasible=False,
                              note=f"{v.name} is out of service", current=False))
        elif trip.status == "onboard":
            out.append(_entry(state, v, None, current_reach, free=is_doctor_free(v), cost="not needed", feasible=False,
                              note=f"the patient is already on board {trip.vehicle_id}", current=False))
        elif is_doctor_free(v):
            at = doctor_arrival(state, v, trip)
            out.append(_entry(state, v, at, current_reach, free=True, cost="free", feasible=True,
                              note=f"from {nearest_place_name(state, v.lat, v.lon)}, {turnout_min(v):.0f} min turnout", current=False))
        else:
            out.append(_entry(state, v, None, current_reach, free=False, cost=f"busy with {v.current_trip_id}", feasible=False,
                              note="a doctor car is never pulled off another call", current=False))
    return out


# --- Assign ---------------------------------------------------------------------------------------


def assign(state: WorldState, trip_id: str, vehicle_id: str, mode: str) -> dict[str, Any]:
    """The dispatcher puts vehicle_id on the call (replace or add). Returns {trip, summary} (+ linked_trip)."""
    if mode not in ("replace", "add"):
        raise OverrideError(400, 'mode must be "replace" or "add"')
    trip = _trip(state, trip_id)
    if trip.status in DONE:
        raise OverrideError(400, f"{trip.id} is {trip.status}")
    v = state.vehicles.get(vehicle_id) or state.reserve_vehicles.get(vehicle_id)
    if v is None:
        raise OverrideError(404, f"Unknown vehicle {vehicle_id}")
    if vehicle_id in state.reserve_vehicles and vehicle_id not in PER_CALL_RESERVE:
        raise OverrideError(400, f"{v.name} is contracted surge capacity: activate surge capacity first")
    project_all(state)
    tracker = timeline.Tracker(state)
    linked = None
    if v.type == "doctor":
        summary = _assign_doctor(state, trip, v, mode)
    elif mode == "replace":
        summary = _replace(state, trip, v)
    else:
        linked, summary = _add(state, trip, v)
    project_all(state)
    before = tracker.before.get(trip.id)
    if before is not None:  # our own "override" entry says it; the tracker logs everything else that moved
        doctor = trip.doctor_vehicle_id if v.type == "doctor" else before[1]  # e.g. a doctor car stood down for H1
        tracker.before[trip.id] = (trip.vehicle_id, doctor, before[2], before[3])
    tracker.log_changes("dispatcher", detail=DETAIL)
    state.ai_stats["overrides"] += 1
    AUDIT.record(state.name, "override", f"Dispatcher override on {trip.id}: {summary}", ref=trip.id,
                 payload={"trip_id": trip.id, "vehicle_id": vehicle_id, "mode": mode, "linked_trip_id": linked.id if linked else None})
    state.bump()
    out = {"trip": trip_view(state, trip), "summary": summary}
    if linked is not None:
        out["linked_trip"] = trip_view(state, linked)
    return out


def _candidate(state: WorldState, trip: Trip, v) -> dict[str, Any]:
    ok, why = can_serve(v, trip)
    if not ok:
        raise OverrideError(400, why or f"{v.id} cannot take {trip.id}")
    try:
        cands = find_candidates(state, trip.id, limit=100, include_reserve=True)
    except ActionError as e:
        raise OverrideError(400, str(e)) from e
    c = next((c for c in cands if c["vehicle_id"] == v.id and c["trip_eta_pickup"]), None)
    if c is None:
        raise OverrideError(400, f"{v.id} cannot take {trip.id} now: it would have to leave a call of the same or a "
                                 "higher level, or it is already at its patient")
    return c


def _apply(state: WorldState, trip: Trip, c: dict[str, Any], rationale: str) -> None:
    plan = Plan(steps=[PlanStep(**c["step"])], rationale=rationale)
    preview = simulate_plan(state, plan)
    if not preview["feasible"]:
        raise OverrideError(400, "; ".join(preview["errors"]))
    try:
        record = apply_plan(state, plan)
    except ActionError as e:
        raise OverrideError(400, str(e)) from e
    AUDIT.record(state.name, "plan_applied", record.summary, ref=record.id, payload=record)
    project_all(state)
    trip.dispatched_at = state.sim_time


def _at(trip: Trip) -> str:
    reach = _reach(trip)
    return f": at the patient {timeline.hhmm(reach)}" if reach else ""


def _replace(state: WorldState, trip: Trip, v) -> str:
    if trip.status == "onboard":
        raise OverrideError(400, f"The patient of {trip.id} is on board {trip.vehicle_id}: the unit cannot be replaced "
                                 "(the destination can still be redirected)")
    if trip.vehicle_id == v.id:
        raise OverrideError(400, f"{v.id} already serves {trip.id}")
    c = _candidate(state, trip, v)
    cost = _cost(state, trip, c)
    old, old_reach = trip.vehicle_id, _reach(trip) if trip.vehicle_id else None
    _apply(state, trip, c, f"Dispatcher override: {v.id} for {trip.id}" + (f" instead of {old}" if old else ""))
    reach = _reach(trip)
    diff = ""
    if reach and old_reach and abs(_mins(reach, old_reach)) >= 1:
        d = _mins(reach, old_reach)
        diff = f" ({abs(d):.0f} min {'sooner' if d < 0 else 'later'})"
    text = (f"Dispatcher override: {v.id} instead of {old}" if old else f"Dispatcher assigned {v.id}") + _at(trip) + diff
    timeline.log(state, trip, "override", "dispatcher", text, v.id, detail=DETAIL)
    units.note(state, trip, v.id, f"dispatcher override{f' (was {old})' if old else ''}: {cost}", "dispatcher")
    return text + (f"; {cost}" if cost != "free" else "")


def _add(state: WorldState, trip: Trip, v) -> tuple[Trip, str]:
    """A further ambulance or the helicopter for another patient of the same call: a linked trip."""
    from .engine.events import EMERGENCY_SLACK_MIN, URGENT_SLACK_MIN

    if v.type not in ("ambulance", "helicopter"):
        raise OverrideError(400, "Add a doctor car, an ambulance or the helicopter")
    if trip.kind != "patient":
        raise OverrideError(400, f"{trip.id} carries equipment: no further unit is added")
    if trip.vehicle_id == v.id or any(t.linked_to == trip.id and t.vehicle_id == v.id and t.status not in DONE for t in state.trips.values()):
        raise OverrideError(400, f"{v.id} already serves this call")
    pickup, dropoff = state.places[trip.pickup_id], state.places[trip.dropoff_id]
    n = 2 + sum(1 for t in state.trips.values() if t.linked_to == trip.id)
    direct = travel_minutes(state, pickup.lat, pickup.lon, dropoff.lat, dropoff.lon, "ambulance", True)
    slack = EMERGENCY_SLACK_MIN if trip.priority == "emergency" else URGENT_SLACK_MIN
    call_id = trip.call.call_id if trip.call else trip.id
    linked = Trip(
        id=f"TR-{len(state.trips) + 1:03d}", patient=f"{trip.patient or trip.id}-{n}", priority=trip.priority, needs=trip.needs,
        pickup_id=trip.pickup_id, dropoff_id=trip.dropoff_id, pickup_after=trip.pickup_after,
        due_by=max(trip.due_by, state.sim_time + timedelta(minutes=direct + on_scene_min(trip) + slack)).replace(microsecond=0),
        note=f"Further unit for call {call_id} (with {trip.id}), added by the dispatcher", severity=trip.severity,
        condition=trip.condition, modifiers=list(trip.modifiers), linked_to=trip.id, call=trip.call,
    )
    grade(state, linked)
    linked.needs_doctor, linked.doctor_target_min = False, None  # one doctor for the scene: the first trip's
    state.trips[linked.id] = linked
    try:
        c = _candidate(state, linked, v)
        cost = _cost(state, linked, c)
        _apply(state, linked, c, f"Dispatcher added {v.id} to call {call_id} ({linked.id}, with {trip.id})")
    except OverrideError:
        del state.trips[linked.id]
        raise
    role = role_of(v)
    timeline.log(state, linked, "received", "dispatcher", f"Further unit for call {call_id} (with {trip.id}), added by the dispatcher",
                 detail=DETAIL)
    text = f"Dispatcher added {v.id} ({role}) for a further patient: {linked.id}{_at(linked)}"
    timeline.log(state, linked, "override", "dispatcher", text, v.id, detail=DETAIL)
    timeline.log(state, trip, "override", "dispatcher", text, v.id, detail=DETAIL)
    units.note(state, linked, v.id, f"added by the dispatcher: {cost}", "dispatcher")
    return linked, text + (f"; {cost}" if cost != "free" else "")


def _assign_doctor(state: WorldState, trip: Trip, v, mode: str) -> str:
    from .agent.triage import sync_triage

    if trip.kind != "patient":
        raise OverrideError(400, f"{trip.id} carries equipment: no doctor")
    if trip.status == "onboard":
        raise OverrideError(400, f"The patient of {trip.id} is already on board {trip.vehicle_id}: a doctor car would only "
                                 "meet them at the hospital")
    if trip.doctor_vehicle_id == v.id:
        raise OverrideError(400, f"{v.id} already supports {trip.id}")
    if v.status == "out_of_service":
        raise OverrideError(400, f"{v.name} is out of service")
    if not is_doctor_free(v):
        raise OverrideError(400, f"{v.id} is busy with {v.current_trip_id}: a doctor car is never pulled off another call")
    cur = state.vehicles.get(trip.doctor_vehicle_id) if trip.doctor_vehicle_id else None
    car = cur if cur is not None and cur.type == "doctor" and cur.current_trip_id == trip.id else None
    if mode == "add" and car is not None:
        raise OverrideError(400, f"{trip.id} already has doctor car {car.id}: use replace to swap it")
    if car is not None and car.status != "to_pickup":
        raise OverrideError(400, f"Doctor car {car.id} is already with the patient")
    if car is not None:
        release(state, trip)  # stands the first car down
    if not trip.needs_doctor:  # the dispatcher decides a doctor is needed
        trip.needs_doctor, trip.doctor_target_min = True, DOCTOR_TARGET_MIN
        sync_triage(trip)
    at = dispatch_doctor_car(state, trip, v)
    when = f", at the patient {timeline.hhmm(at)}"
    if car is not None:
        text = f"Dispatcher override: doctor car {v.id} instead of {car.id}{when}"
        reason = f"dispatcher override (was {car.id})"
    elif cur is not None and flies(cur.type):
        text = f"Dispatcher added doctor car {v.id} (besides the doctor on board {cur.id}){when}"
        reason = f"added by the dispatcher, besides {cur.id}"
    else:
        text = f"Dispatcher added doctor car {v.id}{when}"
        reason = "added by the dispatcher"
    timeline.log(state, trip, "override", "dispatcher", text, v.id, detail=DETAIL)
    units.note(state, trip, v.id, f"{reason}: {_mins(at, state.sim_time):.0f} min", "dispatcher")
    return text
