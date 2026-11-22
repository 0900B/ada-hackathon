# Bypass: jury Q&A (spoken answers)

Prepared for the 3-minute demo at AdaHack 2026 (Challenge 3, Epilog: "Kaos na terenu"). The operator in the
demo is fictional ("Ljubljana Demo EMS"). Every answer below is grounded in this repository; the line under
each answer says where, so you can open the page if a juror digs.

**How to use this page**
- The quoted block is what to say out loud (2 to 4 sentences). Everything under it is backup, not for reading aloud.
- Tags: **[built]** runs in the prototype today. **[planned]** a design or production plan, not built.
  **[assumption]** our choice, no source. **[reported]** from news or search summaries in our research; we did not
  read the original text.
- Three rules for stage: say **"simulated"** about the fleet, the calls and the benchmark; say **"planned"** about
  production hosting and login; never quote the 54 % figure without the helicopter sentence (Q18, T2).

**Numbers to have ready**

| Say | Number | Always add |
|---|---|---|
| Critical patients reached within target | 53.8 % (Bypass rules) against 34.3 % (nearest free ambulance), normal load | simulated, 100 seeds x 8 h day shifts; helicopter as the real one runs (Brnik, 13 min to take-off, day only) |
| The same, ground units only | 42.6 % against 34.3 % | this is the conservative figure (night, fog) |
| Serious patients reached within 18 min | 64.4 % against 43.1 % (ground only: 45.5 % against 43.1 %) | simulated |
| Late transports | 7.5 % against 20.5 % (ground only: 18.5 % against 20.3 %) | simulated |
| AI analysis deadline / triage deadline | 60 s / 12 s, then the engine or keyword rules answer | |
| Claude usage guard | 12 calls per 5 min, 300 per day (defaults) | configurable by environment variable |
| Cost of one AI analysis | about $0.15 | an estimate, arithmetic in Q25 |
| Typical Claude cost for a desk like ours | about $4 a day | an estimate, assumptions in Q25 |
| Ljubljana ambulance station, 2025 | 48,754 interventions, 16,087 life-threatening at dispatch (about 134 a day, about 44 urgent) | UKC annual report 2025, via [OPERATIONS_DETAILS.md](OPERATIONS_DETAILS.md) |

---

## 1. Problem and users

### Q1. What problem are you solving, and why does it matter?
> When something goes wrong, a vehicle breaks down, a road closes, fog grounds the helicopter, calls pile up, the
> dispatcher has to work out under pressure who is affected, who takes over, and what that does to everyone else.
> Bypass does that work: it simulates the knock-on effects and puts two or three complete plans in front of the
> dispatcher, each with real numbers, to approve with one key. In our rehearsals on the deployed system that took about
> 15 seconds from a crew's spoken message to the options; the hard limit is 60 seconds, after which the engine's own
> plan appears.

*Proof:* [CHALLENGE.md](CHALLENGE.md) (part 2, plan repair), [DEMO.md](../DEMO.md). The 15 seconds comes from our
rehearsals on 21 November (13.8 s from the crew's report to the options with Auto-analyse on; an analysis took 11 to 16 s):
a handful of runs, not an average. The 60 s deadline is `AGENT_TIMEOUT_S` in [config.py](../backend/app/config.py).

### Q2. Who actually uses it, and how?
> Three groups. The dispatcher at the operator's desk sees the map, the case list with the AI dispatcher's decisions
> and the options, approves with one key, and can replace any unit by hand. The crew uses a phone: they hold a button and speak Slovenian, or type, or tap one of five quick-status
> buttons, and then see the approved plan. Hospitals and affected patients get notification drafts in Slovenian and
> English that the dispatcher decides to send; the prototype drafts them, it does not send SMS or e-mail yet.

*Proof:* [DEMO.md](../DEMO.md) (roles), [RELIABILITY_AND_SECURITY.md](RELIABILITY_AND_SECURITY.md) (crew input
fallbacks), `notifications` in the output schema of [prompts.py](../backend/app/agent/prompts.py). SMS (Twilio) is
"documented only" in [DATA_SOURCES.md](DATA_SOURCES.md).

### Q3. Why not just use the existing dispatch software, for example Computel NMP 3000?
> Our research found that Slovenia's health dispatch runs on Computel's NMP 3000, that every ambulance must report GPS
> to dispatch within 10 seconds, and that dispatch picks the nearest suitable team. We have not seen its feature
> list, and the routing method is not published, so we do not claim it lacks anything. Bypass is a different layer:
> it replans a whole fleet when something breaks, it understands a crew's Slovenian sentence, and it works for an
> independent operator. It does not replace dispatch, it sits next to it through APIs.

*Proof:* [GAPS_STATUS.md](GAPS_STATUS.md) row 2 (Computel NMP 3000, annual report 2025), [DATA_FRESHNESS.md](DATA_FRESHNESS.md)
(renewal tender ended without a selected bidder, **[reported]**), [LJUBLJANA_FLEET_AND_TEAMS.md](LJUBLJANA_FLEET_AND_TEAMS.md)
section 3 (GPS within 10 s, 99.5 % availability, via the Information Commissioner's quote of the 2017 rulebook).
We have not verified what private transport providers use today.

### Q4. Is this a replacement for 112 or the dispatch centre?
> No. In Slovenia the health dispatch centre at UKC does triage and dispatch, and our research says triage stays a
> human step. We show an independent operator, a fictional one, with its own fleet and its own dispatcher. Every input
> and output is an API (GPS feed, orders, crew messages, decisions), so Bypass can run alone or next to a dispatch centre.

*Proof:* [DEMO.md](../DEMO.md) (intro), [AGENTIC_DISPATCH_DESIGN.md](AGENTIC_DISPATCH_DESIGN.md) sections 1 and 10
(human steps), [EMS_RESEARCH.md](EMS_RESEARCH.md) section 2 (112, ReCO, DCZ). Our 112 intake form with AI triage is
decision support for a call-taker: the engine dispatches the call at once and does not wait for a confirmation, and the
call-taker or dispatcher can re-grade the call or replace the unit at any time (see
[DISPATCH_PRIORITIES.md](DISPATCH_PRIORITIES.md) sections 7 and 8).

---

## 2. How it works

### Q5. What does Claude do, and what does the engine do?
> Claude reads the situation, calls three engine tools (find candidates, simulate a plan, show a vehicle's schedule)
> and writes two or three options with a recommendation and notification drafts in Slovenian and English. The
> deterministic engine does everything that is a number: travel times, arrival times, delays, the dispatch rules,
> and re-simulating every option before the dispatcher sees it. Claude also turns a crew's sentence into a
> structured event and triages a typed 112 call, both through strict JSON schemas that the engine validates. And as the
> AI dispatcher it reviews every new critical or serious call after the engine has dispatched it, and every disruption of
> an open call, and either keeps the engine's decision or recommends a better one.

*Proof:* [backend/README.md](../backend/README.md) ("The Claude agent"), [prompts.py](../backend/app/agent/prompts.py)
(tools, output schema), [messages.py](../backend/app/agent/messages.py), [triage.py](../backend/app/agent/triage.py),
[ai_dispatcher.py](../backend/app/ai_dispatcher.py), [DISPATCH_PRIORITIES.md](DISPATCH_PRIORITIES.md) section 8.
Default model `claude-sonnet-5-5`, effort `medium`; the message parser and the triage run at effort `low`.

### Q6. Why can we trust the numbers on the screen?
> The model is told in its instructions that every number must come from a tool result, and in any case every option is
> re-simulated by the engine before it is shown, and again when the dispatcher approves. If the world changed in
> between, for example the vehicle has already loaded another patient, approval is refused with the reason instead of
> doing something else. The model can still pick a poor option, which is why the dispatcher sees the numbers for each
> option side by side.

*Proof:* "Rules" in [prompts.py](../backend/app/agent/prompts.py); [RELIABILITY_AND_SECURITY.md](RELIABILITY_AND_SECURITY.md)
section 2 ("Human in the loop"); [backend/README.md](../backend/README.md) (plan execution: refused with 409 if now clearly
worse than shown). Regression tests cover the dispatch rules, doctors, surge, service times and plan execution
(`backend/tests/`).

### Q7. What happens if the AI is wrong, or slow?
> Wrong: the engine rejects anything invalid, such as unknown vehicle or place ids, the numbers come from the
> simulator, and the dispatcher sees two or three options with a clinical reason and decides. Slow or down: the
> whole analysis has a 60-second deadline, and after that, or with no key, an outage, a refusal or the usage limit,
> the engine's own plan appears within a few seconds and is labelled as the engine's plan. A typed 112 call falls back
> to keyword rules after 12 seconds, so a call is never lost, and a call was already dispatched by the engine before
> Claude's review, so if the review is slow or fails the engine's decision simply stands.

*Proof:* [runner.py](../backend/app/agent/runner.py) (`wait_for`, fallback to `_engine_recommendation`),
[triage.py](../backend/app/agent/triage.py) (`TRIAGE_TIMEOUT_S = 12`), [guard.py](../backend/app/guard.py) (notes),
[ai_dispatcher.py](../backend/app/ai_dispatcher.py) (`_engine_stands`),
[RELIABILITY_AND_SECURITY.md](RELIABILITY_AND_SECURITY.md) section 1 (AI rows). The engine's plan is computed locally;
it took about 4 seconds for a stranded-equipment scenario in a check without a key (not "under a second").
If Claude declines a request, the API retries on Anthropic's server-side fallback model (`fallbacks="default"`).

### Q8. Where is the human, and what is autonomous versus assisted?
> The default mode is Assisted. The engine acts on its own at the moment a call arrives for only three rules, because
> seconds matter: the nearest unit by true arrival time, including one finishing a drop-off nearby; diverting a lower
> priority unit when the saving is clear; and the helicopter check. Claude then reviews every new critical or serious
> call and every disruption of an open call. In Assisted mode its recommendation is a proposal that the dispatcher
> approves with one key. In Autonomous mode, a switch that is off by default, it is applied after the engine re-checks
> it, and logged as the AI's. In both modes the dispatcher can replace any unit by hand, and that choice sticks. Swaps
> between equal-priority calls, reserve units, contracted surge capacity and the plans for equipment and bookings
> always stay with the dispatcher. Auto-analyse is a second switch, also off by default.

*Proof:* [DISPATCH_PRIORITIES.md](DISPATCH_PRIORITIES.md) section 3 rule 9, section 6, section 8 (the AI dispatcher
modes, overrides that stick), [ai_dispatcher.py](../backend/app/ai_dispatcher.py), `_autopilot` in
[runner.py](../backend/app/agent/runner.py) ("not about an active call, left for the dispatcher").
Also automatic for calls with a 112 record: re-dispatch when a unit drops out, and a free unit that is 3 min faster takes over.

### Q9. How does a Slovenian sentence become a plan?
> The crew holds the mic and says "Vozilo je obstalo. Oprema je še v njem." Claude maps that to a breakdown event with
> equipment on board and picks the vehicle from the context; if no vehicle is named it takes the sender's and says so.
> The engine checks the ids and applies the event, and the analysis then finds who collects the equipment, which is
> the brief's rule. If a message is ambiguous the parser asks back instead of guessing, and the dispatcher sees what
> Claude understood, including any assumption it made.

*Proof:* [CHALLENGE.md](CHALLENGE.md) (part 3), `PARSE_SYSTEM` and `to_operator_events` in
[messages.py](../backend/app/agent/messages.py), [DEMO.md](../DEMO.md) (the 3 minutes). Speech uses the browser's
recognition (`sl-SI`); if it fails, typed text and quick-status buttons give the same result.

---

## 3. Data and safety

### Q10. What about GDPR and health data?
> We do not claim GDPR compliance for the prototype: it uses only synthetic data, and patients are pseudonymous labels
> like P-123. But free text does leave the system. A typed 112 call's words and address go to Claude for triage, and
> they travel again in every later analysis of that case, as its note and place name; a crew message goes as text;
> and Chrome's speech recognition sends audio to Google. The caller's name, crew names and the audit log are never sent.
> In production, health data is a special category, so it would stay in the EU behind a data protection impact
> assessment: Claude in an EU region under a processing agreement with zero retention, redaction of free text or the
> keyword rules, and EU-hosted or on-premises speech-to-text.

*Proof:* [RELIABILITY_AND_SECURITY.md](RELIABILITY_AND_SECURITY.md) section 2 (a table of exactly what is sent where),
`triage_claude` in [triage.py](../backend/app/agent/triage.py) (the request contains only the words and the address),
`build_situation` in [context.py](../backend/app/agent/context.py) (open trips carry the note and place names, not the
call record), [DATA_SOURCES.md](DATA_SOURCES.md) item 11 (Chrome Web Speech API). We have not verified any AI
provider's current data-residency or retention terms. **[planned]** for everything in production.

### Q11. Where would it be hosted? What is the EU plan?
> The demo runs on Railway for the backend and Vercel for the frontend; we have not chosen or verified a region
> because it holds no real data. The production plan is the operator's own servers or a Slovenian or EU sovereign
> cloud, two instances in two data centres with automatic failover and a replicated PostgreSQL. Claude would be used
> through an EU-hosted, zero-data-retention setup if the provider offers it, or swapped for another model; the
> system stays fully usable with the AI off. This is a plan: today the live state is in memory in a single replica.

*Proof:* [RELIABILITY_AND_SECURITY.md](RELIABILITY_AND_SECURITY.md) section 3, [backend/README.md](../backend/README.md)
(deploy on Railway, "Keep 1 replica: the state lives in memory"). **[planned]**

### Q12. How are keys secured, and what is logged?
> API keys for Anthropic, TomTom and NAP exist only as server environment variables: never sent to the browser, never
> logged, never in error messages or the health check, and even the traffic map tiles are proxied through our backend
> so that key never reaches the client. Every crew message, interpreted event, AI recommendation and dispatcher decision
> is stored with a timestamp in PostgreSQL, shown on the Audit page and exportable. The audit writer never blocks a
> dispatch: if the database is down it buffers in memory and retries.

*Proof:* [RELIABILITY_AND_SECURITY.md](RELIABILITY_AND_SECURITY.md) section 3, [audit.py](../backend/app/audit.py),
[admin_key.py](../backend/app/admin_key.py). **Limits to admit if asked:** the prototype has no user login. During the
pitch every action that changes anything (reset, approve, override, inject, spend AI tokens) needs a shared demo key
(`ADMIN_KEY`, sent as `X-Plan-B-Key`), so a stranger with the URL gets a read-only dashboard; but reading, including
the audit log, stays open, and it is one shared secret, not an identity. CORS allows all origins (production: SSO with
multi-factor authentication, roles, every approval signed with the dispatcher's identity, CORS restricted). The
in-memory buffer keeps the last 2,000 entries and is lost on a restart; Postgres keeps the rest.

### Q13. Could someone attack it through a crew message (prompt injection)?
> A crew message is untrusted text, so we limit what it can do. It is capped at 1,000 characters, Claude can only answer
> in a fixed JSON schema with a fixed list of event types, and the engine rejects any vehicle, place or trip id that does
> not exist. The message parser itself cannot assign a vehicle or approve anything, and in an analysis Claude only has
> read-only tools and a what-if simulator. The worst a hostile message can do in the prototype is report a false event,
> the way a false radio message could; that is in the audit log, and production ties each message to a logged-in crew
> member. One path is longer than before: in Autonomous mode Claude's review of an affected case is applied after the
> engine re-checks it, and the parser's short note about the event can reach that review.

*Proof:* `FieldMessage` (max 1000 characters), `PARSE_SCHEMA`, `to_operator_events` in
[messages.py](../backend/app/agent/messages.py); the tools in [prompts.py](../backend/app/agent/prompts.py). A reported
emergency is dispatched at once by the engine's rules, like a radio call; in Assisted mode (the default) re-assignments
need the dispatcher, in Autonomous mode only what the engine's checks allow is applied, never a unit the dispatcher
chose by hand ([ai_dispatcher.py](../backend/app/ai_dispatcher.py), [approvals.py](../backend/app/approvals.py)).
We have not run a red-team test against the prompts. **[planned]** for authenticated crews.

### Q14. What stops abuse, and what stops a runaway bill?
> Two layers. A demo key: with it set on the server, nothing that changes anything, and so nothing that spends tokens,
> works without it, so someone who only sees the URL gets a read-only dashboard. And one usage guard counts every
> Claude call from every path (analyses, case reviews, crew messages, 112 triage): 12 per rolling five minutes and 300
> per day by default, shared by both worlds and configurable. Over the limit, an operator's analysis falls back to the
> engine's plan with a note, automatic analyses and reviews are skipped, triage uses the keyword rules, and a crew
> message gets an HTTP 429 with a Slovenian and English explanation. Routine calls never start an analysis at all, and
> auto-analyse is off by default. The guard is in memory, so a restart resets it, and the prototype has no per-user
> rate limit yet.

*Proof:* [guard.py](../backend/app/guard.py), [admin_key.py](../backend/app/admin_key.py),
[backend/README.md](../backend/README.md) (live calls: "A generated call never starts an AI analysis"; "Demo lock"),
[DEMO.md](../DEMO.md) (Auto-analyse off by default).

---

## 4. Realism

### Q15. How real is the demo?
> The map, the roads, the traffic colours and the weather are real: OSRM and TomTom routing, TomTom traffic, two
> weather providers. The fleet, the crews, the calls and the GPS positions are simulated: three ambulances, five
> transport vans, a helicopter and two doctor cars at fictional bases, with calls generated at about five an hour.
> Real Ljubljana has twelve emergency ambulance teams, so our absolute numbers describe our model, not the city. There
> is no public hospital-capacity feed, so the capacity numbers in the demo are invented.

*Proof:* [BENCHMARK.md](BENCHMARK.md) (Limits), [DEMO.md](../DEMO.md), [RELIABILITY_AND_SECURITY.md](RELIABILITY_AND_SECURITY.md)
section 1, [GAPS_STATUS.md](GAPS_STATUS.md) row 7. The call rate is `CALLS_PER_HOUR = 5` per world hour in
[config.py](../backend/app/config.py), one call every 12 minutes of world time on average; the Simulation world's clock
runs 5 times faster than real time.

### Q16. Which Slovenian rules did you use?
> Severity follows the Slovenian red and yellow priorities: our critical and serious levels are both red, urgent is
> yellow, and any red call predicted to be reached after 15 minutes raises an alert, the Slovenian reference. Doctor cars
> (VUZ) join red calls that need a doctor, about a quarter of them, in line with the 10 to 30 percent in the dispatch
> service's own plan. For surge we model contracted units that the dispatcher can activate for two hours; the 2024 rule
> that non-urgent providers reserve 20 percent of capacity for emergency dispatch is context for that, and we have only
> seen it reported, not read it.

*Proof:* [DISPATCH_PRIORITIES.md](DISPATCH_PRIORITIES.md) sections 1, 4 and 6 (table of levels, 15-minute reference,
VUZ, surge, Uradni list RS 2024-01-2739 "as reported to us, text not read"). **Say if pressed:** splitting red into
critical and serious comes from UK and MPDS practice because the SloIn NMP text is not public; the 20 percent is not a
parameter in the engine (surge is two ambulances and three vans for two hours, `engine/surge.py`); the 15-minute rule is
an annual average, we flag single calls. The 2026 rulebook itself was **[reported]**, not read ([DATA_FRESHNESS.md](DATA_FRESHNESS.md)).

### Q17. Where do your service times come from?
> Turnout is one minute for ambulances and five for doctor cars, following the Slovenian rule as reported and NFPA 1710.
> Time on scene of 12 to 20 minutes, 25 for cardiac arrest, sits around a published median of 17; the 15-minute handover
> is the Slovenian maximum and the NHS standard; cleaning of 10 minutes is at the low end of published turnarounds.
> The times for transport vans and equipment runs are our assumption, we found no source. All of it is a model built
> from published standards, not measured Ljubljana data.

*Proof:* [SERVICE_TIMES.md](SERVICE_TIMES.md) (values and sources table). The Slovenian figures are from our
teammate's research and the rulebook text was not read by us.

---

## 5. Results

### Q18. What does the benchmark show?
> In 100 simulated eight-hour day shifts with identical calls, Bypass's rules reached 54 percent of critical patients
> within target against 34 percent for plain nearest-free-ambulance dispatch, and 64 against 43 percent of serious
> patients within 18 minutes. The helicopter is modelled as the Brnik service runs it, 13 minutes from call to take-off
> and by day only. With ground units only it is 42.6 against 34.3 percent for critical, and the slowest tenth of
> serious calls actually waits longer, 74 against 67 minutes. It is a simulation with synthetic calls, and the
> baseline is a plain rule, not today's dispatchers.

*Proof:* [BENCHMARK.md](BENCHMARK.md), [results.md](../backend/tools/benchmark_results/results.md). Reproduce with
`cd backend && python tools/benchmark.py`. The one-line stage sentence is at the bottom of BENCHMARK.md.

### Q19. The benchmark has no AI in it. What does the AI add?
> Honestly, the benchmark measures the engine's rules, not Claude. The AI is for what rules cannot list in advance:
> reading a crew's free text, combining several problems at once, explaining trade-offs, and drafting notifications in
> two languages. We have not measured its contribution yet; that is a pilot question, with and without the AI on the
> same events.

*Proof:* [BENCHMARK.md](BENCHMARK.md) Method ("No AI") and Limits.

### Q20. What would you measure in a pilot?
> First in shadow mode: replay a month of an operator's anonymised call and vehicle logs through Bypass with no effect
> on real dispatch. We would compare time to the patient by severity against the 15-minute red reference, the share of
> late transports, and doctor-on-scene times; then in advisory mode on live events, how long it takes from event to an
> approved plan and how often dispatchers change or reject the recommendation, and why. Alongside: AI fallback rate,
> latency and cost per day.

*Proof:* metrics from [BENCHMARK.md](BENCHMARK.md) and [DISPATCH_PRIORITIES.md](DISPATCH_PRIORITIES.md); the shadow-mode
design is our proposal **[planned]**, no replay tool exists yet.

---

## 6. Integration and next steps

### Q21. How would it connect to a real dispatch system, and to real vehicle GPS?
> Every input and output is an API: vehicle positions in, orders and calls in, crew messages in, decisions out; the
> backend already exposes REST endpoints and a live event stream. The first integration would be read-only: take
> the CAD's vehicle positions and orders, show proposals, and write decisions back only later. Positions exist: the
> Slovenian dispatch rulebook requires a GPS transmitter in every ambulance with data reaching dispatch within 10
> seconds; what we need is access. Today the simulator stands in for GPS, and no adapter to a real system exists yet.

*Proof:* [backend/README.md](../backend/README.md) (API table), [DEMO.md](../DEMO.md) (integration answer),
[LJUBLJANA_FLEET_AND_TEAMS.md](LJUBLJANA_FLEET_AND_TEAMS.md) section 3 (rulebook art. 11), [OPERATIONS_DETAILS.md](OPERATIONS_DETAILS.md)
section 6 (status chain a crew reports). Computel's interfaces are not public as far as we found.

### Q22. What about the official traffic data, NAP and promet.si?
> Today traffic comes from TomTom live flow and incidents. The official promet.si events through NAP in DATEX II are
> already coded as a client, but NAP approves each dataset by hand and gave no approval time, so we are waiting. If it
> does not arrive nothing breaks: a time-of-day profile and crew reports are the fallback, and the status bar tells the
> dispatcher which source is live.

*Proof:* [RELIABILITY_AND_SECURITY.md](RELIABILITY_AND_SECURITY.md) section 1 (traffic rows), [DATA_SOURCES.md](DATA_SOURCES.md)
section 5 ("NEEDS APPROVAL", "may not arrive before Sunday 11:00"). **[built]** client, **pending** access.

### Q23. What about mass-casualty incidents, other regions and bigger operators?
> For a busy day we have the surge ladder: a demand alert, mutual aid from a neighbouring station, contracted private
> units for two hours, and the helicopter, all as the dispatcher's decision. A mass-casualty event needs a human to
> declare it, with a first-team report, triage and a hospital distribution key; we researched and designed that, but the
> engine does not implement it yet. Other regions are mostly data, bases, fleet, hospitals and rules, which we expect but
> have not tested; multi-tenant support is not built.

*Proof:* [DISPATCH_PRIORITIES.md](DISPATCH_PRIORITIES.md) section 6, [SURGE_AND_MULTI_SERVICE_COORDINATION.md](SURGE_AND_MULTI_SERVICE_COORDINATION.md)
sections 2 to 4, [AGENTIC_DISPATCH_DESIGN.md](AGENTIC_DISPATCH_DESIGN.md) section 5.4. The backend contains no
mass-casualty code. **[planned]**

---

## 7. Business

### Q24. Who pays, and what do you sell first?
> The first customer is an independent or concessionaire transport provider that runs its own fleet and wants fewer late
> transports and less manual replanning; a per-vehicle monthly subscription, starting with a paid pilot. The second is a
> public dispatch service or hospital operator that wants a replanning layer, as a licence plus integration. We
> are not selling new revenue: emergency teams are paid a fixed amount per team under yearly insurer contracts, so the
> value is better use of the same vehicles and fewer late patients. This plan has not been validated with an operator yet.

*Proof:* [EMS_RESEARCH.md](EMS_RESEARCH.md) section 1 (funding: fixed amount per team), [SURGE_AND_MULTI_SERVICE_COORDINATION.md](SURGE_AND_MULTI_SERVICE_COORDINATION.md)
section 5 (providers, concessions), [BUSINESS_ONE_PAGER.md](BUSINESS_ONE_PAGER.md). Prices there are illustrative.

### Q25. What does it cost to run per day, tokens and hosting?
> As an estimate, about four dollars a day of Claude tokens for a desk like our demo fleet, roughly 115 a month. That
> assumes 20 AI analyses, 60 crew messages and 40 triaged calls a day, with one analysis costing about 15 cents. The
> hard ceiling is the usage guard: 300 Claude calls a day, which is about 44 dollars if every one were a typical analysis.
> The AI dispatcher's Autonomous mode adds a review for every critical or serious call, which this estimate does not
> include. Hosting is separate and we have not priced it: today one small backend and a static frontend; in production two sites,
> a replicated database, and commercial licences for data we use on free tiers in the demo.

**Arithmetic (all of it an estimate; prices in USD).**

*Price:* Claude Sonnet 5.5 (`claude-sonnet-5-5`, the default `AGENT_MODEL`) at Anthropic's list price, **$2 per million
input tokens and $10 per million output tokens** (as listed early November 2026; this price is not in the repo, check it
before quoting). `AGENT_MODEL=claude-opus-5-5` would roughly double it ($4 and $20).

*Sizes measured from this repo's code* (the real request texts built offline for five demo scenarios, no Claude call,
characters not tokens): system prompt 11,158; tool definitions 2,425; output schema 1,771 (together 15,354 characters,
the same in every request); situation brief 5.5k to 10.7k (5 to 12 open trips); one `find_candidates` result 3.5k to 4.6k.
Crew-message parse request about 11.9k; triage request about 2.5k plus the caller's words. Converted at about 3.5
characters per token **[assumption]**, which is deliberately on the high side; the tokenizer was not run.

*One AI analysis, typical (4 requests, each re-sends everything before it):* static 4.4k tokens + situation 1.9k = 6.3k;
request 2 adds a 0.5k assistant turn and two `find_candidates` results of 1.1k = 9.0k; request 3 adds 0.5k and three
`simulate_plan` results = 12.8k; request 4 adds 0.5k and one more result = 14.4k. Input total
6.3 + 9.0 + 12.8 + 14.4 = **42.5k tokens**; output **6k** (thinking, tool calls, final JSON with two or three options
and two-language notifications) **[assumption]**. Cost: 42.5k x $2/M = $0.085, plus 6k x $10/M = $0.060, total
**$0.145, about $0.15**. The `simulate_plan` result size was not measured; 1.1k is an assumption.

*A heavy analysis* (the cap `AGENT_MAX_TURNS` = 10 requests, 3.1k situation): input 10 x 7.5k + 1.6k x (0+1+...+9) =
147k tokens ($0.29) plus 16k output ($0.16) = about **$0.45**.

*A crew message:* 3.4k in ($0.007) + 0.5k out ($0.005) = **$0.012**. *A triaged 112 call:* 0.8k in ($0.002) + 0.25k out
($0.0025) = **$0.004**.

*Typical day* **[assumption]**: 20 analyses = $2.90; 60 messages = $0.71; 40 triaged calls = $0.16; total **$3.78,
about $4 a day, about $115 for 30 days**, or about $10 per vehicle per month for the 11 units of our demo fleet. Grounding
for 20 analyses: at the default 5 calls an hour the simulator shows 2 to 3 red calls over 15 minutes and 1 to 2 late
trips per eight hours ([SERVICE_TIMES.md](SERVICE_TIMES.md)), so 3 to 5 problems per eight hours, 9 to 15 a day, rounded up
to 20. The 40 triaged calls echo the roughly 44 urgent interventions a day at the UKC station in 2025
([OPERATIONS_DETAILS.md](OPERATIONS_DETAILS.md)); the 60 messages are a guess. *Busy day:* 60 analyses, 150 messages,
100 triaged calls = $8.70 + $1.80 + $0.40 = about **$11**. *The demo itself* (one crew message and one analysis) is about **$0.16**.

*Ceiling from the guard* ([guard.py](../backend/app/guard.py): 300 per day): 300 x $0.145 = **$43.50** a day if all were
typical analyses; 300 x $0.45 = **$135** if all were heavy (a theoretical bound: 12 per five minutes would use it up in
about two hours of continuous maximum load). Prompt caching is switched on in the code (`cache_control` in
[runner.py](../backend/app/agent/runner.py)); we ignored it, so real input cost should be lower, not higher, but we have not measured it.

*Hosting and data (not priced):* the demo backend is one process on Railway plus one PostgreSQL for the audit log, the
frontend is static on Vercel; neither plan nor price is recorded in the repo. Production adds a second site and replication
[planned]; a placeholder of a few hundred euros a month for a small two-site setup is an **[assumption]**, not a quote.
Free tiers used in the demo would need commercial terms: TomTom's free plan is for evaluation (2,500 incident requests and
20,000 flow requests a month), Open-Meteo is free for non-commercial use only, the public OSRM server is for light use
only (production: self-hosted OSRM), NAP terms and fees are not stated ([DATA_SOURCES.md](DATA_SOURCES.md),
[config.py](../backend/app/config.py)).

---

## 8. Tough questions

### T1. Isn't letting an AI dispatch dangerous?
> It would be if the AI decided alone. It does not. The rules that act at the moment of a call are deterministic, written
> down and covered by tests: nearest unit by arrival time, a clear-saving override, a helicopter check. Claude reviews
> what the engine did, and its change is only applied if the engine re-checks it, the dispatcher can replace any unit
> at any time and that choice sticks, and by default the AI only proposes. Red-flag words can raise the AI's triage
> level but never lower it, and if the AI is down the engine's decision stands.

*Proof:* [DISPATCH_PRIORITIES.md](DISPATCH_PRIORITIES.md) sections 3 and 8, [triage.py](../backend/app/agent/triage.py)
(the safety net), [RELIABILITY_AND_SECURITY.md](RELIABILITY_AND_SECURITY.md) section 3. Be exact about one thing: in
Autonomous mode (a switch, off by default; it is the demo's mode) Claude's recommended option for a critical or serious
case is applied without a click, through the dispatcher's own re-checked and audited approval path; the 112 call itself
is triaged by Claude or the keyword rules and dispatched by the engine at once, with the call-taker or dispatcher able
to re-grade it.

### T2. Your helicopter numbers look too good.
> You are right to check, and our first run did deserve it: the helicopter sat at UKC, flew at any hour and needed only
> three minutes per leg, and the result was 74 against 35.5 percent. We fixed the model: the helicopter is now based at
> Brnik, needs 13 minutes from the call to take-off (the HNMP average for 2025), 2 to 3 minutes to land, and takes new
> calls only from 08:00 to 16:30. A city call costs it about 22 minutes, so it no longer beats an ambulance in the
> city; it goes to remote and suburban calls, and to city calls only when every ambulance is busy. The re-run gives 54
> against 34 percent for critical calls; with ground units only, as at night or in fog, 43 against 34.

*Proof:* [BENCHMARK.md](BENCHMARK.md) ("What changed", "Where the gain comes from", Limits), `HEMS_ACTIVATION_MIN` and
`HEMS_HOURS` in [hems.py](../backend/app/hems.py), [SERVICE_TIMES.md](SERVICE_TIMES.md) ("Helicopter"),
[EMS_RESEARCH.md](EMS_RESEARCH.md) section 4 (call to take-off 15, 15, 12, 16, 13 min for 2021 to 2025; day only). Using the
helicopter for a city critical call when no ambulance is free follows the MPDS "closest unit" principle and the 2013
guideline's "help when the local team is busy"; the real service is tasked by the dispatch centre and the helicopter
doctor decides. The landing times are our assumption.

### T3. What if the Wi-Fi fails?
> On stage we switch to a phone hotspot; the backend runs in the cloud, so only the devices need internet. In real
> operation the plan is to run the deterministic engine and the last known data on the operator's own servers, so
> dispatching continues without internet and only live feeds and AI suggestions pause. The crew view is a web page that
> needs a connection, so radio stays the backup; the dispatch service itself already keeps a phone app as a backup for
> its radio network.

*Proof:* [DEMO.md](../DEMO.md) ("If something goes wrong"), [RELIABILITY_AND_SECURITY.md](RELIABILITY_AND_SECURITY.md)
section 3 ("Works offline", **[planned]**), [LJUBLJANA_FLEET_AND_TEAMS.md](LJUBLJANA_FLEET_AND_TEAMS.md) section 3
(radio coverage problems, phone app backup). In the prototype the engine runs in the cloud, not locally.

### T4. It is all simulated. Why should we believe any of it?
> Believe the mechanism, not the percentages. The rules come from published Slovenian and international practice, the
> road network, traffic and weather are real, and every plan comes from a simulator you can inspect; but the calls, the fleet
> and the times are a model, and we label them that way everywhere. The way to turn this into evidence is a pilot: replay an
> operator's real, anonymised logs in shadow mode and compare. We would rather show you a conservative simulation than
> invent a result.

*Proof:* [BENCHMARK.md](BENCHMARK.md) (Limits), [SERVICE_TIMES.md](SERVICE_TIMES.md) ("a model built from published
standards, not measured Ljubljana data"), [DISPATCH_PRIORITIES.md](DISPATCH_PRIORITIES.md) ("not medical advice").

### T5. Who is liable if a plan is wrong?
> The dispatcher decides, as today, and in production each approval is signed with their identity in the audit log. Bypass
> is decision support: the medical rules would be the operator's own, in Slovenia the SloIn NMP index and the medical
> director's protocol. Whether software like this counts as a medical device is something we have not assessed, and
> we would settle it with legal advice before any live use.

*Proof:* [DISPATCH_PRIORITIES.md](DISPATCH_PRIORITIES.md) intro, [RELIABILITY_AND_SECURITY.md](RELIABILITY_AND_SECURITY.md)
section 3 (access control). **Unknown:** legal classification, not assessed.

### T6. What if dispatchers just click approve every time?
> That is a real risk, so approval is made hard to do blindly: every option lists, step by step, who goes now or next and
> when, with simulated before and after numbers and a one-sentence clinical reason, and approval is refused if the
> situation has changed. A pilot would measure how often dispatchers change or reject the recommendation, and why; the
> Reports page already counts, per call, whether the engine, Claude or a dispatcher override had the last word.
> Autonomous mode, which applies Claude's recommendation without a click, is off by default and would only be switched
> on in production after that evidence.

*Proof:* [DEMO.md](../DEMO.md) (approving a plan), [backend/README.md](../backend/README.md) (plan steps),
[DISPATCH_PRIORITIES.md](DISPATCH_PRIORITIES.md) section 8, [reports.py](../backend/app/reports.py) (`_ai`, "who decided").
The override-rate measurement on real dispatchers is **[planned]**.

---

## Honest unknowns (say "we have not checked" rather than guess)

- What features Computel NMP 3000 has, and what interfaces it exposes (not public as far as we found).
- What private and concessionaire transport providers use today, and whether any would pilot.
- The text of the 2026 emergency-service rulebook and of the 2024 rule on the 20 % reserve (both **[reported]**; the gazette
  site failed its certificate check for us). The 15-minute handover, status chain and 2-hour replacement-vehicle rule are
  2017 values, not re-verified ([DATA_FRESHNESS.md](DATA_FRESHNESS.md)).
- Whether the software would be regulated as a medical device.
- Real hospital admission capacity, real service times in Ljubljana, hour-of-day demand patterns (none published).
- How well speech recognition works in a moving ambulance with a siren; the design assumes a headset or cab microphone.
- The AI's measured contribution to outcomes, and the real token usage per analysis (our figures are estimates).

## Five key messages (repeat these)

1. **The engine computes every number, the AI reviews and proposes (and, only in Autonomous mode, applies what the engine re-checks), the dispatcher decides and can override anything.**
2. **Every number on the screen comes from a simulator, never from the language model.**
3. **When anything fails, the AI, a data feed or the network, a fallback takes over and the screen says so.**
4. **It is a simulation on real roads and Slovenian rules, labelled as one; a pilot turns it into evidence.**
5. **It sits next to the dispatch centre through APIs, and we start with one independent operator.**
