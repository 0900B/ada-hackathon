"""FastAPI app: starts the live loops and exposes state, events, plans and an SSE stream."""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import config, demo
from .agent import runner as agent
from .engine.actions import ActionError
from .engine.events import EventError, apply_event
from .engine.plans import apply_plan, simulate_plan
from .engine.projection import kpis, project_all
from .fetchers import tomtom
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
from .sim.seed import seed_world
from .sim.simulator import tick
from .state import WorldState

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # its request log prints full URLs, incl. TomTom's ?key=
log = logging.getLogger("app")

state = WorldState()


async def sim_loop() -> None:
    """Advance the simulated fleet (our stand-in GPS feed) and re-project every trip."""
    status = state.register_source("vehicle_gps", "simulated", config.SIM_TICK_S)
    while True:
        status.last_attempt = utcnow()
        try:
            tick(state, config.SIM_TICK_S * config.SIM_SPEEDUP)
            project_all(state)
            status.last_success, status.last_error = utcnow(), None
        except Exception as e:  # noqa: BLE001 - keep the loop alive, surface the error in /health
            log.exception("simulation tick failed")
            status.last_error = f"{type(e).__name__}: {e}"[:300]
        state.bump()
        await asyncio.sleep(config.SIM_TICK_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_world(state, config.RANDOM_SEED)
    client = httpx.AsyncClient(timeout=10.0, headers={"User-Agent": config.HTTP_USER_AGENT})
    tasks = [
        asyncio.create_task(sim_loop(), name="sim"),
        asyncio.create_task(
            run_periodic(state, "weather", "live", config.WEATHER_INTERVAL_S, lambda: fetch_weather(state, client)),
            name="weather",
        ),
    ]
    if tomtom.tomtom_key():
        tasks += [
            asyncio.create_task(
                run_periodic(state, "traffic", "live", config.TOMTOM_INTERVAL_S, lambda: tomtom.fetch_flow(state, client)),
                name="traffic",
            ),
            asyncio.create_task(
                run_periodic(
                    state, "incidents", "live", config.TOMTOM_INTERVAL_S, lambda: tomtom.fetch_incidents(state, client)
                ),
                name="incidents",
            ),
        ]
    else:
        tasks.append(
            asyncio.create_task(
                run_periodic(state, "traffic", "fallback", config.TRAFFIC_INTERVAL_S, lambda: update_traffic(state)),
                name="traffic",
            )
        )
    log.info(
        "backend started: %d vehicles, %d trips, agent %s",
        len(state.vehicles),
        len(state.trips),
        f"enabled ({config.AGENT_MODEL})" if config.agent_enabled() else "disabled (no ANTHROPIC_API_KEY): engine fallback only",
    )
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
    return {"service": "emergency-transport-backend", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "sim_time": state.sim_time.isoformat(),
        "sources": {k: s.model_dump(mode="json") for k, s in state.sources.items()},
    }


@app.get("/state")
def get_state() -> dict:
    return state.snapshot()


@app.get("/alerts")
def get_alerts() -> list[dict]:
    return [a.model_dump(mode="json") for a in state.alerts]


@app.get("/kpis")
def get_kpis() -> dict:
    return kpis(state)


@app.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    """Server-sent events: a full snapshot whenever the state changes (about every tick)."""

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


DISRUPTIVE_EVENTS = {"breakdown", "delay", "road_closure", "urgent_request", "weather_override"}


@app.post("/events")
async def post_event(event: OperatorEvent = Body(...)) -> EventRecord:
    """Inject an event: breakdown, delay, road_closure, clear_incident, urgent_request, weather_override.

    Disruptive events start an agent analysis automatically (AGENT_AUTO=1).
    """
    try:
        record = apply_event(state, event)
    except EventError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    clearing = getattr(event, "clear", False)
    if config.AGENT_AUTO and event.type in DISRUPTIVE_EVENTS and not clearing:
        agent.start_run(state, trigger=f"event:{record.id}", focus=record)
    return record


@app.post("/plans/simulate")
def post_simulate(plan: Plan) -> dict:
    """What-if: run the plan on a copy of the world and return before/after KPIs and per-trip changes."""
    return simulate_plan(state, plan)


@app.post("/plans/apply")
def post_apply(plan: Plan) -> EventRecord:
    """Operator approved: apply the plan for real."""
    try:
        return apply_plan(state, plan)
    except ActionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/admin/reset")
def reset() -> dict:
    agent.cancel_all()
    seed_world(state, config.RANDOM_SEED)
    return {"ok": True, "trips": len(state.trips), "vehicles": len(state.vehicles)}


@app.get("/admin/scenarios")
def list_scenarios() -> list[dict]:
    return [{"name": k, "title": title} for k, (title, _) in demo.SCENARIOS.items()]


@app.post("/admin/scenario/{name}")
async def run_scenario(name: str) -> dict:
    """Reset, fast-forward to the scenario's moment, apply its events, start one agent analysis."""
    try:
        return demo.run_scenario(state, name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Unknown scenario {name}") from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


# --- Agent ---------------------------------------------------------------------------


def _find_run(run_id: str) -> AgentRun:
    run = next((r for r in state.agent_runs if r.id == run_id), None)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown run {run_id}")
    return run


@app.post("/agent/analyze")
async def analyze(req: AnalyzeRequest | None = None) -> AgentRun:
    """Ask the agent to review the current situation (optionally with a question). Runs in the background."""
    return agent.start_run(state, trigger="operator", question=req.question if req else None)


@app.get("/agent/runs")
def list_runs() -> list[AgentRun]:
    return list(reversed(state.agent_runs))


@app.get("/agent/runs/{run_id}")
def get_run(run_id: str) -> AgentRun:
    return _find_run(run_id)


@app.post("/agent/runs/{run_id}/approve")
def approve(run_id: str, req: ApproveRequest) -> AgentRun:
    """Operator approves one option: its steps are re-checked against the live world and applied."""
    run = _find_run(run_id)
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
    state.bump()
    return run


@app.post("/agent/runs/{run_id}/reject")
def reject(run_id: str, req: RejectRequest | None = None) -> AgentRun:
    run = _find_run(run_id)
    if run.status not in ("done", "running"):
        raise HTTPException(status_code=409, detail=f"Run {run_id} is {run.status}")
    run.status = "rejected"
    run.decision = {"reason": req.reason if req else None, "at": utcnow().isoformat()}
    run.log("info", "Operator rejected the recommendation" + (f": {req.reason}" if req and req.reason else ""))
    state.bump()
    return run
