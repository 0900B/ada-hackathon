"""Compact, model-friendly views of the world: the situation brief and tool results."""
from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from ..engine.candidates import find_candidates, is_free, nearest_place_name
from ..engine.dispatch import swap_options
from ..engine.doctors import per_call_reserve
from ..engine.surge import active as surge_active, available as surge_available, demand as surge_demand, offer_text as surge_offer
from ..engine.severity import clinical_reason
from ..engine.plans import simulate_plan
from ..engine.projection import DONE, incoming_patients, kpis, over_capacity, project_route
from ..models import EventRecord, Plan, PlanStep, Trip, Vehicle
from ..routing import weather_factor

if TYPE_CHECKING:
    from ..state import WorldState

LJ = ZoneInfo("Europe/Ljubljana")


def hhmm(dt: datetime | None) -> str | None:
    return dt.astimezone(LJ).strftime("%H:%M") if dt else None


def jsonable(obj: Any) -> Any:
    """Datetimes -> HH:MM local; recurse through dicts and lists."""
    if isinstance(obj, datetime):
        return hhmm(obj)
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    return obj


def to_json(obj: Any) -> str:
    return json.dumps(jsonable(obj), ensure_ascii=False, separators=(",", ":"))


def _load(t: Trip) -> dict[str, Any]:
    """Who or what a trip carries: never call equipment a patient."""
    return {"patient": t.patient} if t.kind == "patient" else {"equipment": t.cargo}


def _vehicle_status(state: WorldState, v: Vehicle) -> str:
    current = state.trips.get(v.current_trip_id) if v.current_trip_id else None
    if v.status == "with_patient" and current and current.kind == "equipment":
        return "with_equipment"
    return v.status


def build_hospitals(state: WorldState) -> list[dict[str, Any]]:
    overflow = over_capacity(state)
    return [
        {
            "id": p.id,
            "name": p.name,
            **({"specialty": p.specialty} if p.specialty else {}),
            "can_admit": "unlimited" if p.capacity is None else p.capacity,
            "incoming_patients": len(incoming_patients(state, p.id)),
            **({"over_capacity_redirect": [t.id for t in overflow[p.id]]} if p.id in overflow else {}),
        }
        for p in state.places.values()
        if p.kind == "hospital"
    ]


def build_situation(state: WorldState) -> dict[str, Any]:
    w = state.effective_weather
    places = state.places
    return {
        "mode": "live (real conditions)" if not state.hypothetical else "simulation (hypothetical scenario for training/demo)",
        "operations": "scheduled day (vans have pre-planned trips)" if state.scheduled_day else "live calls",
        "now": hhmm(state.sim_time),
        "weather": None
        if w is None
        else {
            "temperature_c": w.temperature_c,
            "precipitation_mm": w.precipitation_mm,
            "snowfall_cm": w.snowfall_cm,
            "source": "demo override" if state.weather_override else w.source,
            "speed_factor": weather_factor(w),
        },
        "traffic": {
            "speed_factor": state.traffic_factor,
            "source": state.traffic_source,
            "roads": [f"{s['road']}: {s['current_kmh']}/{s['free_flow_kmh']} km/h" for s in state.traffic_samples],
        },
        "data_sources": {s.name: f"{s.health} ({s.kind})" for s in state.sources.values()},
        "totals": kpis(state),
        "alerts": [a.message for a in state.alerts[:12]],
        "incidents": [
            {"id": i.id, "kind": i.kind, "description": i.description, "near": nearest_place_name(state, i.lat, i.lon)}
            for i in state.all_incidents()
            if i.active
        ],
        "vehicles": [
            {
                "id": v.id,
                "type": v.type,
                "status": _vehicle_status(state, v),
                "free": is_free(state, v),  # no job and nothing queued
                "near": nearest_place_name(state, v.lat, v.lon),
                "current_trip": v.current_trip_id,
                "queue": v.queue,
                "busy_until": hhmm(v.busy_until),
                **({"waiting_at_pickup_until": hhmm(v.waiting_until)} if v.waiting_until else {}),
                "fuel_pct": round(v.fuel_pct),
                **({"grounded_by_fog_until": hhmm(v.grounded_until)} if v.grounded_until else {}),
                **({"origin": v.origin} if v.origin != "own" else {}),
                **({"contract_until": hhmm(v.contract_until)} if v.contract_until else {}),
            }
            for v in state.vehicles.values()
        ],
        # Not in the fleet until requested: a plan step that names one requests it (red calls only).
        **(
            {
                "reserve_units": [
                    {"id": r.id, "type": r.type, "origin": r.origin, "base": places[r.base_id].name}
                    for r in per_call_reserve(state)
                ]
            }
            if per_call_reserve(state)
            else {}
        ),
        # The demand trigger and contracted surge capacity (activated only by an approved option with
        # activate_surge true, or by the dispatcher directly).
        **(
            {
                "demand": {
                    "high_demand": d["high"],
                    "reasons": d["reasons"],
                    "surge_capacity": {"active_until": hhmm(state.surge_until)}
                    if surge_active(state)
                    else {"offer": surge_offer(state), "available": surge_available(state)},
                }
            }
            if (d := surge_demand(state))["high"] or surge_active(state)
            else {}
        ),
        "hospitals": build_hospitals(state),
        "open_trips": [
            {
                "id": t.id,
                **_load(t),
                "priority": t.priority,
                "severity": t.severity,
                **({"condition": t.condition_label or t.condition} if t.condition else {}),
                "time_weight": t.time_weight,
                **({"response_target_min": t.response_target_min} if t.response_target_min else {}),
                **({"modifiers": t.modifiers} if t.modifiers else {}),
                **({"clinical_reason": clinical_reason(t)} if t.severity in ("critical", "serious") else {}),
                **(
                    {"needs_doctor": True, "doctor": t.doctor_vehicle_id, "doctor_eta": hhmm(t.doctor_eta)}
                    if t.needs_doctor
                    else {}
                ),
                "needs": t.needs,
                "from": places[t.pickup_id].name,
                "to": places[t.dropoff_id].name,
                "ready": hhmm(t.pickup_after),
                "due": hhmm(t.due_by),
                "status": t.status,
                "vehicle": t.vehicle_id,
                "eta_dropoff": hhmm(t.eta_dropoff),
                "delay_min": t.delay_min,
                "note": t.note,
                **({"dispatched_by_engine_at": hhmm(t.dispatched_at)} if t.dispatched_at else {}),
            }
            for t in state.trips.values()
            if t.status not in DONE
        ],
        # Same-level swaps the engine found worthwhile (doctrine rule 4: proposals only).
        **({"proposed_swaps": [{"text": s["text"], "reason": s["reason"], "steps": s["steps"]} for s in swaps]} if (swaps := swap_options(state)) else {}),
    }


def build_user_message(state: WorldState, focus: EventRecord | None, question: str | None) -> str:
    parts = []
    if focus:
        b, a = focus.kpis_before, focus.kpis_after
        parts.append(
            f"New event {focus.id} at {hhmm(focus.sim_time)}: {focus.summary}. "
            f"Affected trips: {', '.join(focus.affected_trip_ids) or 'none'}. "
            f"Late trips {b['late_trips']} -> {a['late_trips']}; "
            f"unassigned {sum(b['unassigned'].values())} -> {sum(a['unassigned'].values())}."
        )
    if question:
        parts.append(f"Operator request: {question}")
    if not focus and not question:
        parts.append("The operator asked for a review of the current situation.")
    parts.append("Current situation:\n" + to_json(build_situation(state)))
    return "\n\n".join(parts)


# --- Tool implementations ----------------------------------------------------------


def tool_find_candidates(state: WorldState, trip_id: str, dropoff_id: str | None = None) -> dict[str, Any]:
    t = state.trips.get(trip_id)
    candidates = find_candidates(state, trip_id, dropoff_id=dropoff_id, include_reserve=True)
    return {
        "trip": None
        if t is None
        else {
            "id": t.id,
            **_load(t),
            "priority": t.priority,
            "needs": t.needs,
            "ready": hhmm(t.pickup_after),
            "due": hhmm(t.due_by),
            "to": state.places[dropoff_id or t.dropoff_id].name,
        },
        "candidates": candidates,
        "note": "No suitable vehicle can take this trip." if not candidates else None,
    }


def tool_simulate_plan(state: WorldState, steps: list[dict[str, Any]]) -> dict[str, Any]:
    if not steps:
        return {"feasible": True, "note": "Empty plan: nothing changes.", "kpis": kpis(state)}
    plan = Plan(steps=[PlanStep(**s) for s in steps])
    result = simulate_plan(state, plan)
    result.pop("steps", None)  # the engine's anchored copy of the steps; step_details says what they do
    return result


def tool_vehicle_schedule(state: WorldState, vehicle_id: str) -> dict[str, Any]:
    v = state.vehicles.get(vehicle_id)
    if v is None and vehicle_id in state.reserve_vehicles:
        r = state.reserve_vehicles[vehicle_id]
        return {"vehicle": r.id, "type": r.type, "origin": r.origin, "status": "reserve (not requested)",
                "base": state.places[r.base_id].name, "schedule": []}
    if v is None:
        raise ValueError(f"Unknown vehicle {vehicle_id}")
    if v.type == "doctor":
        t = state.trips.get(v.current_trip_id) if v.current_trip_id else None
        return {"vehicle": v.id, "type": v.type, "status": v.status, "near": nearest_place_name(state, v.lat, v.lon),
                "supports": t.id if t else None, "doctor_eta": hhmm(t.doctor_eta) if t else None, "schedule": []}
    if v.status == "out_of_service":
        return {"vehicle": vehicle_id, "status": "out_of_service", "schedule": []}
    legs = project_route(state, v)
    return {
        "vehicle": v.id,
        "type": v.type,
        "status": v.status,
        "near": nearest_place_name(state, v.lat, v.lon),
        **({"grounded_by_fog_until": hhmm(v.grounded_until)} if v.grounded_until else {}),
        "schedule": [
            {
                "trip": leg.trip_id,
                "priority": state.trips[leg.trip_id].priority,
                "eta_pickup": leg.eta_pickup,
                "eta_dropoff": leg.eta_dropoff,
                "due": state.trips[leg.trip_id].due_by,
                "delay_min": leg.delay_min,
            }
            for leg in legs
        ],
    }


def execute_tool(state: WorldState, name: str, args: dict[str, Any]) -> str:
    if name == "find_candidates":
        result = tool_find_candidates(state, args["trip_id"], args.get("dropoff_id"))
    elif name == "simulate_plan":
        result = tool_simulate_plan(state, args["steps"])
    elif name == "get_vehicle_schedule":
        result = tool_vehicle_schedule(state, args["vehicle_id"])
    else:
        raise ValueError(f"Unknown tool {name}")
    return to_json(result)


def describe_call(name: str, args: dict[str, Any]) -> str:
    if name == "find_candidates":
        to = f" (redirected to {args['dropoff_id']})" if args.get("dropoff_id") else ""
        return f"Finding vehicles for {args.get('trip_id')}{to}"
    if name == "simulate_plan":
        steps = args.get("steps") or []
        return "Simulating: " + (
            ", ".join(
                f"{s['trip_id']}→{s['vehicle_id']}" + (f"⇒{s['dropoff_id']}" if s.get("dropoff_id") else "") for s in steps
            )
            or "no changes"
        )
    if name == "get_vehicle_schedule":
        return f"Checking {args.get('vehicle_id')}'s schedule"
    return f"{name}({args})"


def describe_result(name: str, result_json: str) -> str | None:
    if name != "simulate_plan":
        return None
    r = json.loads(result_json)
    if not r.get("feasible", True):
        return "Infeasible: " + "; ".join(r.get("errors", []))
    b, a = r.get("kpis_before"), r.get("kpis_after")
    if not (b and a):
        return None
    over_b, over_a = b.get("over_capacity", 0), a.get("over_capacity", 0)
    return (
        f"Late trips {b['late_trips']} → {a['late_trips']}, total delay "
        f"{b['total_delay_min']:.0f} → {a['total_delay_min']:.0f} min, unassigned "
        f"{sum(b['unassigned'].values())} → {sum(a['unassigned'].values())}"
        + (f", over capacity {over_b} → {over_a}" if over_b or over_a else "")
    )
