# ER Reception Dashboard Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a clinical event log, a crew API and an ER read model to `main`'s backend, delivered through the existing snapshot and stream so the ER, dispatch and crew screens always show the same data.

**Architecture:** A new self-contained package `backend/app/clinical/` (log, validation, projection, alerts, router). It reaches the app through a two-file additive seam: one line in `WorldState.reset_simulation`, one in `WorldState.snapshot()`, and one `mount()` call in `main.py`. Cases are derived from trips every time; nothing hooks the engine or simulator.

**Tech Stack:** Python (3.12 target, 3.13 in the local venv), FastAPI, pydantic v2, httpx (already in `requirements.txt`, used by the crew simulator), pytest (dev only, never added to `requirements.txt`).

**Spec:** `docs/superpowers/specs/2026-11-21-er-dashboard-backend-design.md`. This plan covers phases 1 and 2. Phase 3 (Slovenian clinical phrases, ER board page) is out of scope.

## Global Constraints

- Work only in `C:\Users\telki\ada-hackathon-erdashboard` on branch `metelko-erdashboard`. Never push. Never touch `main` or the checkout at `C:\Users\telki\ada-hackathon`.
- Edit shared files **only** `backend/app/state.py` and `backend/app/main.py`, additively, in **their own commit**. No change to existing models, events, engine, simulator, routes or snapshot keys.
- State is in memory, one replica. No database, no new runtime dependency.
- `CLINICAL_ENABLED=0` must give exactly today's behaviour: no `clinical` snapshot key, no routes mounted.
- The snapshot section must never raise: on any error it logs and returns `{"error": "..."}`.
- Never alter a value: implausible vitals are kept and flagged `needs_check`. Every vital on a card carries its age in minutes.
- ER alerts live in the `clinical` section, never in the teammates' `Alert` model. Clinical limits and the stroke window are labelled placeholders `[A]`, not clinical guidance.
- All patient data is synthetic. Entry times are world time (`state.sim_time`), as the engine does.

## Review Focus

Failure modes the spec implies; each has a pinned test in the task named in brackets.

1. A crew entry for an unassigned trip, or from a vehicle that no longer holds the trip, must return 409 with a clear message and keep earlier entries visible. [Task 4]
2. A naive, future, or pre-case `observed_t` must be rejected with 422, never a 500 and never silently clamped. [Tasks 2, 4, 6]
3. A partial vitals entry must not erase other metrics; an implausible number is shown, flagged, and unchanged. [Task 5]
4. A tablet retrying the same `client_entry_id` after a dropped connection must get the original entry back and create no duplicate. [Tasks 4, 6]
5. Confirming or correcting an entry already superseded must return 409, and the card must show only the latest value. [Tasks 4, 5]

## File Structure

```
backend/app/clinical/__init__.py     empty
backend/app/clinical/config.py       tables and thresholds (no logic beyond enabled())
backend/app/clinical/models.py       entry input models, stored entry, needs_check()
backend/app/clinical/store.py        ClinicalLog, get_log()
backend/app/clinical/service.py      validation + append rules, ClinicalError
backend/app/clinical/projection.py   cases, stages, cards, board(), snapshot_extra()
backend/app/clinical/alerts.py       handover timer, alerts, suggested actions
backend/app/clinical/api.py          mount(app, worlds)
backend/tools/crew_sim.py            test client, never imported by the server
backend/tests/clinical_helpers.py    shared test setup
backend/tests/test_clinical_{models,store,service,projection,api,integration,crew_sim,alerts}.py
modify: backend/app/state.py, backend/app/main.py   (seam, Task 7 only)
```

**Test conventions (every new test file):** start with `import clinical_helpers  # noqa: F401` first (it sets `ROAD_ROUTING=0`, `AGENT_AUTO=0`, removes `ANTHROPIC_API_KEY`, adds `backend/` to `sys.path`), plain `test_*` functions, and the `__main__` runner copied from the end of `tests/test_live_calls.py`. Run from `backend/` with `.venv/Scripts/python.exe -m pytest <file> -q`.

---

### Task 1: Environment and baseline

**Files:** none changed (`backend/.venv` is already in `.gitignore`).

- [ ] **Step 1: Rebase onto current `main`.** `main` has moved since the branch was cut (16 commits at plan time; none touched `state.py` or `main.py`). Run `git fetch origin`, then `git rebase origin/main` (the branch holds only docs commits and was never pushed, so there is nothing to conflict). Then `git diff --stat <old-base>..origin/main -- backend/app/state.py backend/app/main.py` must still be empty, where `<old-base>` is `2af1e48`; if upstream changed either seam file, stop and tell the user before continuing.
- [ ] **Step 2:** From `backend/`: `python -m venv .venv`, then `.venv/Scripts/python.exe -m pip install -r requirements.txt pytest`.
- [ ] **Step 3:** Run `.venv/Scripts/python.exe -m pytest tests -q` on the untouched tree. Save the full output to `C:\Users\telki\AppData\Local\Temp\claude\91650a5436204d05\8575dcd5-1990-4b44-9501-73b0b4ad42f4\scratchpad\baseline.txt`.
  Expected: every existing test file runs (five at plan time; more after the rebase). Record the pass/fail counts per file. A failure here is a baseline failure, reported as such, never "fixed".
- [ ] **Step 4:** Confirm `git status` shows no tracked changes. No commit.

---

### Task 2: Config tables and entry models

**Files:** Create `app/clinical/__init__.py`, `config.py`, `models.py`; Test `tests/test_clinical_models.py`.

**Interfaces:**
- Produces `config.py`: `enabled() -> bool` (reads `CLINICAL_ENABLED` each call, true unless `"0"`); `ER_PLACE_IDS = frozenset({"ukc"})`; `HANDOVER_LIMIT_MIN = 15.0`; `ARRIVING_UNACKED_MIN = 10.0`; `NO_VITALS_RED_MIN = 10.0`; `STROKE_WINDOW_MIN = 270.0`; `SNAPSHOT_TAIL = 50`; `LEVEL_BY_PRIORITY = {"emergency": "red", "urgent": "yellow", "scheduled": "scheduled"}`; `STAGES = ("SPREJETO", "NA POTI", "NA KRAJU", "PRI PACIENTU", "S KRAJA", "NA CILJU", "PREDAJA PACIENTA", "PROST")`; `CREW_SOURCES = frozenset({"crew_voice", "crew_tap", "monitor", "simulated_crew"})`; `ER_ACTIONS = ("acknowledge", "bay_assigned", "team_activated")`; `TEAMS = ("stroke", "heart", "trauma", "resuscitation_room")`; `SUGGESTED_TEAM_BY_PROBLEM` (`stroke→stroke`, `stemi→heart`, `chest_pain→heart`, `polytrauma→trauma`, `severe_head_injury→trauma`, `resuscitation→resuscitation_room`); `PLAUSIBLE: dict[str, tuple[float, float]]` (`hr` 0–300, `sbp` 0–300, `dbp` 0–200, `spo2` 0–100, `rr` 0–80, `gcs` 3–15, `temp_c` 25–45, `glucose_mmol` 0–60); `VITAL_LIMITS: dict[str, tuple[float | None, float | None]]` placeholders `[A]` (`spo2` (90, None), `sbp` (90, 180), `hr` (40, 130), `rr` (8, 30), `gcs` (9, None)), commented as "PLACEHOLDER, not clinical guidance; ER staff must set".
- Produces `models.py`: aliases `Level`, `Source`, `EntryState`, `ProblemType`; content models `TriageContent(level, problem_type="other")`, `PatientInfoContent(age_years: int|None 0..120, sex: "f"|"m"|"unknown"|None)`, `VitalsContent` (`hr sbp dbp spo2 rr gcs temp_c glucose_mmol`, all `float | None`, at least one required), `DrugContent(drug, dose, route)` (strings, never interpreted), `ProcedureContent(name)`, `SeverityContent(value: blue|green|orange|red|arrest)`, `EventContent(kind: arrest|resuscitation_started|rosc|airway|stroke_onset|stemi|transfusion, onset_t: AwareDatetime|None, required for stroke_onset)`, `HandoverContent(note)`, `FreeContent(note)`, `NoteContent(text)`, `ERActionContent(action, bay, team)` (bay required for `bay_assigned`, team required and in `TEAMS` for `team_activated`); base `EntryBase` with `case_id: str, unit: str, source: Source, state: EntryState = "heard", observed_t: AwareDatetime | None = None, verbatim: str | None (max 500), confidence: float | None (0..1), supersedes: str | None, client_entry_id: str | None (max 64)`; one subclass per type adding `type: Literal[...]` and `content`; `EntryIn = Annotated[Union[...], Field(discriminator="type")]`; `ENTRY_IN = TypeAdapter(EntryIn)`; stored `ClinicalEntry(seq, entry_id, case_id, type, content: dict, unit, source, state, t, observed_t, recorded_at, verbatim, confidence, supersedes, needs_check, client_entry_id)`; `needs_check(entry_type: str, content: dict) -> bool`.

- [ ] **Step 1: Write the failing tests** in `test_clinical_models.py` (shared `base = {"case_id": "TR-1", "unit": "A1", "source": "crew_tap"}`):

```python
def test_vitals_partial_ok_and_empty_rejected():
    ENTRY_IN.validate_python({**base, "type": "vitals", "content": {"spo2": 92}})
    with pytest.raises(ValidationError): ENTRY_IN.validate_python({**base, "type": "vitals", "content": {}})
def test_unknown_type_rejected(): ...  # type "diagnosis" raises ValidationError
def test_naive_observed_t_rejected():  # Review Focus 2
    with pytest.raises(ValidationError):
        ENTRY_IN.validate_python({**base, "type": "note", "content": {"text": "x"}, "observed_t": "2026-11-21T20:00:00"})
def test_er_action_requires_bay_or_team():
    # bay_assigned without bay, team_activated with team "xyz": both raise
def test_stroke_onset_requires_onset_t():  # event kind "stroke_onset" without onset_t raises; with an aware onset_t passes
def test_needs_check_flags_without_altering():
    assert needs_check("vitals", {"spo2": 140}) and needs_check("vitals", {"gcs": 2})
    assert not needs_check("vitals", {"spo2": 92, "hr": 80})
def test_oversized_verbatim_and_bad_confidence_rejected(): ...  # 501 chars; confidence 1.5
```
- [ ] **Step 2:** Run `.venv/Scripts/python.exe -m pytest tests/test_clinical_models.py -q`. Expected: FAIL (module not found).
- [ ] **Step 3:** Implement the interfaces above in `config.py` and `models.py`.
- [ ] **Step 4:** Re-run. Expected: PASS.
- [ ] **Step 5:** `git add app/clinical tests/test_clinical_models.py && git commit -m "clinical: config tables and entry models"`

---

### Task 3: The clinical log

**Files:** Create `app/clinical/store.py`, `tests/clinical_helpers.py`; Test `tests/test_clinical_store.py`.

**Interfaces:**
- Consumes: `ClinicalEntry` from Task 2.
- Produces `store.py`: `class ClinicalLog` with `append(self, fields: dict[str, Any]) -> ClinicalEntry` (assigns `seq` from 1 and `entry_id = f"CE-{seq:05d}"`), `get(seq: int) -> ClinicalEntry | None`, `by_client_id(unit: str, client_entry_id: str) -> ClinicalEntry | None`, `for_case(case_id: str) -> list[ClinicalEntry]` (log order), `since(seq: int = 0, case_id: str | None = None, limit: int = 500) -> list[ClinicalEntry]`, `tail(n: int) -> list[ClinicalEntry]`, `superseded_ids() -> set[str]`, property `last_seq -> int`, `__len__`; `get_log(state) -> ClinicalLog` (returns `state.clinical`, creating and attaching it if the attribute is absent). `store.py` must not import `app.state` at runtime (TYPE_CHECKING only).
- Produces `clinical_helpers.py`: sets the env described under Test conventions; `fresh_world() -> WorldState` (`WorldState("t")` then `seed_world(w, 42, scheduled_day=False)`); `er_trip(w, note="suspected stroke", priority="emergency", pickup="home_polje") -> Trip` (applies `UrgentRequestEvent(type="urgent_request", pickup_id=pickup, priority=priority, needs="stretcher", note=note)` and returns `w.trips[record.affected_trip_ids[0]]`); `drive(w, minutes: float, until=None, step_s: float = 30)` (ticks `tick` + `project_all`, stops early when `until()` is true); `entry(trip, **overrides) -> dict` (a valid vitals payload from `trip.vehicle_id`, source `simulated_crew`).

- [ ] **Step 1: Write the failing tests:**

```python
def test_append_assigns_increasing_seq_and_ids():
    log = ClinicalLog(); a = log.append(fields(...)); b = log.append(fields(...))
    assert (a.seq, b.seq, a.entry_id, log.last_seq) == (1, 2, "CE-00001", 2)
def test_for_case_and_since_filter(): ...  # since(1) == [entry 2]; since(0, "TR-9") only that case
def test_client_id_is_scoped_per_unit():
    assert log.by_client_id("A1", "x") is not log.by_client_id("A2", "x")
def test_superseded_ids_follow_the_chain():  # B supersedes A, C supersedes B
    assert log.superseded_ids() == {a.entry_id, b.entry_id}
def test_get_log_attaches_and_reuses():
    w = fresh_world(); assert get_log(w) is get_log(w) is w.clinical
```
- [ ] **Step 2:** Run `tests/test_clinical_store.py`. Expected: FAIL.
- [ ] **Step 3:** Implement `store.py` and `clinical_helpers.py`.
- [ ] **Step 4:** Re-run. Expected: PASS.
- [ ] **Step 5:** `git add app/clinical/store.py tests/clinical_helpers.py tests/test_clinical_store.py && git commit -m "clinical: append-only log and test helpers"`

---

### Task 4: Entry rules (service)

**Files:** Create `app/clinical/service.py`; Test `tests/test_clinical_service.py`.

**Interfaces:**
- Consumes: `get_log`, `ClinicalEntry`, `EntryBase`, `ENTRY_IN`, `needs_check`, `config.CREW_SOURCES`, `app.audit.AUDIT`.
- Produces `service.py`: `class ClinicalError(Exception)` with `.status: int` and `.message: str`; `case_trip(state, case_id: str) -> Trip` (404 unknown, 422 if `kind != "patient"`); `case_start(trip: Trip) -> datetime` (`trip.dispatched_at or trip.pickup_after`); `record_entry(state, entry: EntryBase) -> tuple[ClinicalEntry, bool]` (bool = newly created); `confirm_entry(state, seq: int, unit: str, source: Source = "crew_tap") -> ClinicalEntry`.
- Rules, in order: duplicate `(unit, client_entry_id)` returns `(existing, False)` before anything else; source in `CREW_SOURCES` requires `unit == trip.vehicle_id` else 409 (message names the expected vehicle, or says the trip has no vehicle); type `er_action` requires source `er_reception` else 422; `observed_t` must be ≤ `state.sim_time` and ≥ `case_start(trip)` else 422, default `state.sim_time`; `stroke_onset` `onset_t` must be ≤ `state.sim_time` else 422; `supersedes` must name an entry on the same case (422) that is not already superseded (409); `t = state.sim_time`, `recorded_at = utcnow()`, `needs_check` from `needs_check()`. Success: append, `AUDIT.record(state.name, "clinical", summary, ref=entry_id, payload=entry)`, `state.bump()`. `confirm_entry` appends a copy of the original with `state="confirmed"`, `supersedes=original.entry_id`, through `record_entry`.

- [ ] **Step 1: Write the failing tests** (use `fresh_world`, `er_trip`):

```python
def test_record_stamps_time_and_bumps_version():
    w = fresh_world(); t = er_trip(w); v = w.version
    e, created = record_entry(w, ENTRY_IN.validate_python(entry(t)))
    assert created and e.t == w.sim_time and e.observed_t == w.sim_time and w.version > v
def test_duplicate_client_entry_id_returns_original():  # Review Focus 4
    first = record_entry(w, p); second = record_entry(w, p)
    assert second == (first[0], False) and len(get_log(w)) == 1
def test_crew_entry_from_wrong_vehicle_is_409():  # Review Focus 1
    other = next(v for v in w.vehicles if v != t.vehicle_id)
    assert excinfo.value.status == 409 and t.vehicle_id in excinfo.value.message
def test_crew_entry_on_unassigned_trip_is_409():  # TaskRequestEvent(auto_assign=False) trip, vehicle_id None
def test_reassigned_trip_blocks_old_vehicle_and_keeps_old_entries():
    record_entry(...); t.vehicle_id = "A2" if t.vehicle_id != "A2" else "A3"
    # same unit now 409; get_log(w).for_case(t.id) still has the first entry
def test_unknown_trip_404_and_equipment_trip_422():  # case_id "TR-nope" -> status 404; an equipment TaskRequestEvent trip -> status 422
def test_observed_t_bounds_422():  # Review Focus 2: future, and before case_start; a valid earlier value is stored, t != observed_t
def test_er_action_only_from_er_reception(): ...  # source "crew_tap" with type er_action -> 422
def test_supersedes_rules():  # other case's entry -> 422
def test_confirm_appends_confirmed_copy_and_rejects_superseded():  # Review Focus 5
    c = confirm_entry(w, e.seq, t.vehicle_id)
    assert c.state == "confirmed" and c.supersedes == e.entry_id
    with pytest.raises(ClinicalError) as x: confirm_entry(w, e.seq, t.vehicle_id)
    assert x.value.status == 409
def test_audit_mirror(): assert AUDIT.recent[-1]["kind"] == "clinical" and AUDIT.recent[-1]["ref"] == e.entry_id
```
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement `service.py`.
- [ ] **Step 4:** Re-run. Expected: PASS.
- [ ] **Step 5:** `git add app/clinical/service.py tests/test_clinical_service.py && git commit -m "clinical: entry rules, idempotency, supersede and confirm"`

---

### Task 5: Cases, stages and the board

**Files:** Create `app/clinical/projection.py`; Test `tests/test_clinical_projection.py`.

**Interfaces:**
- Consumes: `get_log`, `config`, `app.engine.projection.DONE`, `app.state.SNAPSHOT_DONE_HOURS`.
- Produces `projection.py`: `er_case_trips(state) -> list[Trip]` (patient trips with `dropoff_id` in `ER_PLACE_IDS`, not cancelled, and open or with `eta_dropoff >= sim_time - SNAPSHOT_DONE_HOURS`); `stage_of(state, trip, entries) -> tuple[str | None, bool]` (stage, inferred); `build_case(state, trip, entries) -> dict`; `board(state) -> dict`; `snapshot_extra(state) -> dict` (`{}` when `not enabled()`; otherwise `{"clinical": board(state)}`, or `{"clinical": {"error": "<Type>: <msg>"[:200]}}` after `log.exception` on any failure).
- Stage rules: a non-superseded `free` entry → `PROST`; else a `handover` entry → `PREDAJA PACIENTA`; else trip `completed` → `NA CILJU`; `onboard` with vehicle status `loading` → `PRI PACIENTU` (inferred), other `onboard` → `S KRAJA` (inferred); `en_route_pickup` with `vehicle.waiting_until` set → `NA KRAJU` (inferred), else `NA POTI` (inferred); `assigned` → `SPREJETO`; `unassigned` → `None`.
- Card keys (stable, all always present): `case_id, vehicle_id, patient_label, priority, level {value, inferred, source}, problem {type, note}, age_years, sex, eta_dropoff, minutes_to_arrival, arrived_at, stage, stage_inferred, severity, vitals {metric: {value, age_min, state, needs_check, seq}}, treatments [{seq, type, content, observed_t, state, needs_check}], events [{kind, observed_t, onset_t, state}], acknowledged, bay, teams_activated, handover (None until Task 9), suggested_actions ([] until Task 9), alert_ids ([] until Task 9)`. Superseded entries are ignored everywhere; vitals resolve latest-per-metric by `(observed_t, seq)`; `age_min = round((sim_time - observed_t) / 60 s, 1)`; level comes from the latest `triage` entry, else `LEVEL_BY_PRIORITY` with `inferred: True`.
- `board(state)` returns `{"world", "as_of", "seq", "cases", "alerts", "entries_tail"}`: cases not yet arrived first by `eta_dropoff` (unassigned last), then arrived by `arrived_at` descending; `alerts` is `[]` until Task 9; `entries_tail` is the last `SNAPSHOT_TAIL` entries as `model_dump(mode="json")`. The whole result must pass `json.dumps`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_board_empty_when_no_er_trips(): assert board(fresh_world())["cases"] == []
def test_only_patient_trips_to_er_places_appear():
    # ER trip, an urgent_request with dropoff_id="onko", an equipment TaskRequestEvent to "onko"
    assert [c["case_id"] for c in board(w)["cases"]] == [t.id]
def test_cancelled_trip_is_excluded(): t.status = "cancelled"; assert board(w)["cases"] == []
def test_level_inferred_then_overridden_by_triage():
    assert card["level"] == {"value": "red", "inferred": True, "source": None}
    # after a dispatcher triage entry level yellow:
    assert card["level"]["value"] == "yellow" and card["level"]["inferred"] is False
def test_stage_never_goes_backwards_through_the_chain():
    # drive 30 s at a time until completed, sampling stage_of; index in STAGES never decreases;
    # first sample in ("SPREJETO", "NA POTI"); last == "NA CILJU"
    # then handover entry -> "PREDAJA PACIENTA"; free entry -> "PROST"
def test_partial_vitals_keep_other_metrics_and_show_age():  # Review Focus 3
    # vitals {hr:80, spo2:95}, then {spo2:91}; drive 6 minutes
    assert v["hr"]["value"] == 80 and v["spo2"]["value"] == 91 and abs(v["hr"]["age_min"] - 6.0) < 0.6
def test_implausible_vital_kept_and_flagged():
    assert v["spo2"]["value"] == 140 and v["spo2"]["needs_check"] is True
def test_superseded_entry_not_shown():  # Review Focus 5: correction replaces the value on the card
def test_er_actions_fill_the_card():
    assert card["acknowledged"] and card["bay"] == "A-3" and card["teams_activated"] == ["stroke"]
def test_cards_sorted_by_eta_then_arrived_last():  # two ER trips: sooner eta_dropoff first; a completed trip after all pending; an unassigned trip last among pending
def test_board_is_json_serialisable(): json.dumps(board(w))
def test_snapshot_extra_never_raises():  # patch projection.board to raise
    assert "error" in snapshot_extra(w)["clinical"]
def test_snapshot_extra_empty_when_disabled(): os.environ["CLINICAL_ENABLED"] = "0"; assert snapshot_extra(w) == {}  # restore env in finally
```
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement `projection.py`.
- [ ] **Step 4:** Re-run. Expected: PASS.
- [ ] **Step 5:** `git add app/clinical/projection.py tests/test_clinical_projection.py && git commit -m "clinical: ER cases, stage chain and board projection"`

---

### Task 6: HTTP routes

**Files:** Create `app/clinical/api.py`; Test `tests/test_clinical_api.py` (builds its own `FastAPI()` and calls `mount(app, {"sim": w})`; does **not** need the seam).

**Interfaces:**
- Consumes: `record_entry`, `confirm_entry`, `case_trip`, `ClinicalError`, `board`, `build_case`, `get_log`, `EntryIn`, `ERActionContent`.
- Produces `api.py`: `mount(app: FastAPI, worlds: dict[str, WorldState]) -> None` (returns without adding routes when `not enabled()`). Routes under `/{world}` (`world` a path parameter validated against the `worlds` keys): `POST /clinical/entries` (body `EntryIn`; 201 new, 200 duplicate; returns the stored entry), `POST /clinical/entries/{seq}/confirm` (body `{unit, source="crew_tap"}`), `GET /clinical/entries?since_seq=0&case_id=&limit=500` (`since_seq >= 0`, `1 <= limit <= 2000`), `GET /er/board` (returns `board(state)`), `GET /er/cases/{case_id}` (returns `{"case": card, "timeline": [entries]}`; 404 if the trip is not an ER case), `POST /er/cases/{case_id}/actions` (body `{action, bay=None, team=None, note=None, client_entry_id=None}`; records an `er_action` entry with source `er_reception`, unit `er`, state `confirmed`). `ClinicalError` becomes `HTTPException(status, message)`.

- [ ] **Step 1: Write the failing tests** (`TestClient`):

```python
def test_post_entry_201_then_duplicate_200():  # Review Focus 4
    r1 = c.post("/sim/clinical/entries", json=p); r2 = c.post(..., json=p)
    assert (r1.status_code, r2.status_code) == (201, 200) and r1.json()["seq"] == r2.json()["seq"]
def test_wrong_vehicle_409_unknown_trip_404_bad_body_422():
    # naive observed_t over HTTP -> 422, never 500 (Review Focus 2)
def test_since_seq_catch_up_and_validation():
    assert [e["seq"] for e in c.get("/sim/clinical/entries?since_seq=1").json()] == [2]
    assert c.get("/sim/clinical/entries?since_seq=-1").status_code == 422
def test_board_endpoint_equals_projection(): assert c.get("/sim/er/board").json() == json.loads(json.dumps(board(w)))
def test_case_detail_has_timeline_and_non_er_trip_404():  # timeline lists the posted entries in seq order; a trip with dropoff "onko" -> 404
def test_actions_endpoint_records_er_action():
    r = c.post(f"/sim/er/cases/{t.id}/actions", json={"action": "bay_assigned", "bay": "A-3"})
    assert r.json()["type"] == "er_action" and r.json()["source"] == "er_reception" and r.json()["unit"] == "er"
    # bay_assigned without bay -> 422
def test_confirm_endpoint(): ...  # 200 with state "confirmed"; second confirm 409
def test_unknown_world_rejected(): assert c.get("/nope/er/board").status_code in (404, 422)
def test_disabled_mounts_nothing():
    os.environ["CLINICAL_ENABLED"] = "0"; app = FastAPI(); n = len(app.routes); mount(app, {}); assert len(app.routes) == n  # restore env
```
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement `api.py`.
- [ ] **Step 4:** Re-run. Expected: PASS.
- [ ] **Step 5:** `git add app/clinical/api.py tests/test_clinical_api.py && git commit -m "clinical: crew entry and ER board routes"`

---

### Task 7: The seam (the only edit to shared files)

**Files:** Modify `app/state.py` (`reset_simulation`, `snapshot`), `app/main.py` (imports, after `app.include_router(router)`); Test `tests/test_clinical_integration.py`.

**Interfaces:** Consumes `ClinicalLog`, `snapshot_extra`, `api.mount`. Produces nothing new.

- [ ] **Step 1: Write the failing tests** (uses the real `main.app`, `main.sim`, `TestClient`, `seed_world(W, config.RANDOM_SEED, scheduled_day=False)` as `live()` in `test_live_calls.py`):

```python
EXPECTED_KEYS = {"world", "hypothetical", "speedup", "version", "sim_time", "real_time", "mode", "calls", "places",
                 "vehicles", "trips", "incidents", "weather", "traffic", "roads", "sources", "alerts", "kpis",
                 "events", "agent"}
def test_snapshot_keeps_every_existing_key_and_adds_clinical():
    s = W.snapshot(); assert set(s) == EXPECTED_KEYS | {"clinical"}; json.dumps(s)
def test_state_endpoint_carries_clinical(): assert "clinical" in client.get("/sim/state").json()
def test_failure_in_clinical_never_breaks_state():
    # monkeypatch app.clinical.projection.board to raise
    r = client.get("/sim/state"); assert r.status_code == 200 and "error" in r.json()["clinical"]
def test_kill_switch_removes_the_section():
    os.environ["CLINICAL_ENABLED"] = "0"; assert "clinical" not in W.snapshot()  # restore env in finally
def test_world_reset_clears_the_log_and_idempotency():  # Review Focus 4
    # post an entry with client_entry_id "x"; POST /sim/admin/reset; GET entries == [];
    # the same payload posts again with 201 and seq == 1
def test_three_views_are_identical_after_mixed_writes():
    # entry via POST, a confirm, an action, a correction
    assert client.get("/sim/er/board").json() == client.get("/sim/state").json()["clinical"] == json.loads(json.dumps(W.snapshot()["clinical"]))
def test_entry_bumps_version_so_the_stream_pushes_it(): v = W.version; post; assert W.version > v
def test_live_and_sim_logs_are_independent():  # an entry posted to /sim/... is absent from GET /live/clinical/entries and from the live board
```
- [ ] **Step 2:** Run `tests/test_clinical_integration.py`. Expected: FAIL.
- [ ] **Step 3:** Seam edits, nothing else: in `reset_simulation` add `from .clinical.store import ClinicalLog  # local import: avoids a cycle` and `self.clinical = ClinicalLog()`; in `snapshot()` add `from .clinical.projection import snapshot_extra` beside the existing local imports and `**snapshot_extra(self),` as the last item of the returned dict; in `main.py` add `from .clinical import api as clinical_api` with the other imports and `clinical_api.mount(app, WORLDS)` directly after `app.include_router(router)`.
- [ ] **Step 4:** Run the new file, then the whole suite: `.venv/Scripts/python.exe -m pytest tests -q`. Expected: new tests PASS; every pre-existing test file gives exactly the counts saved in `baseline.txt`.
- [ ] **Step 5:** Two commits, seam first: `git add app/state.py app/main.py && git commit -m "seam: clinical section in the snapshot and clinical routes (additive, CLINICAL_ENABLED=0 disables)"`, then `git add tests/test_clinical_integration.py && git commit -m "clinical: integration tests (snapshot compatibility, fail-safe, kill switch, sync)"`. Verify `git show --stat HEAD~1` lists only `state.py` and `main.py` with a handful of added lines.

---

### Task 8: Crew simulator

**Files:** Create `tools/crew_sim.py`; Test `tests/test_clinical_crew_sim.py`.

**Interfaces:**
- Consumes the public API only (`GET /{world}/state`, `POST /{world}/clinical/entries`).
- Produces `crew_sim.py`: `plan_entries(snapshot: dict, sent: set[str]) -> list[dict]` (each item `{"path": "/clinical/entries", "json": {...}}`, deterministic, each `client_entry_id` unique and recorded in `sent` by the caller); `run_once(get: Callable[[str], dict], post: Callable[[str, dict], None], sent: set[str]) -> int` (returns how many entries it posted); `main()` (argparse `--base`, `--world`, `--interval`, uses `httpx.Client`). Behaviour per ER-bound patient trip with a vehicle, seeded by `random.Random(trip_id)`: dispatcher `triage` (unit `dispatch`, source `dispatcher`, state `confirmed`, problem type from a keyword table over the trip note); once onboard, `patient_info`, a `severity`, `vitals` every 5 world-minutes (`client_entry_id` `sim-<trip>-vitals-<n>`), one `drug_administered` for emergencies, a `stroke_onset` event for stroke notes, and for one in six emergencies an `arrest` then `rosc`; after arrival, `handover` two world-minutes later, then `free`. All crew entries use unit `trip.vehicle_id`, source `simulated_crew`, state `heard`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_plan_is_deterministic_and_every_payload_validates():
    a = plan_entries(snap, set()); b = plan_entries(snap, set())
    assert a == b and all(ENTRY_IN.validate_python(i["json"]) for i in a)
def test_already_sent_entries_are_not_planned_again():  # feed every planned client_entry_id back in `sent` -> plan_entries returns []
def test_end_to_end_through_the_real_api():
    # TestClient(main.app) as get/post; seed world; er_trip; run_once while driving the world
    # until arrival + 10 minutes; board card has vitals with age_min, stage "PROST", treatments non-empty
    # and every call returned 2xx
def test_simulator_posts_nothing_for_equipment_or_non_er_trips():  # snapshot with an equipment trip and a dropoff "onko" trip -> plan_entries == []
```
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement `tools/crew_sim.py`.
- [ ] **Step 4:** Re-run. Expected: PASS.
- [ ] **Step 5:** `git add tools/crew_sim.py tests/test_clinical_crew_sim.py && git commit -m "clinical: crew simulator that posts through the public API"`

---

### Task 9: Handover timer, alerts and suggested actions (spec phase 2)

**Files:** Create `app/clinical/alerts.py`; Modify `app/clinical/projection.py` (fill the three placeholder card keys and the board `alerts`); Test `tests/test_clinical_alerts.py`.

**Interfaces:**
- Consumes: cards from `build_case`, `config`.
- Produces `alerts.py`: `handover_timer(state, arrived_at: datetime | None, handover_entry) -> dict | None` → `{"started_at", "due_at", "minutes_left", "overdue", "done_at"}` (`minutes_left` is `None` once `done_at` is set); `compute_alerts(state, cards: list[dict]) -> list[dict]` → items `{"id": "er:<case_id>:<rule>", "rule", "severity": "critical"|"high"|"medium"|"low", "case_id", "vehicle_id", "message", "since"}` sorted by severity then id; `suggested_actions(card: dict) -> list[dict]` → items `{"action", "team"?, "reason"}`.
- Rules: `arrest` critical (event `arrest` or `resuscitation_started`); `rosc`, `airway`, `stemi`, `transfusion` high (event kinds); `stroke_window` high (`stroke_onset` with minutes since `onset_t` below `STROKE_WINDOW_MIN`, message gives minutes left); `vitals_out_of_limits` high (any latest vital outside `VITAL_LIMITS` and not `needs_check`); `arriving_unacknowledged` medium (stage before `NA CILJU`, `minutes_to_arrival <= ARRIVING_UNACKED_MIN`, not acknowledged); `handover_overdue` high (arrived, no handover, more than `HANDOVER_LIMIT_MIN` since arrival); `no_vitals` low (red level, stage `PRI PACIENTU` or `S KRAJA`, and more than `NO_VITALS_RED_MIN` since the latest vitals, or since `trip.eta_pickup` when none). Suggestions: acknowledge when not acknowledged and not yet arrived; `bay_assigned` when no bay; `team_activated` for the team from `SUGGESTED_TEAM_BY_PROBLEM[problem.type]`, plus `resuscitation_room` for arrest, `heart` for stemi, `stroke` for stroke onset, each only if not already in `teams_activated`. Nothing here ever records an entry: the ER decides.

- [ ] **Step 1: Write the failing tests:**

```python
def test_arrest_event_raises_critical_alert_with_stable_id():
    assert a["id"] == f"er:{t.id}:arrest" and a["severity"] == "critical"
def test_stroke_window_counts_down_and_closes():  # onset 60 min ago -> minutes left ~210; onset 300 min ago -> no alert
def test_vitals_limits_alert_but_implausible_value_does_not():  # spo2 85 -> alert; spo2 140 -> needs_check, no alert
def test_arriving_unacknowledged_clears_after_acknowledge():  # eta 8 min -> alert "arriving_unacknowledged"; after an acknowledge er_action it is gone; eta 12 min -> no alert
def test_handover_timer_runs_15_minutes_then_overdue_then_stops_on_handover():
    # at arrival: minutes_left ~15, overdue False; +16 min: overdue True and alert handover_overdue;
    # handover entry: done_at set, minutes_left None, alert gone
def test_no_vitals_alert_for_red_case_only():  # onboard red case, 11 min since pickup, no vitals -> "no_vitals" low; same case with a yellow triage entry -> no alert
def test_suggested_team_disappears_once_activated():
    # stroke note + triage problem "stroke" -> suggestion team "stroke"; after team_activated stroke -> gone
def test_alert_ids_listed_on_cards_and_board_alerts_sorted():  # card["alert_ids"] equals the ids of board alerts for that case; board alerts ordered critical, high, medium, low
def test_alerts_never_write_to_the_log(): n = len(get_log(w)); board(w); assert len(get_log(w)) == n
```
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement `alerts.py`; in `projection.py` set each card's `handover`, `suggested_actions` and `alert_ids`, and the board's `alerts`.
- [ ] **Step 4:** Re-run this file, then `tests/test_clinical_projection.py` and `tests/test_clinical_integration.py`. Expected: PASS.
- [ ] **Step 5:** `git add app/clinical/alerts.py app/clinical/projection.py tests/test_clinical_alerts.py && git commit -m "clinical: handover timer, alerts and suggested actions"`

---

### Task 10: Final verification (no new code)

- [ ] **Step 1:** Full suite: `.venv/Scripts/python.exe -m pytest tests -q`. Expected: every pre-existing test file matches `baseline.txt` exactly; all `test_clinical_*` pass.
- [ ] **Step 2: Diff guard.** Use the three-dot form, which compares against the merge base so a moving `main` cannot cause false alarms: `git diff --stat origin/main...HEAD` must list only: `backend/app/state.py`, `backend/app/main.py`, files under `backend/app/clinical/`, `backend/tools/`, `backend/tests/clinical_helpers.py`, `backend/tests/test_clinical_*.py`, and `docs/superpowers/`. Anything else means stop and investigate.
- [ ] **Step 3:** `git diff origin/main...HEAD -- backend/app/state.py backend/app/main.py` shows only added lines (no deletions), at most about ten.
- [ ] **Step 4: Live check.** Start `.venv/Scripts/python.exe -m app` in `backend/` with `CALLS_PER_HOUR=30`; in a second shell run `python tools/crew_sim.py --world sim`; then `curl -s http://localhost:8000/sim/er/board` shows cards with vitals and stages, and `curl -s -N --max-time 4 http://localhost:8000/sim/stream` shows a first event whose JSON contains the same `clinical` section. Stop both processes.
- [ ] **Step 5: Kill switch live.** Restart with `CLINICAL_ENABLED=0`: `/sim/state` has no `clinical` key and `/sim/er/board` returns 404.
- [ ] **Step 6:** Report results honestly (counts, anything skipped). Nothing is pushed.
