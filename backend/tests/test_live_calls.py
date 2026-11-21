"""Live-calls mode (the default): no pre-planned day, a stream of calls dispatched at once.

Run from backend/:  python tests/test_live_calls.py   (or: python -m pytest tests)
Offline: road routing off, no Claude. Analyses are never really started here (start_run is
replaced by a recorder), so the tests can check exactly when one *would* start.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import time
import traceback
from datetime import timedelta
from pathlib import Path

os.environ["ROAD_ROUTING"] = "0"
os.environ["AGENT_AUTO"] = "0"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("SCHEDULED_DAY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, demo, main  # noqa: E402
from app.agent import runner  # noqa: E402
from app.engine.projection import project_all, route_trip_ids  # noqa: E402
from app.geo import haversine_km  # noqa: E402
from app.sim import calls  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402
from app.sim.simulator import tick  # noqa: E402
from app.state import WorldState  # noqa: E402

for noisy in ("httpx", "httpx2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
client = TestClient(main.app)
W = main.sim
STARTED: list[str] = []


def _record_start(state, trigger, focus=None, question=None):  # stands in for agent.start_run
    STARTED.append(trigger)
    return None


def live() -> None:
    seed_world(W, config.RANDOM_SEED, scheduled_day=False)
    W.auto_analyze = False
    W.calls.enabled, W.calls.per_hour = True, config.CALLS_PER_HOUR


def run_calls(hours: float, step_s: float = 30, each=None) -> list:
    """Tick the world like the app does (tick, take calls, project) and collect the call records."""
    out = []
    original = main.agent.start_run
    main.agent.start_run = _record_start
    try:
        for _ in range(int(hours * 3600 / step_s)):
            tick(W, step_s)
            before = len(W.events)
            main.take_calls(W)
            out += [e for e in W.events[before:] if e.generated]
            project_all(W)
            if each:
                each()
    finally:
        main.agent.start_run = original
    return out


def test_default_mode_is_live_calls_with_nothing_planned():
    assert config.SCHEDULED_DAY is False and WorldState("x").scheduled_day is False
    r = client.post("/sim/admin/reset", json={"scheduled_day": False})
    assert r.status_code == 200 and r.json()["mode"] == "live_calls" and r.json()["trips"] == 0, r.json()
    s = client.get("/sim/state").json()
    assert s["mode"] == "live_calls" and s["calls"]["active"] and s["calls"]["per_hour"] == config.CALLS_PER_HOUR
    assert s["trips"] == [] and s["kpis"]["late_trips"] == 0 and sum(s["kpis"]["unassigned"].values()) == 0
    places = {p["id"]: p for p in s["places"]}
    for v in s["vehicles"]:
        base = places[v["base_id"]]
        assert v["status"] == "idle" and v["queue"] == [] and (v["lat"], v["lon"]) == (base["lat"], base["lon"]), v


def test_reset_switches_to_the_scheduled_day_and_back():
    r = client.post("/sim/admin/reset", json={"scheduled_day": True}).json()
    assert r["mode"] == "scheduled_day" and r["trips"] == 28
    s = client.get("/sim/state").json()
    assert s["mode"] == "scheduled_day" and not s["calls"]["active"], "no random calls on the planned day"
    assert s["kpis"]["late_trips"] == 0 and sum(s["kpis"]["unassigned"].values()) == 0
    assert client.post("/sim/admin/reset").json()["mode"] == "scheduled_day", "no body: keeps the mode"
    assert client.post("/sim/admin/reset", json={"scheduled_day": False}).json()["trips"] == 0
    r = client.post("/sim/admin/calls", json={"enabled": False, "per_hour": 12}).json()
    assert r["enabled"] is False and r["per_hour"] == 12 and not r["active"]
    client.post("/sim/admin/calls", json={"enabled": True, "per_hour": config.CALLS_PER_HOUR})


def test_calls_are_dispatched_at_once_and_queues_stay_short():
    live()
    longest: dict[str, int] = {}
    busy = {"ambulance": 0, "transport": 0}
    samples = [0]

    def watch():
        samples[0] += 1
        for v in W.vehicles.values():
            longest[v.id] = max(longest.get(v.id, 0), len(route_trip_ids(v)))
            if v.type in busy and v.status != "idle":
                busy[v.type] += 1

    records = run_calls(6, each=watch)
    assert len(records) >= 30, len(records)
    for rec in records:
        t = W.trips[rec.affected_trip_ids[0]]
        assert t.priority in ("emergency", "urgent") and t.vehicle_id, rec.summary  # every call got a vehicle
        assert not (t.priority == "emergency" and W.vehicles[t.vehicle_id].type == "transport")
        if t.vehicle_id == "H1":  # doctrine rule 6: critical = closest unit; serious 10 min faster; urgent remote
            p, ukc = W.places[t.pickup_id], W.places["ukc"]
            sooner = re.search(r"helicopter, (\d+) min sooner", rec.summary)
            assert (
                t.severity == "critical"
                or haversine_km(p.lat, p.lon, ukc.lat, ukc.lon) >= 15
                or (t.severity == "serious" and sooner and int(sooner.group(1)) >= 10)
            ), rec.summary
    assert max(longest[v] for v in ("A1", "A2", "A3", "H1")) <= 2, longest  # current job + at most one
    assert max(longest[v] for v in ("T1", "T2", "T3", "T4", "T5")) <= 3, longest
    util = {k: busy[k] / samples[0] / (3 if k == "ambulance" else 5) for k in busy}
    assert all(0.3 <= u <= 0.85 for u in util.values()), util
    done = [t for t in W.trips.values() if t.status == "completed"]
    assert len(done) >= len(records) - 8 and sum(1 for t in done if (t.delay_min or 0) >= 5) <= 3
    # Nothing is stuck: what is still open (recent calls, long transfers) has a vehicle and arrives later.
    still_open = [t for t in W.trips.values() if t.status not in ("completed", "cancelled")]
    assert all(t.vehicle_id and t.eta_dropoff and t.eta_dropoff >= W.sim_time for t in still_open), still_open


def test_generated_calls_never_start_an_analysis():
    live()
    W.auto_analyze = True
    STARTED.clear()
    run_calls(4)
    assert all(t.startswith("call:") for t in STARTED)
    routine = W.calls.generated - len(STARTED)
    assert routine >= 20 and len(STARTED) <= 2, (routine, STARTED)  # routine calls: never an analysis

    # A genuine problem (no unit can take the call) may start one, only with auto-analyse on.
    for auto in (False, True):
        live()
        W.auto_analyze = auto
        for v in W.vehicles.values():
            v.status = "out_of_service"
        STARTED.clear()
        records = run_calls(0.5)
        problems = [r for r in records if calls.problem_of(W, r)]
        assert problems, records
        if auto:  # at most one such analysis per PROBLEM_RUN_GAP_MIN (15) world-minutes
            assert 1 <= len(STARTED) <= min(len(problems), 2), (len(problems), STARTED)
        else:
            assert STARTED == [], STARTED


def test_bookings_still_go_to_vans():
    live()
    r = client.post("/sim/events", json={"type": "task_request", "pickup_id": "zd_siska", "dropoff_id": "ukc",
                                          "needs": "stretcher", "ready_in_min": 10})
    t = W.trips[r.json()["affected_trip_ids"][0]]
    assert W.vehicles[t.vehicle_id].type == "transport", r.json()["summary"]


def test_every_scenario_builds_in_live_calls_mode_and_leaves_a_decision():
    for name, (title, _build) in demo.SCENARIOS.items():
        r = client.post(f"/sim/admin/scenario/{name}")
        assert r.status_code == 200, (name, r.text)
        assert r.json()["run_id"] is None, "auto-analyse off: no analysis starts"
        assert not W.scheduled_day and W.calls.paused_until and W.calls.paused_until > W.sim_time, name
        if name == "equipment_en_route":
            assert r.json()["vehicle_id"] == "T1" and "blood products" in r.json()["note"]
            continue
        question = f"Demo scenario: {title}. These events just happened together: x. Analyse the combined situation"
        rec = runner._engine_recommendation(W, None, "test", question)
        assert title in rec.situation, rec.situation
        summary = W.events[-1].summary
        if name in demo.AUTOMATIC:  # the engine decided by itself at dispatch time (doctrine rules 1, 2, 6)
            assert "diverted from" in summary or "available soon" in summary or "+ doctor" in summary, (name, summary)
        else:  # something to decide: options, or an escalation the dispatcher must act on
            assert rec.options or rec.escalation, f"{name}: the engine fallback has nothing to propose"
        for opt in rec.options:
            assert client.post("/sim/plans/simulate", json={"steps": [s.model_dump() for s in opt.steps]}).json()["feasible"], (name, opt.title)


def test_snapshot_stays_bounded_over_a_long_day():
    live()
    W.calls.per_hour = 12
    run_calls(8, step_s=60)
    s = W.snapshot()
    horizon = W.sim_time - timedelta(hours=3)
    assert len(s["trips"]) < len(W.trips)
    for t in s["trips"]:
        assert t["status"] not in ("completed", "cancelled") or t["eta_dropoff"] >= horizon.isoformat()
    calls_places = [p for p in s["places"] if p["kind"] == "call_location"]
    assert len(calls_places) <= len(s["trips"])


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
