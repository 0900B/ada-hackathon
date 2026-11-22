# Bypass: operational metrics

All numbers are from our simulation (synthetic calls and fleet, real roads) or from live runs of the deployed
system with real Claude on 22 Nov 2026. Benchmark details and caveats: [BENCHMARK.md](BENCHMARK.md) (100 simulated
8-hour day shifts, identical calls, Bypass's dispatch rules against nearest-free-ambulance dispatch).

| Metric | Result | Source |
|---|---|---|
| **Time to dispatch** | Rules engine: **< 0.1 s** from the call to units assigned. With Claude's triage of the caller's words first: **2.4–3.4 s** | live runs, timeline `detail` |
| **Response time** | Critical patients within target (8 min city / 15 outside): **53.8 % vs 34.3 %**; median time to a critical patient **8.0 vs 12.4 min**; serious within 18 min **64.4 % vs 43.1 %** | benchmark, normal load |
| **Time to find a feasible reassignment** | Engine recalculation after a disruption: **< 0.1 s**; Claude's check of it: **4–5 s**; a full situation review with 2–3 simulated plans: **16–31 s** (hard limit 60 s) | live runs |
| **Number of disrupted trips** | Every disruption lists the trips it touches (`affected_trip_ids`), each gets a re-plan box; late transports **7.5 % vs 20.5 %** | benchmark, event log |
| **Idle vs utilised vehicle time** | Ambulance utilisation **66.4 % vs 76.6 %** at normal load (**84.8 % vs 91.8 %** at high load): better response with less busy time, because vans take non-urgent work | benchmark |
| **Coverage of geographic areas** | The last free ambulance of an area is kept for red calls when a van can take an urgent one; the 15-min target outside the city is part of the critical metric | dispatch rules |
| **Manual interventions required** | **0** for dispatch and re-dispatch in the benchmark (all automatic); calls never reached **0 vs 30**. The dispatcher only approves trade-offs and can override any unit | benchmark |
| **Performance during demand surges** | High load: critical within target **37.3 % vs 8.4 %**, serious within 18 min **42.8 % vs 18.3 %**, calls never reached **59 vs 265** | benchmark, high load |

Ground units only (night, fog): critical within target 42.6 % vs 34.3 %. The benchmark measures the engine's rules, not Claude.
