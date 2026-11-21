"""Compact, model-friendly views of the world: the situation brief and tool results."""
from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from ..engine.candidates import find_candidates, nearest_place_name
from ..engine.plans import simulate_plan
from ..engine.projection import DONE, kpis, project_route
from ..models import EventRecord, Plan, PlanStep
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


def build_situation(state: WorldState) -> dict[str, Any]:
    w = state.effective_weather
    places = state.places
    return {
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
        "traffic_speed_factor": state.traffic_factor,
        "data_sources": {s.name: f"{s.health} ({s.kind})" for s in state.sources.values()},
        "totals": kpis(state),
        "alerts": [a.message for a in state.alerts[:12]],
        "incidents": [
            {"id": i.id, "kind": i.kind, "description": i.description, "near": nearest_place_name(state, i.lat, i.lon)}
            for i in state.incidents.values()
            if i.active
        ],
        "vehicles": [
            {
                "id": v.id,
                "type": v.type,
                "status": v.status,
                "near": nearest_place_name(state, v.lat, v.lon),
                "current_trip": v.current_trip_id,
                "queue": v.queue,
                "busy_until": hhmm(v.busy_until),
            }
            for v in state.vehicles.values()
        ],
        "open_trips": [
            {
                "id": t.id,
                "patient": t.patient,
                "priority": t.priority,
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
            }
            for t in state.trips.values()
            if t.status not in DONE
        ],
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


def tool_find_candidates(state: WorldState, trip_id: str) -> dict[str, Any]:
    t = state.trips.get(trip_id)
    candidates = find_candidates(state, trip_id)
    return {
        "trip": None
        if t is None
        else {"id": t.id, "priority": t.priority, "needs": t.needs, "ready": hhmm(t.pickup_after), "due": hhmm(t.due_by)},
        "candidates": candidates,
        "note": "No suitable vehicle can take this trip." if not candidates else None,
    }


def tool_simulate_plan(state: WorldState, steps: list[dict[str, Any]]) -> dict[str, Any]:
    if not steps:
        return {"feasible": True, "note": "Empty plan: nothing changes.", "kpis": kpis(state)}
    plan = Plan(steps=[PlanStep(**s) for s in steps])
    return simulate_plan(state, plan)


def tool_vehicle_schedule(state: WorldState, vehicle_id: str) -> dict[str, Any]:
    v = state.vehicles.get(vehicle_id)
    if v is None:
        raise ValueError(f"Unknown vehicle {vehicle_id}")
    if v.status == "out_of_service":
        return {"vehicle": vehicle_id, "status": "out_of_service", "schedule": []}
    legs = project_route(state, v)
    return {
        "vehicle": v.id,
        "type": v.type,
        "status": v.status,
        "near": nearest_place_name(state, v.lat, v.lon),
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
        result = tool_find_candidates(state, args["trip_id"])
    elif name == "simulate_plan":
        result = tool_simulate_plan(state, args["steps"])
    elif name == "get_vehicle_schedule":
        result = tool_vehicle_schedule(state, args["vehicle_id"])
    else:
        raise ValueError(f"Unknown tool {name}")
    return to_json(result)


def describe_call(name: str, args: dict[str, Any]) -> str:
    if name == "find_candidates":
        return f"Finding vehicles for {args.get('trip_id')}"
    if name == "simulate_plan":
        steps = args.get("steps") or []
        return "Simulating: " + (", ".join(f"{s['trip_id']}→{s['vehicle_id']}" for s in steps) or "no changes")
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
    return (
        f"Late trips {b['late_trips']} → {a['late_trips']}, total delay "
        f"{b['total_delay_min']:.0f} → {a['total_delay_min']:.0f} min, unassigned "
        f"{sum(b['unassigned'].values())} → {sum(a['unassigned'].values())}"
    )
