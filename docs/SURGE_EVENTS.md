# Surge events: catalogue, Slovenian messages, expected replans

Data file: [`scenario/surge_events.json`](scenario/surge_events.json) (16 events, 6 playlists). Base data: [SCENARIO_DATA.md](SCENARIO_DATA.md). Research behind the numbers: [SURGE_AND_MULTI_SERVICE_COORDINATION.md](SURGE_AND_MULTI_SERVICE_COORDINATION.md), [LJUBLJANA_FLEET_AND_TEAMS.md](LJUBLJANA_FLEET_AND_TEAMS.md).

**Two kinds of event:**
- **engine** (6): the payload is exactly the shape of the team's `OperatorEvent` in `backend/app/models.py`. All six were validated against the real pydantic union. They can be posted to the existing `POST /events` as they are.
- **extension** (10): need new engine support. The payload is a proposal, not an agreed schema. I changed no code.

The Slovenian messages are my drafts and should be read by a native speaker before going on stage.

---

## 1. Catalogue

| Id | Event (EN / SL) | Time | Kind | Challenge item | Key parameters |
|---|---|---|---|---|---|
| S01 | Breakdown with equipment and patient on board / Okvara vozila z opremo in pacientom | 09:15 | engine | breakdown, equipment rule | `breakdown` A07; extension fields `equipment_aboard: EQ-002`, `patient_aboard` |
| S02 | Delay / Zamuda | 08:00 | engine | vehicle delays | `delay` A03, 25 min |
| S03 | Road closure near UKC / Zapora ceste pri UKC | 08:30 | engine | road closures | `road_closure` at 46.0565, 14.5300, 500 m |
| S04 | Urgent task: suspected stroke / Nujna naloga | 09:00 | engine | urgent new task | `urgent_request` home_polje to ukc, stretcher |
| S05 | Second urgent call while busy / Drugi nujni klic | 09:10 | engine | urgent new task, shortage | `urgent_request` home_crnuce to ukc |
| S06 | Snowfall / Sneženje | 07:30 | engine | delays | `weather_override` 3 cm, -2 °C |
| X01 | Fog grounds the helicopter for 1 h / Megla | 08:30 | extension | fog | H1 grounded 60 min at Brnik |
| X02 | Priority change / Sprememba prioritete | 09:30 | extension | priority change | trip `urgent` becomes `emergency` |
| X03 | Reduced hospital capacity, yellow alarm / Rumeni alarm v UKC | 10:00 | extension | reduced capacity | free resus bays 1, ICU 1, OR 1, ventilators 3; forecasts at +1 h, +2 h |
| X04 | Mass casualty on the motorway / Množična nesreča | 10:30 | extension | surge, shortage | 3 red, 4 yellow, 5 green; vehicle surge cap 25 |
| X05 | UKC helipad out of service / Izpad heliporta | 11:00 | extension | | substitute site at an army barracks, extra road leg |
| X06 | Radio down, phone app fallback / Radijska zveza ne deluje | 11:30 | extension | delays | position updates 10 s becomes 60 s (assumed) |
| X07 | Two crews off sick / Pomanjkanje posadk | 06:30 | extension | shortage of vehicles | A04 and A09 out, call-in lead time 45 min (assumed) |
| X08 | Private non-urgent providers added / Zasebni prevozniki | 10:45 | extension | shortage of vehicles | 4 transport vehicles, 30 min lead time (assumed) |
| X09 | Disaster declared, earthquake VII / Razglašena nesreča | 12:00 | extension | raised threat | vehicle cap 25, call-in, elective freeze, non-urgent providers, Red Cross |
| X10 | Organ transport task / Prevoz organa | 10:30 | extension | urgent run | heart, Maribor to UKC, 4 h limit |

**Where each real fact comes from:**
- **Fog** (X01): brief says 1 h; HNMP site says fog on a fifth to a quarter of days at Brnik.
- **Hospital alarm** (X03): green, yellow, red levels, free capacity reported within 15 minutes with +1 h and +2 h forecasts (2013 national guideline). UKC is the only large emergency hospital in the Ljubljana region, so a diversion is a long transfer.
- **Mass casualty** (X04): first team reports in METHANE format; an emergency ambulance is equipped for about 2 serious + 2 lighter patients; 25-vehicle surge at the UKC station.
- **Helipad out** (X05): UKC annual report 2025 says the helipad was closed temporarily by faults in the fire systems, and a substitute location at an army barracks was set up with the Ministry of Defence each time.
- **Radio** (X06): the dispatch plan of 2022 says the state radio network for health had coverage problems and a phone app is the backup.
- **Crew shortage** (X07): staff shortages are reported by UKC; call-in lead time is an assumption.
- **Private providers** (X08): the dispatcher checklist asks private ambulance services about availability; a minister's decision can include non-urgent providers in a declared disaster. Count and lead time are assumptions.
- **Disaster** (X09): Ministry of Health plan 2025, tiers by earthquake intensity (VI to VII may activate, VIII or more activates at once).
- **Organ** (X10): see SCENARIO_DATA.md; limits are from general medical sources.

---

## 2. Expected replan behaviour (testable)

These are the things a good repair should do, so you can check the demo's answer.

| Event | A good replan |
|---|---|
| S01 | A07's queued trips are reassigned; the patient on board is picked up first at the breakdown site as urgent; **EQ-002 is collected by another vehicle before it is delivered to zd_ig**; ambulances stay free for emergencies; a replacement vehicle is due within 2 hours at most (dispatch rulebook, art. 22) |
| S02 | Only trips that now miss `due_by` move |
| S03 | Legs crossing the closure are re-timed; east-side UKC trips use the nearest free vehicle |
| S04 / S05 | Nearest suitable free NRV goes, whoever area it is (rule since 3 June 2026), even if it must leave a lower-priority trip; both emergencies served; the rest of the city keeps cover |
| X01 | H1 takes nothing until 09:30; its tasks move to road vehicles; the organ task falls back to an ambulance if the deadline holds |
| X02 | `due_by` tightens to emergency slack; a nearer vehicle is chosen |
| X03 | Non-urgent arrivals at UKC are delayed or redirected to outpatient clinics; reds still go to UKC; planner reads the +1 h and +2 h forecast |
| X04 | Nearest NRVs go first, one per red; scheduled trips are cancelled or delayed; free teams are recalled; reserve vehicles staffed after the lead time; helicopter only if daylight and no fog; hospital distribution key applied |
| X05 | Helicopter drop-offs move to the substitute site with an added ambulance leg; compare with road only |
| X06 | Positions go stale, the ETA band widens, source health shows `stale` (the demo already has this state); paper forms are the fallback if the digital record fails |
| X07 | A04 and A09 leave the pool; reserve vehicles help only after the lead time |
| X08 | Scheduled and seated trips move to the added vehicles after their lead time; ambulances are freed for stretcher and red cases |
| X09 | Pool grows in steps with lead times: own, reserve, private, Red Cross; scheduled work suspended |
| X10 | Choose helicopter (about 31 min flight plus loading) if daylight and no fog; otherwise ambulance (about 80 to 95 min, estimate, route with OSRM); the deadline comes from cross-clamp plus the limit |

**Vehicle estimate for X04 [inference]:** by the 2 + 2 rule of thumb, 7 serious patients need at least 4 ambulances. In practice, one per red, one per two yellow and one per four green gives 3 + 2 + 2 = 7 vehicles. Mark this as an estimate in the demo.

---

## 3. Playlists (combinations to demo)

| Id | Name | Events | Story |
|---|---|---|---|
| P1 | Fog and an organ | X10, X01 | Heart in Maribor; fog arrives; helicopter out; road transport decided against the 4 h limit |
| P2 | Motorway mass casualty | X04, S05, X03, X08 | Many patients, a second call, hospital alarm, private providers added |
| P3 | Hospital pressure | X03, X02, X05 | Yellow alarm, a patient gets worse, helipad out |
| P4 | Comms and crews | X07, X06, S04 | Staff short, radio down, a stroke call arrives |
| P5 | Breakdown with equipment | S01, S03 | The challenge's own example plus a closure |
| P6 | Escalation to disaster | S06, S05, X04, X09 | Snow, incidents, then a declared disaster |

**For a 3-minute stage demo [suggestion]:** P5 shows the challenge's own rule and works with the existing engine events (S01 and S03 are engine events; only the equipment field is new). P1 shows the helicopter and the organ deadline but needs engine extensions. The team's own three scenarios map to S01 (stranded patient), S03 + S04 (stroke and closure) and S06 + S02 + S04 (snow cascade).

---

## 4. Slovenian messages for the assistant

For the level-up item: a message in Slovenian becomes an event and triggers a replan. Each message below maps to one event; the parsing needs context (which vehicle sent it).

| Message (SL) | Event | Parse to |
|---|---|---|
| Vozilo je obstalo. Oprema je še v njem. | S01 | breakdown of the sender's vehicle, equipment aboard |
| A07 ima okvaro motorja na Zaloški cesti, pacient je še v vozilu. | S01 | breakdown A07, patient aboard, location Zaloška |
| Zmanjkalo nam je goriva, stojimo v Medvodah. | S01 | breakdown, near Medvode |
| Zaradi kolone zamujamo približno petindvajset minut. | S02 | delay 25 min |
| Stojimo za zaledenelim tovornjakom, še dvajset minut. | S02 | delay 20 min |
| Zaloška cesta je zaprta zaradi nesreče pri UKC. | S03 | road closure at UKC |
| Cesta proti Vrhniki je zaprta, ne moremo mimo. | S03 | road closure on the Vrhnika road |
| Nujno! Sum na možgansko kap v Polju, pacient je na nosilih. | S04 | urgent request, stroke, stretcher |
| Klic: padec na ledu v Šiški, sum na zlom kolka. | S04 | urgent request, fall |
| Še en nujen klic: bolečina v prsih v Črnučah. | S05 | urgent request, chest pain |
| Sneži, ceste so spolzke, vozimo počasneje. | S06 | weather, snow |
| Megla na Brniku, helikopter ne more vzleteti vsaj eno uro. | X01 | helicopter grounded 60 min |
| HNMP je zaradi megle prizemljen. | X01 | helicopter grounded (duration unknown, ask or default 60 min) |
| Pacient P-1xx se je poslabšal, zdaj je nujno. | X02 | priority change to emergency |
| UKC je razglasil rumeni alarm. Prostih je le še en reanimacijski prostor. | X03 | hospital alarm yellow, resus bays 1 |
| Urgenca je polna, sprejemamo samo življenjsko ogrožene. | X03 | hospital accepts red only |
| Množična nesreča na primorski avtocesti pri Vrhniki: trije rdeči, štirje rumeni, pet zelenih. | X04 | mass casualty 3/4/5 |
| Prvi na kraju: avtobus se je prevrnil, okoli dvanajst ponesrečencev, potrebujemo dodatna vozila. | X04 | mass casualty about 12, vehicles needed |
| Heliport UKC je izpadel zaradi okvare gasilnega sistema, pristajamo v vojašnici Edvarda Peperka. | X05 | helipad out, substitute site |
| Radijska zveza ne deluje, prehajamo na aplikacijo Intervencije.net. | X06 | comms degraded |
| Reševalca na A04 sta zbolela, vozilo ne more na teren. | X07 | crew shortage A04 |
| Dve ekipi manjkata, kličemo rezervne iz doma. | X07 | crew shortage, call-in |
| Zasebni prevozniki so na voljo: štiri sanitetna vozila v 30 minutah. | X08 | capacity added 4, 30 min |
| Potres jakosti sedem po evropski lestvici, državni načrt je aktiviran, minister je aktiviral načrt ministrstva za zdravje. | X09 | disaster declared |
| Srce za presaditev v UKC Maribor je pripravljeno, prevzem ob 10.30. | X10 | organ task, heart, 10:30 |

**Parsing traps worth testing:**
- "Vozilo je obstalo" has **no vehicle id**; the sender's id must come from the channel.
- "Je obstalo" could mean a breakdown or just a stop in traffic; the follow-up "Oprema je še v njem" settles it.
- Numbers written as words ("petindvajset", "dvajset") and times written "10.30".
- "Prizemljen" with no duration.
- Place names in the locative ("v Polju", "v Šiški", "v Črnučah", "v Medvodah", "pri Vrhniki") must map to the nominative place ids.

---

## 5. Assumptions to confirm before showing

- The numbers of added private vehicles, call-in lead times, degraded radio interval and substitute-site distance are my assumptions.
- The mass-casualty site and A1 location are illustrative.
- The organ deadline (arrival by 13:00) is my choice.
- Hospital capacity numbers are invented.
