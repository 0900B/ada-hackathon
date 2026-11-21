"""What-if simulation of a plan on a copy of the world, and applying it for real.

simulate_plan is the core tool for the agent: it proposes, the engine computes.

Plans are made unambiguous when the engine checks them: every step that moves a trip records the
trip it ends up right before (before_trip_id). Approving later replays the same order even if the
vehicles have moved on meanwhile (a vehicle that started its next trip turns around for a trip the
plan put before it), and the approval is refused if the outcome is clearly worse than what was shown.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from ..models import EventRecord, Plan, PlanStep
from .actions import ActionError, anchor_of, assign_trip
from .projection import DONE, kpis, project_all, route_trip_ids

if TYPE_CHECKING:
    from ..state import WorldState

LJ = ZoneInfo("Europe/Ljubljana")
# Approval re-checks every step against what the operator was shown. A step is out of date if its
# trip is now picked up this much later (emergency/urgent), or becomes this much later at its
# destination (any trip). Time simply passing while the operator reads is allowed for.
STALE_PICKUP_SLIP_MIN = 10.0
STALE_DELAY_SLIP_MIN = 15.0


def _hhmm(dt: datetime | None) -> str:
    return dt.astimezone(LJ).strftime("%H:%M") if dt else "?"


def _apply_steps(state: WorldState, plan: Plan) -> tuple[list[str], list[PlanStep]]:
    """Apply the steps in order. Returns the errors and the steps as actually applied: the effective
    position/interrupt_current and the anchor (before_trip_id) of every step that moved a trip."""
    errors: list[str] = []
    applied: list[PlanStep] = []
    for i, step in enumerate(plan.steps):
        try:
            placed = assign_trip(
                state, step.trip_id, step.vehicle_id, step.position, step.interrupt_current, step.dropoff_id, step.before_trip_id
            )
        except ActionError as e:
            errors.append(f"step {i + 1}: {e}")
            applied.append(step)
            continue
        if placed.in_place:
            applied.append(step.model_copy(update={"before_trip_id": None}))
            continue
        v = state.vehicles[step.vehicle_id]
        anchor = anchor_of(v, step.trip_id)
        at_end = anchor is None and step.position is None and placed.interrupted is None
        applied.append(
            step.model_copy(
                update={
                    "position": None if at_end else placed.position,
                    "interrupt_current": placed.interrupted is not None,
                    "before_trip_id": anchor,
                }
            )
        )
    return errors, applied


def simulate(state: WorldState, plan: Plan) -> tuple[WorldState, list[str]]:
    """Apply the plan to a what-if copy and project it. Returns the copy and any step errors."""
    sim, errors, _ = simulate_steps(state, plan)
    return sim, errors


def simulate_steps(state: WorldState, plan: Plan) -> tuple[WorldState, list[str], list[PlanStep]]:
    sim = state.clone_for_simulation()
    errors, applied = _apply_steps(sim, plan)
    project_all(sim)
    return sim, errors, applied


def step_details(before: WorldState, after: WorldState, steps: list[PlanStep]) -> list[dict[str, Any]]:
    """What each step really does in the simulated world `after`, in plain words for the operator."""
    out = []
    for s in steps:
        t = after.trips.get(s.trip_id)
        v = after.vehicles.get(s.vehicle_id)
        if t is None or v is None:
            continue
        route = route_trip_ids(v)
        if t.vehicle_id != v.id or t.id not in route:
            continue
        order = route.index(t.id)
        ahead = route[:order]
        # The vehicle may arrive before the patient is ready: it collects them at the later of the two.
        pickup_at = max(t.eta_pickup, t.pickup_after) if t.eta_pickup else None
        old = before.vehicles.get(s.vehicle_id)
        was_current = old.current_trip_id if old else None
        dest = after.places[t.dropoff_id].name
        if t.status == "onboard":
            action, when = "redirect", "keeps its patient on board"
            text = f"{v.id} takes {t.label} to {dest} instead (on board), arrives {_hhmm(t.eta_dropoff)}"
        else:
            if not ahead and was_current and was_current != t.id and was_current in route:
                action, when = "divert", f"turns around now (leaves {was_current} for later)"
            elif not ahead:
                action, when = "now", "goes now"
            elif len(ahead) == 1 and ahead[0] == v.current_trip_id:
                action, when = "next", f"next, after its current trip {ahead[0]}"
            else:
                action, when = "queued", f"stop {order + 1} of its route, after {', '.join(ahead)}"
            redirect = f" (redirected to {dest})" if s.dropoff_id and s.dropoff_id != before.trips[t.id].dropoff_id else ""
            late = f", {t.delay_min:.0f} min late" if (t.delay_min or 0) >= 1 else ""
            text = f"{v.id} {when}: picks up {t.label} at {_hhmm(pickup_at)}, at {dest}{redirect} {_hhmm(t.eta_dropoff)}{late}"
        out.append(
            {
                "trip_id": t.id,
                "vehicle_id": v.id,
                "label": t.label,
                "priority": t.priority,
                "action": action,  # now | divert | next | queued | redirect
                "when": when,
                "order": order + 1,  # 1 = the vehicle's first job
                "after_trip_ids": ahead,
                "eta_pickup": t.eta_pickup,  # arrival at the pickup
                "pickup_at": pickup_at,  # when the patient/cargo is collected (not before it is ready)
                "eta_dropoff": t.eta_dropoff,
                "delay_min": t.delay_min,
                "text": text,
            }
        )
    return out


def simulate_plan(state: WorldState, plan: Plan) -> dict[str, Any]:
    sim, errors, applied = simulate_steps(state, plan)

    changes = []
    for tid, after in sim.trips.items():
        before = state.trips[tid]
        if after.status in DONE:
            continue
        d_before, d_after = before.delay_min, after.delay_min
        redirected = before.dropoff_id != after.dropoff_id
        changed = (
            before.vehicle_id != after.vehicle_id
            or before.status != after.status
            or redirected
            or abs((d_before or 0) - (d_after or 0)) >= 1
        )
        if changed:
            changes.append(
                {
                    "trip_id": tid,
                    "patient": after.patient,
                    "label": after.label,
                    "priority": after.priority,
                    "vehicle_before": before.vehicle_id,
                    "vehicle_after": after.vehicle_id,
                    "delay_before_min": d_before,
                    "delay_after_min": d_after,
                    "eta_dropoff_after": after.eta_dropoff,
                    "redirected_to": after.dropoff_id if redirected else None,
                }
            )
    return {
        "feasible": not errors,
        "errors": errors,
        "kpis_before": kpis(state),
        "kpis_after": kpis(sim),
        "trip_changes": changes,
        "step_details": step_details(state, sim, applied) if not errors else [],
        "steps": [s.model_dump() for s in applied],  # as the engine will apply them (with anchors)
    }


def stale_reasons(promised: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[str]:
    """Compare what a plan would do now (step_details from simulate_plan) with what the operator was shown."""
    now = {d["trip_id"]: d for d in current}
    reasons = []
    for p in promised:
        d = now.get(p["trip_id"])
        if d is None:
            continue
        if p.get("pickup_at") and d["pickup_at"] and p["action"] != "redirect" and d["priority"] in ("emergency", "urgent"):
            slip = (d["pickup_at"] - p["pickup_at"]).total_seconds() / 60
            if slip > STALE_PICKUP_SLIP_MIN:
                reasons.append(
                    f"{d['trip_id']} would now be picked up at {_hhmm(d['pickup_at'])} instead of {_hhmm(p['pickup_at'])} "
                    f"({d['vehicle_id']} {d['when']})"
                )
                continue
        if p.get("eta_dropoff") and d["eta_dropoff"]:
            slip = (d["eta_dropoff"] - p["eta_dropoff"]).total_seconds() / 60
            if slip > STALE_DELAY_SLIP_MIN and (d["delay_min"] or 0) - (p.get("delay_min") or 0) > STALE_DELAY_SLIP_MIN:
                reasons.append(
                    f"{d['trip_id']} would now arrive at {_hhmm(d['eta_dropoff'])} instead of {_hhmm(p['eta_dropoff'])}"
                )
    return reasons


def apply_plan(state: WorldState, plan: Plan) -> EventRecord:
    project_all(state)
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
        payload={**plan.model_dump(mode="json"), "step_details": [d["text"] for d in preview["step_details"]]},
        summary=plan.rationale or f"Plan with {len(plan.steps)} step(s) applied",
        affected_trip_ids=[c["trip_id"] for c in preview["trip_changes"]],
        kpis_before=kpis_before,
        kpis_after=kpis(state),
    )
    state.events.append(record)
    state.bump()
    return record
