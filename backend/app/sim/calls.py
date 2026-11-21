"""Live-calls mode: a stream of synthetic calls, each dispatched by the engine the moment it comes in.

The mix is close to a city EMS evening: emergencies at addresses around Ljubljana (to UKC), now and
then a remote one where the helicopter is clearly faster, urgent field calls, urgent patient
transports (health centre -> UKC, GP referrals, urgent discharges, inter-hospital transfers) and
urgent equipment runs (blood products, lab samples, a ventilator). Every call is emergency or urgent.

Calls go through the normal event path (apply_event): emergencies and field calls are dispatched to
the nearest suitable free unit (dispatch_call); transports and equipment are booked onto a van (an
ambulance only if no van can take it), and when nothing fits on time they go to the vehicle that can
collect them soonest. A generated call never starts an AI analysis by itself: step() only reports
"problems" (a call no unit can take, or one that will be late) and the caller decides.

Each world has its own generator with its own seeded RNG (the trips and the scenarios stay
reproducible); arrivals are exponential with CALLS_PER_HOUR in world time.
"""
from __future__ import annotations

import random
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .. import config

if TYPE_CHECKING:
    from ..models import EventRecord
    from ..state import WorldState

MIN_GAP_MIN, MAX_GAP_MIN = 2.0, 25.0  # clamp the random gaps between calls (world minutes)
MAX_CALLS_PER_STEP = 3  # catch up after a long pause, but never flood
PROBLEM_RUN_GAP_MIN = 15.0  # at most one automatic analysis for call problems per this many minutes
SCENARIO_QUIET_MIN = 30.0  # after a demo scenario starts, no new calls for this long (world time)

# Where calls come from. City areas get most calls; the suburbs some.
CITY = ["home_siska", "home_vic", "home_moste", "home_bezigrad", "home_rudnik", "home_crnuce", "home_polje"]
SUBURBS = ["home_domzale", "home_medvode", "home_grosuplje", "home_skofljica", "home_vrhnika"]
HEALTH_CENTRES = ["zd_center", "zd_siska", "zd_vic"]
# Remote spots where the helicopter is clearly faster than any ambulance by road (approximate).
REMOTE = [
    ("Kamniška Bistrica (hiking trail)", 46.3085, 14.5910, "hiker fell, suspected spinal injury"),
    ("Krvavec (ski area)", 46.2960, 14.5330, "skier collision, head injury"),
    ("Sava valley near Litija", 46.0560, 14.8300, "farm accident, crushed leg"),
]
# Emergencies: about 10% critical (life-threatening now), the rest serious (docs/DISPATCH_PRIORITIES.md).
CRITICAL_SHARE = 0.10
CRITICAL_CONDITIONS = [("cardiac_arrest", 4), ("choking", 2), ("catastrophic_bleeding", 2), ("anaphylaxis", 2)]
SERIOUS_CONDITIONS = [("stroke", 3), ("stemi", 3), ("breathing_difficulty", 3), ("major_trauma", 2), ("seizure", 2), ("sepsis", 1)]
EMERGENCY_NOTES = {
    "cardiac_arrest": "unconscious, not breathing; caller instructed in CPR",
    "choking": "choking, cannot speak",
    "catastrophic_bleeding": "heavy bleeding from a leg wound",
    "anaphylaxis": "bee sting, swelling of the throat",
    "stroke": "face drooping, slurred speech",
    "stemi": "crushing chest pain, sweating",
    "breathing_difficulty": "severe breathing difficulty",
    "major_trauma": "traffic accident, injured driver",
    "seizure": "seizure still going on",
    "sepsis": "high fever, confused, low blood pressure",
}
FIELD_NOTES = ["fall at home, cannot get up", "suspected wrist fracture", "fall on the stairs, hip pain"]


def _modifiers(rng: random.Random, condition: str) -> list[str]:
    """Occasional case modifiers that raise a call's weight within its level."""
    mods = []
    if condition == "cardiac_arrest" and rng.random() < 0.5:
        mods.append("no_bystander_cpr")
    if condition == "stroke" and rng.random() < 0.2:
        mods.append("late_stroke_window")
    if condition == "major_trauma" and rng.random() < 0.1:
        mods.append("multiple_patients")
    if rng.random() < 0.05:
        mods.append("child")
    if rng.random() < 0.05:
        mods.append("deteriorating")
    return mods

# (kind, weight). Tuned so that ambulances and vans are typically 50-70 % busy at 8 calls/hour.
MIX = [
    ("emergency", 0.38),
    ("field_urgent", 0.08),
    ("remote", 0.03),
    ("hc_to_ukc", 0.14),
    ("gp_referral", 0.08),
    ("discharge", 0.07),
    ("transfer", 0.02),  # long runs (Trbovlje, Novo mesto): rare, they tie a van up for 2 to 3 hours
    ("blood", 0.09),
    ("lab", 0.08),
    ("ventilator", 0.01),
]


@dataclass
class CallGenerator:
    """Per-world call stream state (no engine imports here: state.py holds one of these)."""

    enabled: bool = field(default_factory=lambda: config.CALLS_ENABLED)
    per_hour: float = field(default_factory=lambda: config.CALLS_PER_HOUR)
    rng: random.Random = field(default_factory=random.Random)
    next_at: datetime | None = None
    paused_until: datetime | None = None
    last_problem_run_at: datetime | None = None
    generated: int = 0

    def reset(self, seed: int, world: str, now: datetime) -> None:
        self.rng = random.Random(seed * 7919 + zlib.crc32(world.encode()))
        self.paused_until = self.last_problem_run_at = None
        self.generated = 0
        self.next_at = now + self._gap()

    def _gap(self) -> timedelta:
        mean = 60.0 / max(self.per_hour, 0.1)
        return timedelta(minutes=min(MAX_GAP_MIN, max(MIN_GAP_MIN, self.rng.expovariate(1 / mean))))

    def pause(self, until: datetime) -> None:
        self.paused_until = until
        if self.next_at is None or self.next_at < until:
            self.next_at = until + self._gap()

    def status(self, state: WorldState) -> dict[str, Any]:
        active = self.enabled and not state.scheduled_day
        return {
            "enabled": self.enabled,
            "active": active,  # calls are generated now (live-calls mode, switched on)
            "per_hour": self.per_hour,
            "next_at": self.next_at.isoformat() if active and self.next_at else None,
            "paused_until": self.paused_until.isoformat() if self.paused_until and self.paused_until > state.sim_time else None,
            "generated": self.generated,
        }


def _address(state: WorldState, rng: random.Random, suburbs_share: float = 0.25) -> tuple[str, float, float]:
    """A random street address: near a city area (or a suburb), up to ~600 m away from its centre."""
    pid = rng.choice(SUBURBS if rng.random() < suburbs_share else CITY)
    p = state.places[pid]
    lat = p.lat + rng.uniform(-0.0054, 0.0054)
    lon = p.lon + rng.uniform(-0.0078, 0.0078)
    return p.name, round(lat, 5), round(lon, 5)


def build_call(state: WorldState, rng: random.Random, kind: str | None = None):
    """One synthetic call as an operator event (UrgentRequestEvent or TaskRequestEvent)."""
    from ..models import TaskRequestEvent, UrgentRequestEvent

    kind = kind or rng.choices([k for k, _ in MIX], weights=[w for _, w in MIX])[0]
    if kind == "emergency":
        area, lat, lon = _address(state, rng)
        critical = rng.random() < CRITICAL_SHARE
        pool = CRITICAL_CONDITIONS if critical else SERIOUS_CONDITIONS
        condition = rng.choices([c for c, _ in pool], weights=[w for _, w in pool])[0]
        return UrgentRequestEvent(
            type="urgent_request", lat=lat, lon=lon, place_name=f"{area} (call)", dropoff_id="ukc", needs="stretcher",
            priority="emergency", severity="critical" if critical else "serious", condition=condition,
            modifiers=_modifiers(rng, condition), note=EMERGENCY_NOTES.get(condition),
        )
    if kind == "field_urgent":
        area, lat, lon = _address(state, rng)
        condition = rng.choice(["fall", "fall", "fracture"])
        return UrgentRequestEvent(
            type="urgent_request", lat=lat, lon=lon, place_name=f"{area} (call)", dropoff_id="ukc",
            needs="stretcher" if rng.random() < 0.6 else "seated", priority="urgent", severity="urgent",
            condition=condition, modifiers=["child"] if rng.random() < 0.05 else [], note=rng.choice(FIELD_NOTES),
        )
    if kind == "remote":
        name, lat, lon, note = rng.choice(REMOTE)
        return UrgentRequestEvent(
            type="urgent_request", lat=lat, lon=lon, place_name=name, dropoff_id="ukc",
            needs="stretcher", priority="emergency", severity="serious", condition="major_trauma", note=note,
        )

    def booking(pickup: str, dropoff: str, needs: str, note: str, label: str | None = None, ready=(0, 15)):
        return TaskRequestEvent(
            type="task_request", kind="equipment" if needs == "equipment" else "patient",
            pickup_id=pickup, dropoff_id=dropoff, needs=needs, priority="urgent",  # type: ignore[arg-type]
            ready_in_min=rng.randint(*ready), label=label, note=note, if_late="soonest",
            severity="urgent", condition="equipment" if needs == "equipment" else "transfer",
        )

    needs = rng.choices(["seated", "wheelchair", "stretcher"], weights=[4, 3, 3])[0]
    if kind == "hc_to_ukc":
        return booking(rng.choice(HEALTH_CENTRES), "ukc", needs, "referred to the UKC emergency department")
    if kind == "gp_referral":
        return booking(rng.choice(CITY + SUBURBS), "ukc", needs, "GP referral: needs hospital assessment today")
    if kind == "discharge":
        return booking(rng.choice(["ukc", "ukc", "onko"]), rng.choice(CITY + SUBURBS), needs, "urgent discharge: bed needed", ready=(5, 20))
    if kind == "transfer":
        far = rng.choice(["sb_trbovlje", "sb_novo_mesto"])
        a, b = ("ukc", far) if rng.random() < 0.5 else (far, "ukc")
        return booking(a, b, "stretcher", "inter-hospital transfer", ready=(10, 30))
    if kind == "blood":
        return booking("ukc", rng.choice(["onko", "zd_center", "zd_vic"]), "equipment", "for a transfusion", "blood products", (0, 10))
    if kind == "lab":
        return booking(rng.choice(HEALTH_CENTRES), "ukc", "equipment", "to the central lab", "lab samples", (0, 10))
    return booking("ukc", rng.choice(["sb_trbovlje", "sb_novo_mesto"]), "equipment", "ICU loan to a regional hospital", "ventilator", (10, 30))


def problem_of(state: WorldState, record: EventRecord) -> str | None:
    """Why a dispatched call needs a dispatcher's attention (None = handled)."""
    from ..engine.projection import LATE_ALERT_MIN

    trip = state.trips.get(record.affected_trip_ids[0]) if record.affected_trip_ids else None
    if trip is None:
        return None
    if trip.status == "unassigned":
        return f"no unit can take {trip.id} ({trip.label}, {trip.priority})"
    if (trip.delay_min or 0) >= LATE_ALERT_MIN:
        return f"{trip.id} ({trip.label}, {trip.priority}) will be {trip.delay_min:.0f} min late with {trip.vehicle_id}"
    return None


def step(state: WorldState) -> list[tuple[EventRecord, str | None]]:
    """Generate the calls that are due. Returns (event record, problem or None) per call."""
    from ..engine.events import apply_event

    gen: CallGenerator = state.calls
    if not gen.enabled or state.scheduled_day or gen.next_at is None:
        return []
    now = state.sim_time
    if gen.paused_until and now < gen.paused_until:
        return []
    out: list[tuple[EventRecord, str | None]] = []
    while now >= gen.next_at and len(out) < MAX_CALLS_PER_STEP:
        record = apply_event(state, build_call(state, gen.rng))
        record.generated = True
        gen.generated += 1
        out.append((record, problem_of(state, record)))
        gen.next_at += gen._gap()
    if now >= gen.next_at:  # still behind after a long pause: skip ahead instead of a burst
        gen.next_at = now + gen._gap()
    return out


def may_analyse(state: WorldState) -> bool:
    """A call problem may start an analysis: auto-analyse on, none running, not too often."""
    gen: CallGenerator = state.calls
    if not state.auto_analyze or any(r.status == "running" for r in state.agent_runs):
        return False
    last = gen.last_problem_run_at
    if last is not None and state.sim_time - last < timedelta(minutes=PROBLEM_RUN_GAP_MIN):
        return False
    gen.last_problem_run_at = state.sim_time
    return True
