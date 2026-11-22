"""Automatic follow-up of 112 calls (trips with a 112 call record), run by the app loop every
FOLLOWUP_EVERY_S world-seconds (not by the simulator, so the dispatch benchmark is unaffected).

Done by the engine at once, logged on the call's timeline by "engine":
- a call without a unit (none could take it, or its unit dropped out) is dispatched again as soon as
  the dispatch rules find one (engine/dispatch.dispatch_call; a breakdown re-dispatches at once,
  engine/events.py);
- before the unit reaches the patient: if a FREE own ambulance would get there FASTER_FREE_UNIT_MIN_GAIN_MIN
  sooner (e.g. after a delay), it takes the call and the first unit is released, unless the dispatcher
  chose that unit by hand (engine/units.held): their override stands until the unit drops out;
- a call that needs a doctor and has none (none was free, or the doctor car dropped out) gets the
  first doctor car that is free (engine/doctors.send_doctor).
Trade-offs (overrides of other calls, swaps, reserve units, surge capacity) stay proposals for the
dispatcher (agent/runner.py); only the autopilot approves those.
Detours around closures are automatic in the simulator and logged there.
"""
from __future__ import annotations

import time
from datetime import timedelta
from typing import TYPE_CHECKING

from ..models import Plan, PlanStep, Trip
from ..routing import flies, travel_minutes
from . import timeline, units
from .actions import level, near_current_patient
from .candidates import find_candidates, is_free
from .projection import project_all
from .service_times import turnout_min

if TYPE_CHECKING:
    from ..state import WorldState

FOLLOWUP_EVERY_S = 30.0  # world seconds between checks
FASTER_FREE_UNIT_MIN_GAIN_MIN = 3.0  # switch to a free unit that reaches the patient at least this much sooner
OPEN = ("unassigned", "assigned", "en_route_pickup")
DETAIL = "rules engine follow-up"  # the timeline's source text


def _calls(state: WorldState) -> list[Trip]:
    from .events import is_112

    out = [t for t in state.trips.values() if is_112(t) and t.status in OPEN and t.priority in ("emergency", "urgent")]
    return sorted(out, key=lambda t: (level(t), -t.time_weight, t.pickup_after))


def check(state: WorldState, force: bool = False) -> list[str]:
    """One follow-up pass (real world only). Returns what was done, one line each."""
    if state.is_simulation:
        return []
    now = state.sim_time
    if not force and state.followup_at is not None and now < state.followup_at:
        return []
    state.followup_at = now + timedelta(seconds=FOLLOWUP_EVERY_S)
    calls = _calls(state)
    if not calls:
        return []
    from .events import dispatch_call

    done: list[str] = []
    project_all(state)
    for trip in calls:
        if trip.status not in OPEN:
            continue
        tracker = timeline.Tracker(state)
        t0 = time.perf_counter()
        if trip.vehicle_id is None:
            had_doctor = trip.doctor_vehicle_id
            clause = dispatch_call(state, trip)
            if trip.vehicle_id is not None or trip.doctor_vehicle_id != had_doctor:
                project_all(state)
                tracker.log_changes("engine", clause.lstrip("; "), detail=timeline.engine_detail(time.perf_counter() - t0, DETAIL))
                done.append(f"{trip.id}: {clause.lstrip('; ')}")
            continue
        switched = _faster_free_unit(state, trip)
        if switched:
            project_all(state)
            old, text = switched
            detail = timeline.engine_detail(time.perf_counter() - t0, DETAIL)
            timeline.log(state, trip, "reassigned", "engine", text, trip.vehicle_id, detail=detail)
            tracker.before.pop(trip.id, None)  # already said; log only the doctor change, if any
            tracker.log_changes("engine", detail=detail)
            done.append(f"{trip.id}: {text}")
        if trip.needs_doctor and trip.doctor_vehicle_id is None and trip.status in ("assigned", "en_route_pickup"):
            from .doctors import send_doctor

            unit = state.vehicles.get(trip.vehicle_id) if trip.vehicle_id else None
            if unit is not None and not flies(unit.type):
                tracker = timeline.Tracker(state)
                t0 = time.perf_counter()
                clause = send_doctor(state, trip)
                if trip.doctor_vehicle_id is not None:
                    project_all(state)
                    tracker.log_changes("engine", detail=timeline.engine_detail(time.perf_counter() - t0, DETAIL))
                    done.append(f"{trip.id}: doctor{clause}")
    if done:
        state.bump()
    return done


def _faster_free_unit(state: WorldState, trip: Trip) -> tuple[str, str] | None:
    """Move the call to a free own ambulance that reaches the patient FASTER_FREE_UNIT_MIN_GAIN_MIN
    sooner than its unit (never a unit on scene or within 2 min of the patient, never the helicopter's
    call). Returns (old unit, timeline text) when it switched."""
    from .plans import _apply_steps
    from .surge import is_contracted

    v = state.vehicles.get(trip.vehicle_id) if trip.vehicle_id else None
    # Only an ambulance's call: the helicopter is sent by its own rule, and a van on an urgent call
    # may be there on purpose (to keep an area's last ambulance for red calls, engine/dispatch.py).
    if v is None or v.type != "ambulance" or trip.status not in ("assigned", "en_route_pickup") or not trip.eta_pickup:
        return None
    if units.held(trip):
        return None  # the dispatcher chose this unit: their override stands (unless it drops out)
    if near_current_patient(state, v, trip) is not None:
        return None
    now_reach = max(trip.eta_pickup, trip.pickup_after)
    p = state.places[trip.pickup_id]
    emergency = trip.priority == "emergency"
    gain_needed = timedelta(minutes=FASTER_FREE_UNIT_MIN_GAIN_MIN)
    # Cheap first look (straight travel model) before simulating anything.
    maybe = [
        o for o in state.vehicles.values()
        if o.id != v.id and o.type == "ambulance" and o.origin == "own" and not is_contracted(o) and is_free(state, o)
        and state.sim_time + timedelta(minutes=turnout_min(o) + travel_minutes(state, o.lat, o.lon, p.lat, p.lon, o.type, emergency))
        <= now_reach - gain_needed * 0.5
    ]
    if not maybe:
        return None
    ids = {o.id for o in maybe}
    cands = [
        c for c in find_candidates(state, trip.id, limit=50)
        if c["vehicle_id"] in ids and c["vehicle_free"] and not c["step"]["interrupt_current"] and c["trip_eta_pickup"]
    ]
    if not cands:
        return None
    best = min(cands, key=lambda c: c["trip_eta_pickup"])
    reach = max(best["trip_eta_pickup"], trip.pickup_after)
    gain = (now_reach - reach).total_seconds() / 60
    if gain < FASTER_FREE_UNIT_MIN_GAIN_MIN:
        return None
    errors, _ = _apply_steps(state, Plan(steps=[PlanStep(**best["step"])]))
    if errors:
        return None
    trip.dispatched_at = state.sim_time
    who = "the patient" if trip.kind == "patient" else "the pickup"
    why = " (delayed)" if v.busy_until and v.busy_until > state.sim_time else ""
    units.note(state, trip, best["vehicle_id"], f"free and {gain:.0f} min sooner than {v.id}{why}")  # (its ETA is on the card)
    text = (f"{best['vehicle_id']} is free and {gain:.0f} min sooner than {v.id}{why}: switched, at {who} "
            f"{timeline.hhmm(reach)}; {v.id} released")
    return v.id, text
