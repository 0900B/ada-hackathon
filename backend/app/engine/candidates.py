"""Candidate vehicles for a trip, ranked by simulated outcome, and a greedy fallback plan.

Every candidate is evaluated by actually simulating the insertion, so the numbers
include knock-on delays to the vehicle's later trips.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..models import Plan, PlanStep, Trip, Vehicle, VehicleType
from ..routing import flies, haversine_km
from .actions import ActionError, assign_trip, can_serve, check_redirect
from .plans import simulate_steps, step_details
from .projection import DONE, PRIORITY_ORDER, kpis, over_capacity, project_all, route_trip_ids

if TYPE_CHECKING:
    from ..state import WorldState

PRIORITY_ORDER = {"emergency": 0, "urgent": 1, "scheduled": 2}
HELICOPTER_LONG_TRIP_KM = 30.0  # scheduled trips at least this long (straight line) may fly
# Urgent trips: the helicopter ranks first only if it reaches the patient at least this much
# sooner than the best road vehicle (in-city calls stay with ambulances). 0 = always the fastest.
HELICOPTER_MIN_GAIN_MIN = 5.0


def spends_helicopter(state: WorldState, vehicle_type: VehicleType, trip: Trip) -> bool:
    """True if flying this trip would spend the helicopter on routine work a road vehicle should do.

    The helicopter is kept for emergencies, urgent trips and long trips.
    """
    if not flies(vehicle_type) or trip.priority != "scheduled":
        return False
    a, b = state.places[trip.pickup_id], state.places[trip.dropoff_id]
    return haversine_km(a.lat, a.lon, b.lat, b.lon) < HELICOPTER_LONG_TRIP_KM


def is_free(state: WorldState, v: Vehicle) -> bool:
    """Available right now: in service, not grounded, no job and nothing queued (idle or driving home)."""
    return (
        v.status in ("idle", "returning")
        and v.current_trip_id is None
        and not v.queue
        and v.grounded_until is None
    )


def nearest_place_name(state: WorldState, lat: float, lon: float) -> str:
    best = min(state.places.values(), key=lambda p: haversine_km(lat, lon, p.lat, p.lon))
    km = haversine_km(lat, lon, best.lat, best.lon)
    return best.name if km < 0.3 else f"{km:.1f} km from {best.name}"


def _minutes(a, b) -> float:
    return round((a - b).total_seconds() / 60, 1)


def find_candidates(
    state: WorldState, trip_id: str, limit: int = 8, dropoff_id: str | None = None
) -> list[dict[str, Any]]:
    """dropoff_id: evaluate every candidate as if the trip were redirected to that hospital."""
    trip = state.trips.get(trip_id)
    if trip is None:
        raise ActionError(f"Unknown trip {trip_id}")
    redirect = dropoff_id is not None and dropoff_id != trip.dropoff_id
    if trip.status in DONE or (trip.status == "onboard" and not redirect):
        raise ActionError(f"Trip {trip_id} is {trip.status}; it cannot be reassigned")
    if redirect:
        assert dropoff_id is not None
        check_redirect(state, trip, dropoff_id)

    urgent = trip.priority in ("emergency", "urgent")
    results = []
    for v in state.vehicles.values():
        own = trip.vehicle_id == v.id
        if trip.status == "onboard" and not own:
            continue  # a patient on board can only be redirected, not moved to another vehicle
        ok, _ = can_serve(v, trip)
        if not ok and trip.status != "onboard":
            continue
        queue_len = len([t for t in v.queue if t != trip_id])
        options: set[tuple[int | None, bool]] = {(None, False)}  # end of queue (own vehicle + redirect: keep place)
        if queue_len > 0 and trip.status != "onboard":
            options.add((0, False))  # right after the current trip
        current = state.trips.get(v.current_trip_id) if v.current_trip_id else None
        if (
            urgent
            and current
            and current.id != trip_id
            and current.status != "onboard"
            and trip.status != "onboard"
            and PRIORITY_ORDER[trip.priority] < PRIORITY_ORDER[current.priority]
        ):
            options.add((0, True))  # divert now (only for a more urgent trip), current trip goes back to the queue

        seen: set[tuple] = set()
        for position, interrupt in sorted(options, key=lambda o: (o[0] is not None, o[1])):  # least change first
            step = PlanStep(
                trip_id=trip_id, vehicle_id=v.id, position=position, interrupt_current=interrupt, dropoff_id=dropoff_id
            )
            sim, errors, applied = simulate_steps(state, Plan(steps=[step]))
            if errors:
                continue
            # The engine may normalise a step (an emergency always goes first): keep each real outcome once.
            step = applied[0].model_copy(update={"before_trip_id": None})
            outcome = (step.interrupt_current, tuple(route_trip_ids(sim.vehicles[v.id])))
            if outcome in seen:
                continue
            seen.add(outcome)
            t = sim.trips[trip_id]
            k = kpis(sim)
            details = step_details(state, sim, applied)
            results.append(
                {
                    "step": step.model_dump(exclude={"before_trip_id"}),
                    "vehicle_id": v.id,
                    "vehicle_type": v.type,
                    "vehicle_status": v.status,
                    "vehicle_free": is_free(state, v),
                    "vehicle_near": nearest_place_name(state, v.lat, v.lon),
                    "insertion": ("keeps its place" if own and redirect and step.position is None else details[0]["when"])
                    if details
                    else "end of queue",
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
            reserve = HELICOPTER_MIN_GAIN_MIN if flies(c["vehicle_type"]) else 0.0
            return ((c["pickup_in_min"] or 0) + reserve, k["late_non_scheduled"], k["total_delay_min"])
        # Routine trip: no new lateness first; then keep the helicopter free unless only it avoids
        # lateness; then keep ambulances free for emergencies unless the patient needs a
        # stretcher; then the smallest delay.
        spends_heli = spends_helicopter(state, c["vehicle_type"], trip)
        spends_ambulance = c["vehicle_type"] == "ambulance" and trip.needs != "stretcher"
        return (
            k["late_non_scheduled"],
            k["late_trips"],
            spends_heli,
            spends_ambulance,
            c["trip_delay_min"] or 0,
            k["total_delay_min"],
        )

    results.sort(key=score)
    return results[:limit]


def best_redirect(state: WorldState, trip: Trip) -> PlanStep | None:
    """For a patient a full hospital cannot admit: try every general hospital with free capacity, each
    with the trip's best vehicle for it (find_candidates: its own vehicle keeping its place, or another
    vehicle with slack, since a distant hospital can make a busy vehicle's later trips late). Pick the
    option with the fewest late priority trips, then the least total and worst delay: a redirect is
    usually late anyway, so counting late trips first would park the patient at the end of a long queue.
    None if no hospital can take the patient."""
    best: tuple[tuple, PlanStep] | None = None
    for p in state.places.values():
        if p.id == trip.dropoff_id:
            continue
        try:
            check_redirect(state, trip, p.id)
        except ActionError:
            continue  # not a general hospital, or full
        for c in find_candidates(state, trip.id, limit=50, dropoff_id=p.id):
            k = c["kpis_after"]
            score = (k["late_non_scheduled"], k["total_delay_min"], k["max_delay_min"], k["late_trips"])
            if best is None or score < best[0]:
                best = (score, PlanStep(**c["step"]))
    return best[1] if best else None


def greedy_plan(state: WorldState) -> tuple[Plan | None, list[str]]:
    """Engine-only fallback, most urgent trip first:
    - a patient that a hospital over capacity cannot admit (the least urgent incoming ones, see
      projection.over_capacity) is redirected with best_redirect;
    - every other unassigned trip gets its best candidate vehicle.
    Returns the plan and the trips no vehicle can take. A patient with nowhere to be redirected
    keeps its destination; the over-capacity alert stays up for the operator.
    """
    sim = state.clone_for_simulation()
    overflow = {t.id for trips in over_capacity(sim).values() for t in trips}
    targets = sorted(
        (t for t in sim.trips.values() if t.status == "unassigned" or t.id in overflow),
        key=lambda t: (PRIORITY_ORDER[t.priority], t.due_by),
    )
    steps: list[PlanStep] = []
    unresolved: list[str] = []
    for trip in targets:
        step = best_redirect(sim, trip) if trip.id in overflow else None
        if step is None and trip.status == "unassigned":
            candidates = find_candidates(sim, trip.id, limit=1)
            if not candidates:
                unresolved.append(trip.id)
                continue
            step = PlanStep(**candidates[0]["step"])
        if step is None:
            continue
        assign_trip(sim, step.trip_id, step.vehicle_id, step.position, step.interrupt_current, step.dropoff_id)
        project_all(sim)
        steps.append(step)
    return (Plan(steps=steps) if steps else None), unresolved
