"""Clinical entry rules: idempotency, ownership, time bounds, supersede and confirm.

Run from backend/:  python tests/test_clinical_service.py   (or: python -m pytest tests)
Offline and self-contained: every test builds its own WorldState via fresh_world(), never main.sim.
"""
from __future__ import annotations

import clinical_helpers  # noqa: F401  (must be first: sets the offline env, puts backend/ on sys.path)

import sys
import time
import traceback
from datetime import timedelta

import pytest

from app.audit import AUDIT
from app.clinical.models import ENTRY_IN, ClinicalEntry
from app.clinical.service import ClinicalError, case_start, case_trip, confirm_entry, record_entry
from app.clinical.store import get_log
from app.engine.events import apply_event
from app.models import TaskRequestEvent
from clinical_helpers import drive, entry, er_trip, fresh_world


def rec(w, trip, **overrides):
    """Record a valid entry for `trip` (the helper payload with shallow overrides) and return (entry, created)."""
    return record_entry(w, ENTRY_IN.validate_python(entry(trip, **overrides)))


def refused(w, trip, **overrides) -> ClinicalError:
    with pytest.raises(ClinicalError) as excinfo:
        rec(w, trip, **overrides)
    return excinfo.value


def unassigned_trip(w):
    record = apply_event(
        w,
        TaskRequestEvent(
            type="task_request", pickup_id="home_polje", dropoff_id="ukc", needs="stretcher", auto_assign=False
        ),
    )
    return w.trips[record.affected_trip_ids[0]]


def test_record_stamps_time_and_bumps_version():
    w = fresh_world()
    t = er_trip(w)
    v = w.version
    e, created = record_entry(w, ENTRY_IN.validate_python(entry(t)))
    assert created and e.t == w.sim_time and e.observed_t == w.sim_time and w.version > v
    assert isinstance(e, ClinicalEntry) and e.entry_id == "CE-00001" and e.seq == 1
    assert e.recorded_at.tzinfo is not None and e.state == "heard" and e.needs_check is False
    assert get_log(w).get(e.seq) is e and get_log(w).for_case(t.id) == [e]


def test_record_stores_content_as_json_safe_dict_exactly_as_entered():
    w = fresh_world()
    t = er_trip(w)
    e, _ = rec(w, t, content={"hr": 80, "spo2": 140})  # implausible: kept as entered, only flagged
    assert e.content["spo2"] == 140 and e.content["hr"] == 80 and e.needs_check is True
    assert isinstance(e.content, dict)
    ok, _ = rec(w, t, content={"hr": 70})
    assert ok.needs_check is False


def test_duplicate_client_entry_id_returns_original():  # Review Focus 4
    w = fresh_world()
    t = er_trip(w)
    p = ENTRY_IN.validate_python(entry(t, client_entry_id="c-1"))
    first = record_entry(w, p)
    v = w.version
    second = record_entry(w, p)
    assert first[1] is True and second == (first[0], False) and len(get_log(w)) == 1
    assert w.version == v  # a replay changes nothing, so it is not announced to clients either


def test_duplicate_wins_before_any_other_rule():
    w = fresh_world()
    t = er_trip(w)
    p = ENTRY_IN.validate_python(entry(t, client_entry_id="c-1"))
    first = record_entry(w, p)
    t.vehicle_id = "A2" if t.vehicle_id != "A2" else "A3"  # the same payload would now be refused ...
    assert record_entry(w, p) == (first[0], False)  # ... but a replay still gets the original back
    assert len(get_log(w)) == 1


def test_client_entry_id_is_only_unique_per_unit():
    w = fresh_world()
    t = er_trip(w)
    a = rec(w, t, source="dispatcher", unit="disp-1", client_entry_id="c-1")
    b = rec(w, t, source="dispatcher", unit="disp-2", client_entry_id="c-1")
    again = rec(w, t, source="dispatcher", unit="disp-2", client_entry_id="c-1")
    assert a[1] and b[1] and a[0].seq != b[0].seq
    assert again == (b[0], False) and len(get_log(w)) == 2


def test_entries_without_a_client_id_are_never_deduplicated():
    w = fresh_world()
    t = er_trip(w)
    assert rec(w, t)[1] and rec(w, t)[1] and len(get_log(w)) == 2


def test_crew_entry_from_wrong_vehicle_is_409():  # Review Focus 1
    w = fresh_world()
    t = er_trip(w)
    other = next(v for v in w.vehicles if v != t.vehicle_id)
    err = refused(w, t, unit=other)
    assert err.status == 409 and t.vehicle_id in err.message
    assert len(get_log(w)) == 0


def test_every_crew_source_is_bound_to_the_trips_vehicle():
    w = fresh_world()
    t = er_trip(w)
    other = next(v for v in w.vehicles if v != t.vehicle_id)
    for source in ("crew_voice", "crew_tap", "monitor", "simulated_crew"):
        assert refused(w, t, source=source, unit=other).status == 409, source
        assert rec(w, t, source=source)[1] is True, source


def test_non_crew_sources_are_not_bound_to_a_vehicle():
    w = fresh_world()
    t = er_trip(w)
    assert rec(w, t, source="dispatcher", unit="disp-1")[1]
    assert rec(w, t, source="system", unit="system")[1]
    assert rec(w, t, source="er_reception", unit="er", type="note", content={"text": "bed ready"})[1]


def test_crew_entry_on_unassigned_trip_is_409():
    w = fresh_world()
    t = unassigned_trip(w)
    assert t.vehicle_id is None and t.status == "unassigned"
    err = refused(w, t, unit="A1")
    assert err.status == 409 and "no vehicle" in err.message
    assert rec(w, t, source="dispatcher", unit="disp-1")[1]  # but dispatch can still write to it


def test_reassigned_trip_blocks_old_vehicle_and_keeps_old_entries():
    w = fresh_world()
    t = er_trip(w)
    old_unit = t.vehicle_id
    first, _ = rec(w, t)
    t.vehicle_id = "A2" if t.vehicle_id != "A2" else "A3"
    assert refused(w, t, unit=old_unit).status == 409
    assert get_log(w).for_case(t.id) == [first]
    assert rec(w, t, unit=t.vehicle_id)[1]  # the new vehicle can write


def test_unknown_trip_404_and_equipment_trip_422():
    w = fresh_world()
    t = er_trip(w)
    assert refused(w, t, case_id="TR-nope").status == 404
    record = apply_event(
        w,
        TaskRequestEvent(
            type="task_request", kind="equipment", needs="equipment",
            pickup_id="ukc", dropoff_id="onko", label="blood products",
        ),
    )
    equipment = w.trips[record.affected_trip_ids[0]]
    assert equipment.kind == "equipment"
    err = refused(w, t, case_id=equipment.id, source="dispatcher", unit="disp-1")
    assert err.status == 422
    assert len(get_log(w)) == 0


def test_case_trip_and_case_start():
    w = fresh_world()
    t = er_trip(w)
    assert case_trip(w, t.id) is t
    assert t.dispatched_at is not None and case_start(t) == t.dispatched_at
    scheduled = unassigned_trip(w)
    assert scheduled.dispatched_at is None and case_start(scheduled) == scheduled.pickup_after
    with pytest.raises(ClinicalError) as excinfo:
        case_trip(w, "TR-nope")
    assert excinfo.value.status == 404 and "TR-nope" in excinfo.value.message


def test_observed_t_bounds_422():  # Review Focus 2
    w = fresh_world()
    t = er_trip(w)
    drive(w, 3)
    future = w.sim_time + timedelta(seconds=1)
    before_case = case_start(t) - timedelta(seconds=1)
    assert refused(w, t, observed_t=future.isoformat()).status == 422
    assert refused(w, t, observed_t=before_case.isoformat()).status == 422
    assert len(get_log(w)) == 0
    earlier = w.sim_time - timedelta(minutes=1)
    e, created = rec(w, t, observed_t=earlier.isoformat())
    assert created and e.observed_t == earlier and e.t == w.sim_time and e.t != e.observed_t


def test_observed_t_bounds_are_inclusive():
    w = fresh_world()
    t = er_trip(w)
    drive(w, 2)
    assert rec(w, t, observed_t=w.sim_time.isoformat())[0].observed_t == w.sim_time
    assert rec(w, t, observed_t=case_start(t).isoformat())[0].observed_t == case_start(t)


def test_er_action_only_from_er_reception():
    w = fresh_world()
    t = er_trip(w)
    action = {"type": "er_action", "content": {"action": "acknowledge"}}
    assert refused(w, t, source="crew_tap", **action).status == 422
    assert refused(w, t, source="dispatcher", unit="disp-1", **action).status == 422
    assert len(get_log(w)) == 0
    e, created = rec(w, t, source="er_reception", unit="er", **action)
    assert created and e.type == "er_action" and e.content["action"] == "acknowledge"


def test_stroke_onset_time_cannot_be_in_the_future():
    w = fresh_world()
    t = er_trip(w)
    drive(w, 2)
    future = (w.sim_time + timedelta(minutes=5)).isoformat()
    past = (w.sim_time - timedelta(minutes=45)).isoformat()  # may precede the call: the patient fell ill earlier
    err = refused(w, t, type="event", content={"kind": "stroke_onset", "onset_t": future})
    assert err.status == 422
    e, created = rec(w, t, type="event", content={"kind": "stroke_onset", "onset_t": past})
    assert created and e.content["kind"] == "stroke_onset" and e.content["onset_t"] is not None
    assert len(get_log(w)) == 1


def test_supersedes_rules():
    w = fresh_world()
    t = er_trip(w)
    first, _ = rec(w, t)
    other_trip = er_trip(w, note="chest pain")
    foreign, _ = rec(w, other_trip)
    assert other_trip.id != t.id
    assert refused(w, t, supersedes=foreign.entry_id).status == 422  # another case's entry
    assert refused(w, t, supersedes="CE-99999").status == 422  # names nothing
    assert refused(w, t, supersedes="not-an-id").status == 422
    assert len(get_log(w)) == 2

    fixed, created = rec(w, t, supersedes=first.entry_id, content={"hr": 82, "spo2": 96})
    assert created and fixed.supersedes == first.entry_id
    again = refused(w, t, supersedes=first.entry_id)  # already replaced
    assert again.status == 409 and first.entry_id in again.message and fixed.entry_id in again.message
    assert get_log(w).superseded_ids() == {first.entry_id}
    chained, _ = rec(w, t, supersedes=fixed.entry_id)  # but the replacement itself can be corrected
    assert chained.supersedes == fixed.entry_id


def test_refused_entry_changes_nothing():
    w = fresh_world()
    t = er_trip(w)
    other = next(v for v in w.vehicles if v != t.vehicle_id)
    version, audited, last = w.version, len(AUDIT.recent), AUDIT.recent[-1] if AUDIT.recent else None
    refused(w, t, unit=other)
    refused(w, t, supersedes="CE-99999")
    assert w.version == version and len(get_log(w)) == 0
    assert (AUDIT.recent[-1] if AUDIT.recent else None) is last and len(AUDIT.recent) == audited


def test_confirm_appends_confirmed_copy_and_rejects_superseded():  # Review Focus 5
    w = fresh_world()
    t = er_trip(w)
    e, _ = rec(
        w, t, source="crew_voice", state="heard", client_entry_id="c-1",
        verbatim="saturation ninety five", confidence=0.7, content={"hr": 80, "spo2": 95},
    )
    v = w.version
    c = confirm_entry(w, e.seq, t.vehicle_id)
    assert c.state == "confirmed" and c.supersedes == e.entry_id
    assert c.seq != e.seq and c.type == e.type and c.content == e.content and c.case_id == e.case_id
    assert c.observed_t == e.observed_t and c.verbatim == e.verbatim and c.confidence == e.confidence
    assert c.source == "crew_tap" and c.unit == t.vehicle_id
    assert c.client_entry_id is None  # a copy is a new entry, not a replay of the original's id
    assert w.version > v
    assert get_log(w).get(e.seq).state == "heard"  # the original is never edited
    assert get_log(w).superseded_ids() == {e.entry_id}
    with pytest.raises(ClinicalError) as x:
        confirm_entry(w, e.seq, t.vehicle_id)
    assert x.value.status == 409
    assert len(get_log(w)) == 2


def test_confirm_goes_through_the_same_rules():
    w = fresh_world()
    t = er_trip(w)
    e, _ = rec(w, t)
    other = next(v for v in w.vehicles if v != t.vehicle_id)
    with pytest.raises(ClinicalError) as wrong_unit:
        confirm_entry(w, e.seq, other)
    assert wrong_unit.value.status == 409 and t.vehicle_id in wrong_unit.value.message
    with pytest.raises(ClinicalError) as unknown:
        confirm_entry(w, 99, t.vehicle_id)
    assert unknown.value.status == 404
    with pytest.raises(ClinicalError) as bad_source:
        confirm_entry(w, e.seq, t.vehicle_id, source="nobody")  # type: ignore[arg-type]
    assert bad_source.value.status == 422
    assert len(get_log(w)) == 1
    c = confirm_entry(w, e.seq, "disp-1", source="dispatcher")  # a dispatcher may confirm too
    assert c.source == "dispatcher" and c.unit == "disp-1" and c.state == "confirmed"


def test_confirm_works_on_an_unassigned_trip_whose_pickup_is_still_ahead():
    w = fresh_world()
    t = unassigned_trip(w)
    assert t.dispatched_at is None and case_start(t) > w.sim_time  # the default observed_t (now) precedes case_start
    e, _ = rec(w, t, source="dispatcher", unit="disp-1", type="note", content={"text": "call back the family"})
    assert e.observed_t == w.sim_time and e.observed_t < case_start(t)
    c = confirm_entry(w, e.seq, "disp-1", source="dispatcher")
    assert c.state == "confirmed" and c.supersedes == e.entry_id
    assert c.observed_t == e.observed_t and c.content == e.content  # the observation is restated, not moved to now
    assert get_log(w).superseded_ids() == {e.entry_id}


def test_confirm_works_after_the_trip_was_dispatched_again_later():
    w = fresh_world()
    t = er_trip(w)
    e, _ = rec(w, t, source="crew_voice")
    drive(w, 3)
    t.dispatched_at = w.sim_time  # a re-dispatch (e.g. after a grounding) moves the case start past the entry
    assert e.observed_t < case_start(t)
    c = confirm_entry(w, e.seq, t.vehicle_id)
    assert c.state == "confirmed" and c.supersedes == e.entry_id
    assert c.observed_t == e.observed_t and c.t == w.sim_time and c.t != c.observed_t
    # The bound still holds for a NEW observation: only a restated one skips it.
    assert refused(w, t, observed_t=e.observed_t.isoformat()).status == 422


def test_confirm_keeps_a_stored_event_time_intact():
    w = fresh_world()
    t = er_trip(w)
    drive(w, 3)
    onset = (w.sim_time - timedelta(minutes=30)).isoformat()
    e, _ = rec(w, t, type="event", content={"kind": "stroke_onset", "onset_t": onset})
    c = confirm_entry(w, e.seq, t.vehicle_id)
    assert c.content == e.content and c.type == "event"


def test_audit_mirror():
    w = fresh_world()
    t = er_trip(w)
    e, _ = rec(w, t)
    last = AUDIT.recent[-1]
    assert last["kind"] == "clinical" and last["ref"] == e.entry_id and last["world"] == w.name
    assert last["payload"]["case_id"] == t.id and last["payload"]["seq"] == e.seq
    assert e.type in last["summary"] and t.id in last["summary"]
    rec(w, t, client_entry_id="c-1")
    rec(w, t, client_entry_id="c-1")  # replay: not mirrored a second time
    assert AUDIT.recent[-1]["ref"] == "CE-00002"


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
