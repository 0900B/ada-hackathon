# Demo script: Plan B (3 minutes)

**One-liner:** *Kaos na terenu?* Plan B is a dispatch system for an EMS operator. It runs the fleet
on real roads with live traffic and weather. When something goes wrong, a crew can simply **say** it
in Slovenian, and within about 30 seconds the dispatcher sees what's at risk and 2–3 simulated plans to
approve.

We present an **independent EMS** (a fictional operator, "Ljubljana Demo EMS"), not an integration
into Slovenia's 112/DCZ system. If the jury asks about integration: every input and output is an
API (GPS feed, orders, crew messages, decisions), so it can sit next to an existing dispatch centre.

**How the fleet works** (close to how Slovenian EMS works; say it when you click a vehicle):
- **Ambulances A1–A3 are emergency units.** They start the day free at their bases, with nothing
  planned. A new emergency or urgent call is dispatched **at once** by the engine to the free unit that
  reaches the patient first (the event message says who and when). An ambulance never holds more than
  its current job plus one, and is never turned away from a patient on board.
- **Transport vans T1–T5 do the planned day**: seated, wheelchair and stretcher patients, equipment.
  They never take emergencies. New bookings go to a van; an ambulance only helps if no van can.
- **Helicopter H1** flies emergencies and urgent trips only, when it is clearly faster (remote places,
  long distances). Fog grounds it.
- **Approving a plan does exactly what the option says**: each option lists, step by step, which
  vehicle goes now or next and when it arrives; the vehicles then do that. If the world changed while
  the option was on screen (e.g. the vehicle has loaded another patient), approval is refused with the
  reason instead of doing something else.

## Roles
- **Presenter (laptop on the projector):** dispatcher dashboard, Simulation tab.
- **Crew (teammate with an Android phone, Chrome):** Crew view, e.g. `https://<vercel-url>/crew/T1?world=sim`.

## Before going on stage (10 min before)
- [ ] Laptop: open the Vercel URL. The status bar shows `● connected`, and the sources show `fresh`, with traffic as "TomTom live".
- [ ] The AI badge shows `Claude · claude-sonnet-5-5`, not "Engine only".
- [ ] **Auto-analyse:** it is off by default (saves tokens). Either switch **Auto-analyse on in the Simulation tab** right before going on stage, or remember to press **A** (Analyse) after each event / the crew message. Leave it off during rehearsals.
- [ ] **Don't push to `main` anymore.** Every push restarts the backend and resets the simulation.
- [ ] Phone: open the Crew view URL over **HTTPS** (the Vercel URL, never a local IP). Tap the mic once and **allow microphone access**. Set the SL/EN toggle to **SL**.
- [ ] Dry run: Simulation tab → **📦 Prep: crew demo**. The message shows which vehicle carries equipment (with seed 42 it's **T1**, carrying blood products). Open `/crew/T1?world=sim` on the phone, say the sentence, approve, then **↺ Reset simulation**.
- [ ] Browser zoom: make the map and the right-hand panel readable on the projector. Press `?` once to check that the shortcuts work.
- [ ] Phone hotspot ready, in case the venue Wi-Fi fails.

## The 3 minutes

**0:00–0:25 · The problem.** "Dispatchers juggle dozens of transports. When a vehicle breaks down or
a road closes, they must work out, under pressure, who is affected, who takes over, and what that does
to everyone else. The brief calls it *kaos na terenu*, and asks for *a new plan*. That's Plan B."

**0:25–0:50 · Live tab: the initial plan (*začetni plan*).**
- Show real Ljubljana: the fleet drives real roads, TomTom traffic colours are on, plus real weather and real incidents.
- Click a **van**: its crew, fuel, and its whole day highlighted with numbered stops.
- Click an **ambulance**: no stops planned. "Ambulances wait at their base for emergencies; a new call is sent to the nearest free one at once."
- "Every booked trip already has a vehicle and an arrival time. The system always knows the facts."

**0:50–2:10 · Simulation: the crew speaks, Plan B answers (*popravek plana* + AI).**
1. Click **📦 Prep: crew demo** (T1 is now carrying blood products).
2. **Crew on the phone, holding the mic button:** *"Vozilo je obstalo. Oprema je še v njem."*
3. **Point at the dashboard:**
   - "Understood: T1 broke down, the equipment is still inside." The AI also states its assumption: no vehicle was named, so it took the sender's.
   - If Auto-analyse is off, press **A** now.
   - The AI dispatcher's live trace: "It's checking which vehicles can reach the breakdown site, and simulating complete plans. **Every number comes from our engine, not the language model.**"
   - The options appear. Read out the recommended one: who collects the equipment at the breakdown site (the brief's rule; usually a free ambulance, "goes now"), what happens to T1's other bookings (spread over the vans), plus the before/after numbers. Each step line says who goes now or next and when.
4. Press **Y** (or click Approve). The vehicles do exactly what the steps said: the routes update on the map, and the crew's phone shows "✓ Dispatcher approved".

**2:10–2:40 · Why you can trust it.**
- **Human in the loop:** the AI proposes; the dispatcher approves with one key.
- **No invented numbers:** the engine re-simulates every option before it's shown.
- **Always works:** without the AI, the engine's own plan appears. If a data feed fails, the system falls back and says so.
- **Every data source has a backup** (say this sentence): *"Weather comes from two providers, traffic from TomTom with promet.si and a time-of-day model behind it, routing from OSRM and TomTom. If the AI is down, our engine still plans. In production it runs on private servers, twice, in two data centres, with login, encryption and a full audit trail."* Details for jury questions: `docs/RELIABILITY_AND_SECURITY.md`.
- **Accountable:** the **Audit** page logs every message, recommendation and decision, stored in Postgres.

**2:40–3:00 · Close.** "Helicopters with fog grounding, equipment, hospital capacity and priority
changes are all in there too. Next step: real vehicle GPS and real orders. Plan B: when things go
wrong, a new plan in 30 seconds."

## If something goes wrong
- **Speech doesn't work** (permission, noise, network): tap the quick button **1 · "Vozilo je obstalo."** on the phone, or type the sentence. Same result.
- **Claude is slow or down:** the engine fallback still produces a plan. Say: "That's the reliability point: the operator is never left empty-handed."
- **Wi-Fi is down:** switch to the hotspot. The backend runs on Railway, so only the devices need internet.
- **The scene looks odd:** **↺ Reset simulation** → **🧠 Stroke + closure**. It's the most predictable scenario and needs no phone.

## Hotkeys (dashboard, press `?` to see them)
`M` mic · `A` analyse · `Y` approve recommended · `N` reject · `B`/`D` breakdown/delay for the selected vehicle · `F` fog · `E`/`C` emergency/closure on the map · `Esc` cancel · `?` help

## Scenarios (Simulation tab)
With Auto-analyse off, a scenario only applies its events; press **A** for the AI's recommendation.

| Button | What happens | What to point out |
|---|---|---|
| 📦 Prep: crew demo | Fast-forwards until a van carries equipment; nothing else (seed 42: **T1** with blood products) | Sets up the live crew message |
| 🚐 Stranded patient | A van (T3) breaks down **with a patient on board**; its other bookings lose their vehicle | Press A: a free ambulance collects the stranded patient at the roadside ("goes now"); the bookings are spread over the other vans; some become late, so the AI drafts patient notifications. One ambulance stays free |
| 🧠 Stroke + closure | Suspected stroke in Polje plus a closure on Zaloška (Kodeljevo), right on the way to UKC | The engine sends the nearest free ambulance **at once** (event message: who and when). Click it: its route goes **around** the closure (orange). Press A: the AI checks the knock-on effects on vans that drive through the closure; hospital pre-alert |
| 🚁 Remote emergency | A hiker falls at Kamniška Bistrica, about 45 min by road | The engine sends **helicopter H1** (about 30 min sooner than the nearest ambulance). Watch it **fly** straight there, land, load the patient and land at UKC (~25 min). Optional: press **F** (fog) while it flies: it finishes the flight with the patient on board, then stays grounded |
| ❄️ Snow cascade | Snowstorm, a van stuck 25 min and a fall on ice | The fall on ice gets the nearest ambulance at once; many van trips turn late: press A, the agent prioritises, moves late trips and weighs using a free ambulance |
| 🧰 Stranded equipment | T1 breaks down with blood products on board | Press A: another vehicle (a free ambulance, as it's urgent) must collect it at the breakdown site first; T1's bookings go to other vans |
| 🏥 UKC full | A patient on a van becomes an emergency; UKC can admit only one more | The van can't take an emergency: the engine sends the nearest ambulance at once. Press A: the emergency keeps the last UKC slot; the other incoming patients are redirected |

Extra buttons: **🌫 Fog** grounds the helicopter for 1 h (a trip it has not picked up yet goes to the nearest ambulance at once). **Priority & capacity** changes a patient's priority or a hospital's capacity. **Map click (E)**: a new emergency at that spot is dispatched at once.
