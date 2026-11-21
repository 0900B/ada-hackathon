"""What-if simulation of a plan on a copy of the world, and applying it for real.

simulate_plan is the core tool for the agent: it proposes, the engine computes.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..models import EventRecord, Plan
from .actions import ActionError, assign_trip
from .projection import DONE, kpis, project_all

if TYPE_CHECKING:
    from ..state import WorldState


def _apply_steps(state: WorldState, plan: Plan) -> list[str]:
    errors = []
    for i, step in enumerate(plan.steps):
        try:
            assign_trip(state, step.trip_id, step.vehicle_id, step.position, step.interrupt_current)
        except ActionError as e:
            errors.append(f"step {i + 1}: {e}")
    return errors


def simulate_plan(state: WorldState, plan: Plan) -> dict[str, Any]:
    sim = state.clone_for_simulation()
    errors = _apply_steps(sim, plan)
    project_all(sim)

    changes = []
    for tid, after in sim.trips.items():
        before = state.trips[tid]
        if after.status in DONE:
            continue
        d_before, d_after = before.delay_min, after.delay_min
        changed = (
            before.vehicle_id != after.vehicle_id
            or before.status != after.status
            or abs((d_before or 0) - (d_after or 0)) >= 1
        )
        if changed:
            changes.append(
                {
                    "trip_id": tid,
                    "patient": after.patient,
                    "priority": after.priority,
                    "vehicle_before": before.vehicle_id,
                    "vehicle_after": after.vehicle_id,
                    "delay_before_min": d_before,
                    "delay_after_min": d_after,
                    "eta_dropoff_after": after.eta_dropoff.isoformat() if after.eta_dropoff else None,
                }
            )
    return {
        "feasible": not errors,
        "errors": errors,
        "kpis_before": kpis(state),
        "kpis_after": kpis(sim),
        "trip_changes": changes,
    }


def apply_plan(state: WorldState, plan: Plan) -> EventRecord:
    preview = simulate_plan(state, plan)
    if not preview["feasible"]:
        raise ActionError("; ".join(preview["errors"]))
    kpis_before = kpis(state)
    _apply_steps(state, plan)
    project_all(state)
    record = EventRecord(
        id=state.new_id("EV"),
        sim_time=state.sim_time,
        type="plan_applied",
        payload=plan.model_dump(mode="json"),
        summary=plan.rationale or f"Plan with {len(plan.steps)} step(s) applied",
        affected_trip_ids=[c["trip_id"] for c in preview["trip_changes"]],
        kpis_before=kpis_before,
        kpis_after=kpis(state),
    )
    state.events.append(record)
    state.bump()
    return record
