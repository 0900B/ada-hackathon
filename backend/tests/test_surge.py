"""Proactive surge capacity with contracted units (engine/surge.py).

Run from backend/:  python tests/test_surge.py   (or: python -m pytest tests)
Offline: road routing off, no Claude. Live-calls mode, calls generator off.

- The demand trigger: no own ambulance free (25 % or less of those crewed), a red call over 15 min,
  or two calls past their target; the alert "high_demand" once that has lasted 5 world-minutes and
  patients are affected (hysteresis, more in tests/test_calls.py); never activates anything.
- Activation only by the dispatcher (endpoint or an approved option); stand-down; expiry.
- Use rules while active: transports to private vans first; urgent calls to a contracted ambulance
  only when our own is over 45 min away or it is 10 min sooner; red calls only when no public unit
  is within 15 min and it is faster.
"""
from __future__ import annotations

import logging
import os
import sys
import time
import traceback
from datetime import timedelta
from pathlib import Path

os.environ["ROAD_ROUTING"] = "0"
os.environ["AGENT_AUTO"] = "0"
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, main  # noqa: E402
from app.agent import runner  # noqa: E402
from app.agent.context import build_situation  # noqa: E402
from app.engine import surge  # noqa: E402
from app.engine.actions import ActionError, assign_trip, can_serve  # noqa: E402
from app.engine.events import apply_event  # noqa: E402
from app.engine.projection import project_all  # noqa: E402
from app.engine.severity import grade  # noqa: E402
from app.models import AgentRun, TaskRequestEvent, Trip, UrgentRequestEvent, utcnow  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402
from app.sim.simulator import tick  # noqa: E402

for noisy in ("httpx", "httpx2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
client = TestClient(main.app)
W = main.sim
CONTRACTED = ("P1", "P2", "PV1", "PV2", "PV3")


def fresh() -> None:
    seed_world(W, config.RANDOM_SEED, scheduled_day=False)
    W.auto_analyze = False
    W.calls.enabled = False


def run(minutes: float, until=None, step_s: float = 30) -> bool:
    for _ in range(int(minutes * 60 / step_s)):
        tick(W, step_s)
        project_all(W)
        if until and until():
            return True
    return False


def busy(vid: str, place: str = "home_vrhnika") -> Trip:
    """An own unit has just loaded an (urgent) patient far away: not free for a long while, and
    nothing about it can be moved or raises the trigger by itself."""
    t = Trip(id=f"B-{vid}", patient=f"P-{vid}", priority="urgent", severity="urgent", condition="fall",
             needs="stretcher", pickup_id=place, dropoff_id="ukc", pickup_after=W.sim_time,
             due_by=W.sim_time + timedelta(minutes=180))
    grade(W, t)
    W.trips[t.id] = t
    assign_trip(W, t.id, vid)
    v, p = W.vehicles[vid], W.places[place]
    v.queue.remove(t.id)
    v.current_trip_id, v.status, v.lat, v.lon = t.id, "with_patient", p.lat, p.lon
    t.status, t.eta_pickup = "onboard", W.sim_time
    return t


def call(place: str, severity: str, condition: str):
    priority = "urgent" if severity == "urgent" else "emergency"
    rec = apply_event(W, UrgentRequestEvent(type="urgent_request", pickup_id=place, priority=priority,  # type: ignore[arg-type]
                                            severity=severity, condition=condition, needs="stretcher"))  # type: ignore[arg-type]
    return rec, W.trips[rec.affected_trip_ids[0]]


def high_demand():
    return next((a for a in W.alerts if a.kind == "high_demand"), None)


# --- The demand trigger --------------------------------------------------------------------------


def test_trigger_no_own_ambulance_free():
    fresh()
    project_all(W)
    assert not surge.demand(W)["high"] and high_demand() is None
    busy("A1"), busy("A2")
    project_all(W)
    assert not surge.demand(W)["high"], "one of three free: above 25 %"
    busy("A3", "home_grosuplje")
    project_all(W)
    d = surge.demand(W)
    assert d["high"] and "0 of 3 own ambulances free" in d["reasons"], d
    # The alert has hysteresis: no ambulance free alone (no patient affected) never raises it, however long.
    assert high_demand() is None
    W.sim_time += timedelta(minutes=surge.DEMAND_RAISE_AFTER_MIN + 1)
    project_all(W)
    assert surge.demand(W)["high"] and high_demand() is None, "busy, but no patient waits too long"
    W.vehicles["H1"].status = "out_of_service"
    _, t = call("home_polje", "serious", "seizure")  # now a red call waits over 15 min: patients are affected
    assert t.id in surge.demand(W)["red_over_15_min"], surge.demand(W)
    a = high_demand()  # the trigger has been on for over 5 min already: raised at once
    assert a is not None and "Activating contracted units would help (2 ambulances, 3 private vans for 2 h)" in a.message, a
    assert all(v not in W.vehicles for v in CONTRACTED), "the trigger never activates anything"


def test_trigger_red_call_over_15_min_and_calls_past_target():
    fresh()
    for v in ("A1", "A2", "A3", "H1"):
        W.vehicles[v].status = "out_of_service"
    W.vehicles["A3"].status = "idle"
    W.vehicles["A3"].lat, W.vehicles["A3"].lon = W.places["sb_novo_mesto"].lat, W.places["sb_novo_mesto"].lon
    _, t = call("home_polje", "serious", "seizure")
    d = surge.demand(W)
    assert t.id in d["red_over_15_min"] and any(f"red call {t.id}" in r for r in d["reasons"]), d
    assert high_demand() is None, "raised only once the trigger has been on for 5 world-minutes"
    W.sim_time += timedelta(minutes=surge.DEMAND_RAISE_AFTER_MIN)
    project_all(W)
    assert high_demand().trip_id == t.id and high_demand().severity == "critical"
    _, t2 = call("home_moste", "urgent", "fall")  # 60-min target; nobody gets there in time either
    W.vehicles["A3"].status = "out_of_service"
    for v in ("T1", "T2", "T3", "T4", "T5"):
        W.vehicles[v].status = "out_of_service"
    project_all(W)
    assert len(surge.past_target(W)) >= 1


def test_trigger_off_in_the_scheduled_day():
    seed_world(W, config.RANDOM_SEED, scheduled_day=True)
    for v in ("A1", "A2", "A3"):
        busy(v)
    project_all(W)
    assert not surge.demand(W)["high"] and high_demand() is None


# --- Activation, stand-down, expiry ---------------------------------------------------------------


def test_activate_and_stand_down_by_endpoint():
    fresh()
    snap = client.get("/sim/state").json()
    assert snap["surge"]["active"] is False and snap["surge"]["available"] == {"ambulances": ["P1", "P2"], "vans": ["PV1", "PV2", "PV3"]}
    assert not set(CONTRACTED) & {v["id"] for v in snap["vehicles"]}
    r = client.post("/sim/admin/surge", json={"ambulances": 2, "vans": 3, "hours": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["surge"]["active"] and body["surge"]["units"] == list(CONTRACTED)
    assert body["event"]["summary"].startswith("Surge capacity active until")
    vehicles = {v["id"]: v for v in client.get("/sim/state").json()["vehicles"]}
    for vid in CONTRACTED:
        v = vehicles[vid]
        assert v["origin"] == "private" and v["contract_until"] is not None, v
    assert W.vehicles["PV1"].type == "transport" and W.vehicles["P2"].type == "ambulance"
    until = W.vehicles["P1"].contract_until
    assert abs((until - W.sim_time).total_seconds() - 7200) < 1
    run(10)
    assert all(v in W.vehicles for v in CONTRACTED), "idle at their bases while the contract runs: they stay"
    r = client.post("/sim/admin/surge/stand-down")
    assert r.status_code == 200 and not r.json()["surge"]["active"], r.text
    assert "finish their current job and leave" in r.json()["event"]["summary"]
    assert all(v not in W.vehicles for v in CONTRACTED), "idle at home: they leave at once"
    assert all(v in W.reserve_vehicles and W.reserve_vehicles[v].contract_until is None for v in CONTRACTED)
    assert client.post("/sim/admin/surge", json={"ambulances": 0, "vans": 0}).status_code == 400


def test_expiry_finishes_the_current_job_then_leaves():
    fresh()
    surge.activate(W, ambulances=2, vans=0, hours=0.25)
    _, t = call("home_bezigrad", "serious", "sepsis")
    for v in ("A1", "A2", "A3", "H1"):  # make P1/P2 the only units, for a job that outlasts the contract
        if W.trips[t.id].vehicle_id != v:
            W.vehicles[v].status = "out_of_service"
    p = W.vehicles["P2"]
    assign_trip(W, t.id, "P2")
    assert run(20, until=lambda: t.status == "onboard"), t.status
    assert run(10, until=lambda: not surge.active(W))
    assert p.contract_ended and p.current_trip_id == t.id, "it finishes the patient it has on board"
    ok, why = can_serve(p, t)
    assert not ok and "contract has ended" in why
    assert run(120, until=lambda: "P2" not in W.vehicles), p.status
    assert t.status == "completed" and t.vehicle_id == "P2" and "P2" in W.reserve_vehicles


def test_activation_only_by_the_dispatcher_and_per_call_reserve_stays():
    fresh()
    _, t = call("home_polje", "serious", "seizure")
    try:
        assign_trip(W, t.id, "P2")
        raise AssertionError("P2 was requested for a single call")
    except ActionError as e:
        assert "activate surge capacity first" in str(e)
    assert "PV1" not in W.vehicles and {u["id"] for u in build_situation(W).get("reserve_units", [])} == {"M1", "P1"}


# --- Use rules while active -----------------------------------------------------------------------


def test_red_call_private_only_when_no_public_unit_within_15_min():
    fresh()
    surge.activate(W)
    rec, t = call("home_moste", "serious", "seizure")
    assert t.vehicle_id in ("A1", "A2", "A3"), rec.summary  # a public unit is close: no private ambulance
    fresh()
    for v in ("A1", "A2", "A3"):
        busy(v)
    W.vehicles["H1"].status = "out_of_service"  # (else the helicopter is the public unit within 15 min)
    surge.activate(W)
    rec, t = call("home_vic", "serious", "seizure")
    assert t.vehicle_id in ("P1", "P2") and "contracted private ambulance: no public unit within 15 min" in rec.summary, rec.summary


def test_urgent_call_private_when_ours_is_over_45_min_or_10_min_sooner():
    fresh()
    for v in ("A1", "A2", "A3"):
        busy(v)
    for v in ("T1", "T2", "T3", "T4", "T5"):
        W.vehicles[v].status = "out_of_service"
    surge.activate(W, vans=0)
    rec, t = call("home_vic", "urgent", "fall")
    assert t.vehicle_id in ("P1", "P2") and "contracted private ambulance" in rec.summary, rec.summary


def test_transports_go_to_private_vans_first_and_private_units_keep_their_role():
    fresh()
    surge.activate(W)
    rec = apply_event(W, TaskRequestEvent(type="task_request", pickup_id="zd_center", dropoff_id="ukc", needs="seated",
                                          priority="urgent", ready_in_min=10, severity="urgent", condition="transfer"))
    t = W.trips[rec.affected_trip_ids[0]]
    assert t.vehicle_id in ("PV1", "PV2", "PV3"), rec.summary
    rec, fall = call("home_siska", "urgent", "fall")
    assert fall.vehicle_id not in ("PV1", "PV2", "PV3"), "private vans: non-urgent transports only"


# --- The engine option and the scenario -----------------------------------------------------------


def test_call_surge_scenario_offers_surge_capacity_and_the_queue_clears():
    r = client.post("/sim/admin/scenario/surge")
    assert r.status_code == 200, r.text
    a = high_demand()
    assert a is not None and "own ambulances free" in a.message and "red call" in a.message, a
    situation = build_situation(W)
    assert situation["demand"]["high_demand"] and "Activate surge capacity" in situation["demand"]["surge_capacity"]["offer"]
    rec = runner._engine_recommendation(W, W.events[-1], "test", W.pending_question)
    opt = rec.options[0]
    assert opt.activate_surge and not opt.steps and rec.recommended_index == 0
    assert opt.title == ("Activate surge capacity for 2 h: contracted ambulances P1 (Brezovica), P2 (Vič) with qualified crews; "
                         "private vans PV1–PV3 for non-urgent transports"), opt.title
    red_waiting = surge.demand(W)["red_over_15_min"]
    assert len(red_waiting) >= 2
    run_ = AgentRun(id=W.new_id("RUN"), trigger="test", started_at=utcnow())
    W.agent_runs.append(run_)
    runner._finish(W, run_, rec, engine="engine")
    r = client.post(f"/sim/agent/runs/{run_.id}/approve", json={"option_index": 0})
    assert r.status_code == 200, r.text
    assert surge.active(W) and r.json()["decision"]["executed"][0].startswith("Surge capacity active until")
    on_private = {t.id: t.vehicle_id for t in W.trips.values() if t.vehicle_id in CONTRACTED}
    assert {on_private.get(x) for x in red_waiting} <= {"P1", "P2"} and all(x in on_private for x in red_waiting), on_private
    assert any(v.startswith("PV") for v in on_private.values()), "queued transports moved to the private vans"
    assert len(surge.demand(W)["red_over_15_min"]) < len(red_waiting)


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
