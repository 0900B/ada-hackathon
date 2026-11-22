# ER inbound board

A separate dashboard for ER reception staff: who is on the way, how urgent, when they arrive, what the crew has done, and what reception can do about it. It shows only ER-relevant data (no fleet map, fuel, crews or traffic) and reads the same backend data as the dispatch and crew screens.

Data contract: `docs/superpowers/specs/2026-11-22-er-dashboard-api-contract.md`. Backend: `backend/app/clinical/`.

## Run it

```bash
# 1. backend (from backend/), offline demo settings
AGENT_AUTO=0 ROAD_ROUTING=0 CALLS_PER_HOUR=30 python -m app

# 2. demo clinical data: the crew simulator posts triage, vitals, drugs, handover through the public API
python tools/crew_sim.py --world sim

# 3. this app (from er-dashboard/)
npm install
npm run dev          # http://localhost:5174
```

- `?world=sim` (default) or `?world=live` picks the world. The Simulation/Live switch in the header does the same.
- `#TR-003` in the address opens that case.
- `VITE_API_URL` sets the backend address (default `http://localhost:8000` in dev, the Railway URL in a production build). The Railway backend must contain the clinical module, otherwise the page says the board is switched off.
- With the demo lock on (`ADMIN_KEY` set on the server), open the page once with `?key=…`. Reading always works; the three reception actions need the key.

## What it does

- **Grid of cases.** One tile per patient bound for the ER, ordered by arrival time. Click a tile to open a popup with a live map (the ambulance, its route, the patient and the ER; refreshed every 2 s from `GET /{world}/vehicles/{id}`) next to all the case data and the reception actions. Esc or a click outside closes it.
- **Alert sound** (header switch, off until clicked because browsers require it). A new critical alert (cardiac arrest) plays a siren; a new high alert (STEMI, airway, stroke window, vitals out of limits) plays two chimes. Alerts already on screen when the page opens stay silent.
- **Auto-call teams** (header switch, on by default). The dashboard calls the ER teams the backend suggests for each case (its rule table: problem type and key events). Each call is stored with the note "Called automatically: …" and a fixed idempotency key per case and team, so several open dashboards never call a team twice. It is rule-based, not an AI model. A person can still call teams by hand.

## How it works

- `src/api.ts` is the only file that talks to the network. `src/useBoard.ts` polls `GET /{world}/er/board` every 1.5 s and keeps the last good board when a poll fails. To switch to the SSE stream, change that hook only: every frame of `/{world}/stream` carries the same board under `clinical`.
- Reception actions (`acknowledge`, `bay_assigned`, `team_activated`) post to `/{world}/er/cases/{id}/actions`. Suggestions are only suggestions: nothing is sent until a person presses a button.
- Honest-data rules from the design: an assumed level or stage looks different from a recorded one, every vital shows its age, an implausible value is shown and flagged "check this" (never corrected), and the alert thresholds are placeholders that ER staff must set.

## Not done

- English only (stage names are the backend's Slovenian ones with English glosses to confirm).
- No sound or push notification for critical alerts.
