# Bypass: AI dispatch co-pilot, business one-pager

AdaHack 2026, Challenge 3 (Epilog). Demo operator: the fictional "Ljubljana Demo EMS". **Tags:** **[S]** read in the original
by our research; **[reported]** from news summaries, original not read; **simulated** from our model, not from Ljubljana;
**[assumption]** our choice; **illustrative** a placeholder to test with buyers, not market data. Backup for each line: [JURY_QA.md](JURY_QA.md).

## Problem

When a vehicle breaks down, a road closes or calls pile up, the dispatcher replans by judgement under time pressure.
- **48,754 interventions in 2025** at the Ljubljana ambulance station, **16,087 life-threatening at dispatch** (+3.8 % on 2024,
  total -1.2 %): about 134 a day, 44 urgent; two thirds were non-urgent transports **[S]** ([OPERATIONS_DETAILS.md](OPERATIONS_DETAILS.md)).
- Since 3 June 2026 red cases must average **15 minutes or less over a year**, dispatch sends the fastest team across provider
  areas, and non-urgent providers must answer in a demand surge **[reported]** ([DATA_FRESHNESS.md](DATA_FRESHNESS.md)).
- The dispatch service's own 2022 plan lists recurring failures: teams not where the contract says, wrong status messages, reserve
  vehicles below quota, ageing fleets, radio gaps **[S]**; it coordinates up to 123 teams ([LJUBLJANA_FLEET_AND_TEAMS.md](LJUBLJANA_FLEET_AND_TEAMS.md), [GAPS_STATUS.md](GAPS_STATUS.md)).
- Long handovers and cleaning eat capacity **[S]**; in our model one cardiac arrest keeps an ambulance busy about 65 minutes (**simulated**, [SERVICE_TIMES.md](SERVICE_TIMES.md)).

## Solution

Every 112 call is dispatched in the second it arrives by our deterministic engine; Claude classifies it in Slovenian and, as the
**AI dispatcher**, reviews each critical or serious case (Autonomous or Assisted mode), and the dispatcher can replace any unit. When
something breaks, a crew member **says it in Slovenian** ("Vozilo je obstalo. Oprema je še v njem."); Claude turns it into a structured
event; the engine simulates complete plans on real roads with live traffic and weather; in about 15 seconds in our rehearsals (hard limit
60 s) the dispatcher sees two or three options with before and after numbers and approves one with a key. **The engine computes every
number, the AI reviews and proposes, the dispatcher decides and can override.** If the AI is down, the engine's decision stands and its own
plan appears within a few seconds. Fleet and calls in the demo are simulated; roads, traffic and weather are real.

## Who benefits

| Who | Gets | Evidence |
|---|---|---|
| Dispatch centres | Fast, consistent replans, audit trail, open APIs | built, simulated |
| Concessionaire and private providers | Fewer late transports (7.5 % against 20.5 %; ground units only 18.5 % against 20.3 %), vans take non-urgent jobs so ambulances stay free for red calls, contracted surge units | simulated |
| Hospitals | Notification drafts, capacity-aware redirect options | drafts only; capacity numbers invented |
| Crews | Speak or tap instead of typing; the approved plan on the phone | built |
| Patients | Critical patients within target 53.8 % against 34.3 %, with the helicopter as it really runs (Brnik, 13 min to take-off, day only); ground units only 42.6 % against 34.3 % ([BENCHMARK.md](BENCHMARK.md)) | simulated |

## How it is different

Replans a whole fleet (every option tested on a copy of the live world, with knock-on delays), not only dispatches. Slovenian in,
Slovenian and English out. The engine owns the numbers and the AI is optional. Slovenian doctrine built in: red and yellow
priorities, the 15-minute reference, doctor cars, contracted surge units ([DISPATCH_PRIORITIES.md](DISPATCH_PRIORITIES.md)). API-first: next to a
dispatch system, not instead of it. We have not seen the feature list of the national dispatch software (Computel NMP 3000) and claim nothing about it.

## Business model (all prices illustrative)

| Option | Who pays | Shape |
|---|---|---|
| Paid pilot | One provider | Fixed fee, **EUR 5,000 for 3 months**: shadow mode on anonymised logs, then advisory mode, measurement report |
| SaaS | Private and concessionaire providers | **EUR 60 per vehicle per month**, minimum 5 vehicles, EU-hosted, AI within a fair-use cap |
| Licence | Public dispatch service or hospital operator | **EUR 2,500 per month per dispatch centre** plus integration days, after a pilot, likely via public procurement |

Emergency teams are paid a fixed amount per team under yearly insurer contracts **[S]** ([EMS_RESEARCH.md](EMS_RESEARCH.md)): we sell better use of
the same vehicles and fewer late patients, not new revenue.

## Running costs (estimates)

- **Claude tokens:** about **$0.15 per AI analysis, $4 a day, $115 a month, $10 per vehicle per month** for our 11-unit demo fleet
  (Sonnet 5.5 list price $2 and $10 per million input and output tokens; request sizes measured from the repo; 20 analyses, 60 crew messages,
  40 triaged calls a day **[assumption]**; arithmetic in [JURY_QA.md](JURY_QA.md) Q25). The usage guard caps it at 300 calls a day, about **$44 a day** at most
  if all were typical analyses. At the illustrative price, tokens are about one sixth of revenue (currencies not converted). The AI
  dispatcher's Autonomous mode adds one review per critical or serious call, which this estimate does not include.
- **Hosting:** demo on Railway (backend) and Vercel (frontend), price not recorded; production two sites plus a replicated database,
  placeholder **a few hundred euros a month** **[assumption]**, no quote.
- **Data:** free tiers used in the demo (TomTom, Open-Meteo, public OSRM) need commercial terms or self-hosting ([DATA_SOURCES.md](DATA_SOURCES.md)).

## Go-to-market

1. **Pilot with one independent or concessionaire provider:** shadow replay of a month of anonymised logs, then advisory mode live. Measure late
   transports, response time against the 15-minute reference, dispatcher override rate, AI fallback rate, cost a day.
2. **More providers**, read-only GPS and order feeds (the dispatch rulebook already requires GPS in every ambulance).
3. **Dispatch service:** proposals next to its system, read-only first; timing follows the dispatch software renewal and the digital-record rollout (all units in 2027 **[reported]**).

## Roadmap

| 3 months | 6 months | 12 months |
|---|---|---|
| Login (SSO, roles), EU hosting and DPIA, persistent state, self-hosted routing, commercial data licences, NAP access; helicopter weather from METAR (fog is reported by hand today); read-only GPS adapter; shadow-replay tool | Advisory pilot live with one provider; two-site failover; measured KPIs and the AI's contribution; second provider | Dispatch-service integration if the pilot supports it; multi-tenant and multi-region; mass-casualty support with a human declaring the event; regulatory review |

## Risks and handling

| Risk | Handling |
|---|---|
| Simulation is not reality; the helicopter's landing times are our assumption | Say so, quote ground-only numbers too, validate on real logs in shadow mode |
| Patient safety, automation bias | Human approval, stale plans refused, the dispatcher can override any unit and it sticks, Autonomous mode off by default, the Reports page counts overrides |
| Health-data protection, regulation (medical device?) | Pseudonymous IDs, EU hosting, DPIA, AI optional, redaction; classification not assessed, legal review before live use |
| Integration access, AI vendor and price | API-first, start with an independent operator; the engine works without AI, one module to swap |
| Prototype limits today: no user login (one shared demo key locks the controls, reading is open), open CORS, in-memory single replica | On the 3-month roadmap |

## The ask (from Epilog and the jury)

- **A pilot partner:** a transport provider or EMS operator, ideally through your network; this plan has not been validated with an operator yet.
- **Data:** anonymised logs (calls, timestamps, vehicle positions and statuses) for shadow replay, a test GPS feed, help with NAP approval.
- **Mentoring:** dispatch practice and the Slovenian rules, data protection, healthcare procurement and software regulation, production hardening.
