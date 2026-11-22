"""The Reports page's numbers (app/reports.py, GET /{world}/reports).

Run from backend/:  python tests/test_reports.py   (or: python -m pytest tests)
Offline: road routing off, no Claude. A live-calls world runs for a few world-hours; every figure the
endpoint returns is then recomputed independently from the trips themselves.
"""
from __future__ import annotations

import logging
import os
import statistics
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

from app import config, main, reports  # noqa: E402
from app.models import TimelineEntry  # noqa: E402
from app.engine.projection import LATE_ALERT_MIN, project_all  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402
from app.sim.simulator import tick  # noqa: E402
from app.state import WorldState  # noqa: E402

for noisy in ("httpx", "httpx2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
client = TestClient(main.app)
W = main.sim
HOURS = 5
KEYS = {"world", "window", "totals", "by_severity", "doctor", "transports", "utilisation", "ai", "hourly", "method"}


def _noop_start(state, trigger, focus=None, question=None):  # stands in for agent.start_run
    return None


def fresh() -> None:
    seed_world(W, config.RANDOM_SEED, scheduled_day=False)
    W.auto_analyze = False
    W.calls.enabled, W.calls.per_hour = True, config.CALLS_PER_HOUR


def run_world(hours: float, step_s: float = 30, each=None) -> None:
    original = main.agent.start_run
    main.agent.start_run = _noop_start
    try:
        for _ in range(int(hours * 3600 / step_s)):
            tick(W, step_s)
            main.take_calls(W)
            project_all(W)
            if each:
                each()
    finally:
        main.agent.start_run = original


def get(world: str = "sim", hours: float = 3) -> dict:
    r = client.get(f"/{world}/reports", params={"hours": hours})
    assert r.status_code == 200, r.text
    return r.json()


def first_on_scene(t):
    return next((e.at for e in t.timeline if e.kind == "on_scene"), None) or t.eta_pickup


def minutes(a, b) -> float:
    return max(0.0, (a - b).total_seconds() / 60)


def done_trips():
    return [t for t in W.trips.values() if t.status == "completed"]


BUSY: dict[str, list[int]] = {}


def watch() -> None:  # the test's own utilisation measure: every tick, not every minute
    for v in W.vehicles.values():
        if v.status == "out_of_service":
            continue
        b = BUSY.setdefault(v.id, [0, 0])
        b[0] += v.status != "idle"
        b[1] += 1


def test_zero_data_world_has_empty_arrays_and_nulls():
    r = client.post("/sim/admin/reset", json={"scheduled_day": False})
    assert r.status_code == 200
    d = get("sim")
    assert set(d) == KEYS, set(d) ^ KEYS
    assert d["totals"] == {"calls": 0, "closed": 0, "open": 0}, d["totals"]
    assert d["by_severity"] == [] and d["hourly"] == [], d
    assert d["doctor"]["n"] == 0 and d["doctor"]["pct_within_15"] is None and d["doctor"]["median"] is None
    assert d["transports"]["n"] == 0 and d["transports"]["late_pct"] is None and d["transports"]["avg_delay_min"] is None
    assert d["ai"]["calls"] == 0 and d["ai"]["autonomous_share"] is None
    assert sum(d["ai"]["decided"].values()) == 0
    assert d["window"]["hours"] == 3 and d["window"]["from"] < d["window"]["to"]
    # a world that was never seeded (the app's live world before its start-up) answers too
    unseeded = client.get("/live/reports").json()
    assert unseeded["totals"]["closed"] == 0 and unseeded["utilisation"] == [] and unseeded["by_severity"] == []


def test_hours_are_clamped_and_bad_input_is_refused():
    assert get("sim", 0.01)["window"]["hours"] == 0.25
    assert get("sim", 500)["window"]["hours"] == reports.MAX_HOURS
    assert client.get("/sim/reports", params={"hours": "soon"}).status_code == 422
    assert client.get("/nowhere/reports").status_code == 422


def test_totals_and_severity_figures_match_the_trips():
    fresh()
    BUSY.clear()
    run_world(HOURS, each=watch)
    d = get("sim", 24)
    done = done_trips()
    assert len(done) >= 20, len(done)
    assert d["totals"]["closed"] == len(done), (d["totals"], len(done))
    open_n = sum(1 for t in W.trips.values() if t.status not in ("completed", "cancelled"))
    assert d["totals"]["open"] == open_n and d["totals"]["calls"] == len(W.trips)
    assert sum(s["n"] for s in d["by_severity"]) == len(done)
    assert [s["severity"] for s in d["by_severity"]] == sorted((s["severity"] for s in d["by_severity"]),
                                                               key=("critical", "serious", "urgent", "routine").index)
    for s in d["by_severity"]:
        mine = [t for t in done if t.severity == s["severity"]]
        timed = [(minutes(first_on_scene(t), t.call.received_at if t.call else t.pickup_after), t.response_target_min) for t in mine
                 if t.response_target_min is not None]
        assert s["n"] == len(mine) and s["n_timed"] == len(timed), s
        if not timed:
            assert s["median_response"] is None and s["pct_within_target"] is None
            continue
        values = sorted(m for m, _ in timed)
        assert abs(s["median_response"] - statistics.median(values)) <= 0.06, (s["severity"], s["median_response"], values)
        assert s["p90_response"] >= s["median_response"] and s["p90_response"] <= max(values) + 0.06
        within = sum(1 for m, tgt in timed if m <= tgt)
        assert abs(s["pct_within_target"] - 100 * within / len(timed)) <= 0.06, s
        assert [round(x["min"], 1) for x in s["responses"]] == [round(v, 1) for v in values]
        assert all(abs(x["min"] - x["target"]) < 0.06 or x["met"] == (x["min"] <= x["target"]) for x in s["responses"])
    sev = {s["severity"]: s for s in d["by_severity"]}
    assert {"critical", "serious", "urgent"} <= set(sev), sev.keys()
    assert sev["critical"]["target_min"] == 8 and sev["serious"]["target_min"] == 18 and sev["urgent"]["target_min"] == 60
    assert all(0 < (x["median_response"] or 0) < 90 for x in sev.values() if x["median_response"] is not None)


def test_doctor_and_transport_figures_match_the_trips():
    d = get("sim", 24)
    done = done_trips()
    needing = [t for t in done if t.needs_doctor]
    assert d["doctor"]["n"] == len(needing) and len(needing) >= 3, (d["doctor"], len(needing))
    assert 0 <= d["doctor"]["pct_within_15"] <= 100 and d["doctor"]["target_min"] == 15
    assert d["doctor"]["none_arrived"] <= d["doctor"]["n"]
    arrived = [r for r in reports._log(W).records.values() if r.doctor_needed and r.doctor_min is not None]
    assert d["doctor"]["none_arrived"] == d["doctor"]["n"] - len(arrived)
    ontime = sum(1 for r in arrived if r.doctor_min <= 15)
    assert abs(d["doctor"]["pct_within_15"] - 100 * ontime / d["doctor"]["n"]) <= 0.06
    late = sum(1 for t in done if (t.delay_min or 0) >= LATE_ALERT_MIN)
    tr = d["transports"]
    assert tr["n"] == len(done) and tr["late"] == late and tr["late_after_min"] == LATE_ALERT_MIN
    assert abs(tr["late_pct"] - 100 * late / len(done)) <= 0.06
    assert abs(tr["avg_delay_min"] - sum(t.delay_min or 0 for t in done) / len(done)) <= 0.06


def test_utilisation_matches_an_independent_measure():
    d = get("sim", 24)
    util = {u["vehicle_id"]: u for u in d["utilisation"]}
    assert set(util) == {v for v in W.vehicles}, set(util) ^ set(W.vehicles)
    for vid, u in util.items():
        mine = BUSY[vid]
        expected = 100 * mine[0] / mine[1]
        assert 0 <= u["busy_pct"] <= 100 and u["samples"] >= HOURS * 60 - 5, u
        assert abs(u["busy_pct"] - expected) <= 6, (vid, u["busy_pct"], round(expected, 1))  # one sample a minute vs every 30 s
    assert max(util[v]["busy_pct"] for v in ("A1", "A2", "A3")) >= 25, util  # the ambulances do work
    assert {u["type"] for u in d["utilisation"]} >= {"ambulance", "transport", "helicopter", "doctor"}
    # a shorter window uses fewer samples
    short = {u["vehicle_id"]: u for u in get("sim", 1)["utilisation"]}
    assert all(short[v]["samples"] <= 61 for v in short) and all(short[v]["samples"] < util[v]["samples"] for v in short)


def test_hourly_buckets_add_up_and_windows_filter():
    d = get("sim", 24)
    hourly = d["hourly"]
    assert sum(h["calls"] for h in hourly) == d["totals"]["closed"]
    hours = [h["hour"] for h in hourly]
    assert hours == sorted(hours) and all(h.endswith(":00:00+00:00") or h.endswith(":00:00Z") for h in hours), hours
    for a, b in zip(hours, hours[1:]):
        from datetime import datetime
        assert datetime.fromisoformat(b) - datetime.fromisoformat(a) == timedelta(hours=1)  # empty hours stay in
    assert all(h["pct_within_target"] is None or 0 <= h["pct_within_target"] <= 100 for h in hourly)
    assert all(h["within_target"] <= h["timed"] <= h["calls"] for h in hourly)
    assert sum(h["within_target"] for h in hourly) == sum(
        s["pct_within_target"] is not None and round(s["pct_within_target"] * s["n_timed"] / 100) for s in d["by_severity"]
    ), "hourly and per-severity counts of calls within target must agree"
    assert [h["partial"] for h in hourly][-1] is True, "the hour in progress is flagged partial"
    one, three = get("sim", 1), get("sim", 3)
    assert one["totals"]["closed"] <= three["totals"]["closed"] <= d["totals"]["closed"]
    cutoff = W.sim_time - timedelta(hours=1)
    expected = sum(1 for r in reports._log(W).records.values() if r.completed_at >= cutoff)
    assert one["totals"]["closed"] == expected and one["window"]["hours"] == 1


def test_without_claude_or_dispatcher_the_engine_decided_everything():
    a = get("sim", 24)["ai"]
    n = a["calls"]
    assert n == get("sim", 24)["totals"]["closed"] and n >= 20
    assert a["dispatched_by_engine"] == n and a["dispatched_by_claude"] == 0 and a["dispatched_by_dispatcher"] == 0, a
    assert a["reviewed_by_claude"] == a["changed_by_claude"] == a["dispatcher_overrides"] == 0
    assert a["decided"] == {"engine_only": n, "claude_agreed": 0, "claude_changed": 0, "dispatcher_overrode": 0}
    assert a["autonomous_share"] == 100.0


def test_overrides_reviews_and_approvals_are_counted_from_the_timeline():
    fresh()
    open_trips: list = []
    for _ in range(40):  # until four calls are open at once (they are served quickly)
        run_world(0.25)
        open_trips = [t for t in W.trips.values() if t.status in ("assigned", "en_route_pickup", "onboard") and t.vehicle_id and t.call]
        if len(open_trips) >= 4:
            break
    assert len(open_trips) >= 4, len(open_trips)
    overridden, changed, agreed, approved = open_trips[:4]

    def note(trip, kind, by, text, vid):  # model_construct: the "override" and "reviewed" kinds may not be in the model yet
        trip.timeline.append(TimelineEntry.model_construct(at=W.sim_time, kind=kind, by=by, text=text, vehicle_id=vid, run_id=None))

    unit = lambda t: t.vehicle_id  # noqa: E731
    note(overridden, "override", "dispatcher", "Dispatcher override: another unit instead", unit(overridden))
    note(overridden, "reassigned", "dispatcher", "Reassigned by hand", unit(overridden))
    note(changed, "reviewed", "claude", "Claude changed the unit: A2 instead of A1", unit(changed))
    note(changed, "reviewed", "claude", "Claude reviewed: no change", unit(changed))
    note(agreed, "reviewed", "claude", "Claude reviewed: no change", unit(agreed))
    # approving a proposed plan is not an override: the dispatcher's reassignment at the approval's time is credited to the proposer
    note(approved, "proposal", "ai", "Claude proposes a plan", unit(approved))
    note(approved, "approved", "dispatcher", "Operator approved: plan", unit(approved))
    note(approved, "reassigned", "dispatcher", "Reassigned from A1 to A2", unit(approved))
    run_world(4)
    recs = reports._log(W).records
    ids = [t.id for t in (overridden, changed, agreed, approved)]
    assert all(i in recs for i in ids), [i for i in ids if i not in recs]
    r0, r1, r2, r3 = (recs[i] for i in ids)
    assert r0.overrides == 2 and r0.assigned_by == "dispatcher", r0
    assert (r1.claude_reviews, r1.claude_changes, r1.overrides) == (2, 1, 0), r1
    assert (r2.claude_reviews, r2.claude_changes) == (1, 0), r2
    assert r3.overrides == 0 and r3.assigned_by == "claude", r3
    a = get("sim", 24)["ai"]
    dec = a["decided"]
    assert dec["dispatcher_overrode"] >= 1 and dec["claude_changed"] >= 1 and dec["claude_agreed"] >= 1, a
    assert sum(dec.values()) == a["calls"], a
    assert a["dispatcher_overrides"] == 2 and a["reviewed_by_claude"] == 2 and a["changed_by_claude"] == 1
    assert a["dispatched_by_dispatcher"] == 1 and a["dispatched_by_claude"] >= 1
    assert abs(a["autonomous_share"] - 100 * (a["calls"] - dec["dispatcher_overrode"]) / a["calls"]) <= 0.06


def test_what_if_copies_and_resets_never_touch_the_history():
    fresh()
    run_world(1)
    before = len(reports._log(W).records)
    clone = W.clone_for_simulation()
    for _ in range(240):  # two more world-hours on the copy: trips complete there
        tick(clone, 30)
    assert sum(1 for t in clone.trips.values() if t.status == "completed") > sum(1 for t in W.trips.values() if t.status == "completed")
    assert len(reports._log(W).records) == before, "a what-if copy wrote to the real history"
    assert reports._log(clone) is not reports._log(W) and not reports._log(clone).records
    assert before > 0
    client.post("/sim/admin/reset", json={"scheduled_day": False})
    assert get("sim", 24)["totals"]["closed"] == 0, "history must be cleared with the world"


def test_history_is_bounded():
    s = WorldState("bounded")
    seed_world(s, config.RANDOM_SEED, scheduled_day=False)
    entry = reports._log(s)
    sample_trip = None
    fresh()
    run_world(1)
    sample_trip = next(t for t in W.trips.values() if t.status == "completed")
    for i in range(reports.MAX_RECORDS + 50):
        t = sample_trip.model_copy(update={"id": f"X-{i}"})
        reports.record_trip(s, t)
    assert len(entry.records) == reports.MAX_RECORDS and "X-0" not in entry.records
    for _ in range(reports.MAX_SAMPLES + 10):
        s.sim_time += reports.SAMPLE_EVERY
        reports.sample(s)
    assert len(entry.samples) == reports.MAX_SAMPLES


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
