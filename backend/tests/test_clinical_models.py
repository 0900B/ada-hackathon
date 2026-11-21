"""Clinical entry models and config tables: pure data, no world and no env setup needed.

Run from backend/:  python tests/test_clinical_models.py   (or: python -m pytest tests)
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from pydantic import ValidationError

from app.clinical import config
from app.clinical.models import ENTRY_IN, ClinicalEntry, needs_check

base = {"case_id": "TR-1", "unit": "A1", "source": "crew_tap"}


def test_vitals_partial_ok_and_empty_rejected():
    ENTRY_IN.validate_python({**base, "type": "vitals", "content": {"spo2": 92}})
    with pytest.raises(ValidationError):
        ENTRY_IN.validate_python({**base, "type": "vitals", "content": {}})


def test_unknown_type_rejected():
    with pytest.raises(ValidationError):
        ENTRY_IN.validate_python({**base, "type": "diagnosis", "content": {"text": "x"}})


def test_naive_observed_t_rejected():
    with pytest.raises(ValidationError):
        ENTRY_IN.validate_python({**base, "type": "note", "content": {"text": "x"}, "observed_t": "2026-11-21T20:00:00"})
    ok = ENTRY_IN.validate_python({**base, "type": "note", "content": {"text": "x"}, "observed_t": "2026-11-21T20:00:00+01:00"})
    assert ok.observed_t.utcoffset() is not None


def test_er_action_requires_bay_or_team():
    with pytest.raises(ValidationError):
        ENTRY_IN.validate_python({**base, "type": "er_action", "content": {"action": "bay_assigned"}})
    with pytest.raises(ValidationError):
        ENTRY_IN.validate_python({**base, "type": "er_action", "content": {"action": "team_activated"}})
    with pytest.raises(ValidationError):
        ENTRY_IN.validate_python({**base, "type": "er_action", "content": {"action": "team_activated", "team": "xyz"}})
    ENTRY_IN.validate_python({**base, "type": "er_action", "content": {"action": "bay_assigned", "bay": "R1"}})
    ENTRY_IN.validate_python({**base, "type": "er_action", "content": {"action": "team_activated", "team": "stroke"}})
    ENTRY_IN.validate_python({**base, "type": "er_action", "content": {"action": "acknowledge"}})


def test_stroke_onset_requires_onset_t():
    with pytest.raises(ValidationError):
        ENTRY_IN.validate_python({**base, "type": "event", "content": {"kind": "stroke_onset"}})
    with pytest.raises(ValidationError):
        ENTRY_IN.validate_python({**base, "type": "event", "content": {"kind": "stroke_onset", "onset_t": "2026-11-21T19:00:00"}})
    ENTRY_IN.validate_python({**base, "type": "event", "content": {"kind": "stroke_onset", "onset_t": "2026-11-21T19:00:00+00:00"}})
    ENTRY_IN.validate_python({**base, "type": "event", "content": {"kind": "arrest"}})


def test_needs_check_flags_without_altering():
    content = {"spo2": 140}
    assert needs_check("vitals", content) and needs_check("vitals", {"gcs": 2})
    assert content == {"spo2": 140}
    assert not needs_check("vitals", {"spo2": 92, "hr": 80})
    assert not needs_check("note", {"text": "spo2 140"})
    assert not needs_check("vitals", {"spo2": None, "hr": 80})
    assert needs_check("vitals", {"hr": 80, "temp_c": 50})


def test_oversized_verbatim_and_bad_confidence_rejected():
    note = {**base, "type": "note", "content": {"text": "x"}}
    with pytest.raises(ValidationError):
        ENTRY_IN.validate_python({**note, "verbatim": "v" * 501})
    ENTRY_IN.validate_python({**note, "verbatim": "v" * 500})
    with pytest.raises(ValidationError):
        ENTRY_IN.validate_python({**note, "confidence": 1.5})
    with pytest.raises(ValidationError):
        ENTRY_IN.validate_python({**note, "confidence": -0.1})
    with pytest.raises(ValidationError):
        ENTRY_IN.validate_python({**note, "client_entry_id": "c" * 65})
    ENTRY_IN.validate_python({**note, "confidence": 0.5, "client_entry_id": "c" * 64})


def test_every_entry_type_validates_and_state_defaults_to_heard():
    samples = {
        "triage": {"level": "red", "problem_type": "stroke"},
        "patient_info": {"age_years": 70, "sex": "f"},
        "vitals": {"hr": 90},
        "drug_administered": {"drug": "aspirin", "dose": "300 mg", "route": "po"},
        "procedure": {"name": "intubation"},
        "severity": {"value": "orange"},
        "event": {"kind": "rosc"},
        "handover": {"note": "handed to team"},
        "free": {"note": "free text"},
        "note": {"text": "hello"},
        "er_action": {"action": "acknowledge"},
    }
    for type_, content in samples.items():
        parsed = ENTRY_IN.validate_python({**base, "type": type_, "content": content})
        assert parsed.type == type_
        assert parsed.state == "heard"
        assert parsed.observed_t is None
    assert ENTRY_IN.validate_python({**base, "type": "triage", "content": {"level": "red"}}).content.problem_type == "other"


def test_content_bounds_and_enums():
    for type_, content in [
        ("patient_info", {"age_years": 121}),
        ("patient_info", {"age_years": -1}),
        ("patient_info", {"sex": "x"}),
        ("severity", {"value": "purple"}),
        ("event", {"kind": "bogus"}),
        ("triage", {"level": "pink"}),
        ("triage", {"level": "scheduled"}),  # a card level inferred from priority, never a triage level
        ("triage", {"level": "red", "problem_type": "diagnosis"}),
        ("er_action", {"action": "teleport"}),
    ]:
        with pytest.raises(ValidationError):
            ENTRY_IN.validate_python({**base, "type": type_, "content": content})
    with pytest.raises(ValidationError):
        ENTRY_IN.validate_python({**base, "source": "nobody", "type": "note", "content": {"text": "x"}})
    with pytest.raises(ValidationError):
        ENTRY_IN.validate_python({**base, "state": "guessed", "type": "note", "content": {"text": "x"}})


def test_unknown_content_key_and_non_finite_vital_rejected():
    with pytest.raises(ValidationError):
        ENTRY_IN.validate_python({**base, "type": "vitals", "content": {"spo2": 92, "spo3": 1}})
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            ENTRY_IN.validate_python({**base, "type": "vitals", "content": {"spo2": bad}})


def test_clinical_entry_stored_shape():
    entry = ClinicalEntry(
        seq=1, entry_id="E-1", case_id="TR-1", type="vitals", content={"spo2": 92}, unit="A1",
        source="crew_tap", state="heard", t="2026-11-21T20:00:00+00:00", observed_t=None,
        recorded_at="2026-11-21T20:00:01+00:00", verbatim=None, confidence=None, supersedes=None,
        needs_check=False, client_entry_id=None,
    )
    assert entry.seq == 1 and entry.content == {"spo2": 92} and entry.needs_check is False


def test_config_tables():
    assert config.ER_PLACE_IDS == frozenset({"ukc"})
    assert config.HANDOVER_LIMIT_MIN == 15.0
    assert config.ARRIVING_UNACKED_MIN == 10.0
    assert config.NO_VITALS_RED_MIN == 10.0
    assert config.STROKE_WINDOW_MIN == 270.0
    assert config.SNAPSHOT_TAIL == 50
    assert config.LEVEL_BY_PRIORITY == {"emergency": "red", "urgent": "yellow", "scheduled": "scheduled"}
    assert config.STAGES[0] == "SPREJETO" and config.STAGES[-1] == "PROST" and len(config.STAGES) == 8
    assert config.CREW_SOURCES == frozenset({"crew_voice", "crew_tap", "monitor", "simulated_crew"})
    assert config.ER_ACTIONS == ("acknowledge", "bay_assigned", "team_activated")
    assert config.TEAMS == ("stroke", "heart", "trauma", "resuscitation_room")
    assert config.SUGGESTED_TEAM_BY_PROBLEM == {
        "stroke": "stroke", "stemi": "heart", "chest_pain": "heart", "polytrauma": "trauma",
        "severe_head_injury": "trauma", "resuscitation": "resuscitation_room",
    }
    assert config.PLAUSIBLE == {
        "hr": (0, 300), "sbp": (0, 300), "dbp": (0, 200), "spo2": (0, 100),
        "rr": (0, 80), "gcs": (3, 15), "temp_c": (25, 45), "glucose_mmol": (0, 60),
    }
    assert config.VITAL_LIMITS == {
        "spo2": (90, None), "sbp": (90, 180), "hr": (40, 130), "rr": (8, 30), "gcs": (9, None),
    }


def test_enabled_reads_env_each_call():
    saved = os.environ.get("CLINICAL_ENABLED")
    try:
        os.environ.pop("CLINICAL_ENABLED", None)
        assert config.enabled() is True
        os.environ["CLINICAL_ENABLED"] = "0"
        assert config.enabled() is False
        os.environ["CLINICAL_ENABLED"] = "1"
        assert config.enabled() is True
    finally:
        if saved is None:
            os.environ.pop("CLINICAL_ENABLED", None)
        else:
            os.environ["CLINICAL_ENABLED"] = saved


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
