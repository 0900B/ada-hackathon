"""Demo lock: with ADMIN_KEY set, only clients that send `X-Plan-B-Key: <key>` can change anything.

During the live pitch the URL is on a screen; nobody who sees it may reset the simulation, inject
failures, approve plans or spend AI tokens. Reading stays open: GET/HEAD/OPTIONS (state, the SSE
stream, health, tiles, CORS preflight) never need the key. Every other method does (POST, PUT, PATCH,
DELETE), with no exemptions: crew phones and tablets are our devices and carry the key too.

- ADMIN_KEY unset or empty: no lock, everything is open (local dev, tests, CI).
- The key is read from the environment on every request (a dict lookup), so a test can switch it.
- Compared in constant time (hmac.compare_digest). The key is never logged, echoed or put in /health;
  /health only says whether a lock is configured (`admin_lock`).
- POST /lock/check answers {"ok": true, "lock": <bool>} when the request would be allowed, else 401:
  the frontend uses it to tell a person at once that a typed key is wrong. It changes nothing.

Pure ASGI (not BaseHTTPMiddleware), like LegacyPathsToSim in main.py, so SSE streams pass through
untouched. Register it BEFORE CORSMiddleware so it sits inside it: the 401 then still gets CORS
headers and the browser can read the detail.
"""
from __future__ import annotations

import hmac
import os

from starlette.responses import JSONResponse

HEADER = b"x-plan-b-key"  # ASGI header names are lowercase bytes
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CHECK_PATH = "/lock/check"
LOCKED_DETAIL = "Control actions need the admin key (Plan B demo lock)."


def _key() -> bytes | None:
    key = os.environ.get("ADMIN_KEY", "").strip()
    return key.encode("utf-8") if key else None


def lock_enabled() -> bool:
    """Is a key configured? (For /health: never the key itself.)"""
    return _key() is not None


def _sent_key(scope) -> bytes:
    for name, value in scope.get("headers", ()):
        if name == HEADER:
            return value.strip()
    return b""


class AdminKeyLock:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        key = _key()
        method = scope["method"].upper()
        is_check = method == "POST" and scope["path"] == CHECK_PATH
        if key is not None and (method not in SAFE_METHODS or is_check):
            if not hmac.compare_digest(_sent_key(scope), key):
                await JSONResponse({"detail": LOCKED_DETAIL}, status_code=401)(scope, receive, send)
                return
        if is_check:
            await JSONResponse({"ok": True, "lock": key is not None})(scope, receive, send)
            return
        await self.app(scope, receive, send)
