"""The units serving a call, and why each one was chosen (snapshot `trips[].units`).

The reason is written where the decision is made (note): the engine's dispatch (engine/dispatch.py),
the doctor car (engine/doctors.py), the follow-up (engine/followup.py), an approved option
(app/approvals.py) and the dispatcher's own changes (app/overrides.py). Anything else that moves a
unit gets a plain reason from the timeline's Tracker (engine/timeline.py).

Like the timeline, the notes are written only in the real world: what-if copies share the dict.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..models import Trip
from ..routing import flies

if TYPE_CHECKING:
    from ..state import WorldState

DONE = ("completed", "cancelled")
ROLES = {"ambulance": "ambulance", "doctor": "doctor", "helicopter": "helicopter", "transport": "van"}
REASON_MAX = 160


def note(state: WorldState, trip: Trip | None, vehicle_id: str | None, reason: str, by: str = "engine") -> None:
    """Remember why vehicle_id serves trip (real world only). by: engine | ai | dispatcher."""
    if trip is None or not vehicle_id or state.is_simulation:
        return
    trip.unit_notes[vehicle_id] = {"reason": reason[:REASON_MAX], "assigned_by": by, "assigned_at": state.sim_time}


def amend(state: WorldState, trip: Trip | None, vehicle_id: str | None, prefix: str) -> None:
    """Put a few words before the stored reason, e.g. "replaces A2 (out of service)"."""
    if trip is None or not vehicle_id or state.is_simulation:
        return
    old = trip.unit_notes.get(vehicle_id)
    if old is not None:
        old["reason"] = f"{prefix}; {old['reason']}"[:REASON_MAX]


def fresh(state: WorldState, trip: Trip, vehicle_id: str) -> bool:
    """A reason for this unit was written just now (so a generic one must not replace it)."""
    n = trip.unit_notes.get(vehicle_id)
    return n is not None and n["assigned_at"] >= state.sim_time


def held(trip: Trip, vehicle_id: str | None = None) -> bool:
    """The dispatcher chose this unit (an override, or a plan they approved): automatic changes (the
    follow-up's faster free unit, the AI dispatcher, the autopilot) leave it alone. Only a drop-out
    (breakdown, fog) replaces it. vehicle_id: default the transporting unit."""
    vid = vehicle_id or trip.vehicle_id
    n = trip.unit_notes.get(vid) if vid else None
    return n is not None and n["assigned_by"] == "dispatcher"


def role_of(v) -> str:
    return ROLES.get(v.type, v.type)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _dest(state: WorldState, trip: Trip) -> str:
    p = state.places.get(trip.dropoff_id)
    return p.name if p else trip.dropoff_id


def _primary_status(state: WorldState, v, trip: Trip) -> str:
    from .projection import route_trip_ids

    if v.status == "out_of_service":
        return "out of service"
    moving = "flying" if flies(v.type) else "driving"
    if trip.status == "completed":
        return f"at {_dest(state, trip)}: handing over" if v.handover_trip_id == trip.id else "done"
    if trip.status == "onboard":
        return "on scene with the patient" if v.status == "loading" else f"transporting to {_dest(state, trip)}"
    if v.current_trip_id == trip.id:
        if v.waiting_until:
            return "at the pickup, waiting until it is ready"
        if v.busy_until and v.busy_until > state.sim_time:
            if v.status == "to_pickup" and flies(v.type):  # activation at the base (app/hems.py)
                from .timeline import hhmm  # local import: timeline imports this module

                return f"crew to the aircraft, take-off {hhmm(v.busy_until)}"
            return "turning out" if v.status == "to_pickup" and v.busy_reason != "delay" else "held up"
        return f"{moving} to the patient" if trip.kind == "patient" else f"{moving} to the pickup"
    route = route_trip_ids(v)
    if trip.id in route:
        ahead = route[: route.index(trip.id)]
        if not ahead:
            return "ready after handover and cleaning" if v.busy_until and v.busy_until > state.sim_time else "about to leave"
        return f"finishing {ahead[0]}, then this call" if len(ahead) == 1 else f"after {', '.join(ahead)}"
    return v.status.replace("_", " ")


def _doctor_status(state: WorldState, v, trip: Trip) -> str:
    if v.status == "out_of_service":
        return "out of service"
    if v.current_trip_id != trip.id:
        return "stood down" if v.status in ("idle", "returning") else v.status.replace("_", " ")
    if v.status == "to_pickup":
        return "turning out" if v.busy_until and v.busy_until > state.sim_time else "driving to the scene"
    if v.status == "loading":
        return "on scene with the crew"
    if v.status == "with_patient":
        return f"escorting the patient to {_dest(state, trip)}"
    return v.status.replace("_", " ")


def _fallback_reason(state: WorldState, v, trip: Trip, doctor: bool) -> str:
    if doctor:
        what = (trip.condition_label or "this call").lower()
        return f"doctor needed for {what}"
    return "assigned by the engine"


def _unit(state: WorldState, trip: Trip, vehicle_id: str, doctor: bool) -> dict[str, Any] | None:
    v = state.vehicles.get(vehicle_id) or state.reserve_vehicles.get(vehicle_id)
    if v is None:
        return None
    n = trip.unit_notes.get(vehicle_id) or {}
    if doctor:
        eta_scene = trip.doctor_eta
        eta_hospital = trip.eta_dropoff if v.status == "with_patient" and v.current_trip_id == trip.id else None
        status = _doctor_status(state, v, trip)
    else:
        eta_scene = max(trip.eta_pickup, trip.pickup_after) if trip.eta_pickup else None
        eta_hospital = trip.eta_dropoff
        status = _primary_status(state, v, trip)
    reason = n.get("reason") or _fallback_reason(state, v, trip, doctor)
    if not doctor and flies(v.type) and trip.needs_doctor and "doctor on board" not in reason:
        reason = f"{reason}; doctor on board"[:REASON_MAX]
    return {
        "vehicle_id": v.id,
        "role": "doctor" if doctor and v.type == "doctor" else role_of(v),
        "trip_id": trip.id,
        "status_text": status,
        "eta_scene": _iso(eta_scene),
        "eta_hospital": _iso(eta_hospital),
        "reason": reason,
        "assigned_by": n.get("assigned_by", "engine"),
        "assigned_at": _iso(n.get("assigned_at") or trip.dispatched_at),
    }


def trip_units(state: WorldState, trip: Trip) -> list[dict[str, Any]]:
    """The units of a trip with a call record: its transporting unit, its doctor car (the helicopter
    counts once: doctor on board), then the units of trips the dispatcher linked to it (several patients)."""
    if trip.call is None:
        return []
    out = []
    for t in [trip, *[o for o in state.trips.values() if o.linked_to == trip.id and o.status not in DONE]]:
        if t.vehicle_id and (u := _unit(state, t, t.vehicle_id, doctor=False)):
            out.append(u)
        if t.doctor_vehicle_id and t.doctor_vehicle_id != t.vehicle_id and (u := _unit(state, t, t.doctor_vehicle_id, doctor=True)):
            out.append(u)
    return out


def trip_view(state: WorldState, trip: Trip) -> dict[str, Any]:
    """A trip for the API: its fields plus `units`."""
    return {**trip.model_dump(mode="json"), "units": trip_units(state, trip)}
