"""Turn-by-turn navigation for the in-vehicle tablet: OSRM manoeuvres for the leg a vehicle drives.

GET /{world}/vehicles/{id}/navigation answers from a per-vehicle cache and never waits on OSRM:
a missing or outdated route is fetched in the background (at most one OSRM request every
MIN_SPACING_S, so together with the road router we stay near the public server's 1 req/s), and the
tablet picks it up on its next poll. When the vehicle drives a detour around a closure, 2-3 via
points sampled from the detour make OSRM's instructions follow the same roads. Any failure just
means no manoeuvres: the tablet then shows distance and ETA only.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import httpx

from .geo import haversine_km
from .roads import OSRM_URL, Key, key, remaining_points
from .routing import flies, is_detour, leg_route, vehicle_leg_minutes

if TYPE_CHECKING:
    from .models import Vehicle
    from .state import WorldState

log = logging.getLogger(__name__)

MIN_SPACING_S = 2.0  # between our own OSRM requests (the road router also uses the public server)
OFF_ROUTE_M = 120.0  # further than this from the cached route: fetch a new one from where it is now
REFETCH_MIN_S = 15.0  # never refetch the same vehicle's route more often than this
FAILURE_PAUSE_S = 60.0  # after a failed request, wait this long before asking again for that vehicle
MAX_STEPS = 8  # manoeuvres returned (the next one first)
VIA_POINTS = 3  # via points sampled from a detour


@dataclass
class _NavRoute:
    target: Key
    detour: bool
    points: list[tuple[float, float]]
    cum: list[float]  # metres along points
    steps: list[dict[str, Any]]  # manoeuvres with "at_m": distance along the route where they happen
    fetched_at: float
    seg: int = 0  # last matched segment (the vehicle only moves forward)


@dataclass
class _Slot:
    route: _NavRoute | None = None
    pending: bool = False
    failed_until: float = 0.0
    last_fetch: float = 0.0
    error: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)


_slots: dict[tuple[str, str], _Slot] = {}
_lock = asyncio.Lock()
_last_request = 0.0
_client: httpx.AsyncClient | None = None


# --- geometry -------------------------------------------------------------------------------


def _xy(lat: float, lon: float, lat0: float) -> tuple[float, float]:
    r = 6_371_000.0
    return math.radians(lon) * r * math.cos(math.radians(lat0)), math.radians(lat) * r


def _cumulative(points: list[tuple[float, float]]) -> list[float]:
    cum = [0.0]
    for (alat, alon), (blat, blon) in zip(points, points[1:]):
        cum.append(cum[-1] + haversine_km(alat, alon, blat, blon) * 1000)
    return cum


def _project(route: _NavRoute, lat: float, lon: float) -> tuple[float, float, int]:
    """(distance along the route, distance from it in metres, segment index) of the nearest point,
    searching from a little before the last match so a route that passes a spot twice can't jump back."""
    best = (0.0, float("inf"), route.seg)
    start = max(0, route.seg - 3)
    px, py = _xy(lat, lon, lat)
    for i in range(start, len(route.points) - 1):
        (alat, alon), (blat, blon) = route.points[i], route.points[i + 1]
        ax, ay = _xy(alat, alon, lat)
        bx, by = _xy(blat, blon, lat)
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
        d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
        if d < best[1]:
            best = (route.cum[i] + t * (route.cum[i + 1] - route.cum[i]), d, i)
    return best


def bearing_deg(alat: float, alon: float, blat: float, blon: float) -> float:
    p1, p2 = math.radians(alat), math.radians(blat)
    dl = math.radians(blon - alon)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


# --- OSRM -------------------------------------------------------------------------------------


def _parse(data: dict[str, Any], target: Key, detour: bool) -> _NavRoute:
    best = data["routes"][0]
    points: list[tuple[float, float]] = []
    starts: list[int] = []  # index in points where each step begins
    raw_steps: list[dict[str, Any]] = []
    for leg in best["legs"]:
        for step in leg["steps"]:
            coords = [(lat, lon) for lon, lat in step["geometry"]["coordinates"]]
            joined = bool(points) and bool(coords) and coords[0] == points[-1]  # steps share their joint
            starts.append(len(points) - 1 if joined or not coords else len(points))
            points.extend(coords[1:] if joined else coords)
            raw_steps.append(step)
    if len(points) < 2:
        raise RuntimeError("OSRM returned an empty route")
    cum = _cumulative(points)
    steps = []
    for i, (step, start) in enumerate(zip(raw_steps, starts)):
        m = step["maneuver"]
        kind = m.get("type", "turn")
        last = i == len(raw_steps) - 1
        if kind in ("depart", "arrive") and not (kind == "arrive" and last) and i != 0:
            continue  # via points: OSRM splits the route there, the driver sees nothing
        steps.append(
            {
                "type": kind,
                "modifier": m.get("modifier"),
                "exit": m.get("exit"),
                "name": step.get("name") or "",
                "ref": step.get("ref") or None,
                "lat": round(m["location"][1], 6),
                "lon": round(m["location"][0], 6),
                "at_m": cum[max(0, min(start, len(cum) - 1))],
            }
        )
    return _NavRoute(target=target, detour=detour, points=points, cum=cum, steps=steps, fetched_at=time.monotonic())


async def _fetch(slot: _Slot, coords: list[tuple[float, float]], start_bearing: float | None, target: Key, detour: bool) -> None:
    global _last_request, _client
    try:
        async with _lock:
            wait = MIN_SPACING_S - (time.monotonic() - _last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            _last_request = time.monotonic()
            if _client is None:
                _client = httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "plan-b-navigation"})
            path = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in coords)
            params: dict[str, str] = {"steps": "true", "overview": "false", "geometries": "geojson"}
            if len(coords) > 2:
                params["waypoints"] = f"0;{len(coords) - 1}"  # the rest are via points: one leg, no "arrive"
            if start_bearing is not None:  # don't start with a U-turn
                params["bearings"] = f"{round(start_bearing) % 360},60" + ";" * (len(coords) - 1)
            r = await _client.get(f"{OSRM_URL}/route/v1/driving/{path}", params=params)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "Ok" or not data.get("routes"):
            raise RuntimeError(f"OSRM returned {data.get('code')}")
        slot.route = _parse(data, target, detour)
        slot.error = None
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 - navigation is a nice-to-have; the tablet falls back
        slot.error = f"{type(e).__name__}: {e}"[:200]
        slot.failed_until = time.monotonic() + FAILURE_PAUSE_S
        log.warning("navigation fetch failed: %s", slot.error)
    finally:
        slot.pending = False


def _request(slot: _Slot, state: WorldState, v: Vehicle, target: Key, urgent: bool) -> None:
    """Queue a fetch from the vehicle's position to the target (via the detour if it drives one).

    urgent: a new target or a new detour (fetch now); otherwise (drifted off the route) at most
    once every REFETCH_MIN_S."""
    now = time.monotonic()
    if slot.pending or now < slot.failed_until or (not urgent and now - slot.last_fetch < REFETCH_MIN_S):
        return
    route = leg_route(state, v)
    rest = remaining_points(route, v.path_progress) if route is not None and v.on_road else []
    detour = bool(v.path_avoid) and is_detour(route)
    coords: list[tuple[float, float]] = [(v.lat, v.lon)]
    if detour and len(rest) > 4:
        # sample via points along the rest of the detour (not too close to either end)
        n = len(rest)
        coords += [rest[round(n * k / (VIA_POINTS + 1))] for k in range(1, VIA_POINTS + 1)]
    coords.append(target)
    start_bearing = None
    if len(rest) > 1:
        nxt = next((p for p in rest[1:] if haversine_km(v.lat, v.lon, p[0], p[1]) > 0.02), None)
        if nxt:
            start_bearing = bearing_deg(v.lat, v.lon, nxt[0], nxt[1])
    slot.pending = True
    slot.last_fetch = now
    slot.task = asyncio.get_running_loop().create_task(_fetch(slot, coords, start_bearing, target, detour))


# --- public -------------------------------------------------------------------------------------


def _target(state: WorldState, v: Vehicle) -> dict[str, Any] | None:
    trip = state.trips.get(v.current_trip_id) if v.current_trip_id else None
    if v.status == "to_pickup" and trip:
        kind, place_id = "pickup", trip.pickup_id
    elif v.status in ("with_patient", "loading") and trip:
        kind, place_id = "dropoff", trip.dropoff_id
    elif v.status == "returning" and v.queue and v.queue[0] in state.trips:
        # just delivered (unloading) with the next job queued: it drives there, not back to base
        trip = state.trips[v.queue[0]]
        kind, place_id = "pickup", trip.pickup_id
    elif v.status == "returning":
        kind, place_id = "base", v.base_id
    else:
        return None
    p = state.places.get(place_id)
    if p is None:
        return None
    return {"kind": kind, "place_id": p.id, "name": p.name, "lat": p.lat, "lon": p.lon, "trip_id": trip.id if trip else None}


def navigation(state: WorldState, v: Vehicle) -> dict[str, Any]:
    """What the tablet's banner needs: the next manoeuvres, distance and time to the next stop."""
    target = _target(state, v)
    base: dict[str, Any] = {"vehicle_id": v.id, "sim_time": state.sim_time.isoformat(), "target": target, "steps": []}
    if v.status == "out_of_service":
        return {**base, "mode": "none", "status": "out_of_service"}
    if target is None:
        return {**base, "mode": "none", "status": "no_leg"}

    emergency = bool(target["trip_id"] and state.trips[target["trip_id"]].priority == "emergency")
    straight_m = haversine_km(v.lat, v.lon, target["lat"], target["lon"]) * 1000
    minutes = vehicle_leg_minutes(state, v, target["lat"], target["lon"], emergency) if straight_m > 15 else 0.0
    # Loading, unloading or an operator delay: it sets off when that is over
    start = max(state.sim_time, v.busy_until) if v.busy_until else state.sim_time
    timing = {
        "remaining_s": round(minutes * 60),
        "eta": (start + timedelta(minutes=minutes)).isoformat(),
        "waiting": bool(v.busy_until and v.busy_until > state.sim_time),
    }
    if straight_m <= 15:
        return {**base, **timing, "mode": "flight" if flies(v.type) else "road", "status": "arrived", "remaining_m": 0}

    if flies(v.type):
        # From rest at its base the crew needs the activation time first (app/hems.py): take-off then.
        activating = v.status == "to_pickup" and bool(v.busy_until and v.busy_until > state.sim_time)
        return {
            **base,
            **timing,
            "mode": "flight",
            "status": "ok",
            "remaining_m": round(straight_m),
            "bearing_deg": round(bearing_deg(v.lat, v.lon, target["lat"], target["lon"])),
            **({"takeoff_at": v.busy_until.isoformat()} if activating and v.busy_until else {}),
        }

    tkey = key(target["lat"], target["lon"])
    slot = _slots.setdefault((state.name, v.id), _Slot())
    route = slot.route
    along = off = None
    detour_now = bool(v.path_avoid) and is_detour(leg_route(state, v))
    if route is not None and route.target == tkey:
        along, off, route.seg = _project(route, v.lat, v.lon)
        if route.detour != detour_now:
            _request(slot, state, v, tkey, urgent=True)  # now driving around a closure (or no longer)
        elif off > OFF_ROUTE_M:
            _request(slot, state, v, tkey, urgent=False)  # left the cached route: ask again from here
    else:
        route = None
        _request(slot, state, v, tkey, urgent=True)

    if route is None or along is None:
        status = "pending" if slot.pending else "unavailable"
        return {**base, **timing, "mode": "road", "status": status, "remaining_m": round(straight_m * 1.3), "error": slot.error}

    ahead = [s for s in route.steps if s["at_m"] > along + 5]
    steps = [
        {k: s[k] for k in ("type", "modifier", "exit", "name", "ref", "lat", "lon")} | {"distance_m": round(s["at_m"] - along)}
        for s in ahead[:MAX_STEPS]
    ]
    return {
        **base,
        **timing,
        "mode": "road",
        "status": "ok",
        "detour": route.detour,
        "provider": "osrm",
        "remaining_m": round(max(0.0, route.cum[-1] - along)),
        "off_route_m": round(off or 0.0),
        "steps": steps,
    }

