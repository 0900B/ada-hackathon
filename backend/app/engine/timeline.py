"""The call timeline: everything that happens to a trip, from the first second to the end.

Every trip has a bounded list of entries (Trip.timeline): received, triaged, dispatched, doctor
dispatched, rerouted, reassigned, delayed, unit replaced, proposal, approved, reviewed (the AI
dispatcher kept the decision), override (the dispatcher changed it), on scene, doctor on scene,
transporting, at hospital, handover done, closed, note. Each says when (world time), who (`by`: caller,
ai, rules, engine, dispatcher, crew), the source in a few words (`detail`: "rules engine, 0.1 s",
"Claude, 12 s, checked by the engine", "dispatcher override") and what, in one line.

Entries are written only in the real world: what-if copies (state.is_simulation) share the list with
the real trip and never write it. Changes made by events, plans and the automatic follow-up are
logged by comparing the trips before and after (Tracker); the simulator logs the crew's progress.
Every decision entry also counts in the world's ai_stats (dispatched, reroutes, reassignments).
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ..models import TimelineEntry, Trip
from . import units

if TYPE_CHECKING:
    from ..state import WorldState

LJ = ZoneInfo("Europe/Ljubljana")
MAX_ENTRIES = 40  # per trip; the first KEEP_FIRST (received, triaged) always stay
KEEP_FIRST = 2
DONE = ("completed", "cancelled")


def hhmm(dt: datetime | None) -> str:
    return dt.astimezone(LJ).strftime("%H:%M") if dt else "?"


DEFAULT_DETAIL = {
    "caller": "112 call",
    "rules": "keyword rules",
    "ai": "Claude",
    "engine": "rules engine",
    "dispatcher": "dispatcher",
    "crew": "crew / vehicle GPS",
}
# Timeline kinds counted in ai_stats, and the kinds that are decisions (last_decision_at).
COUNTED = {"dispatched": "dispatched", "rerouted": "reroutes", "reassigned": "reassignments", "unit_replaced": "reassignments"}
DECISIONS = {"dispatched", "doctor_dispatched", "rerouted", "reassigned", "unit_replaced", "approved", "reviewed", "override"}


def engine_detail(seconds: float, what: str = "rules engine") -> str:
    """"rules engine, 0.3 s"; "rules engine, <0.1 s" when it took under 50 ms (not "0.0 s")."""
    return f"{what}, <0.1 s" if seconds < 0.05 else f"{what}, {seconds:.1f} s"


def log(
    state: WorldState,
    trip: Trip | None,
    kind: str,
    by: str,
    text: str,
    vehicle_id: str | None = None,
    run_id: str | None = None,
    at: datetime | None = None,
    detail: str | None = None,
    unit_before: str | None = None,
    eta_before: datetime | None = None,
    eta_after: datetime | None = None,
    eta_of: str | None = None,
) -> None:
    """Add one entry to the trip's timeline (real world only)."""
    if trip is None or state.is_simulation:
        return
    entry = TimelineEntry(
        at=at or state.sim_time, kind=kind, by=by, text=text[:300], vehicle_id=vehicle_id, run_id=run_id,  # type: ignore[arg-type]
        detail=(detail or DEFAULT_DETAIL.get(by, by))[:80], unit_before=unit_before, eta_before=eta_before,
        eta_after=eta_after, eta_of=eta_of,  # type: ignore[arg-type]
    )
    trip.timeline.append(entry)
    if len(trip.timeline) > MAX_ENTRIES:
        del trip.timeline[KEEP_FIRST : len(trip.timeline) - (MAX_ENTRIES - KEEP_FIRST)]
    stats = getattr(state, "ai_stats", None)
    if stats is not None:
        if kind in COUNTED:
            stats[COUNTED[kind]] += 1
        if kind in DECISIONS:
            stats["last_decision_at"] = state.sim_time
    state.bump()


def has(trip: Trip, kind: str) -> bool:
    return any(e.kind == kind for e in trip.timeline)


def clause(summary: str | None, *starts: str) -> str | None:
    """The part of an event summary ("...; dispatched A1 (nearest free ambulance): at ...; ...") that
    starts with one of these words, capitalised; None if there is none."""
    if not summary:
        return None
    for part in _clauses(summary):
        p = part.strip()
        for s in starts:
            if p.startswith(s):
                return p[:1].upper() + p[1:]
    return None


def _clauses(summary: str) -> list[str]:
    """The summary split at "; ", but not inside parentheses: "dispatched H1 (helicopter, ...; take-off in
    13 min): at the patient 11:20" stays one clause."""
    out, depth, start, i = [], 0, 0, 0
    while i < len(summary):
        ch = summary[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and summary.startswith("; ", i):
            out.append(summary[start:i])
            start = i + 2
            i += 2
            continue
        i += 1
    out.append(summary[start:])
    return out


def _who(trip: Trip) -> str:
    return "the patient" if trip.kind == "patient" else "the pickup"


def milestone(trip: Trip) -> tuple[datetime | None, str]:
    """The trip's next arrival and what it is: at the patient (or the pickup), or at the hospital once the
    patient is on board."""
    if trip.status == "onboard":
        return trip.eta_dropoff, "hospital"
    reach = max(trip.eta_pickup, trip.pickup_after) if trip.eta_pickup else None
    return reach, "patient" if trip.kind == "patient" else "pickup"


REPLAN_KINDS = ("unit_replaced", "reassigned", "rerouted", "delayed", "note")


def mark_disruption(
    state: WorldState, event_id: str, text: str, by: str, marks: dict[str, tuple[int, datetime | None]],
) -> None:
    """A disruption hit open 112 calls: put a "disruption" entry before what the event logged on each call
    it touched, tag those entries with the event, and give them the arrival before and after (the case
    card's re-plan box). A call whose arrival moved by a minute or more without any entry gets one.
    marks: trip id -> (timeline length, next arrival) taken before the event."""
    if state.is_simulation:
        return
    for tid, (n0, eta0) in marks.items():
        trip = state.trips.get(tid)
        if trip is None or trip.status in DONE:
            continue
        eta1, of = milestone(trip)
        moved = eta0 is not None and eta1 is not None and abs((eta1 - eta0).total_seconds()) >= 60
        n0 = min(n0, len(trip.timeline))
        new = trip.timeline[n0:]
        if not new and not moved:
            continue
        for e in new:
            e.event_id = event_id
            if e.kind in REPLAN_KINDS and e.eta_before is None and eta0 is not None and eta1 is not None:
                e.eta_before, e.eta_after, e.eta_of = eta0, eta1, of  # type: ignore[assignment]
        if not new:
            mins = (eta1 - eta0).total_seconds() / 60  # type: ignore[operator]
            log(state, trip, "delayed", "engine", f"Arrival {'later' if mins > 0 else 'earlier'} by {abs(mins):.0f} min",
                trip.vehicle_id, eta_before=eta0, eta_after=eta1, eta_of=of)
            trip.timeline[-1].event_id = event_id
        head = TimelineEntry(at=state.sim_time, kind="disruption", by=by, text=text[:200],  # type: ignore[arg-type]
                             vehicle_id=None, detail=DEFAULT_DETAIL.get(by, by), event_id=event_id)
        trip.timeline.insert(n0, head)
        if len(trip.timeline) > MAX_ENTRIES:
            del trip.timeline[KEEP_FIRST : len(trip.timeline) - (MAX_ENTRIES - KEEP_FIRST)]
    state.bump()


class Tracker:
    """Remembers who serves which trip, then logs what changed (vehicle, doctor, destination)."""

    def __init__(self, state: WorldState) -> None:
        self.state = state
        self.detail: str | None = None
        self.before = {
            t.id: (t.vehicle_id, t.doctor_vehicle_id, t.dropoff_id, t.status)
            for t in state.trips.values()
            if t.status not in DONE
        }
        self.eta = {t.id: milestone(t)[0] for t in state.trips.values() if t.status not in DONE}

    def keep(self, trip: Trip) -> None:
        """Treat trip's current units as already logged (the caller wrote its own entry)."""
        self.before[trip.id] = (trip.vehicle_id, trip.doctor_vehicle_id, trip.dropoff_id, trip.status)
        self.eta[trip.id] = milestone(trip)[0]

    def log_changes(
        self, by: str, summary: str | None = None, created: list[str] | None = None, detail: str | None = None
    ) -> list[str]:
        """Log the changes since the Tracker was made. summary: the event's summary (its dispatch
        clauses become the entries' text); detail: the entries' source text. Returns the ids of the
        trips that changed. A unit without a reason written by the decision gets a plain one."""
        state = self.state
        if state.is_simulation:
            return []
        self.detail = detail
        changed: list[str] = []
        for t in list(state.trips.values()):
            if t.id in self.before:
                vid, doc, drop, _status = self.before[t.id]
            elif created and t.id in created:
                vid, doc, drop, _status = None, None, t.dropoff_id, "unassigned"
            else:
                continue
            if t.status in DONE:
                continue
            moved = False
            if t.vehicle_id != vid:
                moved = True
                self._vehicle_change(t, vid, by, summary)
            if t.doctor_vehicle_id != doc:
                moved = True
                self._doctor_change(t, doc, by)
            if t.dropoff_id != drop:
                moved = True
                log(state, t, "rerouted", by, f"Redirected to {state.places[t.dropoff_id].name}"
                    + (f" (was {state.places[drop].name})" if drop in state.places else ""), t.vehicle_id, detail=detail)
            if moved:
                changed.append(t.id)
        return changed

    def _note(self, t: Trip, vehicle_id: str, by: str, reason: str) -> None:
        """A plain reason for a unit whose decision wrote none (e.g. moved by surge activation)."""
        if not units.fresh(self.state, t, vehicle_id):
            units.note(self.state, t, vehicle_id, reason, by if by in ("ai", "dispatcher") else "engine")

    def _vehicle_change(self, t: Trip, old: str | None, by: str, summary: str | None) -> None:
        state = self.state
        new = t.vehicle_id
        old_v = state.vehicles.get(old) if old else None
        down = old_v is not None and old_v.status == "out_of_service"
        detail = self.detail
        if new is None:
            why = "out of service" if down else "released"
            log(state, t, "note", by, f"{old} {why}: waiting for another unit" if old else "No unit yet", old, detail=detail)
            return
        reach = max(t.eta_pickup, t.pickup_after) if t.eta_pickup and t.status != "onboard" else None
        when = f": at {_who(t)} {hhmm(reach)}" if reach else ""
        found = clause(summary, f"dispatched {new}", f"placed on {new}", f"re-evaluated: dispatched {new}")
        generic = {"ai": "AI dispatcher (Claude)", "dispatcher": "dispatcher's plan"}.get(by, "assigned by the engine")
        if old is None:
            log(state, t, "dispatched", by, found or f"{new} dispatched{when}", new, detail=detail)
            self._note(t, new, by, generic)
        else:
            eta_after, of = milestone(t)
            eta = {"unit_before": old, "eta_before": self.eta.get(t.id), "eta_after": eta_after, "eta_of": of}
            if down:
                log(state, t, "unit_replaced", by, f"{old} out of service: {new} sent instead{when}", new, detail=detail, **eta)
                self._note(t, new, by, f"replaces {old} (out of service)")
            else:
                log(state, t, "reassigned", by, f"Reassigned from {old} to {new}{when}", new, detail=detail, **eta)
                self._note(t, new, by, f"{generic}, instead of {old}")

    def _doctor_change(self, t: Trip, old: str | None, by: str) -> None:
        state = self.state
        new = t.doctor_vehicle_id
        new_v = state.vehicles.get(new) if new else None
        old_v = state.vehicles.get(old) if old else None
        detail = self.detail
        if new_v is not None and new_v.type == "doctor":
            at = f", at {_who(t)} {hhmm(t.doctor_eta)}" if t.doctor_eta else ""
            if old_v is not None and old_v.type == "doctor" and old_v.status == "out_of_service":
                log(state, t, "doctor_dispatched", by, f"Doctor car {old} out of service: doctor car {new} sent instead{at}", new, detail=detail)
                self._note(t, new_v.id, by, f"replaces doctor car {old} (out of service)")
            else:
                log(state, t, "doctor_dispatched", by, f"Doctor car {new} sent{at}", new, detail=detail)
                self._note(t, new_v.id, by, f"doctor needed for {(t.condition_label or 'this call').lower()}")
        elif new_v is not None and new_v.type == "helicopter":
            if old_v is not None and old_v.type == "doctor":
                log(state, t, "note", by, f"Doctor on board {new}: doctor car {old} stood down", new, detail=detail)
        elif new is None and old_v is not None and old_v.type == "doctor":
            why = "out of service" if old_v.status == "out_of_service" else "stood down"
            log(state, t, "note", by, f"Doctor car {old} {why}", old, detail=detail)
