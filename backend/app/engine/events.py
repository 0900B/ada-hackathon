"""Apply operator/injected events to the world and report which trips they affect."""
from __future__ import annotations

import time
from datetime import timedelta
from typing import TYPE_CHECKING

from ..models import (
    BreakdownEvent,
    CallRecord,
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
from . import timeline, units
from .actions import LJ, ActionError, assign_trip, can_serve, detach_trip, level
from .doctors import release as release_doctor, send_doctor
from .service_times import on_scene_for, on_scene_min
from .severity import DEFAULT_SEVERITY, DOCTOR_TARGET_MIN, SEVERITY_PRIORITY, SEVERITY_RANK, call_label, grade, severity_for
from .projection import (
    DONE,
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


def apply_event(
    state: WorldState, ev: OperatorEvent, call: CallRecord | None = None, reported_by: str = "dispatcher"
) -> EventRecord:
    """Apply one event. call: the 112 call or hospital request behind a new urgent_request or
    task_request (app/intake.py); reported_by: who reported the event, for the call timeline
    (dispatcher, crew). Every change to a trip is logged on its timeline (engine/timeline.py)."""
    project_all(state)  # fresh baseline, so feed updates since the last tick don't count as event effects
    before = {t.id: (t.status, t.vehicle_id, t.eta_dropoff) for t in state.trips.values()}
    kpis_before = kpis(state)
    created: list[str] = []
    tracker = timeline.Tracker(state)
    graded = {t.id: (t.severity, t.condition_label) for t in state.trips.values() if t.call is not None}

    t0 = time.perf_counter()
    summary = _handle(state, ev, created, call)
    project_all(state)
    tracker.detail = timeline.engine_detail(time.perf_counter() - t0)  # "rules engine, 0.1 s"
    _log_event(state, ev, summary, created, tracker, graded, reported_by)

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


def is_112(trip: Trip) -> bool:
    """A trip behind a 112 call: the engine follows it up by itself (re-dispatch when its unit drops
    out, a faster free unit, a doctor car; engine/followup.py). Scenario jobs and bookings have none."""
    return trip.call is not None and trip.call.kind == "112"


def _log_event(
    state: WorldState, ev: OperatorEvent, summary: str, created: list[str], tracker: timeline.Tracker,
    graded: dict[str, tuple], reported_by: str,
) -> None:
    """The event on the timelines of the trips it touched (real world only)."""
    if state.is_simulation:
        return
    for tid in created:
        trip = state.trips.get(tid)
        if trip is None or trip.timeline:
            continue
        c = trip.call
        if c is None:
            timeline.log(state, trip, "received", reported_by, summary.split("; ")[0])
            continue
        words = c.text_en or c.text_sl
        if c.kind == "112":
            text = f"Call {c.call_id} received" + (f' from {c.caller_name}' if c.caller_name else "") + (f': "{words}"' if words else "")
        else:
            text = f"Request {c.call_id}" + (f" from {c.caller_name}" if c.caller_name else "") + (f': "{words}"' if words else "")
        timeline.log(state, trip, "received", "caller", text, at=c.received_at,
                     detail="112 call" if c.kind == "112" else "hospital request")
        if c.triage is not None:
            timeline.log(state, trip, "triaged", c.triage.by, triage_text(c.triage), at=c.triage.at, detail=triage_detail(c.triage))
    tracker.log_changes("engine", summary, created, detail=tracker.detail)
    if isinstance(ev, DelayEvent):
        v = state.vehicles.get(ev.vehicle_id)
        for tid in route_trip_ids(v) if v else []:
            t = state.trips[tid]
            if t.status == "onboard":
                when = f": at {state.places[t.dropoff_id].name} {timeline.hhmm(t.eta_dropoff)}"
            else:
                when = f": at {'the patient' if t.kind == 'patient' else 'the pickup'} {timeline.hhmm(t.eta_pickup)}" if t.eta_pickup else ""
            timeline.log(state, t, "delayed", reported_by, f"{ev.vehicle_id} delayed {ev.minutes:.0f} min"
                         + (f" ({ev.note})" if ev.note else "") + when, ev.vehicle_id, detail=f"{reported_by} report")
    elif isinstance(ev, RoadClosureEvent) and ev.kind == "road_closure":
        inc = next(reversed(state.incidents.values()), None)
        for v in state.vehicles.values():
            if inc is None or not v.current_trip_id or not crosses(state, v, inc):
                continue
            trip = state.trips.get(v.current_trip_id)
            if ROADS.detours_available():
                timeline.log(state, trip, "rerouted", "engine", f"{v.id}: {ev.description} ahead, rerouting around it", v.id)
            else:
                timeline.log(state, trip, "delayed", "engine", f"{v.id}: {ev.description} on the route, slower until it clears", v.id)
    elif isinstance(ev, FogEvent):
        for v in state.vehicles.values():
            trip = state.trips.get(v.current_trip_id) if flies(v.type) and v.current_trip_id else None
            if trip is not None and trip.status == "onboard":
                timeline.log(state, trip, "note", reported_by, f"Fog: {v.id} flies the patient in, then stays on the ground", v.id)
    elif isinstance(ev, PriorityChangeEvent):
        trip = state.trips.get(ev.trip_id)
        if trip is not None:
            old = graded.get(trip.id)
            if trip.call is not None and trip.call.triage is not None and old and old != (trip.severity, trip.condition_label):
                from ..agent.triage import regrade  # local import: the triage module imports the agent package

                regrade(state, trip, f"{old[0]} → {trip.severity}")
                timeline.log(state, trip, "triaged", "dispatcher", triage_text(trip.call.triage))
            else:
                timeline.log(state, trip, "note", reported_by, summary.split("; ")[0], trip.vehicle_id)
    elif isinstance(ev, HospitalCapacityEvent):
        place = state.places.get(ev.place_id)
        for tid in created:
            if (t := state.trips.get(tid)) is not None and place is not None:
                timeline.log(state, t, "note", reported_by, f"{place.name} can admit only {ev.capacity} more patient(s): "
                             "this patient may need another hospital", t.vehicle_id)


def triage_detail(tr) -> str:
    """The triage entry's source: "Claude, 2.1 s", "keyword rules, 0.0 s", "dispatcher re-grade"."""
    what = {"ai": "Claude", "rules": "keyword rules", "dispatcher": "dispatcher re-grade"}.get(tr.by, tr.by)
    return f"{what}, {tr.took_s:.1f} s" if tr.took_s is not None and tr.by != "dispatcher" else what


def triage_text(tr) -> str:
    """'Critical, doctor needed — Cardiac arrest: about 6% survival lost ...' for the timeline."""
    from .severity import MODIFIER_SHORT

    head = tr.severity.capitalize() + (", doctor needed" if tr.needs_doctor else "")
    if tr.reason_en:
        return f"{head} — {tr.reason_en}"
    mods = ", ".join(MODIFIER_SHORT.get(m, m.replace("_", " ")) for m in tr.modifiers)
    return f"{head} — " + ", ".join(filter(None, [tr.condition_label, mods])) if tr.condition_label or mods else head


def crosses(state: WorldState, v, inc: Incident) -> bool:
    """Does the rest of the leg v is driving (its road route, else the straight line to its target)
    pass through the incident?"""
    if v.status == "out_of_service" or flies(v.type):
        return False
    if _drives_through(state, v, inc):
        return True
    if leg_route(state, v) is not None:
        return False
    target = tuple(v.path_to) if v.path_to is not None else _target(state, v)
    if target is None:
        return False
    return bool(points_hit([(v.lat, v.lon), target], [inc]))


def _target(state: WorldState, v) -> tuple[float, float] | None:
    trip = state.trips.get(v.current_trip_id) if v.current_trip_id else None
    if trip is None and v.queue:
        trip = state.trips.get(v.queue[0])
    if trip is None:
        return None
    p = state.places[trip.dropoff_id if trip.status == "onboard" else trip.pickup_id]
    return (p.lat, p.lon)


def _handle(state: WorldState, ev: OperatorEvent, created: list[str], call: CallRecord | None = None) -> str:
    if isinstance(ev, BreakdownEvent):
        v = _vehicle(state, ev.vehicle_id)
        if v.status == "out_of_service":
            raise EventError(f"{v.name} is already out of service")
        if v.type == "doctor":  # the call keeps its ambulance; it needs another doctor
            supported = state.trips.get(v.current_trip_id) if v.current_trip_id else None
            v.current_trip_id, v.queue, v.busy_until, v.status = None, [], None, "out_of_service"
            v.path_from, v.path_to, v.on_road, v.path_avoid = None, None, False, None
            extra = ""
            if supported is not None and supported.doctor_vehicle_id == v.id:
                supported.doctor_vehicle_id = supported.doctor_eta = None
                created.append(supported.id)
                extra = f"; {supported.id} needs another doctor" + (send_doctor(state, supported) or ": none needed")
            return f"{v.name} broke down{extra}" + (f" ({ev.note})" if ev.note else "")
        stranded = None
        released: list[Trip] = []
        for tid in ([v.current_trip_id] if v.current_trip_id else []) + v.queue:
            trip = state.trips[tid]
            released.append(trip)
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
                        trip.priority, trip.severity = "urgent", "urgent"  # a patient waiting at the roadside
                        grade(state, trip)
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
                units.amend(state, stranded, stranded.vehicle_id, f"replaces {v.id} (broke down, patient on board)")
        # 112 calls are re-dispatched at once (highest level first). Scenario jobs and bookings (no
        # call record) and hospital requests stay for the dispatcher/AI, as before.
        for trip in sorted(released, key=level):
            if trip is stranded and stranded.priority == "emergency":
                continue  # already dispatched above
            if is_112(trip) and trip.status == "unassigned":
                extra += f"; {trip.id}" + dispatch_call(state, trip).replace(";", ":", 1)
                units.amend(state, trip, trip.vehicle_id, f"replaces {v.id} (out of service)")
        return f"{v.name} broke down{extra}" + (f" ({ev.note})" if ev.note else "")

    if isinstance(ev, DelayEvent):
        v = _vehicle(state, ev.vehicle_id)
        start = max(state.sim_time, v.busy_until or state.sim_time)
        v.busy_until = start + timedelta(minutes=ev.minutes)
        v.busy_reason = "delay"
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
        crossing = [v.id for v in state.vehicles.values() if crosses(state, v, inc)]
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
            due_by=state.sim_time
            + timedelta(minutes=direct + on_scene_for("patient", severity_for(ev.priority, ev.severity, ev.condition), ev.condition) + slack),
            note=ev.note,
            severity=ev.severity,
            condition=ev.condition,
            modifiers=list(ev.modifiers),
        )
        grade(state, trip)  # level, label and response target (critical: 8 min in the city, 15 outside)
        if ev.needs_doctor and trip.kind == "patient" and trip.severity in ("critical", "serious"):
            trip.needs_doctor, trip.doctor_target_min = True, DOCTOR_TARGET_MIN  # asked for by the call-taker/triage
        state.trips[trip.id] = trip
        created.append(trip.id)
        _attach_call(trip, call)
        label = call_label(trip)  # e.g. "Cardiac arrest, child"
        what = f" ({label})" if label else ""
        return f"New {trip.severity} call {trip.id}{what}: {pickup.name} → {dropoff.name}" + dispatch_call(state, trip)

    if isinstance(ev, TaskRequestEvent):
        text = _book_task(state, ev, created)
        if call is not None and created:
            _attach_call(state.trips[created[-1]], call)
        return text

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


def _attach_call(trip: Trip, call: CallRecord | None) -> None:
    """The call record joins its trip; its triage then shows the trip's final grading."""
    if call is None:
        return
    trip.call = call
    from ..agent.triage import sync_triage  # local import: the triage module imports the agent package

    sync_triage(trip)


def dispatch_call(state: WorldState, trip: Trip) -> str:
    """Engine dispatch of a call that should not wait for an analysis (a new emergency or urgent
    call, or an emergency that lost its vehicle): see engine/dispatch.py for the decision rules.
    Returns a clause for the event summary."""
    from .dispatch import dispatch_call as decide_and_dispatch  # local import: dispatch imports candidates

    return decide_and_dispatch(state, trip)


def _drives_through(state: WorldState, v, inc: Incident) -> bool:
    """True if the rest of the leg v is driving passes through the incident."""
    if v.status == "out_of_service" or flies(v.type):
        return False
    route = leg_route(state, v)
    return route is not None and bool(points_hit(remaining_points(route, v.path_progress), [inc]))


BOOKING_SLACK_MIN = 30  # default deadline: ready + direct travel + loading + this
BOOKING_MAX_PUSH_MIN = 10  # a booking may push other booked patients' arrival back by at most this


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
        else ready + timedelta(minutes=direct + on_scene_for("equipment" if equipment else "patient", "urgent", None, "transport") + BOOKING_SLACK_MIN)
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
        severity=ev.severity,
        condition=ev.condition or ("equipment" if equipment else None),
        modifiers=list(ev.modifiers),
    )
    grade(state, trip)
    state.trips[trip.id] = trip
    created.append(trip.id)
    what = f"Booked {trip.id} ({trip.label}, {trip.priority}): {pickup.name} → {dropoff.name}"
    if not ev.auto_assign:
        return what + "; waiting for the dispatcher"
    late_now = kpis(state)["late_trips"]
    # A booking never diverts a vehicle from the trip it is on, never flies, fits without making
    # any trip late and pushes no booked patient back by more than BOOKING_MAX_PUSH_MIN. Vans first;
    # an ambulance only if no van fits, only a free one and never the last free one.
    usable = [  # never diverts a vehicle, never flies; an ambulance only if free and not the last free one
        c
        for c in find_candidates(state, trip.id, limit=200, all_positions=True)
        if not c["step"]["interrupt_current"]
        and not flies(c["vehicle_type"])
        and (c["vehicle_type"] != "ambulance" or (c["vehicle_free"] and not c["takes_last_free_ambulance"]))
        and not (c["vehicle_type"] == "ambulance" and c.get("vehicle_origin") == "private")  # contracted ambulances: calls
    ]
    fits = [
        c
        for c in usable
        if c["kpis_after"]["late_trips"] <= late_now
        and (c["trip_delay_min"] or 0) <= 0
        and c["pushes_others_min"] <= BOOKING_MAX_PUSH_MIN
    ]
    # Surge capacity in the fleet: private vans first (stable sort keeps the simulated order otherwise).
    vans = sorted((c for c in fits if c["vehicle_type"] == "transport"), key=lambda c: c.get("vehicle_origin") != "private")
    ambulances = [c for c in fits if c["vehicle_type"] == "ambulance"]
    best = (vans or ambulances or [None])[0]
    late = ""
    if best is None and ev.if_late == "soonest" and usable:
        # Must be served (a live call): the vehicle that delivers it least late, not making others late.
        best = min(
            usable,
            key=lambda c: (
                len(route_trip_ids(state.vehicles[c["vehicle_id"]])) >= 2,  # keep queues short: current job + one
                c["kpis_after"]["late_trips"] - late_now > 1,
                c["trip_delay_min"] or 0,
                c["pickup_in_min"] or 0,
            ),
        )
        late = f", {best['trip_delay_min']:.0f} min late (no vehicle could take it on time)" if best["trip_delay_min"] else ""
    if best is None:
        return what + "; no vehicle can take it without a late trip, so it is left for the AI to replan"
    step = best["step"]
    assign_trip(state, trip.id, step["vehicle_id"], step["position"], step["interrupt_current"])
    kind = "van" if best["vehicle_type"] == "transport" else "no van fits; free ambulance"
    units.note(state, trip, step["vehicle_id"], f"booking: {kind}, {best['insertion']}" + (", late" if late else ""))
    eta = best["trip_eta_dropoff"].astimezone(LJ).strftime("%H:%M") if best["trip_eta_dropoff"] else "?"
    return what + f"; placed on {step['vehicle_id']} ({best['insertion']}), arrives {eta}{late}"


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
            units.amend(state, state.trips[tid], state.trips[tid].vehicle_id, "replaces the helicopter (grounded by fog)")
    if finishing:
        summary += f"; {', '.join(finishing)}"
    return summary + (f" ({ev.note})" if ev.note else "")


def _better_unit(state: WorldState, trip: Trip, v) -> bool:
    """Would the dispatch rules now send another unit to this (raised) call than v?"""
    from .dispatch import decide

    sim = state.clone_for_simulation()
    t = sim.trips[trip.id]
    detach_trip(sim, t)
    t.status = "unassigned"
    d = decide(sim, t)
    return d.chosen is not None and d.chosen.vehicle_id != v.id


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
    old, old_level = trip.priority, trip.severity or DEFAULT_SEVERITY[trip.priority]
    if ev.severity:
        new_level = ev.severity
    elif SEVERITY_PRIORITY.get(old_level) == ev.priority:
        new_level = old_level  # same priority (e.g. a new condition only)
    else:
        new_level = DEFAULT_SEVERITY[ev.priority]  # type: ignore[index]
    new_condition = ev.condition if ev.condition and ev.condition != trip.condition else None
    if new_level == old_level and new_condition is None:
        raise EventError(f"Trip {trip.id} is already {old_level} ({old})")
    trip.severity, trip.priority = new_level, SEVERITY_PRIORITY[new_level]  # type: ignore[assignment]
    if new_condition:
        trip.condition, trip.condition_label = new_condition, None
    grade(state, trip)
    affected.append(trip.id)
    change = f"{old_level} → {new_level}" if new_level != old_level else new_level
    parts = [f"{trip.id} ({trip.label}) {change}" + (f", now {trip.condition_label}" if new_condition else "")]

    v = state.vehicles.get(trip.vehicle_id) if trip.vehicle_id else None
    ev_priority = trip.priority
    raised = SEVERITY_RANK[new_level] < SEVERITY_RANK[old_level]
    if raised:
        dropoff = state.places[trip.dropoff_id]
        slack = EMERGENCY_SLACK_MIN if ev_priority == "emergency" else URGENT_SLACK_MIN
        if trip.status == "onboard" and v is not None:
            start = state.sim_time
            direct = travel_minutes(state, v.lat, v.lon, dropoff.lat, dropoff.lon, v.type, True)
        else:
            if ev_priority == "emergency":
                trip.pickup_after = min(trip.pickup_after, state.sim_time)
            start = max(state.sim_time, trip.pickup_after)
            pickup = state.places[trip.pickup_id]
            direct = travel_minutes(state, pickup.lat, pickup.lon, dropoff.lat, dropoff.lon, "ambulance", True) + on_scene_min(trip)
        target = start + timedelta(minutes=direct + slack)
        if target < trip.due_by:
            earlier = (trip.due_by - target).total_seconds() / 60
            trip.due_by = target.replace(microsecond=0)
            parts.append(f"due-by {earlier:.0f} min earlier")

    if v is not None and trip.status == "onboard":
        parts.append(f"stays on {v.id} (on board)")
    elif v is not None:
        ok, why = can_serve(v, trip, state.sim_time)
        if not ok:
            detach_trip(state, trip)
            trip.status = "unassigned"
            parts.append(f"released from {v.id} ({why})")
        elif ev_priority == "emergency" and raised and _better_unit(state, trip, v):
            # Raised to a level where another unit should go (doctrine rules 1, 2, 6): re-dispatch.
            detach_trip(state, trip)
            trip.status = "unassigned"
            parts.append("re-evaluated" + dispatch_call(state, trip).replace("; dispatched", ": dispatched", 1))
        elif ev_priority == "emergency" and route_trip_ids(v)[0] != trip.id:
            try:
                assign_trip(state, trip.id, v.id)  # an emergency goes first (the vehicle turns around if needed)
                route = route_trip_ids(v)
                parts.append(f"moved to the front of {v.id}'s route" if route[0] == trip.id else f"next on {v.id}, after {route[0]}")
            except ActionError as e:
                parts.append(f"stays #{route_trip_ids(v).index(trip.id) + 1} on {v.id} ({e})")
    if trip.status == "unassigned" and trip.priority == "emergency":
        parts.append(dispatch_call(state, trip).removeprefix("; "))  # an emergency can't wait for an analysis
    elif trip.needs_doctor and trip.vehicle_id:  # e.g. now a suspected heart attack: the doctor car joins
        if doctor := send_doctor(state, trip).removeprefix(" + ").removeprefix("; "):
            parts.append(doctor)
    if not trip.needs_doctor and (released := release_doctor(state, trip)):
        trip.doctor_vehicle_id = trip.doctor_eta = None
        parts.append(f"doctor {released} stood down")
    return "; ".join(parts) + (f" ({ev.note})" if ev.note else "")
