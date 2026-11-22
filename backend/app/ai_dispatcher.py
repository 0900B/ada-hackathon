"""The AI dispatcher: Claude runs each case, the dispatcher can intervene (docs/DISPATCH_PRIORITIES.md,
"AI dispatcher modes").

The engine still acts at once where seconds matter: it dispatches every call when it comes in, routes
around closures and replaces a unit that drops out (engine/dispatch.py, engine/followup.py). On top of
that Claude reviews the case, through the usage guard, as a focused analysis (agent/runner.start_review):
- every new critical or serious 112 call, after the engine's dispatch (on_new_call);
- every disruption that touches an open 112 call: breakdown, delay, a closure on the unit's route, a
  priority change (after_event; at most MAX_CASES_PER_EVENT cases per event).

Per world (state.ai_mode, POST /{world}/admin/ai-mode):
- "autonomous": Claude's recommended feasible option is applied through the dispatcher's own approval
  path (app/approvals.py: re-checked by the engine, applied, audited) and logged by "ai"; when Claude keeps
  the engine's decision (no steps) the timeline says "AI dispatcher (Claude) confirmed ...". Contracted
  surge capacity stays the dispatcher's decision.
- "assisted" (default): the same reviews run only with auto-analyse on, and their options stay
  proposals for the dispatcher.
If the guard refuses, there is no API key, or Claude fails or times out, the engine's decision stands and
the case's timeline says so. One review per case at a time, and none within REVIEW_GAP_MIN world-minutes
of the last one for that case.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from . import config
from .agent import runner
from .audit import AUDIT
from .engine import followup, timeline
from .engine.actions import level
from .engine.events import crosses, is_112
from .engine.units import trip_units
from .guard import GUARD, LIMIT_REASON, SLOW_REASON
from .models import AgentRun, EventRecord, Recommendation, Trip, utcnow

if TYPE_CHECKING:
    from .state import WorldState

log = logging.getLogger(__name__)

MODES = ("assisted", "autonomous")
REVIEW_GAP_MIN = 2.0  # world minutes between two reviews of the same case
MAX_CASES_PER_EVENT = 2  # an event touching more open calls: the most urgent ones are reviewed
DISRUPTIONS = {"breakdown", "delay", "road_closure", "priority_change"}
DONE = ("completed", "cancelled")


def reviews_on(state: WorldState) -> bool:
    """Reviews run in autonomous mode, and in assisted mode with auto-analyse on (as proposals)."""
    return state.ai_mode == "autonomous" or state.auto_analyze


def _open_case(trip: Trip | None) -> bool:
    return trip is not None and is_112(trip) and trip.status not in DONE


# --- When a review starts ---------------------------------------------------------------------------


def on_new_call(state: WorldState, record: EventRecord) -> bool:
    """A 112 call has just been dispatched by the engine: Claude reviews a critical or serious one.
    True if a review started (then no separate analysis is needed for this call)."""
    if not reviews_on(state) or record.type != "urgent_request" or not record.affected_trip_ids:
        return False
    trip = state.trips.get(record.affected_trip_ids[0])
    if not _open_case(trip) or trip.severity not in ("critical", "serious"):  # type: ignore[union-attr]
        return False
    return _review(state, trip, record, _call_question(state, trip))  # type: ignore[arg-type]


def after_event(state: WorldState, record: EventRecord) -> bool:
    """A disruption was applied (the engine has already reacted): Claude reviews the open calls it
    touches. True if a review started (then the general auto-analysis of the event is not needed)."""
    if not reviews_on(state) or record.type not in DISRUPTIONS:
        return False
    cases = cases_touched(state, record)
    if not cases:
        return False
    followup.check(state, force=True)  # the engine reacts first (e.g. a faster free unit), then Claude looks
    started = False
    for trip in cases[:MAX_CASES_PER_EVENT]:
        if trip.status not in DONE:
            started = _review(state, trip, record, _event_question(state, trip, record)) or started
    return started


def cases_touched(state: WorldState, record: EventRecord) -> list[Trip]:
    """The open 112 calls an event touches, most urgent first: its affected trips, and for a closure
    the calls of the units whose route crosses it."""
    ids = list(record.affected_trip_ids)
    if record.type == "road_closure":
        inc = next(reversed(state.incidents.values()), None)  # the closure just reported
        if inc is not None and inc.kind == "road_closure":
            ids += [v.current_trip_id for v in state.vehicles.values() if v.current_trip_id and crosses(state, v, inc)]
    trips = [state.trips[t] for t in dict.fromkeys(ids) if t in state.trips and _open_case(state.trips[t])]
    return sorted(trips, key=lambda t: (level(t), -t.time_weight))


def _review(state: WorldState, trip: Trip, focus: EventRecord, question: str) -> bool:
    last = state.reviews.get(trip.id)
    if last is not None:
        run = next((r for r in state.agent_runs if r.id == last["run_id"]), None)
        if run is not None and run.status == "running":
            return False  # one review per case at a time
        if state.sim_time - last["at"] < timedelta(minutes=REVIEW_GAP_MIN):
            return False  # reviewed moments ago
    if not config.agent_enabled():
        _engine_stands(state, trip, "no API key")
        return False
    if not GUARD.available():
        GUARD.skipped_auto()
        AUDIT.record(state.name, "agent_run_skipped", f"AI dispatcher review of {trip.id} skipped: {LIMIT_REASON}", ref=trip.id)
        _engine_stands(state, trip, LIMIT_REASON)
        return False
    try:
        asyncio.get_running_loop()
    except RuntimeError:  # a script without an event loop: nothing can run in the background
        return False
    run = runner.start_review(state, trip.id, focus, question)
    state.reviews[trip.id] = {"run_id": run.id, "at": state.sim_time}
    return True


# --- What Claude is asked ---------------------------------------------------------------------------


def _units_line(state: WorldState, trip: Trip) -> str:
    parts = []
    for u in trip_units(state, trip):
        at = f"; at the patient {timeline.hhmm(_dt(u['eta_scene']))}" if u["eta_scene"] else ""
        parts.append(f"{u['vehicle_id']} ({u['role']}: {u['reason']}{at})")
    return ", ".join(parts) or "no unit could take it yet"


def _dt(iso: str | None) -> datetime | None:
    return datetime.fromisoformat(iso) if iso else None


def _how(state: WorldState) -> str:
    return (
        "Your recommended option is applied automatically (autonomous mode), after the engine re-checks it."
        if state.ai_mode == "autonomous"
        else "Your recommended option goes to the dispatcher for approval."
    )


KEEP = (
    "If the engine's decision is right, return an empty options list (keep it) and say why in one "
    "sentence in `reasoning`. Otherwise give the better option first and recommend it. Be quick: a few "
    "tool calls at most, and only change something that is clearly better for this patient."
)


def _call_question(state: WorldState, trip: Trip) -> str:
    what = trip.condition_label or "unspecified condition"
    return (
        f"AI dispatcher review of new {trip.severity} call {trip.id} ({what}). The engine has dispatched: "
        f"{_units_line(state, trip)}. Check this dispatch against the doctrine: call find_candidates for "
        f"{trip.id} and simulate an alternative only if it may be clearly better. {KEEP} {_how(state)}"
    )


def _event_question(state: WorldState, trip: Trip, record: EventRecord) -> str:
    what = trip.condition_label or "unspecified condition"
    return (
        f"AI dispatcher review of {trip.severity} call {trip.id} ({what}) after this disruption: "
        f"{record.summary}. The engine has already reacted where it acts by itself (detours, replacing a unit "
        f"that dropped out). Now serving the call: {_units_line(state, trip)}. Check whether the call is still "
        f"served best: call find_candidates for {trip.id} and simulate an alternative only if it may be "
        f"clearly better. {KEEP} {_how(state)}"
    )


# --- When the review is done (agent/runner._finish) ------------------------------------------------


def _engine_stands(state: WorldState, trip: Trip, why: str) -> None:
    timeline.log(state, trip, "note", "engine", f"AI dispatcher review not available ({why}): the engine's decision stands",
                 trip.vehicle_id, detail="rules engine")


def _why_not(run: AgentRun) -> str:
    err = run.error or ""
    if err == LIMIT_REASON:
        return LIMIT_REASON
    if err == SLOW_REASON:
        return "Claude took too long"
    if "API_KEY" in err:
        return "no API key"
    return "Claude unavailable"


def _first_sentence(text: str) -> str:
    text = " ".join((text or "").split())
    for end in (". ", "; "):
        if end in text:
            text = text.split(end, 1)[0]
            break
    return text.rstrip(".")[:200]


def _who_serves(trip: Trip) -> str:
    if not trip.vehicle_id:
        return f"the engine's decision for {trip.id}"
    doctor = f" and doctor car {trip.doctor_vehicle_id}" if trip.doctor_vehicle_id and trip.doctor_vehicle_id != trip.vehicle_id else ""
    return f"{trip.vehicle_id}{doctor} for {trip.id}"


def finish_review(state: WorldState, run: AgentRun, rec: Recommendation, engine: str) -> None:
    """Keep, apply (autonomous) or propose (assisted) what Claude recommends for the case; if Claude
    did not answer, the engine's decision stands. Called by agent/runner._finish."""
    from .approvals import ApprovalError, approve

    trip = state.trips.get(run.review_of or "")
    if trip is None or trip.status in DONE or not any(r is run for r in state.agent_runs):
        return  # the call is over, or the world was reset meanwhile
    if engine != "claude":
        _engine_stands(state, trip, _why_not(run))
        return
    secs = max(0.0, (utcnow() - run.started_at).total_seconds())
    took = f"Claude, {secs:.0f} s"
    state.ai_stats["claude_reviews"] += 1
    idx = rec.recommended_index
    option = rec.options[idx] if 0 <= idx < len(rec.options) else None
    if option is None or (not option.steps and not option.activate_surge):
        reason = _first_sentence(rec.reasoning)
        timeline.log(state, trip, "reviewed", "ai", f"AI dispatcher (Claude) confirmed {_who_serves(trip)}"
                     + (f": {reason}" if reason else ""), trip.vehicle_id, run.id, detail=took)
        run.log("info", "AI dispatcher: the engine's decision is kept")
        return
    autonomous = state.ai_mode == "autonomous"
    if autonomous and option.activate_surge:
        run.log("info", "AI dispatcher: activating contracted surge capacity is left to the dispatcher")
    elif autonomous and option.feasible is False:
        timeline.log(state, trip, "note", "ai", f"AI dispatcher (Claude) proposed {option.title}, but the engine found it "
                     f"infeasible ({'; '.join(option.errors)[:120]}): the engine's decision stands", trip.vehicle_id, run.id,
                     detail=f"{took}, refused by the engine")
        return
    elif autonomous:
        try:
            approve(state, run, idx, by="ai", detail=f"{took}, checked by the engine")
        except ApprovalError as e:
            timeline.log(state, trip, "note", "ai", f"AI dispatcher (Claude) wanted: {option.title}; not applied "
                         f"({e.detail[:140]}): the engine's decision stands", trip.vehicle_id, run.id,
                         detail=f"{took}, refused by the engine")
            return
        state.ai_stats["claude_changes"] += 1
        return
    # Assisted mode (or surge capacity): a proposal on every trip the option moves, and on the case.
    moved = list(dict.fromkeys([s.trip_id for s in option.steps] + [trip.id]))
    for tid in moved:
        t = state.trips.get(tid)
        if t is not None and t.status not in DONE:
            timeline.log(state, t, "proposal", "ai", f"AI dispatcher (Claude) proposes: {option.title}",
                         t.vehicle_id, run.id, detail=took)
