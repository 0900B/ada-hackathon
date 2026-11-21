# Dispatch scenarios: from one call to a mass-casualty event

Scenarios for the agentic flow in [AGENTIC_DISPATCH_DESIGN.md](AGENTIC_DISPATCH_DESIGN.md). They differ in the number of calls, the urgency, the number of patients and so in the **number of responding vehicles**: from **one ambulance** (D01) to **19 vehicles** for 22 patients (D10). Machine-readable file: [`scenario/dispatch_scenarios.json`](scenario/dispatch_scenarios.json). Built 2026-11-21. Everything is synthetic.

**Tags:** **[S]** from a source; **[SS]** from a news summary; **[I]** my inference; **[A]** an assumption to confirm.

---

## 1. How the scenarios work

**Colour scheme (kept until told otherwise):** **red** = life-threatening, engine priority `emergency`; **yellow** = possible danger or needs a doctor's assessment, engine priority `urgent`; **non-urgent** = scheduled transport, engine priority `scheduled`. Green appears only as the on-scene severity of walking patients in multi-patient incidents (D05, D10).

**Capacity rule:** **one patient per ambulance.** Every red and every yellow patient needs an ambulance of their own. Green patients (walking wounded) do not go by ambulance: they go by van or bus, 4 per van [A, to confirm].

**Doctors:** a doctor vehicle goes to a red call when triage says a doctor is needed. Which red cases get a doctor is a triage output (the SloIn NMP text is not public). I set it for cardiac arrest, trapped or severe injury, chest pain, severe breathing difficulty and heavy bleeding, and not for a suspected stroke (ambulance and ER pre-alert) [A]. In 2024 about a quarter of urgent interventions at the Ljubljana station had a doctor on board [S, `OPERATIONS_DETAILS.md`].

**Rules used by the model** (the design's rules, run on a seeded stand-in for the dispatcher):

| Rule | Behaviour |
|---|---|
| Red ambulance | Nearest suitable public unit by ETA from its live position, **any area**. A private ambulance only if no public unit reaches in 15 minutes **and** the private one is faster |
| Yellow ambulance | Units in the Ljubljana emergency area only. Other areas only once the demand trigger is on **and** the local arrival is over 30 minutes. A private ambulance only over 45 minutes [A] |
| Scheduled (non-urgent) transports | Stay with public units. Once the trigger is on they go to private vans (at most 6 are available [A]) |
| Doctor vehicle | One per red call with a doctor flag; red calls may draw from other areas, yellow only from the Ljubljana area |
| Helicopter | Considered for red calls that ask for it; only 08:00 to 16:30 local, and not in fog or snow at Brnik [S, `EMS_RESEARCH.md`] |
| Taking a unit off a job | A red call may take a unit that is still driving to a yellow or scheduled job. A yellow call may take one only from a scheduled job. A unit with the patient aboard is never taken. The displaced yellow call is re-planned and its patient told |
| Demand trigger | Free ambulances in the Ljubljana area are 25 percent or less of those crewed, **or** a red arrival is predicted over 15 minutes [A thresholds] |
| Exit time | 1 minute for an ambulance, 5 minutes for a doctor vehicle, when a unit starts from rest (2026 rulebook, reported) [SS] |

**Counting:** "vehicles sent" counts **different vehicles**. A vehicle taken off one call and sent to another counts once. A vehicle that finishes one job and takes a later call also counts once (the reuse is shown where it happens). Fire, police, first responders and the mass-casualty trailer are alerted by dispatch and listed separately; they are not part of the ambulance fleet.

**Travel model:** the same constants as `backend/app/routing.py`: road distance is 1.35 times the straight line, 42 km/h, lights and sirens ×1.3 for red, the engine's weather factor and its time-of-day traffic profile (rush hour 0.65). Units that are driving are placed along their route, so a unit can be diverted from where it is now. **Limits:** one speed for all distances means long runs look slow (a Postojna ambulance needs over an hour to reach Vrhnika in rush hour), and the engine's rush-hour factor of 0.65 is a strong slowdown. Real long runs on a motorway are faster. Treat ETAs over 30 minutes as conservative.

**Service times [A]:** 20 minutes at the scene for red, 15 for yellow, 12 minutes handover, 8 minutes cleaning and restocking.

### The fleet at the start

| | Day (07:00 to 19:00) | Night |
|---|---|---|
| Ambulances in the Ljubljana emergency area | 26 | 22 |
| Doctor vehicles in the Ljubljana area | 10 | 9 |
| Ambulances in neighbouring regions (Kranj, Škofja Loka, Tržič, Litija, Zagorje, Trbovlje, Trebnje, Novo mesto) | 16 | 13 |
| Doctor vehicles in neighbouring regions | 5 | 5 |
| Public sanitary vans (UKC station) | 2 | 2 |
| Private ambulances with qualified crews [A] | 3 | 3 |
| Private non-urgent vans [A] | 6 | 6 |
| Helicopter H1 at Brnik | 08:00 to 16:30 only | none |

Team counts come from the 2026 insurer's decree (24.0 ambulance teams and 10 doctor-vehicle teams in the Ljubljana area). A count of 1.5 teams becomes 2 by day and 1 by night [A]. Private bases and crew qualifications are not published [?]. A share of units (the "background load") is busy with scheduled transports at the start; 30 percent is the all-day average from about 134 interventions a day, two thirds of them non-urgent.

---

## 2. Overview

**What each scenario asks for:**

| Scenario | Start | Calls | Patients (red / yellow / green) | Vehicles needed by the rules |
|---|---|---|---|---|
| D01 Quiet morning: one yellow call | 09:00 | 1 | 0 / 1 / 0 | 1 ambulance |
| D02 Chest pain: ambulance and doctor start from different places | 10:30 | 1 | 1 / 0 / 0 | 1 ambulance, 1 doctor vehicle |
| D03a Cardiac arrest at a mountain trailhead, helicopter flies | 11:15 | 1 | 1 / 0 / 0 | 1 ambulance, 1 doctor vehicle, helicopter |
| D03b Same call with fog at Brnik: helicopter grounded | 11:15 | 1 | 1 / 0 / 0 | 1 ambulance, 1 doctor vehicle, helicopter |
| D04 Two reds compete for the nearest unit | 13:50 | 3 | 2 / 1 / 0 | 3 ambulances, 1 doctor vehicle |
| D05 Multi-vehicle crash on the ring road at dusk | 17:20 | 1 | 2 / 2 / 2 | 4 ambulances, 2 doctor vehicles, helicopter, 1 van |
| D06 Rush hour mix: one red, five yellow, scheduled discharges | 16:00 | 6 | 1 / 5 / 0 | 6 ambulances, 1 doctor vehicle |
| D07 Busy afternoon, teams near full capacity | 15:00 | 11 | 3 / 8 / 0 | 11 ambulances, 2 doctor vehicles |
| D08 Saturday night, thin staffing, three reds | 03:20 | 3 | 3 / 0 / 0 | 3 ambulances, 3 doctor vehicles |
| D09 Snow and ice morning: many calls, slow roads | 07:30 | 14 | 2 / 12 / 0 | 14 ambulances, 2 doctor vehicles, helicopter |
| D10 Mass-casualty: bus crash on the motorway, 22 patients | 18:10 | 1 | 4 / 8 / 10 | 12 ambulances, 4 doctor vehicles, helicopter, 3 vans |
| D11 Everything is out: no public unit is free within 15 minutes | 16:00 | 4 | 2 / 2 / 0 | 4 ambulances, 2 doctor vehicles |
| D12 Everything at once: seven overlapping calls with a closure, a jam, a breakdown and a priority change | 10:00 | 7 | 3 / 4 / 0 | 7 ambulances, 3 doctor vehicles |

**What was sent** (different vehicles; fire, police and similar are alerted by dispatch and listed in the last column):

| Scenario | Ambulances | Doctor vehicles | Helicopter | Vans | **All vehicles sent** | Initial wave | From other regions | Private (ambulances / vans) | Other services alerted |
|---|---|---|---|---|---|---|---|---|---|
| D01 | 1 | 0 | no | 0 | **1** | same | 0 | 0 / 0 | none |
| D02 | 1 | 1 | no | 0 | **2** | same | 0 | 0 / 0 | first responders |
| D03a | 1 | 1 | yes | 0 | **3** | same | 0 | 0 / 0 | first responders |
| D03b | 1 | 1 | no | 0 | **2** | same | 0 | 0 / 0 | first responders |
| D04 | 3 | 1 | no | 0 | **4** | same | 0 | 0 / 0 | first responders |
| D05 | 4 | 2 | no | 1 | **7** | same | 0 | 0 / 0 | first responders, fire brigade, police |
| D06 | 6 | 1 | no | 0 | **7** | same | 0 | 0 / 0 | none |
| D07 | 10 | 2 | no | 0 | **12** | same | 1 | 0 / 0 | none |
| D08 | 3 | 3 | no | 0 | **6** | same | 0 | 0 / 0 | first responders, fire brigade, police |
| D09 | 12 | 2 | no | 0 | **14** | same | 0 | 0 / 0 | fire brigade, police |
| D10 | 12 | 4 | no | 3 | **19** | 24 | 2 | 0 / 3 | first responders, fire brigade, police, mass-casualty trailer, incident commander and triage team |
| D11 | 4 | 2 | no | 0 | **6** | same | 0 | 2 / 0 | first responders, fire brigade, police |
| D12 | 7 | 3 | no | 0 | **10** | same | 0 | 0 / 0 | first responders, police |

**Reading the tables:** *vehicles needed by the rules* come from the patient counts and doctor flags. *All vehicles sent* can be smaller when a vehicle serves two calls one after the other (D07, D09) and smaller when the helicopter cannot fly (D03b, D05, D09, D10). The ambulance column includes private ambulances; the private column splits them out.

---

## 3. The scenarios

### D01. Quiet morning: one yellow call

**Shows:** The smallest case. One patient, one ambulance, procedure-first selection from a live position, no escalation.

**Setup:** 09:00 start, weekday, day roster; dry; speed factor from weather 1.0; 30 percent of units busy with scheduled transports at the start. 1 call, 1 patient.

| Call | Time | Place | Level | Patients | Needs (by rule) | Sent (unit, minutes to arrive) |
|---|---|---|---|---|---|---|
| D01-C1 | 09:00 | Vič (residential block) | yellow | 1 yellow | 1 ambulance | A01 UKC station, 10 min |

**All units sent:**

- **Ambulances (1):** A01
- **From other regions:** none
- **Private units:** none
- **Other services alerted by dispatch (not part of the ambulance fleet):** none

- **Vehicles needed by the rules:** 1 ambulance. **Different vehicles sent:** 1 (helicopter included where it flew).
- **Demand trigger:** not reached.
- **Ljubljana-area ambulances:** 18 of 26 free at the lowest point; at most 31 percent busy.

**What to point out:**

- A01 (UKC station) goes, 10 minutes away, and is back in service about 53 minutes after the call (scene, transport, handover, cleaning).
- The area rule and the demand trigger are never touched.
- Good as the first click of the demo: it shows what "nothing special" looks like.

**Engine events:** 1 `urgent_request` payload in the JSON (`engine_events`), each valid against the engine's event model.

---
### D02. Chest pain: ambulance and doctor start from different places

**Shows:** One red call whose triage response includes a doctor. The two units start at different bases.

**Setup:** 10:30 start, weekday, day roster; dry; speed factor from weather 1.0; 35 percent of units busy with scheduled transports at the start. 1 call, 1 patient.

| Call | Time | Place | Level | Patients | Needs (by rule) | Sent (unit, minutes to arrive) |
|---|---|---|---|---|---|---|
| D02-C1 | 10:30 | Bežigrad | red | 1 red | 1 ambulance, 1 doctor vehicle + first responders | A02 UKC station, 4 min; D02 ZD Ljubljana, 7 min |

**All units sent:**

- **Ambulances (1):** A02
- **Doctor vehicles (1):** D02
- **From other regions:** none
- **Private units:** none
- **Other services alerted by dispatch (not part of the ambulance fleet):** first responders

- **Vehicles needed by the rules:** 1 ambulance, 1 doctor vehicle. **Different vehicles sent:** 2 (helicopter included where it flew).
- **Demand trigger:** not reached.
- **First ambulance to each red call:** D02-C1 4.4 min; 15-minute target met.
- **Ljubljana-area ambulances:** 18 of 26 free at the lowest point; at most 31 percent busy.

**What to point out:**

- A02 starts at the UKC station and arrives in 4 minutes; D02 starts at ZD Ljubljana and arrives in 7 minutes. Each gets its own route.
- The ER dashboard shows the inbound card with the live ETA the moment the units are activated.
- First responders nearest the scene are also activated for a life threat (art. 17) [S].

**Engine events:** 1 `urgent_request` payload in the JSON (`engine_events`), each valid against the engine's event model.

---
### D03a. Cardiac arrest at a mountain trailhead, helicopter flies

**Shows:** A red call far from any base. The agent races the helicopter against the ground units and sends both.

**Setup:** 11:15 start, weekday, day roster; dry; speed factor from weather 1.0; 35 percent of units busy with scheduled transports at the start. 1 call, 1 patient.

| Call | Time | Place | Level | Patients | Needs (by rule) | Sent (unit, minutes to arrive) |
|---|---|---|---|---|---|---|
| D03a-C1 | 11:15 | Kamniška Bistrica trailhead | red | 1 red | 1 ambulance, 1 doctor vehicle, helicopter + first responders | A16 ZD Kamnik, 15 min; D05 ZD Kamnik, 19 min |

**All units sent:**

- **Ambulances (1):** A16
- **Doctor vehicles (1):** D05
- **Helicopter:** H1 from Brnik
- **From other regions:** none
- **Private units:** none
- **Other services alerted by dispatch (not part of the ambulance fleet):** first responders

- **Vehicles needed by the rules:** 1 ambulance, 1 doctor vehicle, helicopter. **Different vehicles sent:** 3 (helicopter included where it flew).
- **Demand trigger:** not reached.
- **First ambulance to each red call:** D03a-C1 14.7 min; 15-minute target met.
- **Ljubljana-area ambulances:** 14 of 26 free at the lowest point; at most 46 percent busy.

**What to point out:**

- Helicopter H1 from Brnik: 13 min to take-off + 4 min flight + landing = about 20 min; ground ETA of the first ambulance 15 min.
- The Kamnik ambulance arrives in 15 minutes and the Kamnik doctor vehicle in 19. The two arrival times are close, so both go. What the helicopter adds is a doctor on scene and a much shorter way to UKC [I]; the model does not yet compute time to hospital.
- First responders nearest the scene are activated for the cardiac arrest (art. 17) [S].

**Engine events:** 1 `urgent_request` payload in the JSON (`engine_events`), each valid against the engine's event model.

---
### D03b. The same call with fog at Brnik: helicopter grounded

**Shows:** Fog grounds the helicopter. The ground units already left in the first minute, so nothing has to be repaired.

**Setup:** 11:15 start, weekday, day roster; dry; speed factor from weather 1.0; 35 percent of units busy with scheduled transports at the start. 1 call, 1 patient.

| Call | Time | Place | Level | Patients | Needs (by rule) | Sent (unit, minutes to arrive) |
|---|---|---|---|---|---|---|
| D03b-C1 | 11:15 | Kamniška Bistrica trailhead | red | 1 red | 1 ambulance, 1 doctor vehicle, helicopter + first responders | A15 ZD Kamnik, 15 min; D05 ZD Kamnik, 19 min |

**All units sent:**

- **Ambulances (1):** A15
- **Doctor vehicles (1):** D05
- **Helicopter:** not sent (fog at Brnik)
- **From other regions:** none
- **Private units:** none
- **Other services alerted by dispatch (not part of the ambulance fleet):** first responders

- **Vehicles needed by the rules:** 1 ambulance, 1 doctor vehicle, helicopter. **Different vehicles sent:** 2 (helicopter included where it flew).
- **Demand trigger:** not reached.
- **First ambulance to each red call:** D03b-C1 14.7 min; 15-minute target met.
- **Ljubljana-area ambulances:** 19 of 26 free at the lowest point; at most 27 percent busy.

**What to point out:**

- Helicopter not available: fog at Brnik; ground units only.
- The ground response is the same as in D03a: that is the point. Weather only matters if it moves assets before the event.
- The brief's fog event (X01 in `SURGE_EVENTS.md`) covers the case where the fog arrives after a launch.

**Engine events:** 1 `urgent_request` payload in the JSON (`engine_events`), each valid against the engine's event model.

---
### D04. Two reds compete for the nearest unit

**Shows:** A yellow call is on its way when two reds arrive three minutes apart. Shows taking a unit off a lower-priority job and re-planning it.

**Setup:** 13:50 start, weekday, day roster; dry; speed factor from weather 1.0; 40 percent of units busy with scheduled transports at the start. 3 calls, 3 patients.

| Call | Time | Place | Level | Patients | Needs (by rule) | Sent (unit, minutes to arrive) |
|---|---|---|---|---|---|---|
| D04-C0 | 13:50 | Bežigrad | yellow | 1 yellow | 1 ambulance | A08 UKC station, 6 min [re-planned at minute 5] (earlier choices A01, A02 were taken off this call for red calls) |
| D04-C1 | 13:52 | Šiška | red | 1 red | 1 ambulance, 1 doctor vehicle + first responders | A01 UKC station, 6 min; D02 ZD Ljubljana, 7 min |
| D04-C2 | 13:55 | Črnuče | red | 1 red | 1 ambulance | A02 UKC station, 7 min |

**All units sent:**

- **Ambulances (3):** A01, A02, A08
- **Doctor vehicles (1):** D02
- **From other regions:** none
- **Private units:** none
- **Other services alerted by dispatch (not part of the ambulance fleet):** first responders

- **Vehicles needed by the rules:** 3 ambulances, 1 doctor vehicle. **Different vehicles sent:** 4 (helicopter included where it flew).
- **Demand trigger:** not reached.
- **Units taken off another job:** 2.
- **First ambulance to each red call:** D04-C1 6.0 min, D04-C2 7.3 min; 15-minute target met.
- **Ljubljana-area ambulances:** 13 of 26 free at the lowest point; at most 50 percent busy.

**What to point out:**

- At minute 2 the red call D04-C1 takes A01, which was still on its way to the yellow call D04-C0. The yellow patient is re-planned to A02 and told.
- At minute 5 the second red call takes A02 the same way. The yellow patient is re-planned again, to A08, and told again.
- Three calls, four vehicles in all: three ambulances (one for each patient) and one doctor vehicle for the cardiac arrest. The stroke call gets an ambulance and an ER pre-alert, no doctor [A].
- If the triage code did not give a clinical order between the two reds, the dispatcher would be asked. Here the nearest unit simply goes to the call that came first.

**Engine events:** 3 `urgent_request` payloads in the JSON (`engine_events`), each valid against the engine's event model.

---
### D05. Multi-vehicle crash on the ring road at dusk

**Shows:** One incident, six patients (2 red, 2 yellow, 2 green): seven vehicles plus fire, police and first responders.

**Setup:** 17:20 start, weekday, day roster; light rain, 4 °C; speed factor from weather 0.93; 45 percent of units busy with scheduled transports at the start. 1 call, 6 patients.

| Call | Time | Place | Level | Patients | Needs (by rule) | Sent (unit, minutes to arrive) |
|---|---|---|---|---|---|---|
| D05-C1 | 17:20 | East ring road (synthetic crash site) | red | 2 red, 2 yellow, 2 green | 4 ambulances, 2 doctor vehicles, helicopter, 1 van + first responders, fire, police | A03 UKC station, 13 min; A02 UKC station, 14 min; A04 UKC station, 18 min; A05 UKC station, 18 min; D01 ZD Ljubljana, 20 min; D02 ZD Ljubljana, 26 min; T02 UKC station (sanitary), 18 min |

**All units sent:**

- **Ambulances (4):** A02, A03, A04, A05
- **Doctor vehicles (2):** D01, D02
- **Public sanitary vans (1):** T02
- **Helicopter:** not sent (outside the daylight window (08:00 to 16:30), local time 17:19)
- **From other regions:** none
- **Private units:** none
- **Other services alerted by dispatch (not part of the ambulance fleet):** first responders, fire brigade, police

- **Vehicles needed by the rules:** 4 ambulances, 2 doctor vehicles, helicopter, 1 van. **Different vehicles sent:** 7 (helicopter included where it flew).
- **Demand trigger:** not reached.
- **Units taken off another job:** 1.
- **First ambulance to each red call:** D05-C1 13.1 min; 15-minute target met.
- **Ljubljana-area ambulances:** 10 of 26 free at the lowest point; at most 62 percent busy.

**What to point out:**

- Four ambulances (one for each red and yellow patient), two doctor vehicles (one for each red patient) and one sanitary van for the two green patients. The first ambulance arrives in 13 minutes: rush hour and a closed lane (×0.85) slow every unit.
- Helicopter not available: outside the daylight window (08:00 to 16:30), local time 17:19; ground units only.
- The ReCO alerts fire and police in parallel for a road accident [S, `EMS_RESEARCH.md`]; the agent only shows them on the incident.
- This is below the mass-casualty threshold: no human declaration is needed, the dispatcher's triage already set the levels.

**Engine events:** 1 `urgent_request` payload in the JSON (`engine_events`), each valid against the engine's event model.

---
### D06. Rush hour mix: one red, five yellow

**Shows:** Steady pressure over an hour in rush hour. The agent keeps the area rule and uses the nearest free unit each time.

**Setup:** 16:00 start, weekday, day roster; dry; speed factor from weather 1.0; 45 percent of units busy with scheduled transports at the start. 6 calls, 6 patients.

| Call | Time | Place | Level | Patients | Needs (by rule) | Sent (unit, minutes to arrive) |
|---|---|---|---|---|---|---|
| D06-C1 | 16:00 | Moste | yellow | 1 yellow | 1 ambulance | A01 UKC station, 5 min |
| D06-C2 | 16:08 | Črnuče | red | 1 red | 1 ambulance, 1 doctor vehicle | A04 UKC station, 5 min; D02 ZD Ljubljana, 16 min |
| D06-C3 | 16:22 | Kočevje (outskirts) | yellow | 1 yellow | 1 ambulance | A20 ZD Kočevje, 5 min |
| D06-C4 | 16:31 | Polje | yellow | 1 yellow | 1 ambulance | A03 UKC station, 16 min |
| D06-C5 | 16:44 | Rudnik | yellow | 1 yellow | 1 ambulance | A08 UKC station, 8 min |
| D06-C6 | 16:55 | Trzin | yellow | 1 yellow | 1 ambulance | A13 ZD Domžale, 10 min |

**All units sent:**

- **Ambulances (6):** A01, A03, A04, A08, A13, A20
- **Doctor vehicles (1):** D02
- **From other regions:** none
- **Private units:** none
- **Other services alerted by dispatch (not part of the ambulance fleet):** none

- **Vehicles needed by the rules:** 6 ambulances, 1 doctor vehicle. **Different vehicles sent:** 7 (helicopter included where it flew).
- **Demand trigger:** not reached.
- **Units taken off another job:** 2.
- **Scheduled transports:** 8 requested at minute 30; 0 to private vans, 8 stay with public units.
- **First ambulance to each red call:** D06-C2 4.7 min; 15-minute target met.
- **Ljubljana-area ambulances:** 17 of 26 free at the lowest point; at most 35 percent busy.

**What to point out:**

- Each call gets the nearest unit; the trigger never fires, so the eight scheduled discharges at minute 30 stay with public units.
- The one red call (a fall from a ladder with a head injury) gets an ambulance and a doctor vehicle; the five yellow calls get one ambulance each: seven vehicles in all.
- The yellow call in Kočevje is served by the Kočevje team, inside the Ljubljana emergency area, and not by an ambulance from the city.
- This is what a normal busy hour looks like for the dispatcher: nothing to decide, only to watch.

**Engine events:** 6 `urgent_request` payloads in the JSON (`engine_events`), each valid against the engine's event model.

---
### D07. Busy afternoon, teams near full capacity

**Shows:** Eleven calls in 75 minutes (3 red, 8 yellow) while most ambulances are out. The demand trigger is on from the start.

**Setup:** 15:00 start, weekday, day roster; light rain, 6 °C; speed factor from weather 0.93; 75 percent of units busy with scheduled transports at the start. 11 calls, 11 patients.

| Call | Time | Place | Level | Patients | Needs (by rule) | Sent (unit, minutes to arrive) |
|---|---|---|---|---|---|---|
| D07-C1 | 15:00 | Šiška | red | 1 red | 1 ambulance, 1 doctor vehicle | A01 UKC station, 11 min; D01 ZD Ljubljana, 13 min |
| D07-C2 | 15:04 | Moste | yellow | 1 yellow | 1 ambulance | A08 UKC station, 5 min |
| D07-C3 | 15:09 | Domžale (outskirts) | red | 1 red | 1 ambulance, 1 doctor vehicle | A13 ZD Domžale, 6 min; D04 ZD Domžale, 10 min |
| D07-C4 | 15:14 | Vrhnika (outskirts) | yellow | 1 yellow | 1 ambulance | A25 ZD Postojna, 61 min |
| D07-C5 | 15:20 | Grosuplje (outskirts) | yellow | 1 yellow | 1 ambulance | A05 UKC station, 44 min |
| D07-C6 | 15:27 | Bežigrad | yellow | 1 yellow | 1 ambulance | A04 UKC station, 7 min [re-planned at minute 33] (earlier choices A06 were taken off this call for red calls) |
| D07-C7 | 15:33 | Črnuče | red | 1 red | 1 ambulance | A06 UKC station, 10 min |
| D07-C8 | 15:41 | Vič (residential block) | yellow | 1 yellow | 1 ambulance | A03 UKC station, 13 min |
| D07-C9 | 15:50 | Medvode (outskirts) | yellow | 1 yellow | 1 ambulance | A30 ZD Škofja Loka (other region), 32 min |
| D07-C10 | 15:58 | Škofljica | yellow | 1 yellow | 1 ambulance | A08 UKC station, 30 min |
| D07-C11 | 16:08 | Polje | yellow | 1 yellow | 1 ambulance | A02 UKC station, 17 min |

**All units sent:**

- **Ambulances (10):** A01, A02, A03, A04, A05, A06, A08, A13, A25, A30 (other regions: A30 ZD Škofja Loka)
- **Doctor vehicles (2):** D01, D04
- **From other regions:** A30 (ZD Škofja Loka)
- **Private units:** none
- **Other services alerted by dispatch (not part of the ambulance fleet):** none
- **Reuse:** 13 assignments were served by 12 different vehicles, because 1 vehicle(s) finished one job and took the next.

- **Vehicles needed by the rules:** 11 ambulances, 2 doctor vehicles. **Different vehicles sent:** 12 (helicopter included where it flew).
- **Demand trigger:** on at minute 0 (free ambulances in the Ljubljana area 6 of 26 (25 percent or less)).
- **Units taken off another job:** 3.
- **Scheduled transports:** 15 requested at minute 30; 6 to private vans, 9 stay with public units.
- **First ambulance to each red call:** D07-C1 10.6 min, D07-C3 5.6 min, D07-C7 9.5 min; 15-minute target met.
- **Ljubljana-area ambulances:** 3 of 26 free at the lowest point; at most 88 percent busy.

**What to point out:**

- The trigger is on at minute 0 (free ambulances in the Ljubljana area 6 of 26 (25 percent or less)). At minute 30, 15 scheduled transports are requested: 6 go to private vans (the whole private-van pool) and 9 stay with public units.
- One yellow call goes to a unit from another region (A30): the local wait was over 30 minutes and the trigger was on.
- Eleven ambulance jobs and two doctor jobs are served by 12 different vehicles, because 1 ambulance finished a job and took a later one.
- A yellow call in Vrhnika waits over an hour in the model because the nearest local units are busy and other regions are slower in rush hour. That is the flat-speed limit noted above, and also a real warning about thin cover.
- 3 units were taken off scheduled or yellow jobs for red calls.

**Engine events:** 11 `urgent_request` payloads in the JSON (`engine_events`), each valid against the engine's event model.

---
### D08. Saturday night, thin staffing, three reds

**Shows:** Night roster (22 ambulances in the area against 26 by day), no helicopter, three reds in 21 minutes at different ends of the area.

**Setup:** 03:20 start, weekend, night roster; dry; speed factor from weather 1.0; 50 percent of units busy with scheduled transports at the start. 3 calls, 3 patients.

| Call | Time | Place | Level | Patients | Needs (by rule) | Sent (unit, minutes to arrive) |
|---|---|---|---|---|---|---|
| D08-C1 | 03:20 | Domžale (outskirts) | red | 1 red | 1 ambulance, 1 doctor vehicle + first responders | A13 ZD Domžale, 3 min; D04 ZD Kamnik, 16 min |
| D08-C2 | 03:32 | Vrhnika (outskirts) | red | 1 red | 1 ambulance, 1 doctor vehicle + fire, police | A10 UKC outpost Vrhnika, 2 min; D06 ZD Vrhnika, 8 min |
| D08-C3 | 03:41 | Grosuplje (outskirts) | red | 1 red | 1 ambulance, 1 doctor vehicle + police | A11 UKC outpost Ivančna Gorica, 15 min; D05 ZD Ivančna Gorica/Grosuplje, 7 min |

**All units sent:**

- **Ambulances (3):** A10, A11, A13
- **Doctor vehicles (3):** D04, D05, D06
- **From other regions:** none
- **Private units:** none
- **Other services alerted by dispatch (not part of the ambulance fleet):** first responders, fire brigade, police

- **Vehicles needed by the rules:** 3 ambulances, 3 doctor vehicles. **Different vehicles sent:** 6 (helicopter included where it flew).
- **Demand trigger:** on at minute 21 (predicted red arrival 15 min (over 15)).
- **Units taken off another job:** 2.
- **First ambulance to each red call:** D08-C1 3.0 min, D08-C2 2.2 min, D08-C3 15.1 min; 15-minute target missed.
- **Ljubljana-area ambulances:** 11 of 22 free at the lowest point; at most 50 percent busy.

**What to point out:**

- Each red call gets one ambulance and one doctor vehicle: three ambulances and three doctor vehicles, six vehicles for three patients. The stab wound with heavy bleeding gets a doctor too [A]; fire and police are alerted for the crash and the stabbing.
- The first two reds are reached in 3 and 2 minutes. The third, in Grosuplje, is 15.1 minutes away, just over the 15-minute target.
- That predicted arrival turns the demand trigger on. A private ambulance is **not** used: it needs 15 minutes to mobilise, so it would not be faster than the public unit already available. The rule "private only if faster" holds.
- The dispatcher is told that the target is missed by a fraction. This is a case where the system shows its reasoning and does not escalate for the sake of it.

**Engine events:** 3 `urgent_request` payloads in the JSON (`engine_events`), each valid against the engine's event model.

---
### D09. Snow and ice morning: many calls, slow roads

**Shows:** Fourteen calls in two hours. Snow cuts speed to 0.6 of normal on top of rush hour.

**Setup:** 07:30 start, weekday, day roster; snow 3 cm, -2.0 °C; speed factor from weather 0.6; 55 percent of units busy with scheduled transports at the start. 14 calls, 14 patients.

| Call | Time | Place | Level | Patients | Needs (by rule) | Sent (unit, minutes to arrive) |
|---|---|---|---|---|---|---|
| D09-C1 | 07:30 | Zaloška cesta | red | 1 red | 1 ambulance, 1 doctor vehicle, helicopter + fire, police | A02 UKC station, 4 min; D02 ZD Ljubljana, 12 min |
| D09-C2 | 07:36 | Moste | yellow | 1 yellow | 1 ambulance | A01 UKC station, 7 min |
| D09-C3 | 07:42 | Polje | yellow | 1 yellow | 1 ambulance | A06 UKC station, 25 min |
| D09-C4 | 07:49 | Šiška | yellow | 1 yellow | 1 ambulance | A09 UKC station, 20 min |
| D09-C5 | 07:55 | Črnuče | yellow | 1 yellow | 1 ambulance | A07 UKC station, 11 min |
| D09-C6 | 08:01 | Domžale (outskirts) | red | 1 red | 1 ambulance, 1 doctor vehicle | A14 ZD Domžale, 6 min; D04 ZD Domžale, 12 min |
| D09-C7 | 08:08 | Rudnik | yellow | 1 yellow | 1 ambulance | A03 UKC station, 17 min |
| D09-C8 | 08:14 | Vič (residential block) | yellow | 1 yellow | 1 ambulance | A08 UKC station, 21 min |
| D09-C9 | 08:22 | Vrhnika (outskirts) | yellow | 1 yellow | 1 ambulance | A17 ZD Logatec, 38 min |
| D09-C10 | 08:31 | Grosuplje (outskirts) | yellow | 1 yellow | 1 ambulance | A11 UKC outpost Ivančna Gorica, 40 min |
| D09-C11 | 08:40 | Bežigrad | yellow | 1 yellow | 1 ambulance | A01 UKC station, 8 min |
| D09-C12 | 08:53 | Kamnik (outskirts) | yellow | 1 yellow | 1 ambulance | A16 ZD Kamnik, 6 min |
| D09-C13 | 09:06 | Medvode (outskirts) | yellow | 1 yellow | 1 ambulance | A04 UKC station, 49 min |
| D09-C14 | 09:20 | Škofljica | yellow | 1 yellow | 1 ambulance | A02 UKC station, 35 min |

**All units sent:**

- **Ambulances (12):** A01, A02, A03, A04, A06, A07, A08, A09, A11, A14, A16, A17
- **Doctor vehicles (2):** D02, D04
- **Helicopter:** not sent (snow and low cloud at Brnik (assumed))
- **From other regions:** none
- **Private units:** none
- **Other services alerted by dispatch (not part of the ambulance fleet):** fire brigade, police
- **Reuse:** 16 assignments were served by 14 different vehicles, because 2 vehicle(s) finished one job and took the next.

- **Vehicles needed by the rules:** 14 ambulances, 2 doctor vehicles, helicopter. **Different vehicles sent:** 14 (helicopter included where it flew).
- **Demand trigger:** on at minute 20 (free ambulances in the Ljubljana area 6 of 26 (25 percent or less)).
- **Units taken off another job:** 4.
- **Scheduled transports:** 20 requested at minute 20; 6 to private vans, 14 stay with public units.
- **First ambulance to each red call:** D09-C1 4.4 min, D09-C6 6.0 min; 15-minute target met.
- **Ljubljana-area ambulances:** 9 of 26 free at the lowest point; at most 65 percent busy.

**What to point out:**

- The agent does not offer A05 (too little fuel) and offers A03 only after its 30-minute cleaning ends: A03 is used first at minute 38.
- Helicopter not available: snow and low cloud at Brnik (assumed); ground units only.
- Sixteen ambulance and doctor jobs are served by 14 different vehicles; 2 vehicles finished a job and took a later one.
- The demand trigger turns on at minute 20 (6 of 26 ambulances free). Of 20 scheduled transports, only 6 can go to private vans; 14 stay with public units, which shows that the private pool is also a limit.
- Yellow arrivals stretch to 40 minutes and more at the busiest moments. Weather slows every unit equally, so the order of calls matters more than the choice of unit.

**Engine events:** 14 `urgent_request` payloads in the JSON (`engine_events`), each valid against the engine's event model.

---
### D10. Mass-casualty: bus crash on the motorway, 22 patients

**Shows:** The largest case. The caller says about 30 injured, so the agent sends everything it can at once. The first team triages on the spot, reports, and the vehicles that are still on the way and no longer needed are stood down.

**Setup:** 18:10 start, weekday, day roster; light rain, 3 °C; speed factor from weather 0.93; 50 percent of units busy with scheduled transports at the start. 1 call, 22 patients.

| Call | Time | Place | Level | Patients | Needs (by rule) | Sent (unit, minutes to arrive) |
|---|---|---|---|---|---|---|
| D10-C1 | 18:10 | A1 motorway near Šentjakob (synthetic crash site) | red | 30 estimated (5 red, 10 yellow, 15 green) -> 22 triaged on scene (4 red, 8 yellow, 10 green) | initial wave 15 ambulances, 5 doctor vehicles, helicopter, 4 vans -> after triage 12 ambulances, 4 doctor vehicles, helicopter, 3 vans + first responders, fire, police, mass-casualty trailer and incident command | A13 ZD Domžale, 6 min; A14 ZD Domžale, 6 min; A08 UKC station, 14 min; A01 UKC station, 19 min; A03 UKC station, 19 min; A02 UKC station, 25 min; A05 UKC station, 25 min; A09 UKC station, 25 min; A28 ZD Kranj (other region), 35 min; A16 ZD Kamnik, 35 min; A32 ZD Tržič (other region), 37 min; A15 ZD Kamnik, 37 min; A12 UKC outpost Medvode, 37 min [stood down at minute 12]; A20 ZD Kočevje, 42 min [stood down at minute 12]; A04 UKC station, 44 min [stood down at minute 12]; D02 ZD Ljubljana, 24 min; D01 ZD Ljubljana, 24 min; D03 ZD Ljubljana, 29 min; D05 ZD Kamnik, 31 min; D04 ZD Domžale, 47 min [stood down at minute 12]; PT03 private van, 41 min; PT05 private van, 48 min; PT01 private van, 52 min; PT02 private van, 57 min [stood down at minute 12] |

**All units sent:**

- **Ambulances (12):** A01, A02, A03, A05, A08, A09, A13, A14, A15, A16, A28, A32 (other regions: A28 ZD Kranj, A32 ZD Tržič)
- **Doctor vehicles (4):** D01, D02, D03, D05
- **Private vans (3):** PT01, PT03, PT05
- **Helicopter:** not sent (outside the daylight window (08:00 to 16:30))
- **From other regions:** A28 (ZD Kranj), A32 (ZD Tržič)
- **Private units:** PT01, PT03, PT05
- **Other services alerted by dispatch (not part of the ambulance fleet):** first responders, fire brigade, police, mass-casualty trailer, incident commander and triage team
- **Stood down after triage (5):** A04, A12, A20, D04, PT02 (the initial wave was 24 vehicles)

- **Vehicles needed by the rules:** 12 ambulances, 4 doctor vehicles, helicopter, 3 vans. **Different vehicles sent:** 19 (helicopter included where it flew).
- **Demand trigger:** on at minute 0 (predicted red arrival 19 min (over 15)).
- **Units taken off another job:** 2.
- **First ambulance to each red call:** D10-C1 5.9 min; 15-minute target met.
- **Ljubljana-area ambulances:** 9 of 26 free at the lowest point; at most 65 percent busy.

**What to point out:**

- **Minute 0, before anyone has seen the scene:** the dispatcher triages the call as red with a suspected mass-casualty event. The agent sends the **initial wave** sized for the caller's estimate (5 red, 10 yellow, 15 green by assumption): 24 vehicles, which is as much as the 25-vehicle surge cap allows. Alerted by dispatch: fire, police, first responders, the mass-casualty trailer, an incident commander with a triage team [S, `SURGE_AND_MULTI_SERVICE_COORDINATION.md`].
- **Minute 12, the first team has done start triage on the spot** and reports (METHANE, a human step): 22 patients, 4 red, 8 yellow, 10 green. A human declares the mass-casualty event and the regional coordination group is formed (art. 21) [S].
- **Stand-down:** with one patient per ambulance the real need is 12 ambulances, 4 doctor vehicles and 3 vans. The agent stands down the 5 vehicles that are still furthest away (A04, A12, A20, D04, PT02). They become free where they are and can cover the rest of the area.
- **What stays: 19 vehicles.** 12 ambulances (the four red patients get the first to arrive, in 6, 6, 14, 19 minutes; the yellow patients' ambulances in 19 to 37 minutes), 4 doctor vehicles (arriving in 24 to 31 minutes) and 3 vans for the 10 green patients.
- **Other regions:** A28 (ZD Kranj), A32 (ZD Tržič), sent for yellow patients because the demand trigger was on and the local wait was over 30 minutes. **Private:** PT01, PT03, PT05, vans for the green patients, because the public vans were not free within 20 minutes. No private ambulance was needed. No helicopter: it is after dark.
- **Hospital distribution** with the synthetic UKC capacity (accepts 3 red, 6 yellow, 20 green at once): one red and two yellow patients overflow to SB Celje. The agent proposes it; the incident medical lead confirms, because the destination of a red patient is a clinical decision.
- A slip road is closed by the fire brigade while the units are on their way: ten vehicles are rerouted (see the script).
- **How this works in real life is only partly documented.** The Slovenian guideline says the first team sends METHANE with an initial estimate of casualties, starts primary triage and calls additional help as needed, and the dispatcher activates further teams per the unit's plan [S, mass-casualty guideline 2013]. I found no published rule for sending an over-sized first wave or for standing vehicles down; that is common practice elsewhere [I] and is modelled here as the agent's job with a human confirming the declaration.

**Engine events:** 1 `urgent_request` payload in the JSON (`engine_events`), each valid against the engine's event model.

---
### D11. Everything is out: no public unit is free within 15 minutes

**Shows:** A storm-hour extreme. Every ambulance in the area and in the neighbouring regions is tied up for at least 18 minutes. Shows the private-ambulance rule for red calls.

**Setup:** 16:00 start, weekday, day roster; storm wind 70 km/h, rain; speed factor from weather 0.85; 100 percent of units busy with scheduled transports at the start. 4 calls, 4 patients.

| Call | Time | Place | Level | Patients | Needs (by rule) | Sent (unit, minutes to arrive) |
|---|---|---|---|---|---|---|
| D11-C1 | 16:00 | Bežigrad | red | 1 red | 1 ambulance, 1 doctor vehicle + first responders | PA01 private ambulance, 17 min; D01 ZD Ljubljana, 10 min |
| D11-C2 | 16:05 | Polje | red | 1 red | 1 ambulance, 1 doctor vehicle + fire, police | PA02 private ambulance, 28 min; D04 ZD Domžale, 33 min |
| D11-C3 | 16:10 | Šiška | yellow | 1 yellow | 1 ambulance | A15 ZD Kamnik, 24 min |
| D11-C4 | 16:16 | Vič (residential block) | yellow | 1 yellow | 1 ambulance | A24 ZD Postojna, 17 min |

**All units sent:**

- **Ambulances (2):** A15, A24
- **Doctor vehicles (2):** D01, D04
- **Private ambulances (2):** PA01, PA02
- **From other regions:** none
- **Private units:** PA01, PA02
- **Other services alerted by dispatch (not part of the ambulance fleet):** first responders, fire brigade, police

- **Vehicles needed by the rules:** 4 ambulances, 2 doctor vehicles. **Different vehicles sent:** 6 (helicopter included where it flew).
- **Demand trigger:** on at minute 0 (free ambulances in the Ljubljana area 0 of 26 (25 percent or less)).
- **Scheduled transports:** 18 requested at minute 12; 6 to private vans, 12 stay with public units.
- **First ambulance to each red call:** D11-C1 16.7 min, D11-C2 28.4 min; 15-minute target missed.
- **Ljubljana-area ambulances:** 0 of 26 free at the lowest point; at most 100 percent busy.

**What to point out:**

- The first red call gets the private ambulance PA01, 17 minutes away, because every public unit would need longer. The second red gets PA02 at 28 minutes. Both miss the 15-minute target, and the dispatcher sees that.
- Each red call also gets a doctor vehicle (public: ZD Ljubljana and ZD Domžale).
- The two yellow calls wait 17 to 24 minutes for public units; none goes outside the area because no neighbour is faster.
- Of 18 scheduled transports, 6 go to private vans and 12 stay with public units.
- This is also the scenario for the open question about private crews: whether their staff may take red calls is not published [?]; the rule used here follows your instruction.

**Engine events:** 4 `urgent_request` payloads in the JSON (`engine_events`), each valid against the engine's event model.

---
### D12. Everything at once: seven overlapping calls

**Shows:** A 25-minute demo script where events overlap in every way: two calls in the same minute, calls that arrive while others are on the road, a duplicate caller, a closure, a jam, a stale feed, a breakdown with a patient aboard, a capacity drop and a patient who gets worse.

**Setup:** 10:00 start, weekday, day roster; dry; speed factor from weather 1.0; 45 percent of units busy with scheduled transports at the start. 7 calls, 7 patients.

| Call | Time | Place | Level | Patients | Needs (by rule) | Sent (unit, minutes to arrive) |
|---|---|---|---|---|---|---|
| D12-C1 | 10:00 | Bežigrad | red | 1 red | 1 ambulance, 1 doctor vehicle + first responders | A04 UKC station, 4 min; D01 ZD Ljubljana, 8 min |
| D12-C2 | 10:00 | Vič (residential block) | yellow | 1 yellow | 1 ambulance | A05 UKC station, 10 min |
| D12-C3 | 10:03 | Zaloška cesta | red | 1 red | 1 ambulance, 1 doctor vehicle + first responders, police | A06 UKC station, 3 min; D02 ZD Ljubljana, 12 min |
| D12-C4 | 10:06 | Šiška | yellow | 1 yellow | 1 ambulance | A07 UKC station, 10 min |
| D12-C5 | 10:09 | Domžale (outskirts) | red | 1 red | 1 ambulance, 1 doctor vehicle + first responders | A16 ZD Kamnik, 16 min; D05 ZD Kamnik, 20 min |
| D12-C6 | 10:14 | Črnuče | yellow | 1 yellow | 1 ambulance | A02 UKC station, 7 min |
| D12-C7 | 10:18 | Polje | yellow | 1 yellow | 1 ambulance | A03 UKC station, 12 min |

**All units sent:**

- **Ambulances (7):** A02, A03, A04, A05, A06, A07, A16
- **Doctor vehicles (3):** D01, D02, D05
- **From other regions:** none
- **Private units:** none
- **Other services alerted by dispatch (not part of the ambulance fleet):** first responders, police

- **Vehicles needed by the rules:** 7 ambulances, 3 doctor vehicles. **Different vehicles sent:** 10 (helicopter included where it flew).
- **Demand trigger:** on at minute 9 (predicted red arrival 16 min (over 15)).
- **Units taken off another job:** 4.
- **First ambulance to each red call:** D12-C1 4.0 min, D12-C3 2.6 min, D12-C5 15.9 min; 15-minute target missed.
- **Ljubljana-area ambulances:** 9 of 26 free at the lowest point; at most 65 percent busy.

**What to point out:**

- **Same time:** D12-C1 (red chest pain) and D12-C2 (yellow fall) arrive in the same minute; two ambulances and a doctor vehicle go out at once.
- **In between:** a pedestrian crash (C3, minute 3), a wasp-sting allergy (C4, minute 6) and a cardiac arrest (C5, minute 9) arrive while the first units are still on the road. The trigger turns on at the arrest because the predicted arrival is over 15 minutes.
- **Closure:** the road towards Domžale is closed after a collision while the arrest ambulance is on its way. The vehicles heading there (A16, D05) are rerouted, about 5 minutes longer. **Jam:** a minor collision delays the Šiška patient's ambulance by 4 minutes.
- **Duplicate caller:** a second caller reports the pedestrian crash; the dispatcher merges it and no new units go (a human step). **Stale feed:** the traffic feed is stale for 5 minutes and ETAs are marked uncertain.
- **Breakdown:** the ambulance carrying the diabetic patient (C6) breaks down; the agent sends the nearest free ambulance (A09) and the patient is transferred.
- **Capacity and priority change:** UKC reports one free resuscitation bay (minute 16). The crew reports that the chest tightness (C7) has become a suspected heart attack (minute 21): the call is upgraded to red and a doctor vehicle is added.
- Humans involved: seven triages, one merge decision and seven signatures. Everything else is the agent.

**Engine events:** 7 `urgent_request` payloads in the JSON (`engine_events`), each valid against the engine's event model.

---
## 4. Simulation scripts

Each scenario has a replayable script in [`scenario/playback/`](scenario/playback/): every vehicle's timeline and road path, reroutes, patient vitals and voice entries, and one event stream for all dashboards. Format and how to replay: [SIMULATION_SCRIPTS.md](SIMULATION_SCRIPTS.md).

| Script | Vehicles | Patients | Events | Voice entries | Reroutes | Human steps |
|---|---|---|---|---|---|---|
| [D01](scenario/playback/D01.json) | 1 | 1 | 50 | 3 | 0 | 2 |
| [D02](scenario/playback/D02.json) | 2 | 1 | 82 | 7 | 0 | 2 |
| [D03a](scenario/playback/D03a.json) | 3 | 1 | 83 | 7 | 0 | 2 |
| [D03b](scenario/playback/D03b.json) | 2 | 1 | 89 | 7 | 0 | 2 |
| [D04](scenario/playback/D04.json) | 4 | 3 | 202 | 13 | 1 | 6 |
| [D05](scenario/playback/D05.json) | 7 | 6 | 289 | 18 | 7 | 6 |
| [D06](scenario/playback/D06.json) | 7 | 6 | 321 | 17 | 0 | 12 |
| [D07](scenario/playback/D07.json) | 13 | 11 | 604 | 32 | 0 | 22 |
| [D08](scenario/playback/D08.json) | 6 | 3 | 230 | 13 | 0 | 7 |
| [D09](scenario/playback/D09.json) | 14 | 14 | 724 | 38 | 1 | 28 |
| [D10](scenario/playback/D10.json) | 24 | 22 | 805 | 38 | 10 | 16 |
| [D11](scenario/playback/D11.json) | 6 | 4 | 261 | 16 | 0 | 8 |
| [D12](scenario/playback/D12.json) | 12 | 7 | 490 | 35 | 2 | 15 |

*Vehicles* counts every vehicle that appears in the script: in D10 the initial wave of 24, of which 5 are stood down at minute 12; D07 and D12 include a replacement ambulance.

## 5. Using the scenarios

- **With the engine.** Each scenario has `engine_events`: `urgent_request` payloads with a time offset in minutes. Red becomes `priority: "emergency"` and yellow `"urgent"`. All payloads were checked against the engine's event model. The engine holds one trip per request, so patient counts, doctor vehicles, helicopters, private providers and the demand trigger need new code; the JSON carries them as `calls[].patients`, `calls[].doctors` and the `expected` block.
- **As a test of the agent.** Feed the `calls` and compare the agent's choices with `dispatch_log`: the units, the order of events and the totals in `expected`. The model is a stand-in, so a different but defensible choice is not an error; a choice that breaks a rule in section 1 is.
- **For the stage.** A good order is D01, D02, D04, D07, D10. D03a and D03b are the weather pair, D09 shows weather, fuel and cleaning, D11 shows the private-ambulance rule.

## 6. What is assumed

- The speeds, thresholds (25 percent free, 15 and 30 and 45 minutes), service times and the private pool (3 ambulances, 6 vans, 15 and 30 minutes to mobilise) are assumptions [A].
- The model picks initial positions of busy units at random around their base from a fixed seed (20261123). Another seed changes individual ETAs, not the rules.
- The model is greedy: it assigns each call in order and does not re-optimise the whole day.
- Slovenian caller texts are my drafts and should be read by a native speaker before going on stage.
- Hospital capacity is the synthetic set in `scenario/ljubljana_scenario.json`.
- No fuel feed exists: the fuel and cleaning cases in D09 are set by hand.

## 7. Open questions

- **Green patients in a mass-casualty event:** the model sends them by van (4 per van). If every patient should get an ambulance, D10 needs 22 ambulances and would not fit the 25-vehicle cap together with the day's other calls.
- **Yellow calls and private ambulances.** The rule used is: only if even other regions leave a wait over 45 minutes. Say if you want it stricter or looser.
- **Crew qualification of private ambulances** for red calls, and what the rules say about it [?].
- **The demand trigger thresholds** (25 percent free; 15-minute red target) should be confirmed with the contact or the dispatch centre.
- **Which red cases get a doctor** is set by triage; the full SloIn NMP scheme is still outstanding.
