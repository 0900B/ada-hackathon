"""Live traffic from TomTom: city-wide speed factor (Flow Segment Data v4) and incidents (Incident Details v5).

TomTom takes the API key as a URL parameter, so errors are re-raised WITHOUT the URL:
/health and alerts are public, and the key must never appear there or in logs.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

import httpx

from ..models import Incident, IncidentKind, utcnow
from .traffic import profile_factor

if TYPE_CHECKING:
    from ..state import WorldState

log = logging.getLogger(__name__)

FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
INCIDENTS_URL = "https://api.tomtom.com/traffic/services/5/incidentDetails"

# Points on Ljubljana's main roads (lat, lon); TomTom snaps each to the nearest road segment.
FLOW_POINTS = {
    "ring road north": (46.0880, 14.5300),
    "Dunajska": (46.0700, 14.5120),
    "Celovška": (46.0680, 14.4900),
    "Tržaška": (46.0430, 14.4900),
    "Zaloška": (46.0560, 14.5300),
    "Slovenska": (46.0530, 14.5030),
}
LJUBLJANA_BBOX = "14.35,45.97,14.72,46.16"  # minLon,minLat,maxLon,maxLat (~550 km²; limit is 10,000)
INCIDENT_FIELDS = (
    "{incidents{type,geometry{type,coordinates},properties{id,iconCategory,magnitudeOfDelay,"
    "events{description},from,to,delay,length}}}"
)
# iconCategory -> our incident kind (1 accident, 6 jam, 7 lane closed, 8 road closed, 9 road works)
CATEGORY_KIND: dict[int, IncidentKind] = {1: "accident", 6: "congestion", 7: "congestion", 8: "road_closure", 9: "congestion"}
MAX_INCIDENTS = 40


def tomtom_key() -> str | None:
    return os.getenv("TOMTOM_API_KEY") or None


# --- Daily request budget (protects the free plan's monthly quota) ---------------------

_usage: dict[str, Any] = {"day": None, "flow": 0, "incidents": 0, "routing": 0, "tiles": 0}


def _caps() -> dict[str, int]:
    from .. import config

    return {
        "flow": config.TOMTOM_DAILY_FLOW_CAP,
        "incidents": config.TOMTOM_DAILY_INCIDENT_CAP,
        "routing": config.TOMTOM_DAILY_ROUTING_CAP,
        "tiles": config.TOMTOM_DAILY_TILE_CAP,
    }


def usage() -> dict[str, Any]:
    caps = _caps()
    return {"day": _usage["day"], **{k: f"{_usage[k]}/{cap}" for k, cap in caps.items()}}


def spend(kind: str, n: int) -> None:
    """Count n requests against today's cap, or refuse before making them."""
    today = utcnow().date().isoformat()
    if _usage["day"] != today:
        _usage.update(day=today, flow=0, incidents=0, routing=0, tiles=0)
    cap = _caps()[kind]
    if _usage[kind] + n > cap:
        raise RuntimeError(f"TomTom daily {kind} budget used ({_usage[kind]}/{cap}); using fallback until tomorrow")
    _usage[kind] += n


async def get(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        r = await client.get(url, params={**params, "key": tomtom_key()}, headers={"Accept-Encoding": "gzip"})
    except httpx.HTTPError as e:
        raise RuntimeError(f"TomTom request failed ({type(e).__name__})") from None
    if r.status_code != 200:
        raise RuntimeError(f"TomTom returned HTTP {r.status_code}")  # no URL: it contains the key
    return r.json()


async def fetch_flow(state: WorldState, client: httpx.AsyncClient) -> None:
    """Weighted average of current/free-flow speed across the sample points -> state.traffic_factor."""
    try:
        spend("flow", len(FLOW_POINTS))
        results = await asyncio.gather(
            *(get(client, FLOW_URL, {"point": f"{lat},{lon}", "unit": "kmph"}) for lat, lon in FLOW_POINTS.values()),
            return_exceptions=True,
        )
        samples = []
        for name, res in zip(FLOW_POINTS, results):
            if isinstance(res, BaseException):
                continue
            seg = res.get("flowSegmentData") or {}
            cur, free = seg.get("currentSpeed"), seg.get("freeFlowSpeed")
            if not cur or not free:
                continue
            samples.append(
                {
                    "road": name,
                    "current_kmh": cur,
                    "free_flow_kmh": free,
                    "ratio": round(min(cur / free, 1.0), 2),
                    "confidence": seg.get("confidence", 1.0),
                    "closed": bool(seg.get("roadClosure")),
                }
            )
        if not samples:
            first_error = next((r for r in results if isinstance(r, BaseException)), None)
            raise RuntimeError(str(first_error) if first_error else "TomTom returned no usable flow data")
        weight = sum(s["confidence"] or 0.1 for s in samples)
        factor = sum(s["ratio"] * (s["confidence"] or 0.1) for s in samples) / weight
        state.traffic_factor = round(max(0.35, min(factor, 1.1)), 2)
        state.traffic_source = "tomtom"
        state.traffic_samples = samples
    except Exception:
        # Keep routing sensible while live data is unavailable, then report the failure.
        state.traffic_factor = profile_factor(state.sim_time)
        state.traffic_source = "time-of-day profile (TomTom unavailable)"
        raise


async def fetch_incidents(state: WorldState, client: httpx.AsyncClient) -> None:
    spend("incidents", 1)
    data = await get(
        client,
        INCIDENTS_URL,
        {"bbox": LJUBLJANA_BBOX, "fields": INCIDENT_FIELDS, "language": "en-GB", "timeValidityFilter": "present"},
    )
    fresh: dict[str, Incident] = {}
    for item in data.get("incidents") or []:
        props = item.get("properties") or {}
        category = props.get("iconCategory")
        magnitude = props.get("magnitudeOfDelay") or 0
        kind = CATEGORY_KIND.get(category)
        if kind is None or (kind == "congestion" and magnitude < 2):
            continue  # skip minor jams, fog, rain etc. (weather is handled separately)
        geom = item.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if geom.get("type") == "LineString" and coords:
            lon, lat = coords[len(coords) // 2]
        elif geom.get("type") == "Point" and len(coords) == 2:
            lon, lat = coords
        else:
            continue
        events = props.get("events") or []
        what = events[0].get("description") if events else kind.replace("_", " ")
        where = " → ".join(x for x in (props.get("from"), props.get("to")) if x)
        inc_id = f"TT-{props.get('id', len(fresh))}"[:40]
        fresh[inc_id] = Incident(
            id=inc_id,
            kind=kind,
            description=f"{what}" + (f" ({where})" if where else "") + " [TomTom]",
            lat=lat,
            lon=lon,
            radius_m=max(150.0, min((props.get("length") or 300) / 2, 1000.0)),
            created_at=utcnow(),
            source="live",
            provider="tomtom",
        )
    replace_provider_incidents(state, "tomtom", fresh)


SEVERITY = {"road_closure": 0, "accident": 1, "congestion": 2}


def replace_provider_incidents(state: WorldState, provider: str, fresh: dict[str, Incident]) -> None:
    """Swap in one feed's current incidents; other feeds' and operator-injected incidents stay."""
    kept = dict(sorted(fresh.items(), key=lambda kv: SEVERITY[kv[1].kind])[:MAX_INCIDENTS])
    live = state.feed.incidents  # shared by the live and simulation worlds
    for inc_id in [i for i, inc in live.items() if inc.provider == provider]:
        del live[inc_id]
    live.update(kept)
