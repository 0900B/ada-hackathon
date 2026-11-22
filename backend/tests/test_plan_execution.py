"""Approved plans are executed as shown: the vehicles do the jobs, in the order and at the times the
option said, even if the world moved on between the analysis and the approval.

Run from backend/:  python tests/test_plan_execution.py   (or: python -m pytest tests)
Offline: road routing off, no automatic agent runs, no Claude. Options are hand-written (like a
model would write them) or come from the engine fallback, and go through the real runner._finish
and the real approve endpoint; then the simulator is ticked and every pickup is traced.
"""
from __future__ import annotations

import logging
import os
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ["ROAD_ROUTING"] = "0"
os.environ["AGENT_AUTO"] = "0"
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, main  # noqa: E402
from app.agent import runner  # noqa: E402
from app.engine.actions import assign_trip, detach_trip  # noqa: E402
from app.engine.projection import project_all  # noqa: E402
from app.models import AgentRun, PlanStep, Recommendation, RecommendationOption, Trip, utcnow  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402
from app.sim.simulator import tick  # noqa: E402

for noisy in ("httpx", "httpx2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
client = TestClient(main.app)  # no `with`: no lifespan, so no background loops; we tick by hand
W = main.sim


DAY = datetime(2026, 11, 23, 9, 0, tzinfo=ZoneInfo("Europe/Ljubljana"))  # fixed clock, by day: the helicopter flies 08:00-16:30


def fresh() -> None:
    seed_world(W, config.RANDOM_SEED, scheduled_day=True, start=DAY)  # these tests plan around a pre-planned day
    W.auto_analyze = False


def clear(vehicle_id: str) -> None:
    """Empty a vehicle's day so a test can give it exactly the jobs it needs."""
    v = W.vehicles[vehicle_id]
    for tid in ([v.current_trip_id] if v.current_trip_id else []) + list(v.queue):
        t = W.trips[tid]
        detach_trip(W, t)
        t.status = "unassigned"
    v.queue, v.current_trip_id, v.status = [], None, "idle"


def only_in_service(*vehicle_ids: str) -> None:
    """These vehicles, with empty days, are the whole fleet."""
    for v in W.vehicles.values():
        clear(v.id)
        if v.id not in vehicle_ids:
            v.status = "out_of_service"


def new_trip(tid: str, priority: str, pickup: str, dropoff: str = "ukc", needs: str = "seated", ready_min: float = 0) -> Trip:
    t = Trip(
        id=tid,
        patient=f"P-{tid}",
        priority=priority,  # type: ignore[arg-type]
        needs=needs,  # type: ignore[arg-type]
        pickup_id=pickup,
        dropoff_id=dropoff,
        pickup_after=W.sim_time + timedelta(minutes=ready_min),
        due_by=W.sim_time + timedelta(minutes=ready_min + 90),
    )
    W.trips[tid] = t
    return t


def checked_run(*options: list[PlanStep], recommended: int = 0, engine: str = "claude") -> AgentRun:
    """A finished run whose options went through the real runner._finish (engine re-check)."""
    rec = Recommendation(
        situation="test",
        options=[RecommendationOption(title=f"Option {i + 1}", summary="", steps=s, pros=[], cons=[]) for i, s in enumerate(options)],
        recommended_index=recommended,
        reasoning="test",
    )
    run = AgentRun(id=W.new_id("RUN"), trigger="test", started_at=utcnow())
    W.agent_runs.append(run)
    project_all(W)
    runner._finish(W, run, rec, engine=engine)
    return run


def approve(run: AgentRun, index: int = 0):
    return client.post(f"/sim/agent/runs/{run.id}/approve", json={"option_index": index})


class Tracer:
    """Ticks the simulator and records every pickup: (time, vehicle, trip), in order."""

    def __init__(self) -> None:
        self.pickups: list[tuple] = []
        self.prev = {t.id: t.status for t in W.trips.values()}

    def run(self, minutes: float, until=None, step_s: float = 15) -> bool:
        for _ in range(int(minutes * 60 / step_s)):
            tick(W, step_s)
            project_all(W)
            for t in W.trips.values():
                if self.prev.get(t.id) not in ("onboard", "completed") and t.status == "onboard":
                    self.pickups.append((W.sim_time, t.vehicle_id, t.id))
                self.prev[t.id] = t.status
            if until and until():
                return True
        return False

    def order(self, vehicle_id: str) -> list[str]:
        return [p[2] for p in self.pickups if p[1] == vehicle_id]

    def picked(self, trip_id: str):
        return next((p for p in self.pickups if p[2] == trip_id), None)


def step(trip_id: str, vehicle_id: str, position=None, interrupt=False, dropoff_id=None) -> PlanStep:
    return PlanStep(trip_id=trip_id, vehicle_id=vehicle_id, position=position, interrupt_current=interrupt, dropoff_id=dropoff_id)


# --- An emergency never waits behind work the vehicle has not started ---------------------------


def test_emergency_step_goes_first():
    """Old behaviour: 'A2 position 0' queued the stroke patient behind A2's unstarted urgent job, so A2
    drove to Vrhnika first and collected the emergency about an hour later."""
    fresh()
    only_in_service("A2")
    far = new_trip("TX-U", "urgent", "home_vrhnika")
    assign_trip(W, far.id, "A2")
    tracer = Tracer()
    tracer.run(1)
    assert W.vehicles["A2"].current_trip_id == far.id and far.status == "en_route_pickup"

    stroke = new_trip("TX-E", "emergency", "home_moste", needs="stretcher")
    run = checked_run([step(stroke.id, "A2", position=0)])
    opt = run.recommendation.options[0]
    assert opt.feasible, opt.errors
    r = approve(run)
    assert r.status_code == 200, r.text
    t0 = W.sim_time
    assert tracer.run(90, until=lambda: stroke.status == "onboard")
    assert tracer.order("A2")[0] == stroke.id, tracer.pickups
    assert (tracer.picked(stroke.id)[0] - t0).total_seconds() <= 15 * 60
    detail = opt.step_details[0]  # and the option said so
    assert detail["action"] == "divert" and detail["after_trip_ids"] == [], detail
    assert opt.steps[0].interrupt_current, "the stored step says what happens: A2 turns around"


# --- What an option says is what the vehicles do ------------------------------------------------


def test_step_details_match_the_executed_order():
    """Steps on one vehicle interact: here step 2 ('position 0') goes before step 1. The option now
    says so in step_details, and the vehicle does exactly that."""
    fresh()
    only_in_service("T5")
    a = new_trip("TX-A", "urgent", "home_bezigrad")
    b = new_trip("TX-B", "urgent", "home_moste")
    run = checked_run([step(a.id, "T5"), step(b.id, "T5", position=0)])
    opt = run.recommendation.options[0]
    details = {d["trip_id"]: d for d in opt.step_details}
    assert set(details) == {a.id, b.id}, opt.step_details
    assert details[b.id]["order"] == 1 and details[a.id]["order"] == 2 and details[a.id]["after_trip_ids"] == [b.id]
    assert all(d["text"].startswith("T5 ") for d in opt.step_details)
    r = approve(run)
    assert r.status_code == 200, r.text
    assert r.json()["decision"]["executed"] == [d["text"] for d in opt.step_details]
    tracer = Tracer()
    assert tracer.run(120, until=lambda: a.status in ("onboard", "completed"))
    assert tracer.order("T5")[:2] == [b.id, a.id], tracer.pickups
    for d in opt.step_details:  # collected when promised (the simulator and the projection agree)
        got = tracer.picked(d["trip_id"])[0]
        assert abs((got - d["pickup_at"]).total_seconds()) <= 120, (d["trip_id"], got, d["pickup_at"])


def _van_with_current_and_next(ready_next_min: float):
    """T5 drives to C (current) and has B queued; X is unassigned. All urgent, seated."""
    only_in_service("T5", "T4")
    c = new_trip("TX-C", "urgent", "zd_center", "ukc")
    b = new_trip("TX-B", "urgent", "home_moste", "ukc", ready_min=ready_next_min)
    x = new_trip("TX-X", "urgent", "home_bezigrad", "ukc")
    assign_trip(W, c.id, "T5")
    assign_trip(W, b.id, "T5")
    tracer = Tracer()
    tracer.run(0.5)
    assert W.vehicles["T5"].current_trip_id == c.id
    return c, b, x, tracer


def test_approval_replays_the_checked_order_after_the_vehicle_moved_on():
    """The plan put X before B ('position 0' = right after the current trip C). Before the operator
    approved, T5 finished C and started driving to B. Old behaviour: position 0 now meant 'after B',
    so X silently waited for B. Now the step is anchored to B: T5 turns around for X."""
    fresh()
    c, b, x, tracer = _van_with_current_and_next(ready_next_min=40)
    run = checked_run([step(x.id, "T5", position=0)])
    opt = run.recommendation.options[0]
    assert tracer.run(60, until=lambda: W.vehicles["T5"].current_trip_id == b.id)
    assert b.status == "en_route_pickup"
    r = approve(run)
    assert r.status_code == 200, r.text
    assert tracer.run(90, until=lambda: x.status in ("onboard", "completed"))
    order = tracer.order("T5")
    assert order.index(x.id) == 1 and b.id not in order[:2], order  # C, then X, then B
    assert opt.steps[0].before_trip_id == b.id and opt.step_details[0]["after_trip_ids"] == [c.id]


def test_keeping_a_dispatch_that_already_happened_is_not_an_error():
    """Seen on the deployment: 'keep the engine's dispatch: A1 to the cardiac arrest' was recommended,
    A1 picked the patient up while Claude was still writing (A1 was 1 min away), and the option became
    infeasible ('TR-004 is onboard and cannot be reassigned'): Approve answered 409. A step that only
    confirms what the unit already did is satisfied, and the option says so."""
    fresh()
    only_in_service("A1", "T5")
    arrest = new_trip("TX-CA", "emergency", "home_moste", needs="stretcher")
    fall = new_trip("TX-F", "urgent", "home_bezigrad")
    assign_trip(W, arrest.id, "A1")
    assign_trip(W, fall.id, "T5")
    keep = [step(arrest.id, "A1"), step(fall.id, "T5")]
    run = checked_run(keep)
    assert run.recommendation.options[0].feasible
    tracer = Tracer()
    assert tracer.run(30, until=lambda: arrest.status == "onboard")  # meanwhile A1 picks the patient up
    run2 = checked_run(keep)  # the same option checked again now
    opt = run2.recommendation.options[0]
    assert opt.feasible, opt.errors
    detail = next(d for d in opt.step_details if d["trip_id"] == arrest.id)
    assert detail["action"] == "onboard" and "already has" in detail["text"], detail
    r = approve(run)  # the option approved as shown earlier
    assert r.status_code == 200, r.text
    assert arrest.vehicle_id == "A1" and arrest.status == "onboard" and fall.vehicle_id == "T5"


def test_out_of_date_plan_is_refused_with_the_reason():
    """Same plan, but meanwhile T5 has loaded B: it can't turn around any more, so X would be collected
    much later than shown. Old behaviour: approved (200) and X silently waited. Now: 409 with the reason."""
    fresh()
    c, b, x, tracer = _van_with_current_and_next(ready_next_min=0)
    run = checked_run([step(x.id, "T5", position=0)])
    assert tracer.run(60, until=lambda: b.status == "onboard")
    r = approve(run)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "out of date" in detail and f"{x.id} would now be picked up at" in detail and "instead of" in detail, detail
    assert x.status == "unassigned" and x.vehicle_id is None, "nothing applied"
    assert run.status == "done"


# --- Later events and plans never push an approved emergency back -------------------------------


def test_later_plans_never_divert_a_vehicle_from_an_emergency():
    """Old behaviour: a later urgent call next to A2 got 'A2 divert now' from the engine, so A2 turned
    away from the stroke patient it had been sent to."""
    fresh()
    only_in_service("A2", "T3")
    stroke = new_trip("TX-E", "emergency", "home_polje", needs="stretcher")
    run = checked_run([step(stroke.id, "A2")])
    assert approve(run).status_code == 200
    tracer = Tracer()
    tracer.run(1)
    assert W.vehicles["A2"].current_trip_id == stroke.id
    v = W.vehicles["A2"]
    W.places["here"] = W.places["zd_center"].model_copy(update={"id": "here", "lat": v.lat, "lon": v.lon})
    urgent = new_trip("TX-U", "urgent", "here", needs="stretcher")
    later = runner._engine_recommendation(W, None, "test")
    run2 = AgentRun(id=W.new_id("RUN"), trigger="test", started_at=utcnow())
    W.agent_runs.append(run2)
    runner._finish(W, run2, later, engine="engine_fallback")
    for opt in later.options:
        assert not any(s.vehicle_id == "A2" and s.interrupt_current for s in opt.steps), opt.steps
    if later.options:
        assert approve(run2).status_code == 200
    assert W.vehicles["A2"].current_trip_id == stroke.id
    assert tracer.run(60, until=lambda: stroke.status == "onboard")
    assert tracer.order("A2")[0] == stroke.id, tracer.pickups
    assert urgent.id not in tracer.order("A2")[:1]


def test_nothing_is_queued_ahead_of_a_higher_priority_trip():
    fresh()
    only_in_service("T5")
    u = new_trip("TX-U", "urgent", "home_bezigrad")
    s = new_trip("TX-S", "scheduled", "home_moste")
    assign_trip(W, u.id, "T5")
    run = checked_run([step(s.id, "T5", position=0)])
    opt = run.recommendation.options[0]
    assert opt.feasible is False and "higher priority goes first" in opt.errors[0], opt.errors
    assert approve(run).status_code != 200


# --- The recommendation itself ------------------------------------------------------------------


def test_recommended_option_is_always_feasible():
    fresh()
    only_in_service("T5", "A1")
    t = new_trip("TX-S", "emergency", "home_moste", needs="stretcher")
    run = checked_run([step(t.id, "T5")], [step(t.id, "A1")], recommended=0)  # a van can't take an emergency
    rec = run.recommendation
    assert rec.options[0].feasible is False and rec.options[1].feasible is True
    assert rec.recommended_index == 1


def test_engine_fallback_option_says_what_happens():
    fresh()
    only_in_service("T5", "T4", "A3")
    t = new_trip("TX-S", "urgent", "home_siska")
    rec = runner._engine_recommendation(W, None, "test")
    opt = rec.options[0]
    assert t.id in [s.trip_id for s in opt.steps]
    assert "picks up" in opt.summary and opt.steps[0].vehicle_id in opt.summary, opt.summary


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
