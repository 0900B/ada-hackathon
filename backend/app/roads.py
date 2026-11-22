"""Real road routing: OSRM for road geometry and free-flow times, TomTom as backup router.

Nothing in the decision path waits on these services. Lookups are served from an in-memory
cache; a miss falls back to the straight-line estimate and queues a background fetch.
- One OSRM "table" request gives free-flow times between ALL known places (used when the
  engine evaluates candidate assignments, so speculative legs need no extra requests).
- OSRM "route" requests give the road geometry for legs vehicles actually drive.
- Detours: when a route crosses an active road closure, TomTom Calculate Route with avoidAreas
  gives a route around it (cached per leg + set of closures avoided).
Live traffic, weather and incidents are applied on top by routing.travel_minutes.
"""
from __future__ import annotations

import asyncio
import bisect
import itertools
import logging
import math
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from .geo import haversine_km, point_segment_distance_m

log = logging.getLogger(__name__)

OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org")
REQUEST_PAUSE_S = 1.0  # the public OSRM demo server allows at most 1 request per second
RETRY_AFTER_FAILURE_S = 300
MAX_POINTS = 120

Key = tuple[float, float]
Avoid = tuple[tuple[float, float, int], ...]  # closures to route around: (lat, lon, radius_m), sorted
MAX_AVOID = 10  # TomTom accepts at most ten avoid rectangles per request
DETOUR_PAUSE_AFTER_FAILURE_S = 300


def avoid_box(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """The square around a closure circle: (south, west, north, east) in degrees."""
    dlat = radius_m / 111_320
    dlon = radius_m / (111_320 * max(0.2, math.cos(math.radians(lat))))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon


def in_box(box: tuple[float, float, float, float], lat: float, lon: float) -> bool:
    return box[0] <= lat <= box[2] and box[1] <= lon <= box[3]


def crosses(points: list[tuple[float, float]], avoid: Avoid, tolerance: float = 0.9) -> bool:
    """True if the polyline passes through any of the closure circles (with a little tolerance)."""
    for lat, lon, radius in avoid:
        limit = radius * tolerance
        if any(point_segment_distance_m(lat, lon, a[0], a[1], b[0], b[1]) <= limit for a, b in zip(points, points[1:])):
            return True
    return False


def key(lat: float, lon: float) -> Key:
    """~10 m grid: places always map to the same key."""
    return (round(lat, 4), round(lon, 4))


@dataclass
class Route:
    duration_s: float  # free-flow driving time
    distance_m: float
    points: list[tuple[float, float]]  # (lat, lon), starts/ends exactly at the requested points
    cum_m: list[float]  # cumulative distance along points
    provider: str


def _downsample(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(points) <= MAX_POINTS:
        return points
    step = (len(points) - 1) / (MAX_POINTS - 1)
    return [points[round(i * step)] for i in range(MAX_POINTS)]


def make_route(duration_s: float, distance_m: float, pts: list[tuple[float, float]], a: Key, b: Key, provider: str) -> Route:
    points = [a, *_downsample(pts), b]
    cum = [0.0]
    for (alat, alon), (blat, blon) in zip(points, points[1:]):
        cum.append(cum[-1] + haversine_km(alat, alon, blat, blon) * 1000)
    return Route(duration_s=duration_s, distance_m=distance_m, points=points, cum_m=cum, provider=provider)


def point_along(route: Route, fraction: float) -> tuple[float, float]:
    total = route.cum_m[-1]
    if total <= 0:
        return route.points[-1]
    target = max(0.0, min(1.0, fraction)) * total
    i = bisect.bisect_left(route.cum_m, target)
    if i <= 0:
        return route.points[0]
    if i >= len(route.points):
        return route.points[-1]
    seg = route.cum_m[i] - route.cum_m[i - 1]
    f = 0.0 if seg == 0 else (target - route.cum_m[i - 1]) / seg
    (alat, alon), (blat, blon) = route.points[i - 1], route.points[i]
    return alat + (blat - alat) * f, alon + (blon - alon) * f


def nearest_fraction(route: Route, lat: float, lon: float) -> float:
    """Fraction (0..1, by distance) of the point on the route nearest to (lat, lon)."""
    total = route.cum_m[-1]
    if total <= 0:
        return 0.0
    kx = 111_320 * math.cos(math.radians(lat))  # metres per degree of longitude here
    ky = 110_540  # metres per degree of latitude
    best_d, best_m = float("inf"), 0.0
    for i, ((alat, alon), (blat, blon)) in enumerate(zip(route.points, route.points[1:])):
        ax, ay = (alon - lon) * kx, (alat - lat) * ky
        bx, by = (blon - lon) * kx, (blat - lat) * ky
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg2))
        d = math.hypot(ax + t * dx, ay + t * dy)
        if d < best_d:
            best_d, best_m = d, route.cum_m[i] + t * (route.cum_m[i + 1] - route.cum_m[i])
    return best_m / total


def remaining_points(route: Route, fraction: float) -> list[tuple[float, float]]:
    i = bisect.bisect_right(route.cum_m, max(0.0, min(1.0, fraction)) * route.cum_m[-1])
    return [point_along(route, fraction), *route.points[i:]]


def stretch_along(
    points: list[tuple[float, float]], lat: float, lon: float, half_m: float, max_off_m: float = 40.0
) -> tuple[list[tuple[float, float]], float] | None:
    """The part of a polyline from half_m before to half_m after its point nearest to (lat, lon):
    (the stretch, how far the polyline passes from the point in metres). None if the polyline
    passes further than max_off_m from the point. Used to draw an incident along its road."""
    if len(points) < 2:
        return None
    kx = 111_320 * math.cos(math.radians(lat))
    ky = 110_540
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    pad = max_off_m / ky
    if not (min(lats) - pad <= lat <= max(lats) + pad and min(lons) - pad * 1.6 <= lon <= max(lons) + pad * 1.6):
        return None
    cum = [0.0]
    best_d, best_m = float("inf"), 0.0
    for i, ((alat, alon), (blat, blon)) in enumerate(zip(points, points[1:])):
        ax, ay = (alon - lon) * kx, (alat - lat) * ky
        dx, dy = (blon - alon) * kx, (blat - alat) * ky
        seg = math.hypot(dx, dy)
        t = 0.0 if seg == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / (seg * seg)))
        d = math.hypot(ax + t * dx, ay + t * dy)
        if d < best_d:
            best_d, best_m = d, cum[i] + t * seg
        cum.append(cum[i] + seg)
    lo, hi = max(0.0, best_m - half_m), min(cum[-1], best_m + half_m)
    if best_d > max_off_m or hi - lo < 20:
        return None

    def at(m: float) -> tuple[float, float]:
        i = max(1, min(len(points) - 1, bisect.bisect_left(cum, m)))
        seg = cum[i] - cum[i - 1]
        f = 0.0 if seg == 0 else (m - cum[i - 1]) / seg
        (alat, alon), (blat, blon) = points[i - 1], points[i]
        return (round(alat + (blat - alat) * f, 6), round(alon + (blon - alon) * f, 6))

    inner = [(round(p[0], 6), round(p[1], 6)) for p, m in zip(points, cum) if lo < m < hi]
    return [at(lo), *inner, at(hi)], best_d


_street_names: dict[Key, str | None] = {}


def street_name(lat: float, lon: float) -> str | None:
    """The street at (lat, lon) from OSRM's nearest service, for an incident's description ("Traffic
    jam on Zaloška cesta"). A short blocking call: only for the demo's random incidents (a request
    handler, never the simulation loop). None when road routing is off or OSRM doesn't answer."""
    k = key(lat, lon)
    if k in _street_names:
        return _street_names[k]
    if not ROADS.enabled:
        return None
    from .config import HTTP_USER_AGENT  # local import: keeps this module free of app settings

    try:
        r = httpx.get(f"{OSRM_URL}/nearest/v1/driving/{lon},{lat}", params={"number": 1}, timeout=2.5,
                      headers={"User-Agent": HTTP_USER_AGENT})
        r.raise_for_status()
        points = r.json().get("waypoints") or []
        name = (points[0].get("name") or "").strip() if points and points[0].get("distance", 99) <= 60 else ""
    except Exception as e:  # noqa: BLE001 - a description without the street name is fine
        log.info("street name lookup failed: %s", e)
        return None
    _street_names[k] = name or None
    return name or None


class RoadNetwork:
    def __init__(self) -> None:
        self.routes: dict[tuple[Key, Key], Route] = {}
        self.detours: dict[tuple[Key, Key], dict[Avoid, Route]] = {}  # leg -> closures avoided -> route
        self.detour_pause_until = 0.0
        self.matrix: dict[tuple[Key, Key], float] = {}  # free-flow seconds between places
        self.matrix_keys: frozenset[Key] = frozenset()
        self.queue: asyncio.PriorityQueue | None = None
        self.pending: set[Any] = set()
        self.failed_until: dict[Any, float] = {}
        self._seq = itertools.count()
        self.stats: dict[str, Any] = {"osrm": 0, "tomtom": 0, "detours": 0, "failed": 0, "last_error": None}

    @property
    def enabled(self) -> bool:
        return os.getenv("ROAD_ROUTING", "1") == "1"

    # --- lookups: synchronous, never touch the network ----------------------------------

    def route(self, alat: float, alon: float, blat: float, blon: float) -> Route | None:
        return self.routes.get((key(alat, alon), key(blat, blon)))

    def duration_s(self, alat: float, alon: float, blat: float, blon: float) -> float | None:
        k = (key(alat, alon), key(blat, blon))
        r = self.routes.get(k)
        return r.duration_s if r is not None else self.matrix.get(k)

    def matrix_s(self, alat: float, alon: float, blat: float, blon: float) -> float | None:
        return self.matrix.get((key(alat, alon), key(blat, blon)))

    def detour(self, alat: float, alon: float, blat: float, blon: float, avoid: Avoid) -> Route | None:
        return self.detours.get((key(alat, alon), key(blat, blon)), {}).get(avoid)

    def detours_for(self, alat: float, alon: float, blat: float, blon: float) -> dict[Avoid, Route]:
        return self.detours.get((key(alat, alon), key(blat, blon)), {})

    def detours_available(self) -> bool:
        """Detours need TomTom (OSRM's public server can't avoid areas); paused for a while after a failure."""
        from .fetchers.tomtom import tomtom_key  # local import: tomtom depends on models only

        return self.enabled and bool(tomtom_key()) and time.monotonic() >= self.detour_pause_until

    # --- requests: only queue work ------------------------------------------------------

    def _enqueue(self, priority: int, job_id: Any) -> None:
        if self.queue is None or not self.enabled or job_id in self.pending:
            return
        if self.failed_until.get(job_id, 0) > time.monotonic():
            return
        self.pending.add(job_id)
        self.queue.put_nowait((priority, next(self._seq), job_id))

    def want_route(self, alat: float, alon: float, blat: float, blon: float) -> None:
        ka, kb = key(alat, alon), key(blat, blon)
        if ka != kb and (ka, kb) not in self.routes:
            self._enqueue(1, ("route", ka, kb))

    def want_detour(self, alat: float, alon: float, blat: float, blon: float, avoid: Avoid) -> None:
        ka, kb = key(alat, alon), key(blat, blon)
        if ka != kb and avoid and self.detours_available() and avoid not in self.detours.get((ka, kb), {}):
            self._enqueue(0, ("detour", ka, kb, avoid))  # a vehicle may be waiting for it

    def want_matrix(self, points: list[tuple[float, float]]) -> None:
        keys = frozenset(key(lat, lon) for lat, lon in points)
        if len(keys) >= 2 and not keys <= self.matrix_keys:
            self._enqueue(0, ("matrix", keys))

    # --- background worker ----------------------------------------------------------------

    async def run(self, client: httpx.AsyncClient, on_update: Callable[[], None]) -> None:
        self.queue = asyncio.PriorityQueue()
        while True:
            _, _, job_id = await self.queue.get()
            try:
                if job_id[0] == "matrix":
                    await self._fetch_matrix(client, job_id[1])
                elif job_id[0] == "detour":
                    await self._fetch_detour(client, job_id[1], job_id[2], job_id[3])
                else:
                    await self._fetch_route(client, job_id[1], job_id[2])
                on_update()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - routing must never break the app
                self.stats["failed"] += 1
                self.stats["last_error"] = f"{type(e).__name__}: {e}"[:200]
                self.failed_until[job_id] = time.monotonic() + RETRY_AFTER_FAILURE_S
                if job_id[0] == "detour":  # quota or TomTom trouble: fall back to slowdowns for a while
                    self.detour_pause_until = time.monotonic() + DETOUR_PAUSE_AFTER_FAILURE_S
                log.warning("road routing job %s failed: %s", job_id[0], self.stats["last_error"])
            finally:
                self.pending.discard(job_id)
            await asyncio.sleep(REQUEST_PAUSE_S)

    async def _fetch_matrix(self, client: httpx.AsyncClient, keys: frozenset[Key]) -> None:
        ordered = sorted(keys | self.matrix_keys)
        coords = ";".join(f"{lon},{lat}" for lat, lon in ordered)
        r = await client.get(f"{OSRM_URL}/table/v1/driving/{coords}", params={"annotations": "duration"}, timeout=20)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "Ok":
            raise RuntimeError(f"OSRM table returned {data.get('code')}")
        for i, a in enumerate(ordered):
            for j, b in enumerate(ordered):
                d = data["durations"][i][j]
                if i != j and d is not None:
                    self.matrix[(a, b)] = float(d)
        self.matrix_keys = frozenset(ordered)
        self.stats["osrm"] += 1

    async def _fetch_route(self, client: httpx.AsyncClient, a: Key, b: Key) -> None:
        try:
            route = await self._osrm_route(client, a, b)
        except Exception as osrm_error:  # noqa: BLE001 - try the backup router
            try:
                route = await self._tomtom_route(client, a, b)
            except Exception as tomtom_error:  # noqa: BLE001
                raise RuntimeError(f"OSRM: {osrm_error}; TomTom: {tomtom_error}") from None
        self.routes[(a, b)] = route
        self.stats[route.provider] += 1

    async def _osrm_route(self, client: httpx.AsyncClient, a: Key, b: Key) -> Route:
        coords = f"{a[1]},{a[0]};{b[1]},{b[0]}"
        r = await client.get(
            f"{OSRM_URL}/route/v1/driving/{coords}", params={"overview": "full", "geometries": "geojson"}, timeout=15
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "Ok" or not data.get("routes"):
            raise RuntimeError(f"OSRM route returned {data.get('code')}")
        best = data["routes"][0]
        pts = [(lat, lon) for lon, lat in best["geometry"]["coordinates"]]
        return make_route(float(best["duration"]), float(best["distance"]), pts, a, b, "osrm")

    async def _tomtom_route(self, client: httpx.AsyncClient, a: Key, b: Key) -> Route:
        from .fetchers import tomtom  # local import: tomtom depends on models only

        if not tomtom.tomtom_key():
            raise RuntimeError("no TomTom key")
        tomtom.spend("routing", 1)
        data = await tomtom.get(
            client,
            f"https://api.tomtom.com/routing/1/calculateRoute/{a[0]},{a[1]}:{b[0]},{b[1]}/json",
            {"traffic": "false", "travelMode": "car", "routeType": "fastest"},
        )
        best = data["routes"][0]
        pts = [(p["latitude"], p["longitude"]) for p in best["legs"][0]["points"]]
        s = best["summary"]
        return make_route(float(s["travelTimeInSeconds"]), float(s["lengthInMeters"]), pts, a, b, "tomtom")

    async def _fetch_detour(self, client: httpx.AsyncClient, a: Key, b: Key, avoid: Avoid) -> None:
        from .fetchers import tomtom  # local import: tomtom depends on models only

        tomtom.spend("routing", 1)
        rectangles = []
        for lat, lon, radius in avoid:
            s, w, n, e = avoid_box(lat, lon, radius)
            rectangles.append(
                {
                    "southWestCorner": {"latitude": round(s, 6), "longitude": round(w, 6)},
                    "northEastCorner": {"latitude": round(n, 6), "longitude": round(e, 6)},
                }
            )
        data = await tomtom.post(
            client,
            f"https://api.tomtom.com/routing/1/calculateRoute/{a[0]},{a[1]}:{b[0]},{b[1]}/json",
            {"traffic": "false", "travelMode": "car", "routeType": "fastest"},
            {"avoidAreas": {"rectangles": rectangles}},
        )
        best = data["routes"][0]
        pts = [(p["latitude"], p["longitude"]) for p in best["legs"][0]["points"]]
        s = best["summary"]
        route = make_route(float(s["travelTimeInSeconds"]), float(s["lengthInMeters"]), pts, a, b, "tomtom-detour")
        if crosses(route.points, avoid):
            # TomTom found no way around (e.g. the only road, or an endpoint snapped inside the area):
            # remember that, so the leg keeps the closure slowdown instead of a fake "detour".
            route.provider = "tomtom-no-way-around"
            self.stats["no_way_around"] = self.stats.get("no_way_around", 0) + 1
        else:
            self.stats["detours"] += 1
        self.detours.setdefault((a, b), {})[avoid] = route

    def summary(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "routes_cached": len(self.routes),
            "detours_cached": sum(len(d) for d in self.detours.values()),
            "detours_available": self.detours_available(),
            "matrix_places": len(self.matrix_keys),
            "pending": len(self.pending),
            **self.stats,
        }


ROADS = RoadNetwork()
