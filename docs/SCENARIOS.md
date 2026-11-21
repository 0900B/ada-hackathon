# Scenarios for simulation and demo (draft)

A spec for the team to react to, not code. Status: **draft, not agreed**. The existing Python scenarios in `backend/app/demo.py` (stranded patient, stroke + closure, snow cascade) are untouched. This document lists what the brief asks for beyond them, using the live-data research in `docs/DATA_SOURCES.md`. All patients are synthetic.

## What the brief needs that the prototype lacks
| Brief item | In the prototype? |
|---|---|
| Helicopters, straight line at 200 km/h | No (only `ambulance`, `transport`) |
| Fog: helicopter grounded 1 h at the centre | No (weather is snow/rain/wind only) |
| Equipment tasks; equipment inside a broken vehicle is picked up first | No |
| Reduced hospital capacity | No |
| Patient priority change | No |
| Slovenian message → event | Partly (agent exists; message-to-event not checked) |
| Breakdown, delay, road closure, urgent task | Yes |

## Places and fleet (real coordinates from `research/samples/overpass_hospitals_helipads.json`)
| Place | Lat, Lon | Role |
|---|---|---|
| UKC Ljubljana + helipad `LJHL` | 46.056, 14.522 | The centre; helicopter base H1 |
| SB Jesenice + heliport `LJHJ` | 46.443, 14.037 | Remote hospital |
| SB Celje | 46.234, 15.261 | Alternative hospital |
| SB Slovenj Gradec | 46.508, 15.082 | Remote hospital |
| UKC Maribor | 46.553, 15.648 | Second helicopter base, optional H2 |

Proposed fleet: ambulances A1–A3 (Ljubljana), optionally A4 staged at Jesenice, vans T1–T5 (existing), helicopter H1 at `LJHL`, optional H2 at Maribor.

## Why the choice isn't obvious (measured)
Road times are OSRM normal-car estimates with no siren and no traffic; air times are straight line at 200 km/h.

| Leg | Road | Air |
|---|---|---|
| UKC → Jesenice | 50 min, 70 km | 17 min |
| UKC → Celje | 55 min, 74 km | 18 min |
| UKC → Slovenj Gradec | 88 min, 105 km | 20 min |
| UKC → UKC Maribor | 86 min, 124 km | 31 min |
| UKC → Murska Sobota | 120 min, 179 km | 43 min |
| Jesenice → UKC Maribor | 127 min, 179 km | 37 min |

Fog example: fetching a patient from Jesenice by H1 takes about 17 + 17 = 34 min. If H1 is grounded for 60 min, that becomes about 94 min, versus about 100 min by an ambulance from UKC. It's close, so the best answer depends on priority and on what else is queued. That is the planner's job.

## Scenarios
Each lists the data that backs it and what the model must gain. Slovenian wording is a draft.

### S0. Baseline morning (Part 1: initial plan)
- **Setup:** about 24 scheduled transfers, an urgent run, an equipment transport, H1 and the ambulances. Time windows and priorities set.
- **Shows:** a feasible plan with several trips per vehicle, pickup then delivery.
- **Needs:** helicopter type, equipment tasks.

### S1. Megla (fog grounds the helicopter)
- **Story:** an emergency transfer from SB Jesenice to UKC was assigned to H1. Fog closes the helipad at UKC for 60 min.
- **Trigger:** fog event, helicopter H1 grounded 60 min.
- **Replan must:** compare waiting, an ambulance from UKC, an ambulance staged at Jesenice, and optionally H2 from Maribor; keep emergencies first and push back scheduled trips with the least extra delay.
- **Live data:** METAR Brnik `LJLJ` (`fltCat` IFR/LIFR or `FG`), ARSO *megla*, Open-Meteo visibility along the path.
- **Fixture:** today's weather is clear, so keep a saved METAR with fog, clearly labelled as simulated.
- **Needs:** fog event with duration, helicopter vehicle type.

### S2. Zaprta cesta (road closure or delay)
- **Story:** the road an ambulance is using is closed, or a jam adds delay.
- **Variants:** the existing Zaloška cesta closure, or a real promet.si entry (such as a *Zastoj* or *Okvara vozila* on the A1/A2 motorway) turned into a closure area.
- **Replan must:** reroute around the closure, reassign if the detour breaks a time window.
- **Live data:** promet.si Atom (Slovenian text, no coordinates; geocode with Nominatim), TomTom incidents, openrouteservice `avoid_polygons`.
- **Needs:** mostly exists. Add real road times and a real-event source.

### S3. "Vozilo je obstalo. Oprema je še v njem." (Level up; the headline scenario)
- **Story:** van T2 carries a ventilator from UKC to SB Celje, needed for a procedure at a fixed time. The driver sends the message, with no location.
- **Pipeline:** message → breakdown event for T2 with `equipment_onboard` → position taken from T2's GPS → new pickup task → another vehicle with the right capability collects the equipment **first** (the brief's rule), then delivers it.
- **Variants:** the driver names a place ("*obstali smo pri Vranskem*"; Nominatim → 46.243, 14.950); a patient is also on board, so the patient is picked up first.
- **More messages to test:** "*Megla je, helikopter ne more poleteti.*", "*Pacientu se je stanje poslabšalo.*", "*UKC ima zasedeno urgenco.*"
- **Needs:** equipment task type and capability matching, `equipment_onboard` flag, message-to-event step.

### S4. Nova nujna naloga (urgent task)
- **Story:** a new emergency arrives when every vehicle has a queue.
- **Replan must:** insert it with the fewest displaced scheduled trips.
- **Needs:** exists (stroke + closure); add helicopter as an option.

### S5. Zmanjšana kapaciteta bolnišnice (reduced hospital capacity)
- **Story:** the UKC emergency department can take only N more arrivals for the next 2 h.
- **Replan must:** redirect extra arrivals to Celje or Maribor, using the helicopter where time-critical.
- **Live data:** none found (NIJZ has only yearly aggregates), so the operator injects this event.
- **Needs:** capacity attribute and event.

### S6. Sprememba prioritete (priority change)
- **Story:** a scheduled patient deteriorates and becomes an emergency while their van is still queued.
- **Replan must:** reassign the nearest suitable vehicle and re-slot the trip it drops.
- **Needs:** priority-change event.

### S7. Kaos na terenu (finale)
- **Story:** within 90 s: fog, a breakdown with equipment on board, an urgent task, and a capacity cut.
- **Shows:** the plan repaired quickly, with a clear before/after.

## Suggested 3-minute running order
| Time | What |
|---|---|
| 0:00–0:20 | The problem and the baseline plan (S0) |
| 0:20–1:10 | S1 fog: show the options and the choice |
| 1:10–2:10 | S3 Slovenian message: the level-up |
| 2:10–2:40 | S7 compressed, or S5/S6 as one-liners |
| 2:40–3:00 | Impact: the numbers below |

## "Minimal impact" metrics to show after every event
- Trips reassigned (fewer is better).
- Total added delay in minutes, and emergencies late (target: 0).
- Time to produce the new plan (seconds).
- A plan diff: which trips moved from which vehicle to which.

## Fixtures to prepare (offline demo safety)
- A fog METAR/ARSO snapshot, labelled simulated.
- A promet.si Atom snapshot and a geocode cache (Vransko, Koseze, Brnik).
- A precomputed OSRM matrix for the places above.
- All data shown as "live" or "snapshot" in the UI.

## Open questions for the team
1. One helicopter (H1 at UKC) or two (add H2 at Maribor)?
2. Does fog hit only UKC, or the whole Ljubljana basin?
3. Is an ambulance staged at Jesenice (A4) allowed in the fleet?
4. Which scenarios are must-have: suggest S1 and S3?
5. Where do scenarios live in the code, and who builds them? This document leaves that to the owners.
