# Demo script: Plan B (3 minutes)

**One-liner:** *Kaos na terenu?* Plan B is a dispatch system for an EMS operator. It runs the fleet
on real roads with live traffic and weather. When something goes wrong, a crew can simply **say** it
in Slovenian, and within about 30 seconds the dispatcher sees what's at risk and 2–3 simulated plans to
approve.

We present an **independent EMS** (a fictional operator, "Ljubljana Demo EMS"), not an integration
into Slovenia's 112/DCZ system. If the jury asks about integration: every input and output is an
API (GPS feed, orders, crew messages, decisions), so it can sit next to an existing dispatch centre.

## Roles
- **Presenter (laptop on the projector):** dispatcher dashboard, Simulation tab.
- **Crew (teammate with an Android phone, Chrome):** Crew view, e.g. `https://<vercel-url>/crew/T1?world=sim`.

## Before going on stage (10 min before)
- [ ] Laptop: open the Vercel URL. The status bar shows `● connected`, and the sources show `fresh`, with traffic as "TomTom live".
- [ ] The AI badge shows `Claude · claude-sonnet-5-5`, not "Engine only".
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
- Click a vehicle: its crew, fuel, and its whole day highlighted with numbered stops.
- "Every trip already has a vehicle and an arrival time. The system always knows the facts."

**0:50–2:10 · Simulation: the crew speaks, Plan B answers (*popravek plana* + AI).**
1. Click **📦 Prep: crew demo** (T1 is now carrying blood products).
2. **Crew on the phone, holding the mic button:** *"Vozilo je obstalo. Oprema je še v njem."*
3. **Point at the dashboard:**
   - "Understood: T1 broke down, the equipment is still inside." The AI also states its assumption: no vehicle was named, so it took the sender's.
   - The AI dispatcher's live trace: "It's checking which vehicles can reach the breakdown site, and simulating complete plans. **Every number comes from our engine, not the language model.**"
   - The options appear. Read out the recommended one: who collects the equipment at the breakdown site (the brief's rule), plus the before/after numbers.
4. Press **Y** (or click Approve). The routes update on the map, and the crew's phone shows "✓ Dispatcher approved".

**2:10–2:40 · Why you can trust it.**
- **Human in the loop:** the AI proposes; the dispatcher approves with one key.
- **No invented numbers:** the engine re-simulates every option before it's shown.
- **Always works:** without the AI, the engine's own plan appears. If a data feed fails, the system falls back and says so.
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
| Button | What happens | What to point out |
|---|---|---|
| 📦 Prep: crew demo | Fast-forwards until a van carries equipment; nothing else | Sets up the live crew message |
| 🚐 Stranded patient | A van breaks down **with a patient on board** | The stranded patient is handled first; ambulances are kept free |
| 🧠 Stroke + closure | Suspected stroke in Polje plus a closure on Zaloška near UKC | Fastest ambulance, around the closure, hospital pre-alert |
| ❄️ Snow cascade | Snowstorm, a van stuck 25 min and a fall on ice | Many late trips at once: the agent prioritises and weighs the reserve ambulance |
| 🧰 Stranded equipment | A vehicle breaks down with blood products on board | Another vehicle must collect it at the breakdown site first |
| 🏥 UKC full | A patient becomes an emergency; UKC can admit only one more | The emergency gets the last UKC slot; the others are redirected |

Extra buttons: **🌫 Fog** grounds the helicopter for 1 h (its patients are handed to ambulances). **Priority & capacity** changes a patient's priority or a hospital's capacity.
