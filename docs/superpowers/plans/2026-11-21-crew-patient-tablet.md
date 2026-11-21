# Crew Patient Tablet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the crew view `/crew/:vehicleId` into a patient-compartment tablet screen: ETA to the ER, a voice and tap clinical log, vitals age, and the existing dispatch quick reports kept working.

**Architecture:** `CrewPage.tsx` becomes a thin composition of focused files in `frontend/src/crew/`. Pure logic (stage, ETA, the clinical log) lives in modules that import only types, so `node --test` runs them with no tooling. React pieces consume that logic. Clinical entries are saved in the browser and posted to the ER backend's `/{world}/clinical/entries` when that endpoint exists. The dispatch path is moved, not changed.

**Tech Stack:** React 19, TypeScript, Vite, lucide-react (all already in `frontend/`); `node:test` for logic tests; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-21-crew-patient-tablet-design.md` (read it first; this plan only records decisions the spec leaves open).

## Global Constraints

- Only files under `frontend/` change (plus this plan and the spec under `docs/superpowers/`), and in 0900B's lane only `frontend/src/pages/CrewPage.tsx` is edited (rewritten). Everything else is new files in `frontend/src/crew/` and `frontend/tests/crew/`. `backend/`, `voice.ts`, `voice.css`, `api.ts`, `doctor.ts`, `severity.ts`, `format.ts`, `hotkeys.ts`, `SeverityBadge.tsx`, `DoctorTag.tsx`, `tsconfig.json` and `package.json` are **not** edited.
- Route `/crew/:vehicleId?world=sim|live` and `sendFieldMessage(world, text, vehicleId)` keep working. Doctor cars (`vehicle.type === "doctor"`) keep their existing lines, produced by the existing `doctorJobLine`, `DoctorTag` and the doctor ETA block, copied verbatim, never re-derived.
- The log channel never calls `sendFieldMessage`. Spoken text is stored verbatim as a `note`; nothing is parsed or guessed. Structured entries (vitals, drug, procedure, event) come from tap pads only.
- A value outside its plausible range is kept and marked `needs_check`; never corrected. A vital is never shown without its age.
- Touch targets at least 64 px, body text at least 18 px, ETA at least 64 px on a tablet; one column at 700 px and below; must work at 390x844 (the demo phone). Dark slate tokens from `styles.css` `:root`; Lucide icons; no emoji; English labels; no new dependencies.
- Work on `Metelko` only; never push; never `git add -A` or `git add .` (untracked `reports/` and `research_notes/` must stay out); add explicit paths.
- Time comes from `state.sim_time` (the world's clock), never `Date.now()`, so the tablet matches the dispatcher screen; the simulation runs 5x.
- Logic modules in `frontend/src/crew/` that tests import (`crewLogic.ts`, `clinicalLog.ts`) may only `import type` from other files and must use erasable TypeScript only (no enums, namespaces or parameter properties).

## Review Focus

Each line is pinned by a test in the task named.

1. **Reload mid-case and corrupt storage:** entries survive a reload; broken or missing stored JSON gives an empty log, never a crash (Task 4).
2. **Backend missing, down or offline:** entries stay `pending`, are retried oldest first, and one that fails stops the queue without losing order; a rejected one (4xx other than 404) is marked `rejected`, not retried forever (Task 4).
3. **Double tap:** saving or confirming twice makes one entry (Task 4).
4. **The vehicle's trip changes mid-log:** entries are kept per trip; a new trip starts an empty timeline and never mixes patients (Task 4 and Task 5).
5. **Missing or invalid time:** an invalid `sim_time` or ETA shows a dash, never `NaN` or a negative age (Tasks 1 and 4).

## Working conventions (every task)

```bash
R=/c/Users/telki/ada-hackathon                       # shared checkout, branch Metelko
S=/c/Users/telki/AppData/Local/Temp/claude/91650a5436204d05/ae9bac42-3f67-42f0-b484-4b709fa689be/scratchpad/crewlook
# logic tests (run in the checkout, no install needed):
cd $R/frontend && node --test "tests/crew/*.test.ts"
# typecheck, build and look: the shared checkout has no node_modules, so mirror src into the scratch copy
rm -rf $S/frontend/src && cp -r $R/frontend/src $S/frontend/src
cd $S/frontend && npx tsc --noEmit && npx vite build     # expected: tsc prints nothing; vite prints "built in"
# the Vite dev server on http://localhost:5199 (scratch, started earlier) hot-reloads after the sync; if it is down:
#   cd $S/frontend && npx vite --port 5199 --strictPort
```

Before each browser check run `ListAgents` and `git branch --show-current` (must print `Metelko`). **Never post to the live backend while testing:** stub with Playwright (`browser_run_code_unsafe`: `page.route("**/sim/messages", ...)`, `page.route("**/clinical/**", ...)`); GETs to the real backend are fine. Speech is faked with `page.addInitScript` that defines `window.webkitSpeechRecognition` (read `frontend/src/voice.ts` for the event shape it expects). Commits are local to `Metelko`.

---

### Task 1: Baseline, and the stage and ETA logic

**Files:**
- Create: `frontend/src/crew/crewLogic.ts`
- Test: `frontend/tests/crew/crewLogic.test.ts`
- Also commit: the spec and this plan (both untracked now)

**Interfaces:**
- Produces:
```ts
export type CrewStage = "no_patient" | "to_patient" | "with_patient";
export function crewStage(v: Pick<Vehicle, "status" | "type">, trip: Pick<Trip, "kind"> | undefined): CrewStage;
export function minutesUntil(iso: string | null | undefined, nowIso: string): number | null; // whole minutes rounded up, never below 0, null if either time is missing or invalid
export interface ErEta { minutes: number | null; arriveAt: string | null; late: boolean; lateMin: number }
export function erEta(trip: Pick<Trip, "eta_dropoff" | "delay_min">, nowIso: string): ErEta; // late = delay_min >= 5, lateMin rounded
```

- [ ] **Step 1: Baseline.** `git fetch origin && git merge --ff-only origin/main` (if it is not a fast-forward, stop and tell the user). Sync the scratch copy, run the typecheck and build from Working conventions. Record both results (expected: both pass).
- [ ] **Step 2: Write the failing tests** in `crewLogic.test.ts`: `crewStage` returns `"to_patient"` for a patient trip with vehicle status `to_pickup`; `"with_patient"` for `loading` and `with_patient`; `"no_patient"` for no trip, for an equipment trip with status `with_patient`, and for `idle`; a doctor car (`type: "doctor"`) with a patient trip and status `loading` gives `"with_patient"`. `minutesUntil("...T23:40:00Z", "...T23:28:40Z")` is `12`; a past time is `0`; `null` and `"garbage"` give `null` (Review Focus 5). `erEta` with `delay_min: 7.4` gives `late: true, lateMin: 7`; with `2` gives `late: false`; with `eta_dropoff: null` gives `minutes: null, arriveAt: null`.
- [ ] **Step 3: Run to verify they fail:** `node --test tests/crew/crewLogic.test.ts`. Expected: FAIL, module not found.
- [ ] **Step 4: Implement** `crewLogic.ts` with the signatures above (type-only imports from `../api`).
- [ ] **Step 5: Run to verify they pass.** Expected: all pass.
- [ ] **Step 6: Commit:** `git add docs/superpowers/specs/2026-11-21-crew-patient-tablet-design.md docs/superpowers/plans/2026-11-21-crew-patient-tablet.md frontend/src/crew/crewLogic.ts frontend/tests/crew/crewLogic.test.ts && git commit -m "crew: stage and ER ETA logic, design and plan"`.

---

### Task 2: Move the dispatch code out of `CrewPage.tsx` (no visible change)

**Files:**
- Create: `frontend/src/crew/useDispatch.ts`, `frontend/src/crew/DispatchPanel.tsx`
- Modify: `frontend/src/pages/CrewPage.tsx` (use them; markup and classes unchanged)

**Interfaces:**
- Produces:
```ts
export const QUICK: { key: string; icon: LucideIcon; sl: string; en: string }[];   // moved verbatim
export function useDispatch(state: WorldSnapshot, vehicle: Vehicle, world: World): {
  busy: boolean; sent: string | null; result: MessageResult | null; error: string | null; direct: string | null;
  run: AgentRun | undefined; send: (raw: string, quickKey?: string) => Promise<boolean>;
};
export function DispatchPanel(props: { dispatch: ReturnType<typeof useDispatch>; draft: string; setDraft: (s: string) => void }): JSX.Element; // quick buttons, text form, response card, MessageOutcome
```

- [ ] **Step 1:** Move `QUICK`, `pointAhead`, `directReport`, `RUN_STATUS`, `MessageOutcome` and the `send` logic with its `busyRef`, `result`, `error`, `direct` and `run` derivation into the two new files, byte for byte apart from the wrapping. `CrewPage.tsx` keeps its own `useSpeechInput` and `usePushToTalk` for now and calls `dispatch.send`.
- [ ] **Step 2: Verify nothing changed.** `tsc --noEmit` passes. In the browser (stubbed `**/sim/messages` returning `{understood_sl:"Vozilo je obstalo.",understood_en:"Vehicle broke down",needs_clarification:null,events:[],applied:[],run_id:null}`), open `/crew/A3?world=sim`, press quick button 1, and check the intercepted request body is exactly `{"text":"Vozilo je obstalo.","sender_vehicle_id":"A3","apply":true}` and the card shows the SL and EN lines. Compare a screenshot with `crew-A3-phone-full.png` in the scratch folder: the same blocks in the same order (live values such as times differ).
- [ ] **Step 3: Commit:** `git add frontend/src/crew/useDispatch.ts frontend/src/crew/DispatchPanel.tsx frontend/src/pages/CrewPage.tsx && git commit -m "crew: move dispatch send logic into a hook and panel"`.

---

### Task 3: New layout, ETA panel, stages

**Files:**
- Create: `frontend/src/crew/EtaPanel.tsx`, `frontend/src/crew/crew.css`, `frontend/src/crew/useWakeLock.ts`
- Modify: `frontend/src/pages/CrewPage.tsx` (rewrite the composition; keep `VehiclePicker` and `nextStop`; import `crew.css`; all new class names start with `pt-`)

**Interfaces:**
- Consumes: Task 1 `crewStage`, `erEta`; Task 2 `useDispatch`, `DispatchPanel`.
- Produces:
```ts
export function EtaPanel(props: { state: WorldSnapshot; vehicle: Vehicle; trip: Trip | undefined; stage: CrewStage }): JSX.Element;
export function useWakeLock(): void;   // requests navigator.wakeLock "screen" while mounted, re-requests on visibilitychange, never throws
```

- [ ] **Step 1: Build the layout.** Header strip: callsign and name, patient label and needs, `SeverityBadge`, `DoctorTag`, an Online/Reconnecting chip. `EtaPanel`: stage `with_patient`: hospital name (`dropoff_id` place), minutes in 64 px or larger, arrival time, a late marker (`+N min late`); stage `to_patient`: "Patient in N min" and "then ER <name>"; vehicle type `doctor`: the existing doctor job line and doctor ETA block copied verbatim from `origin/main`'s `CrewPage.tsx`; `no_patient`: vehicle status and the existing `nextStop` line. A grid: two columns from 900 px, one column at 700 px and below, in this order on a phone: ETA, log area (placeholder text "Log: next task"), `DispatchPanel`, footer (Switch vehicle, Dispatcher dashboard, world tag SIM/LIVE). Hide the `<kbd>` badges under `(hover: none)`. Call `useWakeLock()` in the console.
- [ ] **Step 2: Typecheck and sync** (Working conventions).
- [ ] **Step 3: Check at three sizes** (1280x800, 1024x768, 390x844) for `/crew/A3?world=sim` (patient on board), `/crew/T2?world=sim` (idle), an equipment vehicle (a vehicle whose trip has `kind: "equipment"`, find one in `/sim/state`), and a doctor car if the live sim has one (`D1`). With `browser_evaluate` assert: `document.documentElement.scrollWidth <= innerWidth` at every size; at the two tablet sizes `scrollHeight <= innerHeight` for the with-patient view; every `button` under `.pt` has `getBoundingClientRect().height >= 64` on tablet sizes (list violators); computed `font-size` of the ETA minutes is `>= 64px` on tablet. If the sim has no doctor car, check the doctor block with `git diff` against `origin/main`: those lines are unchanged. Look at each screenshot.
- [ ] **Step 4: Commit:** `git add frontend/src/crew/EtaPanel.tsx frontend/src/crew/crew.css frontend/src/crew/useWakeLock.ts frontend/src/pages/CrewPage.tsx && git commit -m "crew: patient-tablet layout with ETA to the ER"`.

---

### Task 4: The clinical log (pure logic)

**Files:**
- Create: `frontend/src/crew/clinicalLog.ts`
- Test: `frontend/tests/crew/clinicalLog.test.ts`

**Interfaces:**
- Produces:
```ts
export type EntryType = "vitals" | "drug_administered" | "procedure" | "event" | "note" | "handover";
export type EntryState = "heard" | "confirmed";
export type SyncState = "pending" | "sent" | "rejected";
export interface ClinicalEntry {
  client_entry_id: string; case_id: string; unit: string;
  t: string;                       // world time when logged (state.sim_time)
  observed_t: string | null;       // when it happened, if different (e.g. stroke onset)
  recorded_at: string;             // real clock, ISO
  source: "crew_voice" | "crew_tap"; type: EntryType;
  content: Record<string, string | number | boolean>;
  verbatim: string; state: EntryState; needs_check: boolean;
  supersedes: string | null; sync: SyncState;
}
// placeholder tables, labelled as needing an EMS clinician (spec section 9)
export const VITAL_LIMITS: Record<"sbp"|"dbp"|"spo2"|"hr"|"rr"|"temp"|"glucose"|"gcs", { min: number; max: number }>;
export const VITALS_DUE_MIN: Record<"critical"|"serious"|"urgent"|"routine", number>; // 5, 10, 15, 15
export const DRUGS: string[]; export const ROUTES: string[]; export const UNITS: string[]; export const EVENTS: { key: string; label: string }[];
export function makeEntry(i: { case_id: string; unit: string; t: string; source: ClinicalEntry["source"]; type: EntryType; content: ClinicalEntry["content"]; verbatim?: string; observed_t?: string | null }, d: { id: string; recordedAt: string }): ClinicalEntry; // tap = confirmed, voice = heard; sets needs_check
export function appendEntry(log: readonly ClinicalEntry[], e: ClinicalEntry): ClinicalEntry[];   // idempotent on client_entry_id; drops an identical entry (same case, type, content, verbatim, source) recorded within 2000 ms
export function confirmEntry(log: readonly ClinicalEntry[], id: string, d: { id: string; recordedAt: string }): ClinicalEntry[]; // appends a copy with supersedes=id, same t, state confirmed; no-op if already confirmed or unknown
export function discardEntry(log: readonly ClinicalEntry[], id: string, d: { id: string; recordedAt: string }): ClinicalEntry[]; // appends a note {discarded:true} superseding id
export function visibleEntries(log: readonly ClinicalEntry[]): ClinicalEntry[];  // newest t first; hides superseded entries and discard markers
export function latestOf(log: readonly ClinicalEntry[], type: EntryType): ClinicalEntry | undefined;
export function ageMinutes(e: Pick<ClinicalEntry, "t" | "observed_t">, nowIso: string): number | null; // floor, never negative, null if invalid
export function vitalsStatus(log: readonly ClinicalEntry[], nowIso: string, level: keyof typeof VITALS_DUE_MIN): { ageMin: number | null; overdue: boolean };
export function entryLabel(e: ClinicalEntry): string;      // "BP 120/80 · SpO2 92 · HR 96", "Morphine 5 mg i.v.", the event label, or the verbatim text
export function isConfirmPhrase(text: string): boolean;    // "potrjeno" or "confirmed", ignoring case, spaces and punctuation
export const storageKey: (world: string, caseId: string) => string;
export function parseLog(json: string | null): ClinicalEntry[];                       // invalid input gives []
export function syncPending(log: readonly ClinicalEntry[], post: (e: ClinicalEntry) => Promise<SyncState>): Promise<ClinicalEntry[]>;
```

- [ ] **Step 1: Write the failing tests** in `clinicalLog.test.ts`: `makeEntry` for a tap is `confirmed`, for voice is `heard`; a vitals entry with `spo2: 920` has `needs_check: true` and keeps `920` (nothing corrected), `spo2: 92` has `needs_check: false`; `appendEntry` with the same `client_entry_id` twice gives length 1, and an identical entry within 2000 ms gives length 1 but 2500 ms later gives 2 (Review Focus 3); `confirmEntry` twice on one id gives one confirmation, keeps `t`, and `visibleEntries` then shows only the confirmed copy; `discardEntry` hides the entry and the marker; `visibleEntries` orders by `t` descending; `ageMinutes` is `6` for 6 min 40 s, `0` when `t` is in the future, and `null` for `"garbage"` or an invalid `nowIso` (Review Focus 5), and uses `observed_t` when set; `vitalsStatus` with no vitals gives `{ageMin: null, overdue: true}` for critical, with vitals 4 min old and level critical gives `overdue: false`, 6 min gives `true`; `entryLabel` for a note is its verbatim text; `isConfirmPhrase` true for `"Potrjeno."` and `" confirmed "`, false for `"potrjeno morfin"`; `storageKey("sim","TR-001")`, `storageKey("sim","TR-002")` and `storageKey("live","TR-001")` are three different strings (Review Focus 4); `parseLog(null)`, `parseLog("{")` and `parseLog('{"a":1}')` all give `[]`, and a `JSON.stringify` round trip of a log returns it equal (Review Focus 1); `syncPending` with a `post` that returns `"sent"` marks all `sent`, one that returns `"pending"` for the second entry leaves the second and third `pending` and never calls `post` for the third (Review Focus 2), and one that returns `"rejected"` marks it `rejected` and continues to the next.
- [ ] **Step 2: Run to verify they fail:** `node --test tests/crew/clinicalLog.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement** `clinicalLog.ts` per the interfaces. The tables hold labelled placeholders: vitals limits sbp 40 to 260, dbp 20 to 160, spo2 50 to 100, hr 20 to 250, rr 4 to 60, temp 30 to 43, glucose 1 to 40, gcs 3 to 15; routes `i.v.`, `i.o.`, `i.m.`, `s.c.`, `p.o.`, `inhaled`, `s.l.`; units `mg`, `mcg`, `ml`, `g`, `IU`; events as `key`: label pairs `cardiac_arrest`: Cardiac arrest, `rosc`: ROSC, `cpr_started`: CPR started, `defibrillation`: Defibrillation, `airway_secured`: Airway secured, `stroke_onset`: Stroke onset, `stemi`: STEMI, `transfusion_started`: Transfusion started, `patient_worse`: Patient worse. Entry `content` keys are fixed for all later tasks: vitals use the `VITAL_LIMITS` keys (`sbp`, `dbp`, `spo2`, `hr`, `rr`, `temp`, `glucose`, `gcs`); a drug uses `drug`, `dose`, `unit`, `route`; an event uses `key` and `label`; a spoken or typed note has none (the text is in `verbatim`).
- [ ] **Step 4: Run to verify they pass.**
- [ ] **Step 5: Commit:** `git add frontend/src/crew/clinicalLog.ts frontend/tests/crew/clinicalLog.test.ts && git commit -m "crew: clinical log logic with tests"`.

---

### Task 5: Voice log slice (speak, see it, keep it, send it)

**Files:**
- Create: `frontend/src/crew/useVoiceChannels.ts`, `frontend/src/crew/useClinicalLog.ts`, `frontend/src/crew/clinicalApi.ts`, `frontend/src/crew/Timeline.tsx`
- Modify: `frontend/src/pages/CrewPage.tsx` (replace its speech wiring; fill the log area), `frontend/src/crew/crew.css`

**Interfaces:**
- Consumes: Task 4 module; Task 2 `useDispatch`.
- Produces:
```ts
export function useVoiceChannels(h: { onLog: (text: string) => void; onDispatch: (text: string) => void }): {
  speech: SpeechInput; channel: "log" | "dispatch" | null;   // the channel of the session now listening
  logMic: ReturnType<typeof usePushToTalk>; dispatchMic: ReturnType<typeof usePushToTalk>;   // each sets the channel, then delegates
};
export async function postClinicalEntry(world: World, e: ClinicalEntry): Promise<SyncState>;   // POST `${API_URL}/${world}/clinical/entries` with the entry minus `sync`; ok gives "sent"; 404, 5xx or a network error gives "pending"; any other 4xx gives "rejected"
export function useClinicalLog(world: World, caseId: string | null, unit: string, simTime: string): {
  entries: ClinicalEntry[];         // visibleEntries
  add: (type: EntryType, content: ClinicalEntry["content"], o?: { source?: "crew_voice" | "crew_tap"; verbatim?: string; observed_t?: string | null }) => void;
  addSpoken: (text: string) => "confirmed" | "added" | "nothing_to_confirm";   // isConfirmPhrase confirms the latest heard note instead of adding one
  confirm: (id: string) => void; discard: (id: string) => void;
  pending: number;
};   // loads and saves localStorage under storageKey; retries pending entries every 15 s and on the window "online" event via syncPending
export function Timeline(props: { entries: ClinicalEntry[]; nowIso: string; onConfirm: (id: string) => void; onDiscard: (id: string) => void }): JSX.Element;
```

- [ ] **Step 1: Implement** the four files and wire `CrewPage.tsx`: the "Hold to log" button uses `logMic`; the dispatch voice button and quick buttons use `dispatchMic` and `dispatch.send`; hotkey `m` toggles the log channel; a typed-note input (source `crew_tap`, state confirmed) sits under the timeline for browsers without speech; logging is disabled with the text "No patient on board" unless the stage is `with_patient` or the vehicle is loading. `Timeline` rows show time (`fmtTime`), `entryLabel`, a state tag (`heard`, `confirmed`, `check this`), a sync mark (pending or sent), and Confirm and Discard buttons on `heard` rows. When a spoken line is exactly a confirm phrase with nothing to confirm, show "Nothing to confirm" and add nothing. `caseId` is the current trip id (`null` disables logging).
- [ ] **Step 2: Typecheck and sync.**
- [ ] **Step 3: Check in the browser** with the fake recognizer and stubs (`**/clinical/**` fulfilling 404, `**/sim/messages` recording any call): on `/crew/A3?world=sim` say "bolnik je nezavesten": a `heard` row appears with that exact text and **no request to `/messages` is made** (anti-goal); tap Confirm: one row, `confirmed`; say "potrjeno" with nothing to confirm: "Nothing to confirm", no new row; reload the page: both rows are still there, the sync mark says pending (404 stub); change the stub to 200 and wait 15 s: the mark becomes sent; press the dispatch quick button 1: a request to `/messages` is made (and none for log speech). Tap Discard on a row: it disappears from the timeline. Look at screenshots at 1280x800 and 390x844.
- [ ] **Step 4: Commit:** `git add frontend/src/crew/useVoiceChannels.ts frontend/src/crew/useClinicalLog.ts frontend/src/crew/clinicalApi.ts frontend/src/crew/Timeline.tsx frontend/src/crew/crew.css frontend/src/pages/CrewPage.tsx && git commit -m "crew: voice log with timeline, local storage and sync queue"`.

---

### Task 6: Tap pads and the vitals panel

**Files:**
- Create: `frontend/src/crew/NumberPad.tsx`, `frontend/src/crew/DrugPad.tsx`, `frontend/src/crew/VitalsPad.tsx`, `frontend/src/crew/EventPad.tsx`, `frontend/src/crew/VitalsPanel.tsx`
- Modify: `frontend/src/pages/CrewPage.tsx`, `frontend/src/crew/crew.css`

**Interfaces:**
- Consumes: Task 4 tables and `vitalsStatus`, `latestOf`; Task 5 `useClinicalLog().add`.
- Produces:
```ts
export function NumberPad(props: { value: string; onChange: (v: string) => void; allowDecimal?: boolean }): JSX.Element;       // 0-9, ".", backspace, 72 px keys
export function DrugPad(props: { onSave: (c: { drug: string; dose: number; unit: string; route: string }) => void; onClose: () => void }): JSX.Element;   // drug chips from DRUGS plus "Other" (free text), NumberPad for the dose, unit and route chips, a Save button disabled until all four are set
export function VitalsPad(props: { onSave: (c: Record<string, number>) => void; onClose: () => void }): JSX.Element;   // one field at a time: sbp, dbp, spo2, hr, rr, temp, glucose, gcs; every field optional; Save needs at least one
export function EventPad(props: { onSave: (key: string, label: string, minutesAgo: number) => void; onClose: () => void }): JSX.Element;   // EVENTS as big buttons; "stroke onset" asks for minutes ago (0, 5, 10, 15, 30, 60)
export function VitalsPanel(props: { entries: ClinicalEntry[]; nowIso: string; level: "critical"|"serious"|"urgent"|"routine"; onEnter: () => void }): JSX.Element;   // latest vitals, "Last vitals N min ago" (amber when overdue), "No vitals yet" when none
```

- [ ] **Step 1: Implement** the components and the buttons Drug, Vitals, Event in the bottom bar of `CrewPage.tsx` (pads open as full-width sheets; Save adds a `crew_tap` entry and closes; saving appends one entry whatever the tap speed). `observed_t` for stroke onset is `simTime` minus `minutesAgo`. The level for `VitalsPanel` is `levelOf(trip)` from `severity.ts`.
- [ ] **Step 2: Typecheck and sync.**
- [ ] **Step 3: Check in the browser:** enter a drug (Morphine, 5, mg, i.v.): a confirmed row "Morphine 5 mg i.v." appears; enter vitals with spo2 `920`: the row shows `check this` and still reads `920`; "No vitals yet" shows before any vitals and "Last vitals 0 min ago" after; double-tap Save quickly: one row; stroke onset with 15 min ago: row shows the event and its age is 15 (check `ageMinutes`). At 1280x800 every pad button is at least 64 px high and the sheet needs no scrolling.
- [ ] **Step 4: Commit:** `git add frontend/src/crew/NumberPad.tsx frontend/src/crew/DrugPad.tsx frontend/src/crew/VitalsPad.tsx frontend/src/crew/EventPad.tsx frontend/src/crew/VitalsPanel.tsx frontend/src/crew/crew.css frontend/src/pages/CrewPage.tsx && git commit -m "crew: tap pads for drugs, vitals and events, vitals age"`.

---

### Task 7: Timers and the ER echo (if time allows)

**Files:**
- Modify: `frontend/src/crew/clinicalLog.ts`, `frontend/src/crew/crewLogic.ts`, `frontend/src/pages/CrewPage.tsx`, `frontend/src/crew/crew.css`
- Create: `frontend/src/crew/TimersPanel.tsx`
- Test: `frontend/tests/crew/clinicalLog.test.ts`, `frontend/tests/crew/crewLogic.test.ts` (add cases)

**Interfaces:**
- Produces:
```ts
export function timers(log: readonly ClinicalEntry[], nowIso: string): { lastDrugMin: number | null; cprMin: number | null; strokeOnsetMin: number | null };   // clinicalLog.ts; cprMin is minutes since "CPR started" unless a later ROSC; strokeOnsetMin uses observed_t
export function erEcho(clinical: unknown, caseId: string): string[];   // crewLogic.ts; reads the ER backend's draft section `{cases: [{case_id, bay?, er_actions?: [{type, label?}]}]}` defensively; anything else gives []
export function TimersPanel(props: { entries: ClinicalEntry[]; nowIso: string; echo: string[] }): JSX.Element;
```

- [ ] **Step 1: Write the failing tests:** `timers` with a drug 4 min ago gives `lastDrugMin: 4`; CPR started 12 min ago with no ROSC gives `cprMin: 12`, with a later ROSC gives `null`; none gives all `null`. `erEcho` with `{cases:[{case_id:"TR-002",bay:"3",er_actions:[{type:"acknowledge"}]}]}` for `"TR-002"` gives `["ER acknowledged","Bay 3"]` (labels `acknowledge` becomes "ER acknowledged"; `bay_assigned`, `team_activated` with `label` become "Bay N", the label); `undefined`, `{}`, `null`, a different case, or a malformed `cases` all give `[]`.
- [ ] **Step 2: Run to verify they fail.** Expected: FAIL.
- [ ] **Step 3: Implement** the three pieces and show `TimersPanel` in the right column of the logging view, passing `erEcho((state as unknown as { clinical?: unknown }).clinical, trip.id)`.
- [ ] **Step 4: Run to verify they pass,** then typecheck and sync. In the browser a vehicle without a `clinical` section shows no ER line (current live backend) and no error in the console.
- [ ] **Step 5: Commit:** `git add frontend/src/crew/clinicalLog.ts frontend/src/crew/crewLogic.ts frontend/src/crew/TimersPanel.tsx frontend/tests/crew frontend/src/pages/CrewPage.tsx frontend/src/crew/crew.css && git commit -m "crew: elapsed timers and ER echo"`.

---

### Task 8: Handover screen (if time allows)

**Files:**
- Create: `frontend/src/crew/HandoverScreen.tsx`
- Modify: `frontend/src/crew/clinicalLog.ts`, `frontend/src/crew/crewLogic.ts`, `frontend/src/pages/CrewPage.tsx`, `frontend/src/crew/crew.css`
- Test: `frontend/tests/crew/clinicalLog.test.ts`, `frontend/tests/crew/crewLogic.test.ts` (add cases)

**Interfaces:**
- Produces:
```ts
export function handoverLines(log: readonly ClinicalEntry[]): string[];   // clinicalLog.ts: visible confirmed and heard entries, oldest first, "HH:MM label"; entries needing a check end with " (check)"
export function handoverPending(lastCase: string | null, currentCase: string | null, handedOver: boolean): boolean;   // crewLogic.ts: true when a case was being logged, the vehicle's trip is no longer that case, and it was not handed over
export function HandoverScreen(props: { lines: string[]; sinceIso: string; nowIso: string; onDone: () => void }): JSX.Element;   // the lines, a 15:00 countdown from sinceIso (red under 3 min, "over" after 0), a Handover done button
```

- [ ] **Step 1: Write the failing tests:** `handoverLines` is oldest first and marks a `needs_check` entry; `handoverPending("TR-002", null, false)` is `true`, `("TR-002","TR-002",false)` is `false`, `("TR-002","TR-009",false)` is `true`, `("TR-002",null,true)` is `false`, `(null,null,false)` is `false`.
- [ ] **Step 2: Run to verify they fail.** Expected: FAIL.
- [ ] **Step 3: Implement.** `CrewPage.tsx` remembers `lastCase` and its start time in `localStorage` (key `crew-last:{world}:{vehicleId}`); while `handoverPending` is true it shows `HandoverScreen` instead of the idle screen; `onDone` appends a `handover` entry and clears `lastCase`.
- [ ] **Step 4: Run to verify they pass,** typecheck and sync. In the browser, simulate a completed trip by setting `localStorage` `crew-last:sim:A3` to a case that is not current: the handover screen shows with its lines and countdown; Handover done returns to the normal screen and survives a reload.
- [ ] **Step 5: Commit:** `git add frontend/src/crew/HandoverScreen.tsx frontend/src/crew/clinicalLog.ts frontend/src/crew/crewLogic.ts frontend/tests/crew frontend/src/pages/CrewPage.tsx frontend/src/crew/crew.css && git commit -m "crew: handover screen with 15 minute timer"`.

---

### Task 9: Final checks

**Files:** none new; the spec's status line is updated.

- [ ] **Step 1:** `git fetch origin && git merge origin/main` (a normal merge if main moved; resolve conflicts in `CrewPage.tsx` by keeping this plan's structure and porting 0900B's new lines into it, and tell the user what was ported).
- [ ] **Step 2:** Run all logic tests, the typecheck and the build from Working conventions. Expected: all pass.
- [ ] **Step 3: The demo flow.** On `/crew/T1?world=sim` at 390x844 with `**/sim/messages` stubbed: hold the dispatch mic (fake recognizer saying "Vozilo je obstalo. Oprema je še v njem."), the request body has that text and `sender_vehicle_id: "T1"`, and the response card shows. Also check quick buttons 1 to 5 and the `1` to `5` hotkeys on desktop.
- [ ] **Step 4: Screenshots** at 1280x800, 1024x768 and 390x844 for a vehicle with a patient, an idle one, an equipment trip and a doctor car if present; read them against the spec's layout and the Global Constraints.
- [ ] **Step 5:** Edit the spec's status line to "implemented" and list what was cut. Commit: `git add docs/superpowers/specs/2026-11-21-crew-patient-tablet-design.md && git commit -m "docs: crew tablet design status"`. Do not push; report to the user what is done, what was cut, and that pushing and getting it onto `main` is their decision with 0900B.
