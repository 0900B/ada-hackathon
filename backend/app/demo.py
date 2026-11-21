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
    HospitalCapacityEvent,
    PriorityChangeEvent,
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


def _van_carrying(state: WorldState, kind: str) -> Vehicle | None:
    """A van with a patient (or equipment) on board and more trips queued."""
    return next(
        (
            v
            for v in state.vehicles.values()
            if v.type == "transport"
            and v.status == "with_patient"  # loaded (patient or equipment)
            and v.queue
            and v.current_trip_id
            and state.trips[v.current_trip_id].kind == kind
        ),
        None,
    )


def _stranded_patient(state: WorldState) -> list[EventRecord]:
    van = _fast_forward(state, MAX_FAST_FORWARD_MIN, until=lambda: _van_carrying(state, "patient"))
    if van is None:
        raise RuntimeError("no van with a patient on board within the fast-forward window")
    return [apply_event(state, BreakdownEvent(type="breakdown", vehicle_id=van.id, note="engine failure, patient on board"))]


def _loaded_with_equipment(state: WorldState) -> Vehicle | None:
    return next(
        (
            v
            for v in state.vehicles.values()
            if v.current_trip_id
            and state.trips[v.current_trip_id].kind == "equipment"
            and state.trips[v.current_trip_id].status == "onboard"
        ),
        None,
    )


def _stranded_equipment(state: WorldState) -> list[EventRecord]:
    v = _fast_forward(state, MAX_FAST_FORWARD_MIN, until=lambda: _loaded_with_equipment(state))
    if v is None:
        raise RuntimeError("no vehicle with equipment on board within the fast-forward window")
    return [apply_event(state, BreakdownEvent(type="breakdown", vehicle_id=v.id, note="gearbox failure, equipment on board"))]


def _equipment_en_route(state: WorldState) -> list[EventRecord]:
    """Preparation for the live crew demo: stop when a van is carrying equipment. No events, no AI run:
    the crew then reports the problem themselves from /crew/<vehicle> ("Vozilo je obstalo. Oprema je še v njem.")."""
    v = _fast_forward(state, MAX_FAST_FORWARD_MIN, until=lambda: _loaded_with_equipment(state))
    if v is None:
        raise RuntimeError("no vehicle with equipment on board within the fast-forward window")
    return []


def _hospital_full(state: WorldState) -> list[EventRecord]:
    _fast_forward(state, 5)
    to_ukc = sorted(
        (
            t
            for t in state.trips.values()
            if t.dropoff_id == "ukc" and t.kind == "patient" and t.status == "assigned"
            and t.vehicle_id and state.vehicles[t.vehicle_id].type == "transport"
        ),
        key=lambda t: t.due_by,
    )
    if not to_ukc:
        raise RuntimeError("no van trip heading to UKC to escalate")
    return [
        apply_event(
            state,
            PriorityChangeEvent(
                type="priority_change", trip_id=to_ukc[0].id, priority="emergency", note="condition worsened, chest pain"
            ),
        ),
        apply_event(
            state,
            HospitalCapacityEvent(type="hospital_capacity", place_id="ukc", capacity=1, note="emergency department full"),
        ),
    ]


def _stroke_rush_hour(state: WorldState) -> list[EventRecord]:
    _fast_forward(state, 5)
    return [
        apply_event(
            state,
            RoadClosureEvent(
                type="road_closure", lat=46.05615, lon=14.53621, radius_m=250,
                description="Zaloška cesta closed after a collision (Kodeljevo, on the way to UKC)",
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
    "stranded_equipment": ("Vehicle breaks down with medical equipment on board", _stranded_equipment),
    "hospital_full": ("UKC can admit only one more patient as a patient becomes an emergency", _hospital_full),
    "equipment_en_route": ("Prep for the live crew demo: a van is carrying equipment", _equipment_en_route),
}


def run_scenario(state: WorldState, name: str) -> dict[str, Any]:
    if name not in SCENARIOS:
        raise KeyError(name)
    title, build = SCENARIOS[name]
    agent.cancel_all(state)
    seed_world(state, config.RANDOM_SEED)
    records = build(state)
    if not records:  # preparation scenario: nothing happened yet, so no AI run
        v = _loaded_with_equipment(state)
        trip = state.trips[v.current_trip_id] if v and v.current_trip_id else None
        note = (
            f"{v.id} ({v.name}) is carrying {trip.cargo} to {state.places[trip.dropoff_id].name}. "
            f"Open /crew/{v.id}?world=sim on the phone and report the problem."
            if v and trip
            else "Ready."
        )
        state.bump()
        return {"scenario": name, "title": title, "events": [], "run_id": None, "note": note, "vehicle_id": v.id if v else None}
    question = (
        f"Demo scenario: {title}. These events just happened together: "
        + "; ".join(f"({i + 1}) {r.summary}" for i, r in enumerate(records))
        + ". Analyse the combined situation and recommend what to do."
    )
    if not state.auto_analyze:  # analysis on demand only: the operator presses Analyse
        state.bump()
        note = f"Scenario started: {title}. Auto-analyse is off: press Analyse (A) for the AI's recommendation."
        return {"scenario": name, "title": title, "events": records, "run_id": None, "note": note}
    run = agent.start_run(state, trigger=f"scenario:{name}", question=question)
    state.bump()
    return {"scenario": name, "title": title, "events": records, "run_id": run.id}
