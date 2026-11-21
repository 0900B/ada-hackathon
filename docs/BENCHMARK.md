# Dispatch benchmark: Plan B against plain nearest-ambulance dispatch

How much better does Plan B's dispatch do than the simple rule many dispatch systems start from,
"send the nearest free ambulance"? We ran both on the same simulated calls and compared what
matters to patients: how soon a unit reaches them.

Reproduce: `cd backend && python tools/benchmark.py` (about 4 minutes with 6 worker processes).
Results: [backend/tools/benchmark_results/results.md](../backend/tools/benchmark_results/results.md)
and `results.json`.

## Method

- **Calls:** the live-calls generator of the demo (`backend/app/sim/calls.py`). Emergencies
  (10 % of them critical, the rest serious, with conditions such as cardiac arrest, stroke, major
  trauma) are 38 % of the calls. The rest are urgent field calls (8 %), remote mountain calls (3 %)
  and urgent bookings: transfers, discharges, blood and lab runs. Addresses are spread over the
  city (75 %) and the suburbs (25 %). Each seed gives the same call sequence to both policies.
- **Fleet:** the demo fleet (`backend/app/sim/seed.py`): 3 ambulances, 5 patient-transport vans,
  1 helicopter (at UKC) and 2 doctor cars. Reserve units (mutual aid, private ambulances) are a
  dispatcher's decision and are not used by either policy.
- **Runs:** 100 seeds × 8 world-hours of calls, then up to 3 more hours without new calls so that
  every call can finish. Loads: normal (the demo's default, 5 calls per hour) and high (1.75× that,
  8.75 per hour). A third comparison takes the helicopter out of the fleet for both policies.
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
| Helicopter | Only if no ambulance can take the call | The closest unit for a critical call; for a serious call if ≥ 10 min faster; for an urgent call only far away |
| Urgent calls | Nearest free ambulance or van | A van when no ambulance is free, or when sending the ambulance would leave its area without red cover within 15 min |
| Bookings | Nearest free van, else the van free first | The engine's booking placement (best simulated fit, vans first) |
| Doctor cars | The free doctor car that arrives first (same rule for both) | Same |

Sources: [DISPATCH_PRIORITIES.md](DISPATCH_PRIORITIES.md) for Plan B's rules;
`backend/app/engine/dispatch.py` and `backend/tools/benchmark.py` for the code.

## Results

Time to the patient = from the call (for bookings: the ready time) until a unit reaches the patient.

### Normal load (5 calls per hour)

| Metric | Baseline | Plan B | Difference |
|---|---:|---:|---:|
| Critical calls reached within target (8 min city / 15 outside) | 35.5 % | 74 % | +38.5 pp |
| Critical: median / 90th percentile time to the patient | 10.9 / 45.2 min | 4.8 / 19.6 min | −6.1 / −25.6 min |
| Serious calls reached within 18 min | 44.2 % | 81.5 % | +37.3 pp |
| Serious: median / 90th percentile | 22.5 / 66.8 min | 8.2 / 28.5 min | −14.3 / −38.3 min |
| Urgent calls reached within 60 min | 97.8 % | 98.6 % | +0.8 pp |
| Doctor on scene within 15 min (calls that need one) | 47.6 % | 73.9 % | +26.3 pp |
| Late transports (≥ 5 min after due) | 20.5 % | 5.3 % | −15.2 pp |
| Calls not reached by the end of the run | 29 | 0 | |
| Ambulance utilisation (busy share of the call window) | 76.6 % | 59.7 % | |
| Seeds where Plan B is better / same / worse: serious within 18 min | | | 100 / 0 / 0 |
| ... critical within target | | | 53 / 31 / 1 |

4,568 calls (169 critical, 1,737 serious, 2,662 urgent).

### High load (8.75 calls per hour)

| Metric | Baseline | Plan B | Difference |
|---|---:|---:|---:|
| Critical calls reached within target | 13.7 % | 52.9 % | +39.2 pp |
| Critical: median / 90th percentile | 24.5 / 57.4 min | 8.0 / 27.3 min | −16.5 / −30.1 min |
| Serious calls reached within 18 min | 22.2 % | 53.7 % | +31.5 pp |
| Serious: median / 90th percentile | 47.0 / 94.6 min | 15.4 / 72.6 min | −31.6 / −22.0 min |
| Urgent calls reached within 60 min | 95.1 % | 96.6 % | +1.5 pp |
| Doctor on scene within 15 min | 37.8 % | 58.2 % | +20.4 pp |
| Late transports | 30.9 % | 15.9 % | −15.0 pp |
| Calls not reached by the end of the run | 256 | 46 | |
| Ambulance utilisation | 91.8 % | 81.7 % | |
| Seeds better / same / worse: serious within 18 min | | | 99 / 0 / 1 |
| ... critical within target | | | 59 / 32 / 3 |

6,988 calls (263 critical, 2,669 serious, 4,056 urgent).

### Where the gain comes from: ground units only (normal load, no helicopter for either policy)

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

## What this shows

- **Most of the gain is the helicopter rule.** With the helicopter, Plan B sends it to about a
  quarter of serious calls and a third of critical ones, in the suburbs and wherever it is
  clearly faster. The baseline almost never uses it ("only if no ambulance can take the call").
  Without the helicopter, Plan B still reaches critical patients sooner (median 9.0 vs 11.5 min,
  43 % vs 34 % within target), but the difference for serious calls is small.
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
  numbers, such as "74 % within target", describe this model, not Ljubljana.
- **Straight-line travel.** No real roads, traffic or closures in these runs. Both policies use
  the same model, so the comparison is fair, but real times differ.
- **The baseline is a simple rule, not today's dispatchers.** Human dispatchers already use
  judgement (helicopter, priorities). The baseline is the plain "nearest free ambulance" rule that
  dispatch software starts from.
- **No AI and no reserve units.** The AI's proposals, mutual aid and private ambulances would
  change the numbers. The AI only proposes, and every plan is re-simulated by the engine before a
  dispatcher sees it.
- **The helicopter is always available here.** No weather, crew-rest or daylight limits beyond
  the demo's fog event, which is not used in these runs. A grounded helicopter removes most of
  the gain (see the ground-only table).
- **Doctor cars** use the same rule in both policies, so their numbers follow the ambulance and
  helicopter decisions.

## One sentence that is safe to say on stage

"In 100 simulated 8-hour shifts with identical calls, Plan B's dispatch rules got 74 % of critical
patients reached within the target, against 36 % with nearest-free-ambulance dispatch. Mostly
that's from using the helicopter when it is clearly faster; with ground units alone the gain is
smaller (43 % against 34 %)."
