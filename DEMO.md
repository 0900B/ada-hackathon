# Demo script: Plan B (3 minutes)

**One line:** *Kaos na terenu?* Plan B is an AI co-pilot for an EMS dispatcher in Ljubljana. The engine
dispatches every call at once, by severity and true arrival time. When something goes wrong, a crew
says it in Slovenian, and about 20 seconds later the dispatcher has simulated plans to approve with one key.

Timings below were measured on the deployed system (Railway, Simulation, Claude Sonnet 5.5) on
21 November; see "What we measured" at the end.

## Roles

| Who | Device | Screen |
|---|---|---|
| Presenter | Laptop on the projector | Dashboard, **Simulation** tab (Live tab for the first 25 s) |
| Crew (teammate) | Android phone, Chrome | `/crew/T1?world=sim` on the production domain |
| Optional | iPad | `/vehicle/T5?world=sim` (the van that will collect the blood products) |

## Pre-stage checklist (15 minutes before)

- [ ] Laptop: open the **production** Vercel domain (Vercel dashboard, Domains), never a
      `frontend-<hash>-….vercel.app` preview link: previews may point at an old build.
- [ ] Hard refresh (Ctrl+Shift+R) on the laptop and on the phone.
- [ ] Status bar shows **Data feeds fresh** and **TomTom live**; the AI badge shows
      **Claude · claude-sonnet-5-5** (not "Engine only").
- [ ] Simulation tab, Dispatch tab: switch **Auto-analyse on** (or remember to press **A** after the
      crew message). Leave it off during rehearsals: it costs tokens.
- [ ] Phone: open `/crew/T1?world=sim`, tap the mic once and **allow microphone access**, SL/EN toggle on **SL**.
- [ ] Phone hotspot on and tested with the laptop.
- [ ] Browser zoom so the map and the right-hand panel are readable from the back of the room.
- [ ] Scenarios tab: **Reset simulation**. Nobody pushes to `main` from now on (a push restarts the
      backend and resets the simulation).

## The 3 minutes

**0:00–0:20 · The problem** (laptop on the Live tab)
> "When a vehicle breaks down or two emergencies come in at once, a dispatcher has seconds to work out
> who is affected, who takes over, and what that does to everyone else. The brief calls it *kaos na
> terenu* and asks for a new plan. That is Plan B."

**0:20–0:45 · Live: real Ljubljana, every call dispatched at once**
- Point at the map: real roads, TomTom traffic colours, real weather and incidents.
- Point at the event log:
  > "Calls come in with a severity: critical, serious, urgent. The engine sends the unit that reaches
  > the patient first, and says why: the condition, the target time, the arrival."
- Click an idle ambulance: "Nothing planned: it waits for the next emergency."

**0:45–1:50 · The crew speaks, Plan B answers**
1. Click **Simulation**, Scenarios tab, **Prepare crew demo**.
   > "Transport 1 is carrying blood products to the Oncology Institute."
2. Nod to the crew. Holding the mic button, the crew says:
   *"Vozilo je obstalo. Oprema je še v njem."*
3. Dashboard (the Dispatch tab opens by itself):
   > "It understood: T1 broke down, the blood products are still inside. Now the AI dispatcher checks
   > which vehicles can reach the breakdown site and simulates complete plans. Every number you will
   > see comes from our engine, not from the language model."
   (If Auto-analyse is off, press **A** now.) Options appear about 15 s after the message.
4. Read the recommended option, for example:
   > "T5 goes now to the breakdown site and picks up the blood products at 22:18, at the Oncology
   > Institute at 22:27. T2 takes T1's next job, the lab samples. Both ambulances stay free for
   > emergencies. And it drafted the crew messages, in Slovenian."
5. Press **Y**. Point at the map: T5 turns towards T1 (it picks up about one minute later in real
   time); the crew phone shows that the dispatcher approved the new plan.
   > "The vehicles do exactly what the option said. If the world had changed in the meantime, the
   > approval would be refused with the reason."

**1:50–2:25 · Life-threatening first: what an emergency physician would decide**
1. Scenarios tab, **Priority override**. Read the new line in the event log:
   > "A cardiac arrest, nobody doing CPR, right next to A1, which is on its way to a fall. The engine
   > diverts A1 at once: 18 minutes sooner than the next ambulance. The fall is not forgotten: T1 takes
   > it, still within its 60-minute target. And it says why: about 6 % survival lost per minute without
   > defibrillation."
2. Point at A1 turning on the map.
   > "That is the doctrine, written down with its sources: severity first, true arrival time, never
   > divert a unit with a patient on board, never displace a call twice."
   Do not approve anything here (see the fallbacks).

**2:25–2:50 · Why you can trust it**
> "The AI proposes, the dispatcher decides with one key. Every option is re-simulated by the engine
> before it is shown. Without the AI, the engine's own plan still appears. Every data source has a
> backup: weather from two providers, traffic from TomTom with promet.si and a time-of-day model
> behind it, routing from OSRM and TomTom. Every message, recommendation and decision is in the audit log."

**2:50–3:00 · Close**
> "Next step: real vehicle GPS and real calls. Plan B: when things go wrong, a new plan in 20 seconds."

## Fallbacks

| Step | Symptom | Do this | Say |
|---|---|---|---|
| Any | Wi-Fi drops | Laptop and phone to the hotspot; the backend is on Railway | (nothing) |
| Crew message | Speech not recognised, or mic blocked | Crew taps the quick button **1 · Vozilo je obstalo.** (or types the sentence) | "Same message, one tap." |
| Crew message | Phone shows "AI could not be reached" | Quick button **1** still works: it sends the breakdown as a plain event | "Even without the AI, the report gets through." |
| Analysis | No options after 30 s | Wait 10 s more; otherwise press **A** again. If the badge says "Engine only", the engine's plan appears at once | "That is the reliability point: the dispatcher is never left empty-handed." |
| Approve | "Plan no longer valid: …" | Press **A** for a fresh analysis (about 15 s) | "It re-checks before it acts: the world moved on, so it asks again." |
| Priority override | The AI panel fills by itself (Auto-analyse on) | Leave it; do not approve. A1 reaches the patient during the analysis | "The AI confirms the engine's decision." |
| Scene looks odd | Wrong vehicles, old jobs | **Reset simulation**, then **Same level, different urgency**, press **A** (options in about 11 s), approve the swap | "Two serious calls: the heart attack goes first, catheter lab within 90 minutes." |

## Jury Q&A cheat sheet

- **Is this an integration into 112 / the national dispatch centre?** No. We present an independent
  EMS operator. Every input and output is an API (GPS feed, calls, crew messages, decisions), so it
  can sit next to an existing dispatch centre.
- **How do you prioritise?** Four levels (critical, serious, urgent, routine) with response targets
  (8/15 min, 18 min, 60 min), a time-sensitivity weight per condition, and Slovenian practice: the
  15-minute reference for red calls, the helicopter checked for every red call, the last free
  ambulance of an area kept for red calls. Rules and sources: `docs/DISPATCH_PRIORITIES.md`.
- **What does the AI decide?** Nothing on its own. Routine dispatch is the engine (deterministic,
  instant). The AI reads the situation after a disruption, proposes two or three plans, and every
  plan is simulated by the engine before it is shown. A human approves.
- **What if Claude is down or slow?** The engine's own plan appears (no AI needed); crews can still
  report with quick buttons. See `docs/RELIABILITY_AND_SECURITY.md`.
- **Security?** API keys only on the server, never in the browser or logs; map tiles proxied; audit
  log of every decision. Production plan: private servers, two data centres, login, encryption.
  `docs/RELIABILITY_AND_SECURITY.md`.
- **Data sources?** Weather: Open-Meteo, backup MET Norway. Traffic: TomTom live, backup a
  time-of-day profile (promet.si / NAP client built, waiting for access). Incidents: TomTom plus crew
  reports. Routing: OSRM, TomTom for detours around closures. Vehicle GPS and calls are simulated.
- **Cost?** A routine call never starts an AI analysis. One analysis is about 1,500 output tokens and
  15 s; a field message is one short call.
- **Honest limits:** GPS and calls are simulated; travel times are estimates (they are refined as road
  routes come in, so an ETA can move by a few minutes); the doctrine is our reading of public sources,
  not a validated medical protocol; the helicopter ignores weather other than fog.

## Rehearsal: three full runs

Run the whole script three times with a stopwatch. After each run: **Reset simulation**, Auto-analyse
back off.

- [ ] Run 1: with speech. Note the seconds from the crew sentence to the options (target: under 25 s).
- [ ] Run 2: with the quick button **1** instead of speech (the fallback path), and the presenter
      pressing **A** by hand (Auto-analyse off).
- [ ] Run 3: full timing. Finish by 2:55. If over, cut the Live part to 15 s.
- [ ] Each run: the recommended option collects the blood products at the breakdown site; after **Y**,
      the van heads there within a few seconds; the Priority override line names A1, T1 and the
      clinical reason.
- [ ] The crew knows the sentence by heart and the position of quick button **1**.

## What we measured (Railway, 21 November)

| Step | Time |
|---|---|
| Crew breakdown report to options (Auto-analyse on) | 13.8 s |
| Analyse after a scenario | 11.4 s (Same level) to 15.8 s (Priority override, Call surge, Stroke and closure) |
| Approve | 0.2 s; the vehicles move on the next tick |
| Approved van at the breakdown site | about 5 world-minutes, about 1 real minute |
| One analysis | about 1,250–1,800 output tokens |

Most reliable: **Prepare crew demo** (recommended option every time: a free van collects the blood
products), **Same level, different urgency** (swap recommended and executed), **Call surge** (keeps the
dispatch and asks a neighbouring station, in Slovenian). **Priority override** is best shown through
the engine's event line, without waiting for the AI.

## Appendix: scenarios and hotkeys

Every scenario resets the simulation, stages the situation and pauses new random calls for 30
world-minutes. "Automatic" scenarios show a decision the engine takes by itself: point at the event log.

| Button | What happens |
|---|---|
| Prepare crew demo | T1 carries blood products to the Oncology Institute; the crew reports the breakdown |
| Stranded patient | T2 breaks down with an urgent patient on board; who collects the patient |
| Stroke and closure | Automatic: A2, finishing a handover at UKC, goes next to a stroke in Polje; Zaloška closed; over 15 min, the red-call alert |
| Priority override | Automatic: A1 diverted from a fall to a cardiac arrest; T1 takes the fall within its target |
| Same level, different urgency | Two serious calls; press **A**: swap so the heart attack goes first |
| Call surge | Seven calls at once incl. a cardiac arrest (H1) and a child with breathing difficulty; mutual aid |
| Remote emergency | Automatic: H1 turns around for a mountain trauma; the skier stays with H1, next |
| Snow cascade | Snowstorm, a stuck van with a patient on board, a fall on ice |
| Stranded equipment | T1 breaks down with blood products on board (no phone needed) |
| UKC full | UKC can admit two more; which patients are redirected and by whom |

Hotkeys (press `?`): `A` analyse · `Y` approve the recommended option · `N` reject · `M` mic ·
`B`/`D` breakdown/delay for the selected vehicle · `F` fog · `E`/`C` emergency/closure on the map ·
`Esc` cancel.

The brief's "initial plan" (začetni plan): `POST /sim/admin/reset {"scheduled_day": true}` starts a
pre-planned day for the vans (0 late, 0 unassigned, no random calls); `{"scheduled_day": false}`
returns to live calls.
