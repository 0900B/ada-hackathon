# Plan B: reliability and security

A dispatch system must keep working when a data provider, the AI, or a network link fails.
Plan B is built so that **every input has a second source and every step has a fallback**.
The dispatcher always gets an answer and always sees which source it came from.

This page separates what the **prototype already does** (running today on our demo deployment)
from how a **production deployment** for an EMS operator would be set up. It also says plainly what
data leaves the system today (section 2): the prototype uses only synthetic data, but its design is
not yet privacy-safe for real calls, and that is the first thing a production deployment must change.

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
| 112 call triage | Claude (12 s deadline) | Keyword rules (Slovenian and English stems) | A call is never lost |
| AI dispatcher review of a case | Claude (60 s deadline) | none needed: the engine has already dispatched | The engine's decision stands, and the case timeline says so |
| Traffic map layer | TomTom tiles via our backend | (none) | Transparent tile: the base map keeps working |
| Audit log | PostgreSQL | In-memory buffer, retried with backoff | Never blocks a dispatch action |
| Crew input | Speech (Web Speech API, SL/EN) | Typed text | Quick-status buttons 1–5 on the crew phone (1–4 fall back to a plain event when the AI cannot be reached) |

How it behaves:
- **Nothing waits on a network call.** Decisions use cached data. Fetches run in the background on fixed intervals, and a cache miss falls back to the estimate immediately.
- **The engine acts first, the AI reviews.** A 112 call is dispatched by the deterministic engine the moment it arrives (and re-dispatched at once when a unit breaks down). Claude's review of a critical or serious case comes afterwards; if Claude is slow, limited or down, nothing is delayed.
- **Freshness is visible.** The status bar shows each source as `fresh`, `stale` or `down`, and whether the live provider or the fallback is in use (e.g. traffic: "TomTom live" vs "profile"). The dispatcher knows when the system is running on backup data.
- **Quotas are protected.** Paid APIs (TomTom) have daily request caps. When a cap is reached, the system switches to the backup and says so; it does not fail.
- **The AI is optional.** Every number shown to the dispatcher (ETAs, delays, late trips) comes from our deterministic engine, never from the language model. Without the AI (no key, outage, refusal, usage limit or the 60 s deadline), the engine produces its own plan, labelled "Engine only". It is computed locally and needs no network call; it took about 4 seconds for a stranded-equipment scenario in a local check without a key (it can be a few seconds longer in a busy scenario), not instantly.
- **`/health` shows the state of all of this:** feed freshness, the Claude usage guard, the audit log's database status, whether the demo lock is configured (`admin_lock`), and the TomTom and tile budgets.

## 2. What leaves the system: data protection in the prototype

The prototype's fleet, crews and calls are synthetic, and nobody should type real patient data into it.
Read this section as "what a real call would expose today", not as a claim of GDPR compliance.

| Path | What is sent | To whom | Personal data it could carry |
|---|---|---|---|
| **112 call triage** (a call typed or dictated into the "New 112 call" form) | The caller's words and the address as typed, nothing else (`triage_claude` in `app/agent/triage.py`) | Claude, through the Anthropic API | Yes: free text. A real caller's words can contain names, addresses and health information |
| **AI dispatcher review and situation review** (every analysis) | The fleet and the open cases: vehicle IDs, status, nearest place names; for each case a pseudonymous patient label (P-123), severity, condition, needs, times and place names, which for a 112 call means the address as typed, and the case note, which for a 112 call is the caller's words (translated into English by Claude, or as typed; at most 200 characters) (`app/agent/context.py`) | Claude | The address and the caller's words, again |
| **Field messages** (crew or dispatcher, spoken or typed) | The message text (at most 1,000 characters) with a context of vehicle IDs, status and nearest place, the places, and the open cases' IDs, labels, severity, condition and status (`build_context` in `app/agent/messages.py`) | Claude | Whatever the sender says |
| **Speech input** (the mic buttons) | The audio, recognised by **Chrome's Web Speech API, which sends it to Google's servers** (a browser service we do not control; it needs a network connection). The recognised text then follows the paths above | Google (Chrome) | Voices and everything said |
| **Road routes** | Coordinates of the legs to route: vehicle positions, pickup and drop-off points. For a 112 call the pickup is the patient's location | OSRM (the public demo server by default), and TomTom for backup routes and detours | A location, without a name |
| **Audit log** | Every event, call record (including the caller's name if one was typed, the address and the words), field message, AI recommendation and dispatcher decision | PostgreSQL on Railway (memory only if `DATABASE_URL` is not set) | Yes: the same free text, stored and exportable |

**Never sent to Claude:** the caller's name (it stays in the call record and the audit log), crew names,
phone numbers, the call ID, any medical record or patient name (the prototype has none: patients are
labels), the audit log, and the API keys. We checked this against the code that builds each request;
an operator must still treat the free-text fields as the exception: whatever a call-taker types into
"what the caller says" reaches Claude.

**What would change in production** (all planned, none built):
- **Claude under a data-processing agreement, in an EU region, with zero data retention**, or an EU-hosted or on-premises model. We have not verified any provider's current residency or retention terms; they must be settled before real calls.
- **Redaction of free text before it leaves the building** (names, phone numbers, street numbers where the district is enough), or keyword-rule triage only for the most sensitive calls. The system stays fully usable with the AI off.
- **Speech-to-text inside the EU or on the operator's own servers** instead of Chrome's Google service, or a call-taker's headset with an on-premises recogniser.
- **Self-hosted routing:** an OSRM server of our own, so no patient location goes to a public service.
- **A data-protection impact assessment, retention and deletion rules for the audit log**, encryption at rest, and pseudonymised audit payloads. Health data is a special category under the GDPR.
- Whether software like this counts as a medical device has not been assessed; see [JURY_QA.md](JURY_QA.md) T5.

## 3. Security in the prototype (implemented)

- **Keys stay on the server.** API keys (Anthropic, TomTom, NAP) exist only as server environment variables. They are never sent to the browser, never written to logs, and never included in error messages or `/health`. TomTom map tiles are proxied through the backend so the key never reaches the client.
- **Demo lock (the admin key).** With `ADMIN_KEY` set on the backend, every POST, PUT, PATCH and DELETE must carry the header `X-Plan-B-Key`; without it the answer is `401`. That covers everything that changes anything: reset, scenarios, injecting failures, typing a call, crew messages, approving a plan, overriding a unit, switching the AI mode, and spending Claude tokens. Our own devices open once with `?key=…`, store it on that device and show "Control unlocked"; anyone else sees "View only" (`app/admin_key.py`, `frontend/src/adminKey.ts`). The key is compared in constant time and is never logged, echoed or put in `/health`, which only says whether a lock is configured. **What it is not:** one shared secret, not a login. There is no identity, no per-person audit entry, no expiry and no rate limit per user, and **reading stays open**: anyone with the URL can see the dashboard state, the live stream and the audit log. It exists so that a URL on a projector cannot be used to reset the simulation or run up the AI bill during the pitch. Without `ADMIN_KEY` there is no lock at all (local development, tests and CI).
- **Claude usage guard.** One in-memory limiter counts every call to Claude from every path (analyses, the AI dispatcher's reviews, crew messages, 112 triage) for both worlds: at most 12 per rolling 5 minutes and 300 per UTC day by default (`CLAUDE_MAX_PER_5MIN`, `CLAUDE_WINDOW_S`, `CLAUDE_MAX_PER_DAY`; `app/guard.py`). Over the limit: an operator's analysis falls back to the engine's plan with a note, automatic analyses and reviews are skipped and the case timeline says so, 112 triage uses the keyword rules, and a crew message gets HTTP 429 with a Slovenian and English explanation. The counts reset on a restart and are not per user.
- **Human in the loop, and an AI dispatcher with limits.** In Assisted mode (the default) the AI only proposes. In Autonomous mode Claude's recommended option is applied for a critical or serious 112 case, but only through the dispatcher's own approval path: the engine re-simulates and re-checks it, refuses it with a reason if it is infeasible or if the situation changed, logs it as "AI", and audits it. Contracted surge capacity is never activated automatically. A unit the dispatcher assigned by hand sticks: neither the engine's follow-up nor the AI changes it (only a breakdown or fog does, and then the engine replaces it at once). Claude has read-only tools and a what-if simulator and cannot change assignments directly. Every option is re-simulated by the engine before it is shown and again when it is approved.
- **Strict validation.** Every event, message and plan is validated against a schema. Unknown vehicles or places are rejected, and AI tool calls use strict JSON schemas.
- **Full audit trail.** Every crew message, interpreted event, 112 call and triage, AI recommendation, plan applied, dispatcher decision and override, and switch of the AI mode is recorded with a timestamp (in PostgreSQL when `DATABASE_URL` is set), shown on the Audit page and exportable as JSON lines. Each case also has its own timeline of who did what (caller, rules, engine, Claude, dispatcher, crew).
- **Live and simulation are separated.** Hypothetical events (invented weather, demo scenarios, random calls and failures) can only be injected into the Simulation world. The Live world uses real data feeds only.
- **Cost control.** Auto-analyse is off by default, a routine call never starts an analysis, and the guard above caps everything else. In Autonomous mode Claude also reviews every critical or serious call and every disruption of an open call in the background, which costs tokens; those reviews go through the same guard.
- **Known gaps.** No user login or roles. CORS allows all origins (the frontend and backend run on different domains for the demo). The in-memory state, the usage counters and the reports history are lost on a restart (only the audit log persists, and only with a database). The audit log holds free text and is readable without the key. The prompts have not been red-teamed.

## 4. Production deployment (planned)

For a real EMS operator, the same software would run like this:

- **Private servers.** Hosted on the operator's own servers, or in a Slovenian/EU sovereign cloud. Patient and operational data stay in the EU (GDPR; health data is a special category).
- **Twice, in two places.** Two independent instances in two separate data centres, active–standby with automatic failover. PostgreSQL uses streaming replication to the standby site, and health checks switch traffic within seconds.
- **Works offline.** The deterministic engine and the last known data run locally. If the internet link or the AI provider is down, dispatching continues; only live feeds and AI suggestions pause.
- **Access control.** Login via the operator's SSO with multi-factor authentication, replacing the shared demo key. Roles for dispatcher, crew and administrator, with least privilege. Every approval and override is signed with the dispatcher's identity in the audit log. Read access (state, stream, audit) behind the same login.
- **Network.** TLS everywhere. Vehicle tablets and phones connect over a VPN or with client certificates (mTLS). The dispatch API is not public: it sits behind a firewall/WAF with rate limiting. CORS is restricted to the operator's own domains (the prototype allows all origins for the demo).
- **Secrets and data.** Keys in a secrets vault with rotation. Encryption at rest for the database and backups, daily off-site backups, and tested restores.
- **AI data protection.** As listed at the end of section 2: an EU region and zero data retention under a data-processing agreement (or another provider or an on-premises model), redaction of free text before it is sent, EU or on-premises speech-to-text, self-hosted routing. Autonomous mode would be enabled only after a shadow-mode pilot has measured how often dispatchers change or reject the AI's decisions. The system stays fully usable with the AI switched off.
- **Monitoring.** Alerts when a data source falls back, a quota runs low, the AI fails or a vehicle stops reporting.
- **Integration stays open.** Every input and output is an API (GPS/AVL feed, orders, crew messages, decisions). Plan B can run on its own for an independent operator, or next to an existing dispatch centre.

## One-liner for the pitch

> "Every data source has a backup: weather from two providers, traffic from TomTom with promet.si and a time-of-day model behind it, routing from OSRM and TomTom. If the AI is down, our engine still plans. In production it runs on private servers, twice, in two data centres, with login, encryption and a full audit trail."

If asked about data protection, add: "Today it is a prototype on synthetic data: a call's words and address do go to Claude, and Chrome's speech recognition goes to Google. In production that becomes an EU region under a processing agreement, redaction, and speech recognition on our own servers."
