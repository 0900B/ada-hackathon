# Plan B: pitch notes

For the presenter: the five points to land in the 3 minutes ([DEMO.md](../DEMO.md) is the script) and the five questions most
likely to be hard. Every number is simulated unless it says otherwise; say "simulated" out loud. Full answers with proof lines:
[JURY_QA.md](JURY_QA.md).

## The five talking points

**1. An AI dispatcher with the human in charge.**
Every 112 call is dispatched by the rules engine in the second it arrives. Claude then reviews every new **critical or serious** call
and every disruption of an open call (breakdown, delay, closure on the route, priority change). In **Autonomous** mode its
recommendation is applied only after the engine re-checks it; in **Assisted** mode (the default) it is a proposal. The dispatcher can
replace any unit and that choice sticks.
- Numbers: 2 modes; reviews limited to critical and serious calls; 60 s deadline per analysis, 12 s for triage, then the engine's decision or the keyword rules stand; usage guard 12 Claude calls per 5 minutes and 300 per day.
- Shown: **AI dispatcher** tab. The mode switch and the one-line stats ("Handling N cases · reroutes · reassignments · overrides · Claude reviews") at the top; a case card with a one-line reason for each unit and who decided; **Override** with the engine's ranked alternatives; the timeline and badges ("AI classified", "AI dispatched", "Claude reviewed", "Dispatcher overrode").

**2. The crew speaks Slovenian, the dispatcher has a plan in seconds.**
*"Vozilo je obstalo. Oprema je še v njem."* becomes a typed breakdown event with a stated assumption (no vehicle named, so the sender's); the
engine applies the brief's rule (equipment on board must be collected by another vehicle at the breakdown site) and simulates 2–3 complete
plans; every number comes from the engine; approval re-checks the world and is refused with the reason if it changed.
- Numbers: about 15 s from the crew's report to the options in our rehearsals (13.8 s on 21 Nov, one measurement; the hard limit is 60 s); 2–3 options; 1 key to approve.
- Shown: the crew phone (`/crew/T1`, hold to talk); on the dashboard the **Situation review** ("Understood: …", the options with step-by-step lines, **Approve** or `Y`); the phone then says "Dispečer je potrdil nov načrt".

**3. One honest benchmark number.**
In 100 simulated 8-hour day shifts with identical calls, the rules reach **53.8 %** of critical patients within the target (8 min in the city, 15 outside) against **34.3 %** for nearest-free-ambulance dispatch; with ground units only (night, fog) **42.6 % against 34.3 %**.
- Also: serious calls within 18 min 64.4 % against 43.1 % (ground only 45.5 % against 43.1 %); late transports 7.5 % against 20.5 % (ground only 18.5 % against 20.3 %); median time to a critical patient 8.0 against 12.4 min. The slowest tenth of serious calls waits longer without the helicopter (74 against 67 min): we say so.
- The helicopter is the real one's model: Brnik, 13 min from call to take-off, 08:00–16:30 only. Our first run had an unrealistic helicopter (74 % against 35.5 %); we withdrew it.
- Shown: not in the app: [BENCHMARK.md](BENCHMARK.md), `backend/tools/benchmark.py`. The **Reports** page measures the same kind of thing on the running simulation (response time against the target by severity, late transports, who decided). The benchmark does not include Claude.

**4. Every input has a backup, and the AI is optional.**
Weather from two providers; traffic TomTom, then promet.si (client built, access pending), then a time-of-day model; routes OSRM, then TomTom, then straight line × 1.35; Claude, then the engine's plan; triage by Claude, then keyword rules. The status bar says which source is live.
- Numbers: weather 2 providers; traffic and routes 3 levels each (TomTom / promet.si / time-of-day profile; OSRM / TomTom / straight line × 1.35); 60 s and 12 s AI deadlines; guard 12 per 5 min, 300 per day; the demo lock: control actions need `ADMIN_KEY`, reading is open.
- Shown: status bar chips ("Data feeds fresh", "TomTom live" or "profile"), the "Engine only" chip in the Situation review, the triage tag "AI triage · Claude" or "· rules", the header's "Control unlocked" / "View only", the Audit page.

**5. Slovenian doctrine, labelled as a model.**
Four severity levels with response targets (critical 8 min in the city and 15 outside, serious 18, urgent 60), 14 conditions weighted by time sensitivity (cardiac arrest 10, stroke and heart attack 6, ...), the 15-minute red reference, doctor cars, a helicopter that flies by day from Brnik, stroke and heart attack judged by arrival at UKC. Built from published practice; not medical advice, not measured Ljubljana data.
- Numbers: 15 min reference; 13 min helicopter activation; 08:00–16:30; 200 km/h; 3 ambulances, 5 vans, 1 helicopter, 2 doctor cars in the demo fleet (the real station has 12 emergency teams).
- Shown: severity badge, condition and weight on each case; the alert "reached only after N min (reference for red calls: 15 min): ask a neighbouring station"; the helicopter's "Unavailable at night until 08:00"; the clinical reason on every call ("about 6 % survival lost per minute without defibrillation").

## The five hard questions

**1. "Isn't an AI dispatcher dangerous?"**
The engine dispatches at once by written, tested rules; Claude only reviews, its change goes through the same re-checked path a dispatcher's approval uses, the dispatcher can replace any unit and that sticks, and Autonomous mode is a switch that is off by default. → [JURY_QA.md](JURY_QA.md) T1, Q8, T6.

**2. "These numbers look too good, and it is all simulated."**
Our first run did look too good (unrealistic helicopter, 74 % against 35.5 %); we rebuilt it as the real service runs and now quote 54 % against 34 %, and 43 % against 34 % with ground units only; the baseline is a plain rule, Claude is not in it, and only a shadow-mode pilot on real logs turns it into evidence. → T2, T4, Q18, Q19, Q20.

**3. "What data goes where? Is this GDPR-compliant?"**
We do not claim compliance: it is synthetic data. A 112 call's words and address go to Claude, Chrome's speech recognition goes to Google, and patient locations go to the public OSRM server; the caller's name, crew names and the audit log are never sent. Production means an EU region under a processing agreement with zero retention, redaction, and speech and routing on our own servers. → Q10, [RELIABILITY_AND_SECURITY.md](RELIABILITY_AND_SECURITY.md) section 2.

**4. "Why not the existing dispatch software? Are you replacing 112?"**
No: an independent operator, API-first, next to the dispatch centre; we have not seen Computel NMP 3000's feature list and claim nothing about it; Plan B replans a whole fleet when something breaks and understands a crew's Slovenian. → Q3, Q4, Q21.

**5. "Who pays, and who is liable if a plan is wrong?"**
A paid pilot with one independent transport provider first, shadow mode before advisory mode (the prices are illustrative and not validated with an operator); the dispatcher decides, as today, and in production each approval is signed with their identity; the medical rules would be the operator's own, and whether software like this is a medical device we have not assessed. → Q24, Q20, T5, [BUSINESS_ONE_PAGER.md](BUSINESS_ONE_PAGER.md).

## Do not say

- "54 %" without the helicopter clause and "simulated".
- "Integrated with 112 / Computel", "real GPS", "real calls": the fleet, the calls and the GPS are simulated.
- "GDPR-compliant", "EU-hosted" (the demo runs on Railway and Vercel, regions not chosen).
- "The AI dispatches": say the engine dispatches, Claude reviews, the dispatcher can override.
- Any measured effect of Claude on outcomes: the benchmark has no AI in it.
