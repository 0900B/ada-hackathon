"""ER alerts, the handover timer and suggested actions: rules over the cards, never writes.

Everything is derived on every read from a card (and the world clock), so an alert appears when its
condition holds and disappears when it stops; nothing is stored. Alerts carry stable ids
(`er:<case_id>:<rule>`) so a client can diff two reads. Nothing here ever records an entry: a
suggestion is only a suggestion, and performing one is a reception decision.

`compute_alerts` is a pure function of (state, cards): the same card gives the same alert alone or
among others. The projection calls it with the one card while building that card, and with every
card for the board, so a card and the board cannot disagree.

The thresholds live in config.py; the PLACEHOLDER ones there are not clinical guidance.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from . import config
from .models import ClinicalEntry
from .store import get_log

if TYPE_CHECKING:  # type only, as in store.py
    from ..state import WorldState

SEVERITIES = ("critical", "high", "medium", "low")  # most urgent first: the order of the alert list

# Alerts raised by an event on the case: (rule, severity, {event kind: message}). The earliest
# matching event gives the message and the `since`; one alert per rule however many events match.
EVENT_RULES: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("arrest", "critical", {"arrest": "Cardiac arrest reported", "resuscitation_started": "Resuscitation started"}),
    ("rosc", "high", {"rosc": "Return of spontaneous circulation (ROSC) reported"}),
    ("airway", "high", {"airway": "Airway procedure reported"}),
    ("stemi", "high", {"stemi": "STEMI reported"}),
    ("transfusion", "high", {"transfusion": "Transfusion reported"}),
)

# The team an event calls for: event kind -> (team, why), in the order teams are suggested. Teams
# must be rows of config.TEAMS.
TEAM_BY_EVENT: dict[str, tuple[str, str]] = {
    "arrest": ("resuscitation_room", "arrest reported"),
    "resuscitation_started": ("resuscitation_room", "resuscitation started"),
    "stemi": ("heart", "STEMI reported"),
    "stroke_onset": ("stroke", "stroke onset reported"),
}

_ARRIVED = frozenset(config.STAGES[config.STAGES.index("NA CILJU"):])  # NA CILJU and everything after
_BEFORE_ARRIVAL = frozenset(config.STAGES[: config.STAGES.index("NA CILJU")])
_ONBOARD = ("PRI PACIENTU", "S KRAJA")
_HANDED_OVER = frozenset({"PREDAJA PACIENTA", "PROST"})  # the patient is with the ER team: nothing left to alert or suggest


# --- Small helpers -----------------------------------------------------------------------------

def _parse(value: str | None, like: datetime) -> datetime | None:
    """A time that a card carries as ISO text. A time with no zone is read in the world clock's zone."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=like.tzinfo)


def _minutes(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / 60


def _alert(card: dict[str, Any], rule: str, severity: str, message: str, since: str | None) -> dict[str, Any]:
    return {
        "id": f"er:{card['case_id']}:{rule}",
        "rule": rule,
        "severity": severity,
        "case_id": card["case_id"],
        "vehicle_id": card["vehicle_id"],
        "message": message,
        "since": since,
    }


def _reading_time(state: WorldState, reading: dict[str, Any]) -> datetime:
    """When a card's vitals reading was observed: exact from the log entry it came from."""
    stored = get_log(state).get(reading["seq"])
    if stored is not None:
        return stored.observed_t or stored.t
    return state.sim_time - timedelta(minutes=reading["age_min"])  # not expected: the card names a stored entry


# --- Handover timer ----------------------------------------------------------------------------

def handover_timer(state: WorldState, arrived_at: datetime | None, handover_entry: ClinicalEntry | None) -> dict[str, Any] | None:
    """The 15-minute handover clock, from arrival until a handover entry (or a free one) is recorded.

    None while the patient has not (yet) been marked arrived: a handover or free entry can move the
    stage before the engine marks the trip completed, and then there is no arrival to count from.
    Once handed over `done_at` is set, `minutes_left` is None and the clock is no longer overdue.
    The caller passes the handover entry, or the free entry when there is none (a unit that reports
    itself free has finished the handover).
    """
    if arrived_at is None:
        return None
    due = arrived_at + timedelta(minutes=config.HANDOVER_LIMIT_MIN)
    done = None if handover_entry is None else (handover_entry.observed_t or handover_entry.t)
    minutes_left, overdue = None, False
    if done is None:
        minutes_left = max(0.0, round(_minutes(due, state.sim_time), 1))
        overdue = state.sim_time > due
    return {
        "started_at": arrived_at.isoformat(),
        "due_at": due.isoformat(),
        "minutes_left": minutes_left,
        "overdue": overdue,
        "done_at": None if done is None else done.isoformat(),
    }


# --- Alerts ------------------------------------------------------------------------------------

def _stroke_window(card: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    onsets = [e for e in card["events"] if e["kind"] == "stroke_onset"]
    onset = _parse(onsets[-1]["onset_t"], now) if onsets else None  # the latest report (the list is in observed order)
    if onset is None:
        return None
    since_min = max(0.0, _minutes(now, onset))
    if since_min >= config.STROKE_WINDOW_MIN:
        return None
    left = config.STROKE_WINDOW_MIN - since_min
    return _alert(
        card, "stroke_window", "high",
        f"Stroke window open: {left:.0f} min left (onset {since_min:.0f} min ago)", onset.isoformat(),
    )


def _vitals_out_of_limits(state: WorldState, card: dict[str, Any]) -> dict[str, Any] | None:
    breaches: list[tuple[datetime, str]] = []
    for metric, reading in card["vitals"].items():
        limits = config.VITAL_LIMITS.get(metric)
        if limits is None or reading["needs_check"]:  # an implausible value is "check this", not an alarm
            continue
        low, high = limits
        value = reading["value"]
        if low is not None and value < low:
            breaches.append((_reading_time(state, reading), f"{metric} {value:g} (below {low:g})"))
        elif high is not None and value > high:
            breaches.append((_reading_time(state, reading), f"{metric} {value:g} (above {high:g})"))
    if not breaches:
        return None
    breaches.sort(key=lambda b: b[0])
    return _alert(
        card, "vitals_out_of_limits", "high",
        "Vitals outside limits: " + ", ".join(text for _, text in breaches), breaches[0][0].isoformat(),
    )


def _no_vitals(state: WorldState, card: dict[str, Any]) -> dict[str, Any] | None:
    if card["level"]["value"] != "red" or card["stage"] not in _ONBOARD:
        return None
    if card["vitals"]:
        since = max(_reading_time(state, r) for r in card["vitals"].values())  # the latest reading of any metric
    else:
        trip = state.trips.get(card["case_id"])
        since = trip.eta_pickup if trip is not None else None
    if since is None or _minutes(state.sim_time, since) <= config.NO_VITALS_RED_MIN:
        return None
    return _alert(
        card, "no_vitals", "low",
        f"No vitals recorded for {_minutes(state.sim_time, since):.0f} min on a red case", since.isoformat(),
    )


def _case_alerts(state: WorldState, card: dict[str, Any]) -> list[dict[str, Any]]:
    if card["stage"] in _HANDED_OVER:  # derived on read, nothing is written; the facts stay on the card
        return []
    now = state.sim_time
    found: list[dict[str, Any] | None] = []
    for rule, severity, messages in EVENT_RULES:
        hit = next((e for e in card["events"] if e["kind"] in messages), None)
        found.append(None if hit is None else _alert(card, rule, severity, messages[hit["kind"]], hit["observed_t"]))
    found.append(_stroke_window(card, now))
    found.append(_vitals_out_of_limits(state, card))

    minutes_to_arrival = card["minutes_to_arrival"]
    if (
        card["stage"] in _BEFORE_ARRIVAL
        and minutes_to_arrival is not None
        and minutes_to_arrival <= config.ARRIVING_UNACKED_MIN
        and not card["acknowledged"]
    ):
        found.append(_alert(
            card, "arriving_unacknowledged", "medium",
            f"Arriving in {minutes_to_arrival:g} min and not acknowledged by reception", None,
        ))

    handover = card["handover"]
    if handover is not None and handover["done_at"] is None and handover["overdue"]:
        started = _parse(handover["started_at"], now)
        since_arrival = f"{_minutes(now, started):.0f}" if started is not None else "more than the limit of"
        found.append(_alert(
            card, "handover_overdue", "high",
            f"Handover overdue: {since_arrival} min since arrival (limit {config.HANDOVER_LIMIT_MIN:g} min)",
            handover["due_at"],
        ))

    found.append(_no_vitals(state, card))
    return [a for a in found if a is not None]


def compute_alerts(state: WorldState, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The alerts for these cards, most urgent first (critical, high, medium, low), then by id."""
    alerts = [a for card in cards for a in _case_alerts(state, card)]
    alerts.sort(key=lambda a: (SEVERITIES.index(a["severity"]), a["id"]))
    return alerts


# --- Suggested actions -------------------------------------------------------------------------

def suggested_actions(card: dict[str, Any]) -> list[dict[str, Any]]:
    """What reception might do next for this case, from the card alone. Never recorded: the ER decides.

    Nothing once the patient is handed over (stage PREDAJA PACIENTA or PROST): there is no bay or team to arrange."""
    if card["stage"] in _HANDED_OVER:
        return []
    actions: list[dict[str, Any]] = []
    if not card["acknowledged"] and card["stage"] not in _ARRIVED:
        actions.append({"action": "acknowledge", "reason": "The patient is on the way and reception has not acknowledged the case"})
    if card["bay"] is None:
        actions.append({"action": "bay_assigned", "reason": "No bay is assigned yet"})

    why: dict[str, list[str]] = {}  # team -> reasons, in the order first asked for
    problem = card["problem"]["type"]
    team = config.SUGGESTED_TEAM_BY_PROBLEM.get(problem)
    if team is not None:
        why.setdefault(team, []).append(f"problem type: {problem.replace('_', ' ')}")
    reported = {e["kind"] for e in card["events"]}
    for kind, (team, reason) in TEAM_BY_EVENT.items():  # table order, so the list does not depend on who reported first
        if kind in reported:
            why.setdefault(team, []).append(reason)
    for team, reasons in why.items():
        if team not in card["teams_activated"]:
            actions.append({"action": "team_activated", "team": team, "reason": "; ".join(reasons)})
    return actions
