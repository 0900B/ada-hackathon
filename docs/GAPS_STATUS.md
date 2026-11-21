# Research gaps: status after a second pass

Refreshes the "Gaps" lists in [EMS_RESEARCH.md](EMS_RESEARCH.md) (section 8) and [LJUBLJANA_FLEET_AND_TEAMS.md](LJUBLJANA_FLEET_AND_TEAMS.md) (section 7). Researched 2026-11-21.

**Tags:** **[S]** read in the original document; **[SS]** only seen in a web-search summary; **[A]** assumption used in the scenario.

---

## 1. Status table

| # | Gap | Status | Answer | Source | Scenario handling |
|---|---|---|---|---|---|
| 1 | Who owns or leases ambulances in Ljubljana | **Mostly closed** | UKC buys its vehicles with its own funds: the 2025 annual report lists ambulances (€370,743) among equipment over €100,000 bought from own funds. Maintenance is split between the station's own renovated workshop and outside contractors (outside repairs average 12 to 96 hours); the building has no space to wash vehicles. **No lease found** | UKC annual report 2025 [S]; TED notice 2026 [S] | Treat as owned |
| 2 | Routing software and tracking | **Partly closed** | The dispatch program is **Computel "NMP 3000"** ("dispatch program for sending ambulances across Slovenia"), with a call-centre system and a recording system from the same vendor. GPS in every vehicle is required by rule. The routing method inside it is still not published. A Ministry tender to renew the dispatch information system (three lots) was annulled once by the state audit body; a news summary says the repeat ended with all bids rejected and that the NMP information-system contract was signed | UKC annual report 2025 [S]; dispatch rulebook via Information Commissioner [S]; news summaries [SS] | Use OSRM for routing, state it as a stand-in |
| 3 | Road transport of organs | **Open** | Nothing found on who drives organs between airport, helipad and transplant centre | n/a | Scenario offers ambulance and helicopter as options |
| 4 | Organ time limits | **Partly closed** | Ranges from general sources: heart 4 to 6 h, lung 4 to 8 h, liver 8 to 12 h, pancreas 12 to 18 h, kidney 24 to 36 h. Some sources are stricter (liver under 8 to 10 h, kidney under 20 h as optimal). These are typical or "suboptimal above" thresholds, not hard limits. No Slovenian or Eurotransplant figures found | Medscape, OpenAnesthesia, Altmeyers, others [SS] | Conservative values: heart 4 h, lung 6 h, liver 10 h, kidney 24 h |
| 5 | Night helicopter flying | **Partly closed** | HNMP is **day only today**. The police say the specification for the two new helicopters requires **day, night and night-vision flying under visual and instrument rules**. Delivery is October 2027 and February 2028, so none in 2026 | Police statement via news summaries [SS]; earlier contract news [S] | Helicopter window 08:00 to 16:30 on 23 Nov |
| 6 | Current ambulance count | **Partly closed** | Still the end-2022 count of 30 vehicles. The 2025 report gives no fleet count; it shows vehicles were bought in 2025 | UKC annual report 2025 [S] | 21 ambulances + 2 sanitary vans, 12 on duty |
| 7 | Hospital admission capacity | **Open** | No bed, ICU or bay counts in the sources. The report says renovation reduced bed capacity. Press coverage reports 142,762 urgent examinations in 2025 | UKC annual report 2025 [S]; press [SS] | **Invented** numbers, flagged in the file |
| 8 | Maribor helicopter base details | **Open** | Not researched in this pass | n/a | Not used |
| 9 | ZD Ljubljana emergency clinic merged into UKC? | **Closed: no** | In 2025 the station still drives doctors of the emergency service "operating within ZD Ljubljana" | UKC annual report 2025 [S] | ZD Ljubljana stays separate |
| 10 | Service interval for ambulances | **Open** | Not published. Contracts are framework agreements for 24 months; the maintenance is done by outside garages | TED notice [S] | Assumption, labelled |
| 11 | Seat-by-seat rosters and shift start times | **Open** | Only the pattern (12 h day, 12 h night, 2 days off) | Station website [S] | Start 07:00 and 19:00 [A] |

---

## 2. New facts from the 2025 report (updates to earlier numbers)

| Item | 2024 | 2025 | Source |
|---|---|---|---|
| Interventions at the station | 49,352 | **48,754** (down 1.2 percent) | UKC annual reports [S] |
| Life-threatening at dispatch | 15,497 | **16,087** (up 3.8 percent) | UKC annual reports [S] |
| Station staff at 31 Dec | 126 (66 nurses or health technicians, 46 rescuers, 15 other) | **137** (76, 47, 14) | UKC annual reports [S] |
| Dispatch service staff | 96 | 96 | UKC annual reports [S] |
| Teams coordinated by the dispatch service | 110 | **up to 123** | UKC annual reports [S] |
| Share of national population covered by dispatch | 79 percent | 79 percent | UKC annual reports [S] |
| UKC helipad traffic | 287 operations in 2023 (thesis) | **444 flight operations, 369 landings** | thesis 2024; UKC annual report 2025 [S] |
| Teams working at once / emergency cap | 16 / 25 | 16 / 25 | UKC annual reports [S] |

**Other 2025 facts [S]:**
- **Helipad outages:** the helipad was out of service temporarily because of faults in the fire-suppression and fire-detection systems. Each time a **substitute landing site was set up at the Edvard Peperko army barracks** with the Ministry of Defence. This is the basis for event X05.
- **Construction next to the helipad:** two construction sites (the main building renovation and the new infectious diseases clinic) sit next to the pad. A **new east approach corridor** and a special safety procedure were created so building work and flights can run at the same time.
- **Station building:** the station has worked since 1948 in the former Remiza building on Zaloška cesta 25. UKC calls it unsuitable: too few parking places for ambulances, no space to wash them, 114 people share two showers. A move is planned with no mechanical workshop in the new space.
- **Volume trend:** life-threatening cases are rising while total interventions fall slightly, which the report links to a growing need and heavier crew load.

---

## 2b. Operational questions answered in a later pass

Details and sources in [OPERATIONS_DETAILS.md](OPERATIONS_DETAILS.md).

| Question | Status | Answer |
|---|---|---|
| Why do the intervention totals differ? | **Closed** | The total is urgent plus non-urgent transports: 49,352 = 15,497 + 33,855 (2024); 48,754 = 16,087 + 32,667 (2025). Two 2018 pages of the same site count differently |
| How do interventions spread through the year? | **Partly** | Monthly numbers exist for 2024 only. Urgent 38 to 46 a day, non-urgent 88 to 100 a day, very flat. Time of day and weekday are not published |
| Severity split | **Partly** | Urgent against non-urgent, and doctor-staffed share (26 percent of urgent in 2024). Priority colours are not published |
| Range before refuelling | **Estimate** | 75 L tank (Crafter, MAN TGE; Sprinter 71 to 75 L) at 10 to 14 L per 100 km gives 400 to 560 km usable; the station drives about 90 km a day on average |
| Breaks | **Closed (law)** | 30 minutes, counted as work time; 12 h daily rest; 24 h weekly rest (ZDR-1 articles 154 to 156). 45 minutes for 12 h is my inference; the break is taken on standby |
| Cleaning after heavy bleeding | **Open** | The station cleans all contact surfaces, stretcher and aids after every job, then restocks; steam disinfection only for airborne infections. No separate procedure or time published |
| Handover and paperwork time | **Partly** | Legal maximum handover 15 minutes. No measured Slovenian average |
| Documents at the ER | **Closed** | Emergency intervention protocol, resuscitation protocol, transport report, triage card, refusal form; patient data, event summary, leading problem, history and vital signs given orally |
| Regional coordination group for special events | **Closed (in law)** | Article 21 of the 2017 dispatch rulebook; whether used in practice is not known |
| Replacement vehicle after a breakdown | **Closed** | Within 2 hours at most (dispatch rulebook article 22) |
| Spare vehicles | **Old rule, not re-verified** | At least 20 percent per vehicle type (2015 NMP rulebook, article 19); that rulebook was replaced on 3 June 2026 |

---

## 3. What is still worth asking someone

For the challenge mentors or the Ljubljana ambulance station:

1. How many ambulances does the station run today, and how many are crewed at any time?
2. What is the usual service interval and how long is a vehicle out per service?
3. How do organs travel by road in Slovenia?
4. Real hospital capacity numbers or a feed (free beds, ICU, ventilators, resuscitation bays)?
5. What does the dispatcher actually use to estimate drive times?
6. Shift start hours and break rules?
7. Are private providers called in practice, and how fast do they arrive?

---

## 4. Sources used in this pass

- UKC Ljubljana annual report 2025 (read in full): https://www.kclj.si/dokumenti/LetnoPorociloUKCL_2025.pdf
- UKC Ljubljana annual report 2024: https://www.kclj.si/dokumenti/Letno_porocilo_UKC_Ljubljana_za_leto_2024_net.pdf
- TED notice 304264-2026, fleet maintenance: https://ted.europa.eu/en/notice/304264-2026/pdf
- Ambulance station, services and shift pattern: https://rpukclj.si/storitve/res-sluzba/
- Information Commissioner opinion quoting the dispatch rulebook: https://www.ip-rs.si/mnenja-gdpr/6048a38d4323f
- RTV SLO, tender for the dispatch information system (several bids): https://www.rtvslo.si/zdravje/vec-ponudb-za-prenovo-informacijskega-sistema-za-dispecersko-sluzbo-zdravstva/754979
- N1, repeated tender: https://n1info.si/novice/slovenija/ponovljen-razpis-za-informacijski-sistem-zdravstva-pritegnil-vec-ponudnikov/
- Žurnal24, how an ambulance call works under the new rules: https://www.zurnal24.si/zdravje/nmp-nujna-medicinska-pomoc-pravilnik-informacijski-sistem-461340
- DKOM decision 018-052/2025: https://www.dkom.si/sl/revizijske-zadeve/odlocitve-dkom/2025062612132815/018-052-2025-republika-slovenija-ministrstvo-za-zdravje
- Police, tender for the two helicopters (night and night-vision flying requirement): https://www.policija.si/medijsko-sredisce/sporocila-za-javnost/sporocila-za-javnost-gpue/123761-nakup-helikopterjev-za-helikoptersko-nujno-medicinsko-pomoc
- RTV SLO, new helicopters used only for emergency medical service: https://www.rtvslo.si/slovenija/kink-nova-helikopterja-bosta-namenjena-zgolj-za-izvajanje-nujne-medicinske-pomoci/732740
- Medscape, organ preservation: https://emedicine.medscape.com/article/431140-overview
- OpenAnesthesia, organ donation: https://www.openanesthesia.org/keywords/organ-donation-donation-after-brain-death-and-donation-after-cardiac-death/
- Altmeyers, ischemia time: https://www.altmeyers.org/en/internal-medicine/ischemia-time-139040
- UKC Ljubljana press release and Svet24 coverage for 2025 volumes (search summaries only): https://svet24.si/novice/slovenija/ukc-ljubljana-poslovno-porocilo-poslovanje-zdravnik-bolnik-1883046
