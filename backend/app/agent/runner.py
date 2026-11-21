"""Runs the Claude agent loop in the background and turns its answer into a checked recommendation.

Reliability rules:
- The model proposes; the engine re-simulates every option before the operator sees it.
- If Claude is unavailable, refuses, or fails, the engine's greedy plan is shown instead.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import anthropic

from .. import config
from ..audit import AUDIT
from ..engine.candidates import HELICOPTER_MIN_GAIN_MIN, find_candidates, greedy_plan, is_free
from ..engine.dispatch import swap_options
from ..engine.doctors import reserve_options
from ..engine.projection import red_wait_min
from ..engine.severity import RED_REFERENCE_MIN, clinical_reason
from ..engine.plans import simulate_plan
from ..engine.projection import kpis, project_all
from ..models import AgentRun, EventRecord, Plan, PlanStep, Recommendation, RecommendationOption, utcnow
from .context import build_user_message, describe_call, describe_result, execute_tool
from .prompts import OUTPUT_SCHEMA, SYSTEM_PROMPT, TOOLS

if TYPE_CHECKING:
    from ..state import WorldState

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
_tasks: dict[str, asyncio.Task] = {}
_client: anthropic.AsyncAnthropic | None = None


class AgentFailure(RuntimeError):
    pass


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(timeout=config.AGENT_TIMEOUT_S, max_retries=2)
    return _client


# --- Public API ---------------------------------------------------------------------


def _task_key(state: WorldState, run_id: str) -> str:
    return f"{state.name}:{run_id}"  # run ids are per world, so key tasks by world too


def start_run(state: WorldState, trigger: str, focus: EventRecord | None = None, question: str | None = None) -> AgentRun:
    """Start an analysis in the background. A newer run supersedes any run still in progress."""
    for run in state.agent_runs:
        if run.status == "running" and (task := _tasks.get(_task_key(state, run.id))):
            task.cancel()
            run.status = "superseded"
            run.finished_at = utcnow()
            run.log("info", "Superseded by a newer analysis")
    run = AgentRun(
        id=state.new_id("RUN"),
        trigger=trigger,
        event_id=focus.id if focus else None,
        question=question,
        started_at=utcnow(),
        model=config.AGENT_MODEL if config.agent_enabled() else None,
    )
    state.agent_runs.append(run)
    del state.agent_runs[:-20]  # keep the history bounded
    state.analysed_events = len(state.events)  # everything reported so far has now been looked at
    AUDIT.record(
        state.name,
        "agent_run_started",
        f"AI analysis started ({trigger})",
        ref=run.id,
        payload={"trigger": trigger, "event_id": run.event_id, "question": question, "model": run.model},
    )
    task_key = _task_key(state, run.id)
    task = asyncio.create_task(_run(state, run, focus, question), name=task_key)
    _tasks[task_key] = task
    task.add_done_callback(lambda _t, k=task_key: _tasks.pop(k, None))
    state.bump()
    return run


def cancel_all(state: WorldState | None = None) -> None:
    """Cancel running analyses: all of them, or only those of one world."""
    prefix = f"{state.name}:" if state is not None else ""
    for k in [k for k in _tasks if k.startswith(prefix)]:
        _tasks.pop(k).cancel()


# --- The run --------------------------------------------------------------------------


async def _run(state: WorldState, run: AgentRun, focus: EventRecord | None, question: str | None) -> None:
    try:
        if not config.agent_enabled():
            raise AgentFailure("ANTHROPIC_API_KEY is not set")
        run.log("info", f"Analysing with {config.AGENT_MODEL}")
        state.bump()
        rec = await _claude_loop(state, run, focus, question)
        _finish(state, run, rec, engine="claude")
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 - any failure falls back to the engine
        reason = str(e) if isinstance(e, AgentFailure) else f"{type(e).__name__}: {e}"
        log.warning("agent run %s fell back to engine: %s", run.id, reason)
        run.error = reason[:300]
        run.log("error", f"Claude unavailable ({reason[:200]}). Using the engine's best plan.")
        _finish(state, run, _engine_recommendation(state, focus, reason, question), engine="engine_fallback")


async def _claude_loop(
    state: WorldState, run: AgentRun, focus: EventRecord | None, question: str | None
) -> Recommendation:
    client = _get_client()
    messages: list[dict[str, Any]] = [{"role": "user", "content": build_user_message(state, focus, question)}]

    for _turn in range(config.AGENT_MAX_TURNS):
        response = await client.beta.messages.create(
            model=config.AGENT_MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={
                "effort": config.AGENT_EFFORT,
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
            cache_control={"type": "ephemeral"},
            betas=[FALLBACK_BETA],
            fallbacks="default",  # if Claude declines, the API retries on Anthropic's recommended fallback model
        )
        _add_usage(run, response.usage)

        for block in response.content:
            if block.type == "thinking" and getattr(block, "thinking", ""):
                run.log("reasoning", block.thinking)
            elif block.type == "fallback":
                run.log("info", "Request was served by a fallback model")

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise AgentFailure(f"Claude declined ({getattr(details, 'category', None) or 'no category'})")
        if response.stop_reason == "max_tokens":
            raise AgentFailure("response hit max_tokens")

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "pause_turn":
            continue

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason == "tool_use" and tool_uses:
            results = []
            for block in tool_uses:
                args = block.input if isinstance(block.input, dict) else {}
                run.log("tool_call", describe_call(block.name, args))
                try:
                    out = execute_tool(state, block.name, args)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
                    if summary := describe_result(block.name, out):
                        run.log("tool_result", summary)
                except Exception as e:  # noqa: BLE001 - report tool errors back to Claude
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {e}", "is_error": True}
                    )
                    run.log("error", f"{block.name} failed: {e}")
            messages.append({"role": "user", "content": results})  # all results in one message
            state.bump()
            continue

        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not text:
            raise AgentFailure(f"no final answer (stop_reason={response.stop_reason})")
        data = json.loads(text)
        # The model numbers options from 1 (as it names them in prose); the API uses a 0-based index.
        data["recommended_index"] = int(data.pop("recommended_option", 0)) - 1
        return Recommendation.model_validate(data)

    raise AgentFailure(f"no answer within {config.AGENT_MAX_TURNS} turns")


def _add_usage(run: AgentRun, usage: Any) -> None:
    for field in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        run.usage[field] = run.usage.get(field, 0) + (getattr(usage, field, 0) or 0)


# --- Fallback and finishing --------------------------------------------------------------


def _situation(focus: EventRecord | None, question: str | None) -> str:
    """What happened, for the fallback: the event, else the operator's/scenario's question."""
    if focus:
        return focus.summary
    if question:
        # Scenario questions read "Demo scenario: <title>. These events just happened together: (1) ...".
        text = question.removeprefix("Demo scenario: ").split(" Analyse the combined situation")[0]
        return text.replace(" These events just happened together:", "")[:600]
    return "Operator requested a review."


FASTER_UNIT_MIN_GAIN = 5.0  # offer another unit for a dispatched emergency if it gets there this much sooner
FASTER_UNIT_WINDOW_MIN = 20.0  # ... for emergencies the engine dispatched within this many minutes


def _faster_unit_options(state: WorldState, skip: set[str]) -> list[RecommendationOption]:
    """The engine dispatches a call to a *free* unit. A busy one (driving to a less urgent job, or
    the helicopter) may reach the patient much sooner: offer that, with the first unit taking over
    the displaced job."""
    options = []
    recent = [
        t
        for t in state.trips.values()
        if t.priority == "emergency"
        and t.id not in skip
        and t.dispatched_at
        and t.status in ("assigned", "en_route_pickup")
        and t.eta_pickup
        and state.sim_time - t.dispatched_at <= timedelta(minutes=FASTER_UNIT_WINDOW_MIN)
    ]
    any_ambulance_free = any(v.type == "ambulance" and is_free(state, v) for v in state.vehicles.values())
    for t in recent[:2]:
        now_at = max(t.eta_pickup, t.pickup_after)  # type: ignore[type-var]
        best: dict[str, tuple[float, dict]] = {}  # best alternative per kind: a road unit, the helicopter
        for c in find_candidates(state, t.id, limit=50):
            if c["vehicle_id"] == t.vehicle_id or not c["trip_eta_pickup"] or c["vehicle_type"] in ("transport", "doctor"):
                continue
            gain = (now_at - c["trip_eta_pickup"]).total_seconds() / 60
            kind = "air" if c["vehicle_type"] == "helicopter" else "road"
            needed = (
                FASTER_UNIT_MIN_GAIN
                if kind == "road" or not any_ambulance_free
                else HELICOPTER_MIN_GAIN_MIN  # in the city the helicopter only when clearly faster
            )
            if gain >= needed and (kind not in best or gain > best[kind][0]):
                best[kind] = (gain, c)
        for gain, c in [best[k] for k in ("road", "air") if k in best]:
            options.extend(_faster_unit_option(state, t, gain, c))
    return options[:3]


def _faster_unit_option(state: WorldState, t, gain: float, c: dict) -> list[RecommendationOption]:
    """Send unit c to trip t instead; the unit first sent takes over the job c turns away from."""
    steps = [PlanStep(**c["step"])]
    other = state.vehicles[c["vehicle_id"]]
    displaced = other.current_trip_id if c["step"]["interrupt_current"] else None
    if displaced:
        steps.append(PlanStep(trip_id=displaced, vehicle_id=t.vehicle_id))
    result = simulate_plan(state, Plan(steps=steps))
    if not result["feasible"] and len(steps) > 1:
        steps, displaced = steps[:1], None
        result = simulate_plan(state, Plan(steps=steps))
    if not result["feasible"]:
        return []
    return [
        RecommendationOption(
            title=f"Faster unit for {t.id}: {c['vehicle_id']} instead of {t.vehicle_id}",
            summary="; ".join(d["text"] for d in result["step_details"]) + f". {clinical_reason(t).capitalize()}.",
            steps=steps,
            pros=[f"{t.label} is reached {gain:.0f} min sooner ({clinical_reason(t)})"],
            cons=[
                f"{displaced} is taken over by {t.vehicle_id}" if displaced else f"{c['vehicle_id']} is no longer free"
            ],
        )
    ]


def _engine_recommendation(
    state: WorldState, focus: EventRecord | None, reason: str, question: str | None = None
) -> Recommendation:
    plan, unresolved = greedy_plan(state)
    situation = _situation(focus, question)
    options = []
    k = kpis(state)  # after the plan, if there is one
    if plan:
        result = simulate_plan(state, plan)
        details, k = result["step_details"], result["kpis_after"]
        what = "; ".join(d["text"] for d in details[:3]) + (f"; and {len(details) - 3} more" if len(details) > 3 else "")
        options.append(
            RecommendationOption(
                title="Engine: lowest-delay reassignment",
                summary=f"Most urgent first, each trip to its best simulated vehicle: {what}.",
                steps=plan.steps,
                pros=["Computed deterministically from the live simulation"],
                cons=["No AI trade-off reasoning or notification drafts"],
            )
        )
    planned = {s.trip_id for s in plan.steps} if plan else set()
    options += _faster_unit_options(state, skip=planned)
    for sw in swap_options(state):  # same-level swaps: proposed, never automatic (doctrine rule 4)
        if sw["trip_id"] in planned or sw["other_trip_id"] in planned:
            continue
        options.append(
            RecommendationOption(
                title=f"Swap {sw['trip_id']} and {sw['other_trip_id']} between {sw['vehicles'][0]} and {sw['vehicles'][1]}",
                summary=f"{sw['text']}. {sw['reason']}.",
                steps=[PlanStep(**s) for s in sw["steps"]],
                pros=[sw["reason"]]
                + (
                    [f"Worst wait {sw['worst_wait_before_min']:.0f} → {sw['worst_wait_after_min']:.0f} min"]
                    if "worst wait" in sw["text"]
                    else []
                ),
                cons=["Both crews change destination; tell them and the callers"],
            )
        )
    for ro in reserve_options(state):  # no own unit within 15 min of a red call: mutual aid, private
        t = state.trips[ro["trip_id"]]
        options.append(
            RecommendationOption(
                title=ro["title"],
                summary=f"{ro['step_details'][0]['text']}. {clinical_reason(t).capitalize()}.",
                steps=ro["steps"],
                pros=[f"{t.label} is reached {ro['wait_min']:.0f} min after the call instead of {ro['now_wait_min']:.0f} "
                      f"({clinical_reason(t)})"],
                cons=[f"A unit from outside our fleet: {ro['vehicle_id']} is requested on approval; "
                      f"{t.vehicle_id} is released for the next call"],
            )
        )
    escalation = (
        f"No suitable vehicle for {', '.join(unresolved)}: request help from a neighbouring station."
        if unresolved
        else None
    )
    slow_red = [
        (t, w) for t in state.trips.values() if (w := red_wait_min(t)) is not None and w > RED_REFERENCE_MIN
    ]
    if slow_red:  # Slovenian reference: a unit at a red call within 15 min
        red = "; ".join(f"{t.id} ({t.condition_label or t.severity}) reached after {w:.0f} min" for t, w in slow_red[:3])
        escalation = " ".join(filter(None, [escalation, f"Red calls over the {RED_REFERENCE_MIN:.0f}-min reference: {red}. "
                                            "Ask a neighbouring station for an ambulance (mutual aid)."]))
    late = (
        f" {k['late_trips']} trip(s) {'stay' if options else 'are'} predicted late (worst {k['max_delay_min']:.0f} min)"
        f"{' after this plan' if options else ''}: no {'further ' if options else ''}reassignment found that clearly "
        "helps; consider a reserve vehicle and tell the patients."
        if k["late_trips"]
        else ""
    )
    dispatched = [
        t
        for t in state.trips.values()
        if t.dispatched_at
        and t.status in ("assigned", "en_route_pickup")
        and state.sim_time - t.dispatched_at <= timedelta(minutes=FASTER_UNIT_WINDOW_MIN)
    ][-5:]
    sent = (
        " Already dispatched by the engine: " + ", ".join(f"{t.id} → {t.vehicle_id}" for t in dispatched) + "."
        if dispatched
        else ""
    )
    return Recommendation(
        situation=situation,
        options=options,
        recommended_index=0 if options else -1,
        reasoning=f"Claude was unavailable ({reason[:120]}), so this is the engine's own best plan.{sent}{late}"
        if options
        else f"Claude was unavailable ({reason[:120]}). No trip needs a vehicle.{sent}{late}",
        escalation=escalation,
    )


def _finish(state: WorldState, run: AgentRun, rec: Recommendation, engine: str) -> None:
    """Re-simulate every option with the engine so all numbers shown are the engine's, not the model's.

    Each feasible option's steps are replaced by the steps as the engine applies them (normalised,
    with anchors), and step_details says in plain words what every step really does. Approval
    replays exactly these steps and is checked against these details.
    """
    project_all(state)
    rec.kpis_before = kpis(state)
    rec.checked_at = state.sim_time
    for opt in rec.options:
        if not opt.steps:
            opt.feasible, opt.kpis_after = True, kpis(state)
            continue
        result = simulate_plan(state, Plan(steps=opt.steps))
        opt.feasible = result["feasible"]
        opt.errors = result["errors"]
        opt.kpis_after = result["kpis_after"]
        opt.trip_changes = result["trip_changes"][:12]
        if opt.feasible:
            opt.steps = [PlanStep(**s) for s in result["steps"]]
            opt.step_details = result["step_details"]
    if not (0 <= rec.recommended_index < len(rec.options)):
        rec.recommended_index = 0 if rec.options else -1
    if rec.options and rec.options[rec.recommended_index].feasible is False:
        # Never recommend an option that cannot be applied: take the first one that can.
        rec.recommended_index = next((i for i, o in enumerate(rec.options) if o.feasible), rec.recommended_index)
    run.recommendation = rec
    run.engine = engine  # type: ignore[assignment]
    run.status = "done"
    run.finished_at = utcnow()
    run.log("info", f"Done: {len(rec.options)} option(s)")
    best = rec.options[rec.recommended_index].title if rec.recommended_index >= 0 else "no action"
    AUDIT.record(
        state.name,
        "recommendation",
        f"{'Claude' if engine == 'claude' else 'Engine fallback'}: {len(rec.options)} option(s), recommended: {best}",
        ref=run.id,
        payload={
            "engine": engine,
            "model": run.model,
            "error": run.error,
            "usage": run.usage,
            "recommendation": rec,
            "trace": run.steps,
        },
    )
    state.bump()
