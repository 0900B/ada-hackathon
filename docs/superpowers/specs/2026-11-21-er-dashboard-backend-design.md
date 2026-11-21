# ER reception dashboard: backend design

Branch `metelko-erdashboard`, cut from `origin/main` at `2af1e48` on 2026-11-21. Worktree: `C:\Users\telki\ada-hackathon-erdashboard`. Status: **draft, waiting for approval. No code written yet.**

Builds on the user's [AGENTIC_DISPATCH_DESIGN.md](../../AGENTIC_DISPATCH_DESIGN.md) (section 7: one append-only event log, three views) and on what `main`'s backend does today. All patient data is synthetic.

**Tags:** **[M]** read in `main`'s code; **[U]** decided by the user in this conversation; **[C]** my call, change it if you disagree; **[A]** assumption to confirm; **[?]** not known.

---

## 1. Intent

ER reception staff need to see, before an ambulance arrives, what happened, what the crew has done and how the patient is, so the ER can prepare. The same facts must show on the **ER**, **dispatch** and **paramedic (crew)** screens at the same moment **[U]**. Reception must understand the screen and the steps without training. The same mechanism must later extend from reception to activating other ER teams **[U]**.

## 2. Goals, non-goals, anti-goals

**Goals**
1. A **clinical log** per world: append-only entries about a case (vitals, drugs, procedures, severity, key events, triage level, ER actions). Corrections are new entries.
2. A **crew API** that appends entries. Crew input is the real source of clinical data **[U: option B]**.
3. A **read model**: one card per inbound patient with ETA, level, problem, latest vitals *with their age*, treatments, stage in the Slovenian status chain, alerts and what the ER has done.
4. **Alerts** from the log (arrest, stroke window, STEMI, vitals past limits, handover over 15 min). They suggest; the ER decides.
5. **Reception actions** (acknowledge, assign bay, activate a named team), stored in the same log.
6. **Sync by construction**: the read model is part of the existing snapshot and stream that dispatch and the tablet already read.
7. A **crew-simulator script** that posts through the public API, for testing and the demo.

**Non-goals (for now):** an ER board UI (the frontend is the teammates' lane; a thin page can follow); changes to the tablet; Slovenian voice parsing of clinical phrases (phase 3); monitor integration; IS NMP import; real hospital capacity; login and roles; a database (memory only, mirrored into the existing audit log).

**Anti-goals (a failure even if it "works")**
- Two screens ever disagreeing about a patient.
- A vital sign shown without how old it is.
- Any value silently corrected or guessed (a dose, a number). Implausible values are kept and flagged "check this".
- Any change in what `/state`, `/stream` or the existing tests do today.
- The system acting on the ER's behalf. Suggestions only.

## 3. Constraints

- State lives in memory, one replica **[M]**. Two worlds, `live` and `sim` **[M]**.
- Teammates own `backend/app/*` outside my new package. I may edit **only** `state.py` and `main.py`, additively, on my branch **[U]**. Merging into `main` needs their agreement.
- Nothing is pushed, and `main` is never touched, until you say so **[U]**.
- Coding stops Sunday 2026-11-22 11:00 (site says 12:00). It is Saturday evening: about 14 hours.
- Python 3.12 target **[M]**. No new runtime dependencies [C].

## 4. What `main` gives me, and what it lacks **[M]**

- `/{world}/stream` sends a full snapshot whenever `state.version` changes (checked every 1 s); the simulation loop bumps it every 2 s. Writers call `state.bump()`.
- Every patient trip has `dropoff_id`, `status`, `vehicle_id`, `eta_dropoff`, `priority` (emergency, urgent, scheduled), a pseudonymous `patient` label and a free-text `note`. Nearly all drop-offs are `ukc`, and H1's base is `ukc`.
- When a vehicle reaches the drop-off, the simulator sets the trip `completed` at once and sends the vehicle home. **There is no handover phase in the engine**, so handover must live in my log.
- Missing: any clinical field, any red or yellow level, any vitals, bay, handover timer or ER concept. The audit log is a 2,000-entry ring buffer with a generic shape.

## 5. Approaches considered

| Question | Chosen | Rejected, and why |
|---|---|---|
| Where the code lives | **New package `backend/app/clinical/` plus a two-file seam** in `state.py` and `main.py` **[U]** | A separate service with its own `/er/stream`: no edits to teammates, but dispatch and the tablet only see clinical data if they switch streams, so sync becomes their job |
| Where the log is stored | **Dedicated `ClinicalLog` on `WorldState`** [C] | Reuse the audit log: ring buffer drops entries, shape is generic. Extend `EventRecord`: operator events with before/after KPIs, and `models.py` is teammates' |
| How cases appear | **Derived from trips each time** (stateless projection) [C] | Hook trip creation in the engine: edits the engine. Derivation needs no hook |
| Crew data in the demo | **A client script that calls the real API** **[U: B]** | A server-side generator: would bypass the contract |

## 6. Design

### 6.1 Layout

```
backend/app/clinical/
  models.py      entry types, case view, alert (pydantic, validated)
  store.py       ClinicalLog: append, idempotency, by-case index, since(seq)
  projection.py  cases from trips + log -> board payload; status-chain mapping
  alerts.py      rule table -> alerts (derived, never stored)
  api.py         FastAPI router
  config.py      ER place ids, thresholds, action types, level mapping (tables, not code)
backend/tools/crew_sim.py   test client, never imported by the server
backend/tests/test_clinical_*.py
```

### 6.2 The seam (the only edits outside new files)

1. `state.py`, in `reset_simulation`: `self.clinical = ClinicalLog()`. A world reset clears the log.
2. `state.py`, in `snapshot()`: add key `"clinical": clinical_section(self)`. The function **never raises**: on any error it logs and returns `{"error": "..."}`, so `/state` and `/stream` keep working.
3. `main.py`: import the router and `app.include_router(...)`.

Kill switch [C]: `CLINICAL_ENABLED=0` leaves the snapshot without the key and mounts no routes: exactly today's behaviour. The seam goes in **its own commit** so teammates can see it and `git revert` it. No existing key, model, event, simulator or engine behaviour changes.

### 6.3 Clinical log entry

`seq` (per world, increasing), `entry_id`, optional `client_entry_id` (a retry with the same id returns the original, so tablets can resend safely), `case_id` (the trip id), `t` (world time) and `recorded_at` (real time), `unit` (vehicle id, `dispatch` or `er`), `source` (`crew_voice`, `crew_tap`, `monitor`, `dispatcher`, `er_reception`, `system`, `simulated_crew`), `type`, `content` (validated per type), `verbatim`, `confidence`, `state` (`heard`, `inferred`, `confirmed`), `supersedes`, `needs_check`.

Types in v1: `triage` (red or yellow, problem type), `patient_info` (age, sex), `vitals`, `drug_administered`, `procedure`, `severity` (blue, green, orange, red, arrest), `event` (arrest, ROSC, resuscitation started, airway, stroke onset time, STEMI, transfusion), `handover`, `free`, `note`, `er_action`.

Time [C]: the server stamps `t` with the world's current time. A client may send `observed_t` (for example vitals taken two minutes ago, sent late on a weak connection); the server accepts it only if it is not in the future and not before the case began, and keeps both times. Card ages use `observed_t`.

Rules: a crew entry must come from the vehicle on that case's trip, otherwise 409. A correction or confirmation is a new entry with `supersedes`. Field names follow the Ministry data set where I can match them; the mapping table is filled in when I have read that data set **[?]**.

### 6.4 Read model

One **case** per patient trip whose drop-off is an ER place (`ukc` for now, configurable), `kind == "patient"`, still open or finished within the snapshot's 3-hour window **[M]**. Equipment and discharges (drop-off elsewhere) are excluded.

- **Level:** a `triage` entry if present; otherwise a *default marked inferred*: emergency means red, urgent means yellow, scheduled means "scheduled arrival". The mapping is a table, because the national scheme is under revision **[M, per AGENTIC_DISPATCH_DESIGN.md]**.
- **Stage** from the 2017 rulebook chain (`SPREJETO`, `NA POTI`, `NA KRAJU`, `PRI PACIENTU`, `S KRAJA`, `NA CILJU`, `PREDAJA PACIENTA`, `PROST`), derived: trip assigned = accepted; en route to pickup = on the way; waiting at or loading at pickup = at the scene or with the patient; onboard and moving = left the scene; trip completed = at the destination; a `handover` entry = handed over; a `free` entry = free. The first five are inferred from the vehicle state, which cannot tell "at the scene" from "with the patient" exactly; the card says so [A].
- **Card:** ETA, level and whether it is inferred, problem flags, age and sex, latest vitals each with age in minutes, treatments, on-scene severity, stage, alerts, ER actions, bay, handover timer (15 minutes from arrival, the legal maximum [S per OPERATIONS_DETAILS.md]).
- **Snapshot section** `clinical`: `{seq, cases: [cards], alerts, entries_tail (last 50)}`. Full timelines are fetched per case, to keep the stream light.

### 6.5 Alerts and actions

Derived from the log on every read, with stable ids (`er:<case>:<rule>`) so clients can diff. Rules are a table: arrest or resuscitation started (critical); ROSC, airway procedure, STEMI, transfusion, stroke window open (high); vitals past limits (high); arriving within 10 minutes and not acknowledged (medium); handover over 15 minutes (high); no vitals for N minutes on a red case (low). **Vitals limits and the stroke window are placeholders [A]; ER staff must set them.** I do not extend the teammates' `Alert` model; ER alerts live in the `clinical` section.

Reception actions are `er_action` entries from a table: `acknowledge`, `bay_assigned`, `team_activated` (stroke, heart, trauma, resuscitation room). Each case lists `suggested_actions` from its problem flags; **performing one is a reception decision**. Adding a team type later is adding a table row.

### 6.6 API (all under `/{world}`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/clinical/entries` | Append an entry (crew, dispatcher, reception, simulator). Idempotent on `client_entry_id` |
| POST | `/clinical/entries/{seq}/confirm` | Append a confirmation of an entry |
| GET | `/clinical/entries?since_seq=N&case_id=` | Catch-up after a dropped connection |
| GET | `/er/board` | The same payload as `snapshot()["clinical"]` |
| GET | `/er/cases/{case_id}` | Full timeline of one case |
| POST | `/er/cases/{case_id}/actions` | Reception action |

### 6.7 Why the three screens cannot disagree

One store on `WorldState`. Every write path ends in `state.bump()`. `/er/board`, `/er/cases/...` and the snapshot section all call **the same projection function**, never a second implementation. Dispatch and the tablet read `/stream`, which now carries the section. A test asserts the three outputs are equal after a mixed sequence of writes.

### 6.8 Crew simulator

`backend/tools/crew_sim.py` reads `/state`, follows each ER-bound trip and posts realistic entries (triage, patient info, vitals every few minutes, a drug, a severity change, handover) through the public API as `simulated_crew`. It is a client, so the contract is exercised exactly as a real tablet would.

## 7. Verification (what "not broken" means)

1. **Baseline first:** the five existing test files pass on a clean `origin/main` build in a local virtualenv, with the result recorded; they pass unchanged after my work.
2. **Snapshot compatibility:** the set of existing top-level keys and their types is identical; only `clinical` is new.
3. **Fail-safe:** with the projection forced to raise, `/state` and `/stream` still answer.
4. **Kill switch:** with `CLINICAL_ENABLED=0` the snapshot has no `clinical` key and the routes are absent.
5. **Diff guard:** `git diff --stat origin/main` touches only `state.py`, `main.py` and new files under the listed paths.
6. New tests for: append, idempotent retry, supersede, wrong-vehicle 409, stage mapping through a driven simulation, alerts, handover timer, reset clears the log, and the three-way sync equality.

## 8. Phases (cut from the bottom if time slips)

1. **Log, API, projection, seam, tests, simulator** (about 5 hours). Board data is real and in the stream.
2. **Alerts, reception actions, handover timer, suggested actions.**
3. Slovenian clinical phrases through the existing message parser; a thin ER board page if the teammates' lane allows.

## 9. Left to the builder

Exact pydantic field names and ranges; the Ministry field-name mapping; where `entries_tail` is trimmed; test fixture shapes; the thresholds table values (as labelled placeholders).

## 10. Open questions

- Which hospitals count as "ER places": only `ukc` now **[C]**.
- Who builds the ER board UI and the paramedic's clinical entry screen: the contract above is what they would read and write **[?]**.
- Clinical limits and the stroke window: need an ER clinician **[?]**.
- Whether the teammates accept the two-file seam before it merges into `main` **[?]**.
