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
| Feeds | `app/fetchers/` | Live weather (Open-Meteo); traffic (time-of-day profile for now) |

## Run locally

```bash
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt   # macOS/Linux: .venv/bin/python
.venv/Scripts/python.exe -m app                                         # http://localhost:8000/docs
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Per-source freshness (`fresh` / `stale` / `down`) |
| GET | `/state` | Full snapshot: vehicles, trips, places, incidents, weather, alerts, events |
| GET | `/stream` | Server-sent events (SSE): a snapshot on every change, for the frontend |
| GET | `/alerts`, `/kpis` | Current alerts, headline numbers |
| POST | `/events` | Inject an event (see below) |
| POST | `/plans/simulate` | What-if: before/after KPIs and per-trip changes |
| POST | `/plans/apply` | Operator approved: apply the plan |
| POST | `/admin/reset` | Re-seed the simulation |

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
