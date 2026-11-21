# Demo script (3–5 min pitch)

**One-liner:** When something goes wrong in emergency medical transport, our AI dispatcher shows the
operator, within about 30 seconds, what is at risk and 2–3 simulated options. The operator decides
with one click.

## Before you go on stage
- [ ] Open the Vercel dashboard on the presenting laptop. The status bar shows `● connected` and every data source shows `fresh`.
- [ ] The AI badge says `Claude · claude-sonnet-5-5`, not "Engine only".
- [ ] Show the **Live** tab for real conditions, then switch to **Simulation** for the scenario.
- [ ] Do a dry run of the scenario you'll show in **Simulation**, then click **↺ Reset simulation**.
- [ ] Zoom the browser so the map and the AI panel are both readable on the projector.
- [ ] Have a phone hotspot ready in case the venue Wi-Fi fails.

## Flow

**1. The problem (30 s).** Dispatchers juggle dozens of transports. When an ambulance breaks down or
a road closes, they must work out who is affected, which vehicle should take over, and what that does
to everyone else's schedule. Today that happens in their heads, under time pressure.

**2. The live system (30 s).** On the **Live** tab: the fleet driving real roads across Ljubljana,
real weather, TomTom traffic speeds and real incidents, and every trip's predicted arrival. "The backend
runs constantly, so when something happens the facts are already there."

**3. The scenario (90 s).** Switch to **Simulation** and click **🧠 Stroke + closure**.
- While the agent works, point at the live trace: "Claude is checking which ambulances can reach
  the patient, then simulating complete plans. Every number you'll see comes from our simulation
  engine, not from the language model."
- When the options appear, read out the recommended option's before/after numbers and its reasoning.
- Open **Notification drafts**: the pre-alert to UKC's emergency department, in Slovenian.
- Click **Approve**. The map and trips update immediately.

**4. Why you can trust it (45 s).**
- **Human in the loop:** the AI recommends and the operator decides.
- **No invented numbers:** the engine re-simulates every option before it's shown.
- **Always works:** if Claude is unavailable, the engine's own plan appears instead. If a data
  feed drops, the system uses fallback data and says so.
- **Honest about uncertainty:** the agent flags when data such as traffic is stale or estimated.

**5. Impact and next steps (30 s).** Connect it to Epilog's real dispatch data and vehicle GPS. Use
real road routing and hospital capacity. Measure minutes saved per disruption.

## Backup plan
- **Claude is slow or down:** the engine fallback still produces a plan. Say: "This is exactly the
  reliability point: the system never leaves the operator empty-handed."
- **Wi-Fi is down:** use the hotspot. The backend runs on Railway, so only the laptop needs a connection.
- **A scenario looks odd:** click **↺ Reset simulation**, then run **🚐 Stranded patient**. It's
  the most predictable scenario.

## The three scenarios
| Button | What happens | What to point out |
|---|---|---|
| 🚐 Stranded patient | A van breaks down **with a patient on board**; its other trips have no vehicle | The stranded patient is handled first, and ambulances are kept free |
| 🧠 Stroke + closure | Suspected stroke in Polje plus a closure on Zaloška near UKC | Fastest ambulance, route around the closure, hospital pre-alert |
| ❄️ Snow cascade | Snowstorm, a van stuck 25 min and a fall on ice, all at once | Many late trips at once: the agent prioritises and reshuffles |
