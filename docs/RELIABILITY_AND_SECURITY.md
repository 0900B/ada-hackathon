# Plan B: reliability and security

A dispatch system must keep working when a data provider, the AI, or a network link fails.
Plan B is built so that **every input has a second source and every step has a fallback**.
The dispatcher always gets an answer and always sees which source it came from.

This page separates what the **prototype already does** (running today on our demo deployment)
from how a **production deployment** for an EMS operator would be set up.

## 1. Every data source has a backup (implemented)

| What | Primary | Backup(s) | If everything fails |
|---|---|---|---|
| Weather | Open-Meteo | MET Norway (api.met.no) | Last known value, marked stale |
| Traffic speed | TomTom Traffic Flow (live) | promet.si / NAP (DATEX II): client built, waiting for access | Time-of-day traffic profile for Ljubljana |
| Traffic incidents and closures | TomTom Incident Details | promet.si / NAP road events | Reports from crews and the dispatcher (voice, text, map click) |
| Road routes and geometry | OSRM | TomTom Routing API | Straight-line distance × road factor (1.35) |
| Detours around closures | TomTom Routing with avoid areas | (none) | Route kept, with the closure's slowdown applied |
| Travel-time matrix | OSRM table (all places in one request) | Cached road routes | Straight-line estimate |
| AI recommendation | Claude Sonnet 5.5 | Anthropic server-side fallback model | Deterministic engine plan (greedy, fully simulated) |
| Traffic map layer | TomTom tiles via our backend | (none) | Transparent tile: the base map keeps working |
| Audit log | PostgreSQL | In-memory buffer, retried with backoff | Never blocks a dispatch action |
| Crew input | Speech (Web Speech API, SL/EN) | Typed text | Quick-status buttons 1–5 |

How it behaves:
- **Nothing waits on a network call.** Decisions use cached data. Fetches run in the background on fixed intervals, and a cache miss falls back to the estimate immediately.
- **Freshness is visible.** The status bar shows each source as `fresh`, `stale` or `down`, and whether the live provider or the fallback is in use (e.g. traffic: "TomTom live" vs "time-of-day profile"). The dispatcher knows when the system is running on backup data.
- **Quotas are protected.** Paid APIs (TomTom) have daily request caps. When a cap is reached, the system switches to the backup and says so; it does not fail.
- **The AI is optional.** Every number shown to the dispatcher (ETAs, delays, late trips) comes from our deterministic engine, never from the language model. Without the AI (no key, outage or refusal), the engine produces its own plan in under a second.

## 2. Security in the prototype (implemented)

- **Keys stay on the server.** API keys (Anthropic, TomTom, NAP) exist only as server environment variables. They are never sent to the browser, never written to logs, and never included in error messages or `/health`. TomTom map tiles are proxied through the backend so the key never reaches the client.
- **No real patient data.** Patients are pseudonymous labels (P-123). The AI only receives IDs, needs (seated/wheelchair/stretcher), places and times.
- **Human in the loop.** The AI can only *propose*. It has read-only tools plus a what-if simulator; it cannot change assignments. Every option is re-simulated by the engine before it is shown, and again when the dispatcher approves; a plan that no longer fits the current situation is rejected with a clear message.
- **Strict validation.** Every event, message and plan is validated against a schema. Unknown vehicles or places are rejected, and AI tool calls use strict JSON schemas.
- **Full audit trail.** Every crew message, interpreted event, AI recommendation and dispatcher decision is stored in PostgreSQL with a timestamp, and can be exported.
- **Live and simulation are separated.** Hypothetical events (invented weather, demo scenarios) can only be injected into the Simulation world. The Live world uses real data only.
- **Cost control.** AI analysis runs on demand (or with an explicit auto-analyse switch per world), so nothing spends tokens in the background.

## 3. Production deployment (planned)

For a real EMS operator, the same software would run like this:

- **Private servers.** Hosted on the operator's own servers, or in a Slovenian/EU sovereign cloud. Patient and operational data stay in the EU (GDPR; health data is a special category).
- **Twice, in two places.** Two independent instances in two separate data centres, active–standby with automatic failover. PostgreSQL uses streaming replication to the standby site, and health checks switch traffic within seconds.
- **Works offline.** The deterministic engine and the last known data run locally. If the internet link or the AI provider is down, dispatching continues; only live feeds and AI suggestions pause.
- **Access control.** Login via the operator's SSO with multi-factor authentication. Roles for dispatcher, crew and administrator, with least privilege. Every approval is signed with the dispatcher's identity in the audit log.
- **Network.** TLS everywhere. Vehicle tablets and phones connect over a VPN or with client certificates (mTLS). The dispatch API is not public: it sits behind a firewall/WAF with rate limiting. CORS is restricted to the operator's own domains (the prototype allows all origins for the demo).
- **Secrets and data.** Keys in a secrets vault with rotation. Encryption at rest for the database and backups, daily off-site backups, and tested restores.
- **AI data protection.** Claude is used through an EU-hosted, zero-data-retention setup, or swapped for another provider. It only receives pseudonymous IDs, never names or medical records. The system stays fully usable with the AI switched off.
- **Monitoring.** Alerts when a data source falls back, a quota runs low, the AI fails or a vehicle stops reporting.
- **Integration stays open.** Every input and output is an API (GPS/AVL feed, orders, crew messages, decisions). Plan B can run on its own for an independent operator, or next to an existing dispatch centre.

## One-liner for the pitch

> "Every data source has a backup: weather from two providers, traffic from TomTom with promet.si and a time-of-day model behind it, routing from OSRM and TomTom. If the AI is down, our engine still plans. In production it runs on private servers, twice, in two data centres, with login, encryption and a full audit trail."
