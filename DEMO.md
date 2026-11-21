# Demo script: Plan B (3 minutes)

**One-liner:** *Kaos na terenu?* Plan B is a dispatch system for an EMS operator. It runs the fleet
on real roads with live traffic and weather. When something goes wrong, a crew can simply **say** it
in Slovenian, and within about 30 seconds the dispatcher sees what's at risk and 2–3 simulated plans to
approve.

We present an **independent EMS** (a fictional operator, "Ljubljana Demo EMS"), not an integration
into Slovenia's 112/DCZ system. If the jury asks about integration: every input and output is an
API (GPS feed, orders, crew messages, decisions), so it can sit next to an existing dispatch centre.

**How operations work: live calls** (the default; close to how Slovenian EMS works):
- There is **no pre-planned day**. Calls come in all the time (about one every 7–8 minutes of world
  time): emergencies at addresses around Ljubljana, now and then a remote one, urgent patient
  transports (health centre to UKC, GP referrals, urgent discharges, transfers) and urgent equipment runs
  (blood products, lab samples, a ventilator). The engine dispatches **each call at once**; the event log
  says who was sent and when they arrive. Vehicles return to base after every job, so clicking a vehicle
  shows its current job and at most one more.
- **Every call has a severity level and a condition**: critical (cardiac arrest, choking, catastrophic
  bleeding, anaphylaxis; reach within 8 min), serious (stroke, heart attack, breathing difficulty, major
  trauma, seizure, sepsis; 18 min), urgent (falls, fractures, transfers, equipment; 60 min). Within a
  level, each condition has a time-sensitivity weight (cardiac arrest 10, stroke and heart attack 6,
  seizure 4, ...). The doctrine and its sources: `docs/DISPATCH_PRIORITIES.md`.
- **Ambulances A1–A3 are emergency units.** The engine sends the unit that reaches the patient first,
  including one **finishing a drop-off nearby** (if at least 3 min sooner than the free one). A
  life-threatening call may **divert** a unit from a less urgent call it has not reached yet, when that
  saves at least 3 min (critical) or 5 min (serious) and the displaced patient is still reached within
  their own target by another unit. Never with a patient on board, on scene or within 2 min of its
  patient; no call is displaced twice. Two calls of the same level are never swapped automatically: the
  engine proposes a swap (more time-critical first, else the shorter worst wait). Every summary gives
  the clinical reason ("cardiac arrest: about 6% survival lost per minute without defibrillation").
- **Transport vans T1–T5** take urgent patient transports and equipment runs (and bookings). Never
  emergencies. The last free ambulance of an area is kept for red calls: a van takes the non-urgent job.
- **Helicopter H1**: the closest unit for a critical call even in the city; for a serious call only if
  10 min faster; urgent calls only when remote. It is checked for every red call (the summary says so).
  Fog grounds it.
- A red call predicted to be reached after **15 min** (the Slovenian reference) raises an alert and the
  engine recommends asking a neighbouring station.
- A routine call **never** starts an AI analysis (no tokens). Only a genuine problem may (a call no unit
  can take, or one that will be late), and only when Auto-analyse is on.
- **Approving a plan does exactly what the option says**: each option lists, step by step, which
  vehicle goes now or next and when it arrives; the vehicles then do that. If the world changed while
  the option was on screen (e.g. the vehicle has loaded another patient), approval is refused with the
  reason instead of doing something else.

**If a juror asks for the brief's "initial plan" (začetni plan):** switch the world to the **scheduled
day**: the vans start with a pre-planned list of booked trips (0 late, 0 unassigned) and no random calls
come in. `POST /sim/admin/reset {"scheduled_day": true}` (or the UI switch, if wired); back with
`{"scheduled_day": false}`. `SCHEDULED_DAY=1` makes it the start-up default. The demo scenarios always
run in live-calls mode.

## Roles
- **Presenter (laptop on the projector):** dispatcher dashboard, Simulation tab.
- **Crew (teammate with an Android phone, Chrome):** Crew view, e.g. `https://<vercel-url>/crew/T1?world=sim`.

## Before going on stage (10 min before)
- [ ] Laptop: open the Vercel URL. The status bar shows `Connected` and `Data feeds fresh`, with traffic as "TomTom live".
- [ ] The AI badge shows `Claude · claude-sonnet-5-5`, not "Engine only".
- [ ] **Auto-analyse:** it is off by default (saves tokens). Either turn on the **Auto-analyse** switch in the AI dispatcher panel (Simulation, Dispatch tab) right before going on stage, or remember to press **A** (Analyse) after each event / the crew message. Leave it off during rehearsals. Routine live calls never start an analysis, even with it on.
- [ ] Both worlds run **live calls** (status: `mode: live_calls`): calls appear in the event log every few minutes. After a scenario button, new calls pause for 30 world-minutes (6 real minutes in Simulation) so they don't disturb the decision. To stop calls entirely: `POST /sim/admin/calls {"enabled": false}`.
- [ ] **Don't push to `main` anymore.** Every push restarts the backend and resets the simulation.
- [ ] Phone: open the Crew view URL over **HTTPS** (the Vercel URL, never a local IP). Tap the mic once and **allow microphone access**. Set the SL/EN toggle to **SL**.
- [ ] Dry run: Simulation → Scenarios tab → **Prepare crew demo**. The message shows the vehicle carrying equipment: always **T1**, loading blood products at UKC for the Oncology Institute (a short run: the crew should speak within about a minute). Open `/crew/T1?world=sim` on the phone, say the sentence, approve, then **Reset simulation** (bottom of the Scenarios tab).
- [ ] Browser zoom: make the map and the right-hand panel readable on the projector. Press `?` once to check that the shortcuts work.
- [ ] Phone hotspot ready, in case the venue Wi-Fi fails.

## The 3 minutes

**0:00–0:25 · The problem.** "Dispatchers juggle dozens of transports. When a vehicle breaks down or
a road closes, they must work out, under pressure, who is affected, who takes over, and what that does
to everyone else. The brief calls it *kaos na terenu*, and asks for *a new plan*. That's Plan B."

**0:25–0:50 · Live tab: live calls, dispatched at once.**
- Show real Ljubljana: the fleet drives real roads, TomTom traffic colours are on, plus real weather and real incidents.
- Point at the event log: "Calls come in; the engine sends the nearest suitable free unit at once and says when it arrives."
- Click a vehicle on a job: its crew, fuel, its current job (and at most one more) with ETAs. Click an idle **ambulance**: nothing planned, waiting at its base for the next emergency.
- "Every call already has a vehicle and an arrival time. The system always knows the facts."

**0:50–2:10 · Simulation: the crew speaks, Plan B answers (*popravek plana* + AI).**
1. Scenarios tab: click **Prepare crew demo** (T1 is now carrying blood products). The dashboard switches to the Dispatch tab when the AI starts.
2. **Crew on the phone, holding the mic button:** *"Vozilo je obstalo. Oprema je še v njem."*
3. **Point at the dashboard:**
   - "Understood: T1 broke down, the equipment is still inside." The AI also states its assumption: no vehicle was named, so it took the sender's.
   - If Auto-analyse is off, press **A** now.
   - The AI dispatcher's live trace: "It's checking which vehicles can reach the breakdown site, and simulating complete plans. **Every number comes from our engine, not the language model.**"
   - The options appear. Read out the recommended one: who collects the blood products at the breakdown site (the brief's rule; usually a free van, "goes now"), who takes T1's next job (lab samples), plus the before/after numbers. Each step line says who goes now or next and when.
4. Press **Y** (or click Approve). The vehicles do exactly what the steps said: the routes update on the map, and the crew's phone shows "Dispatcher approved the new plan".

**2:10–2:40 · Why you can trust it.**
- **Human in the loop:** the AI proposes; the dispatcher approves with one key.
- **No invented numbers:** the engine re-simulates every option before it's shown.
- **Always works:** without the AI, the engine's own plan appears. If a data feed fails, the system falls back and says so.
- **Every data source has a backup** (say this sentence): *"Weather comes from two providers, traffic from TomTom with promet.si and a time-of-day model behind it, routing from OSRM and TomTom. If the AI is down, our engine still plans. In production it runs on private servers, twice, in two data centres, with login, encryption and a full audit trail."* Details for jury questions: `docs/RELIABILITY_AND_SECURITY.md`.
- **Accountable:** the **Audit** page logs every message, recommendation and decision, stored in Postgres.

**2:40–3:00 · Close.** "Live calls, helicopters with fog grounding, equipment, hospital capacity and priority
changes are all in there too. Next step: real vehicle GPS and real orders. Plan B: when things go
wrong, a new plan in 30 seconds."

## If something goes wrong
- **Speech doesn't work** (permission, noise, network): tap the quick button **1 · "Vozilo je obstalo."** on the phone, or type the sentence. Same result.
- **Claude is slow or down:** the engine fallback still produces a plan. Say: "That's the reliability point: the operator is never left empty-handed."
- **Wi-Fi is down:** switch to the hotspot. The backend runs on Railway, so only the devices need internet.
- **The scene looks odd:** **Reset simulation** → **Stroke and closure** (Scenarios tab). It's the most predictable scenario and needs no phone.

## Hotkeys (dashboard, press `?` to see them)
`M` mic · `A` analyse · `Y` approve recommended · `N` reject · `B`/`D` breakdown/delay for the selected vehicle · `F` fog · `E`/`C` emergency/closure on the map · `Esc` cancel · `?` help

## Scenarios (Simulation tab)
Every scenario starts from an empty live-calls day, puts the fleet on a few live jobs, fast-forwards to
the moment and applies its events. New random calls pause for 30 world-minutes. With Auto-analyse off,
press **A**: the analysis gets the scenario's description. Three scenarios show a decision the
**engine takes by itself** at the moment of dispatch (marked "Automatic": closest unit incl. one
finishing nearby, override of a less urgent call, the helicopter): point at the event log line, which
says what happened and the clinical reason. The others leave a decision for the AI (even the
engine-only fallback has an option to approve or an escalation).

| Button | What happens | The decision when you press A |
|---|---|---|
| Prepare crew demo | T1 loads blood products at UKC for the Oncology Institute (one more job queued); A2, T3, T4 busy | Sets up the live crew message ("Vozilo je obstalo. Oprema je še v njem.") |
| Stranded patient | T2 breaks down **with an urgent patient on board** (one more job queued); A1 and A2 are on emergencies | Who collects the patient at the roadside: a free van (goes now) or A3, the last free ambulance; who takes T2's next job |
| Stroke and closure | **Automatic (available soon).** Stroke in Polje, Zaloška closed at Kodeljevo. A2 is handing over a patient at UKC, the only free ambulance (A3) is far away near Medvode, H1 is out on a mountain call | The event log: "dispatched A2 (available soon: drops off at UKC, at the patient ..., 7 min sooner at UKC than A3)". The stroke is judged by arrival at UKC (stroke centre). The loaded leg goes **around** the closure (orange). Over 15 min: the red-call alert and mutual-aid advice |
| Priority override | **Automatic (override).** A1 is on its way to an urgent fall when a cardiac arrest (no bystander CPR) is reported next to it; A2 has a patient on board, A3 is far away | The event log: "A1 diverted from TR-003 (urgent) to this critical call ... 18 min sooner than A3; TR-003 taken over by T1 (within its 60-min target); Cardiac arrest: about 6% survival lost per minute without defibrillation" |
| Two serious calls | A1 is on its way to a seizure in Polje when a suspected heart attack is reported right next to it; the engine sends the free A3 (same level: nothing automatic) | Press A: **swap** proposed: A1 takes the heart attack (more time-critical: catheter lab within 90 min), A3 the seizure; approve and A1 turns around |
| Remote emergency | **Automatic (override, helicopter).** H1 is flying to an urgent skier (wrist fracture, Krvavec) when a hiker falls at Kamniška Bistrica (major trauma, 45 min by road) | The engine turns H1 around at once ("31 min sooner than A3 by road"); the skier stays with H1, next, within target. Watch H1 **fly**, land, load and land at UKC. Optional: **F** (fog) while it flies |
| Call surge | Seven calls in about three minutes, including a **cardiac arrest** and a child with breathing difficulty; three ambulances | The arrest gets **H1** (the closest unit for a critical call, even in the city); the fall goes to a van; two serious calls wait for units finishing at UKC, over 15 min: red-call alerts. Press A: who waits (time sensitivity), mutual aid from a neighbouring station |
| Snow cascade | Snowstorm, T1 stuck 25 min with a patient on board and another queued, a fall on ice with a head injury (serious) | The fall gets the nearest ambulance at once; T1's queued patient turns late: move it to a free van; who else waits |
| Stranded equipment | T1 breaks down with the blood products on board | Who collects them at the breakdown site (the brief's rule) and who takes T1's next job |
| UKC full | Five patients heading to UKC; one (in a van) gets chest pain (now serious, suspected heart attack) and UKC can admit only two more | The engine sends an ambulance to the heart attack at once (it keeps its UKC slot). Which three are redirected, where (Trbovlje / Novo mesto), and by whom (a long transfer: some will be late, the AI should say so) |

Extra buttons (Events tab): **Fog: ground helicopters 1 h** grounds the helicopter for 1 h (a trip it has not picked up yet goes to the nearest ambulance at once). **Priority & capacity** changes a patient's priority or a hospital's capacity. **Map click (E)**: a new emergency at that spot is dispatched at once.
