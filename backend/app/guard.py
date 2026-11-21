"""Claude usage guard for the live demo: one in-memory limiter for every path that calls Claude.

Counted: each AI analysis that reaches Claude (operator, event, call, field message, scenario,
stale-plan re-analysis) and each field message Claude parses. Shared by both worlds. Limits:
CLAUDE_MAX_PER_5MIN (default 12) per rolling CLAUDE_WINDOW_S (default 300 s) and
CLAUDE_MAX_PER_DAY (default 300) per UTC day. One analysis may make several API requests (tool
turns, at most AGENT_MAX_TURNS) but counts once. In memory: a restart resets the counts.

Over the limit: an operator's analysis falls back to the engine's plan with a note, automatic
analyses are skipped, and field messages get HTTP 429 with a Slovenian and English explanation.
"""
from __future__ import annotations

import math
import os
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Callable

# Short reasons (run.error; the dashboard adds ": showing the engine's own plan") and the full notes
LIMIT_REASON = "AI limit reached"
SLOW_REASON = "The AI took too long"
LIMIT_NOTE = f"{LIMIT_REASON}: showing the engine's plan"
SLOW_NOTE = f"{SLOW_REASON}: showing the engine's plan"


class ClaudeGuard:
    def __init__(
        self,
        per_window: int | None = None,
        window_s: float | None = None,
        per_day: int | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.per_window = per_window if per_window is not None else int(os.getenv("CLAUDE_MAX_PER_5MIN", "12"))
        self.window_s = window_s if window_s is not None else float(os.getenv("CLAUDE_WINDOW_S", "300"))
        self.per_day = per_day if per_day is not None else int(os.getenv("CLAUDE_MAX_PER_DAY", "300"))
        self.clock = clock
        self.reset()

    def reset(self) -> None:
        self._recent: deque[float] = deque()
        self._day: str | None = None
        self._today = 0
        self.used = {"analysis": 0, "message": 0}
        self.refused = {"analysis": 0, "message": 0, "auto_skipped": 0}

    def _roll(self, now: float) -> None:
        while self._recent and now - self._recent[0] >= self.window_s:
            self._recent.popleft()
        day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        if day != self._day:
            self._day, self._today = day, 0

    def available(self) -> bool:
        """Would one more Claude call be allowed now? (Counts nothing.)"""
        self._roll(self.clock())
        return len(self._recent) < self.per_window and self._today < self.per_day

    def try_acquire(self, kind: str) -> bool:
        """Count one Claude call of this kind ("analysis" or "message"), or refuse it."""
        if not self.available():
            self.refused[kind] = self.refused.get(kind, 0) + 1
            return False
        now = self.clock()
        self._recent.append(now)
        self._today += 1
        self.used[kind] = self.used.get(kind, 0) + 1
        return True

    def skipped_auto(self) -> None:
        self.refused["auto_skipped"] += 1

    def retry_after_s(self) -> int:
        """Seconds until the next call would be allowed (0 if allowed now)."""
        now = self.clock()
        self._roll(now)
        waits = [0.0]
        if self._today >= self.per_day:
            midnight = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            waits.append((midnight + timedelta(days=1)).timestamp() - now)
        if len(self._recent) >= self.per_window:  # (a limit of 0 switches Claude off: a full window)
            waits.append(self._recent[0] + self.window_s - now if self._recent else self.window_s)
        return max(0, math.ceil(max(waits)))

    def status(self) -> dict:
        self._roll(self.clock())
        return {
            "limited": not self.available(),
            "last_window": len(self._recent),
            "per_window": self.per_window,
            "window_s": self.window_s,
            "today": self._today,
            "per_day": self.per_day,
            "retry_after_s": self.retry_after_s(),
            "used": dict(self.used),
            "refused": dict(self.refused),
        }


GUARD = ClaudeGuard()


def message_limit_detail(retry_after_s: int) -> str:
    """The 429 text for a field message: Slovenian first (the crews' language), then English."""
    minutes = max(1, math.ceil(retry_after_s / 60))
    when_sl = f"čez {minutes} min" if minutes < 120 else "jutri"
    when_en = f"in {minutes} min" if minutes < 120 else "tomorrow"
    return (
        f"Dosežena je omejitev uporabe AI: sporočilo ni bilo obdelano. Uporabite gumbe za dogodke ali poskusite znova {when_sl}. / "
        f"AI limit reached: the message was not processed. Use the event buttons or try again {when_en}."
    )
