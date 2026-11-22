"""The helicopter emergency medical service (HNMP, Slovenian HEMS): base, activation, landing, hours.

Values and sources (docs/SERVICE_TIMES.md, "Helicopter"; research in docs/EMS_RESEARCH.md section 4,
docs/LJUBLJANA_FLEET_AND_TEAMS.md, docs/DATA_FRESHNESS.md):

- Base: HNMP Brnik, at Ljubljana airport (LJLJ), 46.2237 N 14.4576 E (docs/map/ambulance_units.json,
  "helicopter_bases"), about 19 km north of UKC. Patients are flown to the UKC rooftop helipad (LJHL).
- Activation, from the call to take-off: 15, 15, 12, 16 and 13 min on average in 2021 to 2025 (HNMP
  site, EMS_RESEARCH.md "Performance"); we use the 2025 average, 13 min. It applies when the helicopter
  starts from rest at its base (crew rooms 250 m from the aircraft, airport security, start-up); an
  airborne helicopter (flying home after a job) is re-tasked without it.
- Landing: approach, landing and rotor-down at the end of each flight leg. No published figure: an
  assumption, a little longer at the scene (an unprepared site the pilot must check first, secured by
  police or fire) than on a prepared helipad (UKC's rooftop pad, the base). The lift-off from the scene or
  the hospital is inside the on-scene time and the handover/cleaning, which are longer than HEMS medians.
  No extra in-city landing allowance: the research says only that the helicopter lands where it can and
  police or fire secure the site (EMS_RESEARCH.md, "Activation"), with no minutes to model it.
- Hours: daytime only, 08:00 to sunset in the winter half (08:00 to 16:30 in winter 2026), 08:00 to
  20:00 in summer; no night flying found for HNMP. We model the winter schedule (the demo is in
  November). Outside the hours the helicopter takes no new calls; a mission already under way finishes.
- Fog or snow at Brnik grounds it: the fog event (engine/events.py), unchanged.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from .models import Vehicle
    from .state import WorldState

LJ = ZoneInfo("Europe/Ljubljana")

# (place id, name, kind, lat, lon): the HNMP base at Ljubljana airport (sim/seed.py PLACES).
HEMS_BASE = ("brnik", "HNMP base Brnik (Ljubljana airport)", "base", 46.2237, 14.4576)
HEMS_ACTIVATION_MIN = 13.0  # call to take-off from rest at the base (HNMP site, 2025 average)
HEMS_SCENE_LANDING_MIN = 3.0  # approach, landing and rotor-down near the patient [assumption]
HEMS_HELIPAD_LANDING_MIN = 2.0  # the same on a prepared helipad: a hospital, the base [assumption]
HEMS_HOURS = (time(8, 0), time(16, 30))  # local time, winter 2026 schedule (new calls only)
HEMS_HOURS_TEXT = "08:00-16:30"


def on_duty(now: datetime) -> bool:
    """True while the helicopter takes new calls (local time within HEMS_HOURS)."""
    t = now.astimezone(LJ).time()
    return HEMS_HOURS[0] <= t < HEMS_HOURS[1]


def next_start(now: datetime) -> datetime:
    """When the helicopter takes calls again: the next 08:00 local (now if on duty)."""
    if on_duty(now):
        return now
    local = now.astimezone(LJ)
    start = local.replace(hour=HEMS_HOURS[0].hour, minute=HEMS_HOURS[0].minute, second=0, microsecond=0)
    if local.time() >= HEMS_HOURS[1]:
        start += timedelta(days=1)  # aware arithmetic is wall-clock: still 08:00 across a DST change
    return start


def duty_end(now: datetime) -> datetime:
    """The end of the current (or next) operating day: 16:30 local."""
    start = next_start(now).astimezone(LJ)
    return start.replace(hour=HEMS_HOURS[1].hour, minute=HEMS_HOURS[1].minute, second=0, microsecond=0)


def off_duty_until(v: Vehicle, now: datetime) -> datetime | None:
    """For a helicopter outside its hours: when it takes calls again (None otherwise)."""
    if v.type != "helicopter" or on_duty(now):
        return None
    return next_start(now)


def takeoff_in_min(v: Vehicle, now: datetime) -> float | None:
    """Minutes until a helicopter can lift off for a new job: the whole activation at rest at its base,
    what is left of it while the crew is getting ready, None when it is airborne or busy otherwise."""
    if v.type != "helicopter":
        return None
    if v.status == "idle":
        return HEMS_ACTIVATION_MIN
    if v.status == "to_pickup" and v.busy_until is not None and v.busy_until > now:
        return (v.busy_until - now).total_seconds() / 60
    return None


def any_flying(state: WorldState) -> bool:
    """Is there a helicopter that could take a new call now (in service, not grounded, in its hours)?
    Advice such as "consider the helicopter" is given only then."""
    return any(
        v.type == "helicopter" and v.status != "out_of_service" and v.grounded_until is None and on_duty(state.sim_time)
        for v in state.vehicles.values()
    )


def night_reason(v: Vehicle, now: datetime) -> str:
    until = next_start(now).astimezone(LJ).strftime("%H:%M")
    return f"{v.name} is unavailable (night): HNMP flies {HEMS_HOURS_TEXT} only, no new flights until {until}"


def availability(v: Vehicle, now: datetime) -> dict[str, Any]:
    """Snapshot fields for a helicopter: why it takes no new calls now, if it does not.

    off_duty_until: ISO time it takes calls again (night), else None; unavailable: "night" | "fog" | None;
    unavailable_text: one line for the vehicle card / map."""
    if v.type != "helicopter":
        return {}
    until = off_duty_until(v, now)
    if v.grounded_until is not None:
        kind, text = "fog", f"Grounded by fog until {v.grounded_until.astimezone(LJ).strftime('%H:%M')}"
    elif until is not None:
        kind, text = "night", f"Unavailable (night): flies {HEMS_HOURS_TEXT}, available {until.astimezone(LJ).strftime('%H:%M')}"
    else:
        kind, text = None, None
    return {
        "off_duty_until": until.isoformat() if until else None,
        "unavailable": kind,
        "unavailable_text": text,
        "hours": HEMS_HOURS_TEXT,
    }
