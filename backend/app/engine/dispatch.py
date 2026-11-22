"""Engine dispatch of a new call, decided at once (docs/DISPATCH_PRIORITIES.md, section 3).

Every unit that could take the call is considered with its real time to reach the patient (each
option is simulated, so the numbers include drop-offs, handovers and knock-on effects):

- free: idle or driving home with nothing queued; goes now.
- available soon: has a patient on board; it finishes that drop-off and the handover, then drives
  to the new patient. A unit with a patient on board is never diverted.
- override: it is driving to a lower-level call it has not reached yet (not on scene, not within
  NEAR_PATIENT_MIN of that patient), turns around now, and the displaced call is re-dispatched to
  the best remaining unit. Both moves are simulated together.
- queued: busy with a same- or higher-level call; it comes after that job.

Rules applied automatically (rules 1, 2, 6):
1. The earliest arrival at the patient; for stroke and STEMI the arrival at UKC (definitive care,
   rule 7). A busy unit must beat the best free one by BUSY_UNIT_MIN_GAIN_MIN.
2. An override must save OVERRIDE_MIN_SAVING_MIN (3 min critical, 5 serious) against the best
   alternative, the displaced patient must still be reached within their own response target,
   and no call is displaced twice (rule 3). A unit the dispatcher assigned by hand (engine/units.held)
   is never diverted automatically: when it would have been the pick, the summary says so and the
   dispatcher can divert it with Override.
6. Helicopter: the absolute closest unit for a critical call (even in the city), 10 min faster for
   a serious one, 15 min and remote for an urgent one. Its times are the real service's (app/hems.py):
   based at Brnik, 13 min from the call to take-off, day only (08:00-16:30), so in practice it wins
   remote calls, and a city call only when no ambulance is free.
Same-level swaps (rule 4) are only proposed: swap_options().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from .. import hems
from ..geo import haversine_km
from ..models import Plan, PlanStep, Trip
from ..routing import flies, travel_minutes
from . import units
from .actions import EMERGENCY_UNITS, level, near_current_patient
from .doctors import origin_label, per_call_reserve, send_doctor
from .surge import is_contracted, is_transport, private_reason
from .projection import LATE_ALERT_MIN, route_trip_ids
from .severity import (
    BUSY_UNIT_MIN_GAIN_MIN,
    CONDITIONS,
    DEFINITIVE_CARE_CONDITIONS,
    HELICOPTER_GAIN_MIN,
    HELICOPTER_REMOTE_KM,
    OVERRIDE_MIN_SAVING_MIN,
    RED_REFERENCE_MIN,
    SWAP_MIN_GAIN_MIN,
    WEIGHT_CLEARLY_HIGHER,
    clinical_reason,
)

if TYPE_CHECKING:
    from ..state import WorldState

LJ = ZoneInfo("Europe/Ljubljana")
SWAP_WINDOW_MIN = 20.0  # swaps are proposed for calls dispatched within this many minutes


def _hhmm(dt: datetime | None) -> str:
    return dt.astimezone(LJ).strftime("%H:%M") if dt else "?"


def _mins(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds() / 60


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


@dataclass
class Option:
    kind: str  # free | soon | override | queued
    cand: dict[str, Any]  # find_candidates entry for the new trip on this unit
    reach: datetime  # when the unit reaches the new patient
    rank: float  # what is compared: minutes to the patient (or to UKC for stroke/STEMI) + helicopter handicap
    steps: list[PlanStep] = field(default_factory=list)
    displaced: Trip | None = None
    displaced_to: str | None = None  # unit that takes the displaced call (None = stays on this unit, after)
    displaced_pickup: datetime | None = None
    displaced_wait: float | None = None  # minutes from that call until it is reached
    displaced_ok: bool = True
    displaced_late: bool = False  # re-dispatched, but only after its own target (see _best)
    held: bool = False  # an override of a call the dispatcher gave this unit by hand: never automatic
    why_not: str | None = None

    @property
    def vehicle_id(self) -> str:
        return self.cand["vehicle_id"]


@dataclass
class Decision:
    trip: Trip
    chosen: Option | None
    best_free: Option | None
    options: list[Option]
    best_road: Option | None = None  # the best eligible ambulance option (what the helicopter must beat)
    private_reason: str | None = None  # set when a contracted ambulance was chosen (surge.private_reason)
    held_best: Option | None = None  # the pick if the dispatcher's own units could be diverted (not done)


def _kind(state: WorldState, cand: dict[str, Any]) -> str:
    v = state.vehicles[cand["vehicle_id"]]
    if cand["vehicle_free"]:
        return "free"
    current = state.trips.get(v.current_trip_id) if v.current_trip_id else None
    if current is not None and current.status == "onboard":
        return "soon"
    if current is None and v.busy_until and v.busy_until > state.sim_time and not v.queue:
        return "soon"  # handing over or cleaning after its last patient
    if cand["step"]["interrupt_current"] and current is not None:
        return "override"
    return "queued"


def _override(state: WorldState, opt: Option) -> None:
    """The override plan: the new call to this unit, the displaced call to the best other unit."""
    from .candidates import find_candidates
    from .plans import simulate_steps

    v = state.vehicles[opt.vehicle_id]
    displaced = state.trips[v.current_trip_id]  # type: ignore[index]
    opt.displaced = displaced
    if displaced.times_displaced:
        opt.displaced_ok, opt.why_not = False, f"{displaced.id} was already displaced once"
        return
    first = PlanStep(**opt.cand["step"])
    sim, errors, _ = simulate_steps(state, Plan(steps=[first]))
    second = None
    if not errors:
        may_fly = displaced.severity in ("critical", "serious")
        for c in find_candidates(sim, displaced.id, limit=50):
            if c["vehicle_id"] != v.id and not c["step"]["interrupt_current"] and (may_fly or not flies(c["vehicle_type"])):
                second = PlanStep(**c["step"])
                break
    # Re-dispatch to the best other unit, or keep it on this unit after the new call: whichever
    # reaches the displaced patient sooner.
    variants = []
    for steps in ([first, second], [first]) if second else ([first],):
        sim_v, errors_v, _ = simulate_steps(state, Plan(steps=steps))
        dv = sim_v.trips[displaced.id]
        if not errors_v and dv.eta_pickup:
            variants.append((max(dv.eta_pickup, dv.pickup_after), steps, sim_v))
    if variants:
        _, steps, sim = min(variants, key=lambda x: x[0])
        errors = []
    else:
        steps, errors = [first], ["the displaced call cannot be re-dispatched"]
        sim, _, _ = simulate_steps(state, Plan(steps=steps))
    d = sim.trips[displaced.id]
    opt.steps = steps
    opt.displaced_to = second.vehicle_id if len(steps) > 1 else None
    opt.displaced_pickup = max(d.eta_pickup, d.pickup_after) if d.eta_pickup else None
    if errors or opt.displaced_pickup is None:
        opt.displaced_ok, opt.why_not = False, "the displaced call cannot be re-dispatched"
        return
    opt.displaced_wait = _mins(opt.displaced_pickup, displaced.pickup_after)
    target = displaced.response_target_min
    opt.displaced_ok = (opt.displaced_wait <= target) if target else (d.delay_min or 0) < LATE_ALERT_MIN
    if not opt.displaced_ok:
        opt.displaced_late = True
        opt.why_not = f"{displaced.id} would be reached only after {opt.displaced_wait:.0f} min (target {target or 0:.0f})"


def decide(state: WorldState, trip: Trip) -> Decision:
    """Which unit should take this call now (nothing is changed)."""
    from .candidates import find_candidates

    lvl = trip.severity or "serious"
    pickup = state.places[trip.pickup_id]
    cands = find_candidates(state, trip.id, limit=100)
    road = [c for c in cands if c["vehicle_type"] == "ambulance"]
    definitive = trip.condition in DEFINITIVE_CARE_CONDITIONS

    def allowed(c: dict[str, Any]) -> bool:
        if c["vehicle_type"] == "ambulance":
            return True
        if not flies(c["vehicle_type"]):
            return False
        if lvl in ("critical", "serious") or not road:
            return True
        # An urgent call flies only when remote: far from the hospital the patient goes to (the city),
        # not from the helicopter's base (Brnik is itself 19 km from UKC).
        dest = state.places[trip.dropoff_id]
        return haversine_km(dest.lat, dest.lon, pickup.lat, pickup.lon) >= HELICOPTER_REMOTE_KM

    options: list[Option] = []
    seen: set[str] = set()
    for c in cands:  # the best option per unit comes first (find_candidates ranks them)
        if c["vehicle_type"] not in EMERGENCY_UNITS or not allowed(c) or c["vehicle_id"] in seen or not c["trip_eta_pickup"]:
            continue
        seen.add(c["vehicle_id"])
        kind = _kind(state, c)
        reach = c["trip_eta_pickup"]
        measure = c["trip_eta_dropoff"] if definitive and c["trip_eta_dropoff"] else reach
        opt = Option(kind, c, reach, _mins(measure, state.sim_time), steps=[PlanStep(**c["step"])])
        if kind == "override":
            _override(state, opt)
            opt.held = opt.displaced is not None and units.held(opt.displaced, opt.vehicle_id)
        options.append(opt)

    held_best = None
    if any(o.held for o in options):
        # What the rules would pick if the dispatcher's own units could be diverted: said, never done.
        why = [o.why_not for o in options]
        would = _choose(state, trip, options, holds=False)[0]
        held_best = would if would is not None and would.held else None
        for o, w in zip(options, why):
            o.why_not = w
    chosen, best_road, why_private = _choose(state, trip, options)
    free = [o for o in options if o.kind == "free" and not is_contracted(state.vehicles.get(o.vehicle_id))]
    best_free = min(free, key=lambda o: o.rank) if free else None
    return Decision(trip, chosen, best_free, options, best_road, why_private, held_best)


def _choose(
    state: WorldState, trip: Trip, options: list[Option], holds: bool = True
) -> tuple[Option | None, Option | None, str | None]:
    """The unit for this call among the options: (chosen, best road option, private reason).
    holds=False: as if the dispatcher's own units could be diverted too (see decide)."""
    lvl = trip.severity or "serious"
    # Contracted (private) ambulances do not compete like our own units: see the surge use rules below.
    contracted = [o for o in options if is_contracted(state.vehicles.get(o.vehicle_id))]
    public = [o for o in options if o not in contracted]
    road = [o for o in public if not flies(o.cand["vehicle_type"])]
    air = [o for o in public if flies(o.cand["vehicle_type"])]
    # For a critical call the helicopter is a real alternative: a road override must beat it too.
    air_alt = min((o for o in air if o.kind in ("free", "soon")), key=lambda o: o.rank, default=None) if lvl == "critical" else None
    best_road = _best(trip, road, competitor=air_alt, holds=holds)
    chosen = best_road
    # Rule 6: the helicopter replaces the best road unit only by its level's rule.
    gain_needed = HELICOPTER_GAIN_MIN.get(lvl, float("inf"))
    best_air = _best(trip, air, competitor=best_road, holds=holds)
    if best_air is not None:
        if best_road is None:
            chosen = best_air
        elif lvl == "critical" and best_air.rank < best_road.rank:
            chosen = best_air  # the absolute closest unit for a critical call, even in the city
        elif lvl != "critical" and best_air.rank <= best_road.rank - gain_needed:
            chosen = best_air
        else:
            best_air.why_not = f"not {gain_needed:.0f} min faster than {best_road.vehicle_id}" if lvl != "critical" else "not the closest"
    why_private = None
    priv = _best(trip, contracted, holds=holds)
    if priv is not None:
        why_private = private_reason(trip, chosen.reach if chosen else None, chosen.vehicle_id if chosen else None, priv.reach)
        if why_private:
            chosen = priv
    return chosen, best_road, why_private


def _best(trip: Trip, options: list[Option], competitor: Option | None = None, holds: bool = True) -> Option | None:
    """The best eligible option among these units (rules 1 to 3). competitor: the best unit of the
    other kind, which an override must also beat. holds: a unit the dispatcher assigned by hand is
    never diverted (False: as if it could be, see decide)."""
    lvl = trip.severity or "serious"
    free = [o for o in options if o.kind == "free"]
    best_free = min(free, key=lambda o: o.rank) if free else None
    eligible = list(free)
    for o in options:
        if o.kind in ("soon", "queued"):
            if best_free is None or o.rank <= best_free.rank - BUSY_UNIT_MIN_GAIN_MIN:
                eligible.append(o)
            else:
                o.why_not = f"only {best_free.rank - o.rank:.0f} min sooner than {best_free.vehicle_id}"
    alternatives = eligible + ([competitor] if competitor else [])
    best_alt = min(alternatives, key=lambda o: o.rank) if alternatives else None
    saving_needed = OVERRIDE_MIN_SAVING_MIN.get(lvl)
    # Higher level first: if nothing else reaches this call within its own target, an override may
    # leave the displaced (lower-level) call over its target too, rather than this one waiting.
    target = trip.response_target_min
    alt_misses = best_alt is None or (target is not None and _mins(best_alt.reach, trip.pickup_after) > target)
    for o in options:
        if o.kind == "override" and o.held and holds:
            o.why_not = f"assigned by the dispatcher to {o.displaced.id if o.displaced else 'its call'}"
            continue
        if o.kind != "override" or not (o.displaced_ok or (o.displaced_late and alt_misses)):
            continue
        if saving_needed is None or o.displaced is None or level(o.displaced) <= level(trip):
            o.why_not = "only a higher-level call overrides another"
            continue
        saving = (best_alt.rank - o.rank) if best_alt else float("inf")
        if saving >= saving_needed:
            eligible.append(o)
        else:
            o.why_not = f"saves only {saving:.0f} min (needs {saving_needed:.0f})"
    return min(eligible, key=lambda o: (o.rank, o.kind != "free")) if eligible else None


def _who(trip: Trip) -> str:
    return "the patient" if trip.kind == "patient" else "the pickup"


def _not_diverted(d: Decision) -> str:
    """"A1 not diverted: assigned by the dispatcher to TR-003 (Override to divert)" when the rules would
    have diverted a unit the dispatcher chose by hand; "" otherwise."""
    h = d.held_best
    if h is None or h.displaced is None:
        return ""
    return f"{h.vehicle_id} not diverted: assigned by the dispatcher to {h.displaced.id} (Override to divert)"


def dispatch_call(state: WorldState, trip: Trip) -> str:
    """Decide (see decide) and apply at once. Returns a clause for the event summary: who goes,
    why, when, and the clinical reason. An urgent call no emergency unit can take is queued on
    whichever vehicle (van or ambulance) reaches it first without diverting anyone. A unit the
    dispatcher assigned by hand is never diverted: if it would have been the pick, the summary and
    the chosen unit's reason say so."""
    from .candidates import find_candidates
    from .plans import _apply_steps

    d = decide(state, trip)
    held = _not_diverted(d)
    kept = f"; {held}" if held else ""  # its own clause in the summary, and after the unit's reason
    who = _who(trip)
    dest = state.places[trip.dropoff_id].name
    reason = f"; {_cap(clinical_reason(trip))}" if trip.severity in ("critical", "serious") else ""
    protect = (
        trip.priority == "urgent"
        and d.chosen is not None
        and d.chosen.kind == "free"
        and d.chosen.cand["vehicle_type"] == "ambulance"
        and not is_contracted(state.vehicles[d.chosen.vehicle_id])  # cover is about our own areas
        and _cover_gap(state, state.vehicles[d.chosen.vehicle_id]) > RED_REFERENCE_MIN
    )
    if trip.priority == "urgent" and (d.chosen is None or d.chosen.kind != "free" or protect):
        # No ambulance free for a non-emergency call (or sending it would leave its area without red
        # cover within 15 min): a van takes it if it gets there no later (when protecting cover: at all).
        vans = [  # only a van with at most one other job: queues stay short
            c for c in find_candidates(state, trip.id, limit=100)
            if c["vehicle_type"] == "transport" and not c["step"]["interrupt_current"] and c["trip_eta_pickup"]
            and len(route_trip_ids(state.vehicles[c["vehicle_id"]])) <= 1
            and (not is_contracted(state.vehicles[c["vehicle_id"]]) or is_transport(trip))  # private vans: transports only
        ]
        if vans and (d.chosen is None or protect or vans[0]["trip_eta_pickup"] <= d.chosen.reach):
            best = vans[0]
            _apply_steps(state, Plan(steps=[PlanStep(**best["step"])]))
            trip.dispatched_at = state.sim_time
            if protect:
                amb = state.vehicles[d.chosen.vehicle_id]  # type: ignore[union-attr]
                why = f"protect cover: {amb.id} is the last ambulance free near {state.places[amb.base_id].name}; van"
            else:
                why = "no ambulance free; van"
            units.note(state, trip, best["vehicle_id"], f"{why}, {best['pickup_in_min']:.0f} min{kept}")
            return (
                f"; dispatched {best['vehicle_id']} ({why}, {best['insertion']}): at {who} "
                f"{_hhmm(best['trip_eta_pickup'])} (in {best['pickup_in_min']:.0f} min), at {dest} {_hhmm(best['trip_eta_dropoff'])}"
                + kept
            )
    if d.chosen is None:
        if trip.priority == "emergency":
            doctor = send_doctor(state, trip)  # the doctor car still goes: first on scene
            return ("; no ambulance or helicopter can take it: request one from a neighbouring station"
                    + kept + _helicopter_unavailable(state) + doctor + reason)
        pool = [c for c in find_candidates(state, trip.id, limit=100) if not c["step"]["interrupt_current"]]
        if not pool:
            return "; no vehicle can take it yet: left for the dispatcher to plan" + kept
        best = pool[0]
        _apply_steps(state, Plan(steps=[PlanStep(**best["step"])]))
        trip.dispatched_at = state.sim_time
        units.note(state, trip, best["vehicle_id"], f"no ambulance free: {best['insertion']}, {best['pickup_in_min']:.0f} min{kept}")
        return (
            f"; dispatched {best['vehicle_id']} (no ambulance free; {best['insertion']}): at {who} "
            f"{_hhmm(best['trip_eta_pickup'])} (in {best['pickup_in_min']:.0f} min), at {dest} {_hhmm(best['trip_eta_dropoff'])}"
            + kept
        )

    o = d.chosen
    takeoff = hems.takeoff_in_min(state.vehicles[o.vehicle_id], state.sim_time)  # activation at Brnik (None: airborne)
    errors, _ = _apply_steps(state, Plan(steps=o.steps))
    if errors:  # cannot happen (just simulated): keep the call served by the plain option
        _apply_steps(state, Plan(steps=[PlanStep(**o.cand["step"])]))
    trip.dispatched_at = state.sim_time
    v = state.vehicles[o.vehicle_id]
    free = d.best_free
    compare = "at UKC" if trip.condition in DEFINITIVE_CARE_CONDITIONS else ""
    sooner = (
        f", {free.rank - o.rank:.0f} min sooner{' ' + compare if compare else ''} than {free.vehicle_id}"
        if free and free is not o and free.rank - o.rank >= 1
        else ""
    )
    when = f"at {who} {_hhmm(o.reach)} (in {_mins(o.reach, state.sim_time):.0f} min), at {dest} {_hhmm(o.cand['trip_eta_dropoff'])}"
    in_min = f"{_mins(o.reach, state.sim_time):.0f} min"
    # `unit_reason`: one line for trip.units (engine/units.py), e.g. "nearest free ambulance, 4 min"
    if flies(v.type):
        road = d.best_road
        # what the decision compared: arrival at UKC for stroke and heart attack, else at the patient
        gain = (road.rank - o.rank if compare else _mins(road.reach, o.reach)) if road else 0.0
        at_ukc = " at UKC" if compare else ""
        if road is None:
            why = "helicopter; no ambulance can take it"
        elif trip.severity == "critical":
            why = "helicopter: the closest unit for a critical call" + (f", {gain:.0f} min sooner than {road.vehicle_id}" if gain >= 1 else "")
        else:
            why = f"helicopter, {gain:.0f} min sooner{at_ukc} than {road.vehicle_id} by road"
        if o.kind == "override" and o.displaced is not None:
            why += f"; diverted from {o.displaced.id} ({o.displaced.severity})"
        up = f"take-off in {takeoff:.0f} min" if takeoff is not None else ""  # activation at its base (app/hems.py)
        clause = f"; dispatched {v.id} ({why}{'; ' + up if up else ''}): {when}"
        unit_reason = f"{why}, {in_min}{'; ' + up if up else ''}"
    elif o.kind == "free":
        clause = f"; dispatched {v.id} (nearest free ambulance): {when}"
        unit_reason = f"nearest free ambulance, {in_min}"
    elif o.kind == "soon":
        cur = state.trips[v.current_trip_id] if v.current_trip_id else None
        if cur and cur.status == "onboard":
            drop = f"drops off at {state.places[cur.dropoff_id].name} {_hhmm(cur.eta_dropoff)}, "
            where = f"finishes at {state.places[cur.dropoff_id].name}"
        elif v.busy_until and v.busy_until > state.sim_time:
            drop = f"ready {_hhmm(v.busy_until)} after handover and cleaning, "
            where = "ready after handover and cleaning"
        else:
            drop, where = "", "finishing its job"
        clause = f"; dispatched {v.id} ({'' if free else 'no unit free; '}available soon: {drop}{when}{sooner})"
        if free and free is not o and free.rank - o.rank >= 1:
            unit_reason = f"available soon: {where}, {free.rank - o.rank:.0f} min sooner{' ' + compare if compare else ''} than {free.vehicle_id}"
        else:
            unit_reason = f"available soon: {where}{'' if free else '; no unit free'}, {in_min}"
    elif o.kind == "override" and o.displaced is not None:
        clause = (
            f"; dispatched {v.id}, diverted from {o.displaced.id} ({o.displaced.severity}) to this {trip.severity} call: "
            f"{when}{sooner}"
        )
        unit_reason = f"diverted from {o.displaced.id} ({o.displaced.severity}) to this {trip.severity} call, {in_min}"
    else:
        clause = f"; dispatched {v.id} (no unit free; {o.cand['insertion']}): {when}"
        unit_reason = f"no unit free: {o.cand['insertion']}, {in_min}"
    if d.private_reason:  # surge capacity: a contracted ambulance, by the use rules
        clause = f"; dispatched {v.id} (contracted private ambulance: {d.private_reason}): {when}"
        unit_reason = f"contracted private ambulance: {d.private_reason}"
    units.note(state, trip, v.id, unit_reason + kept)
    clause += send_doctor(state, trip, v.id, o.reach)  # " + doctor D1 (ZD Center, at the patient 22:05, ...)"
    clause += kept
    wait = _mins(max(o.reach, trip.pickup_after), trip.pickup_after)
    if trip.severity in ("critical", "serious") and wait > RED_REFERENCE_MIN and per_call_reserve(state):
        names = ", ".join(f"{r.id} ({origin_label(state, r)})" for r in per_call_reserve(state))
        clause += f"; no own unit within {RED_REFERENCE_MIN:.0f} min: can request {names}"

    if o.kind == "override" and o.displaced is not None:
        dsp = o.displaced
        dsp.times_displaced += 1
        dsp.dispatched_at = state.sim_time
        if not dsp.response_target_min:
            target = "on time"
        elif (o.displaced_wait or 0) <= dsp.response_target_min:
            target = f"within its {dsp.response_target_min:.0f}-min target"
        else:
            target = f"after its {dsp.response_target_min:.0f}-min target: no unit can reach it sooner"
        if o.displaced_to:
            clause += f"; {dsp.id} taken over by {o.displaced_to} (at {_who(dsp)} {_hhmm(o.displaced_pickup)}, {target})"
            units.note(state, dsp, o.displaced_to, f"takes over: {v.id} was diverted to {trip.severity} call {trip.id}")
        else:
            clause += f"; {dsp.id} stays with {v.id}, next (at {_who(dsp)} {_hhmm(o.displaced_pickup)}, {target})"
    if trip.severity in ("critical", "serious") and not flies(v.type):
        # The helicopter is evaluated for every red call: say what it would have done.
        air = next((x for x in d.options if flies(x.cand["vehicle_type"])), None)
        if air is not None:
            up = hems.takeoff_in_min(state.vehicles[air.vehicle_id], state.sim_time)  # 13 min from rest at Brnik
            notes = [n for n in (f"take-off in {up:.0f} min" if up is not None else "", air.why_not or "") if n]
            clause += f"; {air.vehicle_id} checked: at {who} {_hhmm(air.reach)}" + (f" ({'; '.join(notes)})" if notes else "")
        else:
            clause += _helicopter_unavailable(state)
    return clause + reason


def _helicopter_unavailable(state: WorldState) -> str:
    """For a red call: why no helicopter could even be considered (night hours or fog), "" otherwise."""
    out = ""
    for h in state.vehicles.values():
        if not flies(h.type) or h.status == "out_of_service":
            continue
        if h.grounded_until is not None:
            out += f"; {h.id} not available: grounded by fog until {_hhmm(h.grounded_until)}"
        elif hems.off_duty_until(h, state.sim_time) is not None:
            out += f"; {h.id} not available: night (HNMP flies {hems.HEMS_HOURS_TEXT})"
    return out


def _cover_gap(state: WorldState, v) -> float:
    """If ambulance v leaves now: minutes the nearest other free ambulance needs to reach v's base
    (its area) under lights and sirens; infinite if none is free."""
    from .candidates import is_free

    base = state.places[v.base_id]
    times = [
        travel_minutes(state, o.lat, o.lon, base.lat, base.lon, "ambulance", True)
        for o in state.vehicles.values()
        if o.id != v.id and o.type == "ambulance" and is_free(state, o)
    ]
    return min(times, default=float("inf"))


# --- Same-level swaps (rule 4): proposed, never automatic ----------------------------------


def _wait(state: WorldState, t: Trip) -> float | None:
    """Minutes from the call (its ready time) until a unit reaches the patient."""
    if not t.eta_pickup:
        return None
    return _mins(max(t.eta_pickup, t.pickup_after), t.pickup_after)


def swap_options(state: WorldState) -> list[dict[str, Any]]:
    """For a critical/serious call dispatched recently and not yet reached: would the unit driving to
    another call of the same level serve it better, with the first unit taking that other call?
    - weights clearly different: the more time-critical patient should get the sooner unit
      (proposed if that patient is reached SWAP_MIN_GAIN_MIN sooner and the other stays within target);
    - weights comparable: minimise the worse of the two waits relative to the targets (proposed if
      that saves SWAP_MIN_GAIN_MIN), tie-break by the total wait."""
    from .plans import simulate_steps

    out = []
    recent = [
        t
        for t in state.trips.values()
        if t.severity in ("critical", "serious")
        and t.dispatched_at
        and t.status in ("assigned", "en_route_pickup")
        and t.vehicle_id
        and state.sim_time - t.dispatched_at <= timedelta(minutes=SWAP_WINDOW_MIN)
    ]
    for t in recent:
        first = state.vehicles[t.vehicle_id]  # type: ignore[index]
        if route_trip_ids(first)[:1] != [t.id]:
            continue  # only when this call is the unit's next job
        w_t = _wait(state, t)
        best = None
        for other in state.vehicles.values():
            cur = state.trips.get(other.current_trip_id) if other.current_trip_id else None
            if (
                other.id == first.id
                or cur is None
                or cur.status == "onboard"
                or level(cur) != level(t)
                or near_current_patient(state, other, cur) is not None
            ):
                continue
            w_o = _wait(state, cur)
            if w_t is None or w_o is None:
                continue
            steps = [
                PlanStep(trip_id=t.id, vehicle_id=other.id, position=0, interrupt_current=True),
                PlanStep(trip_id=cur.id, vehicle_id=first.id),
            ]
            sim, errors, _ = simulate_steps(state, Plan(steps=steps))
            if errors:
                continue
            a_t, a_o = _wait(sim, sim.trips[t.id]), _wait(sim, sim.trips[cur.id])
            if a_t is None or a_o is None:
                continue
            tt, to = t.response_target_min or 60.0, cur.response_target_min or 60.0
            if t.time_weight >= cur.time_weight + WEIGHT_CLEARLY_HIGHER:
                # the new call is clearly more time-critical: it should get the sooner unit
                gain, why = w_t - a_t, f"{t.condition_label or t.severity} before {cur.condition_label or cur.severity}"
                ok = gain >= SWAP_MIN_GAIN_MIN and a_o <= to
            elif cur.time_weight >= t.time_weight + WEIGHT_CLEARLY_HIGHER:
                continue  # the other call is the more time-critical one and keeps its unit
            else:
                ref = tt if w_t / tt >= w_o / to else to
                gain = (max(w_t / tt, w_o / to) - max(a_t / tt, a_o / to)) * ref
                why = "shorter worst wait"
                ok = gain >= SWAP_MIN_GAIN_MIN
            if not ok:
                continue
            key = (gain, (w_t + w_o) - (a_t + a_o))
            if best is None or key > best[0]:
                best = (key, other, cur, steps, (w_t, w_o, a_t, a_o), sim, why)
        if best is None:
            continue
        _, other, cur, steps, (w_t, w_o, a_t, a_o), sim, why = best
        text = (
            f"Swap: {other.id} takes {t.id} (reached {_hhmm(sim.trips[t.id].eta_pickup)} instead of {_hhmm(t.eta_pickup)}), "
            f"{first.id} takes {cur.id} ({_hhmm(sim.trips[cur.id].eta_pickup)} instead of {_hhmm(cur.eta_pickup)})"
        )
        if why == "shorter worst wait":
            text += f" · worst wait {max(w_t, w_o):.0f} → {max(a_t, a_o):.0f} min"
            reason = "Comparable urgency: the shorter worst wait"
        else:
            label_t = t.condition_label or t.severity
            label_o = cur.condition_label or cur.severity
            text += (
                f" · {label_t} reached {w_t - a_t:.0f} min sooner; {label_o} {a_o - w_o:.0f} min later, "
                f"still within its {cur.response_target_min or 60:.0f}-min target"
            )
            why_t = CONDITIONS[t.condition][3] if t.condition in CONDITIONS else clinical_reason(t)
            reason = f"{label_t} before {(label_o or '').lower()}: {why_t}"
        out.append(
            {
                "trip_id": t.id,
                "other_trip_id": cur.id,
                "vehicles": [first.id, other.id],
                "steps": [s.model_dump() for s in steps],
                "worst_wait_before_min": round(max(w_t, w_o), 1),
                "worst_wait_after_min": round(max(a_t, a_o), 1),
                "text": text,
                "reason": reason,
            }
        )
    return out
