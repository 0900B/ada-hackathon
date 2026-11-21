# Backend: emergency transport assistant

A live FastAPI service that keeps a constantly updated picture of the fleet. When something
goes wrong, every decision is made from data already in memory; nothing waits on an external API.

## How it works

| Piece | File | What it does |
|---|---|---|
| World state | `app/state.py` | Vehicles, trips, places, incidents, weather, data-source freshness, all in memory |
| Simulator | `app/sim/simulator.py` | Moves vehicles every tick (stand-in for live GPS) |
| Seed data | `app/sim/seed.py` | Places, 9 vehicles, crews; in scheduled-day mode also 24 synthetic scheduled trips + 4 equipment runs |
| Live calls | `app/sim/calls.py` | The call stream of live-calls mode (default), each call dispatched at once |
| Travel model | `app/routing.py` | Distance x road factor, adjusted for traffic, weather and incidents |
| Projection | `app/engine/projection.py` | Predicts every trip's arrival time and delay, including knock-on delays; builds alerts and KPIs |
| Events | `app/engine/events.py` | Breakdown, delay, road closure, urgent request, weather override |
| Plans | `app/engine/plans.py` | Simulates a reassignment plan on a copy (what-if), or applies it |
| Feeds | `app/fetchers/` | Live weather (Open-Meteo, MET Norway fallback). Traffic from several sources, each optional and independent: TomTom flow + incidents (`TOMTOM_API_KEY`), official promet.si/DARS events via NAP in DATEX II (`NAP_USERNAME`/`NAP_PASSWORD`), else a time-of-day profile |

## Run locally

```bash
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt   # macOS/Linux: .venv/bin/python
.venv/Scripts/python.exe -m app                                         # http://localhost:8000/docs
```

## Two worlds: live and sim

The real-world feeds (weather, TomTom traffic and incidents, promet.si) are fetched once and shared.
Two worlds read them:

- **`live`**: real clock, real conditions only. Operators can report real events (breakdown, delay,
  emergency, closure); hypothetical weather and demo scenarios are refused.
- **`sim`**: the presentation sandbox: 5× clock (`SIM_SPEEDUP`), snowstorm override, demo scenarios, reset.

## Operating mode: live calls (default) or a scheduled day

- **Live calls** (default for both worlds): no pre-planned trips; every unit starts idle at its base.
  `app/sim/calls.py` generates calls (`CALLS_PER_HOUR`, default 8 per world hour, exponential gaps of
  2–25 min, its own seeded RNG per world): emergencies at street addresses around Ljubljana (to UKC),
  sometimes a remote one (Kamniška Bistrica, Krvavec, Sava valley: the helicopter), urgent field calls,
  urgent patient transports (health centre or GP referral to UKC, urgent discharges, inter-hospital
  transfers) and urgent equipment runs (blood products, lab samples, a ventilator). Emergencies and field
  calls go through `dispatch_call` (nearest suitable free unit); transports and equipment are booked onto
  a van (`task_request` with `if_late: "soonest"`: if nothing fits on time, the vehicle that delivers it
  least late). Typical load at 8/h: ambulances and vans 45–65 % busy, queues at most current job + 1.
  A generated call never starts an AI analysis; a genuine problem (no unit, or late) may, only with
  auto-analyse on and at most once per 15 world-minutes. Demo scenarios pause new calls for 30 world-minutes.
- **Scheduled day** (`SCHEDULED_DAY=1`, or `POST /{world}/admin/reset {"scheduled_day": true}`): the
  vans start with a pre-planned day of booked trips (the brief's "initial plan"); no random calls.
- The snapshot says which: `mode` (`live_calls` / `scheduled_day`) and `calls` (generator status).
  It sends open trips plus those finished in the last 3 world-hours (everything stays in memory).

## API

`{world}` is `live` or `sim`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Feed freshness, both worlds' clocks, TomTom usage, road-routing cache |
| GET | `/{world}/state` | Full snapshot: vehicles (with road path), trips, places, incidents, weather, alerts, events |
| GET | `/{world}/stream` | Server-sent events (SSE): a snapshot on every change, for the frontend |
| GET | `/{world}/alerts`, `/{world}/kpis` | Current alerts, headline numbers |
| POST | `/{world}/events` | Report/inject an event (see below) |
| POST | `/{world}/plans/simulate` | What-if: before/after KPIs and per-trip changes |
| POST | `/{world}/plans/apply` | Operator approved: apply the plan |
| POST | `/{world}/admin/reset` | Re-seed that world; optional `{"scheduled_day": true\|false}` switches the mode |
| POST | `/{world}/admin/calls` | Live-calls generator: `{"enabled": bool, "per_hour": number}` (both optional) |
| GET/POST | `/sim/admin/scenarios`, `/sim/admin/scenario/{name}` | Demo scenarios (simulation only) |
| POST | `/{world}/agent/analyze` | Ask the Claude agent to review the situation (`{"question": "..."}` optional) |
| GET | `/{world}/agent/runs` | Agent runs, newest first (also in `/state` and `/stream` under `agent`) |
| POST | `/{world}/agent/runs/{id}/approve` | Operator approves an option: `{"option_index": 0}` |
| POST | `/{world}/agent/runs/{id}/reject` | Operator rejects the recommendation |

## The Claude agent (`app/agent/`)

With auto-analyse on (a per-world switch, off by default to save tokens), disruptive events (breakdown,
delay, closure, urgent request, snow) start an analysis automatically; routine live calls never do.
Otherwise the operator presses Analyse (the first one after a demo scenario gets its description).
Claude (`claude-sonnet-5-5` by default; set `AGENT_MODEL=claude-opus-5-5` for Opus) gets the situation, then uses three tools backed by the engine:
`find_candidates` (vehicles ranked by simulated outcome), `simulate_plan` (what-if for a whole option)
and `get_vehicle_schedule`. It returns 2-3 options as structured JSON with a recommendation and
notification drafts in Slovenian and English.

The model proposes; the engine decides the numbers. Every option is re-simulated by the engine before the
operator sees it, so all figures in the UI come from the engine, not the model. If there's no
`ANTHROPIC_API_KEY`, or Claude fails or declines, the engine's own greedy plan is shown instead.

Settings: `ANTHROPIC_API_KEY` (required for Claude), `AGENT_MODEL`, `AGENT_EFFORT` (default `medium`),
`AGENT_AUTO` (`1`/`0`), `AGENT_MAX_TURNS`, `AGENT_TIMEOUT_S`.

Example events:

```json
{"type": "breakdown", "vehicle_id": "T1", "note": "flat tyre"}
{"type": "delay", "vehicle_id": "T3", "minutes": 20}
{"type": "road_closure", "lat": 46.0563, "lon": 14.5232, "radius_m": 500, "description": "Closure near UKC"}
{"type": "urgent_request", "pickup_id": "home_polje", "priority": "emergency"}
{"type": "urgent_request", "lat": 46.05, "lon": 14.50, "priority": "emergency"}
{"type": "weather_override", "snowfall_cm": 2}
{"type": "weather_override", "clear": true}
{"type": "priority_change", "trip_id": "TR-007", "priority": "emergency"}
{"type": "hospital_capacity", "place_id": "ukc", "capacity": 2}
{"type": "hospital_capacity", "place_id": "ukc", "capacity": null}
```

- **Equipment transport** (`kind: "equipment"`, `needs: "equipment"`, `cargo`): no patient; vans
  (and, if needed, ambulances) carry it, never the helicopter. If the vehicle breaks down with it on board, another vehicle must collect it
  at the breakdown site first.
- **Priority change**: raised to emergency = collect now, due-by at most direct ambulance time + 5 + 20 min
  (urgent: + 60 min from the ready time); deadlines are never loosened. A vehicle that can no longer
  serve the trip (a van for an emergency) loses it, and the engine dispatches an ambulance at once;
  on an ambulance it moves to the front. Trips on board keep their vehicle.

Severity and dispatch doctrine (`engine/severity.py`, `engine/dispatch.py`, rules and sources in
`docs/DISPATCH_PRIORITIES.md`):
- Every trip has `severity` (`critical` | `serious` | `urgent` | `routine`; priority emergency =
  critical or serious), `condition` (`cardiac_arrest`, `choking`, `catastrophic_bleeding`,
  `anaphylaxis`, `stroke`, `stemi`, `breathing_difficulty`, `major_trauma`, `seizure`, `sepsis`,
  `fracture`, `fall`, `transfer`, `equipment`; `breathing` is accepted as an alias), `condition_label`,
  `modifiers` (`child`, `multiple_patients`, `deteriorating`, `late_stroke_window`, `no_bystander_cpr`),
  `response_target_min` (critical 8 in the city / 15 outside, serious 18, urgent 60) and `time_weight`
  (condition weight + modifiers). Response time runs from `pickup_after` (= the call time for
  emergency and urgent calls) to `eta_pickup`. `urgent_request` and `task_request` accept optional
  `severity`, `condition`, `modifiers`; `priority_change` accepts `severity` (also critical ↔ serious,
  which keeps priority "emergency") and `condition`; raising a level re-evaluates the dispatch.
- New calls are dispatched at once (`dispatch_call`): closest unit by true arrival incl. one finishing
  a drop-off nearby (3 min margin); a critical/serious call may override a lower-level call en route
  (3 / 5 min saved, displaced call re-dispatched within its target, never displaced twice); never with a
  patient on board, on scene or within 2 min; helicopter: closest for critical, 10 min faster for
  serious, remote 15 min for urgent; stroke/STEMI judged by arrival at UKC. Same-level swaps are only
  proposed (`swap_options`: engine-fallback options and `proposed_swaps` in the agent's situation).
  The event summary says who, why, when, the helicopter check and the clinical reason.
- Slovenian practice: a red call predicted over 15 min raises `red_response_over_15_min`; the last free
  ambulance of an area is kept for red calls (a van takes the non-urgent call).
- **Doctor cars** D1 (base `zd_center`) and D2 (`zd_siska`), `type: "doctor"` (VUZ: physician + nurse;
  `engine/doctors.py`). Red calls whose condition is `cardiac_arrest`, `choking`, `catastrophic_bleeding`,
  `anaphylaxis`, `stemi`, `breathing_difficulty` or `major_trauma` get `needs_doctor: true` and
  `doctor_target_min: 15` (set by the backend on every trip). The engine sends the ambulance by the rules
  above plus the free doctor car that reaches the scene first (never one on a scene); the trip gets
  `doctor_vehicle_id` and `doctor_eta` (projected while driving, the actual arrival once there); the
  summary says `+ doctor D1 (Rudnik, at the patient 22:45, 5 min after the ambulance)`. The helicopter
  has a doctor on board (`doctor_vehicle_id: "H1"`), unless it is over 15 min and a doctor car is
  sooner (that car stands down when H1 lifts off). Doctor-car statuses: `to_pickup` = to the scene,
  `loading` = on scene with the crew, `with_patient` = escorting to hospital, then `returning`;
  `current_trip_id` = the supported trip; `trip.vehicle_id` stays the ambulance. A doctor car never
  transports and is never a plan step. No doctor within the target: alert `doctor_response_over_15_min`.
- **Reserve units** M1 (ambulance, `origin: "mutual_aid"`, base `base_domzale`) and P1 (`origin:
  "private"`, base `base_private`) are not in the snapshot until requested. When no own unit reaches a
  red call within 15 min, the summary says so, `find_candidates` (agent tool) and the engine fallback
  offer them ("Request mutual aid: M1 from Domžale, at the patient HH:MM", "Private ambulance P1
  (Brezovica), ..."); approving such a plan step activates the unit, and it leaves again once home.
- **Vans** do the scheduled day (seated, wheelchair, stretcher, equipment) and urgent non-emergencies;
  never emergencies. Bookings (`task_request`) go to a van; a free ambulance only if no van fits.

Plan steps: a critical or serious call goes first (before lower levels; the vehicle turns around if
needed); nothing is queued ahead of a higher level; a vehicle is turned away from a same-level call
only by an explicit step (a swap). When the engine checks an option it
stores the steps anchored (`before_trip_id`) plus `step_details` (what each step does); approving
replays exactly that order and is refused (409, with the reason) if it is now clearly worse than shown.
- **Hospital capacity**: admissions the hospital can still take (each delivered patient uses one;
  `null` = unlimited). Over capacity, the most urgent incoming patients keep their place and the
  rest raise a `hospital_over_capacity` alert and the `over_capacity` KPI until redirected.

Example plan:

```json
{"steps": [{"trip_id": "TR-003", "vehicle_id": "T4", "position": 0}], "rationale": "T4 is closest"}
```

Redirect a patient to another general hospital with free capacity (same vehicle, `position: null`
keeps its place in the queue, also with the patient on board):

```json
{"steps": [{"trip_id": "TR-011", "vehicle_id": "T4", "position": null, "dropoff_id": "sb_trbovlje"}]}
```

## Deploy on Railway

1. New project -> Deploy from GitHub repo -> `ada-hackathon`.
2. Service settings -> **Root Directory** = `/backend`. `railway.json` sets the start command and the `/health` check.
3. Keep **1 replica**: the state lives in memory.
4. Settings -> Networking -> Generate Domain.
5. Optional variables: see `.env.example`.
