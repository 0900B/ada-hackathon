# Simulation scripts: one stream, every dashboard in sync

Replayable scripts for the scenarios in [DISPATCH_SCENARIOS.md](DISPATCH_SCENARIOS.md). A script holds everything that happens from the 112 call until the last vehicle reports "free": each vehicle's activation, **road path with timestamps**, statuses, reroutes around closures and jams, the patient's vitals, the paramedic's **voice entries**, the ER pre-alert, handover and signature. It is meant to be given to the model and the dashboards, which then replay the same events at the same moments.

Built 2026-11-21. Everything is synthetic. 12 scripts, about 4,200 events, 101 vehicles, 80 patients. Design background: [AGENTIC_DISPATCH_DESIGN.md](AGENTIC_DISPATCH_DESIGN.md).

**Tags:** **[S]** from a source; **[I]** my inference; **[A]** an assumption.

---

## 1. Files

| File | What it is |
|---|---|
| `scenario/playback/D01.json` to `D12.json` | One script per scenario |
| `scenario/playback/index.json` | The list of scripts with counts |
| `scenario/dispatch_scenarios.json` | The scenarios the scripts are built from (calls, assignments, engine events) |
| `scenario/tools/replay.py` | Prints the stream as one dashboard would see it |
| `scenario/tools/*.py` | The generators and validators that rebuild everything (see section 9) |

## 2. How the dashboards stay in sync

There is **one ordered event stream** per script (`events`). Every event says who should see it in `visible_on`: `dispatch`, `er`, `crew` and `map`. Each dashboard plays the same stream in order and shows only its own events, so they can never disagree. Positions on the map are not events; they come from each vehicle's `track` and are interpolated between waypoints.

```
t_s       seconds since the script origin. The first model minute is t_s = 120, so the call and the triage come before the plan.
clock     local time, HH:MM:SS (UTC+1 in November); `iso` has the full date and time
seq       1, 2, 3 ... in play order (events with the same t_s keep their order)
```

To play at 30 times real speed, show each event when `t_s / 30` real seconds have passed. To draw a vehicle at time `t`, find the two `track` points around `t` and interpolate linearly.

## 3. Structure of a script

| Key | Content |
|---|---|
| `scenario`, `name`, `intent`, `date`, `start_local`, `shift` | Identity |
| `clock` | Origin, offset and end time in seconds |
| `dashboards` | What each dashboard shows |
| `world` | Weather, hospitals, and the road events (closures, jams) with position, radius and duration |
| `calls` | Each call: place, caller text in Slovenian, priority, estimated patients |
| `vehicles` | One entry per vehicle (section 5) |
| `patients` | One entry per patient (section 6) |
| `idle_fleet` | Vehicles that never moved, for the map's background |
| `events` | The master stream (section 4) |
| `summary` | Counts, including `human_steps` and `event_types` |

## 4. Events

Every event has `seq`, `t_s`, `clock`, `iso`, `type`, `visible_on`, usually `call`, `unit`, `patient`, and a `data` object. Events with **`"human": true`** are the steps a person does; everything else is the agent, the vehicles or the data feeds.

| Type | Seen by | What it carries |
|---|---|---|
| `world_state` | dispatch, map | Weather, speed factor, shift, synthetic hospital capacity |
| `call_received`, `caller_location_pinned` | dispatch (and map) | The caller's words in Slovenian, the pinned location |
| **`triage_set`** (human) | dispatch | The dispatcher's triage: red or yellow, problem, doctor needed, first responders, fire, police, helicopter |
| `plan_made` | dispatch | The agent's plan: which units, from where, why, minutes to arrive |
| `agent_action` | dispatch | One-line log of what the agent did and why (this is the audit trail) |
| `unit_activated` | dispatch, crew, map, ER | Role, base, other region or private, reason, speed and weather and traffic factors |
| `unit_status` | dispatch, crew, map (ER for patient statuses) | The Ministry status chain: SPREJETO, NA POTI, NA KRAJU, PRI PACIENTU, S KRAJA, NA CILJU, PREDAJA PACIENTA, ZAKLJUČEK INT, ČIŠČENJE, PROST (helicopter also PRIHOD DO HELIKOPTERJA, VZLET, VRNITEV V BAZO; OKVARA for a breakdown) [S, Ministry data set] |
| `eta_update` | dispatch, crew, ER | Predicted arrival at the scene or the hospital, as a clock time |
| `road_event`, `road_event_end` | dispatch, crew, map | A closure or jam: position, radius, Slovenian and English title |
| `reroute` | all | The vehicle's new path, extra seconds, a Slovenian message for the crew screen |
| `traffic_delay` | all | A jam on the vehicle's path: delay and position |
| `unit_diverted` | dispatch, crew, map | A vehicle taken off a yellow job for a red call |
| `unit_stand_down` | dispatch, crew, map | A vehicle released because it is not needed (mass casualty) |
| `unit_breakdown`, `replacement_dispatched` | all / dispatch, crew, map | Breakdown with a patient aboard, and the nearest free ambulance sent |
| `demand_trigger_on`, `nonurgent_rebooked` | dispatch | The surge trigger and scheduled transports moved to private vans |
| `patient_created` | dispatch, ER | Severity, category, age, sex (synthetic) |
| `er_card_created`, `er_card_update` | ER | **The ER dashboard card**: priority, category, unit, status, ETA, latest vitals, treatments, alerts, destination. Each update carries the whole card |
| `monitor_vitals` | crew, dispatch, ER | Heart rate, blood pressure, SpO2, respiratory rate from the monitor (simulated) |
| `voice_entry`, `voice_confirm`, `voice_check` | crew, dispatch, ER (check: crew only) | The paramedic's voice entry (section 7) |
| `er_alert` | ER, dispatch | For example "Cardiac arrest, CPR started", "Suspected STEMI", "Suspected stroke, onset time logged", SpO2 under 90 |
| `er_bay_assigned`, `handover_started`, `handover_summary`, `handover_done` | ER, crew (dispatch) | Bay, the 15-minute handover, an auto-generated summary |
| `record_review_prompt`, **`record_signed`** (human) | crew, dispatch (ER) | The paramedic reviews the pre-filled record and signs: the last documentation step at drop-off |
| `duplicate_call_merged` (human), `priority_change`, `capacity_update`, `feed_status` | dispatch (and ER, crew) | A merged duplicate caller, a yellow call upgraded to red, a hospital's reduced capacity, a stale data feed |
| `first_team_on_scene`, **`scene_report`** (human), **`mci_declared`** (human), `triage_complete`, **`hospital_distribution`** (human) | dispatch, ER, map | The mass-casualty sequence in D10 |

The six human event types are `triage_set`, `record_signed`, `duplicate_call_merged`, `scene_report`, `mci_declared` and `hospital_distribution`.

## 5. Vehicles

`vehicles[id]` holds:

- `role` (ambulance, doctor, van, helicopter), `org`, `base`, `area`, and `private` or `other_region` flags.
- `runs`: for each call the vehicle served: `activated_t_s`, `departure_t_s`, `arrival_t_s`, `left_scene_t_s`, `hospital_arrival_t_s`, `free_t_s` and a note. A vehicle reused later has several runs.
- `track`: `[t_s, lat, lon]` points. The vehicle is stationary between two points with the same position (at the scene, at the hospital, waiting out a jam). Where a vehicle was **rerouted**, the track follows the new path from the moment of the reroute.
- `statuses`: the status chain with times.
- `fuel`: start level, kilometres driven, end level for a 75-litre tank at 12 litres per 100 km [A]. No fuel feed exists. A vehicle under 25 percent gets a refuelling action.
- `km`: kilometres driven.

**Paths.** Road geometry comes from the public OSRM demo server (OpenStreetMap data, © OpenStreetMap contributors, ODbL), asked lightly and cached. Paths are the simplified geometry, so between waypoints the vehicle moves in straight lines. **Times come from the scenario model, not from OSRM**: waypoint times are spread along the path to match the model's arrival time. If a route request fails, a synthetic path is used and marked `synthetic` in `path_source`.

**Reroutes.** A closure is placed on the planned path of a chosen vehicle. Every vehicle whose remaining path passes through the closure while it is active gets a `reroute` with a new path (an alternative route, or a detour via a point beside the closure). The extra time is at least 8 percent of the remaining travel time plus 30 seconds, because a detour cannot be faster than the fastest route. A **jam** (`traffic_delay`) does not change the path; the vehicle waits at the point.

**Breakdown.** The vehicle stops (`OKVARA`), the nearest free ambulance is found from the fleet state at that moment, drives to the spot, takes the patient (3 minutes) and continues to the hospital. The patient's later entries are attributed to the replacement.

**Helicopter (D03a).** H1 is activated with the ground units, takes off 13 minutes after it is activated, flies a straight line at 200 km/h, lands, takes the patient to the UKC helipad, and returns to Brnik. The ground crew hand the patient over and are released when it takes off.

## 6. Patients

`patients[id]` holds the severity, category, age and sex, `carried_by` (vehicles in order), `doctor_unit`, `destination` and a `timeline` of the entries. Patient templates cover chest pain, cardiac arrest, stroke, fall with hip fracture, pedestrian trauma, allergic reaction, low blood sugar, head injury, breathing difficulty, severe bleeding, road crash, and the three mass-casualty colours. The vitals, drugs and procedures are **synthetic and not clinical guidance**. Green patients (walking wounded) go by van and get one triage entry.

## 7. Voice entries

Each `voice_entry` is what the paramedic says during the ride:

- `mode`: `wake_phrase` (starts with the wake phrase, "Zapis" is a placeholder) or `push_to_talk`.
- `transcript_sl`: the words in Slovenian (my drafts, to be read by a native speaker), `asr_confidence`.
- `parsed`: a type (`drug_administered`, `vitals`, `procedure`, `event`, `assessment`, `onset_time`, `triage`) and content (drug, dose, route; blood pressure; and so on). It records what was said and never invents a dose.
- `readback_on_screen` is always true: the entry appears on the crew screen. A **`voice_confirm`** follows when the crew confirms (a tap or "potrjeno"). Entries with low confidence give a **`voice_check`** and stay unconfirmed until a **correction** entry arrives (`corrects` points to the first entry). Chest pain and allergy patients carry one such example.
- Confirmed entries update the **ER card**. Alerts are raised for flagged events (arrest, return of circulation, intubation, a stroke onset time, a suspected STEMI, heavy bleeding, a drop in GCS) and for vitals under thresholds (SpO2 under 90, systolic pressure under 90). A doctor's entries come from the doctor vehicle when it reached the patient before the ambulance left.
- The record is **pre-filled from these entries**. At the hospital a `record_review_prompt` lists what needs review (drugs, events, procedures, unconfirmed entries) and the paramedic signs with `record_signed`, about 10 minutes after arrival, inside the 15-minute handover limit [S].

## 8. What happens in each scenario

| Script | What the stream shows |
|---|---|
| D01, D02 | The plain flow from call to free; D02 has a doctor starting from another base and a voice correction |
| D03a, D03b | Helicopter race, and the same call grounded by fog |
| D04 | A unit taken off a yellow call twice for red calls; one closure reroutes the arrest ambulance |
| D05 | A crash with six patients; a closure on the approach reroutes seven vehicles; a duplicate caller |
| D06 | Rush hour; a jam delays one ambulance |
| D07 | Teams near full capacity; an ambulance breaks down with a patient aboard and a replacement takes over |
| D08 | Night, three reds, a duplicate caller |
| D09 | Snow; a closure; the traffic feed goes stale for 15 minutes |
| D10 | Mass casualty: initial wave of 24 vehicles, the first team's report at minute 12, 5 vehicles stood down, 19 stay, hospital overflow to SB Celje, a slip road closure that reroutes ten vehicles |
| D11 | Everything out: two private ambulances for reds; UKC reports no free resuscitation bay |
| D12 | Overlapping events (same minute, in between, closure, jam, breakdown, capacity drop, upgrade to red) |

## 9. Replay and rebuild

From the repository root:

```bash
python docs/scenario/tools/replay.py D12                          # the whole stream
python docs/scenario/tools/replay.py D12 --dashboard er           # what the ER dashboard receives
python docs/scenario/tools/replay.py D12 --dashboard crew --unit A04
python docs/scenario/tools/replay.py D12 --positions 60 --speed 30   # real-time at 30x with positions each minute
python docs/scenario/tools/replay.py D12 --json                   # raw events, one per line
```

To rebuild everything (needs Python 3.10 or later and `pydantic`; the first run asks the public routing server for the paths and caches them in the system temp folder):

```bash
python docs/scenario/tools/dispatch_sim.py docs/scenario/dispatch_scenarios.json
python docs/scenario/tools/dispatch_validate.py      # engine payloads valid, counts consistent
python docs/scenario/tools/run_playback.py           # or give scenario ids: D04 D12
python docs/scenario/tools/playback_validate.py      # order, speeds, status chains, signatures
python docs/scenario/tools/make_scenario_doc.py      # DISPATCH_SCENARIOS.md
```

The seed is fixed (20261123), so the output is repeatable.

## 10. Feeding the team's engine and dashboards

- The engine accepts only the `urgent_request` payloads in `dispatch_scenarios.json` (`engine_events`, all validated against its event model). The rest of the stream needs new code in the backend or a frontend that reads the file directly: the simplest way to see the whole simulation synced is to load a script in each dashboard and play it with a shared clock.
- The ER dashboard needs `er_card_created`, `er_card_update`, `er_alert`, `er_bay_assigned`, `handover_*` and `eta_update`. The crew screen needs the events with its `unit`. The dispatch dashboard shows everything. The map needs `vehicles[].track`, `road_event`, `reroute` and `unit_stand_down`.
- This document and the scripts change no code in `backend/` or `frontend/`.

## 11. Limits

- Paths are simplified OSRM geometry; timing follows the scenario model, whose single speed makes long runs slow. Treat arrival times over 30 minutes as conservative.
- Closures, jams, weather and the hospital capacity are simulated stand-ins for promet.si, NAP and the hospitals' reports. Fuel is assumed.
- Vitals, drugs, procedures and Slovenian transcripts are synthetic drafts.
- The mass-casualty over-response and stand-down are modelled as the agent's job; no published Slovenian rule for sending an over-sized first wave or standing vehicles down was found [?] (the guideline covers METHANE, primary triage and calling additional help [S]).
- Hospital overflow in D10 uses synthetic capacity; the red patient's destination is confirmed by the incident medical lead.
- A vehicle's position between a diversion and the next task is interpolated along its path; the scenario model and the script can differ by a few seconds at hand-over points.
