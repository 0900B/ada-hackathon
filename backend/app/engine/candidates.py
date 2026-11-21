"""Candidate vehicles for a trip, ranked by simulated outcome, and a greedy fallback plan.

Every candidate is evaluated by actually simulating the insertion, so the numbers
include knock-on delays to the vehicle's later trips.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..models import Plan, PlanStep
from ..routing import haversine_km
from .actions import ActionError, assign_trip, can_serve
from .plans import simulate
from .projection import DONE, kpis, project_all

if TYPE_CHECKING:
    from ..state import WorldState

PRIORITY_ORDER = {"emergency": 0, "urgent": 1, "scheduled": 2}


def nearest_place_name(state: WorldState, lat: float, lon: float) -> str:
    best = min(state.places.values(), key=lambda p: haversine_km(lat, lon, p.lat, p.lon))
    km = haversine_km(lat, lon, best.lat, best.lon)
    return best.name if km < 0.3 else f"{km:.1f} km from {best.name}"


def _minutes(a, b) -> float:
    return round((a - b).total_seconds() / 60, 1)


def find_candidates(state: WorldState, trip_id: str, limit: int = 8) -> list[dict[str, Any]]:
    trip = state.trips.get(trip_id)
    if trip is None:
        raise ActionError(f"Unknown trip {trip_id}")
    if trip.status in DONE or trip.status == "onboard":
        raise ActionError(f"Trip {trip_id} is {trip.status}; it cannot be reassigned")

    urgent = trip.priority in ("emergency", "urgent")
    results = []
    for v in state.vehicles.values():
        ok, _ = can_serve(v, trip)
        if not ok:
            continue
        queue_len = len([t for t in v.queue if t != trip_id])
        options: set[tuple[int | None, bool]] = {(None, False)}  # end of queue
        if queue_len > 0:
            options.add((0, False))  # right after the current trip
        current = state.trips.get(v.current_trip_id) if v.current_trip_id else None
        if urgent and current and current.id != trip_id and current.status != "onboard":
            options.add((0, True))  # divert now, current trip goes back to the queue

        for position, interrupt in options:
            step = PlanStep(trip_id=trip_id, vehicle_id=v.id, position=position, interrupt_current=interrupt)
            sim, errors = simulate(state, Plan(steps=[step]))
            if errors:
                continue
            t = sim.trips[trip_id]
            k = kpis(sim)
            results.append(
                {
                    "step": step.model_dump(),
                    "vehicle_id": v.id,
                    "vehicle_type": v.type,
                    "vehicle_status": v.status,
                    "vehicle_near": nearest_place_name(state, v.lat, v.lon),
                    "insertion": "divert now (interrupts current trip)"
                    if interrupt
                    else ("end of queue" if position is None else "next, after current trip"),
                    "trip_eta_pickup": t.eta_pickup,
                    "trip_eta_dropoff": t.eta_dropoff,
                    "trip_delay_min": t.delay_min,
                    "pickup_in_min": _minutes(t.eta_pickup, state.sim_time) if t.eta_pickup else None,
                    "kpis_after": {
                        "late_trips": k["late_trips"],
                        "late_non_scheduled": k["late_non_scheduled"],
                        "total_delay_min": k["total_delay_min"],
                        "max_delay_min": k["max_delay_min"],
                        "unassigned": sum(k["unassigned"].values()),
                    },
                }
            )

    def score(c: dict[str, Any]):
        k = c["kpis_after"]
        if urgent:  # get the patient fastest, then protect other priority trips
            return (c["pickup_in_min"] or 0, k["late_non_scheduled"], k["total_delay_min"])
        # Routine trip: no new lateness first; then keep ambulances free for emergencies
        # unless the patient needs a stretcher; then the smallest delay.
        spends_ambulance = c["vehicle_type"] == "ambulance" and trip.needs != "stretcher"
        return (k["late_non_scheduled"], k["late_trips"], spends_ambulance, c["trip_delay_min"] or 0, k["total_delay_min"])

    results.sort(key=score)
    return results[:limit]


def greedy_plan(state: WorldState) -> tuple[Plan | None, list[str]]:
    """Engine-only fallback: give each unassigned trip its best candidate, most urgent first."""
    sim = state.clone_for_simulation()
    targets = sorted(
        (t for t in sim.trips.values() if t.status == "unassigned"),
        key=lambda t: (PRIORITY_ORDER[t.priority], t.due_by),
    )
    steps: list[PlanStep] = []
    unresolved: list[str] = []
    for trip in targets:
        candidates = find_candidates(sim, trip.id, limit=1)
        if not candidates:
            unresolved.append(trip.id)
            continue
        step = PlanStep(**candidates[0]["step"])
        assign_trip(sim, step.trip_id, step.vehicle_id, step.position, step.interrupt_current)
        project_all(sim)
        steps.append(step)
    return (Plan(steps=steps) if steps else None), unresolved
