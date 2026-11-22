"""The ER read model: one case per patient trip bound for an ER place, derived from trips and the log.

Everything here is computed on every read from the world's trips and the clinical log; nothing is
stored and nothing is written (the log, the trips and the version are left untouched). The three
screens (dispatch, tablet, ER) read this one projection, so they cannot disagree.

A card is a plain JSON-safe dict whose keys never change shape. `handover`, `suggested_actions` and
`alert_ids` are filled in `build_case` itself (the alert rules are in alerts.py), and the board's
`alerts` come from the same rules over the same cards, so a card built alone is identical to the
same case's card on the board.
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from ..engine.projection import DONE
from ..models import Trip
from ..state import SNAPSHOT_DONE_HOURS
from . import config
from .alerts import compute_alerts, handover_timer, suggested_actions
from .models import ClinicalEntry
from .store import get_log

if TYPE_CHECKING:  # type only, as in store.py
    from ..state import WorldState

logger = logging.getLogger(__name__)


# --- Which trips are cases ---------------------------------------------------------------------

def er_case_trips(state: WorldState) -> list[Trip]:
    """Patient trips ending at an ER place that are not cancelled and are open, or finished within the
    snapshot's window (the same rule the snapshot uses for finished trips)."""
    horizon = state.sim_time - timedelta(hours=SNAPSHOT_DONE_HOURS)
    return [
        t
        for t in state.trips.values()
        if t.kind == "patient"
        and t.dropoff_id in config.ER_PLACE_IDS
        and t.status != "cancelled"
        and (t.status not in DONE or (t.eta_dropoff is not None and t.eta_dropoff >= horizon))
    ]


# --- Reading entries ---------------------------------------------------------------------------

def _observed(e: ClinicalEntry) -> datetime:
    return e.observed_t or e.t


def _order(e: ClinicalEntry) -> tuple[datetime, int]:
    """"Latest" always means latest observed, the arrival order (seq) breaking a tie."""
    return (_observed(e), e.seq)


def _live(state: WorldState, entries: list[ClinicalEntry]) -> list[ClinicalEntry]:
    """The entries no later entry replaced, oldest observation first."""
    replaced = get_log(state).superseded_ids()
    return sorted((e for e in entries if e.entry_id not in replaced), key=_order)


def _latest(live: list[ClinicalEntry], entry_type: str) -> ClinicalEntry | None:
    return next((e for e in reversed(live) if e.type == entry_type), None)


def _when(value: datetime | str | None) -> str | None:
    """A time as ISO text. Times inside stored content are already text (JSON mode); they are
    re-written the same way as the entry's own times so one card never mixes two spellings."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        return datetime.fromisoformat(value).isoformat()
    except ValueError:
        return value


# --- Stage -------------------------------------------------------------------------------------

def _stage(state: WorldState, trip: Trip, live: list[ClinicalEntry]) -> tuple[str | None, bool]:
    kinds = {e.type for e in live}
    if "free" in kinds:
        return "PROST", False
    if "handover" in kinds:
        return "PREDAJA PACIENTA", False
    if trip.status == "completed":
        return "NA CILJU", False
    vehicle = state.vehicles.get(trip.vehicle_id) if trip.vehicle_id else None
    if trip.status == "onboard":  # the vehicle state cannot say "at the patient" exactly: marked inferred
        return ("PRI PACIENTU" if vehicle is not None and vehicle.status == "loading" else "S KRAJA"), True
    if trip.status == "en_route_pickup":
        return ("NA KRAJU" if vehicle is not None and vehicle.waiting_until is not None else "NA POTI"), True
    if trip.status == "assigned":
        return "SPREJETO", False
    return None, False


def stage_of(state: WorldState, trip: Trip, entries: list[ClinicalEntry]) -> tuple[str | None, bool]:
    """(stage, inferred) for a case. `entries` are the case's entries; replaced ones are ignored.

    A `free` entry means the unit is free again; else a `handover` entry means the patient was handed
    over; else the trip and its vehicle say where the unit is. The trip alone never reaches the last
    two stages, because the simulator marks it completed the moment it arrives.
    """
    return _stage(state, trip, _live(state, entries))


# --- Card --------------------------------------------------------------------------------------

def _level(trip: Trip, live: list[ClinicalEntry]) -> dict[str, Any]:
    triage = _latest(live, "triage")
    if triage is not None:
        return {"value": triage.content["level"], "inferred": False, "source": triage.source}
    return {"value": config.LEVEL_BY_PRIORITY.get(trip.priority), "inferred": True, "source": None}


def _problem_type(live: list[ClinicalEntry]) -> str | None:
    """The latest problem type any triage named. A later triage that only re-sets the level carries
    the default "other", which must not wipe a problem type already given. "other" when triage
    exists but names none, None when there is no triage at all."""
    triages = [e for e in live if e.type == "triage"]
    if not triages:
        return None
    for e in reversed(triages):
        problem = e.content.get("problem_type")
        if problem is not None and problem != "other":
            return problem
    return "other"


def _vitals(state: WorldState, live: list[ClinicalEntry]) -> dict[str, dict[str, Any]]:
    """The latest reading of each metric. A partial entry only replaces the metrics it carries."""
    latest: dict[str, ClinicalEntry] = {}
    for e in live:  # oldest observation first, so a later one overwrites
        if e.type != "vitals":
            continue
        for metric, value in e.content.items():
            if value is not None:
                latest[metric] = e
    return {
        metric: {
            "value": e.content[metric],  # shown exactly as entered, implausible or not
            "age_min": round((state.sim_time - _observed(e)).total_seconds() / 60, 1),
            "state": e.state,
            "needs_check": e.needs_check,  # as flagged when the entry was stored
            "seq": e.seq,
        }
        for metric, e in latest.items()
    }


def _patient_field(live: list[ClinicalEntry], name: str) -> Any:
    for e in reversed(live):
        if e.type == "patient_info" and e.content.get(name) is not None:
            return e.content[name]
    return None


def _teams(live: list[ClinicalEntry]) -> list[str]:
    teams: list[str] = []
    for e in live:
        team = e.content.get("team") if e.type == "er_action" and e.content.get("action") == "team_activated" else None
        if team is not None and team not in teams:
            teams.append(team)
    return teams


def _bay(live: list[ClinicalEntry]) -> str | None:
    bays = [e for e in live if e.type == "er_action" and e.content.get("action") == "bay_assigned"]
    return bays[-1].content.get("bay") if bays else None


def build_case(state: WorldState, trip: Trip, entries: list[ClinicalEntry]) -> dict[str, Any]:
    """One card. `entries` are the case's entries (as the log returns them); replaced ones are ignored."""
    live = _live(state, entries)
    stage, inferred = _stage(state, trip, live)
    severity = _latest(live, "severity")  # the on-scene severity entry, not the trip's own dispatch level
    arrived = trip.eta_dropoff if trip.status == "completed" else None
    minutes_to_arrival = None
    if arrived is None and trip.eta_dropoff is not None:
        minutes_to_arrival = max(0.0, round((trip.eta_dropoff - state.sim_time).total_seconds() / 60, 1))
    card = {
        "case_id": trip.id,
        "vehicle_id": trip.vehicle_id,
        "patient_label": trip.label,
        "priority": trip.priority,
        "level": _level(trip, live),
        "problem": {"type": _problem_type(live), "note": trip.note},
        "age_years": _patient_field(live, "age_years"),
        "sex": _patient_field(live, "sex"),
        "eta_dropoff": _when(trip.eta_dropoff),
        "minutes_to_arrival": minutes_to_arrival,
        "arrived_at": _when(arrived),
        "stage": stage,
        "stage_inferred": inferred,
        "severity": severity.content["value"] if severity else None,
        "vitals": _vitals(state, live),
        "treatments": [
            {
                "seq": e.seq,
                "type": e.type,
                "content": copy.deepcopy(e.content),
                "observed_t": _when(_observed(e)),
                "state": e.state,
                "needs_check": e.needs_check,
            }
            for e in live
            if e.type in ("drug_administered", "procedure")
        ],
        "events": [
            {
                "kind": e.content["kind"],
                "observed_t": _when(_observed(e)),
                "onset_t": _when(e.content.get("onset_t")),
                "state": e.state,
            }
            for e in live
            if e.type == "event"
        ],
        "acknowledged": any(e.type == "er_action" and e.content.get("action") == "acknowledge" for e in live),
        "bay": _bay(live),
        "teams_activated": _teams(live),
        "handover": handover_timer(state, arrived, _latest(live, "handover")),
        "suggested_actions": [],  # filled below, from the card itself
        "alert_ids": [],  # filled below, from the alerts of this one case
    }
    card["suggested_actions"] = suggested_actions(card)
    card["alert_ids"] = [a["id"] for a in compute_alerts(state, [card])]
    return card


# --- Board -------------------------------------------------------------------------------------

def _board_order(state: WorldState, trips: list[Trip]) -> list[Trip]:
    """Cases still to arrive first, soonest first (those with no ETA, such as unassigned, last);
    then the arrived ones, the most recent arrival first."""
    pending = [t for t in trips if t.status != "completed"]
    arrived = [t for t in trips if t.status == "completed"]
    pending.sort(key=lambda t: (t.status == "unassigned" or t.eta_dropoff is None, t.eta_dropoff or state.sim_time, t.id))
    arrived.sort(key=lambda t: (t.eta_dropoff or state.sim_time, t.id), reverse=True)
    return pending + arrived


def board(state: WorldState) -> dict[str, Any]:
    log = get_log(state)
    cases = [build_case(state, t, log.for_case(t.id)) for t in _board_order(state, er_case_trips(state))]
    return {
        "world": state.name,
        "as_of": state.sim_time.isoformat(),
        "seq": log.last_seq,
        "cases": cases,
        "alerts": compute_alerts(state, cases),  # the same rules over the same cards as each card's alert_ids
        "entries_tail": [e.model_dump(mode="json") for e in log.tail(config.SNAPSHOT_TAIL)],
    }


def snapshot_extra(state: WorldState) -> dict[str, Any]:
    """The `clinical` section for the shared snapshot. It must never break the snapshot: any failure
    becomes an error note in the section instead. `{}` (no section at all) when switched off."""
    if not config.enabled():
        return {}
    try:
        return {"clinical": board(state)}  # looked up by name on each call, so a test can swap it
    except Exception as exc:  # noqa: BLE001
        logger.exception("clinical board projection failed")
        return {"clinical": {"error": f"{type(exc).__name__}: {exc}"[:200]}}
