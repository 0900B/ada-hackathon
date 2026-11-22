# Plan B: how calls are prioritised (and why)

Plan B's dispatch rules follow how emergency dispatch centres and emergency physicians rank calls:
first by **severity level**, then, within the same level, by **how time-critical the specific
condition is** and by the **individual case**. Plan B is decision support for a fictional
operator. The weights below are a model built from published practice, not medical advice. A real
deployment would use the operator's own protocol (in Slovenia, the SloIn NMP index) and its
medical director's rules.

## 1. Severity levels

| Plan B level | Slovenia (SloIn NMP) | UK Ambulance Response Programme | MPDS levels | Typical cases | Plan B response target (to reach the patient) |
|---|---|---|---|---|---|
| **Critical** | I. prioriteta (red): life-threatening now | Category 1 (90% within 15 min; mean 7 min) | Echo, Delta | Cardiac or respiratory arrest, unconscious and not breathing normally, choking, catastrophic bleeding, anaphylaxis with airway compromise | ≤ 8 min in the city, ≤ 15 min outside |
| **Serious** | I. prioriteta (red): may become life-threatening soon | Category 2 (mean 18 min; 90% within 40 min) | Delta, Charlie | Suspected stroke, chest pain or suspected heart attack, severe breathing difficulty, major trauma, ongoing seizure, suspected sepsis | ≤ 18 min |
| **Urgent** | II. prioriteta (yellow): possibly dangerous | Category 3 (90% within 120 min) | Bravo, Alpha | Fractures, falls without red flags, moderate pain, urgent transfers and equipment | ≤ 60 min |
| **Routine** | Planned or non-urgent transport | Category 4 (90% within 180 min) | Alpha, Omega | Scheduled transports (dialysis, discharges) | By appointment |

Critical and serious calls are what the system previously called "emergency". Urgent and routine
are unchanged.

## 2. Same level, different urgency: time sensitivity per condition

Even within one level, some conditions lose more per minute than others. MPDS gives different
responses to different descriptors within the same level. Plan B gives every call a **condition**
with a relative time-sensitivity weight:

| Condition | Level | Weight | Why |
|---|---|---|---|
| Cardiac arrest | Critical | 10 | Steepest time dependence: survival falls about 5.5–6% per minute without defibrillation (7–10% is often quoted). |
| Choking or airway obstruction | Critical | 9 | Minutes to hypoxic damage. |
| Catastrophic bleeding | Critical | 8 | Rapid loss of circulating volume. |
| Anaphylaxis with airway compromise | Critical | 8 | Can progress to arrest within minutes. |
| Suspected stroke | Serious | 6 | Clot-dissolving treatment within 4.5 h, at a stroke centre with pre-alert: destination matters as much as speed. |
| Suspected heart attack (STEMI) | Serious | 6 | First medical contact to catheter lab under 90 min. |
| Severe breathing difficulty | Serious | 5 | May deteriorate quickly. |
| Major trauma | Serious | 5 | "Golden hour" target, but weaker evidence than for the conditions above. |
| Ongoing seizure | Serious | 4 | Time to anticonvulsant matters. |
| Suspected sepsis | Serious | 4 | Time to antibiotics matters, over hours rather than minutes. |
| Fracture or fall injury | Urgent | 2 | Pain and immobility, rarely time-critical. |
| Urgent transfer or equipment | Urgent | 1–2 | Per the requesting hospital's time window. |

**Case modifiers** move a call up within its level:
- a child
- several patients
- a report that the patient is getting worse
- a stroke near the end of its treatment window
- no bystander CPR or AED for an arrest

If a call is reported as better (e.g. the patient is breathing again), the dispatcher re-grades it.

## 3. Decision rules

1. **The closest suitable unit by true arrival time.** This includes units that are **available
   soon**, such as one finishing a drop-off nearby: finish, hand over, then go. A busy unit must beat
   the best free one by at least 3 min, since its timing is less certain.
2. **A higher level may override a lower one.** A unit driving to a lower-level call (not yet on
   scene, no patient on board) is diverted to a critical or serious call when the time saved is
   clear: ≥ 3 min for critical, ≥ 5 min for serious. The displaced patient must still be reached
   within their own level's target by another unit. This follows the "clear and obvious time
   saving, no unnecessary risk to the lower-priority patient" rule used in dispatch policies.
   Exception: when no other unit reaches the higher-level call within its own target, the higher
   level goes first even if the displaced call then misses its target (the summary says so); with
   realistic on-scene and handover times ([SERVICE_TIMES.md](SERVICE_TIMES.md)) the strict rule
   could otherwise leave a serious call waiting hours.
3. **No call is displaced twice.** A unit is not diverted away from the same lower-level call a
   second time.
4. **Same level.** The higher time-sensitivity weight goes first. If the weights are comparable,
   minimise the **worst** wait relative to each patient's target, then the total. Swaps between
   same-level calls are **proposed** to the dispatcher, never applied automatically.
5. **Never divert** a unit with a patient on board, a unit on scene, or one within ~2 min of its
   current patient.
6. **Critical calls get the absolute closest unit**, including the helicopter when it is
   faster, even in the city (the MPDS Echo principle). For serious calls the helicopter goes
   when it is ≥ 10 min faster; for urgent ones only for remote or long-distance cases (≥ 15 min).
7. **Time to definitive care, not only to the scene.** Stroke and STEMI patients go to UKC (stroke
   centre, catheter lab) with a pre-alert; options are compared by arrival at the hospital as well.
8. **Explain clinically.** Every AI recommendation states its reason in one sentence, e.g.
   "cardiac arrest: about 6% survival lost per minute without defibrillation; A1 is 9 min closer".
9. **The human stays in charge.** The engine acts on its own only for rules 1, 2 and 6 at the
   moment of dispatch, because seconds matter. Everything else is a proposal the dispatcher
   approves.

## 4. Slovenian practice adopted

Our teammate's research on Slovenian EMS dispatch ([AGENTIC_DISPATCH_DESIGN.md](AGENTIC_DISPATCH_DESIGN.md)
sections 5.2 to 5.10, with [DISPATCH_SCENARIOS.md](DISPATCH_SCENARIOS.md) and
[LJUBLJANA_FLEET_AND_TEAMS.md](LJUBLJANA_FLEET_AND_TEAMS.md), citing the 2026 rulebook) agrees with the
rules above and adds these points that Plan B now follows:

- **15-minute reference for red calls.** Critical and serious calls are both "red" (I. prioriteta).
  Plan B keeps its tighter critical city target (8 min), and additionally flags any red call whose
  predicted arrival is over 15 min (alert `red_response_over_15_min`); the engine fallback then
  recommends asking a neighbouring station for an ambulance.
- **Protect cover.** The last free ambulance of an area is not sent to a non-life-threatening call if
  a red call there would then be reached only after more than 15 min; a van takes the call instead
  when one can.
- **The helicopter is evaluated for every red call.** This is a calculation, not an automatic flight:
  every dispatch summary for a red call says when H1 would arrive and why it was or was not sent
  (rule 6).
- **Handover at the hospital takes at most 15 minutes**, after which the crew reports free. Plan B
  models a 15-minute handover, then 10 minutes of cleaning ("returning, unavailable"), and a 1-minute
  turnout for ambulances (5 for doctor cars): see [SERVICE_TIMES.md](SERVICE_TIMES.md).
- **Doctor cars (VUZ).** The nurse-and-rescuer ambulance goes first; a doctor car (physician and nurse)
  joins on scene for red calls that need a doctor (cardiac arrest, choking, catastrophic bleeding,
  anaphylaxis, suspected heart attack, severe breathing difficulty, major trauma; not stroke, where the
  stroke centre matters more). About a quarter of red calls, in line with the 10 to 30 % reported in
  [LJUBLJANA_FLEET_AND_TEAMS.md](LJUBLJANA_FLEET_AND_TEAMS.md). The helicopter has a doctor on board.
- **Mutual aid and private ambulances.** When no own unit reaches a red call within 15 minutes, the
  dispatcher is offered a neighbouring station's ambulance or a private one (scenario D11 in
  [DISPATCH_SCENARIOS.md](DISPATCH_SCENARIOS.md)); they join only when the dispatcher approves.

Where his document differs, Plan B keeps the rules above: for two red calls competing for one unit he
minimises the total response time and asks the dispatcher when triage gives no clinical order. Plan B
uses the condition weights (rule 4) and, when they are comparable, the worst wait relative to each
target. In both cases the same-level decision is a **proposal to the dispatcher**, never automatic,
which matches his rule.

## 5. In the code

| Rule | Where | Constant |
|---|---|---|
| Levels, weights, targets, modifiers | `backend/app/engine/severity.py` | `RESPONSE_TARGET_MIN`, `CONDITIONS`, `MODIFIERS`, `RED_REFERENCE_MIN` |
| 1. Closest unit, available soon | `engine/dispatch.py: decide` | `BUSY_UNIT_MIN_GAIN_MIN` = 3 |
| 2. Override a lower level, re-dispatch | `engine/dispatch.py: _override` | `OVERRIDE_MIN_SAVING_MIN` = 3 critical / 5 serious |
| 3. Not displaced twice | `Trip.times_displaced` | |
| 4. Same level: weight, then worst wait | `engine/actions.py: goes_before`, `engine/dispatch.py: swap_options` | `WEIGHT_CLEARLY_HIGHER` = 1.5, `SWAP_MIN_GAIN_MIN` = 5 |
| 5. Never divert near or on scene | `engine/actions.py: near_current_patient` | `NEAR_PATIENT_MIN` = 2 |
| 6. Helicopter per level | `engine/dispatch.py: decide` | `HELICOPTER_GAIN_MIN` = 0 / 10 / 15 |
| 7. Stroke and STEMI judged at UKC | `engine/dispatch.py: decide` | `DEFINITIVE_CARE_CONDITIONS` |
| 8. Clinical reason | `engine/severity.py: clinical_reason` | |
| Doctor cars, mutual aid, private ambulances | `engine/doctors.py` | `DOCTOR_CONDITIONS`, `DOCTOR_TARGET_MIN` = 15 |
| Turnout, on scene, handover, cleaning | `engine/service_times.py` | see [SERVICE_TIMES.md](SERVICE_TIMES.md) |
| Demand trigger, surge capacity, use rules | `engine/surge.py` | see section 6 |

## 6. Surge capacity: contracted units when demand rises

Slovenian dispatch has an escalation ladder for more demand than the area can handle
([AGENTIC_DISPATCH_DESIGN.md](AGENTIC_DISPATCH_DESIGN.md) 5.4,
[SURGE_AND_MULTI_SERVICE_COORDINATION.md](SURGE_AND_MULTI_SERVICE_COORDINATION.md)). Plan B models its
private-provider steps, proactively and always as the **dispatcher's decision**.

**Demand trigger** (thresholds from the rules table in [DISPATCH_SCENARIOS.md](DISPATCH_SCENARIOS.md),
live-calls mode only), on when any of these holds:

| Condition | Constant |
|---|---|
| Free own ambulances are 25 % or less of those crewed (with three crewed: none free) | `DEMAND_FREE_SHARE` = 0.25 |
| A red (critical or serious) call is predicted to wait more than 15 min | `DEMAND_RED_WAIT_MIN` = 15 |
| At least two open calls are predicted past their response target | `DEMAND_PAST_TARGET` = 2 |

It raises the alert `high_demand`, saying why and what would help, with a one-click offer. It never
activates anything. With auto-analyse on, an analysis may start when it turns on and patients are
affected (a red call over 15 min, or calls past target), at most once per 15 world-minutes; the AI then
proposes the surge capacity (rule 10 of the prompt) rather than displacing patients.

**Contracted surge capacity**, activated by the dispatcher (the alert's button, `POST
/{world}/admin/surge`, or an approved option with `activate_surge`): ambulances **P1** (Brezovica) and
**P2** (Vič) with qualified crews, private vans **PV1 to PV3** for non-urgent transports, for **2 hours**
(`SURGE_HOURS`). At the end of the contract (or `POST /{world}/admin/surge/stand-down`) each unit takes
no new jobs, its queued jobs are dispatched again, it finishes its current job, returns and leaves the
fleet. M1 (mutual aid) and P1 can still be requested for a single red call as before.

**Use rules while they are in the fleet** (the ladder's rules, mapped to our severities):

| Calls | Rule | Constant |
|---|---|---|
| Transports (routine bookings, urgent transfers, equipment) | Private vans first; never a contracted ambulance | |
| Urgent calls | A contracted ambulance when our own unit would reach the patient more than 45 min after the call, or the contracted one is 10 min sooner | `PRIVATE_URGENT_WAIT_MIN` = 45, `PRIVATE_URGENT_GAIN_MIN` = 10 |
| Critical and serious calls | A private ambulance only if no public unit (own, helicopter, mutual aid) arrives within 15 min and it is faster | `PRIVATE_RED_GAIN_MIN` = 1 |

Activating moves the waiting calls these rules give to the new units at once (never a patient on
board, a unit on scene or within 2 min of its patient, or a transport already under way).

**Slovenian context.** Non-urgent transports already go through the dispatch service to contracted
providers (dispatch rulebook art. 15); since 2026 non-urgent public providers must answer the
dispatcher's call in a sudden rise in demand [reported, SS]; a **2024 rule (Uradni list RS 2024-01-2739)
requires non-urgent transport providers to reserve 20 % of their capacity for the emergency dispatch
service**. We have not read that text ourselves (the official gazette site failed its certificate check
for us, as it did for Metelko with the 2026 rulebook). Whether private crews may take red calls outside
a declared large disaster is an open point in the research; Plan B keeps them as the last option.

**Measured** (8 world-hours, seeds 42 and 7; "with surge": a stand-in dispatcher activates it for 2 h
whenever the trigger is on and patients are affected):

| Calls per hour | Red calls over 15 min | Worst red wait | Calls displaced | Late trips |
|---|---|---|---|---|
| 5 (default), without | 2 / 3 | 55 / 36 min | 0 / 0 | 2 / 1 |
| 5, with surge capacity | 1 / 3 | 16 / 36 min | 0 / 0 | 1 / 1 |
| 8, without | 16 / 7 | 200 / 45 min | 1 / 1 | 7 / 2 |
| 8, with surge capacity | 5 / 5 | 50 / 47 min | 0 / 1 | 2 / 1 |

With only three own ambulances the first condition ("none free") is on 22 to 53 % of the time even at
5 calls per hour, so the alert itself has **hysteresis** (`engine/surge.update_demand_alert`): it is
raised only when the trigger has been on for 5 world-minutes (`DEMAND_RAISE_AFTER_MIN`) **and**
patients are affected (a red call predicted over 15 min, or two calls past their target), and cleared
only when that has been false for 5 minutes (`DEMAND_CLEAR_AFTER_MIN`; meanwhile it shows as "easing").
All units busy with nobody waiting too long never raises it. Measured over 5 seeds x 8 world-hours:
at 5 calls per hour the raw trigger is on 36 % of the time, the alert 19 % (raised about 3 times per
8 hours); at 8.75 per hour 71 % and 58 %. The engine's and the AI's surge option follow the alert.

## 7. 112 calls from the first second to the end

Every call has a **call record** (`Trip.call`) and a **timeline** (`Trip.timeline`):

- **Intake** (`app/intake.py`): a call typed by the call-taker (`POST /{world}/calls`: the caller's
  words, an address, a known place or a map point) is **triaged by Claude** (a small structured-output
  request, `agent/triage.py`, through the usage guard) and, when Claude is off, limited, slow (12 s) or
  fails, by the **keyword rules** (`agent/messages.grade_text`), so a call is never lost. As a safety
  net the red-flag words may raise Claude's level, never lower it. The call then goes through the
  normal dispatch path (`urgent_request`, section 3), with a doctor car when the triage asks for one.
- **Generated calls** (`sim/calls.py`) carry a fictional caller, a street address and the caller's
  words in Slovenian and English (several texts per condition, each checked against the keyword rules);
  the rules triage them, Claude only with the world's **AI triage** switch on (and while the guard has
  requests to spare). Words come from a separate random stream: the calls and the benchmark are unchanged.
- **Timeline** (`engine/timeline.py`): received, triaged, dispatched, doctor dispatched, rerouted,
  reassigned, delayed, unit replaced, proposal, approved, on scene, doctor on scene, transporting, at
  hospital, handover done, closed, note; each says who (caller, ai, rules, engine, dispatcher, crew).
- **Automatic follow-up of 112 calls** (`engine/followup.py`, every 30 world-seconds, logged by the
  engine): a call whose unit drops out is re-dispatched at once; a call no unit could take is
  dispatched as soon as one can; before arrival a **free** ambulance that reaches the patient **3 min
  sooner** (`FASTER_FREE_UNIT_MIN_GAIN_MIN`, e.g. after a delay) takes over; a call that needs a doctor
  and has none gets the first free doctor car. Detours around closures are automatic (simulator). Calls
  without a 112 record (scenario jobs, bookings, hospital requests) keep the old behaviour, so the
  stranded-patient and stranded-equipment decisions stay with the dispatcher. Trade-offs (overrides of
  other calls, swaps, reserve units, surge) stay **proposals**.
- **Autopilot** (per world, off by default): the recommended feasible option of every analysis about an
  active call is approved by the engine through the dispatcher's own approval path (re-checked,
  applied, audited); activating contracted surge capacity always stays with the dispatcher.

## Sources

- Slovenian dispatch practice as used in section 4: team research (Metelko),
  [AGENTIC_DISPATCH_DESIGN.md](AGENTIC_DISPATCH_DESIGN.md) (unit selection 5.2, several calls 5.3,
  helicopter 5.5, handover 5.8, statuses 5.10), [DISPATCH_SCENARIOS.md](DISPATCH_SCENARIOS.md),
  [LJUBLJANA_FLEET_AND_TEAMS.md](LJUBLJANA_FLEET_AND_TEAMS.md), [DATA_FRESHNESS.md](DATA_FRESHNESS.md).
- Service times (turnout, on scene, handover, cleaning): [SERVICE_TIMES.md](SERVICE_TIMES.md).
- Surge capacity (section 6): [AGENTIC_DISPATCH_DESIGN.md](AGENTIC_DISPATCH_DESIGN.md) 5.4,
  [SURGE_AND_MULTI_SERVICE_COORDINATION.md](SURGE_AND_MULTI_SERVICE_COORDINATION.md) sections 2, 5 and 8,
  [DISPATCH_SCENARIOS.md](DISPATCH_SCENARIOS.md) (rules table, D07 to D11); the 20 % capacity
  reservation for non-urgent providers: Uradni list RS 2024-01-2739 (as reported to us, text not read).

- Slovenia, severity levels (SloIn NMP, red and yellow priorities): [Pravilnik o službi nujne medicinske pomoči in prevozih pacientov (consolidated text, 3 June 2026)](https://www.tax-fin-lex.si/Dokument/Podrobnosti/b509dd37-3d66-492d-893f-61191c3dec52); [gov.si: Nujna medicinska pomoč](https://www.gov.si/teme/nujna-medicinska-pomoc/)
- UK Ambulance Response Programme categories and standards: [NHS England ARP board paper](https://www.england.nhs.uk/wp-content/uploads/2019/07/02-CB-30-03-2017-ARP.pdf), [NEAS: Ambulance Response Programme](https://www.neas.nhs.uk/your-service/999/ambulance-response-programme), [GSS: summary of ambulance response time data](https://analysisfunction.civilservice.gov.uk/government-statistical-service-and-statistician-group/user-facing-pages/health-and-care-statistics/summary-of-ambulance-response-time-data-in-the-uk). The Category 1 mean (7 min) and Category 3 (120 min) figures are the published ARP standards and were not re-checked in this research.
- MPDS determinant levels and responses within a level: [IAED: determinant codes](https://www.iaedjournal.org/determinant-codes), [IAED: response now](https://www.iaedjournal.org/response-now), [PMC: MPDS level and time-critical interventions](https://pmc.ncbi.nlm.nih.gov/articles/PMC3088370)
- Cardiac arrest time dependence: [Larsen et al. (PubMed 8214853)](https://pubmed.ncbi.nlm.nih.gov/8214853), [HealthDay: 2024 Dutch study, 6% per minute to first shock](https://www.healthday.com/health-news/cardiovascular-diseases/every-minute-counts-speedy-defibrillator-delivery-saves-lives-from-cardiac-arrest), [CARES annual report](https://mycares.net/sitepages/uploads/2025/2024_flipbook/inc/html/37.html)
- Time-critical pathways (stroke, STEMI, trauma): [Mills et al. 2019, BMJ Open](https://bmjopen.bmj.com/content/9/11/e023049.full), [Finnish stroke first-response study](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10265899/), [JEMS: limits of response time as a metric](https://www.jems.com/operations/the-enduring-appeal-of-a-myopic-ems-metric/)
- Diverting units to higher-priority calls: [Monterey County EMS Policy 3050](https://countyofmonterey.gov/home/showpublisheddocument/123839/638441310797470000), [Santa Cruz County EMS Policy 612](https://www.santacruzhealth.org/Portals/7/Pdfs/PublicHealth/Emergency%20Medical%20Services/Policies/Section600/Policy%20612%20Resource%20Response%20and%20Management.pdf), [San Mateo County PSC-1: holding priority 3 calls](https://www.smchealth.org/sites/main/files/file-attachments/psc-1_-_holding_priority_3_ambulance_calls.pdf), [PHECC STN001 EMS Priority Dispatch Standard](https://www.phecit.ie/Images/PHECC/Clinical%20resources/STN001%20EMS%20Priority%20Dispatch%20Standard%20V4.pdf)
