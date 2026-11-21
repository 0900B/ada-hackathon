"""Forward projection: walk each vehicle's route and predict every trip's ETAs and delay.

This is the "cascade forecast": a delay early in a vehicle's day ripples into
every later trip, and project_all makes that visible after every tick.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from ..models import Alert, Severity, Trip, Vehicle
from ..roads import ROADS, key
from ..routing import travel_minutes, vehicle_leg_minutes

if TYPE_CHECKING:
    from ..state import WorldState

LOAD_MIN = 5.0
UNLOAD_MIN = 3.0
LATE_ALERT_MIN = 5.0
DONE = ("completed", "cancelled")
SEVERITY_ORDER: dict[Severity, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}
PRIORITY_ORDER = {"emergency": 0, "urgent": 1, "scheduled": 2}


@dataclass
class Leg:
    trip_id: str
    eta_pickup: datetime | None
    eta_dropoff: datetime
    delay_min: float


def _td(minutes: float) -> timedelta:
    return timedelta(minutes=minutes)


def route_trip_ids(v: Vehicle) -> list[str]:
    return ([v.current_trip_id] if v.current_trip_id else []) + list(v.queue)


def project_route(
    state: WorldState, v: Vehicle, trip_ids: list[str] | None = None, prefetch: bool = False
) -> list[Leg]:
    """Predict ETAs for the given trips (default: the vehicle's current route), in order.

    prefetch=True asks the road router for the geometry of each leg (real state only, never
    for what-if copies), so the legs vehicles will actually drive are on real roads.
    """
    ids = route_trip_ids(v) if trip_ids is None else trip_ids
    t = state.sim_time
    if v.busy_until and v.busy_until > t:
        t = v.busy_until
    lat, lon = v.lat, v.lon
    first = True  # the first leg starts from wherever the vehicle is, possibly mid-road

    def leg(blat: float, blon: float, emergency: bool) -> timedelta:
        nonlocal first, lat, lon
        if prefetch:
            if not first:
                ROADS.want_route(lat, lon, blat, blon)  # place -> place
            elif v.path_from is not None and v.path_to is not None and tuple(v.path_to) == key(blat, blon):
                ROADS.want_route(v.path_from[0], v.path_from[1], blat, blon)  # the leg it is driving
            elif v.path_to is None or v.path_progress >= 1.0:
                ROADS.want_route(lat, lon, blat, blon)  # parked at a place
            # else: mid-road towards another target; never request routes from moving positions
        minutes = (
            vehicle_leg_minutes(state, v, blat, blon, emergency)
            if first
            else travel_minutes(state, lat, lon, blat, blon, v.type, emergency)
        )
        first = False
        lat, lon = blat, blon
        return _td(minutes)

    legs: list[Leg] = []
    for tid in ids:
        trip = state.trips[tid]
        pickup, dropoff = state.places[trip.pickup_id], state.places[trip.dropoff_id]
        emergency = trip.priority == "emergency"
        if trip.status == "onboard" and trip.vehicle_id == v.id:
            eta_pickup = trip.eta_pickup  # already picked up
        else:
            t += leg(pickup.lat, pickup.lon, emergency)
            eta_pickup = t
            t = max(t, trip.pickup_after) + _td(LOAD_MIN)
        t += leg(dropoff.lat, dropoff.lon, emergency)
        delay = max(0.0, (t - trip.due_by).total_seconds() / 60)
        legs.append(Leg(tid, eta_pickup, t, round(delay, 1)))
        t += _td(UNLOAD_MIN)
    if prefetch and v.status != "out_of_service":
        base = state.places.get(v.base_id)
        if base:
            ROADS.want_route(lat, lon, base.lat, base.lon)  # the drive home after the last trip
    return legs


def project_all(state: WorldState) -> None:
    """Refresh ETAs/delays on every open trip, then recompute alerts."""
    real = not state.is_simulation
    if real:
        ROADS.want_matrix([(p.lat, p.lon) for p in state.places.values()])
    for trip in state.trips.values():
        if trip.status == "unassigned":
            trip.eta_pickup = trip.eta_dropoff = trip.delay_min = None
    for v in state.vehicles.values():
        if v.status == "out_of_service":
            continue
        for leg in project_route(state, v, prefetch=real):
            trip = state.trips[leg.trip_id]
            trip.eta_pickup, trip.eta_dropoff, trip.delay_min = leg.eta_pickup, leg.eta_dropoff, leg.delay_min
    state.alerts = compute_alerts(state)


# --- Hospital capacity ----------------------------------------------------------------
# A hospital's `capacity` is how many more patients it can admit (None = unlimited). Every open
# patient trip heading there needs one admission; equipment deliveries need none. When more
# patients are incoming than it can admit, the most urgent keep their place (then patients already
# on board, then the earliest due) and the rest are "overflow": they need another hospital.


def incoming_patients(state: WorldState, place_id: str, exclude_trip: str | None = None) -> list[Trip]:
    return [
        t
        for t in state.trips.values()
        if t.dropoff_id == place_id and t.kind == "patient" and t.status not in DONE and t.id != exclude_trip
    ]


def free_capacity(state: WorldState, place_id: str, exclude_trip: str | None = None) -> int | None:
    """Admissions left after every incoming patient (None = unlimited; negative = over capacity)."""
    place = state.places.get(place_id)
    if place is None or place.capacity is None:
        return None
    return place.capacity - len(incoming_patients(state, place_id, exclude_trip))


def over_capacity(state: WorldState) -> dict[str, list[Trip]]:
    """Hospitals with more incoming patients than they can admit -> the overflow trips, most urgent first."""
    out: dict[str, list[Trip]] = {}
    for p in state.places.values():
        if p.kind != "hospital" or p.capacity is None:
            continue
        incoming = sorted(
            incoming_patients(state, p.id),
            key=lambda t: (PRIORITY_ORDER[t.priority], t.status != "onboard", t.due_by),
        )
        if len(incoming) > p.capacity:
            out[p.id] = incoming[p.capacity :]
    return out


def compute_alerts(state: WorldState) -> list[Alert]:
    alerts: list[Alert] = []
    for trip in state.trips.values():
        if trip.status in DONE:
            continue
        if trip.status == "unassigned":
            sev: Severity = {"emergency": "critical", "urgent": "high"}.get(trip.priority, "medium")  # type: ignore[assignment]
            alerts.append(
                Alert(
                    id=f"trip_unassigned:{trip.id}",
                    kind="trip_unassigned",
                    severity=sev,
                    message=f"{trip.priority.capitalize()} trip {trip.id} ({trip.label}) has no vehicle",
                    trip_id=trip.id,
                )
            )
        elif (trip.delay_min or 0) >= LATE_ALERT_MIN:
            sev = "high" if trip.delay_min >= 15 or trip.priority != "scheduled" else "medium"  # type: ignore[operator]
            alerts.append(
                Alert(
                    id=f"trip_late:{trip.id}",
                    kind="trip_late",
                    severity=sev,
                    message=f"Trip {trip.id} ({trip.label}) predicted {trip.delay_min:.0f} min late",
                    trip_id=trip.id,
                    vehicle_id=trip.vehicle_id,
                )
            )
    for v in state.vehicles.values():
        if v.status == "out_of_service":
            alerts.append(
                Alert(
                    id=f"vehicle_down:{v.id}",
                    kind="vehicle_down",
                    severity="high",
                    message=f"{v.name} is out of service",
                    vehicle_id=v.id,
                )
            )
    for place_id, overflow in over_capacity(state).items():
        p = state.places[place_id]
        alerts.append(
            Alert(
                id=f"hospital_over_capacity:{place_id}",
                kind="hospital_over_capacity",
                severity="critical" if any(t.priority == "emergency" for t in overflow) else "high",
                message=(
                    f"{p.name} over capacity: {p.capacity + len(overflow)} patients incoming, can admit "
                    f"{p.capacity}; redirect {', '.join(t.id for t in overflow)}"
                ),
                trip_id=overflow[0].id,
            )
        )
    w = state.effective_weather
    snow_soon = any(h.snowfall_cm > 0 for h in state.weather_forecast[:3])
    if (w and (w.snowfall_cm > 0 or (w.precipitation_mm > 0 and w.temperature_c <= 0.5))) or snow_soon:
        alerts.append(
            Alert(
                id="weather_risk",
                kind="weather_risk",
                severity="medium",
                message="Snow or ice now or within 3 h: travel times are increased",
            )
        )
    for s in state.sources.values():
        if s.health == "down":
            alerts.append(
                Alert(
                    id=f"data_source_down:{s.name}",
                    kind="data_source_down",
                    severity="medium",
                    message=f"Data source '{s.name}' is down; using fallback values",
                )
            )
    alerts.sort(key=lambda a: SEVERITY_ORDER[a.severity])
    return alerts


def kpis(state: WorldState) -> dict[str, Any]:
    """Headline numbers used to compare plans ("before" vs "after")."""
    open_trips = [t for t in state.trips.values() if t.status not in DONE]
    late = [t for t in open_trips if (t.delay_min or 0) >= LATE_ALERT_MIN]
    unassigned = [t for t in open_trips if t.status == "unassigned"]
    return {
        "open_trips": len(open_trips),
        "late_trips": len(late),
        "late_non_scheduled": sum(1 for t in late if t.priority != "scheduled"),
        "total_delay_min": round(sum(t.delay_min or 0 for t in open_trips), 1),
        "max_delay_min": round(max((t.delay_min or 0 for t in open_trips), default=0), 1),
        "unassigned": {p: sum(1 for t in unassigned if t.priority == p) for p in ("emergency", "urgent", "scheduled")},
        "vehicles_in_service": sum(1 for v in state.vehicles.values() if v.status != "out_of_service"),
        "over_capacity": sum(len(trips) for trips in over_capacity(state).values()),  # patients without an admission
    }
