"""Operational statistics for the Reports page: how well the service is doing, and who decided.

Every world keeps a compact history (bounded, cleared when the world is reset):

- one TripRecord per finished trip, written by the simulator at the moment the trip is completed
  (record_trip, one call, never in a what-if copy of the world), and
- a ring buffer of fleet samples (sample, one call per tick, at most one sample per world-minute)
  from which unit utilisation is approximated.

build_report() turns the history into the JSON of GET /{world}/reports?hours=N. Everything is in
world time (the simulation's clock), exactly like the call timeline. Nothing here changes how the
simulation behaves: a failure while writing a record is logged and swallowed.

Definitions (kept in the response under "method" so the page can state them):
- response time: from the call (its received time; for a trip without a call record the time the
  patient is ready) to the first unit at the patient (the first "on scene" timeline entry). The target
  is the trip's own response_target_min (critical 8 min in the city, 15 outside; serious 18; urgent 60;
  routine has none and is left out of the response statistics).
- doctor on time: a doctor on scene (doctor car, or the helicopter's doctor) within the trip's doctor
  target (15 min) of the call. A call that needed a doctor and never got one counts as not on time.
- late transport: the patient reached the hospital 5 min or more after the trip's due-by time (the same
  threshold as the app's "late" alert).
- who decided: the unit that carried the patient was assigned by the rules engine, by Claude or by the
  dispatcher (last assignment entry of that unit on the timeline). A dispatcher's approval of a
  proposed plan is credited to whoever proposed it; an override is a dispatcher entry that changes a
  unit (kind "override", or a dispatcher "reassigned"/"unit_replaced" that is not part of an approval).
- unit utilisation: the share of samples (one per world-minute, last 24 world-hours kept) in which the
  unit was not idle (driving to a call, on scene, transporting, handing over or returning to base);
  samples while a unit was out of service are left out.
"""
from __future__ import annotations

import logging
import math
import re
import weakref
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .engine.projection import LATE_ALERT_MIN
from .engine.severity import DOCTOR_TARGET_MIN, RESPONSE_TARGET_MIN, SEVERITIES

if TYPE_CHECKING:
    from .models import Trip
    from .state import WorldState

log = logging.getLogger("app.reports")

MAX_RECORDS = 2000  # finished trips kept per world
SAMPLE_EVERY = timedelta(seconds=60)  # world time between fleet samples
MAX_SAMPLES = 1440  # 24 world-hours of samples
MAX_HOURS = 24.0
ASSIGN_KINDS = ("dispatched", "reassigned", "unit_replaced", "override")
NO_CHANGE = re.compile(r"no change|agrees?|confirmed|keeps?\b", re.I)
CHANGE = re.compile(r"chang|instead|swap|moved|replac|redirect", re.I)  # same reading as the case card's badge


@dataclass(slots=True)
class TripRecord:
    trip_id: str
    call_id: str | None
    call_kind: str  # "112" | "hospital_request" | "booking" (no call record)
    received_at: datetime
    completed_at: datetime
    severity: str
    condition: str | None
    response_min: float | None  # call -> first unit at the patient (None: no target, e.g. routine)
    target_min: float | None
    met: bool | None  # response within target (None when there is no target)
    doctor_needed: bool
    doctor_min: float | None  # call -> doctor on scene (None: none arrived)
    doctor_met: bool | None  # None when no doctor was needed
    delay_min: float  # at the hospital vs due-by (0 = on time)
    units: list[str]
    assigned_by: str  # who assigned the carrying unit: engine | claude | dispatcher
    overrides: int  # dispatcher overrides on the call
    claude_reviews: int
    claude_changes: int


class ReportLog:
    """One world's history. It belongs to a world epoch: a reset of the world starts a new, empty one."""

    def __init__(self, epoch: int) -> None:
        self.epoch = epoch
        self.records: OrderedDict[str, TripRecord] = OrderedDict()  # by trip id (a trip is recorded once)
        # (world time, ((vehicle id, type, busy), ...)) of the units in service
        self.samples: deque[tuple[datetime, tuple[tuple[str, str, bool], ...]]] = deque(maxlen=MAX_SAMPLES)


_LOGS: weakref.WeakKeyDictionary[Any, ReportLog] = weakref.WeakKeyDictionary()


def _log(state: WorldState) -> ReportLog:
    entry = _LOGS.get(state)
    if entry is None or entry.epoch != state.epoch:
        entry = _LOGS[state] = ReportLog(state.epoch)
    return entry


# --- Writing: one call where a trip is completed, one per tick --------------------------------------


def sample(state: WorldState) -> None:
    """Remember which units are busy (called at the end of every simulator tick)."""
    if state.is_simulation:
        return
    entry = _log(state)
    if entry.samples and state.sim_time - entry.samples[-1][0] < SAMPLE_EVERY:
        return
    entry.samples.append((
        state.sim_time,
        tuple((v.id, v.type, v.status != "idle") for v in state.vehicles.values() if v.status != "out_of_service"),
    ))


def record_trip(state: WorldState, trip: Trip) -> None:
    """A trip was completed (the patient or the equipment is at the drop-off): add it to the history."""
    if state.is_simulation:  # what-if copies never write
        return
    try:
        rec = _make_record(state, trip)
        entry = _log(state)
        entry.records[trip.id] = rec
        while len(entry.records) > MAX_RECORDS:
            entry.records.popitem(last=False)
    except Exception:  # noqa: BLE001 - statistics must never break the simulation
        log.exception("could not record trip %s", trip.id)


def _actor(by: str | None) -> str:
    by = (by or "").lower()
    if by == "dispatcher":
        return "dispatcher"
    if by == "ai" or by.startswith("claude"):
        return "claude"
    return "engine"  # rules engine, keyword rules, autopilot (the engine approving)


def _minutes(a: datetime, b: datetime) -> float:
    return max(0.0, (a - b).total_seconds() / 60)


def _make_record(state: WorldState, trip: Trip) -> TripRecord:
    tl = trip.timeline
    received = trip.call.received_at if trip.call is not None else trip.pickup_after
    first_on_scene = next((e.at for e in tl if e.kind == "on_scene"), None) or trip.eta_pickup

    target = trip.response_target_min
    response = _minutes(first_on_scene, received) if first_on_scene is not None and target is not None else None
    met = None if response is None or target is None else response <= target

    doctor_at = next((e.at for e in tl if e.kind == "doctor_on_scene"), None)
    holder = state.vehicles.get(trip.doctor_vehicle_id) if trip.doctor_vehicle_id else None
    if doctor_at is None and holder is not None and holder.type == "helicopter":
        doctor_at = first_on_scene  # the helicopter's doctor is on scene with the helicopter
    doctor_min = _minutes(doctor_at, received) if doctor_at is not None else None
    doctor_target = trip.doctor_target_min or DOCTOR_TARGET_MIN
    doctor_met = None if not trip.needs_doctor else (doctor_min is not None and doctor_min <= doctor_target)

    approved_at = {e.at for e in tl if e.kind == "approved"}
    overrides = sum(
        1 for e in tl
        if e.kind == "override" or (e.by == "dispatcher" and e.kind in ("reassigned", "unit_replaced") and e.at not in approved_at)
    )
    reviews = [e for e in tl if e.kind == "reviewed"]
    changes = sum(1 for e in reviews if not NO_CHANGE.search(e.text) and CHANGE.search(e.text))

    assigned_by = "engine"
    mine = [e for e in tl if e.kind in ASSIGN_KINDS and e.vehicle_id == trip.vehicle_id]
    if mine:
        last = mine[-1]
        assigned_by = _actor(last.by)
        if assigned_by == "dispatcher" and last.at in approved_at:  # approved a proposal: credit its author
            proposals = [e for e in tl if e.kind == "proposal"]
            assigned_by = _actor(proposals[-1].by) if proposals else "engine"

    units = [u for u in dict.fromkeys([trip.vehicle_id or "", trip.doctor_vehicle_id or ""]) if u]
    return TripRecord(
        trip_id=trip.id,
        call_id=trip.call.call_id if trip.call is not None else None,
        call_kind=trip.call.kind if trip.call is not None else "booking",
        received_at=received,
        completed_at=state.sim_time,
        severity=trip.severity or "routine",
        condition=trip.condition,
        response_min=response,
        target_min=target,
        met=met,
        doctor_needed=trip.needs_doctor,
        doctor_min=doctor_min,
        doctor_met=doctor_met,
        delay_min=float(trip.delay_min or 0.0),
        units=units,
        assigned_by=assigned_by,
        overrides=overrides,
        claude_reviews=len(reviews),
        claude_changes=changes,
    )


# --- Reading: GET /{world}/reports ------------------------------------------------------------------


def _share(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 1) if whole else None


def _quantile(sorted_values: list[float], q: float) -> float | None:
    """Linear interpolation between the closest ranks (q in 0..1)."""
    if not sorted_values:
        return None
    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return round(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo), 1)


def _by_severity(recs: list[TripRecord]) -> list[dict[str, Any]]:
    out = []
    for sev in SEVERITIES:
        mine = [r for r in recs if r.severity == sev]
        if not mine:
            continue
        timed = sorted((r for r in mine if r.response_min is not None), key=lambda r: r.response_min or 0.0)
        values = [r.response_min for r in timed if r.response_min is not None]
        out.append({
            "severity": sev,
            "n": len(mine),
            "n_timed": len(timed),  # calls with a response target (the statistics below use these)
            "target_min": RESPONSE_TARGET_MIN.get(sev),  # nominal; a critical call outside the city has 15 min
            "median_response": _quantile(values, 0.5),
            "p90_response": _quantile(values, 0.9),
            "pct_within_target": _share(sum(1 for r in timed if r.met), len(timed)),
            "responses": [{"min": round(r.response_min or 0.0, 1), "target": r.target_min, "met": bool(r.met)} for r in timed],
        })
    return out


def _doctor(recs: list[TripRecord]) -> dict[str, Any]:
    needed = [r for r in recs if r.doctor_needed]
    times = sorted(r.doctor_min for r in needed if r.doctor_min is not None)
    return {
        "n": len(needed),
        "target_min": DOCTOR_TARGET_MIN,
        "pct_within_15": _share(sum(1 for r in needed if r.doctor_met), len(needed)),
        "median": _quantile(times, 0.5),
        "none_arrived": sum(1 for r in needed if r.doctor_min is None),
    }


def _utilisation(entry: ReportLog, since: datetime) -> list[dict[str, Any]]:
    busy: dict[str, list[int]] = {}  # vehicle id -> [busy samples, samples]
    kind: dict[str, str] = {}
    for at, units in entry.samples:
        if at < since:
            continue
        for vid, vtype, is_busy in units:
            kind[vid] = vtype
            counts = busy.setdefault(vid, [0, 0])
            counts[0] += is_busy
            counts[1] += 1
    return [
        {"vehicle_id": vid, "type": kind[vid], "busy_pct": _share(b, n), "samples": n}
        for vid, (b, n) in busy.items()
    ]


def _hourly(recs: list[TripRecord], since: datetime, now: datetime) -> list[dict[str, Any]]:
    """Calls closed per world-hour (clock hours, oldest first, empty hours included) and how many of the
    timed ones met their target. The first and the last hour of the window may be partial."""
    if not recs:
        return []
    first = since.replace(minute=0, second=0, microsecond=0)
    hours: list[datetime] = []
    h = first
    while h <= now:
        hours.append(h)
        h += timedelta(hours=1)
    out = []
    for h in hours:
        mine = [r for r in recs if h <= r.completed_at < h + timedelta(hours=1)]
        timed = [r for r in mine if r.met is not None]
        within = sum(1 for r in timed if r.met)
        out.append({
            "hour": h.isoformat(),
            "calls": len(mine),
            "timed": len(timed),  # calls with a response target
            "within_target": within,
            "pct_within_target": _share(within, len(timed)),
            "partial": h < since or now < h + timedelta(hours=1),  # only part of this hour is in the window / has happened
        })
    return out


def _ai(recs: list[TripRecord]) -> dict[str, Any]:
    n = len(recs)
    overridden = {r.trip_id for r in recs if r.overrides or r.assigned_by == "dispatcher"}
    changed = {r.trip_id for r in recs if r.claude_changes} - overridden
    agreed = {r.trip_id for r in recs if r.claude_reviews} - overridden - changed
    engine_only = n - len(overridden) - len(changed) - len(agreed)
    return {
        "calls": n,
        "dispatched_by_engine": sum(1 for r in recs if r.assigned_by == "engine"),
        "dispatched_by_claude": sum(1 for r in recs if r.assigned_by == "claude"),
        "dispatched_by_dispatcher": sum(1 for r in recs if r.assigned_by == "dispatcher"),
        "reviewed_by_claude": sum(1 for r in recs if r.claude_reviews),
        "changed_by_claude": sum(1 for r in recs if r.claude_changes),
        "dispatcher_overrides": sum(r.overrides for r in recs),
        # every closed call in exactly one group, by the last word on it (the groups add up to calls)
        "decided": {
            "engine_only": engine_only,
            "claude_agreed": len(agreed),
            "claude_changed": len(changed),
            "dispatcher_overrode": len(overridden),
        },
        "autonomous_share": _share(n - len(overridden), n),  # calls with no dispatcher intervention
    }


def build_report(state: WorldState, hours: float = 3.0) -> dict[str, Any]:
    hours = float(hours)
    hours = min(max(hours, 0.25), MAX_HOURS) if math.isfinite(hours) else 3.0  # ?hours=nan would 500
    entry = _log(state)
    now = state.sim_time
    since = now - timedelta(hours=hours)
    recs = [r for r in entry.records.values() if r.completed_at >= since]
    open_trips = sum(1 for t in state.trips.values() if t.status not in ("completed", "cancelled"))
    late = [r for r in recs if r.delay_min >= LATE_ALERT_MIN]
    return {
        "world": state.name,
        "window": {"hours": hours, "from": since.isoformat(), "to": now.isoformat()},
        "totals": {"calls": len(recs) + open_trips, "closed": len(recs), "open": open_trips},
        "by_severity": _by_severity(recs),
        "doctor": _doctor(recs),
        "transports": {
            "n": len(recs),
            "late": len(late),
            "late_pct": _share(len(late), len(recs)),
            "late_after_min": LATE_ALERT_MIN,
            "avg_delay_min": round(sum(r.delay_min for r in recs) / len(recs), 1) if recs else None,
        },
        "utilisation": _utilisation(entry, since),
        "ai": _ai(recs),
        "hourly": _hourly(recs, since, now),
        "method": {
            "response": "call to first unit at the patient, against the call's own target",
            "utilisation": "share of one-per-world-minute samples with the unit not idle; out-of-service time left out",
            "autonomous_share": "closed calls with no dispatcher override or manual assignment",
        },
    }
