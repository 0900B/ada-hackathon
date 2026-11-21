# Slovenian emergency medical services: research findings (Ljubljana focus)

Researched 2026-11-21 for the AdaHack Epilog challenge #3. Map of all ambulance units by region: [AMBULANCE_MAP.md](AMBULANCE_MAP.md). Workflow diagrams and per-step data dependencies are in [WORKFLOWS.md](WORKFLOWS.md); image copies are in `docs/diagrams/`. Ljubljana fleet, teams, shifts and dispatch decision: [LJUBLJANA_FLEET_AND_TEAMS.md](LJUBLJANA_FLEET_AND_TEAMS.md). Surge capacity, private ambulances, army, multi-event coordination: [SURGE_AND_MULTI_SERVICE_COORDINATION.md](SURGE_AND_MULTI_SERVICE_COORDINATION.md). Totals, seasons, fuel, breaks, cleaning, handover: [OPERATIONS_DETAILS.md](OPERATIONS_DETAILS.md). Scenario data, surge events, gap status: [SCENARIO_DATA.md](SCENARIO_DATA.md), [SURGE_EVENTS.md](SURGE_EVENTS.md), [GAPS_STATUS.md](GAPS_STATUS.md).

**How to read this:** each fact is tagged **[S]** stated in a source I read, **[I]** my inference, **[?]** not found. Several PDFs could not be read by the web fetch tool, so I extracted their text locally and read it directly; those are marked "(read in full)". Source dates are given because some are old.

---

## 1. System overview

- **Legal framework [S]:** EMS acts of 1996, 2008 and 2015 (the 2015 act brought important changes); a 2016 act on helicopter EMS conditions; a 2017 act on the medical dispatch service. These set the organisation, staff, vehicles, duties and funding basis. (Rajapakse slides, about 2016-17, read in full.)
- **Funding [S]:** compulsory insurance (ZZZS) pays providers under yearly contracts per programme. Emergency vehicle teams are priced as a fixed amount per team. Helicopter EMS and the dispatch service are funded "at the level of last year's contract" (ZZZS programme decree, published 17 Apr 2026, read in full).
- **Historic structure [S, about 2016]:** 63 EMS units; in 75% of them family doctors answered emergencies from their practice, only 25% were dedicated. Planned future model: 12 large hospital emergency centres, 19 small emergency centres in bigger health centres, 32 out-of-hours primary-care sites, all coordinated by central dispatch. The 2026 decree still lists teams per provider, so this transition is ongoing [I].
- **Care levels [S]:**
  - Doctor-staffed emergency ambulance (NRV, EN 1789 type C)
  - Rescuer-staffed ambulance (type B)
  - Non-emergency rescue vehicle (type A)
  - Medical vehicle for patients who can sit
- **Network criteria [S]:** average access time of a mobile unit must not exceed **15 minutes**; at least one emergency transport team per **30,000 insured people**; one team carries out about **2,000 emergency transports a year**.
- **Vehicle counts [S, about 2016]:** 52 resuscitation vehicles, 32.6 rescuer-staffed (equivalent), 104 non-emergency rescue vehicles, 319 medical vehicles. These are old; no current national count found.

## 2. Dispatch: from 112 to a team

- **Chain [S]:** 112 → one of **13 regional notification centres (ReCO)** → **medical dispatch centre (DCZ)**. There are two DCZ, in **Ljubljana and Maribor**, set up under the Pravilnik o dispečerski službi zdravstva (OJ RS 58/2017; a consolidated text dated 21 May 2025 exists, status not verified).
- **Operator [S]:** the DCZ is an independent unit inside **UKC Ljubljana**. The 2026 decree lists "helicopter EMS and the health dispatch service" under UKC Ljubljana's programme. Phone for the UKC dispatch service is on the UKC website.
- **Triage [S]:** the Slovenian Index for Emergency medical help, based on the Norwegian index (3rd edition). Outcomes: doctor-staffed emergency team, rescuer ambulance without doctor, doctor home visit, send the patient to the nearest health service, or phone advice.
- **Team selection [S]:** the nearest suitable team is sent; a dispatcher screen lists the nearest first responders (can include non-emergency vehicles or motorcycles). A 2026 report says a team from a nearby health centre may be sent if it is faster. **GPS [S, updated]:** the dispatch rulebook (art. 11, OJ 58/2017) requires every ambulance to have a GPS transmitter, radio, navigation device and tablet, with position data reaching dispatch within 10 seconds (99.5% availability). Full detail in [LJUBLJANA_FLEET_AND_TEAMS.md](LJUBLJANA_FLEET_AND_TEAMS.md).
- **Roll-out [S]:** regions are joining step by step (for example Idrija, Pomurje, Gorenjska were reported). In the old model each local unit dispatched itself.
- **Road accidents [S]:** ReCO alerts fire brigade and police in parallel; emergency vehicles use lights and sirens and form a rescue corridor; DARS (motorway company) also takes part.
- **Routes [S for intent, ? for software]:** the dispatcher uses traffic information and orders the vehicle the fastest route; the routing software is not named in any source. For the challenge, use OSRM.

## 3. Who operates what in Ljubljana

- **UKC Ljubljana [S, decree 2026]:** 12 NRV teams, 1 motorcycle team, helicopter EMS and dispatch service contracts. A 2019 report says the Ljubljana ambulance station handles up to 45,000 interventions a year over about 1,700 km² and had 3 rescue motorcycles; it also took delivery of two ambulances able to carry incubators.
- **ZD Ljubljana [S, decree 2026]:** for on-duty emergency care in the City of Ljubljana: 3 doctor-plus-nurse intervention teams (MoE VUZ), 1 urgent home-visit team (MoE DZ), 5 on-duty teams (DS1), 2.5 rapid-exam teams in working hours, 1.5 triage and admission teams, 0.8 emergency-centre team. The walk-in adult emergency clinic (SNMP) is at the UKC emergency department, entrance from Bohoričeva, open 24/7.
- **Fleet maintenance [S]:** a 2026 EU tender covers maintenance of the Ljubljana ambulance station's fleet, about €1.6M ex VAT, split by manufacturer (VW, MAN, Mercedes-Benz). I read only a search summary of this notice, not the notice itself.
- **Fleet size [S, updated]:** 29 vehicles (2018) and 30 (end 2022) at the UKC station, with type mix, age and mileage in [LJUBLJANA_FLEET_AND_TEAMS.md](LJUBLJANA_FLEET_AND_TEAMS.md). Maintenance is outsourced under a 2026 framework contract (six lots, about €402k awarded).
- **Ownership and renting [?]:** still not found. The tender and per-team funding suggest the public institute owns and maintains emergency ambulances **[I]**. Non-emergency transport is different: private providers hold concessions with ZZZS (a 2022 regional news report, Podravje; not verified for Ljubljana).

## 4. Helicopter emergency medical service (HNMP)

### Organisation
- **Medical side [S]:** the Brnik unit is organised through Osnovno zdravstvo Gorenjske / ZD Kranj; 25 members listed (15 doctors, 10 rescuers) with the unit head Uroš Lampič. Doctors come mostly from NMP units at Kranj, Jesenice, Bled and others (HNMP site, 20 Jul 2026).
- **Aircraft side [S]:** army helicopters (Bell 412) and police helicopters. A **June 2024 government decision** makes helicopter EMS, inter-hospital helicopter transfers and incubator transports a state activity carried out with **police** aircraft; until the police are ready, the army continues. Police bought a third multi-purpose helicopter (AW169) in March 2024, replacing older AB 212 and AB 412 types [S, search summary].
- **Dedicated helicopters [S]:** police signed a contract with Leonardo on 13 Oct 2025 for **two** EMS helicopters; reported value about €32M (RTV) to almost €37M with maintenance (Svet24). Delivery planned **Oct 2027** and **Feb 2028**, so the original 2026 hand-over has slipped. Livery confirmed 24 Apr 2026 (yellow-blue). The police will train 12 new pilots and 6 aircraft technicians.
- **Joint mountain team [S]:** a combined HNMP + Mountain Rescue Association (GRZS) team has operated from Brnik since 2017.

### Bases and hours
- **Two bases [S]:** Brnik airport and Maribor airport. A May 2024 proposal suggests moving the Brnik base to **Lesce**, because of fog; not a decision.
- **Brnik hours [S]:** every day 08:00-20:00 in the summer half, 08:00 to sunset in the winter half; the schedule follows Ljubljana sunrise and sunset rounded to the half hour. **No night flying found for HNMP.** One older (about 10 years) article mentioned a police night crew for HEMS and mountain rescue, not verified as current.
- **Brnik problems [S]:** security and airport traffic add delay; crew rooms are about 400 m from the operator's premises and 250 m from the helicopter, with several checkpoints; fog days are quoted at "20 to 25 percent per year" (wording ambiguous).

### Performance
- **Missions, Brnik [S]:** 324 (2021), 310 (2022), 333 (2023), 333 (2024), 344 (2025).
- **Call to takeoff, average [S]:** 15, 15, 12, 16, 13 minutes. Older figures: 17 min (2003-06 pilot), 10 min (2013 guideline). **Use the recent range.**
- **History [S, 2007 text, read in full]:** pilot project 16 Jul 2003 to 30 Nov 2006 with 540 interventions (one per 2.3 days), average total mission 1 h 57 min, 557 patients (48% illness, 25% road accidents, 26% other injuries). Regular service from 1 Dec 2006. A private carrier flew an EC 135 for about six weeks in 2007 before the government ended it and police took over.
- **Aircraft equipment [S]:** 12-lead ECG monitor, defibrillator, external pacer, ventilator, ultrasound, mechanical chest-compression device, video laryngoscope, vacuum splints and more.

### Activation
- **Current [S]:** via DCZ (Ljubljana 08209-7440, Maribor 08201-0039 per the HNMP site) or 112. The plan for using state aircraft (applied since **15 Oct 2022**) puts HNMP under the DCZ and allows simultaneous activation with NMP teams, fire and police.
- **Older rule set [S, 14 May 2013, read in full, marked archived on gov.si]:**
  - No medical dispatch system existed, so the field doctor normally activated HNMP after arriving.
  - Early activation allowed if clearly needed; the ground team must still keep driving.
  - HNMP doctor decides finally; communication on ZARE channel 34.
  - Indications: time advantage; gentler transport (spine injury, severe head injury, polytrauma, pelvis, femur, aortic dissection); upgrade to NMP care; help when the local team is busy; mass casualty.
  - **Time rule:** helicopter justified if road transport to the right hospital exceeds **45 minutes**; **distance rule:** more than **72 km**. Trapped patients qualify at shorter distances.
  - Flight-time rings of 5 to 30 minutes around Brnik (shown as a map).
  - Helicopter only goes where it can land; otherwise move the patient, else call the GRZS winch helicopter. Police or fire secure the landing site.

### Hospital-to-hospital helicopter transfers
- **Since 1993 [S]** run from the Ljubljana clinical centre. Adults are escorted by anaesthetists and anaesthesia nurses; newborns and critically ill children by paediatric specialists. Activated after the sending and receiving hospitals agree.
- **Rules [S, thesis]:** these count as standard air transport; no relaxed risk acceptance as in emergency flights. Operators use HNMP helicopters between missions, which makes them unavailable for emergencies; dispatch tries to schedule transfers at quiet times.

## 5. Where helicopters land (infrastructure and rules)

Source: master's thesis "Prometna infrastruktura HNMP v Sloveniji" (Ivan Šmon, University of Ljubljana, 2024), read in full.

### Legal basis
- **Hospital heliports [S]:** treated as "own-use" aerodromes, not covered by the EU basic regulation. A 2016 rulebook (OJ RS 53/16) applies **ICAO Annex 14 vol. II** and makes two services mandatory: **fire-and-rescue** and **maintenance**. Slovenia does not use the EU exemption for small traffic.
- **Heliport geometry [S]:** FATO (final approach and take-off area), TLOF (touchdown and lift-off area), safety area, at least two approach/departure surfaces, obstacle limitation, markings and lighting for night use, an emergency response plan.
- **Aircraft performance rules [S]:** helicopters operating to a hospital site in a built-up area must fly in **Performance Class 1** (engine failure survivable), unless the operator has approval for "public interest sites". At field sites (the scene), relaxed Class 2 or 3 is allowed, with special HEMS approval, more experienced crews and multi-member crews.
- **Public interest sites (PIS) [S]:** an EU concept allowing a temporary relaxation. **Slovenia has no register of PIS**, so formally they do not exist; the thesis calls the regulation of unregistered hospital landing sites deficient and a possible safety risk.

### Registered hospital heliports (2024) [S]
| Site | Code | Notes |
|---|---|---|
| UKC Ljubljana | LJHL | rooftop, opened 2013 |
| SB Jesenice | LJHJ | rooftop of car park, opened 2010, TLOF 20 m |
| SB Slovenj Gradec | LJHS | |
| SB Izola | LJHI | |
| SB Celje | LJHC | built 2022 |

### UKC Ljubljana helipad (LJHL) [S]
- Raised, heated aluminium platform on the roof of the emergency building, city centre, 318 m elevation, 46°03'18"N 14°31'15"E
- TLOF 28 m, FATO 28 m, safety area 38 m; load 9 t; fire category H2; lighting yes; two approach directions; **Performance Class 1 only**
- Integrated automatic fire system with infrared detection, 34,500 L of water, two fire monitors at least 500 L/min of foam; enough for 5 minutes
- Fire and rescue crew: trained hospital or Ljubljana ambulance station staff with other jobs, called out whenever a helicopter is announced
- **Single access, over a bridge** (a second fire access was not required when it was built)
- Traffic: stable 2019-2022, **287 operations in 2023**

### Public interest sites [S]
UKC Maribor (ground site about 22 × 28 m, 127/88/94/115/135 operations in 2019-2023 and 88 in the first half of 2024), SB Murska Sobota, Brežice, Novo mesto, Nova Gorica, Ptuj, Trbovlje. The thesis says the UKC Maribor "heliport" does not meet heliport rules and is high-risk.

### Other infrastructure observations [S]
- Instrument approach is rarely used; satellite-based navigation is expanding the use of non-instrument sites in poor weather.
- Choosing a base location needs wind and fog statistics: for example the thesis shows strong-wind days exceeding 35 kt on 9 days and 40 kt on 6 days in 2022 for one exposed site, versus fog at others.

## 6. Organ donation and transplant

Sources: Slovenija-transplant pages (donor network, transplantation, statistics, history), UKC Ljubljana, gov.si news on the Falcon, a search summary of RTV and gov.si.

- **Organisation [S]:** Slovenija-transplant is a public institute under the Ministry of Health (founded 2002). It is the national competent authority and runs the registers, waiting lists, the central information system and adverse-event reporting. Central transplant coordinators work **24/7** and coordinate logistics and surgical teams. Director Andrej Gadžijev (since 1 Jan 2022). Address Zaloška cesta 7, Ljubljana.
- **Donor network [S]:** since 1998; **11 donor hospitals** (UKC Ljubljana, UKC Maribor, Celje, Murska Sobota, Slovenj Gradec, Jesenice, Novo mesto, Izola, Ptuj, Nova Gorica, Brežice). Each has a hospital transplant coordinator. Brain death needs a commission of two specialists, two independent clinical tests and an instrument test; a mobile UKC neurophysiology team covers hospitals that lack the instrument.
- **Eurotransplant [S]:** Slovenia joined on 1 Jan 2000. Offers for Slovenian patients come from the Leiden office 24/7; criteria include urgency, blood group, size, age, expected success and time on the list. Shared list about 23,600 patients; Slovenian list about 240.
- **Where transplants happen [S]:** **all** solid-organ transplants at UKC Ljubljana (Centre for Transplantation Activity, head Ivan Kneževič). Corneas are also done in Maribor. Some paediatric cases go abroad (Bergamo or Hamburg for liver, Graz for kidney).
- **Volumes, 2025 [S]:** 103 organ transplants (44 kidney, 25 heart, 22 liver, 10 lung, 2 pancreas), 50 deceased donors. Waiting times quoted: kidney about 240 days, heart 244, liver 91, lung 92 (two pages give slightly different figures).
- **Teams [S]:** more than 100 health professionals take part in each transplant; retrieval teams are specially trained surgeons with instrument nurses and perfusionists; for heart, lung or liver from a foreign donor a Slovenian team travels abroad and brings the organ back to UKC Ljubljana.
- **Air transport [S]:** since a **March 2015** contract between the Ministry of Defence and Slovenija-transplant (with UKC Ljubljana), the army's **Falcon 2000EX** jet flies organs; **118 organs** (and an antidote) had been carried by May 2025, including trips to France, the UK and Greece. These count as medical flights and get priority.
- **Road leg [?]:** no source says who drives organs between the airport and UKC, or between hospitals in Slovenia. **Cost of transport [?]**: not stated (transplant treatment is covered by basic insurance; Slovenija-transplant's running costs by the Ministry budget).
- **Time limits [?]:** not in any source I read. General medical knowledge only (unverified here): heart and lung about 4 to 8 hours, liver about 8 to 12, kidney 24 hours or more.

## 7. Conflicts between sources

| Topic | Source A | Source B | What to use |
|---|---|---|---|
| Call-to-takeoff | 10 min (2013 guideline); 17 min (2007) | 12 to 16 min (2021-2025 site data) | recent range |
| Dispatch | "No health dispatch system" (2013) | DCZ exists since the 2017 law, roll-out ongoing | current |
| Aircraft type | Bell 412 (HNMP site) | AB 412 / AB 212 / A109 (2007); AW169 added 2024 | HNMP site plus police fleet change |
| Helicopter price | about €32M (RTV) | almost €37M with maintenance (Svet24) | give the range |
| Waiting times | kidney about 240 days (statistics page) | about 12 months (transplantation page) | not needed for the plan |
| Transplants per year | about 110 (statistics headline) | 103 (2025 breakdown), about 120 (transplantation page) | 103 |
| Adult SNMP phone | +386 1 522 84 08 | +386 1 555 2222 | not needed |

## 8. Gaps (not found), see [GAPS_STATUS.md](GAPS_STATUS.md) for the updated status

1. Who owns or leases ambulances in Ljubljana
2. The routing software used by dispatch (live GPS tracking is now confirmed as a rulebook requirement)
3. Road transport of organs and its organisation
4. Time limits per organ
5. Night helicopter operations today
6. Current (2025-26) number of ambulances in Ljubljana (2018 and 2022 counts found)
7. Hospital admission capacity data
8. The Maribor base details (operator, hours)

## 9. Source list

All accessed 2026-11-21.

- HNMP Slovenia, base organisation article (20 Jul 2026): https://www.hnmp.info/novica/stanje-hnmp-organiziranost-baz/
- HNMP history PDF, 2007 (read in full): https://www.hnmp.info/app/uploads/2026/07/hnmp-zgodovina.pdf
- Ministry of Health, HNMP activation instructions, 14 May 2013 (read in full): https://www.gov.si/assets/ministrstva/MZ/DOKUMENTI/staro/Organizacija-zdravstvenega-varstva/NMP/Navodila-za-aktivacijo-enote-helikopterske-nujne-medicinske-pomoci-Slovenije-za-intervencije-na-terenu.pdf
- Thesis, Prometna infrastruktura HNMP v Sloveniji, 2024 (read in full): https://repozitorij.uni-lj.si/IzpisGradiva.php?id=161334&lang=slv&prip=dkum%3A25189603%3Ad4
- Rajapakse, Emergency medical system in Slovenia (read in full): https://etsc.eu/wp-content/uploads/4_Renata-Rajapakse_EMS_Slovenia_Debate_21.pdf
- ZZZS programme decree, 17 Apr 2026 (read in full): https://www.zzzs.si/fileadmin/user_upload/dokumenti/novice/2026/uredba_2026_17.4.2026.pdf
- Slovenija-transplant, donor and transplant network: https://www.slovenija-transplant.si/o-nas/nacionalna-donorska-in-transplantacijska-mreza/
- Slovenija-transplant, transplantation: https://www.slovenija-transplant.si/presaditev/
- Slovenija-transplant, about and history: https://www.slovenija-transplant.si/o-nas/
- Falcon, ten years of organ transport (gov.si): https://www.gov.si/novice/2025-05-05-falcon-ze-deset-let-vkljucen-v-prevoze-organov-za-presaditev/
- RTV SLO, dispatch centres in Ljubljana and Maribor: https://www.rtvslo.si/zdravje/zdravstvena-dispecerska-sluzba-bo-imela-centra-v-ljubljani-in-mariboru/447278
- Pravilnik o dispečerski službi zdravstva: https://www.uradni-list.si/glasilo-uradni-list-rs/vsebina/2017-01-2698/pravilnik-o-dispecerski-sluzbi-zdravstva
- Contract for the new HEMS helicopters (gov.si, 13 Oct 2025): https://www.gov.si/novice/2025-10-13-podpisana-pogodba-za-nakup-novih-namenskih-helikopterjev-za-helikoptersko-nujno-medicinsko-pomoc/
- N1, first rescue helicopter expected October 2027: https://n1info.si/novice/slovenija/prvi-resevalni-helikopter-bo-predvidoma-prispel-oktobra-2027/
- Ljubljana ambulance station, 2019 report: https://www.zurnal24.si/zdravje/aktualno/zivljenja-so-vsakodnevno-odvisna-tudi-od-njihove-pomoci-330914
- TED notice, fleet maintenance tender 2026: https://ted.europa.eu/en/notice/304264-2026/pdf
- ZD Ljubljana, emergency first aid service: https://www.zd-lj.si/zdlj/index.php?option=com_content&view=article&id=380&Itemid=2211&lang=en
- UKC Ljubljana, emergency services: https://www.kclj.si/index.php?dir=/divisions__departments/emergency_services
- Vertical Magazine, Slovenian support (about 10 years old): https://verticalmag.com/features/sloveniansupport/

## 10. Notes on method

- Web search summaries were used for some items (Falcon figures, fleet changes, dispatch roll-out, ambulance station 2019 report, TED tender). Those are tagged by the source named, but I did not open every cited page myself.
- Extracted text of the five PDFs is in the session scratchpad, not in the repo.
- No real patient data was used or is needed.
