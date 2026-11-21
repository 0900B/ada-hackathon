# Backend: emergency transport assistant

A live FastAPI service that keeps a constantly updated picture of the fleet. When something
goes wrong, every decision is made from data already in memory; nothing waits on an external API.

## How it works

| Piece | File | What it does |
|---|---|---|
| World state | `app/state.py` | Vehicles, trips, places, incidents, weather, data-source freshness, all in memory |
| Simulator | `app/sim/simulator.py` | Moves vehicles every tick (stand-in for live GPS) |
| Seed data | `app/sim/seed.py` | 8 vehicles, 24 synthetic scheduled trips around Ljubljana |
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
| POST | `/{world}/admin/reset` | Re-seed that world |
| GET/POST | `/sim/admin/scenarios`, `/sim/admin/scenario/{name}` | Demo scenarios (simulation only) |
| POST | `/{world}/agent/analyze` | Ask the Claude agent to review the situation (`{"question": "..."}` optional) |
| GET | `/{world}/agent/runs` | Agent runs, newest first (also in `/state` and `/stream` under `agent`) |
| POST | `/{world}/agent/runs/{id}/approve` | Operator approves an option: `{"option_index": 0}` |
| POST | `/{world}/agent/runs/{id}/reject` | Operator rejects the recommendation |

## The Claude agent (`app/agent/`)

Disruptive events (breakdown, delay, closure, urgent request, snow) start an analysis automatically.
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
```

Example plan:

```json
{"steps": [{"trip_id": "TR-003", "vehicle_id": "T4", "position": 0}], "rationale": "T4 is closest"}
```

## Deploy on Railway

1. New project -> Deploy from GitHub repo -> `ada-hackathon`.
2. Service settings -> **Root Directory** = `/backend`. `railway.json` sets the start command and the `/health` check.
3. Keep **1 replica**: the state lives in memory.
4. Settings -> Networking -> Generate Domain.
5. Optional variables: see `.env.example`.
