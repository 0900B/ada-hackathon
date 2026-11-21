"""Runs the Claude agent loop in the background and turns its answer into a checked recommendation.

Reliability rules:
- The model proposes; the engine re-simulates every option before the operator sees it.
- If Claude is unavailable, refuses, or fails, the engine's greedy plan is shown instead.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

import anthropic

from .. import config
from ..audit import AUDIT
from ..engine.candidates import greedy_plan
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
        _finish(state, run, _engine_recommendation(state, focus, reason), engine="engine_fallback")


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


def _engine_recommendation(state: WorldState, focus: EventRecord | None, reason: str) -> Recommendation:
    plan, unresolved = greedy_plan(state)
    situation = focus.summary if focus else "Operator requested a review."
    options = []
    if plan:
        details = simulate_plan(state, plan)["step_details"]
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
    escalation = (
        f"No suitable vehicle for {', '.join(unresolved)}: request help from a neighbouring station."
        if unresolved
        else None
    )
    return Recommendation(
        situation=situation,
        options=options,
        recommended_index=0 if options else -1,
        reasoning=f"Claude was unavailable ({reason[:120]}), so this is the engine's own best plan."
        if options
        else f"Claude was unavailable ({reason[:120]}). No unassigned trips need a vehicle.",
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
