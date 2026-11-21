"""Run a fetch function forever on an interval, with timeout, backoff and freshness tracking."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Awaitable, Callable

from ..models import SourceKind, utcnow

if TYPE_CHECKING:
    from ..state import WorldState

log = logging.getLogger(__name__)


async def run_periodic(
    state: WorldState,
    name: str,
    kind: SourceKind,
    interval_s: float,
    fetch: Callable[[], Awaitable[None]],
    timeout_s: float = 15.0,
) -> None:
    status = state.register_source(name, kind, interval_s)
    while True:
        status.last_attempt = utcnow()
        try:
            await asyncio.wait_for(fetch(), timeout=timeout_s)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - a failing feed must never crash the app
            status.consecutive_failures += 1
            status.last_error = f"{type(e).__name__}: {e}"[:300]
            delay = min(interval_s, 5 * 2 ** min(status.consecutive_failures, 6))  # retry sooner than the interval
            log.warning("source %s failed (%s); retrying in %.0fs", name, status.last_error, delay)
        else:
            status.last_success = utcnow()
            status.last_error = None
            status.consecutive_failures = 0
            delay = interval_s
        state.bump()
        await asyncio.sleep(delay)
