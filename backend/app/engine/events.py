"""Apply operator/injected events to the world and report which trips they affect."""
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from ..models import (
    BreakdownEvent,
    ClearIncidentEvent,
    DelayEvent,
    EventRecord,
    FogEvent,
    Incident,
    Place,
    RoadClosureEvent,
    Trip,
    UrgentRequestEvent,
    WeatherNow,
    WeatherOverrideEvent,
)
from ..routing import flies, travel_minutes
from .projection import DONE, LOAD_MIN, kpis, project_all, route_trip_ids

if TYPE_CHECKING:
    from ..models import OperatorEvent
    from ..state import WorldState

EMERGENCY_SLACK_MIN = 20  # target: at hospital within direct travel + this
URGENT_SLACK_MIN = 60


class EventError(ValueError):
    pass


def apply_event(state: WorldState, ev: OperatorEvent) -> EventRecord:
    project_all(state)  # fresh baseline, so feed updates since the last tick don't count as event effects
    before = {t.id: (t.status, t.vehicle_id, t.eta_dropoff) for t in state.trips.values()}
    kpis_before = kpis(state)
    created: list[str] = []

    summary = _handle(state, ev, created)
    project_all(state)

    affected: list[str] = []
    for t in state.trips.values():
        if t.id in created:
            affected.append(t.id)
            continue
        if t.id not in before or t.status in DONE:
            continue
        status, vehicle_id, eta = before[t.id]
        moved = eta and t.eta_dropoff and abs((t.eta_dropoff - eta).total_seconds()) >= 60
        if t.status != status or t.vehicle_id != vehicle_id or moved:
            affected.append(t.id)

    record = EventRecord(
        id=state.new_id("EV"),
        sim_time=state.sim_time,
        type=ev.type,
        payload=ev.model_dump(mode="json"),
        summary=summary,
        affected_trip_ids=affected,
        kpis_before=kpis_before,
        kpis_after=kpis(state),
    )
    state.events.append(record)
    state.bump()
    return record


def _vehicle(state: WorldState, vehicle_id: str):
    v = state.vehicles.get(vehicle_id)
    if v is None:
        raise EventError(f"Unknown vehicle {vehicle_id}")
    return v


def _handle(state: WorldState, ev: OperatorEvent, created: list[str]) -> str:
    if isinstance(ev, BreakdownEvent):
        v = _vehicle(state, ev.vehicle_id)
        if v.status == "out_of_service":
            raise EventError(f"{v.name} is already out of service")
        stranded = None
        for tid in ([v.current_trip_id] if v.current_trip_id else []) + v.queue:
            trip = state.trips[tid]
            if trip.status == "onboard":
                # Patient is inside the broken vehicle: they now need pickup at the breakdown site.
                site = Place(
                    id=state.new_id("site"),
                    name=f"Breakdown site of {v.name}",
                    kind="incident_site",
                    lat=v.lat,
                    lon=v.lon,
                )
                state.places[site.id] = site
                trip.pickup_id = site.id
                trip.pickup_after = state.sim_time
                if trip.priority == "scheduled":
                    trip.priority = "urgent"
                trip.note = f"Patient on board {v.name} at breakdown"
                stranded = trip.id
            trip.status = "unassigned"
            trip.vehicle_id = None
        v.current_trip_id, v.queue, v.busy_until = None, [], None
        v.path_from, v.path_to, v.on_road = None, None, False
        v.status = "out_of_service"
        extra = f"; patient of {stranded} stranded on board" if stranded else ""
        return f"{v.name} broke down{extra}" + (f" ({ev.note})" if ev.note else "")

    if isinstance(ev, DelayEvent):
        v = _vehicle(state, ev.vehicle_id)
        start = max(state.sim_time, v.busy_until or state.sim_time)
        v.busy_until = start + timedelta(minutes=ev.minutes)
        return f"{v.name} delayed by {ev.minutes:.0f} min" + (f" ({ev.note})" if ev.note else "")

    if isinstance(ev, RoadClosureEvent):
        inc = Incident(
            id=state.new_id("INC"),
            kind=ev.kind,
            description=ev.description,
            lat=ev.lat,
            lon=ev.lon,
            radius_m=ev.radius_m,
            created_at=state.sim_time,
        )
        state.incidents[inc.id] = inc
        return f"{ev.kind.replace('_', ' ').capitalize()}: {ev.description}"

    if isinstance(ev, ClearIncidentEvent):
        inc = state.incidents.get(ev.incident_id)
        if inc is None:
            if ev.incident_id in state.feed.incidents:
                raise EventError("Live incidents from TomTom/promet.si clear themselves when the feed does")
            raise EventError(f"Unknown incident {ev.incident_id}")
        inc.active = False
        return f"Incident {inc.id} cleared"

    if isinstance(ev, UrgentRequestEvent):
        if ev.pickup_id:
            pickup = state.places.get(ev.pickup_id)
            if pickup is None:
                raise EventError(f"Unknown place {ev.pickup_id}")
        elif ev.lat is not None and ev.lon is not None:
            pickup = Place(id=state.new_id("call"), name="Call location", kind="call_location", lat=ev.lat, lon=ev.lon)
            state.places[pickup.id] = pickup
        else:
            raise EventError("Give pickup_id, or lat and lon")
        dropoff = state.places.get(ev.dropoff_id)
        if dropoff is None:
            raise EventError(f"Unknown place {ev.dropoff_id}")
        direct = travel_minutes(state, pickup.lat, pickup.lon, dropoff.lat, dropoff.lon, "ambulance", True)
        slack = EMERGENCY_SLACK_MIN if ev.priority == "emergency" else URGENT_SLACK_MIN
        trip = Trip(
            id=f"TR-{len(state.trips) + 1:03d}",  # same format as seeded trips; trips are never deleted
            patient=f"P-{len(state.trips) + 100}",
            priority=ev.priority,
            needs=ev.needs,
            pickup_id=pickup.id,
            dropoff_id=dropoff.id,
            pickup_after=state.sim_time,
            due_by=state.sim_time + timedelta(minutes=direct + LOAD_MIN + slack),
            note=ev.note,
        )
        state.trips[trip.id] = trip
        created.append(trip.id)
        return f"New {ev.priority} request {trip.id}: {pickup.name} -> {dropoff.name}"

    if isinstance(ev, WeatherOverrideEvent):
        if not state.hypothetical:
            raise EventError("Live mode always uses real weather; use Simulation for hypothetical weather")
        if ev.clear:
            state.weather_override = None
            return "Weather override cleared; back to live weather"
        state.weather_override = WeatherNow(
            observed_at=state.sim_time,
            temperature_c=ev.temperature_c,
            precipitation_mm=ev.precipitation_mm,
            snowfall_cm=ev.snowfall_cm,
            wind_speed_kmh=ev.wind_speed_kmh,
            source="injected",
        )
        return f"Weather override: {ev.snowfall_cm} cm snow, {ev.temperature_c} °C"

    if isinstance(ev, FogEvent):
        return _ground_helicopters(state, ev)

    raise EventError(f"Unsupported event type {getattr(ev, 'type', '?')}")


def _ground_helicopters(state: WorldState, ev: FogEvent) -> str:
    """Fog: no helicopter may take off until it lifts (the simulator clears grounded_until).

    Trips not yet picked up go back to unassigned so road vehicles can be found for them. A
    helicopter with a patient on board finishes that flight, then flies home and waits.
    """
    helis = [v for v in state.vehicles.values() if flies(v.type)]
    if not helis:
        raise EventError("There is no helicopter to ground")
    until = state.sim_time + timedelta(minutes=ev.duration_min)
    released: list[str] = []
    finishing: list[str] = []
    for v in helis:
        v.grounded_until = max(v.grounded_until or until, until)
        for tid in route_trip_ids(v):
            trip = state.trips[tid]
            if trip.status == "onboard":
                finishing.append(f"{v.name} flies {tid} in first")
                continue
            trip.status, trip.vehicle_id = "unassigned", None
            released.append(tid)
        v.queue = []
        if v.current_trip_id and state.trips[v.current_trip_id].status != "onboard":
            v.current_trip_id = None  # the simulator now sends it back to base
    names = ", ".join(v.name for v in helis)
    summary = f"Fog (megla): {names} grounded for {ev.duration_min:.0f} min"
    if released:
        summary += f"; {len(released)} trip(s) released for road vehicles ({', '.join(released)})"
    if finishing:
        summary += f"; {', '.join(finishing)}"
    return summary + (f" ({ev.note})" if ev.note else "")
