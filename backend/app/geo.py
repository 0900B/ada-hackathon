"""Small geometry helpers shared by the travel model and the road router."""
from __future__ import annotations

import math

EARTH_R_KM = 6371.0


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
