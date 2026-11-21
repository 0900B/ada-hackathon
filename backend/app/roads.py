"""Real road routing: OSRM for road geometry and free-flow times, TomTom as backup router.

Nothing in the decision path waits on these services. Lookups are served from an in-memory
cache; a miss falls back to the straight-line estimate and queues a background fetch.
- One OSRM "table" request gives free-flow times between ALL known places (used when the
  engine evaluates candidate assignments, so speculative legs need no extra requests).
- OSRM "route" requests give the road geometry for legs vehicles actually drive.
Live traffic, weather and incidents are applied on top by routing.travel_minutes.
"""
from __future__ import annotations

import asyncio
import bisect
import itertools
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from .geo import haversine_km

log = logging.getLogger(__name__)

OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org")
REQUEST_PAUSE_S = 1.0  # the public OSRM demo server allows at most 1 request per second
RETRY_AFTER_FAILURE_S = 300
MAX_POINTS = 120

Key = tuple[float, float]


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


def remaining_points(route: Route, fraction: float) -> list[tuple[float, float]]:
    i = bisect.bisect_right(route.cum_m, max(0.0, min(1.0, fraction)) * route.cum_m[-1])
    return [point_along(route, fraction), *route.points[i:]]


class RoadNetwork:
    def __init__(self) -> None:
        self.routes: dict[tuple[Key, Key], Route] = {}
        self.matrix: dict[tuple[Key, Key], float] = {}  # free-flow seconds between places
        self.matrix_keys: frozenset[Key] = frozenset()
        self.queue: asyncio.PriorityQueue | None = None
        self.pending: set[Any] = set()
        self.failed_until: dict[Any, float] = {}
        self._seq = itertools.count()
        self.stats: dict[str, Any] = {"osrm": 0, "tomtom": 0, "failed": 0, "last_error": None}

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
                else:
                    await self._fetch_route(client, job_id[1], job_id[2])
                on_update()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - routing must never break the app
                self.stats["failed"] += 1
                self.stats["last_error"] = f"{type(e).__name__}: {e}"[:200]
                self.failed_until[job_id] = time.monotonic() + RETRY_AFTER_FAILURE_S
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

    def summary(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "routes_cached": len(self.routes),
            "matrix_places": len(self.matrix_keys),
            "pending": len(self.pending),
            **self.stats,
        }


ROADS = RoadNetwork()
