"""Candidate vehicles for a trip, ranked by simulated outcome, and a greedy fallback plan.

Every candidate is evaluated by actually simulating the insertion, so the numbers
include knock-on delays to the vehicle's later trips.
"""
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from ..models import Plan, PlanStep, Trip, Vehicle, VehicleType
from ..routing import flies, haversine_km
from .actions import ActionError, assign_trip, can_serve, check_redirect
from .plans import simulate_steps, step_details
from .projection import DONE, PRIORITY_ORDER, kpis, over_capacity, project_all, route_trip_ids

if TYPE_CHECKING:
    from ..state import WorldState

PRIORITY_ORDER = {"emergency": 0, "urgent": 1, "scheduled": 2}
HELICOPTER_LONG_TRIP_KM = 30.0  # (legacy) the helicopter no longer takes scheduled trips at all, see can_serve
# The helicopter ranks first only if it reaches the patient at least this much sooner than the
# best road vehicle: in-city calls stay with the ambulances, remote ones fly. 0 = always the fastest.
HELICOPTER_MIN_GAIN_MIN = 10.0  # emergencies
HELICOPTER_MIN_GAIN_URGENT_MIN = 15.0  # urgent (non-emergency) trips: only when clearly faster (long distance)
# The engine offers an ambulance for a scheduled trip only if the patient is ready within this many
# minutes: an emergency unit is never tied up waiting for a routine pickup hours ahead.
AMBULANCE_ROUTINE_HORIZON_MIN = 30.0


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
    state: WorldState, trip_id: str, limit: int = 8, dropoff_id: str | None = None, all_positions: bool = False
) -> list[dict[str, Any]]:
    """dropoff_id: evaluate every candidate as if the trip were redirected to that hospital.
    all_positions: also try every place in each queue (not only next / at the end), e.g. for bookings."""
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
    free_ambulances = sum(1 for v in state.vehicles.values() if v.type == "ambulance" and is_free(state, v))
    soon = state.sim_time + timedelta(minutes=AMBULANCE_ROUTINE_HORIZON_MIN)
    results = []
    for v in state.vehicles.values():
        own = trip.vehicle_id == v.id
        if trip.status == "onboard" and not own:
            continue  # a patient on board can only be redirected, not moved to another vehicle
        ok, _ = can_serve(v, trip)
        if not ok and trip.status != "onboard":
            continue
        if v.type == "ambulance" and not urgent and not own and trip.pickup_after > soon:
            continue  # an ambulance helps out with routine work only when it is needed now, not hours ahead
        queue_len = len([t for t in v.queue if t != trip_id])
        options: set[tuple[int | None, bool]] = {(None, False)}  # end of queue (own vehicle + redirect: keep place)
        if queue_len > 0 and trip.status != "onboard":
            options.add((0, False))  # right after the current trip
            if all_positions:
                options.update((k, False) for k in range(1, queue_len))
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
                    # True if this uses the last ambulance still free for the next emergency
                    "takes_last_free_ambulance": v.type == "ambulance" and is_free(state, v) and free_ambulances <= 1,
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
            gain = HELICOPTER_MIN_GAIN_MIN if trip.priority == "emergency" else HELICOPTER_MIN_GAIN_URGENT_MIN
            reserve = gain if flies(c["vehicle_type"]) else 0.0
            return ((c["pickup_in_min"] or 0) + reserve, k["late_non_scheduled"], k["total_delay_min"])
        # Scheduled trip: no new lateness for emergency/urgent trips; never the last free ambulance
        # (kept for the next emergency); then no new lateness; then vans before ambulances
        # (ambulances only if no van can do it on time); then the smallest delay. The helicopter
        # never takes scheduled trips (can_serve).
        spends_heli = spends_helicopter(state, c["vehicle_type"], trip)
        spends_ambulance = c["vehicle_type"] == "ambulance"
        return (
            k["late_non_scheduled"],
            c["takes_last_free_ambulance"],
            k["late_trips"],
            spends_heli,
            spends_ambulance,
            c["trip_delay_min"] or 0,
            k["total_delay_min"],
        )

    results.sort(key=score)
    top = results[:limit]
    if redirect:  # always show the least disruptive option: the trip's own vehicle, keeping its place
        keep = next((c for c in results if c["insertion"] == "keeps its place"), None)
        if keep is not None and keep not in top:
            top.append(keep)
    return top


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
            score = (k["late_non_scheduled"], c["takes_last_free_ambulance"], k["total_delay_min"], k["max_delay_min"], k["late_trips"])
            if best is None or score < best[0]:
                best = (score, PlanStep(**c["step"]))
    return best[1] if best else None


LATE_REPAIR_MIN = 15.0  # the fallback tries to move trips predicted at least this late
LATE_REPAIR_MAX_MOVES = 5
LATE_REPAIR_MIN_GAIN = 10.0  # a move must cut the total delay by at least this many minutes


def _repair_late(sim: WorldState, steps: list[PlanStep]) -> None:
    """Move badly late trips (worst first) to a vehicle with slack, like the AI's process step 2.

    A move is kept only if it adds no late trip, makes the moved trip less late and cuts the total
    delay by LATE_REPAIR_MIN_GAIN minutes; it never takes the last free ambulance and never touches
    emergencies or loaded trips.
    """
    tried: set[str] = set()
    for _ in range(LATE_REPAIR_MAX_MOVES):
        late = sorted(
            (
                t
                for t in sim.trips.values()
                if t.status in ("assigned", "en_route_pickup")
                and t.priority != "emergency"
                and (t.delay_min or 0) >= LATE_REPAIR_MIN
                and t.id not in tried
            ),
            key=lambda t: -(t.delay_min or 0),
        )
        if not late:
            return
        trip = late[0]
        tried.add(trip.id)
        base = kpis(sim)
        for c in find_candidates(sim, trip.id, limit=50):
            k = c["kpis_after"]
            if (
                c["takes_last_free_ambulance"]
                or k["late_non_scheduled"] > base["late_non_scheduled"]
                or k["late_trips"] > base["late_trips"]
                or k["total_delay_min"] > base["total_delay_min"] - LATE_REPAIR_MIN_GAIN
                or (c["trip_delay_min"] or 0) >= (trip.delay_min or 0)  # the moved trip itself must gain
            ):
                continue
            step = PlanStep(**c["step"])
            assign_trip(sim, step.trip_id, step.vehicle_id, step.position, step.interrupt_current, step.dropoff_id)
            project_all(sim)
            steps.append(step)
            break


def greedy_plan(state: WorldState, fix_late: bool = True) -> tuple[Plan | None, list[str]]:
    """Engine-only fallback, most urgent trip first:
    - a patient that a hospital over capacity cannot admit (the least urgent incoming ones, see
      projection.over_capacity) is redirected with best_redirect;
    - every other unassigned trip gets its best candidate vehicle;
    - then (fix_late) badly late trips are moved where that clearly cuts the delay (_repair_late).
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
    if fix_late:
        _repair_late(sim, steps)
    return (Plan(steps=steps) if steps else None), unresolved
