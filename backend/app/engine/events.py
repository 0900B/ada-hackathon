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
    HospitalCapacityEvent,
    TaskRequestEvent,
    Incident,
    Place,
    PriorityChangeEvent,
    RoadClosureEvent,
    Trip,
    UrgentRequestEvent,
    WeatherNow,
    WeatherOverrideEvent,
)
from ..roads import ROADS, remaining_points
from ..routing import flies, leg_route, points_hit, travel_minutes
from .actions import EMERGENCY_UNITS, LJ, ActionError, assign_trip, can_serve, detach_trip
from .projection import (
    DONE,
    LOAD_MIN,
    PRIORITY_ORDER,
    incoming_patients,
    kpis,
    over_capacity,
    project_all,
    route_trip_ids,
)

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

    affected: list[str] = list(dict.fromkeys(created))  # the event's own trips first (e.g. the new call)
    for t in state.trips.values():
        if t.id in created:
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
                # The patient (or equipment) is inside the broken vehicle: another vehicle must
                # first collect it at the breakdown site, then deliver it.
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
                if trip.kind == "equipment":
                    # No one is waiting at the roadside, so the priority stays; the due-by still counts.
                    trip.note = f"Equipment ({trip.cargo}) stranded in {v.id}: collect at the breakdown site"
                else:
                    if trip.priority == "scheduled":
                        trip.priority = "urgent"
                    trip.note = f"Patient on board {v.name} at breakdown"
                stranded = trip
            trip.status = "unassigned"
            trip.vehicle_id = None
        v.current_trip_id, v.queue, v.busy_until = None, [], None
        v.path_from, v.path_to, v.on_road, v.path_avoid = None, None, False, None
        v.status = "out_of_service"
        extra = ""
        if stranded and stranded.kind == "equipment":
            extra = f"; equipment ({stranded.cargo}) stranded in {v.id}: {stranded.id} must be collected at the breakdown site"
        elif stranded:
            extra = f"; patient of {stranded.id} stranded on board"
            if stranded.priority == "emergency":  # an emergency patient can't wait for an analysis
                extra += dispatch_call(state, stranded)
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
        what = f"{ev.kind.replace('_', ' ').capitalize()}: {ev.description}"
        if inc.kind != "road_closure":
            return what
        crossing = [v.id for v in state.vehicles.values() if _drives_through(state, v, inc)]
        if not crossing:
            return what
        how = "rerouting around it" if ROADS.detours_available() else "slower until it clears (no detour service)"
        return what + f"; on the route of {', '.join(crossing)}: {how}"

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
            name = ev.place_name or "Call location"
            pickup = Place(id=state.new_id("call"), name=name, kind="call_location", lat=ev.lat, lon=ev.lon)
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
        return f"New {ev.priority} request {trip.id}: {pickup.name} -> {dropoff.name}" + dispatch_call(state, trip)

    if isinstance(ev, TaskRequestEvent):
        return _book_task(state, ev, created)

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

    if isinstance(ev, PriorityChangeEvent):
        return _priority_change(state, ev, created)

    if isinstance(ev, HospitalCapacityEvent):
        place = state.places.get(ev.place_id)
        if place is None:
            raise EventError(f"Unknown place {ev.place_id}")
        if place.kind != "hospital":
            raise EventError(f"{place.name} is not a hospital")
        place.capacity = ev.capacity
        note = f" ({ev.note})" if ev.note else ""
        if ev.capacity is None:
            return f"{place.name}: capacity limit lifted{note}"
        incoming = incoming_patients(state, place.id)
        over = len(incoming) - ev.capacity
        created.extend(t.id for t in over_capacity(state).get(place.id, []))  # reported as affected
        return (
            f"{place.name} can admit only {ev.capacity} more patient(s); {len(incoming)} incoming"
            + (f", {over} must be redirected" if over > 0 else "")
            + note
        )

    raise EventError(f"Unsupported event type {getattr(ev, 'type', '?')}")


def _hhmm(dt) -> str:
    return dt.astimezone(LJ).strftime("%H:%M") if dt else "?"


def dispatch_call(state: WorldState, trip: Trip) -> str:
    """Engine dispatch for a call that should not wait for an analysis: a new emergency or urgent
    call, or an emergency that lost its vehicle. Picks the unit that reaches the patient first.

    - Emergency units only (ambulances; the helicopter only when it is HELICOPTER_MIN_GAIN_MIN
      minutes faster, see find_candidates), free units first (idle or driving home, nothing queued).
    - An emergency with no free unit takes a busy ambulance: one driving to a less urgent pickup
      turns around; one with a patient on board finishes that job first. Never a van.
    - An urgent call with no free unit is queued on whichever vehicle (van or ambulance) reaches it
      first without diverting anyone.
    The AI analysis can still propose a better unit. Returns a clause for the event summary.
    """
    from .candidates import find_candidates  # local import: candidates imports this package's modules

    cands = find_candidates(state, trip.id, limit=100)  # emergency/urgent: ranked by arrival at the patient
    units = [c for c in cands if c["vehicle_type"] in EMERGENCY_UNITS]
    free = [c for c in units if c["vehicle_free"]]
    if free:
        pool = free
    elif trip.priority == "emergency":
        pool = units
    else:
        pool = [c for c in cands if not c["step"]["interrupt_current"]]
    if not pool:
        if trip.priority == "emergency":
            return "; no ambulance or helicopter can take it: request one from a neighbouring station"
        return "; no vehicle can take it yet: left for the dispatcher to plan"
    best = pool[0]
    step = best["step"]
    assign_trip(state, trip.id, step["vehicle_id"], step["position"], step["interrupt_current"])
    trip.dispatched_at = state.sim_time
    v = state.vehicles[step["vehicle_id"]]
    if flies(v.type):
        road = next((c for c in units if c["vehicle_type"] == "ambulance"), None)
        why = (
            f"helicopter, {road['pickup_in_min'] - best['pickup_in_min']:.0f} min sooner than {road['vehicle_id']} by road"
            if road
            else "helicopter; no ambulance can take it"
        )
    elif best["vehicle_free"]:
        why = "nearest free ambulance" if v.type == "ambulance" else "nearest free unit"
    else:
        why = f"no ambulance free; {best['insertion']}"
    who = "the patient" if trip.kind == "patient" else "the pickup"
    return (
        f"; dispatched {v.id} ({why}): at {who} {_hhmm(best['trip_eta_pickup'])} (in {best['pickup_in_min']:.0f} min), "
        f"at {state.places[trip.dropoff_id].name} {_hhmm(best['trip_eta_dropoff'])}"
    )


def _drives_through(state: WorldState, v, inc: Incident) -> bool:
    """True if the rest of the leg v is driving passes through the incident."""
    if v.status == "out_of_service" or flies(v.type):
        return False
    route = leg_route(state, v)
    return route is not None and bool(points_hit(remaining_points(route, v.path_progress), [inc]))


BOOKING_SLACK_MIN = 30  # default deadline: ready + direct travel + loading + this


def _book_task(state: WorldState, ev: TaskRequestEvent, created: list[str]) -> str:
    """Create the booked trip and place it into the plan where the engine's simulation says it fits best."""
    from .candidates import find_candidates  # local import: candidates imports this package's modules

    pickup, dropoff = state.places.get(ev.pickup_id), state.places.get(ev.dropoff_id)
    if pickup is None or dropoff is None:
        raise EventError(f"Unknown place {ev.pickup_id if pickup is None else ev.dropoff_id}")
    if pickup.id == dropoff.id:
        raise EventError("Pickup and drop-off are the same place")
    equipment = ev.kind == "equipment" or ev.needs == "equipment"
    ready = state.sim_time + timedelta(minutes=ev.ready_in_min)
    direct = travel_minutes(state, pickup.lat, pickup.lon, dropoff.lat, dropoff.lon, "transport")  # bookings go by van
    due = (
        state.sim_time + timedelta(minutes=ev.due_in_min)
        if ev.due_in_min is not None
        else ready + timedelta(minutes=direct + LOAD_MIN + BOOKING_SLACK_MIN)
    )
    if due <= ready:
        raise EventError("The deadline must be after the ready time")
    trip = Trip(
        id=f"TR-{len(state.trips) + 1:03d}",
        kind="equipment" if equipment else "patient",
        patient=None if equipment else (ev.label or f"P-{len(state.trips) + 100}"),
        cargo=(ev.label or "equipment") if equipment else None,
        priority=ev.priority,
        needs="equipment" if equipment else ev.needs,
        pickup_id=pickup.id,
        dropoff_id=dropoff.id,
        pickup_after=ready.replace(microsecond=0),
        due_by=due.replace(microsecond=0),
        note=ev.note,
    )
    state.trips[trip.id] = trip
    created.append(trip.id)
    what = f"Booked {trip.id} ({trip.label}, {trip.priority}): {pickup.name} -> {dropoff.name}"
    if not ev.auto_assign:
        return what + "; waiting for the dispatcher"
    late_now = kpis(state)["late_trips"]
    # A booking never diverts a vehicle from the trip it is on, never flies, and fits without
    # making any trip late. Vans first; an ambulance only if no van fits, only a free one (never
    # queued behind an emergency) and never the last free one.
    fits = [
        c
        for c in find_candidates(state, trip.id, limit=200, all_positions=True)
        if not c["step"]["interrupt_current"]
        and not flies(c["vehicle_type"])
        and c["kpis_after"]["late_trips"] <= late_now
        and (c["trip_delay_min"] or 0) <= 0
    ]
    vans = [c for c in fits if c["vehicle_type"] == "transport"]
    ambulances = [
        c for c in fits if c["vehicle_type"] == "ambulance" and c["vehicle_free"] and not c["takes_last_free_ambulance"]
    ]
    best = (vans or ambulances or [None])[0]
    if best is None:
        return what + "; no vehicle can take it without a late trip, so it is left for the AI to replan"
    step = best["step"]
    assign_trip(state, trip.id, step["vehicle_id"], step["position"], step["interrupt_current"])
    eta = best["trip_eta_dropoff"].astimezone(LJ).strftime("%H:%M") if best["trip_eta_dropoff"] else "?"
    return what + f"; placed on {step['vehicle_id']} ({best['insertion']}), arrives {eta}"


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
        for tid in released:  # helicopter jobs are emergency/urgent calls: send a road unit now
            summary += f"; {tid}" + dispatch_call(state, state.trips[tid]).replace(";", ":", 1)
    if finishing:
        summary += f"; {', '.join(finishing)}"
    return summary + (f" ({ev.note})" if ev.note else "")


def _priority_change(state: WorldState, ev: PriorityChangeEvent, affected: list[str]) -> str:
    """Change a trip's priority.

    - Raised to emergency: the patient must be collected now (pickup_after = now) and due-by becomes
      at most now + direct ambulance time + loading + EMERGENCY_SLACK_MIN (the rule for a new emergency).
    - Raised to urgent: due-by becomes at most ready time + direct time + loading + URGENT_SLACK_MIN.
    - With the patient on board, the deadline counts from the vehicle's position instead.
    - Deadlines are only ever tightened; lowering a priority keeps the current due-by.
    - If the assigned vehicle can no longer serve the trip (a van cannot take an emergency), the trip
      is released (unassigned) so it gets replanned. Trips on board keep their vehicle.
    """
    trip = state.trips.get(ev.trip_id)
    if trip is None:
        raise EventError(f"Unknown trip {ev.trip_id}")
    if trip.status in DONE:
        raise EventError(f"Trip {trip.id} is {trip.status}")
    old = trip.priority
    if ev.priority == old:
        raise EventError(f"Trip {trip.id} is already {old}")
    trip.priority = ev.priority
    affected.append(trip.id)
    parts = [f"{trip.id} ({trip.label}) priority {old} -> {ev.priority}"]

    v = state.vehicles.get(trip.vehicle_id) if trip.vehicle_id else None
    if PRIORITY_ORDER[ev.priority] < PRIORITY_ORDER[old]:  # raised
        dropoff = state.places[trip.dropoff_id]
        slack = EMERGENCY_SLACK_MIN if ev.priority == "emergency" else URGENT_SLACK_MIN
        if trip.status == "onboard" and v is not None:
            start = state.sim_time
            direct = travel_minutes(state, v.lat, v.lon, dropoff.lat, dropoff.lon, v.type, True)
        else:
            if ev.priority == "emergency":
                trip.pickup_after = min(trip.pickup_after, state.sim_time)
            start = max(state.sim_time, trip.pickup_after)
            pickup = state.places[trip.pickup_id]
            direct = travel_minutes(state, pickup.lat, pickup.lon, dropoff.lat, dropoff.lon, "ambulance", True) + LOAD_MIN
        target = start + timedelta(minutes=direct + slack)
        if target < trip.due_by:
            earlier = (trip.due_by - target).total_seconds() / 60
            trip.due_by = target.replace(microsecond=0)
            parts.append(f"due-by {earlier:.0f} min earlier")

    if v is not None and trip.status == "onboard":
        parts.append(f"stays on {v.id} (on board)")
    elif v is not None:
        ok, why = can_serve(v, trip)
        if not ok:
            detach_trip(state, trip)
            trip.status = "unassigned"
            parts.append(f"released from {v.id} ({why})")
        elif ev.priority == "emergency" and route_trip_ids(v)[0] != trip.id:
            try:
                assign_trip(state, trip.id, v.id)  # an emergency goes first (the vehicle turns around if needed)
                route = route_trip_ids(v)
                parts.append(f"moved to the front of {v.id}'s route" if route[0] == trip.id else f"next on {v.id}, after {route[0]}")
            except ActionError as e:
                parts.append(f"stays #{route_trip_ids(v).index(trip.id) + 1} on {v.id} ({e})")
    if trip.status == "unassigned" and trip.priority == "emergency":
        parts.append(dispatch_call(state, trip).removeprefix("; "))  # an emergency can't wait for an analysis
    return "; ".join(parts) + (f" ({ev.note})" if ev.note else "")
