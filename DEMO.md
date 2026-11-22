# Demo script: Bypass (3 minutes)

**One line:** *Kaos na terenu?* Bypass is an **AI dispatcher** for an EMS operator in Ljubljana. The rules engine
sends a unit to every 112 call in the second it arrives; Claude triages the call, reviews the case and
re-plans when something breaks; a crew can simply **say** a problem in Slovenian; the dispatcher can take over
any decision, and approves the plans that matter with one key.

We present an **independent EMS**, the fictional "Ljubljana Demo EMS", not an integration into Slovenia's 112/DCZ
system. If the jury asks about integration: every input and output is an API (GPS feed, calls, crew messages,
decisions), so it can sit next to an existing dispatch centre. Roads, traffic and weather are real; the fleet and
the calls are simulated. Say "simulated" whenever you quote a number.

Related: [docs/PITCH_NOTES.md](docs/PITCH_NOTES.md) (talking points, hard questions), [docs/JURY_QA.md](docs/JURY_QA.md),
[docs/BENCHMARK.md](docs/BENCHMARK.md), [media/README.md](media/README.md) (the recorded backup videos).

## Roles and devices

| Who | Device | What is open |
|---|---|---|
| Presenter | Laptop on the projector | The **production** Vercel domain, `/sim` (Simulation), tab **AI dispatcher**, UI in English |
| Crew (a teammate) | Android phone, **Chrome**, HTTPS | `/crew/T1?world=sim&lang=sl` (Slovenian is the phone's default anyway) |
| Optional | Tablet | `/vehicle/A1?world=sim`, the in-vehicle view of any unit |

Everything below happens in the **Simulation** world: its clock runs **5× faster than real time**, so a unit "14 minutes
away" arrives in under 3 real minutes. That is why the 112 call below is in a suburb: the unit is still driving while you
break it and override it.

## 1. Setup checklist (the morning of the demo)

> **22 Nov, 11:30:** `ADMIN_KEY` was removed from Railway so the judges can use the app freely (`/health` shows `admin_lock: false`, no lock chip in the header). Skip the key steps below; they apply only if a key is set again.

**Deploy (code freeze 12:00)**
- [ ] **No pushes to `main` between 12:00 and the pitch.** A push redeploys and restarts the backend: the simulation resets, the Claude usage counters reset, and the switches below fall back to their defaults (Assisted; the Simulation call stream is off by default).
- [ ] Railway, backend service, **Variables** (look at the names, never print the values): `ANTHROPIC_API_KEY`, `TOMTOM_API_KEY`, `ADMIN_KEY`, `DATABASE_URL` (a **reference** to the Postgres service, not a pasted copy), and optionally `NAP_USERNAME` + `NAP_PASSWORD` (access is pending; the app runs without). Also check that nobody set `SIM_SPEEDUP`, `CALLS_PER_HOUR`, `CLAUDE_MAX_PER_5MIN`, `CLAUDE_MAX_PER_DAY` or `AGENT_MODEL` to something unintended; the defaults are 5, 5, 12, 300 and `claude-sonnet-5-5`. All names: [backend/.env.example](backend/.env.example).
- [ ] Open `https://ada-hackathon-production.up.railway.app/health` in a browser (reading needs no key). Look for: `ok: true`; `admin_lock: false` (no key set: the app is open for the judges); **`claude.enabled: true`**, `claude.limited: false`, `claude.today` small; the `traffic` source with `kind: "live"` (not `"fallback"`) and `weather` `fresh`; `tomtom_requests_today` not `null`; **`audit.status: "connected"`** (not "memory only"); `traffic_tiles.available: true` and `capped: false`; no `last_error` on a source.

**Devices**
- [ ] Use the production domain **https://frontend-tau-rust-6kpoiztcvd.vercel.app** (every device, every time), never a `frontend-<hash>-….vercel.app` preview link: a preview can point at an old build, and the admin key is stored per web address.
- [ ] **Open each device once with the key:** laptop `https://frontend-tau-rust-6kpoiztcvd.vercel.app/sim?key=<ADMIN_KEY>`, phone `https://frontend-tau-rust-6kpoiztcvd.vercel.app/crew/T1?world=sim&lang=sl&key=<ADMIN_KEY>`, tablet likewise. The page keeps the key on that device and removes it from the address bar. Do this off-screen: never show a URL with the key. The header chip must say **"Control unlocked"**. "View only" = key missing; "Key rejected" = typo; **"No lock set" = the Railway variable is missing**, fix it before the pitch.
- [ ] Hard refresh (Ctrl+Shift+R) on laptop and phone. Dashboard language **EN** (toggle top right; `?lang=en`), phone **SL**.
- [ ] Status bar: `Connected`, `Data feeds fresh`, `Traffic … · TomTom live`, `Simulation · hypothetical · 5× speed`.
- [ ] Phone: **Chrome on Android, over HTTPS** (speech recognition needs both). Tap **Hold to talk** once and **allow the microphone**; the language toggle says SL ("Speaks: slovenščina"). Say the test sentence once.
- [ ] Browser zoom so the map and the right-hand panel read from the back of the room. Close other tabs. Laptop on power, sleep off, notifications off. Phone hotspot ready.

**State (about 10 minutes before)**
- [ ] Simulation → **Scenarios** tab → **Reset simulation**. This also re-anchors the Simulation clock to the real time of day: the helicopter flies only 08:00–16:30 on that clock, which at 5× runs out about 40 real minutes after a reset at 13:00. Reset again if the sim time is after 16:30.
- [ ] Same tab: check the **call stream is off** (the Simulation default since 22 Nov; switch under "Operations"). Otherwise a random call every ~2.4 real minutes can take the units your story needs. It survives resets and scenario buttons, not a backend restart. Leave the **Live** world as it is.
- [ ] **AI dispatcher** tab: set the mode to **Autonomous** (switch at the top). Then unfold **Situation review**, check the chip says **`Claude · claude-sonnet-5-5`** (not "Engine only") and leave **Auto-analyse off**: in Autonomous mode Claude reviews every critical or serious case anyway, and you start the one fleet-wide analysis yourself with **A** (no stray analysis, no wasted tokens). Fold it again.
- [ ] Click **New 112 call** and pre-fill the form (it stays filled; the tab keeps its state): *What the caller says:* `Mož se je zgrudil na dvorišču, ne diha, nihče ne dela oživljanja.` *Where:* `Šmarska cesta 3, Škofljica` (about 13 minutes from the ambulances, and far enough from Brnik that the helicopter is never the closest unit, before or after the breakdown; in our local checks at a daytime clock). Do not submit.
- [ ] **Dry run** with a stopwatch (section 2, all of it), then **Reset simulation** and put the switches back. One run uses about **5 of the 12 Claude calls allowed per rolling 5 minutes** (triage, two case reviews, the crew message, one analysis), so do not rehearse within 5 minutes of the pitch (`claude.retry_after_s` in `/health` shows the wait if you hit the limit).
- [ ] `https://frontend-tau-rust-6kpoiztcvd.vercel.app/reports?world=live&hours=8` shows closed calls (the Live world runs on the real clock and is never reset by a scenario button; it needs a backend that has been up for an hour or two). If it is empty, skip the page on stage and only say the sentence.
- [ ] **Backup:** the recorded showcase videos (`showcase-112-to-hospital`, `showcase-crew-replan`, `showcase-vehicle-tablet`, `showcase-chaos`, plus `promo-60s`) from `media/out/` are copied to the presenting laptop and the phone and play offline. They are not in git (re-record: `node media/showcase/record-all.mjs`; see media/README.md); check that their captions say what they show (Claude, or the keyword rules and the engine's plan). **Never run those scripts against the deployed backend before the pitch: they reset the Simulation world.**

## 2. The 3 minutes

| Time | Do | Say |
|---|---|---|
| **0:00–0:20** The problem | Laptop on `/sim`, AI dispatcher tab, no cases yet | "When a vehicle breaks down or two emergencies land at once, a dispatcher has seconds to work out who is affected, who takes over and what that does to everyone else. The brief calls it *kaos na terenu* and asks for a new plan. This is Bypass: an AI dispatcher. Real Ljubljana roads, traffic and weather; the fleet and the calls are simulated." |
| **0:20–0:55** A 112 call in Slovenian | Click **Classify and dispatch** (or speak the sentence with the form's mic). Watch the result, then the case card that opens by itself | "A call, in Slovenian, as the call-taker hears it. Claude reads it: **critical, cardiac arrest, doctor needed**, and says why. The engine had already sent the nearest ambulance and a doctor car in the same second. Every unit says **why** it was sent and **who** decided: engine, Claude or dispatcher." Point at: the case opens with a blue **"New call · Handled by the AI dispatcher"** box: line by line **AI DISPATCHER · Classified** (Claude or the keyword rules, with the time) and **AI DISPATCHER · Dispatched** (rules engine, <0.1 s), then the doctor car and Claude's review; then the severity badge and **AI triage · Claude**, the English translation under the Slovenian words, the clinical reason, the unit lines ("nearest free ambulance"; "doctor needed for cardiac arrest"), each with its arrival time on the unit tile. |
| **0:55–1:25** Something breaks: automatic re-plan | Once the first **Claude review** line is in the case's **Timeline** (15–25 s after the call; a case is not reviewed again within 24 real seconds or while a review is running): **Random failure ▾ → Engine failure** (it hits the unit on the 112 call first) | "Now something goes wrong: the ambulance on its way breaks down (or use **Random failure ▾ → Choose unit…** to pick it). The AI dispatcher recalculates at once and says so, even when it keeps the unit ("Recalculated: … compared N free ambulances"). The engine re-dispatched the call at once and logged it; for this address the new unit is at about the 15-minute reference, so the summary offers mutual aid or a private ambulance, and a red-call alert appears if it is over 15 minutes. Claude reviews the case: here it keeps the engine's decision, or changes it and the engine re-checks the change before it is applied." Point at: the case opens by itself with an amber frame and the **re-plan box** (it stays until you close it or open another case): the disruption, the engine's line with its real time ("Rules engine · <0.1 s"), ~~A1~~ → the new unit, "at the patient ~~old~~ → new, +N min", and, a few seconds later, the **Claude review** line; the badge says who did what; the header line counts reassignments and Claude reviews. |
| **1:25–1:45** The dispatcher overrides | On the unit tile click **Override**; read the list; pick the top feasible unit; **Confirm** | "Autonomous does not mean unsupervised. The dispatcher can replace any unit. The list is ranked by the rules engine by arrival at the patient, with what each choice costs. This one is logged as the dispatcher's decision, and from now on neither the engine nor the AI will change it." Point at: "ranked by the rules engine", the minutes better or worse than the current unit, the **Dispatcher overrode** badge. |
| **1:45–2:30** The crew speaks; plan; approval | **Scenarios** tab → **Prepare crew demo** (a new scene: T1 carries blood products to the Oncology Institute; this replaces the previous scene). Nod to the crew, who hold the mic: *"Vozilo je obstalo. Oprema je še v njem."* When the phone confirms the message ("Dispatcher notified"), press **A** (it opens the **Situation review** and starts the analysis). When the review says "Waiting for your decision", read the recommended option and press **Y** | "Transport 1 is carrying blood products. The crew just says it. Claude turns the sentence into a typed event, and tells us its assumption: no vehicle was named, so it took the sender's. Now the AI dispatcher checks which vehicle can reach the breakdown site and simulates complete plans. **Every number comes from our engine, not from the language model.** The recommended option: a free van collects the blood products at the breakdown site, another vehicle takes T1's next job. The dispatcher approves with one key." After **Y**: the routes change on the map; the phone says "Dispečer je potrdil nov načrt" (Dispatcher approved the new plan). |
| **2:30–2:50** Reports, and the honest number | Header → **Reports**, top of the page: world **Live** (a scenario button restarted the Simulation's history), window 8 h | "Every call ends up in the Reports: response time against the target for each severity, doctor on time, late transports, and who decided, engine, Claude or dispatcher override. These are measured on a simulation. So here is the one number we dare to quote:" then the sentence in section 4. |
| **2:50–3:00** Close | | "Next step: real vehicle GPS and real calls, and a pilot in shadow mode on an operator's logs. Bypass: when things go wrong, a new plan in seconds, and the dispatcher always has the last word." |

**If you are over time:** drop the override (mention it), then skip the Reports page and say only the sentence. Keep the crew part: it is the brief's part 3.

**What to expect, timing** (our 21 Nov rehearsals on Railway, before the AI dispatcher tab existed; re-measure in the dry run): crew report to options about 14 s (with Auto-analyse on; with **A** it is the analysis time, 11–16 s); approve 0.2 s; the chosen van at the breakdown site about 1 real minute. There is no measurement of Claude's triage or of a case review on the deployed system in our notes: time them in the dry run.

## 3. If something goes wrong

| Symptom | Do | Say |
|---|---|---|
| Triage is slow or the result says "Triaged by the keyword rules", tag **AI triage · rules** | Carry on: Claude is off, limited or slower than 12 s, and the keyword rules classified the call and the engine dispatched it | "That is the fallback: a call is never lost, and the dispatcher sees which source classified it." |
| No Claude review line after the breakdown, or "AI dispatcher review not available (…): the engine's decision stands" | Carry on to the override | "The engine had already acted. The review is a second pair of eyes, not a dependency." |
| No options 30 s after you pressed **A** | Wait up to 60 s (the hard deadline). If the Situation review says "Engine only" or "Claude took too long", the engine's own plan is shown: approve it. If nothing started, press **Esc** (leave any field) and **A** again | "The reliability point: the dispatcher is never left empty-handed." |
| "AI limit reached" | The limit is 12 Claude calls per rolling 5 minutes (300 a day). Wait, or use the engine's plan | "A guard caps the AI spend; over the limit the engine plans." |
| Phone: speech not recognised, mic blocked, or "AI could not be reached" | Tap the quick button **1 · Vozilo je obstalo.** (it falls back to a plain breakdown event if the AI is unreachable). Or on the dashboard open **Message to the AI dispatcher**, sender **From: T1 crew**, pick the first **Example…** | "Same message, one tap. Speech is the convenience, not the only way in." |
| The status bar says "profile" instead of "TomTom live" | Do not use **Road closure** or **Car crash** as the failure (no detour is drawn without TomTom, the unit only slows) | "The status bar shows which source is live; traffic falls back to a time-of-day model." |
| Override refused (for example the patient is already on board, or the unit is at the patient) | Skip it and say so | "The system refuses what cannot be done and says why." |
| The scene looks odd, or T1 has already delivered the blood | **Reset simulation**, then repeat the step. **Prepare crew demo** can be pressed again | (nothing) |
| Backend restarted | Cold start: set Autonomous again and re-fill the form (the Simulation call stream starts off); 20 seconds | (nothing) |
| Wi-Fi drops | Laptop and phone to the hotspot; the backend is on Railway, only the devices need the internet | (nothing) |
| Page stuck on "Connecting to …railway.app" | Some networks hold back the live stream. The page switches to fetching the state every 1.5 s after about 5 s by itself; if it still hangs, turn the VPN on or use the phone hotspot (seen on 22 Nov: fixed by a VPN). **Test the venue Wi-Fi before the pitch.** | (nothing) |
| Nothing works | Play `showcase-crew-replan.mp4` or `showcase-112-to-hospital.mp4` | "This is the same run, recorded." |

## 4. The honest benchmark sentence

Say this, with the helicopter clause, and say "simulated" (from [docs/BENCHMARK.md](docs/BENCHMARK.md)):

> "In 100 simulated 8-hour day shifts with identical calls, Bypass's dispatch rules reached 54 % of critical patients within the target, against 34 % with nearest-free-ambulance dispatch. That counts the helicopter as it really runs, 13 minutes to take off from Brnik and by day only; with ground units alone it is 43 % against 34 %."

Never quote 54 % without the second sentence. The benchmark measures the engine's rules, not Claude; the baseline is a plain rule, not today's dispatchers.

## Reference

### How the system behaves (for questions on stage)

- **Calls.** There is no pre-planned day. Synthetic calls come in about 5 per world hour (`CALLS_PER_HOUR`, gaps of 2–25 min; about one per 2.4 real minutes in the 5× Simulation) and a 112 call typed by you; each is dispatched at once. Severity: critical (cardiac arrest, choking, catastrophic bleeding, anaphylaxis: 8 min in the city, 15 outside), serious (stroke, heart attack, breathing difficulty, major trauma, seizure, sepsis: 18 min), urgent (falls, fractures, transfers, equipment: 60 min), each condition with a time-sensitivity weight (cardiac arrest 10, stroke and heart attack 6, ...). Rules and sources: [docs/DISPATCH_PRIORITIES.md](docs/DISPATCH_PRIORITIES.md).
- **Who goes.** Ambulances A1–A3 take emergencies; the engine sends the unit that reaches the patient first, including one finishing a drop-off nearby (at least 3 min sooner than a free one), and may divert a unit from a lower-level call (saving at least 3 min for critical, 5 for serious; never with a patient on board or within 2 min of its patient). Vans T1–T5 take urgent transports and equipment, never emergencies. The last free ambulance of an area is kept for red calls. Doctor cars D1, D2 join red calls that need a doctor.
- **Helicopter H1** (HNMP Brnik): 13 minutes from the call to take-off, 200 km/h, 08:00–16:30 only; at night it shows "Unavailable at night until 08:00". By rule it is the closest unit for a critical call, a serious call only if 10 min faster, an urgent call only far from the hospital. In practice it wins remote calls and city calls only when every ambulance is busy. Fog grounds it.
- **AI dispatcher.** Claude reviews every new critical or serious call and every disruption of an open call. Assisted (default): its recommendation is a proposal (reviews run only with Auto-analyse on). Autonomous: it is applied after the engine re-checks it, and logged as "AI". Surge capacity and the plans of non-call work (equipment, bookings) stay with the dispatcher. A dispatcher's override sticks. Details: [docs/DISPATCH_PRIORITIES.md](docs/DISPATCH_PRIORITIES.md) section 8.
- **Approving a plan does exactly what the option says**, step by step; if the world changed while the option was on screen, approval is refused with the reason.
- A routine call never starts a general AI analysis. A red call predicted over 15 minutes raises an alert and the engine advises asking a neighbouring station.
- **Scheduled day** (the brief's initial plan): `POST /sim/admin/reset {"scheduled_day": true}` (or the "Scheduled day" switch in the Scenarios tab) starts a pre-planned day of 24 booked trips and 4 equipment runs for the vans, no random calls; `false` returns to live calls. `SCHEDULED_DAY=1` makes it the start-up default.

### Scenarios (Simulation → Scenarios tab)

Every scenario resets the world, stages a few live jobs, fast-forwards to the moment, applies its events and pauses new random calls for 30 world-minutes. They start at a daytime clock (the helicopter flies by day), so they look the same at 13:00 and at an evening rehearsal. With Auto-analyse off, press **A**: the analysis gets the scenario's description. "Automatic" scenarios show a decision the engine takes by itself: point at the event log line.

| Button | What happens | What to look at |
|---|---|---|
| Prepare crew demo | T1 loads blood products at UKC for the Oncology Institute (a short run: the crew must speak within about a minute), one more job queued | Sets up the live crew message ("Vozilo je obstalo. Oprema je še v njem.") |
| Stranded patient | T2 breaks down **with an urgent patient on board**; A1 and A2 are on emergencies | Who collects the patient at the roadside (a free van, or the last free ambulance) and who takes T2's next job |
| Stroke and closure | **Automatic (available soon).** Stroke in Polje, Zaloška closed at Kodeljevo; A2 is finishing a handover at UKC, the free A3 is far away (back from Novo mesto) | "dispatched A2 (available soon: ready HH:MM after handover and cleaning ...)" and "H1 checked: take-off in 13 min; not 10 min faster". The loaded leg goes around the closure (orange) when TomTom is live |
| Priority override | **Automatic (override).** A1 is on its way to an urgent fall when a cardiac arrest (no bystander CPR) is reported next to it | "A1 diverted from TR-002 (urgent) to this critical call, N min sooner than A3; TR-002 taken over by T1 (within its 60-min target); H1 checked: not the closest" and the clinical reason (about 6 % survival lost per minute without defibrillation) |
| Same level, different urgency | A1 is on its way to a seizure when a suspected heart attack comes in next to it; the free A3 is sent (same level: nothing automatic) | Press **A**: a **swap** is proposed (heart attack first: catheter lab within 90 min); approve and A1 turns around |
| Call surge | Seven calls in about three minutes, including a **cardiac arrest** and a child with breathing difficulty; three ambulances | The arrest **diverts A2 from a major trauma** (N min sooner than H1) and the trauma goes to **H1**; the fall goes to a van; two serious calls queue behind busy ambulances (over 15 min, red-call alerts, "no doctor car free"). Press **A**: surge capacity, who waits, mutual aid |
| Doctor rendezvous | Chest pain in Bežigrad; the ambulance and the doctor car start from different bases | **Automatic:** two units, two routes, one patient; the doctor joins the crew on scene and rides along |
| Nothing free | A cardiac arrest while every ambulance has a patient on board far away and H1 is loading a hiker | The engine sends H1 ("the closest unit for a critical call") and the doctor car at once; "can request M1 / P1". Press **A**: mutual aid, a private ambulance or wait |
| Remote emergency | **Automatic (override, helicopter).** H1 was activated 2 min ago for a skier (wrist fracture, Krvavec) when a hiker falls at Kamniška Bistrica (major trauma, 45 min by road) | "H1 ... N min sooner than A1 by road; diverted from TR-001 (urgent); take-off in 12 min" and "TR-001 taken over by A3 (within its 60-min target)". Watch H1 take off, **fly**, land, load and land at UKC. Optional: **F** (fog) while it flies |
| Snow cascade | Snowstorm; T1 stuck 25 min with a patient on board and another queued; a fall on ice with a head injury (major trauma) | The trauma gets the nearest ambulance and a doctor car at once; T1's queued patient turns late: press **A** to move it and decide who waits |
| Stranded equipment | T1 breaks down with the blood products on board (no phone needed) | Who collects them at the breakdown site (the brief's rule) and who takes T1's next job |
| UKC full | Five patients heading to UKC; one (in a van) gets chest pain (now serious) and UKC can admit only two more | The engine sends an ambulance to the heart attack at once; press **A**: which three are redirected, where (Trbovlje / Novo mesto) and by whom |

The numbers in those lines (minutes sooner, ETAs) move a little between runs with the live road routing; the decisions do not.

### Hotkeys (press `?` on the dashboard)

`A` analyse · `Y` approve the recommended option · `N` reject · `M` mic · `B` / `D` breakdown / 10-min delay of the selected vehicle · `F` fog · `E` / `C` emergency / closure on the map · `R` random call · `X` random failure · `Esc` cancel · `?` help. On the crew phone: `1`–`5` are the quick reports, `M` the mic.

Extra buttons (Events tab): **Fog: ground helicopters 1 h** (a trip it has not picked up yet goes to the nearest ambulance at once), **Priority & capacity** (a patient's priority, a hospital's capacity), **Map click (E)**. **Random call** takes a call from the Slovenian call library (Claude triages it only with the **AI triage** switch on); **Random failure** hits what is happening now (engine failure, delay, road closure, car crash, fog, hospital full, stranded equipment).
