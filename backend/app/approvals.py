"""Approving one option of an analysis: the dispatcher (POST /{world}/agent/runs/{id}/approve) and the
autopilot use the same path, so both are re-checked against the current world, applied and audited.

The steps carry anchors (before_trip_id) from when the engine checked them, so the vehicles do the jobs
in the order that was shown even if they moved on meanwhile. If the outcome is now clearly worse than
shown (e.g. a vehicle loaded a patient and can no longer turn around), the approval is refused with the
reason (409) and, if auto-analyse is on, a fresh analysis starts (not for the autopilot).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .agent.context import hhmm
from .audit import AUDIT
from .engine import surge, timeline, units
from .engine.actions import ActionError
from .engine.plans import apply_plan, simulate_plan, stale_reasons
from .engine.projection import DONE, project_all
from .models import AgentRun, Plan, utcnow

if TYPE_CHECKING:
    from .state import WorldState


class ApprovalError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def _out_of_date(state: WorldState, run: AgentRun, why: str, restart: bool) -> ApprovalError:
    """The world moved on since the option was checked: say what changed and start a fresh analysis."""
    from .agent import runner as agent

    run.log("info", f"Approval refused, plan out of date: {why}"[:600])
    fresh = None
    if restart and state.auto_analyze:  # analysis on demand otherwise: the operator presses Analyse
        fresh = agent.start_run(
            state, trigger=f"stale:{run.id}", question=f"The operator wanted to approve a plan that is out of date ({why}). Re-plan."
        )
    state.bump()
    tail = f" A new analysis has started ({fresh.id})." if fresh else " Ask for a new analysis."
    return ApprovalError(409, why + tail)


WHO = {"autopilot": "Autopilot", "ai": "AI dispatcher (Claude)", "dispatcher": "Operator"}
ACTOR = {"autopilot": "engine", "ai": "ai", "dispatcher": "dispatcher"}  # the timeline's `by`


def approve(
    state: WorldState, run: AgentRun, option_index: int, by: str = "dispatcher", detail: str | None = None
) -> AgentRun:
    """Apply option option_index of run. by: "dispatcher", "autopilot" (the engine approves an analysis
    about a call) or "ai" (the AI dispatcher applies its own review, app/ai_dispatcher.py). detail: the
    timeline's source text. Raises ApprovalError."""
    autopilot = by in ("autopilot", "ai")
    if run.status != "done" or run.recommendation is None:
        raise ApprovalError(409, f"Run {run.id} is {run.status}; nothing to approve")
    options = run.recommendation.options
    if not 0 <= option_index < len(options):
        raise ApprovalError(400, "option_index out of range")
    option = options[option_index]
    if autopilot:  # the dispatcher's own choice of a unit is never changed automatically
        for s in option.steps:
            t = state.trips.get(s.trip_id)
            if t is not None and t.vehicle_id and t.vehicle_id != s.vehicle_id and units.held(t):
                raise ApprovalError(409, f"the dispatcher assigned {t.vehicle_id} to {t.id} by hand: their decision stands")
    tracker = timeline.Tracker(state)
    applied_event = None
    executed: list[str] = []
    if option.activate_surge and not surge.active(state):
        # The dispatcher's decision: contracted surge capacity joins first, then the option's steps.
        surge_event = surge.activate(state)
        AUDIT.record(state.name, "surge", surge_event.summary, ref=surge_event.id, payload=surge_event)
        executed.append(surge_event.summary)
        applied_event = surge_event
    if option.steps:
        plan = Plan(steps=option.steps, rationale=f"{WHO[by] if autopilot else 'Approved'}: {option.title}")
        project_all(state)
        preview = simulate_plan(state, plan)
        checked = run.recommendation.checked_at
        since = f" (checked at {hhmm(checked)}, now {hhmm(state.sim_time)})" if checked else ""
        if not preview["feasible"]:
            # e.g. a patient was picked up meanwhile, or the vehicle broke down.
            raise _out_of_date(state, run, f"Plan no longer valid{since}: {'; '.join(preview['errors'])}.", not autopilot)
        if stale := stale_reasons(option.step_details, preview["step_details"]):
            raise _out_of_date(state, run, f"Plan is out of date{since}: {'; '.join(stale)}.", not autopilot)
        try:
            applied_event = apply_plan(state, plan)
        except ActionError as e:
            raise _out_of_date(state, run, f"Plan no longer valid{since}: {e}.", not autopilot) from e
        executed += [d["text"] for d in preview["step_details"]]
    run.status = "approved"
    run.decision = {
        "option_index": option_index,
        "title": option.title,
        "event_id": applied_event.id if applied_event else None,
        "at": utcnow().isoformat(),
        "executed": executed,  # what each step does as applied (same wording as step_details[].text)
        "by": by,
    }
    who = WHO.get(by, "Operator")
    run.log("info", f"{who} approved option {option_index + 1}: {option.title}")
    AUDIT.record(
        state.name,
        "decision_approved",
        f"{who} approved option {option_index + 1}: {option.title}",
        ref=run.id,
        payload={"option": option, "decision": run.decision},
    )
    # The call timeline: what was approved, on every trip the option touches, then what moved; and
    # why each unit now serves its trip (trip.units).
    actor = ACTOR.get(by, "dispatcher")
    decided_by = "dispatcher" if by == "dispatcher" else ("ai" if run.engine == "claude" else "engine")
    what = {"ai": "AI dispatcher (Claude)", "autopilot": "autopilot"}.get(by, "approved")
    for s in option.steps:
        trip = state.trips.get(s.trip_id)
        if trip is not None and trip.vehicle_id == s.vehicle_id:
            units.note(state, trip, s.vehicle_id, f"{what}: {option.title}", decided_by)
    for tid in dict.fromkeys(s.trip_id for s in option.steps):
        trip = state.trips.get(tid)
        if trip is not None and trip.status not in DONE and by != "ai":  # (the AI dispatcher logs "reviewed: changed")
            timeline.log(state, trip, "approved", actor, f"{who} approved: {option.title}", trip.vehicle_id, run.id, detail=detail)
    tracker.log_changes(actor, detail=detail)
    state.bump()
    return run
