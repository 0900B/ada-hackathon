"""Analyse (operator button, auto-analyse off) must look at what just happened.

Regression for: a scenario was started but not analysed; later the operator delayed a vehicle and
pressed Analyse, and the AI answered about the old scenario (another patient, another situation).
Run: cd backend && python tests/test_analyse_focus.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("ROAD_ROUTING", "0")
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.disable(logging.WARNING)

from app import config, demo, main  # noqa: E402
from app.engine.events import apply_event  # noqa: E402
from app.models import DelayEvent  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402
from app.sim.simulator import tick  # noqa: E402

W = main.sim
CAPTURED: list[tuple] = []


def fake_start_run(state, trigger, focus=None, question=None):
    """Stands in for agent.start_run (no AI): records what the run would be asked about."""
    CAPTURED.append((trigger, focus, question))
    state.analysed_events = len(state.events)  # like the real start_run
    return None


def analyse():
    CAPTURED.clear()
    original = main.agent.start_run
    main.agent.start_run = fake_start_run
    try:
        asyncio.run(main.analyze(None, W))
    finally:
        main.agent.start_run = original
    assert len(CAPTURED) == 1
    return CAPTURED[0]


def fresh_with_scenario(name: str = "stroke_rush_hour"):
    seed_world(W, config.RANDOM_SEED, scheduled_day=False)
    W.auto_analyze = False
    W.calls.enabled = False
    r = demo.run_scenario(W, name)
    assert r["run_id"] is None and W.pending_question, "auto-analyse off: the scenario waits for Analyse"
    return r


def busy_vehicle():
    return next(v for v in W.vehicles.values() if v.current_trip_id and v.status != "out_of_service")


def delay(v, minutes=10):
    return apply_event(W, DelayEvent(type="delay", vehicle_id=v.id, minutes=minutes, note="operator test"))


def test_analyse_right_after_a_scenario_gets_the_scenario():
    fresh_with_scenario()
    trigger, focus, question = analyse()
    assert trigger == "operator" and focus is None
    assert question and question.startswith("Demo scenario:"), question


def test_a_later_event_wins_over_a_stale_scenario():
    fresh_with_scenario()
    tick(W, 120)
    v = busy_vehicle()
    rec = delay(v)
    trigger, focus, question = analyse()
    assert focus is not None and focus.id == rec.id, (focus, rec.id)
    assert "Demo scenario" not in (question or ""), question
    assert question.startswith("Focus on"), question  # the delay is the focus; the scenario only context
    assert W.pending_question is None, "the stale scenario description is dropped"


def test_several_new_events_are_listed_together():
    fresh_with_scenario()
    analyse()  # the scenario has been looked at
    vs = [v for v in W.vehicles.values() if v.current_trip_id][:2]
    assert len(vs) == 2
    r1, r2 = delay(vs[0], 10), delay(vs[1], 15)
    _, focus, question = analyse()
    assert focus.id == r2.id
    assert "Focus on the newest event" in question and r1.summary in question, question  # r2 is the focus itself


def test_routine_calls_alone_give_a_plain_review():
    fresh_with_scenario()
    analyse()
    W.calls.enabled = True
    W.calls.next_at, W.calls.paused_until = W.sim_time, None  # scenarios pause the call stream
    before = len(W.events)
    main.take_calls(W)  # one generated call
    assert len(W.events) > before and W.events[-1].generated
    _, focus, question = analyse()
    assert focus is None and question is None, (focus, question)


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
