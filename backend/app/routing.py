"""Travel-time model: real road free-flow time (OSRM/TomTom, from the road cache) adjusted for
live traffic, weather and incidents. Falls back to straight-line distance x road factor when
a route isn't cached yet, so a decision never waits on a routing service.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from .geo import haversine_km, point_segment_distance_m  # noqa: F401 - re-exported for other modules
from .models import Incident, Vehicle, VehicleType, WeatherNow
from .roads import ROADS, Route, key

if TYPE_CHECKING:
    from .state import WorldState

ROAD_FACTOR = 1.35  # fallback: road distance / straight-line distance in a city
BASE_SPEED_KMH: dict[VehicleType, float] = {"ambulance": 42.0, "transport": 36.0}  # fallback only
ROUTE_TYPE_FACTOR: dict[VehicleType, float] = {"ambulance": 1.0, "transport": 1.1}  # vans are a bit slower
EMERGENCY_BONUS = 1.3  # lights and sirens
INCIDENT_FACTORS = {"road_closure": 1.6, "accident": 1.35, "congestion": 1.25}  # detour/slowdown multipliers
# Helicopters (HNMP) fly straight: no roads, so no traffic, incidents or lights-and-sirens bonus.
HELICOPTER_SPEED_KMH = 200.0
HELICOPTER_OVERHEAD_MIN = 3.0  # take-off and landing, added to every flight leg


def flies(vehicle_type: VehicleType) -> bool:
    """True for aircraft: straight-line travel, and never ask the road router for routes."""
    return vehicle_type == "helicopter"


def flight_minutes(alat: float, alon: float, blat: float, blon: float) -> float:
    km = haversine_km(alat, alon, blat, blon)
    if km < 0.01:
        return 0.0
    return km / HELICOPTER_SPEED_KMH * 60 + HELICOPTER_OVERHEAD_MIN


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
        return flight_minutes(alat, alon, blat, blon)
    straight_km = haversine_km(alat, alon, blat, blon)
    if straight_km < 0.01:
        return 0.0
    conditions = state.traffic_factor * weather_factor(state.effective_weather) * (EMERGENCY_BONUS if emergency else 1.0)
    incidents = state.all_incidents()
    free_flow_s = ROADS.duration_s(alat, alon, blat, blon)
    if free_flow_s is not None:
        route = ROADS.route(alat, alon, blat, blon)
        inc = route_incident_factor(route, incidents) if route else incident_factor(incidents, alat, alon, blat, blon)[0]
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
