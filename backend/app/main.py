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

from . import config
from .engine.actions import ActionError
from .engine.events import EventError, apply_event
from .engine.plans import apply_plan, simulate_plan
from .engine.projection import kpis, project_all
from .fetchers.base import run_periodic
from .fetchers.traffic import update_traffic
from .fetchers.weather import fetch_weather
from .models import EventRecord, OperatorEvent, Plan, utcnow
from .sim.seed import seed_world
from .sim.simulator import tick
from .state import WorldState

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
        asyncio.create_task(
            run_periodic(state, "traffic", "fallback", config.TRAFFIC_INTERVAL_S, lambda: update_traffic(state)),
            name="traffic",
        ),
    ]
    log.info("backend started: %d vehicles, %d trips", len(state.vehicles), len(state.trips))
    yield
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


@app.post("/events")
def post_event(event: OperatorEvent = Body(...)) -> EventRecord:
    """Inject an event: breakdown, delay, road_closure, clear_incident, urgent_request, weather_override."""
    try:
        return apply_event(state, event)
    except EventError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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
    seed_world(state, config.RANDOM_SEED)
    return {"ok": True, "trips": len(state.trips), "vehicles": len(state.vehicles)}
