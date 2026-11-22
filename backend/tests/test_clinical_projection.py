"""ER read model: cases from trips, the stage chain, cards and the board.

Run from backend/:  python tests/test_clinical_projection.py   (or: python -m pytest tests)
Offline and self-contained: every test builds its own WorldState via fresh_world(), never main.sim.
"""
from __future__ import annotations

import clinical_helpers  # noqa: F401  (must be first: sets the offline env, puts backend/ on sys.path)

import json
import os
import sys
import time
import traceback
from datetime import timedelta
from unittest.mock import patch

from app.clinical import config, projection
from app.clinical.config import STAGES
from app.clinical.models import ENTRY_IN
from app.clinical.projection import board, build_case, er_case_trips, snapshot_extra, stage_of
from app.clinical.service import confirm_entry, record_entry
from app.clinical.store import get_log
from app.engine.events import apply_event
from app.models import TaskRequestEvent, UrgentRequestEvent
from app.state import SNAPSHOT_DONE_HOURS
from clinical_helpers import drive, entry, er_trip, fresh_world, stored_fields

CARD_KEYS = {
    "case_id", "vehicle_id", "patient_label", "priority", "level", "problem", "age_years", "sex",
    "eta_dropoff", "minutes_to_arrival", "arrived_at", "stage", "stage_inferred", "severity", "vitals",
    "treatments", "events", "acknowledged", "bay", "teams_activated", "handover", "suggested_actions",
    "alert_ids",
}
BOARD_KEYS = {"world", "as_of", "seq", "cases", "alerts", "entries_tail"}


def rec(w, trip, **overrides):
    """Record a valid entry for `trip` (the helper payload with shallow overrides); return the stored entry."""
    stored, created = record_entry(w, ENTRY_IN.validate_python(entry(trip, **overrides)))
    assert created
    return stored


def er_action(w, trip, **content):
    return rec(w, trip, type="er_action", source="er_reception", unit="er", content=content)


def triage(w, trip, level="yellow", problem_type="other"):
    return rec(w, trip, type="triage", source="dispatcher", unit="dispatch", content={"level": level, "problem_type": problem_type})


def card_of(w, trip) -> dict:
    cards = [c for c in board(w)["cases"] if c["case_id"] == trip.id]
    assert len(cards) == 1
    return cards[0]


def live_entries(w, trip):
    return get_log(w).for_case(trip.id)


def unassigned_trip(w):
    record = apply_event(
        w,
        TaskRequestEvent(
            type="task_request", pickup_id="home_polje", dropoff_id="ukc", needs="stretcher", auto_assign=False
        ),
    )
    t = w.trips[record.affected_trip_ids[0]]
    assert t.status == "unassigned"
    return t


# --- Which trips become cases ------------------------------------------------------------------

def test_board_empty_when_no_er_trips():
    w = fresh_world()
    b = board(w)
    assert b["cases"] == [] and b["alerts"] == [] and b["entries_tail"] == []
    assert set(b) == BOARD_KEYS and b["world"] == w.name and b["seq"] == 0
    assert b["as_of"] == w.sim_time.isoformat()


def test_only_patient_trips_to_er_places_appear():
    w = fresh_world()
    t = er_trip(w)
    # An emergency to the oncology institute (not an ER place) and equipment going to the ER place
    # itself (a patient-only rule must exclude it) and to onko.
    apply_event(
        w, UrgentRequestEvent(type="urgent_request", pickup_id="home_vic", dropoff_id="onko", priority="emergency", needs="stretcher")
    )
    for dropoff in ("ukc", "onko"):
        apply_event(
            w,
            TaskRequestEvent(
                type="task_request", kind="equipment", needs="equipment",
                pickup_id="zd_center", dropoff_id=dropoff, label="blood products",
            ),
        )
    assert len(w.trips) == 4
    assert [c["case_id"] for c in board(w)["cases"]] == [t.id]
    assert [x.id for x in er_case_trips(w)] == [t.id]


def test_cancelled_trip_is_excluded():
    w = fresh_world()
    t = er_trip(w)
    assert [c["case_id"] for c in board(w)["cases"]] == [t.id]
    t.status = "cancelled"
    assert board(w)["cases"] == []


def test_finished_trips_stay_for_three_hours_of_world_time():
    w = fresh_world()
    recent, old, unknown = er_trip(w), er_trip(w, pickup="home_vic"), er_trip(w, pickup="home_siska")
    for t in (recent, old, unknown):
        t.status = "completed"
    recent.eta_dropoff = w.sim_time - timedelta(hours=SNAPSHOT_DONE_HOURS - 0.5)
    old.eta_dropoff = w.sim_time - timedelta(hours=SNAPSHOT_DONE_HOURS + 0.5)
    unknown.eta_dropoff = None
    assert [c["case_id"] for c in board(w)["cases"]] == [recent.id]


# --- Level -------------------------------------------------------------------------------------

def test_level_inferred_then_overridden_by_triage():
    w = fresh_world()
    t = er_trip(w)  # emergency
    assert card_of(w, t)["level"] == {"value": "red", "inferred": True, "source": None}
    triage(w, t, level="yellow")
    card = card_of(w, t)
    assert card["level"]["value"] == "yellow" and card["level"]["inferred"] is False
    assert card["level"]["source"] == "dispatcher"


def test_level_follows_the_priority_table_and_the_latest_triage():
    w = fresh_world()
    t = er_trip(w, priority="urgent")
    assert card_of(w, t)["level"] == {"value": "yellow", "inferred": True, "source": None}
    first = triage(w, t, level="red", problem_type="stroke")
    assert card_of(w, t)["level"]["value"] == "red" and card_of(w, t)["problem"] == {"type": "stroke", "note": t.note}
    record_entry(
        w,
        ENTRY_IN.validate_python(
            entry(t, type="triage", source="dispatcher", unit="dispatch", supersedes=first.entry_id,
                  content={"level": "yellow", "problem_type": "stroke"})
        ),
    )
    assert card_of(w, t)["level"]["value"] == "yellow"  # the replaced entry no longer counts


# --- Stage -------------------------------------------------------------------------------------

def stage_index(stage):
    return STAGES.index(stage)


def test_stage_never_goes_backwards_through_the_chain():
    w = fresh_world()
    t = er_trip(w)
    samples = [stage_of(w, t, live_entries(w, t))[0]]
    assert samples[0] in ("SPREJETO", "NA POTI")
    for _ in range(600):
        drive(w, 0.5)
        samples.append(stage_of(w, t, live_entries(w, t))[0])
        if t.status == "completed":
            break
    assert t.status == "completed", "the world never delivered the patient"
    indexes = [stage_index(s) for s in samples]
    assert indexes == sorted(indexes), f"the stage went backwards: {samples}"
    assert samples[-1] == "NA CILJU"
    assert "S KRAJA" in samples  # the leg with the patient was observed, not skipped over

    rec(w, t, type="handover", content={"note": "handed to the triage nurse"})
    assert stage_of(w, t, live_entries(w, t)) == ("PREDAJA PACIENTA", False)
    assert card_of(w, t)["stage"] == "PREDAJA PACIENTA"
    rec(w, t, type="free", content={"note": "unit free"})
    assert stage_of(w, t, live_entries(w, t)) == ("PROST", False)
    assert card_of(w, t)["stage"] == "PROST" and card_of(w, t)["stage_inferred"] is False


def test_stage_rules_per_trip_and_vehicle_state():
    w = fresh_world()
    t = er_trip(w)
    v = w.vehicles[t.vehicle_id]
    none = live_entries(w, t)

    t.status = "assigned"
    assert stage_of(w, t, none) == ("SPREJETO", False)
    t.status = "en_route_pickup"
    v.waiting_until = None
    assert stage_of(w, t, none) == ("NA POTI", True)
    v.waiting_until = w.sim_time + timedelta(minutes=5)
    assert stage_of(w, t, none) == ("NA KRAJU", True)
    t.status, v.status = "onboard", "loading"
    assert stage_of(w, t, none) == ("PRI PACIENTU", True)
    v.status = "with_patient"
    assert stage_of(w, t, none) == ("S KRAJA", True)
    t.status = "completed"
    assert stage_of(w, t, none) == ("NA CILJU", False)
    t.status = "unassigned"
    assert stage_of(w, t, none) == (None, False)


def test_stage_ignores_superseded_free_and_handover_entries():
    w = fresh_world()
    t = er_trip(w)
    t.status = "completed"
    log = get_log(w)
    # Appended to the log directly: the service lets a correction change the entry type, so a
    # replaced `free` can be a plain note, and the stage must then go back to what the trip says.
    mine = {"case_id": t.id, "unit": t.vehicle_id, "source": "simulated_crew"}
    h = log.append(stored_fields(type="handover", content={"note": "x"}, **mine))
    f = log.append(stored_fields(type="free", content={"note": "x"}, **mine))
    assert stage_of(w, t, log.for_case(t.id))[0] == "PROST"
    log.append(stored_fields(type="note", content={"text": "free tapped by mistake"}, supersedes=f.entry_id, **mine))
    assert stage_of(w, t, log.for_case(t.id))[0] == "PREDAJA PACIENTA"
    log.append(stored_fields(type="note", content={"text": "handover tapped by mistake"}, supersedes=h.entry_id, **mine))
    assert stage_of(w, t, log.for_case(t.id))[0] == "NA CILJU"


# --- Vitals ------------------------------------------------------------------------------------

def test_partial_vitals_keep_other_metrics_and_show_age():  # Review Focus 3
    w = fresh_world()
    t = er_trip(w)
    rec(w, t, content={"hr": 80, "spo2": 95})
    second = rec(w, t, content={"spo2": 91})
    drive(w, 6)
    v = card_of(w, t)["vitals"]
    assert v["hr"]["value"] == 80 and v["spo2"]["value"] == 91 and abs(v["hr"]["age_min"] - 6.0) < 0.6
    assert v["spo2"]["seq"] == second.seq and v["hr"]["seq"] == 1
    assert set(v["hr"]) == {"value", "age_min", "state", "needs_check", "seq"}
    assert v["hr"]["state"] == "heard" and v["hr"]["needs_check"] is False
    assert "sbp" not in v  # a metric nobody measured is absent, never a null placeholder


def test_vitals_resolve_by_observation_time_before_arrival_order():
    w = fresh_world()
    t = er_trip(w)
    drive(w, 4)
    late_news = rec(w, t, content={"spo2": 90}, observed_t=w.sim_time)
    rec(w, t, content={"spo2": 97}, observed_t=w.sim_time - timedelta(minutes=3))  # recorded later, measured earlier
    v = card_of(w, t)["vitals"]["spo2"]
    assert v["value"] == 90 and v["seq"] == late_news.seq and v["age_min"] == 0.0


def test_implausible_vital_kept_and_flagged():
    w = fresh_world()
    t = er_trip(w)
    rec(w, t, content={"spo2": 140})
    v = card_of(w, t)["vitals"]
    assert v["spo2"]["value"] == 140 and v["spo2"]["needs_check"] is True


def test_superseded_entry_not_shown():  # Review Focus 5: a correction replaces the value on the card
    w = fresh_world()
    t = er_trip(w)
    wrong = rec(w, t, content={"spo2": 91})
    fixed = rec(w, t, content={"spo2": 95}, supersedes=wrong.entry_id)
    v = card_of(w, t)["vitals"]
    assert v["spo2"]["value"] == 95 and v["spo2"]["seq"] == fixed.seq

    # A superseded drug entry is not a treatment any more either; the correction is the only one.
    drug = rec(w, t, type="drug_administered", content={"drug": "adrenalin", "dose": "10 mg", "route": "iv"})
    rec(w, t, type="drug_administered", content={"drug": "adrenalin", "dose": "1 mg", "route": "iv"}, supersedes=drug.entry_id)
    treatments = card_of(w, t)["treatments"]
    assert [x["content"]["dose"] for x in treatments] == ["1 mg"]

    # An implausible reading that was corrected is gone, not merely flagged.
    bad = rec(w, t, content={"hr": 900})
    rec(w, t, content={"hr": 90}, supersedes=bad.entry_id)
    hr = card_of(w, t)["vitals"]["hr"]
    assert hr["value"] == 90 and hr["needs_check"] is False


def test_confirming_leaves_only_the_latest_value_on_the_card():  # Review Focus 5
    w = fresh_world()
    t = er_trip(w)
    heard = rec(w, t, content={"hr": 80, "spo2": 95})
    confirmed = confirm_entry(w, heard.seq, unit=t.vehicle_id)
    card = card_of(w, t)
    assert card["vitals"]["hr"]["seq"] == confirmed.seq and card["vitals"]["hr"]["state"] == "confirmed"
    assert card["vitals"]["spo2"]["seq"] == confirmed.seq
    assert len(card["vitals"]) == 2


# --- Treatments, events, patient, severity -----------------------------------------------------

def test_treatments_events_patient_and_severity_on_the_card():
    w = fresh_world()
    t = er_trip(w)
    rec(w, t, type="patient_info", content={"age_years": 71, "sex": "f"})
    rec(w, t, type="patient_info", content={"age_years": 72})  # a partial correction keeps the sex
    rec(w, t, type="severity", content={"value": "orange"})
    rec(w, t, type="severity", content={"value": "red"})
    drug = rec(w, t, type="drug_administered", content={"drug": "aspirin", "dose": "300 mg", "route": "po"})
    proc = rec(w, t, type="procedure", content={"name": "iv access"})
    onset = w.sim_time - timedelta(minutes=40)
    rec(w, t, type="event", content={"kind": "stroke_onset", "onset_t": onset.isoformat()})
    rec(w, t, type="event", content={"kind": "airway"}, state="inferred")
    rec(w, t, type="note", content={"text": "calm"})
    c = card_of(w, t)
    assert c["age_years"] == 72 and c["sex"] == "f" and c["severity"] == "red"
    assert [(x["seq"], x["type"]) for x in c["treatments"]] == [(drug.seq, "drug_administered"), (proc.seq, "procedure")]
    assert set(c["treatments"][0]) == {"seq", "type", "content", "observed_t", "state", "needs_check"}
    assert c["treatments"][0]["content"] == {"drug": "aspirin", "dose": "300 mg", "route": "po"}
    assert [(e["kind"], e["state"]) for e in c["events"]] == [("stroke_onset", "heard"), ("airway", "inferred")]
    assert set(c["events"][0]) == {"kind", "observed_t", "onset_t", "state"}
    assert c["events"][0]["onset_t"] == onset.isoformat() and c["events"][1]["onset_t"] is None


def test_er_actions_fill_the_card():
    w = fresh_world()
    t = er_trip(w)
    c = card_of(w, t)
    assert c["acknowledged"] is False and c["bay"] is None and c["teams_activated"] == []
    er_action(w, t, action="acknowledge")
    er_action(w, t, action="bay_assigned", bay="A-3")
    er_action(w, t, action="team_activated", team="stroke")
    er_action(w, t, action="team_activated", team="stroke")  # said twice: listed once
    c = card_of(w, t)
    assert c["acknowledged"] and c["bay"] == "A-3" and c["teams_activated"] == ["stroke"]
    er_action(w, t, action="bay_assigned", bay="B-1")  # the latest bay wins
    er_action(w, t, action="team_activated", team="heart")
    c = card_of(w, t)
    assert c["bay"] == "B-1" and c["teams_activated"] == ["stroke", "heart"]


def test_acknowledgement_and_bay_that_were_replaced_do_not_count():
    w = fresh_world()
    t = er_trip(w)
    ack = er_action(w, t, action="acknowledge")
    bay = er_action(w, t, action="bay_assigned", bay="A-3")
    record_entry(
        w,
        ENTRY_IN.validate_python(
            entry(t, type="er_action", source="er_reception", unit="er", supersedes=bay.entry_id,
                  content={"action": "bay_assigned", "bay": "C-2"})
        ),
    )
    c = card_of(w, t)
    assert c["bay"] == "C-2" and c["acknowledged"] is True
    assert ack.entry_id not in get_log(w).superseded_ids()


# --- Arrival and the card as a whole -----------------------------------------------------------

def test_eta_arrival_and_placeholders_on_the_card():
    w = fresh_world()
    t = er_trip(w)
    t.eta_dropoff = w.sim_time + timedelta(minutes=12.34)
    c = card_of(w, t)
    assert set(c) == CARD_KEYS
    assert c["case_id"] == t.id and c["vehicle_id"] == t.vehicle_id and c["patient_label"] == t.label
    assert c["priority"] == "emergency" and c["eta_dropoff"] == t.eta_dropoff.isoformat()
    assert c["minutes_to_arrival"] == 12.3 and c["arrived_at"] is None
    # not arrived, 12 min out: no handover timer and no alert; reception can still acknowledge and give a bay
    assert c["handover"] is None and c["alert_ids"] == []
    assert [a["action"] for a in c["suggested_actions"]] == ["acknowledge", "bay_assigned"]
    t.status = "completed"
    t.eta_dropoff = w.sim_time - timedelta(minutes=5)
    c = card_of(w, t)
    assert c["arrived_at"] == t.eta_dropoff.isoformat() and c["minutes_to_arrival"] is None


def test_card_keys_are_the_same_for_every_kind_of_case():
    w = fresh_world()
    busy = er_trip(w)
    rec(w, busy, content={"hr": 80})
    triage(w, busy, level="red", problem_type="stroke")
    waiting = unassigned_trip(w)
    done = er_trip(w, pickup="home_vic")
    done.status, done.eta_dropoff = "completed", w.sim_time - timedelta(minutes=1)
    cases = {c["case_id"]: c for c in board(w)["cases"]}
    assert set(cases) == {busy.id, waiting.id, done.id}
    assert all(set(c) == CARD_KEYS for c in cases.values())
    u = cases[waiting.id]
    assert u["vehicle_id"] is None and u["stage"] is None and u["stage_inferred"] is False
    assert u["vitals"] == {} and u["treatments"] == [] and u["events"] == []
    assert u["age_years"] is None and u["sex"] is None and u["severity"] is None
    assert u["problem"] == {"type": None, "note": waiting.note}
    assert build_case(w, waiting, []) == u  # building one card directly gives the card the board shows


def test_cards_sorted_by_eta_then_arrived_last():
    w = fresh_world()
    now = w.sim_time
    late = er_trip(w)
    soon = er_trip(w, pickup="home_vic")
    waiting = unassigned_trip(w)
    newest_done = er_trip(w, pickup="home_siska")
    older_done = er_trip(w, pickup="home_moste")
    late.eta_dropoff = now + timedelta(minutes=20)
    soon.eta_dropoff = now + timedelta(minutes=10)
    waiting.eta_dropoff = None
    for t, ago in ((newest_done, 5), (older_done, 30)):
        t.status, t.eta_dropoff = "completed", now - timedelta(minutes=ago)
    got = [c["case_id"] for c in board(w)["cases"]]
    assert got == [soon.id, late.id, waiting.id, newest_done.id, older_done.id]


# --- The board and the snapshot section --------------------------------------------------------

def test_board_is_json_serialisable():
    w = fresh_world()
    t = er_trip(w)
    rec(w, t, content={"hr": 80, "spo2": 140})
    rec(w, t, type="event", content={"kind": "stroke_onset", "onset_t": (w.sim_time - timedelta(minutes=30)).isoformat()})
    rec(w, t, type="drug_administered", content={"drug": "x", "dose": "1", "route": "iv"})
    er_action(w, t, action="bay_assigned", bay="A-3")
    unassigned_trip(w)
    drive(w, 3)
    b = board(w)
    again = json.loads(json.dumps(b))
    assert again == b  # nothing was lost or turned into text by the round trip
    assert set(b) == BOARD_KEYS and b["seq"] == get_log(w).last_seq


def test_entries_tail_is_the_newest_entries_as_json():
    w = fresh_world()
    t = er_trip(w)
    for hr in (70, 71, 72, 73):
        rec(w, t, content={"hr": hr})
    with patch.object(config, "SNAPSHOT_TAIL", 3):
        tail = board(w)["entries_tail"]
    assert [e["seq"] for e in tail] == [2, 3, 4]
    assert tail == [e.model_dump(mode="json") for e in get_log(w).tail(3)]
    assert isinstance(tail[0]["t"], str) and tail[0]["case_id"] == t.id


def test_board_changes_nothing():
    w = fresh_world()
    t = er_trip(w)
    rec(w, t, content={"hr": 80})
    version, size = w.version, len(get_log(w))
    before = json.dumps(board(w), sort_keys=True)
    after = json.dumps(board(w), sort_keys=True)
    assert before == after and w.version == version and len(get_log(w)) == size


def test_card_does_not_share_entry_content_with_the_log():
    w = fresh_world()
    t = er_trip(w)
    stored = rec(w, t, type="drug_administered", content={"drug": "aspirin", "dose": "300 mg", "route": "po"})
    card_of(w, t)["treatments"][0]["content"]["dose"] = "tampered"
    assert stored.content["dose"] == "300 mg"


def test_snapshot_extra_returns_the_board_under_clinical():
    w = fresh_world()
    t = er_trip(w)
    extra = snapshot_extra(w)
    assert list(extra) == ["clinical"] and [c["case_id"] for c in extra["clinical"]["cases"]] == [t.id]
    assert extra["clinical"] == board(w)


def test_snapshot_extra_never_raises():
    w = fresh_world()
    er_trip(w)
    with patch.object(projection, "board", side_effect=RuntimeError("boom " + "x" * 500)), patch.object(
        projection.logger, "exception"
    ) as logged:
        extra = snapshot_extra(w)
    assert list(extra) == ["clinical"] and list(extra["clinical"]) == ["error"]
    assert extra["clinical"]["error"].startswith("RuntimeError: boom") and len(extra["clinical"]["error"]) == 200
    logged.assert_called_once()
    json.dumps(extra)


def test_snapshot_extra_empty_when_disabled():
    w = fresh_world()
    er_trip(w)
    before = os.environ.get("CLINICAL_ENABLED")
    os.environ["CLINICAL_ENABLED"] = "0"
    try:
        assert snapshot_extra(w) == {}
        os.environ["CLINICAL_ENABLED"] = "1"
        assert "clinical" in snapshot_extra(w)
    finally:
        if before is None:
            os.environ.pop("CLINICAL_ENABLED", None)
        else:
            os.environ["CLINICAL_ENABLED"] = before


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
