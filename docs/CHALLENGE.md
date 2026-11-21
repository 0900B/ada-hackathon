# Challenge brief: Epilog #3 — "Kaos na terenu. Vaša rešitev ponudi nov plan."

*"Chaos in the field. Your solution offers a new plan."*

**Event:** AdaHack 2026 ("Code for change"), Ljubljana, hosted at Epilog.
**Coding stops:** Sunday 22 Nov 2026, 11:00. **Demo:** 3 minutes on stage (Sunday 13:00).

## Part 1: Initial plan (*začetni plan*)

Build an initial plan for a fleet of **ambulances (*reševalna vozila*)** and **helicopters (*helikopterji*)**. The centre (depot) is a **hospital (*bolnišnica*)**.

**Task types (*naloge*):**
- patient transport (*prevoz pacientov*)
- equipment transport (*prevoz opreme*)
- urgent runs (*nujne vožnje / nujni prevozi*)

**Constraints (*omejitve*):**
- vehicle capacities (*kapacitete vozil*)
- time windows (*časovna okna*)
- task priorities (*prioritete nalog*)
- several trips per vehicle (*več voženj na vozilo*)
- pickup and delivery (*prevzem in dostava*)

**Travel:**
- ambulances: road routes (real road network)
- helicopters: straight-line distance at **200 km/h**

**Extras (optional):**
- vehicle capabilities (e.g. which vehicle can carry which patient/equipment)
- crew availability (*razpoložljivost posadke*)
- hospital admission capacity (*sprejemna kapaciteta bolnišnice*)

## Part 2: Plan repair (*popravek plana*)

When an unexpected event (*nepričakovan dogodek*) happens, repair the plan **quickly, with minimal impact on execution, respecting real constraints**.

Events from the brief:
- **vehicle breakdown** (*okvara vozila*)
- **fog** (*megla*): helicopter grounded for 1 h at the centre
- **urgent new task** (*nova nujna naloga*)
- **reduced hospital capacity** (*zmanjšana kapaciteta bolnišnice*)
- **patient priority change** (*sprememba prioritete pacienta*)

Also mentioned in the original challenge text:
- vehicle delays (*zamude vozil*)
- road closures (*zaprte ceste*)
- shortage of available vehicles (*pomanjkanje razpoložljivih vozil*)

**Rule:** equipment inside a broken-down vehicle must first be picked up by another vehicle before it can be delivered.

## Part 3: Level up — AI assistant

An AI assistant turns a natural-language message in **Slovenian** into a structured event and triggers a new plan.

Example: *"Vozilo je obstalo. Oprema je še v njem."* ("The vehicle has stopped. The equipment is still inside.") → event: vehicle breakdown, equipment on board → replan, including picking up the equipment.

## Glossary
| Slovenian | English |
|---|---|
| reševalno vozilo / reševalec | ambulance |
| helikopter (HNMP) | helicopter (emergency medical) |
| bolnišnica / UKC | hospital / university medical centre |
| nujno | urgent |
| okvara | breakdown |
| megla | fog |
| zapora ceste | road closure |
| zastoj | traffic jam |
| prevzem / dostava | pickup / delivery |
| oprema | equipment |
| posadka | crew |
