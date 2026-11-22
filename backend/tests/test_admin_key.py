"""The demo lock (app/admin_key.py): with ADMIN_KEY set, only requests carrying X-Plan-B-Key can change anything.

Run from backend/:  python tests/test_admin_key.py   (or: python -m pytest tests)
Offline: road routing off, no agent auto-runs, no Claude. The lock reads the env per request, so each
test sets and clears ADMIN_KEY itself; every other suite runs without it (everything open).
"""
from __future__ import annotations

import contextlib
import http.client
import logging
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

os.environ["ROAD_ROUTING"] = "0"
os.environ["AGENT_AUTO"] = "0"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("ADMIN_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import admin_key, config, main  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402

KEY = "demo-Key_0123456789/abcdef"
HEADER = "X-Plan-B-Key"
DETAIL = "Control actions need the admin key (Bypass demo lock)."
ORIGIN = {"Origin": "https://plan-b.example"}
for noisy in ("httpx", "httpx2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
client = TestClient(main.app)  # no `with`: no lifespan, so no background loops
W = main.sim


@contextlib.contextmanager
def locked(key: str | None = KEY):
    old = os.environ.get("ADMIN_KEY")
    if key is None:
        os.environ.pop("ADMIN_KEY", None)
    else:
        os.environ["ADMIN_KEY"] = key
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("ADMIN_KEY", None)
        else:
            os.environ["ADMIN_KEY"] = old


def fresh() -> None:
    seed_world(W, config.RANDOM_SEED, scheduled_day=False)


def assert_locked(r) -> None:
    assert r.status_code == 401, (r.status_code, r.text)
    assert r.json() == {"detail": DETAIL}, r.text
    assert KEY not in r.text and KEY not in str(dict(r.headers))


def test_without_a_key_configured_everything_is_open():
    fresh()
    for blank in (None, "", "   "):
        with locked(blank):
            assert not admin_key.lock_enabled()
            assert client.post("/sim/admin/reset").status_code == 200
            assert client.post("/sim/agent/auto", json={"enabled": False}).status_code == 200
            assert client.get("/sim/state").status_code == 200
            r = client.get("/health")
            assert r.status_code == 200 and r.json()["admin_lock"] is False
            r = client.post("/lock/check")  # nothing to unlock: reports that, same answer with or without a header
            assert r.status_code == 200 and r.json() == {"ok": True, "lock": False}, r.text
            assert client.post("/sim/admin/reset", headers={HEADER: "whatever"}).status_code == 200


def test_control_actions_need_the_key():
    fresh()
    with locked():
        assert admin_key.lock_enabled()
        # every control method, no header / empty / wrong / near misses
        for headers in ({}, {HEADER: ""}, {HEADER: "nope"}, {HEADER: KEY.upper()}, {HEADER: KEY[:-1]}, {HEADER: KEY + "x"}, {HEADER: " "}):
            assert_locked(client.post("/sim/admin/reset", headers=headers))
        assert_locked(client.post("/sim/events", json={"type": "delay", "vehicle_id": "A1", "minutes": 5}))
        assert_locked(client.post("/sim/agent/analyze", json={"question": None}))  # would spend AI tokens
        assert_locked(client.post("/sim/admin/random-incident", json={}))
        assert_locked(client.post("/sim/admin/scenario/surge"))
        assert_locked(client.post("/sim/agent/runs/RUN-0001/approve", json={"option_index": 0}))
        assert_locked(client.post("/live/admin/reset"))
        for method in ("put", "patch", "delete"):  # nothing routes these: the lock answers before routing does
            assert_locked(getattr(client, method)("/sim/events"))
        assert_locked(client.post("/lock/check"))
        assert_locked(client.post("/lock/check", headers={HEADER: "nope"}))
        # legacy unprefixed paths are rewritten to /sim and are locked too
        assert_locked(client.post("/admin/reset"))
        assert_locked(client.post("/agent/analyze", json={}))
        # a 401 changed nothing and started no analysis
        assert client.get("/sim/agent/runs").json() == []


def test_the_key_unlocks():
    fresh()
    with locked():
        h = {HEADER: KEY}
        assert client.post("/sim/admin/reset", headers=h).status_code == 200
        assert client.post("/sim/agent/auto", json={"enabled": False}, headers=h).status_code == 200
        # header name is case-insensitive; surrounding spaces are not part of the key
        assert client.post("/sim/admin/reset", headers={"x-plan-b-key": KEY}).status_code == 200
        assert client.post("/sim/admin/reset", headers={HEADER: f" {KEY} "}).status_code == 200
        # past the lock the request is the app's: an unrouted method is 405, not 401
        assert client.delete("/sim/events", headers=h).status_code == 405
        r = client.post("/lock/check", headers=h)
        assert r.status_code == 200 and r.json() == {"ok": True, "lock": True}, r.text
        assert KEY not in r.text
        # a key with surrounding spaces in the env is the same key
    with locked(f"  {KEY}  "):
        assert client.post("/sim/admin/reset", headers={HEADER: KEY}).status_code == 200


def test_reading_stays_open():
    fresh()
    with locked():
        for path in ("/", "/health", "/sim/state", "/live/state", "/sim/kpis", "/sim/alerts", "/sim/agent/runs", "/openapi.json", "/sim/admin/scenarios"):
            r = client.get(path)
            assert r.status_code == 200, (path, r.status_code, r.text[:200])
        assert client.get("/state").status_code == 200  # legacy path
        assert client.head("/sim/state").status_code != 401  # HEAD is a read (FastAPI answers 405: no HEAD route)
        r = client.get("/health")
        assert r.json()["admin_lock"] is True
        assert KEY not in r.text, "/health says that a lock exists, never the key"


def test_cors_preflight_is_open_and_the_401_is_readable_cross_origin():
    fresh()
    with locked():
        pre = client.options(
            "/sim/admin/reset",
            headers={
                **ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-plan-b-key",
            },
        )
        assert pre.status_code == 200, (pre.status_code, pre.text)
        assert pre.headers["access-control-allow-origin"] == "*"
        assert "x-plan-b-key" in pre.headers["access-control-allow-headers"].lower()
        assert "POST" in pre.headers["access-control-allow-methods"]
        assert client.options("/sim/state").status_code != 401  # a plain OPTIONS is a read too
        # cross-origin POST without the key: 401 with CORS headers, so the browser can read the detail
        r = client.post("/sim/admin/reset", headers=ORIGIN)
        assert_locked(r)
        assert r.headers["access-control-allow-origin"] == "*", dict(r.headers)
        r = client.post("/sim/admin/reset", headers={**ORIGIN, HEADER: "wrong"})
        assert_locked(r)
        assert r.headers["access-control-allow-origin"] == "*"
        # and with the key it goes through, CORS headers too
        r = client.post("/sim/admin/reset", headers={**ORIGIN, HEADER: KEY})
        assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "*"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_sse_stream_passes_through_the_lock():
    """A real server (pure ASGI middleware, no buffering): the SSE stream opens without the key."""
    fresh()
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(main.app, host="127.0.0.1", port=port, lifespan="off", log_level="error", timeout_graceful_shutdown=2)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    with locked():
        thread.start()
        try:
            deadline = time.time() + 15
            while not server.started and time.time() < deadline:
                time.sleep(0.05)
            assert server.started, "test server did not start"
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", "/sim/stream", headers=ORIGIN)  # no key
            resp = conn.getresponse()
            assert resp.status == 200, resp.status
            assert resp.getheader("content-type", "").startswith("text/event-stream")
            assert resp.getheader("access-control-allow-origin") == "*"
            first = resp.readline().decode()  # http.client undoes the chunked encoding
            assert first.startswith("data: {"), first[:80]
            conn.close()
            # over the same real server: a control action without the key is refused, with it accepted
            c2 = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c2.request("POST", "/sim/admin/reset", headers=ORIGIN)
            r2 = c2.getresponse()
            assert r2.status == 401 and DETAIL in r2.read().decode()
            c2.request("POST", "/sim/admin/reset", headers={**ORIGIN, HEADER: KEY})
            r3 = c2.getresponse()
            r3.read()
            assert r3.status == 200, r3.status
            c2.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        t0 = time.time()
        try:
            fn()
            print(f"PASS {name} ({time.time() - t0:.1f}s)")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
