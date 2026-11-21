"""The rules every clinical entry must pass, and the one way to write: append, audit mirror, version bump.

Routes and the crew simulator both call record_entry, so a rule lives here once. A refused entry
raises ClinicalError and changes nothing (no seq taken, no audit line, no version bump); the API
layer turns `.status` and `.message` into the HTTP response. Like the rest of the world state this
runs on one event loop with no awaits, so check-then-append below cannot interleave.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ..audit import AUDIT
from ..models import Trip, utcnow
from . import config
from .models import ENTRY_IN, ClinicalEntry, EntryBase, ERActionIn, EventIn, Source, needs_check
from .store import ClinicalLog, get_log

if TYPE_CHECKING:  # type only, as in store.py
    from ..state import WorldState


class ClinicalError(Exception):
    """A rule refused the entry. `status` is the HTTP status to answer with, `message` says why."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def case_trip(state: WorldState, case_id: str) -> Trip:
    """The patient trip a case id names: 404 when there is none, 422 for an equipment transport."""
    trip = state.trips.get(case_id)
    if trip is None:
        raise ClinicalError(404, f"No case {case_id!r} in this world.")
    if trip.kind != "patient":
        raise ClinicalError(422, f"Case {case_id} is an equipment transport; clinical entries belong to patient cases.")
    return trip


def case_start(trip: Trip) -> datetime:
    """When the case began in world time: the engine's own dispatch, else when the patient was ready."""
    return trip.dispatched_at or trip.pickup_after


def _check_unit(entry: EntryBase, trip: Trip) -> None:
    """A crew entry must come from the vehicle on the case now; an old vehicle is refused after reassignment."""
    if entry.source not in config.CREW_SOURCES or entry.unit == trip.vehicle_id:
        return
    if trip.vehicle_id is None:
        raise ClinicalError(409, f"Case {trip.id} has no vehicle assigned, so a crew entry from {entry.unit} cannot be accepted.")
    raise ClinicalError(409, f"Case {trip.id} is assigned to vehicle {trip.vehicle_id}, not {entry.unit}.")


def _check_times(entry: EntryBase, trip: Trip, now: datetime) -> None:
    observed = entry.observed_t
    if observed is not None:
        if observed > now:
            raise ClinicalError(422, f"observed_t {observed.isoformat()} is in the future (world time is {now.isoformat()}).")
        started = case_start(trip)
        if observed < started:
            raise ClinicalError(422, f"observed_t {observed.isoformat()} is before case {trip.id} began ({started.isoformat()}).")
    # The onset of a stroke may well precede the call, but it cannot lie ahead of now.
    if isinstance(entry, EventIn) and entry.content.kind == "stroke_onset":
        onset = entry.content.onset_t
        if onset is not None and onset > now:
            raise ClinicalError(422, f"onset_t {onset.isoformat()} is in the future (world time is {now.isoformat()}).")


def _check_supersedes(entry: EntryBase, log: ClinicalLog) -> None:
    if entry.supersedes is None:
        return
    on_case = log.for_case(entry.case_id)  # looked up by entry_id on this case only: another case's entry is "no such entry"
    target = next((e for e in on_case if e.entry_id == entry.supersedes), None)
    if target is None:
        raise ClinicalError(422, f"supersedes {entry.supersedes!r} names no entry on case {entry.case_id}.")
    if target.entry_id in log.superseded_ids():
        newer = next((e.entry_id for e in on_case if e.supersedes == target.entry_id), None)
        by = f" by {newer}" if newer else ""
        raise ClinicalError(409, f"Entry {target.entry_id} was already superseded{by}; correct the newer entry instead.")


def record_entry(state: WorldState, entry: EntryBase) -> tuple[ClinicalEntry, bool]:
    """Apply every rule, then store. Returns (stored entry, True), or (the earlier entry, False) for a replay."""
    log = get_log(state)
    if entry.client_entry_id is not None:  # a replay of what this unit already sent: nothing else is looked at
        earlier = log.by_client_id(entry.unit, entry.client_entry_id)
        if earlier is not None:
            return earlier, False

    trip = case_trip(state, entry.case_id)
    _check_unit(entry, trip)
    if isinstance(entry, ERActionIn) and entry.source != "er_reception":
        raise ClinicalError(422, f"An er_action can only be recorded by er_reception, not {entry.source}.")
    now = state.sim_time
    _check_times(entry, trip, now)
    _check_supersedes(entry, log)

    dumped = entry.model_dump(mode="json")  # content becomes plain JSON (times as ISO strings), as entered
    stored = log.append(
        {
            "case_id": entry.case_id,
            "type": dumped["type"],
            "content": dumped["content"],
            "unit": entry.unit,
            "source": entry.source,
            "state": entry.state,
            "t": now,
            "observed_t": entry.observed_t or now,
            "recorded_at": utcnow(),
            "verbatim": entry.verbatim,
            "confidence": entry.confidence,
            "supersedes": entry.supersedes,
            "needs_check": needs_check(dumped["type"], dumped["content"]),
            "client_entry_id": entry.client_entry_id,
        }
    )
    AUDIT.record(
        state.name,
        "clinical",
        f"{stored.type} on {stored.case_id} from {stored.unit} ({stored.source}, {stored.state})",
        ref=stored.entry_id,
        payload=stored,
    )
    state.bump()
    return stored, True


def confirm_entry(state: WorldState, seq: int, unit: str, source: Source = "crew_tap") -> ClinicalEntry:
    """Record a confirmed copy of entry `seq` that supersedes it (a tap on "heard" or "inferred").

    It is a new entry like any other, so it passes the same rules: `unit` must be the case's vehicle
    for a crew source, and an entry that was already replaced cannot be confirmed (409).
    """
    original = get_log(state).get(seq)
    if original is None:
        raise ClinicalError(404, f"No clinical entry with seq {seq}.")
    try:
        copy = ENTRY_IN.validate_python(
            {
                "case_id": original.case_id,
                "unit": unit,
                "source": source,
                "type": original.type,
                "content": original.content,
                "state": "confirmed",
                "observed_t": original.observed_t,
                "verbatim": original.verbatim,
                "confidence": original.confidence,
                "supersedes": original.entry_id,
                # no client_entry_id: the copy is a new entry, not a replay of the original's id
            }
        )
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ClinicalError(422, f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}") from exc
    stored, _ = record_entry(state, copy)
    return stored
