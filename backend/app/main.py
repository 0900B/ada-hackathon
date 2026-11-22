"""FastAPI app: runs the shared live feeds and two worlds, and exposes them per world.

- /live/...  real time, real weather/traffic/incidents; operators may report real events
- /sim/...   presentation sandbox: faster clock, hypothetical weather, demo scenarios, reset
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Literal

import httpx
from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Path, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from . import ai_dispatcher, approvals, config, demo, intake, overrides
from .agent import runner as agent
from .agent.messages import FieldMessage, MessageError, parse_message, to_operator_events
from .guard import GUARD, message_limit_detail
from .audit import AUDIT
from .engine import followup, surge, timeline
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
from . import navigation, tiles
from .vehicles import vehicle_detail
from .sim import calls, incidents
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
HTTP: httpx.AsyncClient | None = None  # shared client, set at startup (used by the tile proxy)


def bump_all() -> None:
    for w in WORLDS.values():
        w.bump()


def call_problem(w: WorldState, record: EventRecord) -> None:
    """Every 112 call after the engine's dispatch (typed, demo, generated). A critical or serious one is
    reviewed by the AI dispatcher (app/ai_dispatcher.py: autonomous mode, or assisted with auto-analyse).
    A call that needs a dispatcher's attention is audited; with auto-analyse on (rate-limited) an analysis
    starts, unless the AI dispatcher is already reviewing it."""
    reviewed = ai_dispatcher.on_new_call(w, record)
    problem = calls.problem_of(w, record)
    if problem is None:
        return
    AUDIT.record(w.name, "event", f"{record.summary} [needs attention: {problem}]", ref=record.id, payload=record)
    if not reviewed and calls.may_analyse(w):
        agent.start_run(w, trigger=f"call:{record.id}", focus=record, question=f"A live call needs attention: {problem}.")


def _defer_to_ai(w: WorldState, ev, call) -> bool:
    return intake.defer_generated(w, ev, call, call_problem)


def take_calls(w: WorldState) -> None:
    """Live-calls mode: new calls come in and the engine dispatches each at once. A routine call
    never starts an AI analysis; a genuine problem (no unit can take it, or it will be late) may,
    and only if this world's auto-analyse is on (at most one such run every 15 world-minutes).
    With ai_triage on, Claude triages a 112 call first (guarded; app/intake.py)."""
    for record, _problem in calls.step(w, intake=_defer_to_ai if w.ai_triage else None):
        call_problem(w, record)
    # The high-demand alert (engine/surge.py, with hysteresis) turning on: logged, and with auto-analyse
    # on (rate-limited like call problems) an analysis may propose surge capacity. Nothing is activated
    # automatically.
    on = surge.alert_on(w)
    if on and not w.demand_was_high:
        d = surge.demand(w)
        AUDIT.record(w.name, "event", "High demand: " + "; ".join(d["reasons"]), ref="high_demand", payload=d)
        if surge.patients_affected(d) and not surge.active(w) and calls.may_analyse(w):  # not for "no ambulance free" alone
            agent.start_run(w, trigger="demand", question=(
                "High demand: " + "; ".join(d["reasons"]) + ". Consider activating the contracted surge capacity "
                "(an option with activate_surge true) rather than displacing patients."))
    w.demand_was_high = on


async def sim_loop() -> None:
    """Advance both fleets (our stand-in GPS feed) and re-project every trip."""
    status = feed.register_source("vehicle_gps", "simulated", config.SIM_TICK_S)
    while True:
        status.last_attempt = utcnow()
        errors = []
        for w in WORLDS.values():
            try:
                tick(w, config.SIM_TICK_S * w.speedup)
                take_calls(w)
                followup.check(w)  # 112 calls: re-dispatch, a faster free unit, a doctor car (engine/followup.py)
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
        seed_world(w, config.RANDOM_SEED, scheduled_day=config.SCHEDULED_DAY)  # live calls unless SCHEDULED_DAY=1
    global HTTP
    client = httpx.AsyncClient(timeout=10.0, headers={"User-Agent": config.HTTP_USER_AGENT})
    HTTP = client
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


class LegacyPathsToSim:
    """Backwards compatibility: pre-split clients (e.g. the `client/` app on the Klimentina branch) call
    unprefixed paths like /state, /stream or /agent/runs/... They're served by the simulation world.
    Pure ASGI (not BaseHTTPMiddleware) so the SSE stream passes through untouched."""

    PREFIXES = ("/state", "/stream", "/alerts", "/kpis", "/events", "/plans", "/admin", "/agent", "/messages", "/vehicles")

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            path = scope["path"]
            if any(path == p or path.startswith(p + "/") for p in self.PREFIXES):
                scope = {**scope, "path": "/sim" + path, "raw_path": ("/sim" + path).encode()}
        await self.app(scope, receive, send)


app = FastAPI(title="Emergency transport assistant - backend", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(LegacyPathsToSim)


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
        "traffic_tiles": tiles.status(),
        "claude": {"enabled": config.agent_enabled(), **GUARD.status()},
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


ANALYSE_LOOKBACK_MIN = 30  # Analyse looks at operator events from the last 30 world-minutes
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


@router.get("/vehicles/{vehicle_id}")
def get_vehicle(vehicle_id: str, state: WorldState = World) -> dict:
    """Vehicle card: crew, fuel, capabilities, upcoming stops with ETAs, and road geometry of each leg."""
    v = state.vehicles.get(vehicle_id)
    if v is None:
        raise HTTPException(status_code=404, detail=f"Unknown vehicle {vehicle_id}")
    return vehicle_detail(state, v)


@router.get("/vehicles/{vehicle_id}/navigation")
async def get_navigation(vehicle_id: str, state: WorldState = World) -> dict:
    """In-vehicle tablet: the next manoeuvres (OSRM, cached, fetched in the background) and the
    distance and time to the next stop. Never waits on OSRM; an empty step list means "not yet"."""
    v = state.vehicles.get(vehicle_id)
    if v is None:
        raise HTTPException(status_code=404, detail=f"Unknown vehicle {vehicle_id}")
    return navigation.navigation(state, v)


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
    unplaced_booking = event.type == "task_request" and any(
        state.trips[t].status == "unassigned" for t in record.affected_trip_ids if t in state.trips
    )
    # A disruption touching an open 112 call: the AI dispatcher reviews that call (app/ai_dispatcher.py);
    # otherwise, with auto-analyse on, the usual analysis of the event.
    reviewed = ai_dispatcher.after_event(state, record)
    if not reviewed and state.auto_analyze and ((event.type in DISRUPTIVE_EVENTS and not clearing) or unplaced_booking):
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
    if not GUARD.try_acquire("message"):  # Claude usage limit (cost/abuse guard for the live demo)
        retry = GUARD.retry_after_s()
        AUDIT.record(state.name, "field_message", f'"{msg.text}" -> not processed: AI limit reached', ref=msg.sender_vehicle_id)
        raise HTTPException(status_code=429, detail=message_limit_detail(retry), headers={"Retry-After": str(retry)})
    try:
        parsed = await parse_message(state, msg.text, msg.sender_vehicle_id)
        events = to_operator_events(state, parsed, msg.text)
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
    reviewed = [r for r in result["applied"] if ai_dispatcher.after_event(state, r)]  # the AI dispatcher (every event)
    if result["applied"] and state.auto_analyze and not reviewed:
        run = agent.start_run(
            state,
            trigger="message",
            focus=result["applied"][-1],
            question=f'Field message: "{msg.text}". Understood as: {parsed.understood_en}',
        )
        result["run_id"] = run.id if run else None  # None: skipped (AI usage limit)
    return result


@router.post("/plans/simulate")
def post_simulate(plan: Plan, state: WorldState = World) -> dict:
    """What-if: run the plan on a copy of the world and return before/after KPIs and per-trip changes."""
    return simulate_plan(state, plan)


@router.post("/plans/apply")
def post_apply(plan: Plan, state: WorldState = World) -> EventRecord:
    """Operator approved: apply the plan for real."""
    tracker = timeline.Tracker(state)
    try:
        record = apply_plan(state, plan)
    except ActionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    tracker.log_changes("dispatcher", detail="dispatcher plan")
    AUDIT.record(state.name, "plan_applied", record.summary, ref=record.id, payload=record)
    return record


class ResetRequest(BaseModel):
    # None keeps the world's current mode; True = the pre-planned scheduled day ("initial plan");
    # False = live calls (no pre-planned trips; calls come in and are dispatched at once).
    scheduled_day: bool | None = None


@router.post("/admin/reset")
def reset(req: ResetRequest | None = None, state: WorldState = World) -> dict:
    """Re-seed this world. Body (optional): {"scheduled_day": true|false} switches the mode."""
    agent.cancel_all(state)
    seed_world(state, config.RANDOM_SEED, scheduled_day=req.scheduled_day if req else None)
    mode = "scheduled_day" if state.scheduled_day else "live_calls"
    AUDIT.record(state.name, "reset", f"{state.name} world reset ({mode.replace('_', ' ')})")
    return {
        "ok": True,
        "world": state.name,
        "mode": mode,
        "scheduled_day": state.scheduled_day,
        "trips": len(state.trips),
        "vehicles": len(state.vehicles),
    }


class CallsRequest(BaseModel):
    enabled: bool | None = None
    per_hour: float | None = Field(default=None, gt=0, le=60)


@router.post("/admin/calls")
def set_calls(req: CallsRequest, state: WorldState = World) -> dict:
    """Live-calls generator for this world: switch it on/off, or change the rate (calls per world hour)."""
    if req.enabled is not None:
        state.calls.enabled = req.enabled
    if req.per_hour is not None:
        state.calls.per_hour = req.per_hour
        state.calls.next_at = state.sim_time + state.calls._gap()
    AUDIT.record(state.name, "setting", f"Live calls {'on' if state.calls.enabled else 'off'}, {state.calls.per_hour:g}/h")
    state.bump()
    return {"world": state.name, **state.calls.status(state)}


class SwitchRequest(BaseModel):
    enabled: bool


@router.post("/admin/ai-triage")
def set_ai_triage(req: SwitchRequest, state: WorldState = World) -> dict:
    """Generated and demo (random) 112 calls: triage by Claude (guarded; else the keyword rules) or by the
    rules only (default). Calls typed by the call-taker (POST /calls) always try Claude first."""
    state.ai_triage = req.enabled
    AUDIT.record(state.name, "setting", f"AI triage {'on' if req.enabled else 'off'}")
    state.bump()
    return {"world": state.name, "ai_triage": state.ai_triage}


class AiModeRequest(BaseModel):
    mode: Literal["assisted", "autonomous"]


def _set_ai_mode(state: WorldState, mode: str) -> None:
    if state.ai_mode != mode:
        state.ai_mode = mode
        AUDIT.record(state.name, "setting", f"AI dispatcher: {mode}")
    state.bump()


@router.post("/admin/ai-mode")
def set_ai_mode(req: AiModeRequest, state: WorldState = World) -> dict:
    """The AI dispatcher (app/ai_dispatcher.py). "autonomous": Claude reviews every new critical/serious
    call and every disruption of an open call, and its recommendation is applied (re-checked by the engine,
    audited). "assisted" (default): the same reviews only with auto-analyse on, as proposals."""
    _set_ai_mode(state, req.mode)
    return {"world": state.name, "ai_mode": state.ai_mode, "autopilot": state.autopilot}


@router.post("/admin/autopilot")
def set_autopilot(req: SwitchRequest, state: WorldState = World) -> dict:
    """The old switch, kept as an alias: on = ai_mode "autonomous", off = "assisted". The recommended
    feasible option of every analysis about an active call is approved by the engine (same path as the
    dispatcher's approval, audited). Surge capacity stays manual."""
    _set_ai_mode(state, "autonomous" if req.enabled else "assisted")
    return {"world": state.name, "autopilot": state.autopilot}


class AssignRequest(BaseModel):
    vehicle_id: str
    mode: Literal["replace", "add"] = "replace"


@router.get("/trips/{trip_id}/alternatives")
def get_alternatives(trip_id: str, role: Literal["ambulance", "doctor", "helicopter"] = "ambulance",
                     state: WorldState = World) -> list[dict]:
    """Who else could do this unit's job, ranked by arrival at the patient (the engine simulates each on a
    copy): eta, delta_min vs the current unit (negative = sooner), free, cost_text, feasible, note."""
    try:
        return overrides.alternatives(state, trip_id, role)
    except overrides.OverrideError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/trips/{trip_id}/assign")
def assign_unit(trip_id: str, req: AssignRequest, state: WorldState = World) -> dict:
    """The dispatcher intervenes: "replace" swaps the transporting unit (or the doctor car), "add" adds a
    doctor car, or a further ambulance / the helicopter for another patient of the call (a linked trip).
    Simulated first, applied through the plan path, audited; timeline "override". Returns {trip, summary};
    400 with the reason if it cannot be done (e.g. the patient is on board)."""
    try:
        return overrides.assign(state, trip_id, req.vehicle_id, req.mode)
    except overrides.OverrideError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


@router.post("/calls")
async def post_call(req: intake.CallRequest, state: WorldState = World) -> dict:
    """A 112 call typed by the call-taker: the caller's words and where. Claude triages it (through the
    usage guard); when Claude is off, limited, slow or fails, the keyword rules do (never fails the call).
    Then the normal dispatch path. Returns {trip (with call and timeline), summary}."""
    try:
        record, result = await intake.take_call(state, req)
    except intake.LocationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except EventError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    call_problem(state, record)
    return intake.response(state, record, result)


class RandomCallRequest(BaseModel):
    severity: Literal["critical", "serious", "urgent"] | None = None


@router.post("/admin/random-call")
async def random_call(req: RandomCallRequest | None = None, state: WorldState = World) -> dict:
    """Demo: one 112 call from the library (sim/calls.py: caller, street address, Slovenian words),
    through the same intake path (Claude triages only with ai_triage on). Simulation only."""
    if not state.hypothetical:
        raise HTTPException(status_code=400, detail="Demo calls run in the simulation, not in live mode")
    try:
        record, result = await intake.random_call(state, req.severity if req else None)
    except EventError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    call_problem(state, record)
    return intake.response(state, record, result)


class RandomIncidentRequest(BaseModel):
    kind: Literal["crash", "closure", "fog", "breakdown", "delay", "capacity", "equipment"] | None = None


@router.post("/admin/random-incident")
def random_incident(req: RandomIncidentRequest | None = None, state: WorldState = World) -> dict:
    """Demo: a disruption that hits current operations (sim/incidents.py), applied through the normal
    event path. The event's payload names the unit hit (vehicle_id) and its call comes first in
    affected_trip_ids. 409 when nothing is happening to disrupt. Simulation only."""
    if not state.hypothetical:
        raise HTTPException(status_code=400, detail="Demo incidents run in the simulation, not in live mode")
    project_all(state)
    target, note = incidents.pick(state, state.calls.text_rng, req.kind if req else None)
    if target is None:
        raise HTTPException(status_code=409, detail=note)
    try:
        record = apply_event(state, target.event, reported_by=target.reported_by)
    except EventError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    record.payload["vehicle_id"] = target.vehicle_id
    record.payload["incident_kind"] = target.kind
    if target.trip_id:
        record.affected_trip_ids = [target.trip_id] + [t for t in record.affected_trip_ids if t != target.trip_id]
    follow = followup.check(state, force=True)  # the engine's automatic reaction, now rather than at the next check
    summary = " ".join(filter(None, [note, record.summary])) + (f"; engine: {'; '.join(follow)}" if follow else "")
    AUDIT.record(state.name, "event", f"Demo incident ({target.kind}): {summary}", ref=record.id, payload=record)
    reviewed = ai_dispatcher.after_event(state, record)  # after the engine's reaction: Claude reviews the call
    if not reviewed and state.auto_analyze and record.type in DISRUPTIVE_EVENTS:
        agent.start_run(state, trigger=f"event:{record.id}", focus=record)
    state.bump()
    return {"event": record.model_dump(mode="json"), "summary": summary, "kind": target.kind}


class SurgeRequest(BaseModel):
    ambulances: int = Field(default=len(surge.SURGE_AMBULANCES), ge=0, le=len(surge.SURGE_AMBULANCES))
    vans: int = Field(default=len(surge.SURGE_VANS), ge=0, le=len(surge.SURGE_VANS))
    hours: float = Field(default=surge.SURGE_HOURS, gt=0, le=surge.SURGE_MAX_HOURS)
    stand_down: bool = False


def _surge_result(state: WorldState, record: EventRecord | None) -> dict:
    if record is not None:
        AUDIT.record(state.name, "surge", record.summary, ref=record.id, payload=record)
    state.bump()
    return {"world": state.name, "surge": surge.status(state), "event": record}


@router.post("/admin/surge")
def set_surge(req: SurgeRequest | None = None, state: WorldState = World) -> dict:
    """The dispatcher activates contracted surge capacity (engine/surge.py) for `hours`, or stands it
    down (`stand_down: true`). Never done automatically: the high_demand alert only offers it."""
    req = req or SurgeRequest()
    if req.stand_down:
        return _surge_result(state, surge.stand_down(state))
    if req.ambulances + req.vans == 0:
        raise HTTPException(status_code=400, detail="Ask for at least one ambulance or van")
    if not any(surge.available(state).values()) and not surge.active(state):
        raise HTTPException(status_code=409, detail="No contracted units are available")
    return _surge_result(state, surge.activate(state, req.ambulances, req.vans, req.hours))


@router.post("/admin/surge/stand-down")
def stand_down_surge(state: WorldState = World) -> dict:
    """End the contract now: the contracted units finish their current job, return and leave."""
    return _surge_result(state, surge.stand_down(state))


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


class AutoAnalyzeRequest(BaseModel):
    enabled: bool


@router.post("/agent/auto")
def set_auto_analyze(req: AutoAnalyzeRequest, state: WorldState = World) -> dict:
    """Switch automatic AI analysis on/off for this world (off by default: every analysis costs tokens)."""
    state.auto_analyze = req.enabled
    AUDIT.record(state.name, "setting", f"Auto-analyse {'on' if req.enabled else 'off'}")
    state.bump()
    return {"world": state.name, "auto": state.auto_analyze}


@router.post("/agent/analyze")
async def analyze(req: AnalyzeRequest | None = None, state: WorldState = World) -> AgentRun:
    """Ask the agent to review this world's situation (optionally with a question). Runs in the background.

    It focuses on what happened since the last analysis: one new event becomes the run's focus, several
    are listed together. A demo scenario's description is used only if nothing else happened after it."""
    extra = req.question if req else None
    pending, state.pending_question = state.pending_question, None
    scenario_ids, state.pending_scenario_events = state.pending_scenario_events, set()
    recent_after = state.sim_time - timedelta(minutes=ANALYSE_LOOKBACK_MIN)
    new = [
        e
        for e in state.events[state.analysed_events :]
        if not e.generated and e.type != "plan_applied" and e.sim_time >= recent_after
    ]
    focus, question = None, None
    if pending and new and all(e.id in scenario_ids for e in new):
        question = pending  # nothing else happened since the scenario: analyse the scenario
    elif len(new) == 1:
        focus = new[0]
        question = "Focus on this event: what it affects and what the dispatcher should do now."
    elif new:
        focus = new[-1]  # the operator's latest report is what they want answered
        earlier = "; ".join(f"({i + 1}) {e.summary}" for i, e in enumerate(new[-6:-1]))
        question = (
            "Focus on the newest event: what it affects and what the dispatcher should do now. "
            f"Also not yet analysed: {earlier}. Mention those only where they interact with it."
        )
    if extra:
        question = f"{question} {extra}" if question else extra
    return agent.start_run(state, trigger="operator", focus=focus, question=question)


@router.get("/agent/runs")
def list_runs(state: WorldState = World) -> list[AgentRun]:
    return list(reversed(state.agent_runs))


@router.get("/agent/runs/{run_id}")
def get_run(run_id: str, state: WorldState = World) -> AgentRun:
    return _find_run(state, run_id)


@router.post("/agent/runs/{run_id}/approve")
async def approve(run_id: str, req: ApproveRequest, state: WorldState = World) -> AgentRun:
    """Operator approves one option: its steps are re-checked against the current world and applied
    (app/approvals.py; the autopilot uses the same path). If the outcome is now clearly worse than
    shown, the approval is refused with the reason (409) and, with auto-analyse on, a fresh analysis
    starts."""
    run = _find_run(state, run_id)
    try:
        return approvals.approve(state, run, req.option_index, by="dispatcher")
    except approvals.ApprovalError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


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


@app.get("/tiles/traffic/{layer}/{z}/{x}/{y}.png")
async def traffic_tile(layer: str, z: int, x: int, y: int) -> Response:
    """TomTom traffic tiles (layer: flow or incidents) via our cache; the API key stays on the server."""
    content, _real, max_age = await tiles.get_tile(HTTP, layer, z, x, y)
    # browsers keep a tile for what is left of its two minutes in our cache (reloads don't re-ask)
    return Response(content, media_type="image/png", headers={"Cache-Control": f"public, max-age={max_age}"})


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
