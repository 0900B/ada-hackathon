"""Dispatch benchmark: Plan B's engine rules against plain "nearest free ambulance" dispatch.

Same seeded call sequences from the live-calls generator (sim/calls.py), two policies:

- BASELINE, a simple CAD rule: the nearest free suitable unit by ETA at call time; if none is free,
  the unit that becomes free first (its queue's end: first come, first served; the only ordering
  is emergency before other work). No "available soon", no overrides, no swaps; the helicopter
  only if no ambulance can take the call. Bookings: the nearest free van, else the van free first.
- PLAN B, the engine's own dispatch (engine/dispatch.py): severity-graded, units available soon,
  overrides with re-dispatch of the displaced call, the helicopter rules, protecting cover, and the
  engine's booking placement (engine/events.py).

Both policies send doctor cars the same simple way (the free doctor car that arrives first,
engine/doctors.send_doctor) when the fleet has them and the call needs a doctor, so the doctor
metric shows the effect of the ambulance decisions only. Reserve units (mutual aid, private) are
a dispatcher's decision and are not used by either policy. The AI is not in the loop: these are
engine rules only.

Run (from backend/):  python tools/benchmark.py [--seeds 100] [--hours 8] [--workers 6]  (about 4 min)
ROAD_ROUTING=0 is forced: straight-line travel times with the city's speed model (fast and
deterministic, no routing service). Every run starts at 08:00 local (START): a day shift, inside the
helicopter's hours. The helicopter is the real service's (app/hems.py): based at Brnik, 13 min from
the call to take-off, day only.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ["ROAD_ROUTING"] = "0"  # straight-line travel model: deterministic and fast
os.environ.pop("ANTHROPIC_API_KEY", None)  # the AI is not part of this benchmark
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import logging  # noqa: E402

logging.disable(logging.WARNING)

from app import config  # noqa: E402
from app.engine import dispatch as engine_dispatch  # noqa: E402
from app.engine import events as engine_events  # noqa: E402
from app.engine.candidates import find_candidates  # noqa: E402
from app.engine.projection import LATE_ALERT_MIN, project_all  # noqa: E402
from app.models import Plan, PlanStep  # noqa: E402
from app.routing import flies  # noqa: E402
from app.sim import calls  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402
from app.sim.simulator import tick  # noqa: E402
from app.state import WorldState  # noqa: E402

try:  # doctor cars (merged later): used automatically when present
    from app.engine.doctors import send_doctor
except ImportError:  # pragma: no cover
    send_doctor = None  # type: ignore[assignment]

OUT = Path(__file__).resolve().parent / "benchmark_results"
# A day shift with a fixed clock (reproducible): calls 08:00-16:00 local, inside the helicopter's hours
# (08:00-16:30, app/hems.py). At night the helicopter takes no calls: the ground-only rows apply.
START = datetime(2026, 11, 23, 8, 0, tzinfo=ZoneInfo("Europe/Ljubljana"))
TICK_S = 15.0  # simulated seconds per step
DRAIN_H = 3.0  # after the call window: no new calls, until every call is finished (or this long)
DOCTOR_TARGET_MIN = 15.0
DONE = ("completed", "cancelled")

_PLAN_B_DISPATCH = engine_dispatch.dispatch_call
_PLAN_B_BOOK = engine_events._book_task


# --- The baseline policy ---------------------------------------------------------------------------


def _apply(state: WorldState, cand: dict) -> None:
    from app.engine.plans import _apply_steps

    _apply_steps(state, Plan(steps=[PlanStep(**cand["step"])]))


def _pick(pool: list[dict]) -> dict | None:
    """The nearest free unit by ETA; if none is free, the one that becomes free first (queue end)."""
    free = [c for c in pool if c["vehicle_free"] and c["trip_eta_pickup"]]
    if free:
        return min(free, key=lambda c: c["trip_eta_pickup"])
    at_end = [c for c in pool if c["step"]["position"] is None and c["trip_eta_pickup"]]
    return min(at_end, key=lambda c: c["trip_eta_pickup"]) if at_end else None


def baseline_dispatch(state: WorldState, trip) -> str:
    cands = [c for c in find_candidates(state, trip.id, limit=200) if not c["step"]["interrupt_current"]]
    if trip.priority == "emergency":
        pool = [c for c in cands if c["vehicle_type"] == "ambulance"] or [c for c in cands if flies(c["vehicle_type"])]
    else:  # an urgent field call: any suitable road unit
        pool = [c for c in cands if c["vehicle_type"] in ("ambulance", "transport")]
    best = _pick(pool)
    if best is None:
        return "; baseline: no unit"
    _apply(state, best)
    trip.dispatched_at = state.sim_time
    if send_doctor is not None:
        send_doctor(state, trip, best["vehicle_id"], best["trip_eta_pickup"])
    return f"; baseline: {best['vehicle_id']}"


def baseline_book(state: WorldState, ev, created: list[str]) -> str:
    text = _PLAN_B_BOOK(state, ev.model_copy(update={"auto_assign": False}), created)  # create the trip only
    trip = state.trips[created[-1]]
    cands = [c for c in find_candidates(state, trip.id, limit=200) if not c["step"]["interrupt_current"]]
    best = _pick([c for c in cands if c["vehicle_type"] == "transport"]) or _pick(
        [c for c in cands if c["vehicle_type"] == "ambulance"]
    )
    if best is not None:
        _apply(state, best)
    return text


def use_policy(name: str) -> None:
    engine_dispatch.dispatch_call = baseline_dispatch if name == "baseline" else _PLAN_B_DISPATCH  # type: ignore[assignment]
    engine_events._book_task = baseline_book if name == "baseline" else _PLAN_B_BOOK  # type: ignore[assignment]


# --- One run ----------------------------------------------------------------------------------------


def run_once(policy: str, seed: int, hours: float, per_hour: float, helicopter: bool = True) -> dict:
    use_policy(policy)
    state = WorldState(name="bench", speedup=1.0, hypothetical=True)
    seed_world(state, seed, scheduled_day=False, start=START)
    if not helicopter:  # ground units only, for both policies (how much do the ground rules alone add?)
        for vid in [v.id for v in state.vehicles.values() if flies(v.type)]:
            del state.vehicles[vid]
    state.auto_analyze = False
    state.calls.enabled, state.calls.per_hour = True, per_hour
    state.calls.reset(seed, "bench", state.sim_time)
    start = state.sim_time
    end_calls = start + timedelta(hours=hours)
    ambulances = [v for v in state.vehicles.values() if v.type == "ambulance"]
    busy_samples, samples = 0, 0
    while state.sim_time < end_calls + timedelta(hours=DRAIN_H):
        tick(state, TICK_S)
        if state.sim_time < end_calls:
            calls.step(state)
            now = state.sim_time
            busy_samples += sum(
                1
                for v in ambulances
                if v.status in ("to_pickup", "loading", "with_patient") or (v.busy_until is not None and v.busy_until > now)
            )
            samples += len(ambulances)
        else:
            state.calls.enabled = False
            if all(t.status in DONE for t in state.trips.values()):
                break
        project_all(state)
    return {
        "policy": policy,
        "seed": seed,
        "per_hour": per_hour,
        "helicopter": helicopter,
        "utilisation": busy_samples / max(1, samples),
        "trips": _trips(state),
    }


def _minutes(a: datetime | None, b: datetime) -> float | None:
    return None if a is None else max(0.0, (a - b).total_seconds() / 60)


def _trips(state: WorldState) -> list[dict]:
    out = []
    for t in state.trips.values():
        reached = t.eta_pickup if t.status in ("onboard", "completed") else None
        out.append(
            {
                "severity": t.severity,
                "kind": t.kind,
                "booking": t.condition in ("transfer", "equipment"),
                "wait": _minutes(reached, t.pickup_after),  # call (or ready time) to reaching the patient
                "target": t.response_target_min,
                "needs_doctor": bool(getattr(t, "needs_doctor", False)),
                "doctor_wait": _minutes(getattr(t, "doctor_eta", None), t.pickup_after)
                if getattr(t, "doctor_vehicle_id", None)
                else None,
                "late": (t.delay_min or 0) >= LATE_ALERT_MIN,
                "done": t.status == "completed",
                "vehicle": t.vehicle_id,
            }
        )
    return out


# --- Metrics ----------------------------------------------------------------------------------------


def _pct(xs: list[bool]) -> float | None:
    return round(100 * sum(xs) / len(xs), 1) if xs else None


def _q(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def metrics(runs: list[dict]) -> dict:
    trips = [t for r in runs for t in r["trips"]]
    never = float("inf")

    def waits(level: str) -> list[float]:
        return [t["wait"] if t["wait"] is not None else never for t in trips if t["severity"] == level]

    crit = [t for t in trips if t["severity"] == "critical"]
    serious = [t for t in trips if t["severity"] == "serious"]
    ser = waits("serious")
    urgent = [t for t in trips if t["severity"] == "urgent"]
    doctor = [t for t in trips if t["needs_doctor"]]
    finite = lambda xs: [x for x in xs if x != never]  # noqa: E731
    return {
        "calls": len(trips),
        "critical_calls": len(crit),
        "critical_within_target_pct": _pct([t["wait"] is not None and t["target"] is not None and t["wait"] <= t["target"] for t in crit]),
        "critical_median_min": _q(finite(waits("critical")), 0.5),
        "critical_p90_min": _q(finite(waits("critical")), 0.9),
        "serious_calls": len(ser),
        "serious_within_18_pct": _pct([w <= 18 for w in ser]),
        "serious_median_min": _q(finite(ser), 0.5),
        "serious_p90_min": _q(finite(ser), 0.9),
        "urgent_calls": len(urgent),
        "urgent_within_60_pct": _pct([t["wait"] is not None and t["wait"] <= 60 for t in urgent]),
        "doctor_calls": len(doctor),
        "doctor_within_15_pct": _pct([t["doctor_wait"] is not None and t["doctor_wait"] <= DOCTOR_TARGET_MIN for t in doctor]),
        "late_transports_pct": _pct([t["late"] for t in trips]),
        "not_reached": sum(1 for t in trips if t["wait"] is None),
        "ambulance_utilisation_pct": round(100 * statistics.mean(r["utilisation"] for r in runs), 1),
        # who served the call in the end (the demo fleet's only helicopter is H1)
        "helicopter_critical_pct": _pct([t["vehicle"] == "H1" for t in crit]),
        "helicopter_serious_pct": _pct([t["vehicle"] == "H1" for t in serious]),
    }


ROWS = [
    ("Critical calls reached within target (8 min city / 15 outside)", "critical_within_target_pct", "%", True),
    ("Critical: median time to the patient", "critical_median_min", " min", False),
    ("Critical: 90th percentile time to the patient", "critical_p90_min", " min", False),
    ("Serious calls reached within 18 min", "serious_within_18_pct", "%", True),
    ("Serious: median time to the patient", "serious_median_min", " min", False),
    ("Serious: 90th percentile time to the patient", "serious_p90_min", " min", False),
    ("Urgent calls reached within 60 min", "urgent_within_60_pct", "%", True),
    ("Doctor on scene within 15 min (calls that need one)", "doctor_within_15_pct", "%", True),
    ("Late transports (≥ 5 min after due)", "late_transports_pct", "%", False),
    ("Calls never reached", "not_reached", "", False),
    ("Ambulance utilisation (busy share of the call window)", "ambulance_utilisation_pct", "%", None),
    ("Critical calls served by the helicopter", "helicopter_critical_pct", "%", None),
    ("Serious calls served by the helicopter", "helicopter_serious_pct", "%", None),
]


def per_seed(runs: list[dict], key: str, higher_better: bool) -> dict:
    """In how many seeds Plan B is better, the same, or worse on one metric."""
    out = {"better": 0, "same": 0, "worse": 0}
    for seed in sorted({r["seed"] for r in runs}):
        b = metrics([r for r in runs if r["seed"] == seed and r["policy"] == "baseline"])[key]
        p = metrics([r for r in runs if r["seed"] == seed and r["policy"] == "planb"])[key]
        if b is None or p is None:
            continue
        out["same" if abs(p - b) < 0.05 else "better" if (p > b) == higher_better else "worse"] += 1
    return out


def table(load: str, base: dict, planb: dict) -> str:
    lines = [f"### {load}", "", "| Metric | Baseline (nearest free) | Plan B (engine rules) | Difference |", "|---|---:|---:|---:|"]
    for label, key, unit, higher_better in ROWS:
        b, p = base.get(key), planb.get(key)
        if b is None and p is None:
            continue
        diff = ""
        if isinstance(b, (int, float)) and isinstance(p, (int, float)):
            d = round(p - b, 1)
            better = "" if higher_better is None or d == 0 else (" (better)" if (d > 0) == higher_better else " (worse)")
            diff = f"{d:+g}{unit.strip() and (' pp' if unit == '%' else unit)}{better}"
        fmt = lambda v: "n/a" if v is None else f"{v:g}{unit}"  # noqa: E731
        lines.append(f"| {label} | {fmt(b)} | {fmt(p)} | {diff} |")
    counts = lambda m: f"{m['calls']} ({m['critical_calls']} / {m['serious_calls']} / {m['urgent_calls']})"  # noqa: E731
    lines.append(f"| Calls (critical / serious / urgent) | {counts(base)} | {counts(planb)} | |")
    for key, name in (("serious_within_18_pct", "serious within 18 min"), ("critical_within_target_pct", "critical within target")):
        w = planb.get(f"seeds_{key}")
        if w:
            lines.append(f"| Seeds where Plan B is better / same / worse ({name}) | | | {w['better']} / {w['same']} / {w['worse']} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds", type=int, default=100)
    ap.add_argument("--hours", type=float, default=8.0)
    ap.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 2) - 1)))
    ap.add_argument("--high", type=float, default=1.75, help="high load = this many times the default call rate")
    args = ap.parse_args()
    loads = {"normal": config.CALLS_PER_HOUR, "high": round(config.CALLS_PER_HOUR * args.high, 2)}
    configs = [(name, rate, True) for name, rate in loads.items()] + [("normal_ground_only", loads["normal"], False)]
    print(
        f"Dispatch benchmark: {args.seeds} seeds x {args.hours:g} world-hours, loads {loads} calls/hour; "
        "ROAD_ROUTING=0 (straight-line travel model); engine rules only, no AI"
    )
    jobs = [(p, s, args.hours, rate, heli) for _, rate, heli in configs for s in range(1, args.seeds + 1) for p in ("baseline", "planb")]
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(_job, jobs))
    elapsed = time.time() - t0
    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seeds": args.seeds,
        "hours": args.hours,
        "loads_per_hour": loads,
        "road_routing": False,
        "doctor_cars": any(t["needs_doctor"] for r in results for t in r["trips"]),
        "runtime_s": round(elapsed),
        "results": {},
    }
    md = [
        "# Dispatch benchmark results",
        "",
        f"{args.seeds} seeds × {args.hours:g} world-hours per load, same call sequences for both policies. "
        "Straight-line travel model (ROAD_ROUTING=0). Engine rules only, no AI. Generated by `python tools/benchmark.py`.",
        "",
    ]
    titles = {
        "normal": f"Normal load ({loads['normal']:g} calls per hour)",
        "high": f"High load ({loads['high']:g} calls per hour, {args.high:g}× normal)",
        "normal_ground_only": f"Normal load, ground units only (no helicopter for either policy, {loads['normal']:g} calls per hour)",
    }
    for load, rate, heli in configs:
        runs = [r for r in results if r["per_hour"] == rate and r["helicopter"] == heli]
        base = metrics([r for r in runs if r["policy"] == "baseline"])
        planb = metrics([r for r in runs if r["policy"] == "planb"])
        planb["seeds_serious_within_18_pct"] = per_seed(runs, "serious_within_18_pct", True)
        planb["seeds_critical_within_target_pct"] = per_seed(runs, "critical_within_target_pct", True)
        report["results"][load] = {"per_hour": rate, "helicopter": heli, "baseline": base, "planb": planb}
        md += [table(titles[load], base, planb), ""]
    OUT.mkdir(exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "results.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"\nWritten to {OUT / 'results.md'} and results.json ({elapsed:.0f} s)")


def _job(args: tuple) -> dict:
    return run_once(*args)


if __name__ == "__main__":
    main()
