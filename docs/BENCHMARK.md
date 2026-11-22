# Dispatch benchmark: Plan B against plain nearest-ambulance dispatch

How much better does Plan B's dispatch do than the simple rule many dispatch systems start from,
"send the nearest free ambulance"? We ran both on the same simulated calls and compared what
matters to patients: how soon a unit reaches them.

Reproduce: `cd backend && python tools/benchmark.py` (about 3 to 4 minutes with 6 to 8 worker processes).
Results: [backend/tools/benchmark_results/results.md](../backend/tools/benchmark_results/results.md)
and `results.json`.

## Method

- **Calls:** the live-calls generator of the demo (`backend/app/sim/calls.py`). Emergencies
  (10 % of them critical, the rest serious, with conditions such as cardiac arrest, stroke, major
  trauma) are 38 % of the calls. The rest are urgent field calls (8 %), remote mountain calls (3 %)
  and urgent bookings: transfers, discharges, blood and lab runs. Addresses are spread over the
  city (75 %) and the suburbs (25 %). Each seed gives the same call sequence to both policies.
- **Fleet:** the demo fleet (`backend/app/sim/seed.py`): 3 ambulances, 5 patient-transport vans,
  1 helicopter and 2 doctor cars. The helicopter is the real service's (`backend/app/hems.py`,
  [SERVICE_TIMES.md](SERVICE_TIMES.md) "Helicopter"): based at **Brnik** (Ljubljana airport),
  **13 minutes from the call to take-off** (the HNMP average), 200 km/h, 2 to 3 minutes to land,
  new calls only **08:00 to 16:30**. Reserve units (mutual aid, private ambulances) are a
  dispatcher's decision and are not used by either policy.
- **Runs:** 100 seeds × 8 world-hours of calls, then up to 3 more hours without new calls so that
  every call can finish. Every run is a **day shift**: calls from 08:00 to 16:00 local, inside the
  helicopter's hours (at night the helicopter takes no calls, so the ground-only table applies).
  Loads: normal (the demo's default, 5 calls per hour) and high (1.75× that, 8.75 per hour). A third
  comparison takes the helicopter out of the fleet for both policies.
- **Travel:** `ROAD_ROUTING=0`, straight-line distances with the city's speed model (lights and
  sirens for emergencies), and the same service times (turnout, on scene, handover) for both
  policies. This is fast and deterministic; road routing is not used.
- **No AI.** The AI dispatcher (Claude) is not in the loop. Plan B here is the engine's own
  rules, which apply at the moment a call comes in. The AI's options and swaps would come on top,
  only when a dispatcher approves them.

### The two policies

| | Baseline: a simple CAD rule | Plan B: the engine's dispatch rules |
|---|---|---|
| Who goes | The nearest free suitable unit by arrival time at the moment of the call | The earliest arrival at the patient among free units, units available soon (finishing a drop-off nearby), and units it may divert; for stroke and heart attack, the earliest arrival at UKC |
| Nothing free | The unit that becomes free first: first come, first served (the only ordering is emergency before other work) | A busy unit only if it beats the best free one by 3 min |
| Higher level first | No | A unit driving to a lower-level call can be diverted (≥ 3 min saved for critical, ≥ 5 for serious); the displaced call is re-dispatched and must still be reached within its own target; never displaced twice |
| Helicopter | Only if no ambulance can take the call | The closest unit for a critical call; for a serious call if ≥ 10 min faster; for an urgent call only far away (both with its real activation time and hours) |
| Urgent calls | Nearest free ambulance or van | A van when no ambulance is free, or when sending the ambulance would leave its area without red cover within 15 min |
| Bookings | Nearest free van, else the van free first | The engine's booking placement (best simulated fit, vans first) |
| Doctor cars | The free doctor car that arrives first (same rule for both) | Same |

Sources: [DISPATCH_PRIORITIES.md](DISPATCH_PRIORITIES.md) for Plan B's rules;
`backend/app/engine/dispatch.py` and `backend/tools/benchmark.py` for the code.

## Results

Time to the patient = from the call (for bookings: the ready time) until a unit reaches the patient.
Generated 22 Nov 2026 with the realistic helicopter (see "What changed" below for the earlier run).

### Normal load (5 calls per hour)

| Metric | Baseline | Plan B | Difference |
|---|---:|---:|---:|
| Critical calls reached within target (8 min city / 15 outside) | 34.3 % | 53.8 % | +19.5 pp |
| Critical: median / 90th percentile time to the patient | 12.4 / 45.2 min | 8.0 / 22.4 min | −4.4 / −22.8 min |
| Serious calls reached within 18 min | 43.1 % | 64.4 % | +21.3 pp |
| Serious: median / 90th percentile | 22.8 / 67.6 min | 11.8 / 35.0 min | −11.0 / −32.6 min |
| Urgent calls reached within 60 min | 97.8 % | 98.5 % | +0.7 pp |
| Doctor on scene within 15 min (calls that need one) | 46.4 % | 52.0 % | +5.6 pp |
| Late transports (≥ 5 min after due) | 20.5 % | 7.5 % | −13.0 pp |
| Calls not reached by the end of the run | 30 | 0 | |
| Ambulance utilisation (busy share of the call window) | 76.6 % | 66.4 % | |
| Critical / serious calls served by the helicopter | 1.8 / 1.6 % | 17.2 / 16.8 % | |
| Seeds where Plan B is better / same / worse: serious within 18 min | | | 83 / 16 / 1 |
| ... critical within target | | | 30 / 54 / 1 |

4,568 calls (169 critical, 1,737 serious, 2,662 urgent).

### High load (8.75 calls per hour)

| Metric | Baseline | Plan B | Difference |
|---|---:|---:|---:|
| Critical calls reached within target | 8.4 % | 37.3 % | +28.9 pp |
| Critical: median / 90th percentile | 24.4 / 58.1 min | 10.2 / 26.5 min | −14.2 / −31.6 min |
| Serious calls reached within 18 min | 18.3 % | 42.8 % | +24.5 pp |
| Serious: median / 90th percentile | 47.8 / 94.8 min | 20.5 / 77.1 min | −27.3 / −17.7 min |
| Urgent calls reached within 60 min | 95.1 % | 96.3 % | +1.2 pp |
| Doctor on scene within 15 min | 33.7 % | 48.5 % | +14.8 pp |
| Late transports | 31.0 % | 17.1 % | −13.9 pp |
| Calls not reached by the end of the run | 265 | 59 | |
| Ambulance utilisation | 91.8 % | 84.8 % | |
| Critical / serious calls served by the helicopter | 7.2 / 8.8 % | 25.5 / 22.4 % | |
| Seeds better / same / worse: serious within 18 min | | | 96 / 4 / 0 |
| ... critical within target | | | 53 / 38 / 3 |

6,988 calls (263 critical, 2,669 serious, 4,056 urgent).

### Where the gain comes from: ground units only (normal load, no helicopter for either policy)

Unchanged by the helicopter model (no helicopter in these runs):

| Metric | Baseline | Plan B | Difference |
|---|---:|---:|---:|
| Critical calls reached within target | 34.3 % | 42.6 % | +8.3 pp |
| Critical: median / 90th percentile | 11.5 / 46.4 min | 9.0 / 33.9 min | −2.5 / −12.5 min |
| Serious calls reached within 18 min | 43.1 % | 45.5 % | +2.4 pp |
| Serious: median / 90th percentile | 23.0 / 67.0 min | 20.2 / 74.4 min | −2.8 / **+7.4 min (worse)** |
| Doctor on scene within 15 min | 46.6 % | 48.7 % | +2.1 pp |
| Late transports | 20.3 % | 18.5 % | −1.8 pp |
| Calls not reached by the end of the run | 60 | 36 | |
| Seeds better / same / worse: serious within 18 min | | | 43 / 47 / 10 |
| ... critical within target | | | 16 / 67 / 2 |

## What changed: a realistic helicopter (22 Nov 2026)

The first run (21 Nov) had a helicopter that sat at UKC, flew at any hour and needed only 3 minutes
of take-off and landing per leg. Plan B sent it to about a third of the critical calls, even in the
city, and most of the gain came from that. A jury from the service would rightly challenge it. The
helicopter now follows the team's research ([EMS_RESEARCH.md](EMS_RESEARCH.md) section 4,
[SERVICE_TIMES.md](SERVICE_TIMES.md) "Helicopter"): based at Brnik, 13 minutes from the call to
take-off (HNMP average 2025; 12 to 16 minutes in 2021 to 2025), 3 minutes to land at the scene and 2 on
a helipad, new calls 08:00 to 16:30. A city call now costs it about 22 minutes; the remote valley of
Kamniška Bistrica about 20 (45 by road). The runs also start at a fixed 08:00 (a day shift) so they
are reproducible.

| Normal load, Plan B against the baseline | Before (helicopter at UKC, 3 min overhead) | Now (Brnik, 13 min to take-off, by day) |
|---|---:|---:|
| Critical calls within target | 74 % vs 35.5 % (+38.5 pp) | **53.8 % vs 34.3 % (+19.5 pp)** |
| Critical: median time to the patient | 4.8 vs 10.9 min | 8.0 vs 12.4 min |
| Serious calls within 18 min | 81.5 % vs 44.2 % (+37.3 pp) | **64.4 % vs 43.1 % (+21.3 pp)** |
| Serious: median time to the patient | 8.2 vs 22.5 min | 11.8 vs 22.8 min |
| Doctor on scene within 15 min | 73.9 % vs 47.6 % | 52.0 % vs 46.4 % |
| Late transports | 5.3 % vs 20.5 % | 7.5 % vs 20.5 % |
| Red calls served by the helicopter (Plan B) | about a third of critical, a quarter of serious | 17 % of critical and of serious |
| Ground units only (critical within target) | 42.6 % vs 34.3 % | 42.6 % vs 34.3 % (unchanged) |

The gain roughly halved, and the part due to the helicopter is now about the same size as the part
due to the ground rules (critical within target: +8.3 pp from the ground rules, +11.2 pp more with
the helicopter). The doctor metric fell most: from rest the helicopter can no longer bring its doctor
within 15 minutes (13 minutes to take off alone).

**Where the helicopter goes now** (Plan B, 25 seeds, normal load, 78 of 461 red calls): about 40 %
remote calls (20 km or more from UKC), a third in the suburbs, and the rest in the city, which, with
one exception, only when no ambulance was free at that moment, the indication "help when the local
team is busy" of the 2013 activation guideline ([EMS_RESEARCH.md](EMS_RESEARCH.md) section 4).

## What this shows

- **The gain is real without the helicopter, and the helicopter adds about as much again.** With
  ground units only, Plan B reaches 42.6 % of critical patients within target against 34.3 %. With
  the realistic helicopter it reaches 53.8 %; serious calls within 18 minutes go from 45.5 % (ground
  only) to 64.4 %. The baseline uses the helicopter only when no ambulance can take the call.
- **The helicopter rule no longer wins city calls.** 13 minutes to take off at Brnik put it behind
  any free ambulance in the city; it goes to remote calls, the suburbs, and city calls when every
  ambulance is busy.
- **The ground rules help the most urgent calls at a cost in the tail.** Diverting a unit from a
  lower-level call and preferring a unit that is available soon bring critical patients forward.
  Without the helicopter, the slowest tenth of serious calls waits longer (90th percentile 74 vs
  67 min), because displaced and queued calls wait more. This is the trade-off the doctrine
  chooses (higher level first). We report it rather than hide it.
- **Urgent calls and bookings** are about the same in both. Plan B's van-first rule keeps
  ambulances free for red calls without delaying urgent work.
- **Lower ambulance utilisation** in the full comparison means the helicopter and the vans did
  work the ambulances would otherwise have done. It is not a quality measure in itself.

## Limits (read before quoting)

- **A simulation.** Synthetic calls with a synthetic mix, a small demo fleet (3 ambulances,
  1 helicopter) and fictional bases. Real Ljubljana has more units (12 NRV teams). Absolute
  numbers, such as "54 % within target", describe this model, not Ljubljana.
- **Straight-line travel.** No real roads, traffic or closures in these runs. Both policies use
  the same model, so the comparison is fair, but real times differ.
- **The baseline is a simple rule, not today's dispatchers.** Human dispatchers already use
  judgement (helicopter, priorities). The baseline is the plain "nearest free ambulance" rule that
  dispatch software starts from.
- **No AI and no reserve units.** The AI's proposals, mutual aid and private ambulances would
  change the numbers. The AI only proposes, and every plan is re-simulated by the engine before a
  dispatcher sees it.
- **A day shift, no weather.** The runs fall inside the helicopter's hours and never use the fog
  event. At night, in fog or snow (fog on a fifth to a quarter of days at Brnik) there is no
  helicopter: then the ground-only table applies. The landing times are our assumption; the
  activation time is the service's 2025 average (one value, not a distribution). Plan B also uses
  the helicopter for city calls when every ambulance is busy, which follows the "closest unit"
  principle; the real service is tasked by the dispatch centre and the helicopter doctor decides.
- **Doctor cars** use the same rule in both policies, so their numbers follow the ambulance and
  helicopter decisions.

## One sentence that is safe to say on stage

"In 100 simulated 8-hour day shifts with identical calls, Plan B's dispatch rules reached 54 % of
critical patients within the target, against 34 % with nearest-free-ambulance dispatch. That counts
the helicopter as it really runs, 13 minutes to take off from Brnik and by day only; with ground units
alone it is 43 % against 34 %."
