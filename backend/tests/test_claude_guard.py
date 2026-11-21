"""Claude cost/abuse guard and the analysis deadline (app/guard.py, agent/runner.py).

No real Claude: a fake client stands in (fast, slow, or must-not-be-called).
Run: cd backend && python tests/test_claude_guard.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("ROAD_ROUTING", "0")
os.environ["ANTHROPIC_API_KEY"] = "test-key-not-used"  # agent "enabled"; every call goes to the fake client
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.disable(logging.WARNING)

from fastapi import HTTPException  # noqa: E402

from app import config, guard, main  # noqa: E402
from app.agent import runner  # noqa: E402
from app.agent.messages import FieldMessage  # noqa: E402
from app.guard import GUARD, LIMIT_NOTE, LIMIT_REASON, SLOW_NOTE, SLOW_REASON, ClaudeGuard  # noqa: E402
from app.models import DelayEvent  # noqa: E402
from app.engine.events import apply_event  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402

W = main.sim


class FakeClient:
    """Stands in for anthropic.AsyncAnthropic: `delay` seconds per request, then a final answer."""

    def __init__(self, delay: float = 0.0, forbid: bool = False) -> None:
        self.delay, self.forbid = delay, forbid
        self.calls = 0
        self.cancelled = False
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        assert not self.forbid, "Claude must not be called"
        self.calls += 1
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        answer = {"situation": "Test", "options": [], "recommended_option": 1, "reasoning": "Nothing to do.", "notifications": []}
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0),
            content=[SimpleNamespace(type="text", text=json.dumps(answer))],
            stop_reason="end_turn",
        )


def use(client: FakeClient) -> None:
    runner._get_client = lambda: client  # type: ignore[assignment]
    runner._client = None


def fresh(per_window: int = 12, per_day: int = 300) -> None:
    seed_world(W, config.RANDOM_SEED, scheduled_day=False)
    W.auto_analyze = False
    GUARD.reset()
    GUARD.per_window, GUARD.per_day = per_window, per_day


async def run_and_wait(trigger: str = "operator"):
    run = runner.start_run(W, trigger=trigger)
    if run is None:
        return None
    await asyncio.wait_for(runner._tasks[runner._task_key(W, run.id)], timeout=10)
    return run


# --- The limiter itself --------------------------------------------------------------------


def test_window_and_day_limits():
    now = [1_000_000.0]
    g = ClaudeGuard(per_window=3, window_s=300, per_day=5, clock=lambda: now[0])
    assert all(g.try_acquire("analysis") for _ in range(3))
    assert not g.try_acquire("message") and g.refused["message"] == 1
    assert 0 < g.retry_after_s() <= 300
    now[0] += 301  # the window rolls on
    assert g.try_acquire("message") and g.try_acquire("analysis")
    assert not g.try_acquire("analysis")  # 5 today: the day cap holds although the window has room
    assert g.retry_after_s() > 300  # until the next UTC day
    s = g.status()
    assert s["limited"] and s["today"] == 5 and s["used"] == {"analysis": 4, "message": 1}, s


def test_limits_from_env_defaults():
    g = ClaudeGuard()
    assert (g.per_window, g.window_s, g.per_day) == (
        int(os.getenv("CLAUDE_MAX_PER_5MIN", "12")),
        float(os.getenv("CLAUDE_WINDOW_S", "300")),
        int(os.getenv("CLAUDE_MAX_PER_DAY", "300")),
    )


# --- Analyses --------------------------------------------------------------------------------


def test_analysis_within_the_limit_uses_claude_and_counts():
    fresh()
    client = FakeClient()
    use(client)
    run = asyncio.run(run_and_wait())
    assert run.engine == "claude" and client.calls == 1, (run.engine, run.error)
    assert GUARD.status()["used"]["analysis"] == 1


def test_operator_analysis_over_the_limit_shows_the_engine_plan():
    fresh(per_window=1)
    use(FakeClient())
    asyncio.run(run_and_wait())  # uses the only slot
    use(FakeClient(forbid=True))
    run = asyncio.run(run_and_wait())
    assert run is not None and run.engine == "engine_fallback", run
    assert run.error == LIMIT_REASON, run.error
    assert run.recommendation.reasoning.startswith(LIMIT_NOTE), run.recommendation.reasoning
    assert GUARD.status()["refused"]["analysis"] == 1


def test_automatic_analyses_are_skipped_over_the_limit():
    fresh(per_window=1)
    use(FakeClient())
    asyncio.run(run_and_wait())
    use(FakeClient(forbid=True))
    runs_before = len(W.agent_runs)
    for trigger in ("event:EV-1", "call:EV-2", "message", "scenario:surge", "stale:RUN-1"):
        assert asyncio.run(run_and_wait(trigger)) is None, trigger
    assert len(W.agent_runs) == runs_before
    assert GUARD.status()["refused"]["auto_skipped"] == 5


def test_event_with_auto_analyse_on_and_limit_reached_still_applies():
    fresh(per_window=0)
    use(FakeClient(forbid=True))
    W.auto_analyze = True
    v = next(iter(W.vehicles))

    async def post():
        return await main.post_event(DelayEvent(type="delay", vehicle_id=v, minutes=10), W)

    record = asyncio.run(post())
    assert record.type == "delay" and not any(r.status == "running" for r in W.agent_runs)


def test_without_a_key_nothing_is_counted_or_skipped():
    fresh(per_window=0)
    key = os.environ.pop("ANTHROPIC_API_KEY")
    try:
        run = asyncio.run(run_and_wait("event:EV-1"))  # engine-only runs cost nothing: not skipped
        assert run is not None and run.engine == "engine_fallback" and run.error == "ANTHROPIC_API_KEY is not set"
        assert GUARD.status()["refused"] == {"analysis": 0, "message": 0, "auto_skipped": 0}
    finally:
        os.environ["ANTHROPIC_API_KEY"] = key


# --- Field messages ------------------------------------------------------------------------------


def test_message_over_the_limit_is_429_in_slovenian_and_english():
    fresh(per_window=0)
    use(FakeClient(forbid=True))

    async def post():
        return await main.post_message(FieldMessage(text="Vozilo je obstalo."), W)

    try:
        asyncio.run(post())
        raise AssertionError("expected HTTP 429")
    except HTTPException as e:
        assert e.status_code == 429, e.status_code
        assert "omejitev" in e.detail and "AI limit reached" in e.detail, e.detail
        assert int(e.headers["Retry-After"]) >= 0
    assert GUARD.status()["refused"]["message"] == 1


# --- Slow Claude ---------------------------------------------------------------------------------


def test_slow_claude_falls_back_after_the_deadline():
    fresh()
    client = FakeClient(delay=30)
    use(client)
    old = config.AGENT_TIMEOUT_S
    config.AGENT_TIMEOUT_S = 0.3
    try:
        run = asyncio.run(run_and_wait())
    finally:
        config.AGENT_TIMEOUT_S = old
    assert run.engine == "engine_fallback" and run.error == SLOW_REASON, (run.engine, run.error)
    assert run.recommendation.reasoning.startswith(SLOW_NOTE), run.recommendation.reasoning
    assert client.cancelled, "the Claude request must be cancelled"
    assert run.status == "done"


def test_health_shows_claude_usage():
    fresh(per_window=7, per_day=99)
    h = main.health()["claude"]
    assert h["per_window"] == 7 and h["per_day"] == 99 and h["last_window"] == 0 and h["enabled"] is True, h


def test_limit_detail_wording():
    assert "čez 3 min" in guard.message_limit_detail(150) and "in 3 min" in guard.message_limit_detail(150)
    assert "jutri" in guard.message_limit_detail(10 * 3600)


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
