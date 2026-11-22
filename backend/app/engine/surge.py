"""Proactive surge capacity with contracted units (docs/DISPATCH_PRIORITIES.md, section 6).

Slovenian practice (docs/AGENTIC_DISPATCH_DESIGN.md 5.4, docs/SURGE_AND_MULTI_SERVICE_COORDINATION.md,
docs/DISPATCH_SCENARIOS.md): when demand outgrows the own fleet the dispatcher brings in contracted
private units. Bypass models it in three parts:

1. The demand trigger (live-calls mode): free own ambulances at most DEMAND_FREE_SHARE of those
   crewed, or a red call predicted to wait more than 15 min, or DEMAND_PAST_TARGET or more open calls
   predicted past their response target. It raises the alert "high_demand" saying what would help.
   It never activates anything by itself.
2. Contracted surge capacity, activated only by the dispatcher (the alert's button, POST
   /{world}/admin/surge, or an approved option with activate_surge): ambulances P1 and P2 with
   qualified crews, private vans PV1 to PV3 for non-urgent transports, for SURGE_HOURS. At the end of
   the contract each unit finishes its current job, returns and leaves the fleet.
3. While they are in the fleet the engine uses them by these rules (mapped to our severities):
   - transports (routine, urgent transfers and equipment): private vans first;
   - urgent calls: a contracted ambulance when our own would reach the patient more than
     PRIVATE_URGENT_WAIT_MIN after the call, or the contracted one is PRIVATE_URGENT_GAIN_MIN sooner;
   - critical and serious calls: a private ambulance only if no public unit arrives within 15 min
     and it is faster.
   Activating it also moves the waiting calls that these rules give to the new units, so the queue
   clears at once.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from ..models import Alert, EventRecord, Plan, PlanStep, Trip, Vehicle
from .doctors import activate_reserve, reserve_area, stand_down_reserve
from .severity import RED_REFERENCE_MIN

if TYPE_CHECKING:
    from ..state import WorldState

LJ = ZoneInfo("Europe/Ljubljana")

# The demand trigger (thresholds from docs/DISPATCH_SCENARIOS.md, "Demand trigger").
DEMAND_FREE_SHARE = 0.25  # free own ambulances at most this share of those crewed (3 crewed: none free)
DEMAND_RED_WAIT_MIN = RED_REFERENCE_MIN  # a red call predicted to wait longer than this (15 min)
DEMAND_PAST_TARGET = 2  # or at least this many open calls predicted past their response target
# The alert itself has hysteresis (with three ambulances the raw trigger is on 22-53 % of the time):
# raised only when the trigger has been on for DEMAND_RAISE_AFTER_MIN world-minutes AND patients are
# affected (a red call over 15 min, or DEMAND_PAST_TARGET calls past their target); cleared only when
# that (trigger on and patients affected) has been false for DEMAND_CLEAR_AFTER_MIN.
DEMAND_RAISE_AFTER_MIN = 5.0
DEMAND_CLEAR_AFTER_MIN = 5.0

# The contracted pool and the default offer.
SURGE_AMBULANCES = ("P1", "P2")
SURGE_VANS = ("PV1", "PV2", "PV3")
SURGE_HOURS = 2.0
SURGE_MAX_HOURS = 12.0

# How the contracted units are used while they are in the fleet.
PRIVATE_RED_GAIN_MIN = 1.0  # red: only when no public unit is within 15 min, and at least this much faster
PRIVATE_URGENT_WAIT_MIN = 45.0  # urgent: when our own unit reaches the patient this long after the call ...
PRIVATE_URGENT_GAIN_MIN = 10.0  # ... or the contracted ambulance is this much sooner
PRIVATE_VAN_GAIN_MIN = 5.0  # on activation: a queued transport moves to a private van if collected this much sooner
TRANSPORT_CONDITIONS = ("transfer", "equipment")


def _hhmm(dt: datetime | None) -> str:
    return dt.astimezone(LJ).strftime("%H:%M") if dt else "?"


def _mins(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds() / 60


def is_contracted(v: Vehicle | None) -> bool:
    return v is not None and v.origin == "private"


def is_transport(trip: Trip) -> bool:
    """A non-urgent or transport job (routine booking, urgent transfer, equipment): private vans first."""
    return trip.kind == "equipment" or trip.priority == "scheduled" or trip.condition in TRANSPORT_CONDITIONS


def active(state: WorldState) -> bool:
    return state.surge_until is not None and state.surge_until > state.sim_time


def _wait(trip: Trip, reach: datetime | None) -> float:
    if reach is None:
        return math.inf
    return _mins(max(reach, trip.pickup_after), trip.pickup_after)


# --- The demand trigger -------------------------------------------------------------------------


def past_target(state: WorldState) -> list[tuple[Trip, float]]:
    """Open calls not yet reached that are predicted (or already) past their response target."""
    out = []
    for t in state.trips.values():
        if t.status not in ("unassigned", "assigned", "en_route_pickup") or not t.response_target_min:
            continue
        if t.priority not in ("emergency", "urgent") or is_transport(t):
            continue
        w = _wait(t, t.eta_pickup) if t.eta_pickup else _mins(state.sim_time, t.pickup_after)
        if w > t.response_target_min:
            out.append((t, w))
    return sorted(out, key=lambda x: -x[1])


def demand(state: WorldState) -> dict[str, Any]:
    """The demand trigger: is it on, and why (plain sentences)."""
    from .candidates import is_free
    from .projection import red_wait_min

    if state.scheduled_day:
        return {"high": False, "reasons": [], "free_ambulances": None, "crewed_ambulances": None}
    crewed = [v for v in state.vehicles.values() if v.type == "ambulance" and v.origin == "own" and v.status != "out_of_service"]
    free = [v for v in crewed if is_free(state, v)]
    reasons = []
    if crewed and len(free) <= DEMAND_FREE_SHARE * len(crewed):
        reasons.append(f"{len(free)} of {len(crewed)} own ambulances free")
    red = sorted(((t, w) for t in state.trips.values() if (w := red_wait_min(t)) is not None and w > DEMAND_RED_WAIT_MIN),
                 key=lambda x: -x[1])
    for t, w in red[:2]:
        reasons.append(f"red call {t.id} ({t.condition_label or t.severity}) reached only after {math.ceil(w)} min")
    late = past_target(state)
    if len(late) >= DEMAND_PAST_TARGET:
        reasons.append(f"{len(late)} calls predicted past their response target")
    worst = red[0][0] if red else (late[0][0] if late else None)
    return {
        "high": bool(reasons),
        "reasons": reasons,
        "free_ambulances": len(free),
        "crewed_ambulances": len(crewed),
        "red_over_15_min": [t.id for t, _ in red],
        "past_target": [t.id for t, _ in late],
        "worst_trip_id": worst.id if worst else None,
    }


# --- The contracted pool -------------------------------------------------------------------------


def available(state: WorldState) -> dict[str, list[str]]:
    """Contracted units that an activation would bring in (P1 counts if it is in the fleet for a single call)."""
    def ok(vid: str) -> bool:
        if vid in state.reserve_vehicles:
            return True
        v = state.vehicles.get(vid)
        return v is not None and v.contract_until is None and not v.contract_ended
    return {"ambulances": [v for v in SURGE_AMBULANCES if ok(v)], "vans": [v for v in SURGE_VANS if ok(v)]}


def _unit(state: WorldState, vid: str) -> Vehicle | None:
    return state.vehicles.get(vid) or state.reserve_vehicles.get(vid)


def offer_text(state: WorldState, ambulances: int = 2, vans: int = 3, hours: float = SURGE_HOURS) -> str:
    avail = available(state)
    amb = [f"{v} ({reserve_area(state, _unit(state, v))})" for v in avail["ambulances"][:ambulances] if _unit(state, v)]
    pv = avail["vans"][:vans]
    parts = []
    if amb:
        parts.append(f"contracted ambulances {', '.join(amb)} with qualified crews")
    if pv:
        parts.append(f"private vans {pv[0]}–{pv[-1] if len(pv) > 1 else ''}".rstrip("–") + " for non-urgent transports")
    return f"Activate surge capacity for {hours:g} h: " + "; ".join(parts) if parts else "No contracted units available"


def status(state: WorldState) -> dict[str, Any]:
    """For the snapshot: is surge capacity active, until when, which units; what an activation would add."""
    units = [v.id for v in state.vehicles.values() if v.contract_until is not None]
    return {
        "active": active(state),
        "until": state.surge_until.isoformat() if active(state) and state.surge_until else None,
        "units": units,
        "available": available(state),
        "offer": offer_text(state),
        "default": {"ambulances": len(SURGE_AMBULANCES), "vans": len(SURGE_VANS), "hours": SURGE_HOURS},
    }


def patients_affected(d: dict[str, Any]) -> bool:
    """The trigger is about patients, not only about how many ambulances are free."""
    return bool(d.get("red_over_15_min")) or len(d.get("past_target") or []) >= DEMAND_PAST_TARGET


def update_demand_alert(state: WorldState, d: dict[str, Any] | None = None) -> bool:
    """Advance the alert's hysteresis with the current trigger (world time); returns whether it is raised."""
    d = d if d is not None else demand(state)
    now = state.sim_time
    if d["high"]:
        if state.demand_high_since is None or state.demand_high_since > now:
            state.demand_high_since = now
    else:
        state.demand_high_since = None
    sustained = state.demand_high_since is not None and now - state.demand_high_since >= timedelta(minutes=DEMAND_RAISE_AFTER_MIN)
    # "On" for the alert: the trigger and patients affected. All units busy alone keeps nothing raised.
    on = d["high"] and patients_affected(d)
    if on:
        state.demand_low_since = None
        if not state.demand_alert and sustained:
            state.demand_alert = True
    elif state.demand_alert:
        if state.demand_low_since is None or state.demand_low_since > now:
            state.demand_low_since = now
        if now - state.demand_low_since >= timedelta(minutes=DEMAND_CLEAR_AFTER_MIN):
            state.demand_alert, state.demand_low_since = False, None
    return state.demand_alert


def assume_sustained(state: WorldState) -> None:
    """For a demo scenario that stages demand which built up before it starts (the surge scenario):
    the trigger counts as on for long enough already."""
    if demand(state)["high"]:
        state.demand_high_since = state.sim_time - timedelta(minutes=DEMAND_RAISE_AFTER_MIN)


def alert_on(state: WorldState) -> bool:
    return bool(getattr(state, "demand_alert", False))


def high_demand_alert(state: WorldState) -> Alert | None:
    d = demand(state)
    if not update_demand_alert(state, d):
        return None
    if not (d["high"] and patients_affected(d)):  # still raised for under DEMAND_CLEAR_AFTER_MIN after it eased
        return Alert(id="high_demand", kind="high_demand", severity="medium",
                     message="High demand easing: no patient has waited too long for under "
                             f"{DEMAND_CLEAR_AFTER_MIN:g} min; keep watching before standing anything down.",
                     trip_id=d.get("worst_trip_id"))
    why = "; ".join(d["reasons"])
    if active(state):
        help_ = f"surge capacity is active until {_hhmm(state.surge_until)}"
    elif any(available(state).values()):
        avail = available(state)
        help_ = (f"activating contracted units would help ({len(avail['ambulances'])} ambulances, "
                 f"{len(avail['vans'])} private vans for {SURGE_HOURS:g} h)")
    else:
        help_ = "no contracted units left: ask a neighbouring station"
    return Alert(
        id="high_demand",
        kind="high_demand",
        severity="critical" if d["red_over_15_min"] else "high",
        message=f"High demand: {why}. {help_[:1].upper() + help_[1:]}.",
        trip_id=d["worst_trip_id"],
    )


# --- Activation, stand-down, expiry --------------------------------------------------------------


def _record(state: WorldState, kind: str, summary: str, affected: list[str]) -> EventRecord:
    from .projection import kpis, project_all

    project_all(state)
    record = EventRecord(
        id=state.new_id("EV"), sim_time=state.sim_time, type=kind, payload={}, summary=summary,
        affected_trip_ids=list(dict.fromkeys(affected)), kpis_before=kpis(state), kpis_after=kpis(state),
    )
    state.events.append(record)
    state.bump()
    return record


def activate(state: WorldState, ambulances: int = len(SURGE_AMBULANCES), vans: int = len(SURGE_VANS),
             hours: float = SURGE_HOURS, kpis_before: dict | None = None) -> EventRecord:
    """The dispatcher brings in contracted units until now + hours. Waiting calls that the use rules
    give to them move at once. Calling it again extends the contract (and adds units)."""
    from .projection import kpis

    before = kpis_before or kpis(state)
    until = state.sim_time + timedelta(hours=max(0.25, min(hours, SURGE_MAX_HOURS)))
    ids = list(SURGE_AMBULANCES[: max(0, ambulances)]) + list(SURGE_VANS[: max(0, vans)])
    joined = []
    for vid in ids:
        v = state.vehicles.get(vid)
        if v is None and vid in state.reserve_vehicles:
            v = activate_reserve(state, vid)
        if v is None or v.contract_ended:
            continue
        v.contract_until = until
        joined.append(vid)
    state.surge_until = until if joined else state.surge_until
    moved = rebalance(state)
    amb = [f"{v} ({reserve_area(state, state.vehicles[v])})" for v in joined if state.vehicles[v].type == "ambulance"]
    pv = [v for v in joined if state.vehicles[v].type == "transport"]
    summary = f"Surge capacity active until {_hhmm(until)}: " + "; ".join(
        filter(None, [f"contracted ambulances {', '.join(amb)}" if amb else "", f"private vans {', '.join(pv)}" if pv else ""])
    )
    summary += ("; moved: " + "; ".join(m for m, _ in moved)) if moved else "; no waiting call needs them yet"
    record = _record(state, "surge_capacity", summary, [t for _, t in moved])
    record.kpis_before = before
    return record


def _end_contract(state: WorldState, v: Vehicle) -> list[str]:
    """No new jobs; queued (not started) ones are dispatched again; it finishes its current job, returns, leaves."""
    from .actions import detach_trip
    from .events import dispatch_call

    v.contract_ended = True
    v.contract_until = min(v.contract_until or state.sim_time, state.sim_time)
    out = []
    for tid in list(v.queue):
        trip = state.trips[tid]
        detach_trip(state, trip)
        trip.status = "unassigned"
        out.append(f"{tid}" + dispatch_call(state, trip).replace(";", ":", 1))
    if v.current_trip_id is None:
        base = state.places[v.base_id]
        if v.status == "idle" and abs(v.lat - base.lat) < 1e-4 and abs(v.lon - base.lon) < 1e-4:
            stand_down_reserve(state, v)  # already home: it leaves now
        else:
            v.status = "returning"
    return out


def stand_down(state: WorldState, why: str = "stood down by the dispatcher") -> EventRecord | None:
    units = [v for v in list(state.vehicles.values()) if v.contract_until is not None and not v.contract_ended]
    state.surge_until = None
    if not units:
        return None
    redispatched = []
    for v in units:
        redispatched += _end_contract(state, v)
    summary = (f"Surge capacity {why}: {', '.join(v.id for v in units)} finish their current job and leave"
               + (f"; re-dispatched {'; '.join(redispatched)}" if redispatched else ""))
    return _record(state, "surge_capacity", summary, [r.split(":")[0] for r in redispatched])


def expire(state: WorldState) -> EventRecord | None:
    """Called every tick: at the end of the contract the units finish, return and leave."""
    if state.surge_until is not None and state.sim_time >= state.surge_until:
        return stand_down(state, "contract ended")
    return None


# --- Using the contracted units ------------------------------------------------------------------


def private_reason(trip: Trip, own_reach: datetime | None, own_id: str | None, private_reach: datetime) -> str | None:
    """Why a contracted ambulance should take this call instead of the best public unit (None: it should not)."""
    if is_transport(trip):
        return None  # transports go to vans
    own_wait = _wait(trip, own_reach)
    gain = math.inf if own_reach is None else _mins(max(own_reach, trip.pickup_after), max(private_reach, trip.pickup_after))
    against = f" than {own_id}" if own_id else ""
    if trip.severity in ("critical", "serious"):
        if own_wait > RED_REFERENCE_MIN and gain >= PRIVATE_RED_GAIN_MIN:
            return (f"no public unit within {RED_REFERENCE_MIN:.0f} min, {gain:.0f} min sooner{against}"
                    if own_reach else "no public unit can take it")
        return None
    if (own_wait > PRIVATE_URGENT_WAIT_MIN and gain >= 1) or gain >= PRIVATE_URGENT_GAIN_MIN:
        if own_reach is None:
            return "no own unit can take it"
        return (f"own unit only after {own_wait:.0f} min" if own_wait > PRIVATE_URGENT_WAIT_MIN
                else f"{gain:.0f} min sooner{against}")
    return None


def rebalance(state: WorldState) -> list[tuple[str, str]]:
    """Move waiting calls to the contracted units where the use rules say so (highest level first).
    Returns (summary, trip id) per move. Never touches a patient on board or a unit on scene or within
    2 min of its patient; a transport already under way is not turned around."""
    from .actions import level, near_current_patient
    from .candidates import find_candidates
    from .plans import _apply_steps
    from .projection import project_all

    project_all(state)
    contracted = {v.id for v in state.vehicles.values() if is_contracted(v) and not v.contract_ended}
    if not contracted:
        return []
    waiting = sorted(
        (t for t in state.trips.values() if t.status in ("unassigned", "assigned", "en_route_pickup")),
        key=lambda t: (level(t), -t.time_weight, t.pickup_after),
    )
    moved: list[tuple[str, str]] = []
    for t in waiting:
        v = state.vehicles.get(t.vehicle_id) if t.vehicle_id else None
        if v is not None and v.id in contracted:
            continue  # already with a contracted unit
        if v is not None and v.current_trip_id == t.id and near_current_patient(state, v, t) is not None:
            continue  # its unit is on scene or within 2 min: never taken away
        now_reach = t.eta_pickup if t.vehicle_id else None
        transport = is_transport(t)
        if transport and v is not None and v.current_trip_id == t.id:
            continue  # already on its way: not turned around
        want = "transport" if transport else "ambulance"
        cands = [
            c for c in find_candidates(state, t.id, limit=50)
            if c["vehicle_id"] in contracted and c["vehicle_type"] == want and not c["step"]["interrupt_current"] and c["trip_eta_pickup"]
        ]
        if not cands:
            continue
        best = min(cands, key=lambda c: c["trip_eta_pickup"])
        new_reach = best["trip_eta_pickup"]
        if transport:
            gain = math.inf if now_reach is None else _mins(max(now_reach, t.pickup_after), max(new_reach, t.pickup_after))
            if gain < PRIVATE_VAN_GAIN_MIN:
                continue
        elif private_reason(t, now_reach, t.vehicle_id, new_reach) is None:
            continue
        errors, _ = _apply_steps(state, Plan(steps=[PlanStep(**best["step"])]))
        if errors:
            continue
        project_all(state)
        who = "the patient" if t.kind == "patient" else "the pickup"
        was = f" instead of {_hhmm(max(now_reach, t.pickup_after))}" if now_reach else ""
        moved.append((f"{t.id} → {best['vehicle_id']} (at {who} {_hhmm(max(new_reach, t.pickup_after))}{was})", t.id))
    return moved
