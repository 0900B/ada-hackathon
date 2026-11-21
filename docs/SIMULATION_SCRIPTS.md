# Simulation scripts: what the world does, and what the model must decide

Scripts for the scenarios in [DISPATCH_SCENARIOS.md](DISPATCH_SCENARIOS.md). They are built so that **the model decides everything the dispatcher decides**: which vehicle takes a call, from where, how long it needs, which way it drives, when it is rerouted. The script only holds what happens *to* the system and what people say and do.

Built 2026-11-21. Everything is synthetic. Design background: [AGENTIC_DISPATCH_DESIGN.md](AGENTIC_DISPATCH_DESIGN.md).

**Tags:** **[S]** from a source; **[I]** my inference; **[A]** an assumption.

---

## 1. Two kinds of file

| | Input scripts | Reference runs |
|---|---|---|
| Folder | `scenario/scripts/` | `scenario/reference_runs/` |
| What it is | **The input.** The starting fleet, the calls, the dispatcher's simulated triage, closures and jams, hospital reports, data-feed problems, the patients' monitor feed and the paramedic's voice entries | **An example output** of a stand-in dispatcher for the same input |
| Contains vehicle assignments | **No** | Yes: who went, ETAs, paths, statuses, reroutes |
| Use | Give it to the model | Compare the model against it; show the dashboards before the model is connected |

The input script holds no vehicle ids outside the starting fleet, no ETAs, no paths and no statuses. `scenario/tools/scripts_validate.py` checks this on every build.

## 2. The input script

| Key | Content |
|---|---|
| `scenario`, `name`, `intent`, `date`, `start_local`, `shift` | Identity |
| `what_this_is` | A reminder that this is input only |
| `clock` | Origin time. `t_s` is seconds since the origin; the first model minute is `t_s = 120` |
| `rules` | How anchors work, how voice entries are timed, assumed human timings and durations |
| `world` | Weather, a speed-factor hint, shift, the (synthetic) capacity of UKC |
| `fleet` | **The resources at the start**: every ambulance, doctor vehicle, van, private unit and the helicopter, with position, status, fuel and whether it can be taken off a scheduled job. This is the situation the model decides from; nothing says who goes where |
| `timeline` | The events that happen at fixed times (below) |
| `conditional_events` | Events that depend on what the model did (below) |
| `patients` | Each patient: severity, category, age and sex (synthetic), monitor feed, voice entries |
| `summary` | Counts |

### Timeline events (fixed times)

Each has `t_s`, `clock`, `type`, `source` (who or what produces it) and `data`. Events from a person are marked `(human, simulated)`.

| Type | Source | What it says |
|---|---|---|
| `call_received` | caller | The caller's words in Slovenian and the pinned location (from the 112 call) |
| `triage` | dispatcher (human, simulated) | Red or yellow, problem, estimated patients, doctor needed, first responders, fire, police, helicopter requested, suspected mass casualty. This is the one mandatory human step. **It names no vehicle** |
| `duplicate_call` | caller | A second caller about the same incident; the dispatcher merges it (human) |
| `caller_callback` | caller | The caller phones back and the dispatcher re-triages (D12: yellow to red) |
| `road_event`, `road_event_end` | traffic feed (simulated) | A closure or jam: position, radius, duration, a delay for jams, titles in Slovenian and English |
| `data_feed_status` | data feed | A feed goes stale or fresh again |
| `hospital_capacity_update` | hospital report | For example UKC reports one free resuscitation bay |
| `scheduled_transport_requests` | booking system | A batch of scheduled transports; the model decides who takes them |

### Conditional events

They depend on what the model did, so they cannot have a fixed time:

- **`vehicle_breakdown`** (D07, D12): *whichever vehicle carries the named patient* breaks down at a given fraction of the transport. The model must send a replacement.
- **`scene_report_sequence`** (D10): **4 minutes after the first unit reaches the scene** the first team reports (METHANE, human) with the real counts; 10 s later the mass-casualty event is declared (human); 60 s after the report start triage is complete and the 22 patients appear. The model decides what to send before this and what to stand down after it.

### Patients and voice entries

Everything a patient says or shows is anchored to the **care episode**, not to a vehicle:

| Anchor | Means |
|---|---|
| `at_patient` | The first crew (ambulance or doctor) reaches the patient |
| `left_scene` | The patient leaves the scene |
| `at_hospital` | The patient arrives at the hospital |

- `voice_entries[]`: `anchor` and `offset_s` (the entry happens that many seconds after the anchor), `by` (`crew`, or `doctor_if_on_scene`: the doctor vehicle's crew if a doctor reached the patient before transport, otherwise the crew), `mode` (`wake_phrase`, placeholder "Zapis", or `push_to_talk`), `transcript_sl` (Slovenian drafts, to be read by a native speaker), `asr_confidence`, `parsed` (type and content: drug, dose, route, blood pressure and so on), `needs_correction`, `corrects`, and `expected_er_alert` (what a correct system should raise; for checking, not an instruction).
- **Timing rule:** if a phase is shorter than the last offset, scale all offsets of that anchor so the last falls inside 90 percent of the phase; keep their order.
- **Voice states:** an entry is *heard* when said and *confirmed* by a tap or "potrjeno" about 5 to 9 seconds later. An entry with `needs_correction` (low confidence) stays unconfirmed until the entry that `corrects` it. Chest pain and allergy patients carry one such pair.
- `monitor_feed[]`: vitals from the monitor at anchored offsets. Values may vary by a few units.
- The vitals, drugs and procedures are **synthetic and not clinical guidance**. Walking wounded (green) have one triage entry.
- The record is **pre-filled from these entries** by the model. After handover the paramedic reviews it and signs, assumed 10 minutes after arrival (`rules.human_timings_assumed_s`).

## 3. What the model must produce, and how every dashboard stays in sync

The model reads the script and produces **one ordered event stream** for all dashboards. The reference runs show the format; the model should follow it so every dashboard renders either one. Each event has `seq`, `t_s`, `clock`, `type`, `visible_on` (`dispatch`, `er`, `crew`, `map`), usually `call`, `unit`, `patient`, and `data`. Events with `"human": true` are steps a person does.

| Type | Seen by | Carries |
|---|---|---|
| `plan_made`, `unit_activated` | dispatch (activated also crew, map, ER) | **The model's decision**: which units, from where, why, minutes to arrive |
| `unit_status` | dispatch, crew, map (ER for patient statuses) | The Ministry chain: SPREJETO, NA POTI, NA KRAJU, PRI PACIENTU, S KRAJA, NA CILJU, PREDAJA PACIENTA, ZAKLJUČEK INT, ČIŠČENJE, PROST (helicopter also PRIHOD DO HELIKOPTERJA, VZLET, VRNITEV V BAZO; OKVARA) [S, Ministry data set] |
| `eta_update` | dispatch, crew, ER | Predicted arrival at the scene or the hospital |
| `reroute`, `traffic_delay` | all | The new path and the extra time when a closure or jam is on the way; a Slovenian message for the crew screen |
| `unit_diverted`, `unit_stand_down`, `unit_breakdown`, `replacement_dispatched` | dispatch, crew, map | Taking a vehicle off a yellow job, standing one down, a breakdown, a replacement |
| `demand_trigger_on`, `nonurgent_rebooked`, `agent_action`, `hospital_distribution` | dispatch (distribution also ER) | The surge trigger, scheduled transports moved to private vans, a one-line log of what the model did and why, the hospital overflow in D10 (human confirms) |
| `er_card_created`, `er_card_update`, `er_alert`, `er_bay_assigned` | ER (alert also dispatch; bay also crew) | **The ER dashboard**: priority, category, unit, status, ETA, latest vitals, treatments, alerts, destination |
| `voice_entry`, `voice_confirm`, `voice_check`, `monitor_vitals` | crew, dispatch, ER | The script's entries, with the unit that carries the patient filled in by the model |
| `handover_started`, `handover_summary`, `handover_done`, `record_review_prompt`, `record_signed` (human) | ER, crew, dispatch | Bay, the 15-minute handover, an auto-generated summary, review and signature at drop-off |
| the script's own events | as above | `call_received`, `triage`, `duplicate_call`, `caller_callback`, `road_event`, `data_feed_status`, `hospital_capacity_update` pass through to the stream |

A dashboard plays the stream in order and shows only its own events. Vehicle positions are not events: each vehicle has a `track` of `[t_s, lat, lon]` points that the map interpolates.

**Replay:** `python docs/scenario/tools/replay.py D12 --script` shows the input; `python docs/scenario/tools/replay.py D12 --dashboard er` shows what the ER dashboard receives from the reference run (also `--dashboard crew --unit A04`, `--positions 60`, `--speed 30`, `--json`).

## 4. Reference runs

`scenario/reference_runs/Dxx.json` is what a stand-in dispatcher did with the input. Besides the stream it holds `vehicles` (timeline, statuses, fuel, `track`), `patients` (who carried them), `world` and `idle_fleet`.

- **Paths** are road geometry from the public OSRM demo server (OpenStreetMap data, © OpenStreetMap contributors, ODbL), asked lightly and cached. The geometry is simplified, so between waypoints a vehicle moves in a straight line. **Times come from the scenario model**: waypoint times are spread along the path to match the model's arrival time. A failed request falls back to a synthetic path, marked in `path_source`.
- **Reroutes:** a closure placed on a vehicle's planned path reroutes every vehicle whose remaining path crosses it while it is active (an alternative route or a detour via a point beside the closure); the extra time is at least 8 percent of the remaining travel time plus 30 seconds. A jam makes the vehicle wait at the point.
- **Breakdown:** the vehicle stops, the nearest free ambulance is found from the fleet state at that moment, takes the patient (3 minutes) and continues. **Helicopter (D03a):** takes off 13 minutes after activation, flies a straight line at 200 km/h and takes the patient to the UKC helipad; the ground crew hand over and are released.
- **Mass casualty (D10):** an initial wave of 24 vehicles for the caller's estimate, the first team's report, 5 vehicles stood down, 19 stay, overflow to SB Celje.
- **Fuel:** a 75-litre tank at 12 litres per 100 km [A]; no fuel feed exists.

The model is **not** expected to match a reference run vehicle for vehicle. A different but defensible choice is fine; a choice that breaks a rule in [DISPATCH_SCENARIOS.md](DISPATCH_SCENARIOS.md) section 1 is not.

## 5. Mapping to the team's engine

- The engine accepts the `urgent_request` payloads in `dispatch_scenarios.json` (`engine_events`, all valid against its event model). A closure `road_event` maps to the engine's `road_closure` event (`lat`, `lon`, `radius_m`, `description`); weather to `weather_override`; a breakdown to `breakdown` with a `vehicle_id` that the harness fills in from whoever carries the patient.
- The rest (patients, voice entries, monitor feed, hospital reports, the per-dashboard stream) needs new code in the backend or a frontend that reads the files. This work changes no code in `backend/` or `frontend/`.

## 6. Rebuild

From the repository root (Python 3.10 or later, `pydantic` for the engine check; the first run asks the public routing server for paths and caches them in the system temp folder):

```bash
python docs/scenario/tools/dispatch_sim.py docs/scenario/dispatch_scenarios.json   # the stand-in dispatcher's decisions
python docs/scenario/tools/dispatch_validate.py
python docs/scenario/tools/run_playback.py            # reference runs, or give ids: D04 D12
python docs/scenario/tools/playback_validate.py
python docs/scenario/tools/make_input_scripts.py      # the input scripts
python docs/scenario/tools/scripts_validate.py        # no vehicle decisions in the input
python docs/scenario/tools/make_scenario_doc.py       # DISPATCH_SCENARIOS.md
```

The seed is fixed (20261123), so the output is repeatable.

## 7. Limits

- Closure and jam positions and times are fixed in the input. They were placed on the stand-in dispatcher's planned paths, so with different decisions a closure may affect other vehicles or none.
- Closures, jams, weather and hospital capacity are simulated stand-ins for promet.si, NAP and the hospitals' reports. Fuel is assumed.
- Vitals, drugs, procedures and Slovenian transcripts are synthetic drafts.
- The mass-casualty over-response and stand-down are modelled as the model's job; no published Slovenian rule for an over-sized first wave or for standing vehicles down was found [?] (the guideline covers METHANE, primary triage and calling additional help [S]).
- D10's scene report is 4 minutes after the first unit arrives; the reference run uses a fixed minute 12, about 16 seconds different.
- Paths are simplified OSRM geometry; timing follows the scenario model, whose single speed makes long runs slow. Treat arrival times over 30 minutes as conservative.
