"""Reproducible one-click demo scenarios for the pitch (live-calls mode).

Each scenario re-seeds the world in live-calls mode (no pre-planned day), puts the fleet to work
on a few live jobs (fixed vehicles, so it is reproducible), fast-forwards to an interesting moment
and applies its events. Every scenario leaves a real decision for the AI when the operator presses
Analyse (with auto-analyse on, one analysis starts by itself). New random calls are paused for
SCENARIO_QUIET_MIN world-minutes so they don't disturb that decision.
"""
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Callable

from . import config
from .agent import runner as agent
from .engine.actions import assign_trip
from .engine.events import EMERGENCY_SLACK_MIN, URGENT_SLACK_MIN, apply_event
from .engine.projection import LOAD_MIN, project_all
from .engine.severity import grade
from .models import (
    BreakdownEvent,
    DelayEvent,
    EventRecord,
    HospitalCapacityEvent,
    Place,
    PriorityChangeEvent,
    RoadClosureEvent,
    Trip,
    UrgentRequestEvent,
    Vehicle,
    WeatherOverrideEvent,
)
from .routing import travel_minutes
from .sim.calls import SCENARIO_QUIET_MIN
from .sim.seed import seed_world
from .sim.simulator import tick

if TYPE_CHECKING:
    from .state import WorldState

STEP_S = 30.0
MAX_FAST_FORWARD_MIN = 90
BOOKED_SLACK_MIN = 30  # live urgent transports: deadline = ready + direct + loading + this

# Kamniška Bistrica (valley below the Kamnik Alps), approximate: ~30 km from UKC, ~45 min by road.
REMOTE_CALL = (46.3085, 14.5910)
KRVAVEC = (46.2960, 14.5330)


def _fast_forward(state: WorldState, minutes: float, until: Callable[[], Any] | None = None) -> Any:
    for _ in range(int(minutes * 60 / STEP_S)):
        tick(state, STEP_S)
        project_all(state)
        if until and (found := until()):
            return found
    return None


def _job(
    state: WorldState,
    vehicle_id: str | None,
    pickup: str | tuple[float, float, str],
    dropoff: str = "ukc",
    priority: str = "urgent",
    needs: str = "seated",
    note: str | None = None,
    cargo: str | None = None,
    ready_min: float = 0,
    severity: str | None = None,
    condition: str | None = None,
    modifiers: list[str] | None = None,
) -> Trip:
    """A live job that came in earlier and was dispatched to vehicle_id (None = not yet assigned).
    pickup is a place id, or (lat, lon, name) for a call at a street address."""
    if isinstance(pickup, tuple):
        lat, lon, name = pickup
        place = Place(id=state.new_id("call"), name=name, kind="call_location", lat=lat, lon=lon)
        state.places[place.id] = place
        pickup = place.id
    a, b = state.places[pickup], state.places[dropoff]
    emergency = priority == "emergency"
    direct = travel_minutes(state, a.lat, a.lon, b.lat, b.lon, "ambulance" if emergency else "transport", emergency)
    if emergency:
        slack = EMERGENCY_SLACK_MIN
    elif vehicle_id and state.vehicles[vehicle_id].type != "transport":
        slack = URGENT_SLACK_MIN  # an urgent field call (ambulance or helicopter)
    else:
        slack = BOOKED_SLACK_MIN  # an urgent transport or equipment run (van)
    ready = state.sim_time + timedelta(minutes=ready_min)
    trip = Trip(
        id=f"TR-{len(state.trips) + 1:03d}",
        kind="equipment" if cargo else "patient",
        patient=None if cargo else f"P-{len(state.trips) + 100}",
        cargo=cargo,
        priority=priority,  # type: ignore[arg-type]
        needs="equipment" if cargo else needs,  # type: ignore[arg-type]
        pickup_id=pickup,
        dropoff_id=dropoff,
        pickup_after=ready,
        due_by=(ready + timedelta(minutes=direct + LOAD_MIN + slack)).replace(microsecond=0),
        note=note,
        severity=severity,  # type: ignore[arg-type]
        condition=condition or ("equipment" if cargo else ("transfer" if priority == "urgent" and vehicle_id and vehicle_id.startswith("T") else None)),
        modifiers=modifiers or [],
    )
    grade(state, trip)
    state.trips[trip.id] = trip
    if vehicle_id:
        assign_trip(state, trip.id, vehicle_id)
        trip.dispatched_at = state.sim_time
    return trip


def _near(state: WorldState, place_id: str, dlat: float, dlon: float, name: str) -> tuple[float, float, str]:
    p = state.places[place_id]
    return (round(p.lat + dlat, 5), round(p.lon + dlon, 5), name)


def _onboard(trip: Trip) -> Callable[[], bool]:
    return lambda: trip.status == "onboard"


def _park(state: WorldState, vehicle_id: str, place_id: str, status: str = "returning") -> None:
    """Put a free unit somewhere (e.g. driving home from a job far away)."""
    v, p = state.vehicles[vehicle_id], state.places[place_id]
    v.lat, v.lon, v.status, v.path_from, v.path_to = p.lat, p.lon, status, None, None  # type: ignore[assignment]


def _helicopter_on_remote_job(state: WorldState) -> Trip:
    return _job(state, "H1", (KRVAVEC[0], KRVAVEC[1], "Krvavec (ski area)"), priority="emergency", severity="serious",
                condition="major_trauma", note="skier collision, head injury")


def _blood_run_on_t1(state: WorldState) -> Trip:
    """The crew-demo set-up: background work, and T1 (with one more job queued) loads blood products
    at UKC for the Oncology Institute."""
    _job(state, "A2", _near(state, "home_bezigrad", 0.002, -0.003, "Bežigrad (call)"), priority="emergency",
         needs="stretcher", severity="serious", condition="stemi", note="crushing chest pain, sweating")
    _job(state, "T3", "zd_siska", needs="wheelchair", note="referred to the UKC emergency department")
    _job(state, "T4", "ukc", "home_rudnik", needs="seated", note="urgent discharge: bed needed", ready_min=5)
    blood = _job(state, "T1", "ukc", "onko", cargo="blood products", note="for a transfusion", ready_min=2)
    _job(state, "T1", "zd_center", "ukc", cargo="lab samples", note="to the central lab", ready_min=10)
    if not _fast_forward(state, 30, until=_onboard(blood)):
        raise RuntimeError("T1 did not load the blood products")
    return blood


def _equipment_en_route(state: WorldState) -> list[EventRecord]:
    """Preparation for the live crew demo: T1 is carrying blood products. No events, no AI run: the
    crew then reports the problem themselves from the crew view ("Vozilo je obstalo. Oprema je še v njem.")."""
    _blood_run_on_t1(state)
    return []


def _stranded_equipment(state: WorldState) -> list[EventRecord]:
    """T1 breaks down with the blood products on board: another vehicle must collect them at the
    breakdown site (and T1's next job needs a vehicle). Decision: who goes, ambulance or van."""
    _blood_run_on_t1(state)
    return [apply_event(state, BreakdownEvent(type="breakdown", vehicle_id="T1", note="gearbox failure, equipment on board"))]


def _stranded_patient(state: WorldState) -> list[EventRecord]:
    """T2 breaks down with an urgent patient on board (and one more job queued). Two ambulances are
    on serious calls, so collecting the patient fast means using the last free ambulance or a van."""
    _job(state, "A1", _near(state, "home_vic", 0.002, 0.004, "Vič (call)"), priority="emergency", needs="stretcher",
         severity="serious", condition="breathing_difficulty", note="severe breathing difficulty")
    _job(state, "A2", _near(state, "home_bezigrad", -0.002, 0.003, "Bežigrad (call)"), priority="emergency",
         needs="stretcher", severity="serious", condition="seizure", note="seizure still going on")
    _job(state, "T3", "zd_vic", needs="wheelchair", note="referred to the UKC emergency department")
    patient = _job(state, "T2", "zd_siska", needs="wheelchair", note="referred to the UKC emergency department")
    _job(state, "T2", "home_siska", needs="seated", note="GP referral: needs hospital assessment today", ready_min=15)
    if not _fast_forward(state, 30, until=lambda: patient.status == "onboard" and state.vehicles["T2"].status == "with_patient"):
        raise RuntimeError("T2 did not load its patient")
    _fast_forward(state, 1.5)  # under way
    return [apply_event(state, BreakdownEvent(type="breakdown", vehicle_id="T2", note="engine failure, patient on board"))]


def _hospital_full(state: WorldState) -> list[EventRecord]:
    """Five patients are heading to UKC when one of them (in a van) gets chest pain (now serious,
    suspected heart attack) and UKC can admit only two more. The engine sends an ambulance to the
    heart attack at once; the AI decides who is redirected where (Trbovlje / Novo mesto)."""
    _job(state, "A1", _near(state, "home_moste", 0.001, 0.003, "Moste (call)"), priority="emergency", needs="stretcher",
         severity="serious", condition="seizure", note="seizure still going on")
    _job(state, "T3", "zd_vic", needs="wheelchair", note="referred to the UKC emergency department")
    worsening = _job(state, "T4", "home_crnuce", needs="seated", note="GP referral: needs hospital assessment today")
    _job(state, "T5", "zd_center", needs="stretcher", note="referred to the UKC emergency department")
    _job(state, "T2", "home_siska", needs="seated", note="GP referral: needs hospital assessment today", ready_min=10)
    _fast_forward(state, 4)
    return [
        apply_event(
            state,
            PriorityChangeEvent(type="priority_change", trip_id=worsening.id, severity="serious", condition="stemi",
                                note="condition worsened, chest pain"),
        ),
        apply_event(state, HospitalCapacityEvent(type="hospital_capacity", place_id="ukc", capacity=2, note="emergency department full")),
    ]


def _stroke_rush_hour(state: WorldState) -> list[EventRecord]:
    """Available soon (rule 1): a stroke in Polje while Zaloška is closed. A2 is about to hand over a
    patient at UKC, the only free ambulance (A3) is driving back from a transfer to Novo mesto and H1 is out on a
    mountain call. The engine sends A2 at once: drop-off, handover, then Polje, and it compares arrival
    at UKC (the stroke centre). The loaded leg goes around the closure."""
    _helicopter_on_remote_job(state)
    a2_job = _job(state, "A2", _near(state, "home_bezigrad", 0.001, -0.002, "Bežigrad (call)"), priority="emergency",
                  needs="stretcher", severity="serious", condition="breathing_difficulty", note="severe breathing difficulty")
    _job(state, "A1", _near(state, "home_vic", 0.003, -0.004, "Vič (call)"), priority="emergency", needs="stretcher",
         severity="serious", condition="sepsis", note="high fever, confused, low blood pressure")
    _job(state, "T5", "zd_center", needs="seated", note="referred to the UKC emergency department")
    _fast_forward(state, 20, until=lambda: a2_job.status == "onboard" and state.vehicles["A2"].status == "with_patient"
                  and a2_job.eta_dropoff is not None and (a2_job.eta_dropoff - state.sim_time).total_seconds() <= 150)
    # The only free ambulance is far away, driving back from a transfer to Novo mesto, so the unit
    # finishing at UKC is clearly sooner with real road times too, even through the Zaloška closure
    # (from Medvode or Vrhnika the motorway made A3 about as fast as A2).
    _park(state, "A3", "sb_novo_mesto")
    return [
        apply_event(
            state,
            RoadClosureEvent(
                type="road_closure", lat=46.05615, lon=14.53621, radius_m=250,
                description="Zaloška cesta closed after a collision (Kodeljevo, on the way to UKC)",
            ),
        ),
        apply_event(
            state,
            UrgentRequestEvent(
                type="urgent_request", pickup_id="home_polje", dropoff_id="ukc", needs="stretcher",
                priority="emergency", severity="serious", condition="stroke", note="face drooping, slurred speech; FAST positive",
            ),
        ),
    ]


def _priority_override(state: WorldState) -> list[EventRecord]:
    """Override (rule 2): A1 is on its way to an urgent fall in Polje when a cardiac arrest is reported
    next to it, with no bystander CPR. A2 has a patient on board, the only free ambulance (A3) is
    driving home from Medvode and H1 is out. The engine diverts A1 at once and gives the fall to A3,
    still within its 60-min target."""
    _helicopter_on_remote_job(state)
    _job(state, "A2", _near(state, "home_bezigrad", 0.001, -0.002, "Bežigrad (call)"), priority="emergency",
         needs="stretcher", severity="serious", condition="stemi", note="crushing chest pain, sweating")
    _job(state, "A1", _near(state, "home_polje", -0.002, 0.004, "Polje (call)"), priority="urgent", needs="stretcher",
         severity="urgent", condition="fall", note="fall at home, cannot get up")
    _park(state, "A3", "home_medvode")
    _fast_forward(state, 2)
    a1 = state.vehicles["A1"]
    return [
        apply_event(
            state,
            UrgentRequestEvent(
                type="urgent_request", lat=round(a1.lat + 0.004, 5), lon=round(a1.lon + 0.006, 5), place_name="Moste (call)",
                dropoff_id="ukc", needs="stretcher", priority="emergency", severity="critical", condition="cardiac_arrest",
                modifiers=["no_bystander_cpr"], note="unconscious, not breathing; nobody is doing CPR",
            ),
        )
    ]


def _same_level(state: WorldState) -> list[EventRecord]:
    """Same level, different urgency (rule 4): A1 is on its way to a seizure in Polje when a suspected
    heart attack is reported right next to it; A3 (free, from the west) is sent to the heart attack.
    Both are serious, so nothing changes automatically. Decision: the heart attack is more
    time-critical (catheter lab within 90 min): swap, A1 takes it and A3 the seizure."""
    _job(state, "A2", _near(state, "home_bezigrad", 0.001, -0.002, "Bežigrad (call)"), priority="emergency",
         needs="stretcher", severity="serious", condition="breathing_difficulty", note="severe breathing difficulty")
    _job(state, "A1", _near(state, "home_polje", -0.002, 0.004, "Polje (call)"), priority="emergency", needs="stretcher",
         severity="serious", condition="seizure", note="seizure still going on")
    _fast_forward(state, 2)
    a1 = state.vehicles["A1"]
    return [
        apply_event(
            state,
            UrgentRequestEvent(
                type="urgent_request", lat=round(a1.lat + 0.003, 5), lon=round(a1.lon + 0.004, 5), place_name="Moste (call)",
                dropoff_id="ukc", needs="stretcher", priority="emergency", severity="serious", condition="stemi",
                note="crushing chest pain, sweating",
            ),
        )
    ]


def _remote_emergency(state: WorldState) -> list[EventRecord]:
    """Override with the helicopter (rules 2 and 6): H1 is flying to an urgent call (a skier with a
    wrist fracture on Krvavec) when a hiker falls in Kamniška Bistrica (major trauma, 45 min by road).
    The engine turns H1 around at once and gives the skier to the nearest ambulance, still within its
    target. H1 flies, lands, loads and lands at UKC."""
    _job(state, "H1", (KRVAVEC[0], KRVAVEC[1], "Krvavec (ski area)"), priority="urgent", needs="seated",
         severity="urgent", condition="fracture", note="skier, suspected wrist fracture, cannot ski down")
    _job(state, "T3", "zd_vic", needs="wheelchair", note="referred to the UKC emergency department")
    _fast_forward(state, 2)
    return [
        apply_event(
            state,
            UrgentRequestEvent(
                type="urgent_request", lat=REMOTE_CALL[0], lon=REMOTE_CALL[1], place_name="Kamniška Bistrica (hiking trail)",
                dropoff_id="ukc", needs="stretcher", priority="emergency", severity="serious", condition="major_trauma",
                note="hiker fell, suspected spinal injury; 45 min by road",
            ),
        )
    ]


def _snow_cascade(state: WorldState) -> list[EventRecord]:
    """Snowstorm: every journey takes longer, T1 is stuck behind a jack-knifed truck for 25 min with a
    patient waiting and another job queued, and a fall on ice with a head injury comes in. Urgent
    transports turn late: the AI moves jobs to vans with slack and decides who waits."""
    _job(state, "A1", _near(state, "home_rudnik", 0.002, -0.002, "Rudnik (call)"), priority="emergency", needs="stretcher",
         severity="serious", condition="major_trauma", note="traffic accident, injured driver")
    _job(state, "T1", "zd_center", needs="wheelchair", note="referred to the UKC emergency department", ready_min=3)
    _job(state, "T1", "home_bezigrad", needs="seated", note="GP referral: needs hospital assessment today", ready_min=12)
    _job(state, "T2", "zd_siska", needs="stretcher", note="referred to the UKC emergency department")
    _job(state, "T2", "ukc", "home_crnuce", needs="seated", note="urgent discharge: bed needed", ready_min=20)
    _job(state, "T3", "zd_vic", "ukc", cargo="lab samples", note="to the central lab", ready_min=5)
    _fast_forward(state, 3)
    return [
        apply_event(state, WeatherOverrideEvent(type="weather_override", snowfall_cm=3, temperature_c=-2, precipitation_mm=3)),
        apply_event(state, DelayEvent(type="delay", vehicle_id="T1", minutes=25, note="stuck behind a jack-knifed truck")),
        apply_event(
            state,
            UrgentRequestEvent(
                type="urgent_request", pickup_id="home_siska", dropoff_id="ukc", needs="stretcher", priority="emergency",
                severity="serious", condition="major_trauma", note="fall on ice, head injury, drowsy",
            ),
        ),
    ]


def _surge(state: WorldState) -> list[EventRecord]:
    """Seven calls within about three minutes, one of them a cardiac arrest, and only three ambulances:
    the engine sends the free ones, the closest unit (the helicopter if need be) to the arrest; the
    next serious calls queue behind a patient, the urgent fall goes to a van. Decision: who waits
    (by time sensitivity), the helicopter, help from a neighbouring station."""
    _job(state, "T4", "zd_vic", needs="wheelchair", note="referred to the UKC emergency department")
    _fast_forward(state, 1)
    calls = [
        (_near(state, "home_moste", 0.002, 0.004, "Moste (call)"), "serious", "stemi", [], "crushing chest pain"),
        (_near(state, "home_siska", -0.002, 0.003, "Šiška (call)"), "serious", "stroke", ["late_stroke_window"], "face drooping since 3 hours"),
        (_near(state, "home_vic", 0.003, -0.002, "Vič (call)"), "serious", "major_trauma", [], "traffic accident, injured cyclist"),
        (_near(state, "home_bezigrad", 0.002, 0.002, "Bežigrad (call)"), "critical", "cardiac_arrest", ["no_bystander_cpr"],
         "unconscious, not breathing"),
        (_near(state, "home_crnuce", -0.003, 0.003, "Črnuče (call)"), "urgent", "fall", [], "fall at home, cannot get up"),
        (_near(state, "home_rudnik", 0.002, 0.003, "Rudnik (call)"), "serious", "seizure", [], "seizure still going on"),
        (_near(state, "home_polje", -0.002, -0.004, "Polje (call)"), "serious", "breathing_difficulty", ["child"], "child, severe breathing difficulty"),
    ]
    records = []
    for (lat, lon, name), severity, condition, modifiers, note in calls:
        records.append(
            apply_event(
                state,
                UrgentRequestEvent(
                    type="urgent_request", lat=lat, lon=lon, place_name=name, dropoff_id="ukc",
                    needs="seated" if severity == "urgent" else "stretcher",
                    priority="urgent" if severity == "urgent" else "emergency",
                    severity=severity, condition=condition, modifiers=modifiers, note=note,  # type: ignore[arg-type]
                ),
            )
        )
        _fast_forward(state, 0.5)
    return records


SCENARIOS: dict[str, tuple[str, Callable[[WorldState], list[EventRecord]]]] = {
    "stranded_patient": ("Van breaks down with an urgent patient on board", _stranded_patient),
    "stroke_rush_hour": ("Stroke near a closure: an ambulance finishing at UKC goes next", _stroke_rush_hour),
    "priority_override": ("Cardiac arrest next to an ambulance on its way to a fall", _priority_override),
    "same_level": ("Two serious calls, one close ambulance: heart attack before seizure", _same_level),
    "remote_emergency": ("Remote emergency in the mountains: the helicopter turns around", _remote_emergency),
    "surge": ("Surge: seven calls at once, including a cardiac arrest", _surge),
    "snow_cascade": ("Snowstorm, a stuck van and an emergency at once", _snow_cascade),
    "stranded_equipment": ("Van breaks down with blood products on board", _stranded_equipment),
    "hospital_full": ("UKC can admit only two more patients as a patient becomes an emergency", _hospital_full),
    "equipment_en_route": ("Prep for the live crew demo: T1 is carrying blood products", _equipment_en_route),
}
# Scenarios whose point is a decision the engine takes by itself at dispatch time (rules 1, 2, 6).
AUTOMATIC = {"stroke_rush_hour", "priority_override", "remote_emergency"}


def _loaded_with_equipment(state: WorldState) -> Vehicle | None:
    return next(
        (
            v
            for v in state.vehicles.values()
            if v.current_trip_id
            and state.trips[v.current_trip_id].kind == "equipment"
            and state.trips[v.current_trip_id].status == "onboard"
        ),
        None,
    )


def prepare(state: WorldState, name: str) -> list[EventRecord]:
    """Re-seed in live-calls mode and build the scenario (no AI run). Raises KeyError if unknown."""
    if name not in SCENARIOS:
        raise KeyError(name)
    seed_world(state, config.RANDOM_SEED, scheduled_day=False)
    records = SCENARIOS[name][1](state)
    state.calls.pause(state.sim_time + timedelta(minutes=SCENARIO_QUIET_MIN))  # let the decision be made first
    project_all(state)
    return records


def run_scenario(state: WorldState, name: str) -> dict[str, Any]:
    if name not in SCENARIOS:
        raise KeyError(name)
    title = SCENARIOS[name][0]
    agent.cancel_all(state)
    records = prepare(state, name)
    if not records:  # preparation scenario: nothing happened yet, so no AI run
        v = _loaded_with_equipment(state)
        trip = state.trips[v.current_trip_id] if v and v.current_trip_id else None
        note = (
            f"{v.id} ({v.name}) is carrying {trip.cargo} to {state.places[trip.dropoff_id].name}. "
            f"Open /crew/{v.id}?world=sim on the phone and report the problem."
            if v and trip
            else "Ready."
        )
        state.bump()
        return {"scenario": name, "title": title, "events": [], "run_id": None, "note": note, "vehicle_id": v.id if v else None}
    question = (
        f"Demo scenario: {title}. These events just happened together: "
        + "; ".join(f"({i + 1}) {r.summary}" for i, r in enumerate(records))
        + ". Analyse the combined situation and recommend what to do."
    )
    if not state.auto_analyze:  # analysis on demand only: the operator presses Analyse
        state.pending_question = question  # the next Analyse gets the scenario's description
        state.pending_scenario_events = {r.id for r in records}  # ... unless something else happens first
        state.bump()
        note = f"Scenario started: {title}. Auto-analyse is off: press Analyse (A) for the AI's recommendation."
        return {"scenario": name, "title": title, "events": records, "run_id": None, "note": note}
    run = agent.start_run(state, trigger=f"scenario:{name}", question=question)
    if run is None:  # automatic analysis skipped: Claude usage limit reached (app/guard.py)
        state.pending_question = question  # the operator's Analyse still gets the scenario's description
        state.pending_scenario_events = {r.id for r in records}
        state.bump()
        note = f"Scenario started: {title}. The AI limit is reached: press Analyse (A) for the engine's plan."
        return {"scenario": name, "title": title, "events": records, "run_id": None, "note": note}
    state.bump()
    return {"scenario": name, "title": title, "events": records, "run_id": run.id}
