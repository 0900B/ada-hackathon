"""Traffic map tiles from TomTom, proxied so the API key never reaches the browser.

Tiles are cached for two minutes (traffic changes slowly at that scale), zoom is limited, and a
daily cap protects the free plan's quota. Browsers may keep each tile for the rest of its two
minutes (Cache-Control), so reloads and other tabs don't ask again. Any failure, including the
daily cap, returns a transparent tile: the map quietly shows no traffic colours instead of
breaking, and status() says why (the dashboard's status bar shows it).
"""
from __future__ import annotations

import struct
import time
import zlib
from collections import OrderedDict

import httpx

from .fetchers import tomtom

LAYERS = {
    "flow": "https://api.tomtom.com/traffic/map/4/tile/flow/relative0-dark/{z}/{x}/{y}.png",
    "incidents": "https://api.tomtom.com/traffic/map/4/tile/incidents/s0-dark/{z}/{x}/{y}.png",
}
MIN_ZOOM, MAX_ZOOM = 9, 18
TTL_S = 120
CACHE_MAX = 3000
EMPTY_MAX_AGE_S = 60  # browsers re-ask for a transparent (no data / capped) tile after a minute

def _transparent_png() -> bytes:
    """A fully transparent 1x1 RGBA PNG (alpha 0), built rather than pasted so it can't be wrong."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)  # 1x1, 8-bit, RGBA
    pixels = zlib.compress(b"\x00" + b"\x00\x00\x00\x00")  # filter byte + one transparent pixel
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


TRANSPARENT_PNG = _transparent_png()

_cache: OrderedDict[tuple[str, int, int, int], tuple[float, bytes]] = OrderedDict()
stats = {"served": 0, "fetched": 0, "cache_hits": 0, "errors": 0, "refused_over_cap": 0}
_capped_day: str | None = None  # the UTC day the daily tile cap was reached


def available() -> bool:
    return tomtom.tomtom_key() is not None


def status() -> dict:
    """For /health and the snapshot: is the traffic layer live, or paused by the daily cap?"""
    used = tomtom.usage().get("tiles", "0/0")
    return {"available": available(), "capped": _capped_day == tomtom.today(), "used": used, "ttl_s": TTL_S, **stats}


def _max_age(fetched_at: float) -> int:
    """Seconds a browser may keep a tile: what is left of its two minutes in our cache."""
    return max(1, int(TTL_S - (time.monotonic() - fetched_at)))


async def get_tile(client: httpx.AsyncClient | None, layer: str, z: int, x: int, y: int) -> tuple[bytes, bool, int]:
    """Returns (png bytes, is_real_tile, max_age_s for the browser's cache)."""
    global _capped_day
    stats["served"] += 1
    if client is None or layer not in LAYERS or not available() or not (MIN_ZOOM <= z <= MAX_ZOOM):
        return TRANSPARENT_PNG, False, EMPTY_MAX_AGE_S
    k = (layer, z, x, y)
    hit = _cache.get(k)
    if hit and time.monotonic() - hit[0] < TTL_S:
        _cache.move_to_end(k)
        stats["cache_hits"] += 1
        return hit[1], True, _max_age(hit[0])
    stale = (hit[1], True, EMPTY_MAX_AGE_S) if hit else (TRANSPARENT_PNG, False, EMPTY_MAX_AGE_S)
    try:
        tomtom.spend("tiles", 1)
    except RuntimeError:  # today's cap: quietly no traffic colours (an older tile if we still have it)
        stats["refused_over_cap"] += 1
        _capped_day = tomtom.today()
        return stale
    try:
        r = await client.get(LAYERS[layer].format(z=z, x=x, y=y), params={"key": tomtom.tomtom_key()}, timeout=8)
    except Exception:  # noqa: BLE001 - network error: no colours, never an error page
        stats["errors"] += 1
        return stale
    if r.status_code != 200 or not r.content:
        stats["errors"] += 1
        return stale
    stats["fetched"] += 1
    now = time.monotonic()
    _cache[k] = (now, r.content)
    _cache.move_to_end(k)
    while len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)
    return r.content, True, _max_age(now)
