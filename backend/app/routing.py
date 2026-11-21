"""Travel-time model: straight-line distance x road factor, adjusted for traffic, weather and incidents.

Deliberately simple and deterministic so every number the agent quotes is reproducible.
Swap in a real road graph (e.g. OSMnx) later without changing the function signatures.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Iterable

from .models import Incident, VehicleType, WeatherNow

if TYPE_CHECKING:
    from .state import WorldState

EARTH_R_KM = 6371.0
ROAD_FACTOR = 1.35  # road distance / straight-line distance in a city
BASE_SPEED_KMH: dict[VehicleType, float] = {"ambulance": 42.0, "transport": 36.0}
EMERGENCY_BONUS = 1.3  # lights and sirens
INCIDENT_FACTORS = {"road_closure": 1.6, "accident": 1.35, "congestion": 1.25}  # detour/slowdown multipliers


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(a))


def _xy_m(lat: float, lon: float, lat0: float) -> tuple[float, float]:
    """Local equirectangular projection in metres; fine at city scale."""
    r = EARTH_R_KM * 1000
    return math.radians(lon) * r * math.cos(math.radians(lat0)), math.radians(lat) * r


def point_segment_distance_m(plat: float, plon: float, alat: float, alon: float, blat: float, blon: float) -> float:
    lat0 = (alat + blat) / 2
    px, py = _xy_m(plat, plon, lat0)
    ax, ay = _xy_m(alat, alon, lat0)
    bx, by = _xy_m(blat, blon, lat0)
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


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
    """Slowdown for a leg passing near active incidents, and which incidents it hits."""
    factor, hits = 1.0, []
    for inc in incidents:
        if inc.active and point_segment_distance_m(inc.lat, inc.lon, alat, alon, blat, blon) <= inc.radius_m:
            factor = max(factor, INCIDENT_FACTORS.get(inc.kind, 1.2))
            hits.append(inc.id)
    return factor, hits


def travel_minutes(
    state: WorldState,
    alat: float,
    alon: float,
    blat: float,
    blon: float,
    vehicle_type: VehicleType,
    emergency: bool = False,
) -> float:
    km = haversine_km(alat, alon, blat, blon) * ROAD_FACTOR
    if km < 0.01:
        return 0.0
    speed = BASE_SPEED_KMH[vehicle_type] * state.traffic_factor * weather_factor(state.effective_weather)
    if emergency:
        speed *= EMERGENCY_BONUS
    inc_factor, _ = incident_factor(state.incidents.values(), alat, alon, blat, blon)
    return km / speed * 60 * inc_factor
