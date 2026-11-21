"""Reproducible one-click demo scenarios for the pitch.

Each scenario re-seeds the world, fast-forwards the simulation to an interesting moment,
applies several events at once and starts ONE agent analysis of the combined situation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from . import config
from .agent import runner as agent
from .engine.events import apply_event
from .engine.projection import project_all
from .models import (
    BreakdownEvent,
    DelayEvent,
    EventRecord,
    RoadClosureEvent,
    UrgentRequestEvent,
    Vehicle,
    WeatherOverrideEvent,
)
from .sim.seed import seed_world
from .sim.simulator import tick

if TYPE_CHECKING:
    from .state import WorldState

STEP_S = 30.0
MAX_FAST_FORWARD_MIN = 90


def _fast_forward(state: WorldState, minutes: float, until: Callable[[], Vehicle | None] | None = None) -> Vehicle | None:
    for _ in range(int(minutes * 60 / STEP_S)):
        tick(state, STEP_S)
        project_all(state)
        if until and (found := until()):
            return found
    return None


def _van_with_patient(state: WorldState) -> Vehicle | None:
    return next(
        (v for v in state.vehicles.values() if v.type == "transport" and v.status == "with_patient" and v.queue),
        None,
    )


def _stranded_patient(state: WorldState) -> list[EventRecord]:
    van = _fast_forward(state, MAX_FAST_FORWARD_MIN, until=lambda: _van_with_patient(state))
    if van is None:
        raise RuntimeError("no van with a patient on board within the fast-forward window")
    return [apply_event(state, BreakdownEvent(type="breakdown", vehicle_id=van.id, note="engine failure, patient on board"))]


def _stroke_rush_hour(state: WorldState) -> list[EventRecord]:
    _fast_forward(state, 5)
    return [
        apply_event(
            state,
            RoadClosureEvent(
                type="road_closure", lat=46.0565, lon=14.5300, radius_m=500,
                description="Zaloška cesta closed after a collision (near UKC)",
            ),
        ),
        apply_event(
            state,
            UrgentRequestEvent(
                type="urgent_request", pickup_id="home_polje", dropoff_id="ukc", needs="stretcher",
                priority="emergency", note="suspected stroke, FAST positive",
            ),
        ),
    ]


def _snow_cascade(state: WorldState) -> list[EventRecord]:
    _fast_forward(state, 10)
    busiest_van = max(
        (v for v in state.vehicles.values() if v.type == "transport"),
        key=lambda v: len(v.queue),
    )
    return [
        apply_event(state, WeatherOverrideEvent(type="weather_override", snowfall_cm=3, temperature_c=-2, precipitation_mm=3)),
        apply_event(state, DelayEvent(type="delay", vehicle_id=busiest_van.id, minutes=25, note="stuck behind a jack-knifed truck")),
        apply_event(
            state,
            UrgentRequestEvent(
                type="urgent_request", pickup_id="home_siska", dropoff_id="ukc", needs="stretcher",
                priority="emergency", note="fall on ice, suspected hip fracture",
            ),
        ),
    ]


SCENARIOS: dict[str, tuple[str, Callable[[WorldState], list[EventRecord]]]] = {
    "stranded_patient": ("Van breaks down with a patient on board", _stranded_patient),
    "stroke_rush_hour": ("Stroke emergency with a road closure near UKC", _stroke_rush_hour),
    "snow_cascade": ("Snowstorm, a delayed van and an emergency at once", _snow_cascade),
}


def run_scenario(state: WorldState, name: str) -> dict[str, Any]:
    if name not in SCENARIOS:
        raise KeyError(name)
    title, build = SCENARIOS[name]
    agent.cancel_all()
    seed_world(state, config.RANDOM_SEED)
    records = build(state)
    question = (
        f"Demo scenario: {title}. These events just happened together: "
        + "; ".join(f"({i + 1}) {r.summary}" for i, r in enumerate(records))
        + ". Analyse the combined situation and recommend what to do."
    )
    # Pass a focus record so build_user_message emits the explicit KPI-delta line
    # ("unassigned 0 -> N") that tells Claude action is required. Without focus,
    # Claude only sees the current snapshot and may conclude nothing changed.
    if len(records) == 1:
        focus = records[0]
    else:
        # Synthesise one record spanning all events so the aggregate delta is shown.
        all_affected = list(dict.fromkeys(tid for r in records for tid in r.affected_trip_ids))
        focus = EventRecord(
            id=records[0].id,
            sim_time=records[0].sim_time,
            type="scenario",
            payload={},
            summary="; ".join(r.summary for r in records),
            affected_trip_ids=all_affected,
            kpis_before=records[0].kpis_before,
            kpis_after=records[-1].kpis_after,
        )
    run = agent.start_run(state, trigger=f"scenario:{name}", focus=focus, question=question)
    state.bump()
    return {"scenario": name, "title": title, "events": records, "run_id": run.id}
