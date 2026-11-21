"""Traffic tile proxy: browser cache lifetime and the daily cap degrading quietly (app/tiles.py).

No network: a fake HTTP client returns a PNG. Run: cd backend && python tests/test_tiles.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("ROAD_ROUTING", "0")
os.environ["TOMTOM_API_KEY"] = "test-key-not-used"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.disable(logging.WARNING)

from app import config, main, tiles  # noqa: E402
from app.fetchers import tomtom  # noqa: E402

PNG = b"\x89PNG-fake-tile"


class FakeHTTP:
    def __init__(self) -> None:
        self.calls = 0

    async def get(self, url, params=None, timeout=None):
        self.calls += 1
        assert params and params.get("key"), "the key goes to TomTom only"
        return SimpleNamespace(status_code=200, content=PNG)


def fresh(cap: int) -> FakeHTTP:
    tiles._cache.clear()
    tiles._capped_day = None
    for k in tiles.stats:
        tiles.stats[k] = 0
    tomtom._usage.update(day=None, tiles=0)
    config.TOMTOM_DAILY_TILE_CAP = cap
    return FakeHTTP()


def test_fresh_tile_is_cached_for_its_two_minutes():
    http = fresh(cap=10)
    body, real, max_age = asyncio.run(tiles.get_tile(http, "flow", 14, 8900, 5800))
    assert body == PNG and real and 110 <= max_age <= tiles.TTL_S, max_age
    body, real, max_age2 = asyncio.run(tiles.get_tile(http, "flow", 14, 8900, 5800))
    assert http.calls == 1 and real and max_age2 <= max_age, (http.calls, max_age2)  # served from our cache


def test_cap_reached_gives_a_transparent_tile_and_says_so():
    http = fresh(cap=1)
    asyncio.run(tiles.get_tile(http, "flow", 14, 1, 1))
    body, real, max_age = asyncio.run(tiles.get_tile(http, "flow", 14, 2, 2))  # over today's cap
    assert body == tiles.TRANSPARENT_PNG and not real and max_age == tiles.EMPTY_MAX_AGE_S
    assert http.calls == 1, "no request to TomTom over the cap"
    s = tiles.status()
    assert s["capped"] is True and s["used"] == "1/1" and s["refused_over_cap"] == 1, s
    assert main.health()["traffic_tiles"]["capped"] is True


def test_endpoint_sets_cache_control():
    fresh(cap=10)
    main.HTTP = FakeHTTP()  # the proxy's shared client
    resp = asyncio.run(main.traffic_tile("flow", 14, 3, 3))
    cc = resp.headers["cache-control"]
    assert cc.startswith("public, max-age=") and 110 <= int(cc.split("=")[1]) <= tiles.TTL_S, cc
    resp = asyncio.run(main.traffic_tile("nope", 14, 3, 3))  # unknown layer: transparent, short cache
    assert resp.body == tiles.TRANSPARENT_PNG and resp.headers["cache-control"] == f"public, max-age={tiles.EMPTY_MAX_AGE_S}"


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception:
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
