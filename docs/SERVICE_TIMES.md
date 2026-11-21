# Plan B: service times (the minutes a unit is not driving)

Every predicted and simulated time in Plan B is driving time plus these service times. They live in
one place, `backend/app/engine/service_times.py`, and are used by the simulator, the projection (ETAs,
delays, "available soon"), the dispatch rules, the tablet navigation, the doctor cars and the
deadlines of new calls and bookings.

This is a model built from published standards and studies, not measured Ljubljana data.

## Values

| Phase | Value | Applies to |
|---|---|---|
| **Turnout** (activation, from rest at the base until it drives off) | ambulance **1 min**, doctor car **5 min** | Only when the unit is idle at its base; 0 when it is already driving (e.g. returning from a job). Vans and the helicopter: none (the helicopter's take-off and landing are already in its flight time, 3 min per leg) |
| **On scene** (arrival until it leaves with the patient) | critical **20 min** (cardiac arrest **25**), serious **15 min** (stroke **12**), urgent **12 min**, routine **8 min** | Ambulance and helicopter crews. The stroke is kept short on purpose: time to the stroke centre matters most |
| | **8 min** | A transport van collecting a patient (routine or urgent transport) |
| | **5 min** | Loading equipment or cargo |
| **Handover** at the hospital | **15 min** | A patient brought by ambulance or helicopter |
| | **5 min** | A van unloading a transport patient (the 15-minute handover rule is for ambulance patients) |
| | **5 min** | Equipment drop-off |
| **Cleaning and restocking** after a patient | ambulance and helicopter **10 min**, van **5 min** | The unit is "returning, unavailable" meanwhile, then free. None after equipment |

A doctor car (physician and nurse) has no handover or cleaning of its own: it stays on scene while
the ambulance crew works, escorts the patient to the hospital, takes part in the 15-minute handover
and then drives back.

**What a full emergency costs the fleet**, e.g. a cardiac arrest 6 min from an idle ambulance, 8 min
from UKC: 1 turnout + 6 driving + 25 on scene + 8 driving + 15 handover + 10 cleaning = **65 min**
before that ambulance can take the next call, against 22 min with the old values.

**Before:** every trip had 5 min of loading at the pickup and 3 min of unloading at the destination,
with no turnout, no cleaning, and the unit free again right after unloading.

## Sources

| Value | Source | Notes |
|---|---|---|
| Turnout ambulance 1 min | NFPA 1710: EMS turnout time ≤ 60 s ([IAFF summary](https://www.iaff.org/wp-content/uploads/English_Version_-_NFPA_1710_standards_DFSR_Summary_2022_new.pdf)). Slovenia: a red-call unit must start the intervention at the latest 1 minute after activation (dispatch rulebook art. 13, see [AGENTIC_DISPATCH_DESIGN.md](AGENTIC_DISPATCH_DESIGN.md) and [DATA_FRESHNESS.md](DATA_FRESHNESS.md)) | The Slovenian figures come from Metelko's research; we have not read the rulebook text ourselves |
| Turnout doctor car 5 min | Slovenia: "exit time normally 1 minute; a doctor vehicle may leave later, up to 5 minutes, with the delay documented" ([DATA_FRESHNESS.md](DATA_FRESHNESS.md)) | As above: reported by Metelko, not verified by us |
| On scene, ground EMS | Median on-scene time 17 min (IQR 13 to 23) ([BMJ Open, table 2](https://pmc.ncbi.nlm.nih.gov/articles/PMC4716242/table/BMJOPEN2015009599TB2)) | Our 12 to 20 min (25 for cardiac arrest) sit around that median, longer for the most severe |
| On scene, helicopter | Norwegian HEMS: median on-scene 10 min, cardiac arrest 20 min ([PMC5609050](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5609050/)) | We use the same table for the helicopter as for ambulances (slightly longer than these medians) |
| Handover 15 min | NHS standard: 65 % of handovers within 15 min, 95 % within 30 min ([NHS England, key lines of enquiry](https://www.england.nhs.uk/wp-content/uploads/2020/08/Reducing_ambulance_handover_delays_-_key_lines_of_enquiry_v1.1.pdf), [AACE](https://aace.org.uk/hospital-handovers/)). Slovenia: handover at most 15 min, then report free or give the reason (2017 dispatch rulebook art. 22, see [AGENTIC_DISPATCH_DESIGN.md](AGENTIC_DISPATCH_DESIGN.md)) | The Slovenian rule is a 2017 value that a 2025 law amended; Metelko could not check what changed ([DATA_FRESHNESS.md](DATA_FRESHNESS.md)) |
| Cleaning 10 min (ambulance) | Turnaround at the hospital including cleaning: San Francisco target ≤ 30 min ([SF EMS Policy 4000.1](https://media.api.sf.gov/documents/Policy-4000.1-Ambulance-Turnaround-Time-Standard-EMSAC-June-2026.pdf)); Scotland 26 to 34 min on average ([Scottish Ambulance Service FOI](https://www.scottishambulance.com/contact-us/freedom-of-information/foi-requests/turnaround-time/)); US mean 35.6 min ([Prehospital Emergency Care](https://informahealthcare.com/doi/abs/10.3109/10903127.2011.561412)) | Our handover 15 + cleaning 10 = 25 min, at the lower end of these turnarounds. The Slovenian statuses after an intervention include "returning unavailable" and "cleaning" ([AGENTIC_DISPATCH_DESIGN.md](AGENTIC_DISPATCH_DESIGN.md)) |
| Van times (8 min pickup, 5 min unloading, 5 min cleaning), equipment 5 min | **Assumption**: we found no reliable source for patient-transport vans or equipment runs | Chosen to be shorter than an emergency crew's, which do assessment and treatment |

## What changed in the simulation

- **Call rate:** 8 calls per world-hour would overload the three ambulances with these times
  (75 to 88 % busy, 9 to 19 red calls over 15 min in 8 world-hours). The default is now **5 per hour**:
  measured over 8 world-hours with two seeds, ambulances are **53 to 63 % busy**, vans 33 to 56 %,
  2 to 3 red calls over 15 min and 1 to 2 late trips (`CALLS_PER_HOUR` overrides it).
- **"Available soon"** now includes the handover and cleaning: a unit with a patient on board is
  25 min plus the drive from its drop-off away from a new call, so it rarely beats a free unit. A unit
  finishing its cleaning near the call often does ("ready 23:41 after handover and cleaning").
- **Scheduled day:** the vans' booked trips are spread over 6 hours instead of 4, so the day starts
  with no late trip for the default seed (other seeds may start with one or two).
- **A doctrine refinement** the longer times made necessary: a higher-level call may override a
  lower-level one even if the displaced call then misses its own target, but only when no other unit
  reaches the higher-level call within its target ([DISPATCH_PRIORITIES.md](DISPATCH_PRIORITIES.md),
  rule 2).
