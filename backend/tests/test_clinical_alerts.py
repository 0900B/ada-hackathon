"""ER alerts, the handover timer and suggested actions (spec 6.5), read through the board and the cards.

Run from backend/:  python tests/test_clinical_alerts.py   (or: python -m pytest tests)
Offline and self-contained: every test builds its own WorldState via fresh_world(), never main.sim.
All thresholds used here are the config's PLACEHOLDER values, read from config, not copied.
"""
from __future__ import annotations

import clinical_helpers  # noqa: F401  (must be first: sets the offline env, puts backend/ on sys.path)

import json
import sys
import time
import traceback
from datetime import timedelta

from app.clinical import config
from app.clinical.alerts import compute_alerts, handover_timer, suggested_actions
from app.clinical.models import ENTRY_IN
from app.clinical.projection import board, build_case
from app.clinical.service import record_entry
from app.clinical.store import get_log
from clinical_helpers import drive, entry, er_trip, fresh_world, stored_fields

ALERT_KEYS = {"id", "rule", "severity", "case_id", "vehicle_id", "message", "since"}
HANDOVER_KEYS = {"started_at", "due_at", "minutes_left", "overdue", "done_at"}
RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# --- Helpers -----------------------------------------------------------------------------------

def rec(w, trip, **overrides):
    """Record a valid entry for `trip` (the helper payload with shallow overrides); return the stored entry."""
    stored, created = record_entry(w, ENTRY_IN.validate_python(entry(trip, **overrides)))
    assert created
    return stored


def er_action(w, trip, **content):
    return rec(w, trip, type="er_action", source="er_reception", unit="er", content=content)


def triage(w, trip, level="yellow", problem_type="other"):
    return rec(w, trip, type="triage", source="dispatcher", unit="dispatch", content={"level": level, "problem_type": problem_type})


def event(w, trip, kind, **content):
    return rec(w, trip, type="event", content={"kind": kind, **content})


def card_of(w, trip) -> dict:
    cards = [c for c in board(w)["cases"] if c["case_id"] == trip.id]
    assert len(cards) == 1
    return cards[0]


def alerts_of(w, trip) -> list[dict]:
    return [a for a in board(w)["alerts"] if a["case_id"] == trip.id]


def rules_of(w, trip) -> set[str]:
    return {a["rule"] for a in alerts_of(w, trip)}


def alert(w, trip, rule) -> dict:
    found = [a for a in alerts_of(w, trip) if a["rule"] == rule]
    assert len(found) == 1, f"expected one {rule} alert, got {[a['rule'] for a in alerts_of(w, trip)]}"
    return found[0]


def onboard(w, trip, minutes_since_pickup: float) -> None:
    """Put the trip onboard (the leg to the ER), the pickup `minutes_since_pickup` ago."""
    trip.status = "onboard"
    w.vehicles[trip.vehicle_id].status = "with_patient"
    trip.eta_pickup = w.sim_time - timedelta(minutes=minutes_since_pickup)


def arrive_naturally(w, trip) -> None:
    """Drive the world until the engine marks the trip completed (the arrival)."""
    drive(w, 300, until=lambda: trip.status == "completed")
    assert trip.status == "completed", "the world never delivered the patient"


def team_suggestions(card) -> dict[str, dict]:
    return {a["team"]: a for a in card["suggested_actions"] if a["action"] == "team_activated"}


def actions_of(card) -> list[str]:
    return [a["action"] for a in card["suggested_actions"]]


# --- Event alerts ------------------------------------------------------------------------------

def test_arrest_event_raises_critical_alert_with_stable_id():
    w = fresh_world()
    t = er_trip(w)
    assert "arrest" not in rules_of(w, t)
    event(w, t, "arrest")
    a = alert(w, t, "arrest")
    assert a["id"] == f"er:{t.id}:arrest" and a["severity"] == "critical"
    assert set(a) == ALERT_KEYS and a["case_id"] == t.id and a["vehicle_id"] == t.vehicle_id
    assert a["since"] is not None and isinstance(a["message"], str) and a["message"]
    assert a["id"] in card_of(w, t)["alert_ids"]
    drive(w, 1)  # time passing does not change the id (clients diff on it)
    assert alert(w, t, "arrest")["id"] == a["id"]


def test_resuscitation_started_raises_the_same_arrest_alert():
    w = fresh_world()
    t = er_trip(w)
    event(w, t, "resuscitation_started")
    a = alert(w, t, "arrest")
    assert a["id"] == f"er:{t.id}:arrest" and a["severity"] == "critical"
    event(w, t, "arrest")  # both reported: still one alert for the case
    assert [x["rule"] for x in alerts_of(w, t)].count("arrest") == 1


def test_rosc_airway_stemi_transfusion_each_raise_a_high_alert():
    w = fresh_world()
    t = er_trip(w)
    for kind in ("rosc", "airway", "stemi", "transfusion"):
        assert kind not in rules_of(w, t)
        event(w, t, kind)
        a = alert(w, t, kind)
        assert a["id"] == f"er:{t.id}:{kind}" and a["severity"] == "high" and a["since"] is not None


def test_superseded_event_no_longer_alerts():
    w = fresh_world()
    t = er_trip(w)
    wrong = event(w, t, "arrest")
    assert "arrest" in rules_of(w, t)
    rec(w, t, type="note", content={"text": "arrest tapped by mistake"}, supersedes=wrong.entry_id)
    assert "arrest" not in rules_of(w, t) and card_of(w, t)["alert_ids"] == []


def test_stroke_window_counts_down_and_closes():
    w = fresh_world()
    t = er_trip(w)
    onset = w.sim_time - timedelta(minutes=60)
    event(w, t, "stroke_onset", onset_t=onset.isoformat())  # stored (and read back) as an ISO string
    a = alert(w, t, "stroke_window")
    assert a["id"] == f"er:{t.id}:stroke_window" and a["severity"] == "high"
    assert a["since"] == onset.isoformat()
    assert str(int(config.STROKE_WINDOW_MIN) - 60) in a["message"]  # onset 60 min ago: 210 min left
    drive(w, 10)
    assert str(int(config.STROKE_WINDOW_MIN) - 70) in alert(w, t, "stroke_window")["message"]  # it counts down

    closed = er_trip(w, pickup="home_vic")
    event(w, closed, "stroke_onset", onset_t=(w.sim_time - timedelta(minutes=300)).isoformat())
    assert "stroke_window" not in rules_of(w, closed)  # onset 300 min ago: closed
    assert [e["kind"] for e in card_of(w, closed)["events"]] == ["stroke_onset"]  # the event itself stays on the card


def test_stroke_window_edge_is_exclusive():
    w = fresh_world()
    inside, edge = er_trip(w), er_trip(w, pickup="home_vic")
    limit = config.STROKE_WINDOW_MIN
    event(w, inside, "stroke_onset", onset_t=(w.sim_time - timedelta(minutes=limit - 1)).isoformat())
    event(w, edge, "stroke_onset", onset_t=(w.sim_time - timedelta(minutes=limit)).isoformat())
    assert "stroke_window" in rules_of(w, inside) and "stroke_window" not in rules_of(w, edge)


def test_latest_stroke_onset_report_decides_the_window():
    w = fresh_world()
    t = er_trip(w)
    event(w, t, "stroke_onset", onset_t=(w.sim_time - timedelta(minutes=300)).isoformat())
    assert "stroke_window" not in rules_of(w, t)
    event(w, t, "stroke_onset", onset_t=(w.sim_time - timedelta(minutes=30)).isoformat())  # a later report
    assert "stroke_window" in rules_of(w, t)


# --- Vitals ------------------------------------------------------------------------------------

def test_vitals_limits_alert_but_implausible_value_does_not():
    w = fresh_world()
    t = er_trip(w)
    low = rec(w, t, content={"spo2": 85})
    a = alert(w, t, "vitals_out_of_limits")
    assert a["id"] == f"er:{t.id}:vitals_out_of_limits" and a["severity"] == "high"
    assert "spo2" in a["message"] and "85" in a["message"]
    assert a["since"] == low.observed_t.isoformat()

    other = er_trip(w, pickup="home_vic")
    rec(w, other, content={"spo2": 140})  # not physically possible: "check this", not a clinical alarm
    assert card_of(w, other)["vitals"]["spo2"]["needs_check"] is True
    assert "vitals_out_of_limits" not in rules_of(w, other)


def test_vitals_limits_are_inclusive_and_cover_both_sides():
    w = fresh_world()
    t = er_trip(w)
    at_the_edge = {"spo2": 90, "sbp": 180, "hr": 40, "rr": 30, "gcs": 9}  # every metric exactly on a limit
    for metric, (low, high) in config.VITAL_LIMITS.items():
        assert at_the_edge[metric] in (low, high)
    rec(w, t, content=at_the_edge)
    assert "vitals_out_of_limits" not in rules_of(w, t)
    rec(w, t, content={"sbp": 181})
    assert "sbp 181" in alert(w, t, "vitals_out_of_limits")["message"]
    rec(w, t, content={"sbp": 120, "hr": 39})
    message = alert(w, t, "vitals_out_of_limits")["message"]
    assert "hr 39" in message and "sbp" not in message  # only what is out of limits, and only the latest reading
    rec(w, t, content={"hr": 80})
    assert "vitals_out_of_limits" not in rules_of(w, t)


def test_a_corrected_reading_stops_the_vitals_alert_and_a_flagged_one_never_hides_a_real_one():
    w = fresh_world()
    t = er_trip(w)
    wrong = rec(w, t, content={"spo2": 85})
    assert "vitals_out_of_limits" in rules_of(w, t)
    rec(w, t, content={"spo2": 95}, supersedes=wrong.entry_id)
    assert "vitals_out_of_limits" not in rules_of(w, t)
    rec(w, t, content={"spo2": 140, "hr": 200})  # ONE reading: spo2 needs a check, hr is plausible and dangerous
    message = alert(w, t, "vitals_out_of_limits")["message"]
    assert "hr 200" in message and "spo2" not in message
    vitals = card_of(w, t)["vitals"]
    assert vitals["spo2"]["needs_check"] is True and vitals["hr"]["needs_check"] is False


def test_one_implausible_value_does_not_hide_a_real_one_in_the_same_reading():  # ruling R11: judged per metric
    w = fresh_world()
    t = er_trip(w)
    rec(w, t, content={"hr": 200, "spo2": 140})
    a = alert(w, t, "vitals_out_of_limits")
    assert "hr 200" in a["message"] and "spo2" not in a["message"] and a["severity"] == "high"
    vitals = card_of(w, t)["vitals"]
    assert vitals["spo2"]["value"] == 140 and vitals["spo2"]["needs_check"] is True  # kept as entered, flagged
    assert vitals["hr"]["value"] == 200 and vitals["hr"]["needs_check"] is False  # judged on its own
    assert set(vitals["hr"]) == {"value", "age_min", "state", "needs_check", "seq"}

    only = er_trip(w, pickup="home_vic")
    rec(w, only, content={"hr": 80, "spo2": 140})  # the implausible one alone never raises a clinical alert
    assert "vitals_out_of_limits" not in rules_of(w, only)
    assert card_of(w, only)["vitals"]["hr"]["needs_check"] is False


def test_plausibility_is_inclusive_at_each_bound_and_flags_just_outside():
    w = fresh_world()
    inside, outside = er_trip(w), er_trip(w, pickup="home_vic")
    at_the_bounds = {"spo2": 100, "gcs": 3, "hr": 0, "sbp": 300, "temp_c": 25}  # each exactly on a PLAUSIBLE bound
    for metric, value in at_the_bounds.items():
        assert value in config.PLAUSIBLE[metric]
    rec(w, inside, content=at_the_bounds)
    assert not any(r["needs_check"] for r in card_of(w, inside)["vitals"].values())
    just_outside = {"spo2": 100.5, "gcs": 2, "hr": -1, "sbp": 301, "temp_c": 24.9}
    for metric, value in just_outside.items():
        assert not config.PLAUSIBLE[metric][0] <= value <= config.PLAUSIBLE[metric][1]
        rec(w, outside, content={metric: value})
    flagged = {m: r["needs_check"] for m, r in card_of(w, outside)["vitals"].items()}
    assert flagged == {m: True for m in just_outside}

    mixed = er_trip(w, pickup="home_siska")
    rec(w, mixed, content={"spo2": 100, "gcs": 2})  # one reading: the metric on its bound is fine, the one outside is flagged
    v = card_of(w, mixed)["vitals"]
    assert v["spo2"]["needs_check"] is False and v["gcs"]["needs_check"] is True


# --- Arrival, acknowledgement, handover --------------------------------------------------------

def test_arriving_unacknowledged_clears_after_acknowledge():
    w = fresh_world()
    t = er_trip(w)
    t.eta_dropoff = w.sim_time + timedelta(minutes=8)
    a = alert(w, t, "arriving_unacknowledged")
    assert a["id"] == f"er:{t.id}:arriving_unacknowledged" and a["severity"] == "medium"
    er_action(w, t, action="acknowledge")
    assert "arriving_unacknowledged" not in rules_of(w, t)

    far = er_trip(w, pickup="home_vic")
    far.eta_dropoff = w.sim_time + timedelta(minutes=12)
    assert "arriving_unacknowledged" not in rules_of(w, far)
    far.eta_dropoff = w.sim_time + timedelta(minutes=config.ARRIVING_UNACKED_MIN)  # the limit itself counts
    assert "arriving_unacknowledged" in rules_of(w, far)


def test_arriving_unacknowledged_stops_once_the_patient_is_in_handover():
    w = fresh_world()
    t = er_trip(w)
    t.eta_dropoff = w.sim_time + timedelta(minutes=3)
    assert "arriving_unacknowledged" in rules_of(w, t)
    rec(w, t, type="handover", content={"note": "handed over"})  # stage is PREDAJA PACIENTA now
    assert card_of(w, t)["stage"] == "PREDAJA PACIENTA"
    assert "arriving_unacknowledged" not in rules_of(w, t)


def test_handover_timer_runs_15_minutes_then_overdue_then_stops_on_handover():
    w = fresh_world()
    t = er_trip(w)
    assert card_of(w, t)["handover"] is None  # not arrived: no timer
    arrive_naturally(w, t)
    c = card_of(w, t)
    h = c["handover"]
    assert set(h) == HANDOVER_KEYS and h["started_at"] == c["arrived_at"] == t.eta_dropoff.isoformat()
    assert h["due_at"] == (t.eta_dropoff + timedelta(minutes=config.HANDOVER_LIMIT_MIN)).isoformat()
    assert abs(h["minutes_left"] - config.HANDOVER_LIMIT_MIN) <= 1.0 and h["overdue"] is False and h["done_at"] is None
    assert "handover_overdue" not in rules_of(w, t)

    drive(w, 16)
    h = card_of(w, t)["handover"]
    assert h["overdue"] is True and h["minutes_left"] == 0.0 and h["done_at"] is None
    a = alert(w, t, "handover_overdue")
    assert a["id"] == f"er:{t.id}:handover_overdue" and a["severity"] == "high" and a["since"] == h["due_at"]

    done = rec(w, t, type="handover", content={"note": "handed to the triage nurse"})
    h = card_of(w, t)["handover"]
    assert h["done_at"] == done.observed_t.isoformat() and h["minutes_left"] is None and h["overdue"] is False
    assert h["started_at"] == t.eta_dropoff.isoformat()
    assert "handover_overdue" not in rules_of(w, t) and card_of(w, t)["alert_ids"] == []


def test_a_free_entry_alone_finishes_the_handover_clock():  # final review F2: free implies handover is over
    w = fresh_world()
    t = er_trip(w)
    arrive_naturally(w, t)
    drive(w, 16)
    assert card_of(w, t)["handover"]["overdue"] is True and "handover_overdue" in rules_of(w, t)
    freed = rec(w, t, type="free", content={"note": "unit free"})  # no handover entry was ever recorded
    c = card_of(w, t)
    assert c["stage"] == "PROST"
    h = c["handover"]
    assert h["done_at"] == freed.observed_t.isoformat() and h["minutes_left"] is None and h["overdue"] is False
    assert h["started_at"] == t.eta_dropoff.isoformat()
    assert "handover_overdue" not in rules_of(w, t)


def test_a_handover_entry_wins_over_a_later_free_entry_for_the_clock():
    w = fresh_world()
    t = er_trip(w)
    arrive_naturally(w, t)
    drive(w, 2)
    handed = rec(w, t, type="handover", content={"note": "handed over"})
    drive(w, 3)
    rec(w, t, type="free", content={"note": "unit free"})
    assert card_of(w, t)["handover"]["done_at"] == handed.observed_t.isoformat()  # the earlier, real handover time


def test_handover_timer_function_reports_minutes_left_and_overdue():
    w = fresh_world()
    arrived = w.sim_time - timedelta(minutes=5)
    h = handover_timer(w, arrived, None)
    assert h == {
        "started_at": arrived.isoformat(),
        "due_at": (arrived + timedelta(minutes=config.HANDOVER_LIMIT_MIN)).isoformat(),
        "minutes_left": config.HANDOVER_LIMIT_MIN - 5,
        "overdue": False,
        "done_at": None,
    }
    h = handover_timer(w, w.sim_time - timedelta(minutes=config.HANDOVER_LIMIT_MIN), None)  # due this very moment
    assert h["overdue"] is False and h["minutes_left"] == 0.0
    h = handover_timer(w, w.sim_time - timedelta(minutes=config.HANDOVER_LIMIT_MIN + 4), None)
    assert h["overdue"] is True and h["minutes_left"] == 0.0

    t = er_trip(w)
    handed = get_log(w).append(
        stored_fields(case_id=t.id, type="handover", content={"note": "x"}, unit=t.vehicle_id, t=w.sim_time, observed_t=w.sim_time)
    )
    h = handover_timer(w, w.sim_time - timedelta(minutes=40), handed)  # handed over late: the timer simply stopped
    assert h["done_at"] == w.sim_time.isoformat() and h["minutes_left"] is None and h["overdue"] is False


def test_handover_before_the_engine_marks_arrival_has_no_timer_and_no_alert():  # carried finding B
    w = fresh_world()
    t = er_trip(w)
    assert t.status != "completed"
    handed = rec(w, t, type="handover", content={"note": "handed over early"})  # the stage moves on, arrived_at is still None
    c = card_of(w, t)
    assert c["stage"] == "PREDAJA PACIENTA" and c["arrived_at"] is None
    assert c["handover"] is None and "handover_overdue" not in rules_of(w, t)
    assert handover_timer(w, None, None) is None and handover_timer(w, None, handed) is None
    rec(w, t, type="free", content={"note": "unit free"})
    c = card_of(w, t)
    assert c["stage"] == "PROST" and c["handover"] is None and "handover_overdue" not in rules_of(w, t)


# --- A handed-over case no longer alerts (final review F1) -------------------------------------

def test_a_handed_over_or_free_case_has_no_alerts_and_no_suggestions():
    for closing in ("handover", "free"):
        w = fresh_world()
        t = er_trip(w)
        event(w, t, "arrest")
        rec(w, t, content={"spo2": 80})
        before = card_of(w, t)
        assert {"arrest", "vitals_out_of_limits"} <= rules_of(w, t) and before["alert_ids"] and before["suggested_actions"]
        arrive_naturally(w, t)
        arrived = card_of(w, t)
        assert arrived["stage"] == "NA CILJU"  # the rule is not simply off: an arrived case still alerts and suggests
        assert {"arrest", "vitals_out_of_limits"} <= rules_of(w, t) and arrived["alert_ids"] and arrived["suggested_actions"]

        inbound = er_trip(w, pickup="home_vic")  # a new case on its way, with a (medium) alert of its own
        inbound.eta_dropoff = w.sim_time + timedelta(minutes=config.ARRIVING_UNACKED_MIN - 2)
        assert "arriving_unacknowledged" in rules_of(w, inbound)
        n = len(get_log(w))
        rec(w, t, type=closing, content={"note": "done"})
        c = card_of(w, t)
        assert c["stage"] == ("PREDAJA PACIENTA" if closing == "handover" else "PROST")
        assert alerts_of(w, t) == [] and c["alert_ids"] == [] and c["suggested_actions"] == [], closing
        assert len(get_log(w)) == n + 1  # derived on read: only the entry itself was written, nothing for the suppression
        assert c["events"] and c["vitals"]["spo2"]["value"] == 80  # the facts stay on the card, only the alerts stop

        board_alerts = board(w)["alerts"]  # the new inbound alert is now the first on the board, not the old critical one
        assert board_alerts and board_alerts[0]["case_id"] == inbound.id
        assert all(a["case_id"] != t.id for a in board_alerts)
        assert compute_alerts(w, [c]) == [] and suggested_actions(c) == []


def test_a_case_handed_over_before_the_engine_marks_arrival_stops_alerting_too():
    w = fresh_world()
    t = er_trip(w)
    event(w, t, "arrest")
    rec(w, t, content={"spo2": 80})
    assert t.status != "completed" and "arrest" in rules_of(w, t)  # onboard or on the way: still alerts
    rec(w, t, type="handover", content={"note": "handed over early"})
    assert alerts_of(w, t) == [] and card_of(w, t)["suggested_actions"] == []


# --- No vitals ---------------------------------------------------------------------------------

def test_no_vitals_alert_for_red_case_only():
    w = fresh_world()
    t = er_trip(w)  # emergency: red, inferred
    onboard(w, t, minutes_since_pickup=11)
    assert card_of(w, t)["stage"] == "S KRAJA" and card_of(w, t)["level"]["value"] == "red"
    a = alert(w, t, "no_vitals")
    assert a["id"] == f"er:{t.id}:no_vitals" and a["severity"] == "low"
    assert a["since"] == t.eta_pickup.isoformat()
    triage(w, t, level="yellow")  # the level the dispatcher set is yellow now
    assert "no_vitals" not in rules_of(w, t)


def test_no_vitals_needs_the_onboard_stage_and_more_than_the_limit():
    w = fresh_world()
    t = er_trip(w)
    assert card_of(w, t)["stage"] in ("SPREJETO", "NA POTI") and "no_vitals" not in rules_of(w, t)
    onboard(w, t, minutes_since_pickup=config.NO_VITALS_RED_MIN)
    assert "no_vitals" not in rules_of(w, t)  # exactly the limit is not "more than"
    onboard(w, t, minutes_since_pickup=config.NO_VITALS_RED_MIN + 1)
    assert "no_vitals" in rules_of(w, t)
    w.vehicles[t.vehicle_id].status = "loading"  # with the patient (PRI PACIENTU) counts as well
    assert card_of(w, t)["stage"] == "PRI PACIENTU" and "no_vitals" in rules_of(w, t)
    t.status = "completed"  # arrived: the unit is no longer onboard
    assert "no_vitals" not in rules_of(w, t)


def test_no_vitals_counts_from_the_latest_vitals_and_clears_on_a_new_reading():
    w = fresh_world()
    t = er_trip(w)
    rec(w, t, content={"hr": 80, "spo2": 95})
    drive(w, 11)
    onboard(w, t, minutes_since_pickup=3)  # the pickup alone would not raise it; the stale vitals do
    a = alert(w, t, "no_vitals")
    assert a["since"] == get_log(w).get(1).observed_t.isoformat()
    rec(w, t, content={"hr": 82})
    assert "no_vitals" not in rules_of(w, t)


def test_no_vitals_without_any_reference_time_does_not_alert():
    w = fresh_world()
    t = er_trip(w)
    onboard(w, t, minutes_since_pickup=30)
    assert "no_vitals" in rules_of(w, t)
    t.eta_pickup = None  # no vitals and no pickup time to count from
    assert "no_vitals" not in rules_of(w, t)


# --- Suggested actions -------------------------------------------------------------------------

def test_suggested_team_disappears_once_activated():
    w = fresh_world()
    t = er_trip(w, note="suspected stroke")
    triage(w, t, level="red", problem_type="stroke")
    s = team_suggestions(card_of(w, t))
    assert list(s) == ["stroke"]
    assert s["stroke"]["action"] == "team_activated" and s["stroke"]["reason"]
    er_action(w, t, action="team_activated", team="stroke")
    assert team_suggestions(card_of(w, t)) == {}


def test_acknowledge_and_bay_suggestions_follow_the_card():
    w = fresh_world()
    t = er_trip(w)
    c = card_of(w, t)
    assert actions_of(c) == ["acknowledge", "bay_assigned"]
    assert all(a["reason"] and "team" not in a for a in c["suggested_actions"])
    er_action(w, t, action="acknowledge")
    assert actions_of(card_of(w, t)) == ["bay_assigned"]
    er_action(w, t, action="bay_assigned", bay="A-3")
    assert card_of(w, t)["suggested_actions"] == []


def test_acknowledge_is_not_suggested_once_the_patient_has_arrived():
    w = fresh_world()
    t = er_trip(w)
    other = er_trip(w, pickup="home_vic")
    assert "acknowledge" in actions_of(card_of(w, t)) and "acknowledge" in actions_of(card_of(w, other))
    t.status, t.eta_dropoff = "completed", w.sim_time - timedelta(minutes=2)
    assert "acknowledge" not in actions_of(card_of(w, t))
    rec(w, other, type="handover", content={"note": "x"})  # handed over, though the engine has not marked the arrival
    assert "acknowledge" not in actions_of(card_of(w, other))


def test_teams_are_suggested_from_the_problem_type_and_from_events():
    w = fresh_world()
    t = er_trip(w)
    er_action(w, t, action="acknowledge")
    er_action(w, t, action="bay_assigned", bay="A-1")
    triage(w, t, level="red", problem_type="polytrauma")
    assert list(team_suggestions(card_of(w, t))) == ["trauma"]
    event(w, t, "arrest")
    event(w, t, "stemi")
    event(w, t, "stroke_onset", onset_t=(w.sim_time - timedelta(minutes=20)).isoformat())
    s = team_suggestions(card_of(w, t))
    assert list(s) == ["trauma", "resuscitation_room", "heart", "stroke"]
    assert all(x["reason"] for x in s.values())
    for team in ("resuscitation_room", "heart"):
        er_action(w, t, action="team_activated", team=team)
    assert list(team_suggestions(card_of(w, t))) == ["trauma", "stroke"]


def test_a_team_asked_for_twice_is_suggested_once_with_both_reasons():
    w = fresh_world()
    t = er_trip(w)
    triage(w, t, level="red", problem_type="stemi")
    event(w, t, "stemi")
    tips = [a for a in card_of(w, t)["suggested_actions"] if a["action"] == "team_activated"]
    assert [a["team"] for a in tips] == ["heart"]
    event(w, t, "resuscitation_started")
    event(w, t, "arrest")
    assert [a["team"] for a in card_of(w, t)["suggested_actions"] if a["action"] == "team_activated"] == ["heart", "resuscitation_room"]


def test_problem_without_a_team_suggests_none_and_suggested_actions_is_a_pure_function_of_the_card():
    w = fresh_world()
    t = er_trip(w)
    triage(w, t, level="yellow", problem_type="sepsis")  # no row in SUGGESTED_TEAM_BY_PROBLEM
    c = card_of(w, t)
    assert team_suggestions(c) == {} and actions_of(c) == ["acknowledge", "bay_assigned"]
    assert suggested_actions(c) == c["suggested_actions"]
    assert suggested_actions(c) == suggested_actions(json.loads(json.dumps(c)))


def test_suggestions_are_never_recorded():
    w = fresh_world()
    t = er_trip(w)
    triage(w, t, level="red", problem_type="stroke")
    n = len(get_log(w))
    assert card_of(w, t)["suggested_actions"]
    assert len(get_log(w)) == n and get_log(w).for_case(t.id)[-1].type == "triage"  # nothing acknowledges for the ER


# --- Problem type (carried finding A) ----------------------------------------------------------

def test_a_later_level_only_triage_keeps_the_problem_type():
    w = fresh_world()
    t = er_trip(w)
    assert card_of(w, t)["problem"]["type"] is None  # no triage at all
    triage(w, t, level="red", problem_type="stroke")
    triage(w, t, level="yellow")  # the dispatcher only re-sets the level: problem_type defaults to "other"
    c = card_of(w, t)
    assert c["level"]["value"] == "yellow" and c["problem"]["type"] == "stroke"
    assert list(team_suggestions(c)) == ["stroke"]
    triage(w, t, level="red", problem_type="stemi")  # a later, real problem type replaces the earlier one
    assert card_of(w, t)["problem"]["type"] == "stemi"


def test_problem_type_is_other_when_a_triage_exists_but_names_none():
    w = fresh_world()
    t = er_trip(w)
    first = triage(w, t, level="red", problem_type="stroke")
    triage(w, t, level="yellow")
    assert card_of(w, t)["problem"]["type"] == "stroke"
    rec(  # the only non-"other" triage is replaced (corrected to "other"): nothing is left to keep
        w, t, type="triage", source="dispatcher", unit="dispatch", supersedes=first.entry_id,
        content={"level": "red", "problem_type": "other"},
    )
    assert card_of(w, t)["problem"]["type"] == "other"


# --- The alert list: order, sync, purity, no writes --------------------------------------------

def mixed_world():
    """Four cases with alerts of every severity, one without any, and an unassigned one."""
    w = fresh_world()
    now = w.sim_time
    critical, medium, low, quiet = (
        er_trip(w), er_trip(w, pickup="home_vic"), er_trip(w, pickup="home_siska"), er_trip(w, pickup="home_moste"),
    )
    for t in (critical, medium, low, quiet):
        t.eta_dropoff = now + timedelta(minutes=40)
    event(w, critical, "arrest")  # critical
    event(w, critical, "stroke_onset", onset_t=(now - timedelta(minutes=30)).isoformat())  # high
    rec(w, critical, content={"spo2": 85})  # high
    medium.eta_dropoff = now + timedelta(minutes=8)  # medium
    onboard(w, low, minutes_since_pickup=11)  # low
    er_action(w, quiet, action="acknowledge")
    return w, critical, medium, low, quiet


def test_alert_ids_listed_on_cards_and_board_alerts_sorted():
    w, critical, medium, low, quiet = mixed_world()
    b = board(w)
    alerts = b["alerts"]
    assert {a["severity"] for a in alerts} == {"critical", "high", "medium", "low"}
    ranks = [RANK[a["severity"]] for a in alerts]
    assert ranks == sorted(ranks), "ordered critical, high, medium, low"
    assert alerts == sorted(alerts, key=lambda a: (RANK[a["severity"]], a["id"]))  # then by id
    assert [a["id"] for a in alerts][0] == f"er:{critical.id}:arrest"
    assert len({a["id"] for a in alerts}) == len(alerts), "ids are unique"
    for c in b["cases"]:
        assert c["alert_ids"] == [a["id"] for a in alerts if a["case_id"] == c["case_id"]]
    cards = {c["case_id"]: c for c in b["cases"]}
    assert cards[quiet.id]["alert_ids"] == []
    assert cards[critical.id]["alert_ids"] == [f"er:{critical.id}:arrest"] + sorted(
        f"er:{critical.id}:{r}" for r in ("stroke_window", "vitals_out_of_limits")
    )


def test_a_card_built_alone_is_identical_to_its_card_on_the_board():  # ruling R10: one path, in sync by construction
    w, *_ = mixed_world()
    waiting = er_trip(w, pickup="home_polje")
    waiting.status, waiting.vehicle_id, waiting.eta_pickup, waiting.eta_dropoff = "unassigned", None, None, None
    done = er_trip(w, pickup="home_bezigrad")
    done.status, done.eta_dropoff = "completed", w.sim_time - timedelta(minutes=20)  # overdue handover
    b = board(w)
    assert {c["case_id"] for c in b["cases"]} >= {waiting.id, done.id}
    assert "handover_overdue" in rules_of(w, done)
    for c in b["cases"]:
        trip = w.trips[c["case_id"]]
        alone = build_case(w, trip, get_log(w).for_case(trip.id))
        assert alone == c
        assert alone["alert_ids"] == [a["id"] for a in b["alerts"] if a["case_id"] == trip.id]
        assert alone["handover"] == c["handover"] and alone["suggested_actions"] == c["suggested_actions"]


def test_compute_alerts_gives_the_same_alert_for_a_card_alone_or_among_others():
    w, *_ = mixed_world()
    cards = board(w)["cases"]
    everything = compute_alerts(w, cards)
    assert len(everything) >= 5 and everything == board(w)["alerts"]
    for c in cards:
        assert compute_alerts(w, [c]) == [a for a in everything if a["case_id"] == c["case_id"]]
    assert compute_alerts(w, list(reversed(cards))) == everything  # the order of the cards does not matter
    assert compute_alerts(w, []) == []


def test_alerts_are_computed_from_the_cards_without_changing_them():
    w, *_ = mixed_world()
    cards = board(w)["cases"]
    before = json.dumps(cards, sort_keys=True)
    assert compute_alerts(w, cards)
    assert json.dumps(cards, sort_keys=True) == before


def test_alerts_never_write_to_the_log():
    w, critical, *_ = mixed_world()
    n, version = len(get_log(w)), w.version
    b = board(w)
    assert b["alerts"] and len(get_log(w)) == n
    build_case(w, critical, get_log(w).for_case(critical.id))
    compute_alerts(w, b["cases"])
    assert len(get_log(w)) == n and w.version == version
    assert json.dumps(board(w), sort_keys=True) == json.dumps(b, sort_keys=True)  # and reading twice gives the same board


def test_board_with_alerts_is_json_serialisable():
    w, *_ = mixed_world()
    b = board(w)
    assert b["alerts"] and json.loads(json.dumps(b)) == b


def test_alerts_follow_world_time():
    w = fresh_world()
    t = er_trip(w)
    t.eta_dropoff = w.sim_time + timedelta(minutes=config.ARRIVING_UNACKED_MIN + 2)
    assert "arriving_unacknowledged" not in rules_of(w, t)
    w.sim_time += timedelta(minutes=3)  # the clock moves, the ETA stays: three minutes closer (drive() would re-project the ETA)
    assert "arriving_unacknowledged" in rules_of(w, t)


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
