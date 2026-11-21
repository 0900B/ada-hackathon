"""FastAPI app: runs the shared live feeds and two worlds, and exposes them per world.

- /live/...  real time, real weather/traffic/incidents; operators may report real events
- /sim/...   presentation sandbox: faster clock, hypothetical weather, demo scenarios, reset
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Path, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import config, demo
from .agent import runner as agent
from .agent.messages import FieldMessage, MessageError, parse_message, to_operator_events
from .audit import AUDIT
from .engine.actions import ActionError
from .engine.events import EventError, apply_event
from .engine.plans import apply_plan, simulate_plan
from .engine.projection import kpis, project_all
from .fetchers import nap, tomtom
from .fetchers.base import run_periodic
from .fetchers.traffic import update_traffic
from .fetchers.weather import fetch_weather
from .models import (
    AgentRun,
    AnalyzeRequest,
    ApproveRequest,
    EventRecord,
    OperatorEvent,
    Plan,
    RejectRequest,
    utcnow,
)
from .roads import ROADS
from .sim.seed import seed_world
from .sim.simulator import tick
from .state import FeedState, WorldState

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # its request log prints full URLs, incl. TomTom's ?key=
log = logging.getLogger("app")

feed = FeedState()
live = WorldState("live", feed, speedup=config.LIVE_SPEEDUP, hypothetical=False)
sim = WorldState("sim", feed, speedup=config.SIM_SPEEDUP, hypothetical=True)
WORLDS: dict[str, WorldState] = {"live": live, "sim": sim}
state = sim  # backwards-compatible name used by older scripts and tests


def bump_all() -> None:
    for w in WORLDS.values():
        w.bump()


async def sim_loop() -> None:
    """Advance both fleets (our stand-in GPS feed) and re-project every trip."""
    status = feed.register_source("vehicle_gps", "simulated", config.SIM_TICK_S)
    while True:
        status.last_attempt = utcnow()
        errors = []
        for w in WORLDS.values():
            try:
                tick(w, config.SIM_TICK_S * w.speedup)
                project_all(w)
            except Exception as e:  # noqa: BLE001 - keep the loop alive, surface the error in /health
                log.exception("simulation tick failed (%s)", w.name)
                errors.append(f"{w.name}: {type(e).__name__}: {e}"[:300])
            w.bump()
        if errors:
            status.last_error = "; ".join(errors)
        else:
            status.last_success, status.last_error = utcnow(), None
        await asyncio.sleep(config.SIM_TICK_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    for w in WORLDS.values():
        seed_world(w, config.RANDOM_SEED)
    client = httpx.AsyncClient(timeout=10.0, headers={"User-Agent": config.HTTP_USER_AGENT})
    # Feeds write into the shared FeedState; passing the live world is just a handle to it.
    tasks = [
        asyncio.create_task(sim_loop(), name="sim"),
        asyncio.create_task(ROADS.run(client, bump_all), name="roads"),
        asyncio.create_task(AUDIT.run(), name="audit"),
        asyncio.create_task(
            run_periodic(live, "weather", "live", config.WEATHER_INTERVAL_S, lambda: fetch_weather(live, client)),
            name="weather",
        ),
    ]
    if tomtom.tomtom_key():
        tasks += [
            asyncio.create_task(
                run_periodic(live, "traffic", "live", config.TOMTOM_INTERVAL_S, lambda: tomtom.fetch_flow(live, client)),
                name="traffic",
            ),
            asyncio.create_task(
                run_periodic(
                    live,
                    "tomtom_incidents",
                    "live",
                    config.TOMTOM_INCIDENTS_INTERVAL_S,
                    lambda: tomtom.fetch_incidents(live, client),
                ),
                name="tomtom_incidents",
            ),
        ]
    else:
        tasks.append(
            asyncio.create_task(
                run_periodic(live, "traffic", "fallback", config.TRAFFIC_INTERVAL_S, lambda: update_traffic(live)),
                name="traffic",
            )
        )
    if nap.nap_credentials():
        tasks.append(
            asyncio.create_task(
                run_periodic(live, "promet.si", "live", config.NAP_INTERVAL_S, lambda: nap.fetch_events(live, client)),
                name="promet.si",
            )
        )
    log.info(
        "backend started: live + sim worlds (%d vehicles each), agent %s, traffic feeds: %s",
        len(live.vehicles),
        f"enabled ({config.AGENT_MODEL})" if config.agent_enabled() else "disabled (no ANTHROPIC_API_KEY): engine fallback only",
        ", ".join(name for name, on in (("TomTom", tomtom.tomtom_key()), ("promet.si/NAP", nap.nap_credentials())) if on)
        or "none (time-of-day profile)",
    )
    AUDIT.record("system", "startup", "Backend started", payload={"agent_model": config.AGENT_MODEL})
    yield
    agent.cancel_all()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await client.aclose()


app = FastAPI(title="Emergency transport assistant - backend", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/")
def root() -> dict:
    return {"service": "emergency-transport-backend", "docs": "/docs", "health": "/health", "worlds": list(WORLDS)}


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "worlds": {name: {"sim_time": w.sim_time.isoformat(), "speedup": w.speedup} for name, w in WORLDS.items()},
        "sources": {k: s.model_dump(mode="json") for k, s in feed.sources.items()},
        "tomtom_requests_today": tomtom.usage() if tomtom.tomtom_key() else None,
        "roads": ROADS.summary(),
        "audit": AUDIT.summary(),
    }


# --- Per-world API: /live/... and /sim/... ------------------------------------------------


def get_world(world: Literal["live", "sim"] = Path(..., description="live or sim")) -> WorldState:
    return WORLDS[world]


router = APIRouter(prefix="/{world}")
World = Depends(get_world)


@router.get("/state")
def get_state(state: WorldState = World) -> dict:
    return state.snapshot()


@router.get("/alerts")
def get_alerts(state: WorldState = World) -> list[dict]:
    return [a.model_dump(mode="json") for a in state.alerts]


@router.get("/kpis")
def get_kpis(state: WorldState = World) -> dict:
    return kpis(state)


@router.get("/stream")
async def stream(request: Request, state: WorldState = World) -> StreamingResponse:
    """Server-sent events: a full snapshot of this world whenever it changes (about every tick)."""

    async def gen():
        last = -1
        while not await request.is_disconnected():
            if state.version != last:
                last = state.version
                yield f"data: {json.dumps(state.snapshot())}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


DISRUPTIVE_EVENTS = {
    "breakdown",
    "delay",
    "road_closure",
    "urgent_request",
    "weather_override",
    "fog",
    "priority_change",
    "hospital_capacity",
}


@router.post("/events")
async def post_event(event: OperatorEvent = Body(...), state: WorldState = World) -> EventRecord:
    """Report/inject an event. Disruptive events start an agent analysis automatically (AGENT_AUTO=1).

    Live accepts real operator reports; hypothetical weather is only allowed in the simulation.
    """
    try:
        record = apply_event(state, event)
    except EventError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    AUDIT.record(state.name, "event", record.summary, ref=record.id, payload=record)
    clearing = getattr(event, "clear", False)
    if config.AGENT_AUTO and event.type in DISRUPTIVE_EVENTS and not clearing:
        agent.start_run(state, trigger=f"event:{record.id}", focus=record)
    return record


@router.post("/messages")
async def post_message(msg: FieldMessage, state: WorldState = World) -> dict:
    """Part 3 of the brief: a field message (Slovenian/English) -> structured events -> new plan.

    Claude interprets the message; the engine validates and applies the events; the dispatcher
    agent then replans. Ambiguous messages come back with a clarification question instead.
    """
    if not config.agent_enabled():
        raise HTTPException(status_code=503, detail="Message parsing needs the Claude API key; use the event buttons")
    if msg.sender_vehicle_id and msg.sender_vehicle_id not in state.vehicles:
        raise HTTPException(status_code=400, detail=f"Unknown vehicle {msg.sender_vehicle_id}")
    try:
        parsed = await parse_message(state, msg.text, msg.sender_vehicle_id)
        events = to_operator_events(state, parsed)
    except MessageError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 - API/network failure: tell the operator, don't crash
        log.warning("message parsing failed: %s", e)
        raise HTTPException(status_code=502, detail="The AI could not be reached; please use the event buttons") from e

    result: dict = {
        "understood_sl": parsed.understood_sl,
        "understood_en": parsed.understood_en,
        "needs_clarification": parsed.needs_clarification,
        "events": [e.model_dump(mode="json") for e in events],
        "applied": [],
        "run_id": None,
    }
    AUDIT.record(
        state.name,
        "field_message",
        f'"{msg.text}" -> {parsed.needs_clarification or parsed.understood_en}',
        ref=msg.sender_vehicle_id,
        payload={"text": msg.text, "sender": msg.sender_vehicle_id, **{k: result[k] for k in ("understood_sl", "understood_en", "needs_clarification", "events")}},
    )
    if not msg.apply or parsed.needs_clarification or not events:
        return result
    for ev in events:
        try:
            applied = apply_event(state, ev)
            result["applied"].append(applied)
            AUDIT.record(state.name, "event", applied.summary, ref=applied.id, payload=applied)
        except EventError as e:
            result["error"] = f"{ev.type}: {e}"
            break
    if result["applied"]:
        run = agent.start_run(
            state,
            trigger="message",
            focus=result["applied"][-1],
            question=f'Field message: "{msg.text}". Understood as: {parsed.understood_en}',
        )
        result["run_id"] = run.id
    return result


@router.post("/plans/simulate")
def post_simulate(plan: Plan, state: WorldState = World) -> dict:
    """What-if: run the plan on a copy of the world and return before/after KPIs and per-trip changes."""
    return simulate_plan(state, plan)


@router.post("/plans/apply")
def post_apply(plan: Plan, state: WorldState = World) -> EventRecord:
    """Operator approved: apply the plan for real."""
    try:
        record = apply_plan(state, plan)
    except ActionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    AUDIT.record(state.name, "plan_applied", record.summary, ref=record.id, payload=record)
    return record


@router.post("/admin/reset")
def reset(state: WorldState = World) -> dict:
    agent.cancel_all(state)
    seed_world(state, config.RANDOM_SEED)
    AUDIT.record(state.name, "reset", f"{state.name} world reset")
    return {"ok": True, "world": state.name, "trips": len(state.trips), "vehicles": len(state.vehicles)}


@router.get("/admin/scenarios")
def list_scenarios(state: WorldState = World) -> list[dict]:
    if not state.hypothetical:
        return []
    return [{"name": k, "title": title} for k, (title, _) in demo.SCENARIOS.items()]


@router.post("/admin/scenario/{name}")
async def run_scenario(name: str, state: WorldState = World) -> dict:
    """Reset, fast-forward to the scenario's moment, apply its events, start one agent analysis."""
    if not state.hypothetical:
        raise HTTPException(status_code=400, detail="Demo scenarios run in the simulation, not in live mode")
    try:
        result = demo.run_scenario(state, name)
        AUDIT.record(state.name, "scenario", f"Scenario: {result['title']}", ref=name, payload=result)
        return result
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Unknown scenario {name}") from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


def _find_run(state: WorldState, run_id: str) -> AgentRun:
    run = next((r for r in state.agent_runs if r.id == run_id), None)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown run {run_id}")
    return run


@router.post("/agent/analyze")
async def analyze(req: AnalyzeRequest | None = None, state: WorldState = World) -> AgentRun:
    """Ask the agent to review this world's situation (optionally with a question). Runs in the background."""
    return agent.start_run(state, trigger="operator", question=req.question if req else None)


@router.get("/agent/runs")
def list_runs(state: WorldState = World) -> list[AgentRun]:
    return list(reversed(state.agent_runs))


@router.get("/agent/runs/{run_id}")
def get_run(run_id: str, state: WorldState = World) -> AgentRun:
    return _find_run(state, run_id)


@router.post("/agent/runs/{run_id}/approve")
def approve(run_id: str, req: ApproveRequest, state: WorldState = World) -> AgentRun:
    """Operator approves one option: its steps are re-checked against the current world and applied."""
    run = _find_run(state, run_id)
    if run.status != "done" or run.recommendation is None:
        raise HTTPException(status_code=409, detail=f"Run {run_id} is {run.status}; nothing to approve")
    options = run.recommendation.options
    if not 0 <= req.option_index < len(options):
        raise HTTPException(status_code=400, detail="option_index out of range")
    option = options[req.option_index]
    applied_event = None
    if option.steps:
        try:
            applied_event = apply_plan(state, Plan(steps=option.steps, rationale=f"Approved: {option.title}"))
        except ActionError as e:
            # The world moved on since the recommendation (e.g. a patient was picked up meanwhile).
            raise HTTPException(status_code=409, detail=f"Plan no longer valid: {e}. Ask for a new analysis.") from e
    run.status = "approved"
    run.decision = {
        "option_index": req.option_index,
        "title": option.title,
        "event_id": applied_event.id if applied_event else None,
        "at": utcnow().isoformat(),
    }
    run.log("info", f"Operator approved option {req.option_index + 1}: {option.title}")
    AUDIT.record(
        state.name,
        "decision_approved",
        f"Operator approved option {req.option_index + 1}: {option.title}",
        ref=run.id,
        payload={"option": option, "decision": run.decision},
    )
    state.bump()
    return run


@router.post("/agent/runs/{run_id}/reject")
def reject(run_id: str, req: RejectRequest | None = None, state: WorldState = World) -> AgentRun:
    run = _find_run(state, run_id)
    if run.status not in ("done", "running"):
        raise HTTPException(status_code=409, detail=f"Run {run_id} is {run.status}")
    run.status = "rejected"
    run.decision = {"reason": req.reason if req else None, "at": utcnow().isoformat()}
    run.log("info", "Operator rejected the recommendation" + (f": {req.reason}" if req and req.reason else ""))
    AUDIT.record(state.name, "decision_rejected", "Operator rejected the recommendation", ref=run.id, payload=run.decision)
    state.bump()
    return run


@app.get("/audit")
async def get_audit(world: str | None = None, kind: str | None = None, limit: int = 200) -> dict:
    """The audit trail, newest first: events, field messages, AI recommendations, operator decisions."""
    return {"status": AUDIT.summary(), "entries": await AUDIT.query(world, kind, limit)}


@app.get("/audit/export")
async def export_audit(world: str | None = None, limit: int = 2000) -> StreamingResponse:
    """Download the audit trail as JSON lines (one entry per line)."""
    entries = await AUDIT.query(world, None, limit)
    lines = [json.dumps(e, ensure_ascii=False) for e in reversed(entries)]
    body = "".join(line + "\n" for line in lines)
    return StreamingResponse(
        iter([body]),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=plan-b-audit.jsonl"},
    )


app.include_router(router)
