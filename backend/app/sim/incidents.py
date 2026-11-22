"""Demo: a random disruption that hits what is happening NOW (POST /sim/admin/random-incident).

Each kind looks for a fitting target in the running simulation and is applied through the normal
event path (engine/events.apply_event), so the engine's automatic reaction and the timeline are the
real ones:
- crash / closure: a road closure ahead on the route an emergency unit is driving (it detours, or is
  slowed where no detour service runs);
- jam: a traffic jam (a congestion incident) ahead on such a route: it slows, never blocks
  (routing.JAM_SPEED_KMH through the jammed stretch), and clears by itself after JAM_DURATION_MIN;
  the engine's follow-up may then give the call to a free unit that is clearly faster;
- breakdown: engine failure of a unit on its way to a patient or carrying one (a 112 call is
  re-dispatched at once);
- delay: a busy unit held up 10 to 25 min (a free unit that is clearly faster takes over the call);
- fog: the helicopter grounded while it has a job;
- capacity: UKC can admit one patient fewer than are heading there;
- equipment: a van with equipment on board breaks down (stranded equipment: a decision for the AI).
If the asked-for kind has nothing to hit, the next best kind is used and the summary says so.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..engine.actions import level
from ..engine.candidates import nearest_place_name
from ..engine.projection import incoming_patients, over_capacity
from ..geo import haversine_km
from ..models import BreakdownEvent, DelayEvent, FogEvent, HospitalCapacityEvent, RoadClosureEvent
from ..roads import remaining_points, street_name, stretch_along
from ..routing import INCIDENT_PATH_MAX_HALF_M, SNAP_MARGIN_M, flies, leg_route

if TYPE_CHECKING:
    from ..models import Trip, Vehicle
    from ..state import WorldState

KINDS = ("crash", "closure", "jam", "fog", "breakdown", "delay", "capacity", "equipment")
NEXT_BEST: dict[str, tuple[str, ...]] = {
    "crash": ("closure", "jam", "delay", "breakdown", "capacity", "fog", "equipment"),
    "closure": ("crash", "jam", "delay", "breakdown", "capacity", "fog", "equipment"),
    "jam": ("delay", "crash", "closure", "breakdown", "capacity", "fog", "equipment"),
    "fog": ("delay", "breakdown", "crash", "closure", "jam", "capacity", "equipment"),
    "breakdown": ("delay", "crash", "closure", "jam", "equipment", "capacity", "fog"),
    "delay": ("jam", "crash", "closure", "breakdown", "capacity", "fog", "equipment"),
    "capacity": ("delay", "crash", "closure", "jam", "breakdown", "fog", "equipment"),
    "equipment": ("breakdown", "delay", "crash", "closure", "jam", "capacity", "fog"),
}
CLOSURE_RADIUS_M = 250
MIN_CLEAR_M = CLOSURE_RADIUS_M + SNAP_MARGIN_M + 150  # the closure stays clear of the unit and of its target
# A traffic jam: about 1 km of the unit's route (the circle's diameter), ahead of it and short of its
# target; clears by itself after 20 to 30 world-minutes. The slowdown itself: routing.JAM_SPEED_KMH.
JAM_RADIUS_M = 500
JAM_CLEAR_M = JAM_RADIUS_M + 100
JAM_DURATION_MIN = (20, 30)
DELAY_MIN = (10, 25)
TARGETED_DELAY_MIN = 10  # "delay" on a unit the presenter picked
# Failures the presenter can aim at one unit (fog and a full hospital are not about one unit)
TARGETED_KINDS = ("breakdown", "delay", "crash", "closure", "jam", "equipment")
WHY_NOT_UNIT = {
    "breakdown": "is not on its way to a patient or carrying one",
    "delay": "is not on a job",
    "crash": "is not driving a leg long enough for a crash ahead of it",
    "closure": "is not driving a leg long enough for a closure ahead of it",
    "jam": "is not driving a leg long enough for a traffic jam ahead of it",
    "equipment": "is not a van with equipment on board",
}
WHY_NONE = {
    "crash": "no emergency unit is driving a long enough leg",
    "closure": "no emergency unit is driving a long enough leg",
    "jam": "no emergency unit is driving a long enough leg",
    "fog": "the helicopter has no job",
    "breakdown": "no unit is on its way to a patient or carrying one",
    "delay": "no unit is busy",
    "capacity": "no patient is heading to UKC",
    "equipment": "no van has equipment on board",
}


@dataclass
class Target:
    kind: str
    event: Any  # an OperatorEvent
    vehicle_id: str | None
    trip_id: str | None
    reported_by: str = "crew"


def _trip(state: WorldState, v: Vehicle) -> Trip | None:
    return state.trips.get(v.current_trip_id) if v.current_trip_id else None


def _job(state: WorldState, v: Vehicle) -> Trip | None:
    """The call the unit is on, or the one it was just sent to (still in its queue until it drives off)."""
    t = _trip(state, v)
    if t is None and v.queue:
        t = state.trips.get(v.queue[0])
    return t


def _rank(state: WorldState, v: Vehicle) -> tuple:
    """Prefer units on a 112 call, then the most severe call."""
    t = _job(state, v)
    return (t is None, t is None or t.call is None or t.call.kind != "112", level(t) if t else 9)


def _path(state: WorldState, v: Vehicle) -> list[tuple[float, float]] | None:
    """The rest of the leg v is driving: its road route, else the straight line to its target."""
    route = leg_route(state, v)
    if route is not None:
        return remaining_points(route, v.path_progress)
    t = _trip(state, v)
    if t is None:
        return None
    p = state.places[t.dropoff_id if t.status == "onboard" else t.pickup_id]
    return [(v.lat, v.lon), (p.lat, p.lon)]


def _point_on(path: list[tuple[float, float]], share: float) -> tuple[float, float]:
    lengths = [haversine_km(a[0], a[1], b[0], b[1]) for a, b in zip(path, path[1:])]
    goal, run = sum(lengths) * share, 0.0
    for (a, b), d in zip(zip(path, path[1:]), lengths):
        if run + d >= goal and d > 0:
            f = (goal - run) / d
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        run += d
    return path[-1]


def _closure(state: WorldState, rng: random.Random, kind: str, only: str | None = None) -> Target | None:
    # only: the unit the presenter picked (any road unit driving a job); else an emergency unit
    units = sorted(
        (v for v in state.vehicles.values()
         if (v.id == only if only else v.type in ("ambulance", "doctor")) and not flies(v.type)
         and v.status in ("to_pickup", "with_patient") and _trip(state, v) is not None),
        key=lambda v: (v.type != "ambulance", *_rank(state, v)),
    )
    jam = kind == "jam"
    radius, clear = (JAM_RADIUS_M, JAM_CLEAR_M) if jam else (CLOSURE_RADIUS_M, MIN_CLEAR_M)
    for v in units:
        path = _path(state, v)
        if not path or len(path) < 2:
            continue
        for share in (0.45, 0.35, 0.55, 0.25, 0.65):
            lat, lon = _point_on(path, share)
            clear_start = haversine_km(lat, lon, v.lat, v.lon) * 1000 >= clear
            clear_end = haversine_km(lat, lon, path[-1][0], path[-1][1]) * 1000 >= clear
            if clear_start and clear_end:
                # Drawn on the map as the stretch of this route it covers (a jam: its whole circle)
                stretch = stretch_along(path, lat, lon, radius if jam else min(radius, INCIDENT_PATH_MAX_HALF_M))
                where = nearest_place_name(state, lat, lon)
                street = street_name(lat, lon)
                if jam:
                    what = f"Traffic jam on {street} ({where})" if street else f"Traffic jam ({where})"
                elif kind == "crash":
                    what = f"Traffic crash on {street}, road blocked ({where})" if street else f"Traffic crash, road blocked ({where})"
                else:
                    what = f"{street} closed (emergency works, {where})" if street else f"Road closed (emergency works) ({where})"
                ev = RoadClosureEvent(type="road_closure", lat=round(lat, 5), lon=round(lon, 5), radius_m=radius,
                                      kind="congestion" if jam else "road_closure", description=what,
                                      path=stretch[0] if stretch else None,
                                      duration_min=rng.randint(*JAM_DURATION_MIN) if jam else None)
                return Target(kind, ev, v.id, v.current_trip_id, "dispatcher")
    return None


def _on_the_way(state: WorldState, v: Vehicle) -> bool:
    """On its way to a patient (dispatched, driving there) or carrying one."""
    t = _job(state, v)
    return t is not None and (v.status == "with_patient" or t.status in ("assigned", "en_route_pickup"))


def _breakdown(state: WorldState, rng: random.Random, only: str | None = None) -> Target | None:
    def ok(v: Vehicle) -> bool:
        if v.status == "out_of_service" or flies(v.type) or not _on_the_way(state, v):
            return False
        if only:
            return v.id == only and v.status != "loading"  # the picked unit, on its way or carrying a patient
        if v.type in ("ambulance", "doctor"):
            return v.status != "loading"  # not while treating on scene
        t = _job(state, v)
        return v.status == "with_patient" and t is not None and t.kind == "patient"  # a van carrying a patient

    units = sorted((v for v in state.vehicles.values() if ok(v)),
                   key=lambda v: (v.type != "ambulance", v.status == "with_patient", *_rank(state, v)))
    if not units:
        return None
    v = units[0]
    note = rng.choice(["engine failure", "engine warning light, cannot continue", "flat tyre and a damaged rim"])
    job = _job(state, v)
    return Target("breakdown", BreakdownEvent(type="breakdown", vehicle_id=v.id, note=note), v.id, job.id if job else None)


def _delay(state: WorldState, rng: random.Random, only: str | None = None) -> Target | None:
    units = sorted(
        (v for v in state.vehicles.values()
         if (v.id == only and not flies(v.type) if only else v.type in ("ambulance", "transport"))
         and v.status != "out_of_service" and (_on_the_way(state, v) or v.status == "loading")),
        key=lambda v: (v.type != "ambulance", v.status in ("loading", "with_patient"), *_rank(state, v)),
    )
    if not units:
        return None
    v = units[0]
    minutes = TARGETED_DELAY_MIN if only else rng.randint(*DELAY_MIN)
    note = rng.choice(["stuck behind a crash", "stuck in heavy traffic", "road works, single lane", "wrong turn, turning back"])
    job = _job(state, v)
    return Target("delay", DelayEvent(type="delay", vehicle_id=v.id, minutes=minutes, note=note), v.id, job.id if job else None)


def _fog(state: WorldState, rng: random.Random) -> Target | None:
    for v in state.vehicles.values():
        if flies(v.type) and v.status != "out_of_service" and not v.grounded_until and (v.current_trip_id or v.queue):
            tid = v.current_trip_id or v.queue[0]
            ev = FogEvent(type="fog", duration_min=rng.choice([45, 60, 90]), note="fog over the helicopter base")
            return Target("fog", ev, v.id, tid)
    return None


def _capacity(state: WorldState, rng: random.Random) -> Target | None:
    ukc = state.places.get("ukc")
    incoming = incoming_patients(state, "ukc") if ukc else []
    if not incoming:
        return None
    cap = max(0, len(incoming) - 1)
    if ukc.capacity is not None and ukc.capacity <= cap:
        cap = max(0, ukc.capacity - 1)
    ev = HospitalCapacityEvent(type="hospital_capacity", place_id="ukc", capacity=cap, note="emergency department full")
    # The patient who would lose the place: the last of the incoming patients by urgency.
    probe = state.clone_for_simulation()
    probe.places = dict(state.places)
    probe.places["ukc"] = ukc.model_copy(update={"capacity": cap})
    over = over_capacity(probe).get("ukc") or incoming
    t = over[0]
    return Target("capacity", ev, t.vehicle_id, t.id, "dispatcher")


def _equipment(state: WorldState, rng: random.Random, only: str | None = None) -> Target | None:
    for v in state.vehicles.values():
        t = _trip(state, v)
        if (not only or v.id == only) and v.type == "transport" and t is not None and t.kind == "equipment" and t.status == "onboard" and v.status != "out_of_service":
            note = f"engine failure with {t.cargo or 'equipment'} on board"
            return Target("equipment", BreakdownEvent(type="breakdown", vehicle_id=v.id, note=note), v.id, t.id)
    return None


FINDERS = {
    "crash": lambda s, r: _closure(s, r, "crash"),
    "closure": lambda s, r: _closure(s, r, "closure"),
    "jam": lambda s, r: _closure(s, r, "jam"),
    "fog": _fog,
    "breakdown": _breakdown,
    "delay": _delay,
    "capacity": _capacity,
    "equipment": _equipment,
}
# The same, aimed at one unit (the presenter's pick): (state, rng, vehicle id)
UNIT_FINDERS = {
    "crash": lambda s, r, vid: _closure(s, r, "crash", vid),
    "closure": lambda s, r, vid: _closure(s, r, "closure", vid),
    "jam": lambda s, r, vid: _closure(s, r, "jam", vid),
    "breakdown": _breakdown,
    "delay": _delay,
    "equipment": _equipment,
}


def pick_for_unit(state: WorldState, rng: random.Random, vehicle_id: str, kind: str | None = None) -> tuple[Target | None, str]:
    """A failure aimed at one unit (the targeted failure): the asked-for kind, or with none the first
    that fits it (breakdown, delay, crash, ...). No other unit and no other kind is chosen instead:
    (None, why) when it does not fit this unit."""
    v = state.vehicles.get(vehicle_id)
    if v is None:
        return None, f"Unknown unit {vehicle_id}"
    if kind is not None and kind not in UNIT_FINDERS:
        return None, f"A {kind} is not about one unit: use Random failure"
    if v.status == "out_of_service":
        return None, f"{v.id} is out of service"
    if kind in ("crash", "closure", "jam") and (v.busy_reason == "turnout" or (v.current_trip_id is None and v.queue)):
        # Just dispatched: it has not driven off, so there is no road route to put the failure on yet
        return None, f"{v.id} is still turning out and has no route yet: try again in a few seconds"
    for k in [kind] if kind else list(TARGETED_KINDS):
        if (t := UNIT_FINDERS[k](state, rng, v.id)) is not None:
            return t, ""
    if kind:
        return None, f"No {kind} possible for {v.id}: it {WHY_NOT_UNIT[kind]}"
    return None, f"Nothing to inject for {v.id}: it is not on a job"


def pick(state: WorldState, rng: random.Random, kind: str | None = None) -> tuple[Target | None, str]:
    """The incident to inject: the asked-for kind if it has a target, else the next best one.
    Returns (target or None, note on what was chosen and why)."""
    if kind is None:
        order = list(KINDS)
        rng.shuffle(order)
        for k in order:
            if (t := FINDERS[k](state, rng)) is not None:
                return t, ""
        return None, "Nothing to disrupt: no unit is on a job. Add a random call first."
    t = FINDERS[kind](state, rng)
    if t is not None:
        return t, ""
    for k in NEXT_BEST[kind]:
        if (t := FINDERS[k](state, rng)) is not None:
            return t, f"No {kind} possible ({WHY_NONE[kind]}), so {k} instead."
    return None, f"No {kind} possible ({WHY_NONE[kind]}), and nothing else to disrupt: add a random call first."


