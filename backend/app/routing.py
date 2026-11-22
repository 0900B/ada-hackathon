"""Travel-time model: real road free-flow time (OSRM/TomTom, from the road cache) adjusted for
live traffic, weather and incidents. Falls back to straight-line distance x road factor when
a route isn't cached yet, so a decision never waits on a routing service.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from .geo import haversine_km, point_segment_distance_m  # noqa: F401 - re-exported for other modules
from .hems import HEMS_HELIPAD_LANDING_MIN, HEMS_SCENE_LANDING_MIN
from .models import Incident, Vehicle, VehicleType, WeatherNow
from .roads import MAX_AVOID, ROADS, Avoid, Route, avoid_box, in_box, key, remaining_points

SNAP_MARGIN_M = 150  # a leg starting/ending this close to a closure can't be routed around it

if TYPE_CHECKING:
    from .state import WorldState

ROAD_FACTOR = 1.35  # fallback: road distance / straight-line distance in a city
# fallback only; the doctor car (VUZ) is an estate car with lights and sirens: as quick as an ambulance
BASE_SPEED_KMH: dict[VehicleType, float] = {"ambulance": 42.0, "transport": 36.0, "doctor": 42.0}
ROUTE_TYPE_FACTOR: dict[VehicleType, float] = {"ambulance": 1.0, "transport": 1.1, "doctor": 1.0}  # vans are a bit slower
EMERGENCY_BONUS = 1.3  # lights and sirens
INCIDENT_FACTORS = {"road_closure": 1.6, "accident": 1.35, "congestion": 1.25}  # detour/slowdown multipliers
# Helicopters (HNMP) fly straight: no roads, so no traffic, incidents or lights-and-sirens bonus.
# Each flight leg = cruise at 200 km/h (the challenge brief) + the landing at its end (app/hems.py:
# a prepared helipad, or the scene). The activation from rest at the base (call to take-off,
# hems.HEMS_ACTIVATION_MIN) is the helicopter's turnout (engine/service_times.py).
HELICOPTER_SPEED_KMH = 200.0
HELIPAD_KINDS = ("hospital", "base")  # where a flight ends on a prepared pad (hospital helipads, the HEMS base)


def flies(vehicle_type: VehicleType) -> bool:
    """True for aircraft: straight-line travel, and never ask the road router for routes."""
    return vehicle_type == "helicopter"


def flight_minutes(alat: float, alon: float, blat: float, blon: float, landing_min: float = HEMS_SCENE_LANDING_MIN) -> float:
    """One flight leg: cruise in a straight line, then the landing at the destination."""
    km = haversine_km(alat, alon, blat, blon)
    if km < 0.01:
        return 0.0
    return km / HELICOPTER_SPEED_KMH * 60 + landing_min


def landing_min(state: WorldState, lat: float, lon: float) -> float:
    """Approach and landing at (lat, lon): a prepared helipad (a hospital, the base) or the scene."""
    for p in state.places.values():
        if p.kind in HELIPAD_KINDS and abs(p.lat - lat) < 1e-5 and abs(p.lon - lon) < 1e-5:
            return HEMS_HELIPAD_LANDING_MIN
    return HEMS_SCENE_LANDING_MIN


def weather_factor(w: WeatherNow | None) -> float:
    """Speed multiplier for the current weather (1.0 = no effect)."""
    if w is None:
        return 1.0
    f = 1.0
    if w.snowfall_cm >= 1.0:
        f = min(f, 0.6)
    elif w.snowfall_cm > 0:
        f = min(f, 0.75)
    if w.precipitation_mm > 0 and w.temperature_c <= 0.5:
        f = min(f, 0.7)  # freezing rain / ice risk
    elif w.precipitation_mm >= 2:
        f = min(f, 0.85)
    elif w.precipitation_mm > 0:
        f = min(f, 0.93)
    if w.wind_speed_kmh >= 60:
        f = min(f, 0.85)
    return f


def incident_factor(
    incidents: Iterable[Incident], alat: float, alon: float, blat: float, blon: float
) -> tuple[float, list[str]]:
    """Slowdown for a straight leg passing near active incidents, and which incidents it hits."""
    factor, hits = 1.0, []
    for inc in incidents:
        if inc.active and point_segment_distance_m(inc.lat, inc.lon, alat, alon, blat, blon) <= inc.radius_m:
            factor = max(factor, INCIDENT_FACTORS.get(inc.kind, 1.2))
            hits.append(inc.id)
    return factor, hits


_route_incident_memo: dict[tuple, float] = {}


def route_incident_factor(route: Route, incidents: Iterable[Incident]) -> float:
    """Slowdown for a road route passing near active incidents (memoised per route + incident set)."""
    active = [i for i in incidents if i.active]
    memo_key = (id(route), tuple(sorted(i.id for i in active)))
    if memo_key in _route_incident_memo:
        return _route_incident_memo[memo_key]
    lats = [p[0] for p in route.points]
    lons = [p[1] for p in route.points]
    factor = 1.0
    for inc in active:
        pad = inc.radius_m / 111_000 * 1.5  # metres -> degrees, generous
        if not (min(lats) - pad <= inc.lat <= max(lats) + pad and min(lons) - pad * 1.5 <= inc.lon <= max(lons) + pad * 1.5):
            continue
        if any(
            point_segment_distance_m(inc.lat, inc.lon, a[0], a[1], b[0], b[1]) <= inc.radius_m
            for a, b in zip(route.points, route.points[1:])
        ):
            factor = max(factor, INCIDENT_FACTORS.get(inc.kind, 1.2))
    if len(_route_incident_memo) > 5000:
        _route_incident_memo.clear()
    _route_incident_memo[memo_key] = factor
    return factor


# --- Detours around road closures ---------------------------------------------------------
# A road closure is avoidable on a leg unless the leg starts or ends inside it. A route that
# crosses one is swapped for a cached TomTom detour (avoidAreas); until that arrives, or if
# TomTom is unavailable, the route keeps the road_closure slowdown factor above.


def avoid_key(inc: Incident) -> tuple[float, float, int]:
    return (round(inc.lat, 4), round(inc.lon, 4), int(round(inc.radius_m)))


def avoidable_closures(
    incidents: Iterable[Incident], alat: float, alon: float, blat: float, blon: float
) -> list[Incident]:
    out = []
    for inc in incidents:
        if inc.active and inc.kind == "road_closure":
            box = avoid_box(inc.lat, inc.lon, inc.radius_m + SNAP_MARGIN_M)  # routers snap to nearby roads
            if not in_box(box, alat, alon) and not in_box(box, blat, blon):
                out.append(inc)
    return out


def points_hit(points: list[tuple[float, float]], closures: Iterable[Incident]) -> list[Incident]:
    """The closures a polyline passes through."""
    if len(points) < 2:
        return []
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    hits = []
    for inc in closures:
        pad = inc.radius_m / 111_000 * 1.5
        if not (min(lats) - pad <= inc.lat <= max(lats) + pad and min(lons) - pad * 1.5 <= inc.lon <= max(lons) + pad * 1.5):
            continue
        if any(point_segment_distance_m(inc.lat, inc.lon, a[0], a[1], b[0], b[1]) <= inc.radius_m for a, b in zip(points, points[1:])):
            hits.append(inc)
    return hits


_route_hits_memo: dict[tuple, list[Incident]] = {}


def route_hits(route: Route, closures: list[Incident]) -> list[Incident]:
    memo_key = (id(route), tuple(sorted(avoid_key(c) for c in closures)))
    if memo_key not in _route_hits_memo:
        if len(_route_hits_memo) > 5000:
            _route_hits_memo.clear()
        _route_hits_memo[memo_key] = points_hit(route.points, closures)
    return _route_hits_memo[memo_key]


def merge_avoid(avoid: Avoid | None, hits: Iterable[Incident]) -> Avoid:
    return tuple(sorted({*(avoid or ()), *(avoid_key(c) for c in hits)}))[:MAX_AVOID]


def is_detour(route: Route | None) -> bool:
    """A real way around the closures (not TomTom's best effort straight through them)."""
    return route is not None and route.provider == "tomtom-detour"


def resolve_route(
    state: WorldState, alat: float, alon: float, blat: float, blon: float, request: bool = False
) -> tuple[Route | None, bool]:
    """The road route for a -> b with closures taken into account: (route, is_detour).

    request=True (real state only) asks TomTom for a detour when the cached route crosses a closure.
    """
    base = ROADS.route(alat, alon, blat, blon)
    closures = avoidable_closures(state.all_incidents(), alat, alon, blat, blon)
    if not closures:
        return base, False
    route, avoid, found = base, (), False
    if route is None:  # e.g. a vehicle re-routed from mid-road: only a detour was ever fetched
        cached = ROADS.detours_for(alat, alon, blat, blon)
        if not cached:
            return None, False
        avoid = max(cached, key=len)
        route = cached[avoid]
        found = is_detour(route)
    for _ in range(3):  # a detour may cross another closure: add it and look again
        hits = route_hits(route, closures)
        if not hits:
            break
        wanted = merge_avoid(avoid, hits)
        if wanted == avoid:
            break  # TomTom found no way around: keep the slowdown
        detour = ROADS.detour(alat, alon, blat, blon, wanted)
        if detour is None:
            if request:
                ROADS.want_detour(alat, alon, blat, blon, wanted)
            break
        if not is_detour(detour):
            break  # no way around: keep the route with the closure slowdown
        route, avoid, found = detour, wanted, True
    return route, found


def leg_route(state: WorldState, v: Vehicle) -> Route | None:
    """The road geometry v follows on the leg it is driving: its detour if it has one, else the route."""
    if v.path_from is None or v.path_to is None:
        return None
    a, b = v.path_from, v.path_to
    if v.path_avoid:
        detour = ROADS.detour(a[0], a[1], b[0], b[1], v.path_avoid)
        if detour is not None:
            # no way around: TomTom's route is still the best road path from a mid-road position
            return detour if is_detour(detour) else (ROADS.route(a[0], a[1], b[0], b[1]) or detour)
        if ROADS.detours_available():
            return None  # waiting for the detour: drive towards the target meanwhile
    return ROADS.route(a[0], a[1], b[0], b[1])


def reroute_if_blocked(state: WorldState, v: Vehicle) -> bool:
    """If the rest of v's leg crosses a closure, re-plan the leg from where v is now, around it.

    Returns True when v was rerouted. The new leg starts at v's position (so it never jumps);
    the detour is requested from TomTom and v snaps onto it when it arrives.
    """
    if flies(v.type) or v.path_from is None or v.path_to is None or not ROADS.detours_available():
        return False
    closures = avoidable_closures(state.all_incidents(), v.lat, v.lon, v.path_to[0], v.path_to[1])
    if not closures:
        return False
    rerouted = False
    for _ in range(3):
        route = leg_route(state, v)
        if route is None:
            break
        rest = route.points if v.path_progress <= 0 else remaining_points(route, v.path_progress)
        hits = points_hit(rest, closures)
        if not hits:
            break
        wanted = merge_avoid(v.path_avoid, hits)
        if wanted == v.path_avoid:
            break  # already avoiding these and still crossing: TomTom found no way around
        if v.path_progress > 0:
            v.path_from, v.path_progress = (v.lat, v.lon), 0.0
        v.path_avoid = wanted
        ROADS.want_detour(v.path_from[0], v.path_from[1], v.path_to[0], v.path_to[1], wanted)
        v.on_road = leg_route(state, v) is not None
        rerouted = True
    return rerouted


def travel_minutes(
    state: WorldState,
    alat: float,
    alon: float,
    blat: float,
    blon: float,
    vehicle_type: VehicleType,
    emergency: bool = False,
) -> float:
    if flies(vehicle_type):
        return flight_minutes(alat, alon, blat, blon, landing_min(state, blat, blon))
    straight_km = haversine_km(alat, alon, blat, blon)
    if straight_km < 0.01:
        return 0.0
    conditions = state.traffic_factor * weather_factor(state.effective_weather) * (EMERGENCY_BONUS if emergency else 1.0)
    incidents = state.all_incidents()
    route, _ = resolve_route(state, alat, alon, blat, blon)
    if route is not None:
        inc = route_incident_factor(route, incidents)
        return route.duration_s / 60 * ROUTE_TYPE_FACTOR[vehicle_type] / conditions * inc
    free_flow_s = ROADS.matrix_s(alat, alon, blat, blon)
    if free_flow_s is not None:
        inc = incident_factor(incidents, alat, alon, blat, blon)[0]
        return free_flow_s / 60 * ROUTE_TYPE_FACTOR[vehicle_type] / conditions * inc
    km = straight_km * ROAD_FACTOR
    inc = incident_factor(incidents, alat, alon, blat, blon)[0]
    return km / (BASE_SPEED_KMH[vehicle_type] * conditions) * 60 * inc


def vehicle_leg_minutes(
    state: WorldState, v: Vehicle, blat: float, blon: float, emergency: bool = False
) -> float:
    """Time for v to reach (blat, blon) from where it is now, honouring the leg it is driving."""
    if v.path_to is not None and v.path_from is not None and tuple(v.path_to) == key(blat, blon):
        full = travel_minutes(state, v.path_from[0], v.path_from[1], blat, blon, v.type, emergency)
        return full * (1.0 - v.path_progress)
    return travel_minutes(state, v.lat, v.lon, blat, blon, v.type, emergency)
