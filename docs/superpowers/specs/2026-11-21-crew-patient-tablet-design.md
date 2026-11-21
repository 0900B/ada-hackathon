# Crew view redesign: the patient-compartment tablet

Branch `Metelko` (in line with `main` at `b7eeac9`, 2026-11-21 23:05). Status: **draft, user decisions applied at 23:15 (no clinical parser, see 4.4). Waiting for a final yes.** No code written yet.

Tags: **[U]** decided by the user in this conversation; **[C]** my call, change it if you disagree; **[M]** read in the code; **[A]** assumption to confirm.

---

## 1. Intent

Today `/crew/:vehicleId` is a phone screen: a header card, a hold-to-talk button, a text box and five quick buttons that send a message to the dispatcher. It is made for a person who can look at it and tap precisely.

The new screen is for the **paramedic in the back of the ambulance, with a patient, gloves on and hands busy [U]**. It runs on a **tablet in the patient compartment [U]**. Its main job is to let that person **speak, or tap once, what is happening** (vitals, drugs given, procedures, events) so it becomes the clinical record for the documents and the ER dashboard **[U]**, and to show **the ETA to the ER [U]**. The cab tablet (`/vehicle/:id`, navigation for the driver) stays as it is **[A]**.

## 2. Goals, non-goals, anti-goals

**Goals (user cut: 1-4 and 9 for sure, 5-8 if time allows) [U]**
1. **Voice log.** Push-to-talk (and the "Zapis" phrase if time allows) puts each utterance on a large timeline as *heard*; one tap, or saying "potrjeno", makes it *confirmed*. Spoken lines are saved word for word as notes; they are **not** turned into structured drugs or vitals **[U]**.
2. **ETA to the ER.** A big countdown, arrival time, hospital name, a late marker.
3. **Vitals age.** "Last vitals 6 min ago", amber when overdue.
4. **One-tap fallback** for loud moments: big buttons for events and a drug pad (drug, dose, route) and a vitals pad. Same entries, source `crew_tap`.
5. Elapsed timers (time since last drug, CPR running, time since stroke onset). Elapsed time only, never advice.
6. What the ER is doing (acknowledged, bay, team ready), shown from the shared log. Needs the ER backend.
7. Handover screen on arrival: the record to read out, plus the 15-minute handover timer.
8. Offline queue: entries are kept on the tablet and sent when the signal returns, with a sent/pending mark.
9. Dispatch quick reports and dispatch voice, exactly as today (the demo script depends on them, see 4.5).

**Non-goals:** navigation, fuel, fleet, dose calculators, AI suggestions, a chat interface, a Slovenian UI translation (labels stay English, speech is Slovenian/English as today), login, a clinician-approved drug list (see section 9), changes to `backend/`.

**Anti-goals (a failure even if it "works")**
- A value written down that was not said or tapped. No silent correction or guessing of a dose or number; an implausible or unclear number is kept and marked **check this**.
- A vital sign shown without its age.
- **Clinical speech reaching the dispatch parser.** That parser treats words like "nezavesten" and "ne diha" as a new urgent call [M: `backend/app/agent/messages.py`]. The two channels never mix.
- An entry lost by a reload, a dropped connection or a double tap.
- A screen that needs a keyboard, a mouse or small precise taps.

## 3. Constraints

- **Only `frontend/` files change; `backend/` is not touched [U].** The voice backend (browser speech recognition in `voice.ts`, plus the dispatch parser behind `sendFieldMessage`) is reused as it is **[U]**.
- **Rewrite `CrewPage.tsx` in place [U].** 0900B edits this file often (a doctor-car change landed 30 minutes ago), so I merge `main` into `Metelko` before I start and again before I finish, and keep the diff in few files.
- Route `/crew/:vehicleId?world=sim|live` and the dispatch message path keep working. Doctor cars (`vehicle.type === "doctor"`) keep working.
- The demo crew device is an **Android phone in Chrome** [M: `DEMO.md`], so the screen is **tablet-first but must collapse to one column on a phone**.
- Chrome and Edge only for speech (Web Speech API, `sl-SI`), HTTPS or localhost, as today.
- Work only on `Metelko`; nothing is pushed to `main`. Coding stops Sunday 11:00; about 12 hours.
- All patient data is synthetic.

## 4. Design

### 4.1 Stages, from the vehicle and trip [M]

| Stage | When | The screen shows |
|---|---|---|
| Idle | no current trip | status, next stop, the dispatch panel; the log is switched off ("no patient") |
| To the patient | trip not yet loading | job card, ETA to the patient, the dispatch panel |
| With the patient | status loading or onboard | **the logging screen**, ETA to the ER |
| Arrived | trip completed, until the crew says "handover done" | handover screen (goal 7) |

The simulator completes the trip the moment the vehicle arrives and there is no handover phase in the engine [M, ER spec], so "arrived" is kept by the tablet from its own log, not read from the engine.

### 4.2 Layout (landscape tablet, 1024x768 up; no scrolling on the logging screen)

```
+--------------------------------------------------------------------------+
| A3 Ambulance 3 | P-101 stretcher | RED Cardiac arrest      ER UKC  11 min|
|                                                            arrive 23:40   |
+-----------------------------------------+--------------------------------+
| TIMELINE (newest first)                  | VITALS     last 6 min ago      |
| 23:31 morfin 5 mg i.v.      confirmed    | BP 120/80  SpO2 92  HR 96      |
| 23:29 BP 120/80 SpO2 92     confirmed    | [ Enter vitals ]               |
| 23:27 "bolnik je bled"      heard [OK]   | TIMERS  last drug 4 m          |
|                                          | ER      acknowledged, bay 3    |
+------------------------------------------+--------------------------------+
| [ HOLD TO LOG ]  [ Drug ] [ Vitals ] [ Event v ]  [ Dispatch ] [ Handover ]|
+--------------------------------------------------------------------------+
```

Targets at least 64 px, body text at least 18 px, the ETA 64 px or more, dark slate palette of the existing app [C]. On a phone the same blocks stack in this order: ETA, log button, timeline, vitals, pads, dispatch. Hotkey badges are hidden on touch screens. The screen asks to stay awake (Screen Wake Lock, best effort).

### 4.3 Two voice channels [U + M]

- **Log** (hold-to-log button): the speech result is *never* sent to the dispatcher. It becomes a clinical entry.
- **Dispatch** (its own button and the five quick reports): exactly today's path, `sendFieldMessage(world, text, vehicleId)` and its result card.
- One speech recognizer, with a mode that decides which handler receives the result **[C]**; the `voice.ts` hooks are reused unchanged.

### 4.4 Clinical entries

- **Verbatim always, no parsing [U].** Every utterance is stored exactly as said, as a `note` entry. There is no speech parser in the browser or the backend; nothing is guessed or structured from speech.
- **Structured entries come from the tap pads only** (vitals, drug, procedure, event, severity): the crew taps values in, so every number is one the crew entered.
- **Heard, then confirmed:** a spoken note starts as `heard`; the crew confirms it with a tap or "potrjeno" (a spoken line that is exactly "potrjeno" confirms the latest note instead of becoming one), edits it as a new entry, or discards it.
- **Entry shape follows the ER backend draft** [M, `docs/superpowers/specs/2026-11-21-er-dashboard-backend-design.md` on `metelko-erdashboard`]: `client_entry_id`, `case_id` (trip id), `t` (the world's clock from `state.sim_time`), `unit`, `source` (`crew_voice` or `crew_tap`), `type` (`vitals`, `drug_administered`, `procedure`, `event`, `severity`, `handover`, `note`), `content`, `verbatim`, `state` (`heard`, `confirmed`), `needs_check`, `supersedes` (a correction is a new entry).
- **Storage:** the browser (`localStorage`, per world and trip), with a `sent` mark. A small module `clinicalApi.ts` is the only place that talks to the backend: it posts to `/{world}/clinical/entries` and keeps entries pending on a 404 or no signal. **Until the ER backend session ships that endpoint, entries stay on the tablet and the ER dashboard cannot see them [A].** The ER echo (goal 6) reads `state.clinical` only if present, the same way the doctor-car fields are optional.
- **Time:** in the simulation world the clock runs 5x, so "6 min ago" and the ETA tick fast; both use the world clock so they match the dispatcher screen **[C]**.

### 4.5 What must not break

`DEMO.md`: Scenarios tab, **Prepare crew demo**, `/crew/T1?world=sim` on the phone, hold the mic and say *"Vozilo je obstalo. Oprema je še v njem."*, the dispatcher approves, the phone shows "Dispatcher approved the new plan". The dispatch panel keeps this flow, and the quick buttons 1-5 keep their keys on desktop.

## 5. Approaches considered

| Question | Chosen | Rejected, and why |
|---|---|---|
| Where the screen lives | **Rewrite `CrewPage.tsx` in place [U]** | New page on a new route: fewer conflicts but a second crew screen to maintain; separate app folder: duplicates API and voice code |
| How speech becomes entries | **Existing browser voice capture, saved word for word, no parser; structure from tap pads; backend untouched [U]** | Browser rule parser: more work and a risk of wrong numbers; backend Claude parser: it knows no clinical words and would turn "nezavesten" into a dispatch call |
| Storage until the ER backend exists | **Local store behind one swappable module [C]** | Waiting for the backend: blocks the whole screen; mocking a server: more code than it saves |

## 6. Phases (cut from the bottom if time slips)

1. Stages, layout, ETA, dispatch channel kept (goals 2 and 9). Check on tablet and phone sizes.
2. Clinical log: store, voice to confirm card, tap pads, timeline, vitals age (goals 1, 3, 4).
3. Timers, ER echo, offline sync, handover (goals 5-8).

## 7. Verification

- The clinical log (store and sync queue) is pure logic with tests that run with `node --test` and no new dependencies: append, idempotent retry with the same `client_entry_id`, supersede, confirm, the pending/sent queue, vitals age.
- `vite build` and `tsc --noEmit` pass in a scratch copy of `frontend/` (no `npm install` in the shared checkout).
- Playwright screenshots at 1280x800, 1024x768 and 390x844, on a vehicle on a job, an idle one and a doctor car. The dispatch flow of 4.5 is checked without posting to the live backend (only GETs; the send path is checked by reading the request in the network log).

## 8. Left to the builder

Exact component split and file names; CSS details; the drug list for the pad and the vitals ranges that trigger "check this" (labelled placeholders); icon choices; the timeline's maximum visible rows.

## 9. Open questions

- **Drug list and plausible vital ranges** need an EMS clinician. Placeholders are marked as such [?].
- **The ER backend endpoint** (`/clinical/entries`) is in progress in another session; the contract may change [?].
- **Handover** is derived on the tablet, not by the engine; the ER sees it only once the backend exists [A].
- **Slovenian UI labels** are a later pass.
