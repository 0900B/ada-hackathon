# ER dashboard: API contract for the frontend

Branch `metelko-erdashboard`. For whoever builds the ER reception UI. Derived from the code in `backend/app/clinical/` (`projection.py`, `alerts.py`, `api.py`, `models.py`, `config.py`, `service.py`) and read from nothing else; where the code does not settle a point it says **to confirm**. Design background: [2026-11-21-er-dashboard-backend-design.md](2026-11-21-er-dashboard-backend-design.md). All patient data is synthetic. The examples below come from a real offline run (an in-memory world named `sim`, filled through the real routes); only whitespace was condensed.

Placeholders: `{world}` is `live` or `sim`. Every path below is under `/{world}`. Use the world in the path explicitly: the legacy unprefixed `/state` and `/stream` are mapped to `sim` by `main.py`, but `/er/...` and `/clinical/...` are not, so unprefixed ER paths 404.

---

## 1. Overview: two ways to read the same thing

The ER read model is one function, `board(state)`. It is derived on every read from the world's trips and the append-only clinical log; nothing is cached, so two readers cannot disagree.

| How | Use it for |
|---|---|
| `GET /{world}/er/board` | the board alone (poll it, or fetch once on load) |
| `snapshot()["clinical"]` inside `GET /{world}/state` and in every frame of the SSE stream `GET /{world}/stream` | when the UI already reads the shared snapshot (dispatch screen, tablet): `clinical` is the same object as the board |

The stream sends the **whole** snapshot (so the whole board), not deltas, whenever the world's `version` changes (checked every second; every write bumps it, and the simulation loop bumps it about every 2 s). A client simply replaces its board with each frame.

Other routes (sections 6 and 7): `GET /{world}/er/cases/{case_id}` (one card, its timeline and its alerts), `GET /{world}/clinical/entries` (catch-up read of the log), and the three write routes.

## 2. The board object

```json
{
  "world": "sim",
  "as_of": "2026-11-22T03:27:19+00:00",
  "seq": 10,
  "cases": [ { "...": "one card per case, see section 3" } ],
  "alerts": [ { "...": "section 5" } ],
  "entries_tail": [ { "...": "the 50 newest log entries, section 6" } ]
}
```

| Key | Type | Meaning |
|---|---|---|
| `world` | string | the world's name (`live` or `sim`) |
| `as_of` | ISO time | the **world** clock when the board was built (ages and countdowns are relative to it) |
| `seq` | int | `seq` of the newest log entry in this world; `0` for an empty log. Only ever grows, unless the world is reset (section 7) |
| `cases` | array of cards | patient trips that end at the ER place (`ukc`) and are not cancelled, and are still open or finished within the last 3 world hours. Order: cases still to arrive first, soonest ETA first (no ETA, such as unassigned, last); then arrived cases, most recent arrival first |
| `alerts` | array | every alert of every case, most urgent first (critical, high, medium, low), then by `id` |
| `entries_tail` | array of entries | the newest 50 entries of the whole world (all cases, superseded ones included), oldest first |

## 3. The card (one case)

Keys never change shape: a card always has exactly these 23 keys; "empty" is `null`, `[]` or `{}` as listed.

| Key | Type | Null / empty when |
|---|---|---|
| `case_id` | string | never. The trip id, e.g. `TR-001` |
| `vehicle_id` | string \| null | no vehicle assigned yet (unassigned trip) |
| `patient_label` | string | never. A pseudonymous label (the trip's `patient`, else the trip id) |
| `priority` | `"emergency"` \| `"urgent"` \| `"scheduled"` | never. The trip's dispatch priority |
| `level` | `{value, inferred, source}` | never. `value`: `"red"` \| `"yellow"` from a triage entry, or inferred from `priority` (`emergency` red, `urgent` yellow, `scheduled` `"scheduled"`). `inferred`: true when no triage entry exists. `source`: the triage entry's source (e.g. `"dispatcher"`), `null` when inferred |
| `problem` | `{type, note}` | `type` is `null` when there is no triage entry; `"other"` when triage exists but names no problem; else one of `chest_pain stemi stroke breathing_difficulty severe_head_injury resuscitation polytrauma sepsis poisoning other`. `note` is the call's free text (`null` if none) |
| `age_years` | int \| null | no `patient_info` entry with an age |
| `sex` | `"f"` \| `"m"` \| `"unknown"` \| null | no `patient_info` entry with a sex |
| `eta_dropoff` | ISO time \| null | no ETA yet (unassigned). For an arrived case it equals `arrived_at` |
| `minutes_to_arrival` | number \| null | arrived, or no ETA. Otherwise minutes (world) to the ETA, never negative, one decimal |
| `arrived_at` | ISO time \| null | the engine has not marked the trip completed. The engine marks it the moment the unit reaches the ER |
| `stage` | string \| null | `null` for a trip with no vehicle yet. Else one of the 8 stages (section 4) |
| `stage_inferred` | bool | `true` for the stages the system only guesses from vehicle state (section 4) |
| `severity` | string \| null | no `severity` entry yet. A **bare string**: `blue green orange red arrest` (the on-scene severity, not `priority`, not `level`) |
| `vitals` | object | `{}` until a vitals entry exists. Key = metric (`hr sbp dbp spo2 rr gcs temp_c glucose_mmol`), only metrics reported so far, each `{value, age_min, state, needs_check, seq}` (see below) |
| `treatments` | array | `[]`. Drugs and procedures, oldest first: `{seq, type, content, observed_t, state, needs_check}`; `type` is `drug_administered` (`content`: `drug dose route`) or `procedure` (`content`: `name`) |
| `events` | array | `[]`. Key events, oldest first: `{kind, observed_t, onset_t, state}`; `kind` is `arrest resuscitation_started rosc airway stroke_onset stemi transfusion`; `onset_t` is non-null only for `stroke_onset` |
| `acknowledged` | bool | false until reception records `acknowledge` |
| `bay` | string \| null | no `bay_assigned` yet; the latest one wins |
| `teams_activated` | array of string | `[]`. Teams (`stroke heart trauma resuscitation_room`) in the order first activated, no duplicates |
| `handover` | object \| null | `null` until the trip is marked arrived (section 5) |
| `suggested_actions` | array | `[]` (section 5). Suggestions only, never recorded |
| `alert_ids` | array of string | `[]`. The ids of this case's alerts, in the board's alert order |

`vitals[m]`: `value` is a number exactly as entered (never corrected, even when implausible); `age_min` is how old the reading is in **world** minutes, one decimal (a vital sign must always be shown with its age); `state` is `heard`, `inferred` or `confirmed`; `needs_check` is true when **this metric's** value lies outside its physically possible range (so the UI should show "check this", and it is never used as an alarm value); `seq` is the log entry the value came from. A later partial entry replaces only the metrics it carries.

A card is built from the entries that are not superseded; a superseded entry still shows in the timeline and the entries API.

### Example: an onboard stroke patient (real run)

```json
{
  "case_id": "TR-001",
  "vehicle_id": "A1",
  "patient_label": "P-100",
  "priority": "emergency",
  "level": {"value": "red", "inferred": false, "source": "dispatcher"},
  "problem": {"type": "stroke", "note": "suspected stroke"},
  "age_years": 72,
  "sex": "f",
  "eta_dropoff": "2026-11-22T03:36:01.243159+00:00",
  "minutes_to_arrival": 8.7,
  "arrived_at": null,
  "stage": "PRI PACIENTU",
  "stage_inferred": true,
  "severity": "orange",
  "vitals": {
    "hr": {"value": 96.0, "age_min": 0.0, "state": "confirmed", "needs_check": false, "seq": 4},
    "sbp": {"value": 168.0, "age_min": 0.0, "state": "confirmed", "needs_check": false, "seq": 4},
    "dbp": {"value": 92.0, "age_min": 0.0, "state": "confirmed", "needs_check": false, "seq": 4},
    "spo2": {"value": 85.0, "age_min": 0.0, "state": "confirmed", "needs_check": false, "seq": 4},
    "gcs": {"value": 14.0, "age_min": 0.0, "state": "confirmed", "needs_check": false, "seq": 4},
    "temp_c": {"value": 50.0, "age_min": 0.0, "state": "heard", "needs_check": true, "seq": 5}
  },
  "treatments": [
    {
      "seq": 6,
      "type": "drug_administered",
      "content": {"drug": "Sodium chloride 0.9%", "dose": "500 ml", "route": "IV"},
      "observed_t": "2026-11-22T03:27:19+00:00",
      "state": "heard",
      "needs_check": false
    }
  ],
  "events": [
    {
      "kind": "stroke_onset",
      "observed_t": "2026-11-22T03:27:19+00:00",
      "onset_t": "2026-11-22T02:42:19+00:00",
      "state": "heard"
    }
  ],
  "acknowledged": true,
  "bay": "R2",
  "teams_activated": ["stroke"],
  "handover": null,
  "suggested_actions": [],
  "alert_ids": ["er:TR-001:stroke_window", "er:TR-001:vitals_out_of_limits"]
}
```

Here `temp_c` 50 is kept as entered and flagged (`needs_check: true`) while the other metrics of the same reading are not.

### Example: a case with nothing recorded yet (real run)

```json
{
  "case_id": "TR-001", "vehicle_id": "A1", "patient_label": "P-100", "priority": "emergency",
  "level": {"value": "red", "inferred": true, "source": null},
  "problem": {"type": null, "note": "suspected stroke"},
  "age_years": null, "sex": null,
  "eta_dropoff": "2026-11-22T03:35:59.152581+00:00", "minutes_to_arrival": 20.0, "arrived_at": null,
  "stage": "SPREJETO", "stage_inferred": false,
  "severity": null, "vitals": {}, "treatments": [], "events": [],
  "acknowledged": false, "bay": null, "teams_activated": [],
  "handover": null,
  "suggested_actions": [
    {"action": "acknowledge", "reason": "The patient is on the way and reception has not acknowledged the case"},
    {"action": "bay_assigned", "reason": "No bay is assigned yet"}
  ],
  "alert_ids": []
}
```

## 4. The stage chain

`stage` follows the Slovenian status chain, in this order (the code only uses the Slovenian names; the English glosses are ours, **to confirm**):

| # | `stage` | Gloss | How the card gets there | `stage_inferred` |
|---|---|---|---|---|
| 1 | `SPREJETO` | accepted | trip assigned to a vehicle | false |
| 2 | `NA POTI` | on the way to the patient | trip en route to pickup, vehicle not waiting | **true** |
| 3 | `NA KRAJU` | at the scene | en route to pickup and the vehicle is waiting | **true** |
| 4 | `PRI PACIENTU` | with the patient | patient on board and the vehicle is `loading` | **true** |
| 5 | `S KRAJA` | leaving the scene, transporting | patient on board, any other vehicle state | **true** |
| 6 | `NA CILJU` | at the destination | the engine marked the trip completed (arrival) | false |
| 7 | `PREDAJA PACIENTA` | handover | a `handover` entry exists | false |
| 8 | `PROST` | unit free | a `free` entry exists | false |

Rules: `free` beats `handover` beats the trip state, so a `free` entry alone gives `PROST`. A superseded `handover`/`free` entry does not count. `stage` is `null` (and `stage_inferred` false) for a trip with no vehicle yet. The engine has no handover phase of its own, so stages 7 and 8 exist only through entries, and a `handover` or `free` entry can move the stage before the engine marks the trip completed (then `arrived_at` and `handover` stay `null`). Stages 2 to 5 are guesses from the vehicle's state: show them as such (`stage_inferred`).

## 5. Alerts, suggested actions, handover timer

Alerts, suggestions and the timer are **derived on every read** from the card and the world clock. Nothing is stored, nothing is written, an alert disappears as soon as its condition stops, and there is no "acknowledge alert" call. **A case in stage `PREDAJA PACIENTA` or `PROST` has no alerts and no suggested actions** (the patient is with the ER team), whatever was recorded before.

### Alert object

```json
{
  "id": "er:TR-001:vitals_out_of_limits",
  "rule": "vitals_out_of_limits",
  "severity": "high",
  "case_id": "TR-001",
  "vehicle_id": "A1",
  "message": "Vitals outside limits: spo2 85 (below 90)",
  "since": "2026-11-22T03:27:19+00:00"
}
```

`id` is `er:<case_id>:<rule>` and there is at most one alert per rule per case, so an id is **stable**: the same condition keeps the same id across reads, which lets a client diff two boards (new id = new alert, missing id = cleared). Do not compare `message` to decide it is "the same alert": messages carry live countdowns. `message` is English text built on the server; `severity` is a bare string; `since` is `null` for one rule. `vehicle_id` can be `null`.

| `rule` | `severity` | Raised when | `since` |
|---|---|---|---|
| `arrest` | critical | an `arrest` or `resuscitation_started` event | the earliest such event's `observed_t` |
| `rosc` | high | a `rosc` event | its `observed_t` |
| `airway` | high | an `airway` event | its `observed_t` |
| `stemi` | high | a `stemi` event | its `observed_t` |
| `transfusion` | high | a `transfusion` event | its `observed_t` |
| `stroke_window` | high | the latest `stroke_onset` is less than `STROKE_WINDOW_MIN` (270) world minutes old; message counts down the minutes left | the onset time (`onset_t`) |
| `vitals_out_of_limits` | high | the latest value of a metric is outside `VITAL_LIMITS`: spo2 < 90; sbp < 90 or > 180; hr < 40 or > 130; rr < 8 or > 30; gcs < 9 (limits inclusive). A value with `needs_check` true is never an alarm | the earliest breaching reading's time |
| `arriving_unacknowledged` | medium | stage is 1 to 5, ETA is at most `ARRIVING_UNACKED_MIN` (10) minutes away and reception has not acknowledged | `null` |
| `handover_overdue` | high | arrived, no `handover` or `free` entry, more than `HANDOVER_LIMIT_MIN` (15) minutes after arrival | the handover `due_at` |
| `no_vitals` | low | `level.value` is `red`, stage is `PRI PACIENTU` or `S KRAJA`, and more than `NO_VITALS_RED_MIN` (10) minutes since the latest reading of any metric (or since pickup if there is none) | that reference time |

**All thresholds except the 15-minute handover limit are PLACEHOLDERS** in `config.py` ("not clinical guidance; ER staff must set"): `ARRIVING_UNACKED_MIN`, `NO_VITALS_RED_MIN`, `STROKE_WINDOW_MIN` and `VITAL_LIMITS`. Do not present them to users as clinical rules. `STROKE_WINDOW_MIN` only drives the `stroke_window` alert; whether a stroke team is still worth calling later is a clinical decision for the ER. The config comment cites `OPERATIONS_DETAILS.md` as the source of the 15-minute handover limit; that file is not on this branch (**to confirm**).

### Suggested actions

`card.suggested_actions` is an array of `{action, reason}`, plus `team` when `action` is `team_activated`. They are suggestions: nothing records them and nothing acts on them. Performing one means calling the actions route (section 6).

| `action` | Suggested when |
|---|---|
| `acknowledge` | not acknowledged and the stage is before `NA CILJU` (including a null stage) |
| `bay_assigned` | `bay` is `null` |
| `team_activated` (`team`) | the team is not in `teams_activated` and is called for by the problem type (`stroke`->`stroke`, `stemi`->`heart`, `chest_pain`->`heart`, `polytrauma`->`trauma`, `severe_head_injury`->`trauma`, `resuscitation`->`resuscitation_room`) or by an event (`arrest` or `resuscitation_started`->`resuscitation_room`, `stemi`->`heart`, `stroke_onset`->`stroke`); `reason` joins the reasons with `; ` |

Order: `acknowledge`, `bay_assigned`, then teams. Empty after handover (see above).

### Handover timer (`card.handover`)

`null` until `arrived_at` is set, else:

```json
{"started_at": "2026-11-22T03:35:49+00:00", "due_at": "2026-11-22T03:50:49+00:00", "minutes_left": 10.0, "overdue": false, "done_at": null}
```

`started_at` is the arrival, `due_at` is 15 minutes later. While running: `minutes_left` is a number (never negative; `0.0` once past due) and `overdue` turns true after `due_at`. The clock stops when a `handover` entry exists, or else a `free` entry (a unit that reports itself free has finished the handover): then `done_at` is that entry's `observed_t`, `minutes_left` is `null` and `overdue` is false. Real run, same case: overdue (with its alert), then after a `handover` entry (alerts and suggestions are gone):

```json
{"minutes_left": 0.0, "overdue": true, "done_at": null}
{"id": "er:TR-001:handover_overdue", "rule": "handover_overdue", "severity": "high", "case_id": "TR-001", "vehicle_id": "A1",
 "message": "Handover overdue: 17 min since arrival (limit 15 min)", "since": "2026-11-22T03:50:49+00:00"}
{"stage": "PREDAJA PACIENTA", "handover": {"started_at": "2026-11-22T03:35:49+00:00", "due_at": "2026-11-22T03:50:49+00:00",
 "minutes_left": null, "overdue": false, "done_at": "2026-11-22T03:52:49+00:00"}, "alert_ids": [], "suggested_actions": []}
```

## 6. Writing and reading the log

No login. The server may set `ADMIN_KEY`, in which case every write needs the `X-Plan-B-Key` header (section 7, item 10). The backend allows any origin (CORS `*`, any header).

### `POST /{world}/clinical/entries`: record one entry (crew tablet, dispatcher, system)

Body: the envelope plus a `type` and its `content`.

| Field | Type | Notes |
|---|---|---|
| `case_id` | string, 1 to 64 | a patient trip id (the trip must exist and carry a patient; equipment transports are refused) |
| `unit` | string, 1 to 64 | who is speaking: for a crew source it must be the vehicle currently on the case |
| `source` | enum | `crew_voice crew_tap monitor dispatcher er_reception system simulated_crew` |
| `type` | enum | `triage patient_info vitals drug_administered procedure severity event handover free note er_action` |
| `content` | object | per type, below. An unknown key inside `content` is a 422 (never silently dropped). Unknown keys at the top level are ignored |
| `state` | `heard` \| `inferred` \| `confirmed` | default `heard`; a tap on "heard"/"inferred" becomes a confirmed copy via `.../confirm` |
| `observed_t` | ISO time **with an offset** | optional. Default and recommended: omit it, the server stamps the world's current time. Must not be in the future (world time) nor before the case began; a time with no offset is refused |
| `verbatim` | string, max 500 | the words as spoken or typed |
| `confidence` | number 0 to 1 | optional |
| `supersedes` | string, max 64 | an `entry_id` (e.g. `CE-00006`) on the **same case** that this entry replaces (a correction). A replaced entry stays in the log but leaves the card. Replacing an already replaced entry is a 409. A replacement may be of another `type` (nothing stops a note from retracting an event) |
| `client_entry_id` | string, max 64 | idempotency key, see below |

`content` per `type` (all values are checked for shape only; no value is clinically validated or corrected):

| `type` | `content` |
|---|---|
| `triage` | `{level: "red"\|"yellow", problem_type?: <problem type>}` (`problem_type` defaults to `"other"`; the card level `"scheduled"` is inferred only and cannot be sent) |
| `patient_info` | `{age_years?: int 0 to 120 \| null, sex?: "f"\|"m"\|"unknown"\|null}` |
| `vitals` | any of `hr sbp dbp spo2 rr gcs temp_c glucose_mmol` as finite numbers or `null`; at least one must be non-null |
| `drug_administered` | `{drug, dose, route}`, free text 1 to 200 chars each, never parsed |
| `procedure` | `{name}` 1 to 200 chars |
| `severity` | `{value: "blue"\|"green"\|"orange"\|"red"\|"arrest"}` |
| `event` | `{kind, onset_t?}`; `kind` is one of `arrest resuscitation_started rosc airway stroke_onset stemi transfusion`; `onset_t` (ISO with offset, not in the future) is **required** for `stroke_onset` and may be earlier than the call |
| `handover` | `{note}` 1 to 2000 chars |
| `free` | `{note}` 1 to 2000 chars |
| `note` | `{text}` 1 to 2000 chars |
| `er_action` | `{action, bay?, team?}` as in the actions route below; only accepted from `source: "er_reception"` (else 422), so the UI uses the actions route instead |

**Idempotency:** `client_entry_id` is unique per `unit`, not global. A second POST with the same `unit` and `client_entry_id` returns the **first** stored entry unchanged and writes nothing; the body is not compared. Status: **201** when stored, **200** when it was a replay. Without a `client_entry_id` every POST is a new entry.

Response (the stored entry; times in entries use a `Z` suffix, see section 7):

```json
{
  "seq": 1, "entry_id": "CE-00001", "case_id": "TR-001", "type": "triage",
  "content": {"level": "red", "problem_type": "stroke"},
  "unit": "dispatch", "source": "dispatcher", "state": "confirmed",
  "t": "2026-11-22T03:27:19Z", "observed_t": "2026-11-22T03:27:19Z", "recorded_at": "2026-11-22T03:15:49.584405Z",
  "verbatim": null, "confidence": null, "supersedes": null, "needs_check": false, "client_entry_id": "demo-triage"
}
```

Server-stamped, never taken from the client: `seq` (per world, starts at 1), `entry_id` (`CE-00001`...), `t` (world time recorded), `recorded_at` (**real** wall-clock time, not world time), `needs_check`. The stored entry's `needs_check` is true when **any** metric of a vitals entry is outside its plausible range (`hr` 0 to 300, `sbp` 0 to 300, `dbp` 0 to 200, `spo2` 0 to 100, `rr` 0 to 80, `gcs` 3 to 15, `temp_c` 25 to 45, `glucose_mmol` 0 to 60); it is always false for other types.

### `POST /{world}/clinical/entries/{seq}/confirm`: "heard" to "confirmed"

Body `{"unit": "<unit>", "source": "crew_tap"}` (`source` optional, default `crew_tap`; no other keys). It stores a **new** entry that copies entry `seq` with `state: "confirmed"` and `supersedes` set to the original, keeping the original `observed_t`. Always **200** with the new entry. It passes the same rules as a normal write (a crew `unit` must be the case's vehicle; a second confirm of the same entry is a 409 because it is already superseded). Not idempotent.

### `GET /{world}/clinical/entries?since_seq=0&case_id=&limit=500`: catch-up read

Returns a JSON array of entries with `seq` greater than `since_seq`, oldest first, at most `limit` (1 to 2000, default 500), optionally for one `case_id`. `since_seq` must be 0 or more (else 422).

### `GET /{world}/er/cases/{case_id}`: one case

```json
{"case": { "...": "the card, identical to its copy on the board" }, "timeline": [ "...entries of this case in seq order, superseded ones included" ], "alerts": [ "...this case's alerts, full objects" ]}
```

`alerts` sit next to the card, not inside it, and `[a.id for a in alerts] == case.alert_ids`. 404 when the trip is not on the ER board (unknown id, not bound for the ER, cancelled, or finished more than 3 world hours ago).

### `POST /{world}/er/cases/{case_id}/actions`: what reception does

Body:

| Field | Type | Notes |
|---|---|---|
| `action` | `"acknowledge"` \| `"bay_assigned"` \| `"team_activated"` | required |
| `bay` | string, 1 to 200 | required for `bay_assigned` |
| `team` | `"stroke"` \| `"heart"` \| `"trauma"` \| `"resuscitation_room"` | required for `team_activated`; any other team is a 422 |
| `note` | string, max 500 | optional, stored as the entry's `verbatim` |
| `client_entry_id` | string, max 64 | optional idempotency key (scoped to unit `er`) |

Unknown keys are a 422. The server records an `er_action` entry with `unit: "er"`, `source: "er_reception"`, `state: "confirmed"` and returns it (`content` is `{action, bay, team}` with the unused ones `null`). Codes: **201** stored, **200** replay of a `client_entry_id`, **404** unknown world or a case not on the ER board, **422** invalid body. Repeating `acknowledge` without a `client_entry_id` adds another entry (harmless: `acknowledged` stays true); the latest `bay_assigned` wins; each new team is added to `teams_activated`.

### Status codes

| Code | Meaning |
|---|---|
| 200 | replay of a known `client_entry_id`; every `confirm`; every read |
| 201 | a new entry was stored |
| 404 | unknown world, unknown `case_id` (also: not an ER case, for `/er/cases/...`), or unknown `seq` on confirm |
| 409 | a crew entry from a unit that is not the case's vehicle, or a case with no vehicle; or the entry to supersede was already superseded |
| 422 | invalid body or parameters; an equipment transport; `observed_t`/`onset_t` in the future or before the case began; `supersedes` that names no entry on this case; an `er_action` from a non-reception source |

A refused request changes nothing (no `seq` is taken). `detail` is **either a string** (rule refusals: 404, 409 and the service 422s) **or an array** of FastAPI/pydantic errors (`{type, loc, msg, input, ctx}`; body validation 422): handle both. A write to a case that is not on the ER board (for example a patient transport to another place) is accepted by `POST /clinical/entries` but never appears on the board.

## 7. Caveats for the UI

1. **Two `needs_check`.** `card.vitals[metric].needs_check` is **per metric**. A stored entry's `needs_check` (in `timeline`, `entries_tail` and the entries API) covers the **whole entry**: one implausible metric flags the entry, even if its other metrics are fine. Use the card's flag for display; use the entry's only for the raw log.
2. **`severity` is a bare string** (on the card and on alerts), not an object like `level`; it has no `state` or age.
3. **`level.inferred` matters.** `inferred: true` means no one has triaged the case; the colour comes from the dispatch priority. Show it differently from a recorded level. `stage_inferred` is the same idea for the stage.
4. **Times.** All times are UTC ISO strings with an offset; the UI must show Ljubljana local time (CET/CEST) itself. Cards, alerts and `as_of` spell UTC as `+00:00`; stored entries (`timeline`, `entries_tail`, the entries API) spell it `Z`. Parse them with a date parser; never compare them as strings. `observed_t` and `t` are **world** time, `recorded_at` is **real** time.
5. **Ages are in WORLD minutes.** `age_min`, `minutes_left`, `minutes_to_arrival` and the alert countdowns are world minutes. The `sim` world runs faster than real time (`speedup` in the snapshot, default 5x via `SIM_SPEEDUP`); the `live` world runs at 1x. So on `sim` a "10 minutes" label passes in about 2 real minutes. Use `board.as_of`, not the browser clock, to age anything.
6. **The `clinical` section can be `{"error": "..."}` for one poll.** `snapshot_extra` turns a projection failure into an error note so the shared snapshot never breaks (rare: the app's `GET /state` runs in a threadpool next to the event loop). Keep showing the last good board for one bad poll. The section is absent altogether when the feature is switched off (item 11).
7. **Alert ids are stable**: diff by `id` (section 5), do not diff by position or message.
8. **World reset.** `POST /{world}/admin/reset` re-seeds the world: trip ids restart at `TR-001` and the clinical log starts again, so `board.seq` drops. Since the rebase onto upstream `main` (2026-11-22) the shared snapshot (`/state` and every `/stream` frame) also carries a top-level `epoch` that goes up by one on every reset; `/er/board` does **not** repeat it. A client that reads the snapshot or stream should drop its state when `epoch` changes; a client that only polls the board uses this rule: if `board.seq` is lower than the `since_seq` you hold, discard your local state and refetch from `since_seq=0`. A reset that is followed by as many new entries before your next poll would not be seen by the `seq` rule alone.
9. **Cases leave the board.** A finished case stays for 3 world hours after arrival, then drops out of `cases`; its entries remain in the log and in `GET /clinical/entries`.
10. **Authentication.** Upstream's middleware `AdminKeyLock` (`backend/app/admin_key.py`, on this branch since the 2026-11-22 rebase) applies: when the environment variable `ADMIN_KEY` is set on the server, **every non-GET request** (all the POST routes here included) needs the header `X-Plan-B-Key: <key>`, otherwise the answer is **401** `{"detail": "Control actions need the admin key (Bypass demo lock)."}`. Reads (GET, the stream) never need it. `POST /lock/check` with the header answers `{"ok": true, "lock": <bool>}` (401 on a wrong key) and changes nothing: use it to validate a typed key. With `ADMIN_KEY` unset there is no lock. The UI must be able to send the header and show "view only" on a 401. The existing dashboard keeps the key in `localStorage` under `planb.adminKey`.
11. **Kill switch.** With `CLINICAL_ENABLED=0` on the server (read at startup), the `clinical` key is missing from the snapshot and none of the routes in this document exist (404). Treat both as "feature off".
12. **Sim and live.** `sim` is the demo world (hypothetical, 5x clock); `live` is the real-time world. Both have their own log, with their own `seq`. Poll or stream the world you show; never mix them.
13. **Demo data.** Nothing posts clinical data by itself. For a demo, run the crew simulator, which plays the dispatcher's triage and the crews through the public API: `python tools/crew_sim.py --base http://localhost:8000 --world sim` (from `backend/`; `--interval` seconds between polls, `--key` or `ADMIN_KEY` for a locked server). It posts triage when a vehicle is assigned; patient info, severity, vitals every 5 world minutes, a drug (emergencies), a stroke onset (stroke notes) and, for about one emergency in six, an arrest then ROSC once onboard; handover 10 minutes and free 15 minutes after arrival. It survives a world reset (it notices `seq` dropping and starts again).
