"""The clinical log (append-only, in memory) and the shared clinical test helpers.

Run from backend/:  python tests/test_clinical_store.py   (or: python -m pytest tests)
Offline and self-contained: every test builds its own WorldState via fresh_world().
"""
from __future__ import annotations

import clinical_helpers  # noqa: F401  (must be first: sets the offline env, puts backend/ on sys.path)

import subprocess
import sys
import time
import traceback
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.clinical.models import ENTRY_IN, ClinicalEntry
from app.clinical.store import ClinicalLog, get_log
from clinical_helpers import drive, entry, er_trip, fresh_world, stored_fields

BACKEND = Path(__file__).resolve().parents[1]


def test_append_assigns_increasing_seq_and_ids():
    log = ClinicalLog()
    a = log.append(stored_fields())
    b = log.append(stored_fields())
    assert isinstance(a, ClinicalEntry)
    assert (a.seq, b.seq, a.entry_id, b.entry_id, log.last_seq) == (1, 2, "CE-00001", "CE-00002", 2)
    assert len(log) == 2
    assert log.get(2) is b and log.get(1) is a
    assert log.get(0) is None and log.get(3) is None
    assert ClinicalLog().last_seq == 0


def test_for_case_and_since_filter():
    log = ClinicalLog()
    a = log.append(stored_fields(case_id="TR-1"))
    b = log.append(stored_fields(case_id="TR-9"))
    c = log.append(stored_fields(case_id="TR-1"))
    assert [e.seq for e in log.for_case("TR-1")] == [a.seq, c.seq]  # log order
    assert log.for_case("TR-404") == []
    assert log.since(0) == [a, b, c]
    assert log.since(1) == [b, c]
    assert log.since(3) == []
    assert log.since(0, "TR-9") == [b]
    assert log.since(1, "TR-1") == [c]
    assert log.since(0, limit=2) == [a, b]  # oldest first, capped
    assert log.tail(2) == [b, c]
    assert log.tail(0) == []
    assert log.tail(99) == [a, b, c]


def test_client_id_is_scoped_per_unit():
    log = ClinicalLog()
    a1 = log.append(stored_fields(unit="A1", client_entry_id="x"))
    a2 = log.append(stored_fields(unit="A2", client_entry_id="x"))
    log.append(stored_fields(unit="A1", client_entry_id=None))
    assert log.by_client_id("A1", "x") is a1
    assert log.by_client_id("A2", "x") is a2
    assert log.by_client_id("A1", "x") is not log.by_client_id("A2", "x")
    assert log.by_client_id("A3", "x") is None
    assert log.by_client_id("A1", "nope") is None


def test_superseded_ids_follow_the_chain():
    log = ClinicalLog()
    a = log.append(stored_fields())
    b = log.append(stored_fields(supersedes=a.entry_id))
    c = log.append(stored_fields(supersedes=b.entry_id))
    assert log.superseded_ids() == {a.entry_id, b.entry_id}
    assert c.entry_id not in log.superseded_ids()
    assert ClinicalLog().superseded_ids() == set()


def test_get_log_attaches_and_reuses():
    w = fresh_world()
    assert not hasattr(w, "clinical")  # until the later state.py seam adds it, get_log attaches lazily
    assert get_log(w) is get_log(w) is w.clinical
    assert isinstance(w.clinical, ClinicalLog)
    assert get_log(fresh_world()) is not get_log(w)  # one log per world


def test_a_caller_cannot_rewrite_history_through_the_returned_lists():
    log = ClinicalLog()
    a = log.append(stored_fields())
    log.since(0).clear()
    log.for_case("TR-1").clear()
    log.tail(5).clear()
    assert len(log) == 1 and log.get(1) is a


def test_append_rejects_an_invalid_entry():
    log = ClinicalLog()
    with pytest.raises(ValidationError):
        log.append(stored_fields(source="nobody"))
    assert len(log) == 0 and log.last_seq == 0  # a refused entry takes no seq


def test_store_does_not_import_app_state_at_runtime():
    # In a clean interpreter, so what other test files already imported cannot hide a runtime import.
    code = "import sys; import app.clinical.store; sys.exit(1 if 'app.state' in sys.modules else 0)"
    result = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or "app.state was imported by app.clinical.store"


def test_helpers_build_a_dispatched_er_trip_and_a_valid_payload():
    w = fresh_world()
    trip = er_trip(w)
    assert trip.kind == "patient" and trip.vehicle_id is not None and trip.dropoff_id == "ukc"
    assert trip.id in w.trips and trip.note == "suspected stroke"
    payload = entry(trip)
    assert payload["case_id"] == trip.id and payload["unit"] == trip.vehicle_id
    parsed = ENTRY_IN.validate_python(payload)
    assert parsed.type == "vitals" and parsed.source == "simulated_crew"
    assert entry(trip, content={"hr": 120})["content"] == {"hr": 120}  # overrides apply on top
    assert ClinicalEntry.model_validate({**stored_fields(), "seq": 1, "entry_id": "CE-00001"}).seq == 1

    before = w.sim_time
    drive(w, 2, step_s=30)
    assert (w.sim_time - before).total_seconds() == 120
    drive(w, 60, until=lambda: True)  # stops after the first tick
    assert (w.sim_time - before).total_seconds() == 150


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
