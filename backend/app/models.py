"""Data models for the world state, operator events and plans."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, computed_field, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


PlaceKind = Literal["hospital", "health_centre", "residential", "base", "incident_site", "call_location"]
VehicleType = Literal["ambulance", "transport", "helicopter", "doctor"]
# own fleet, a neighbouring station's ambulance (mutual aid) or a private ambulance; the last two exist
# in the world only after the dispatcher has requested them (approved plan).
VehicleOrigin = Literal["own", "mutual_aid", "private"]
VehicleStatus = Literal["idle", "to_pickup", "loading", "with_patient", "returning", "out_of_service"]
Priority = Literal["emergency", "urgent", "scheduled"]
CallSeverity = Literal["critical", "serious", "urgent", "routine"]  # see engine/severity.py
Needs = Literal["stretcher", "wheelchair", "seated", "equipment"]  # "equipment": no patient, cargo only
TripKind = Literal["patient", "equipment"]
TripStatus = Literal["unassigned", "assigned", "en_route_pickup", "onboard", "completed", "cancelled"]
SourceKind = Literal["live", "simulated", "fallback"]
SourceHealth = Literal["starting", "fresh", "stale", "down"]
IncidentKind = Literal["road_closure", "accident", "congestion"]
Severity = Literal["critical", "high", "medium", "low"]


# --- World entities ---------------------------------------------------------


class Place(BaseModel):
    id: str
    name: str
    kind: PlaceKind
    lat: float
    lon: float
    # Hospitals only: admissions it can still take (None = unlimited); each delivered patient uses one.
    capacity: int | None = None
    specialty: str | None = None  # e.g. "oncology"; None = general hospital (a valid redirect target)


class Vehicle(BaseModel):
    id: str
    name: str
    # ambulance: emergency unit (emergencies, urgent calls; at most current job + 1 queued);
    # transport: the scheduled day (any non-emergency patient incl. stretcher, equipment);
    # helicopter: emergencies and urgent trips only (no equipment, no scheduled work);
    # doctor: a doctor car (VUZ, physician + nurse) that joins the ambulance crew on scene and never
    # transports a patient. Its current_trip_id is the call it supports (to_pickup = driving to the
    # scene, loading = on scene with the crew, with_patient = escorting the ambulance to hospital).
    type: VehicleType
    origin: VehicleOrigin = "own"
    # Contracted surge capacity (engine/surge.py): in the fleet until this time; then it finishes its
    # current job, returns and leaves (contract_ended: takes no new jobs meanwhile).
    contract_until: datetime | None = None
    contract_ended: bool = False
    base_id: str
    lat: float
    lon: float
    status: VehicleStatus = "idle"
    current_trip_id: str | None = None
    queue: list[str] = Field(default_factory=list)  # upcoming trip ids, in order
    busy_until: datetime | None = None  # loading/unloading, or stuck after an injected delay
    # Why busy_until is set (the UI shows a normal turnout neutrally, a delay as held): turnout (crew to
    # the vehicle, or the helicopter's activation), on_scene, handover (handover and cleaning), delay.
    # None when unknown (older states) or not busy.
    busy_reason: Literal["turnout", "on_scene", "handover", "delay"] | None = None
    # Set by the simulator while the vehicle stands at its next pickup before the patient (or cargo)
    # is ready: it waits there until this time. None when it is not waiting.
    waiting_until: datetime | None = None
    # Helicopters (HNMP) fly straight, off the road network. Fog grounds them until this time:
    # no new flights; a patient already on board is flown in, then the helicopter goes home.
    grounded_until: datetime | None = None
    # The leg being driven (set by the simulator): where it started, its target, progress 0..1.
    path_from: tuple[float, float] | None = Field(default=None, exclude=True)
    path_to: tuple[float, float] | None = Field(default=None, exclude=True)
    path_progress: float = 0.0
    on_road: bool = False  # True while following real road geometry (False = straight-line fallback)
    # Road closures this leg is routed around: ((lat, lon, radius_m), ...); None = the normal route.
    path_avoid: tuple[tuple[float, float, int], ...] | None = Field(default=None, exclude=True)
    # When the road route arrives mid-leg: how far (lat, lon) the vehicle still is from the road;
    # it shrinks every tick, so the vehicle merges onto the road instead of jumping onto it.
    snap_offset: tuple[float, float] | None = Field(default=None, exclude=True)
    # Operational details for the vehicle card (synthetic crew; fuel falls with distance driven).
    crew: list[CrewMember] = Field(default_factory=list)
    fuel_pct: float = 100.0
    km_today: float = 0.0
    shift_end: datetime | None = None
    # Set by the simulator on arrival at the drop-off: the handover of this trip ends at this time
    # (then cleaning). Only for the call timeline ("handover_done", "closed").
    handover_trip_id: str | None = Field(default=None, exclude=True)
    handover_until: datetime | None = Field(default=None, exclude=True)


class CrewMember(BaseModel):
    name: str  # fictional
    role: str  # e.g. "Medical rescuer (driver)", "Emergency physician", "Pilot"


# --- The call record and the call timeline (app/intake.py, engine/timeline.py) ---------------

CallKind = Literal["112", "hospital_request"]
TriageBy = Literal["ai", "rules", "dispatcher"]
TimelineKind = Literal[
    "received", "triaged", "dispatched", "doctor_dispatched", "rerouted", "reassigned", "delayed",
    "unit_replaced", "proposal", "approved", "on_scene", "doctor_on_scene", "transporting", "at_hospital",
    "handover_done", "closed", "note",
    "reviewed",  # the AI dispatcher (Claude) reviewed the case and kept the decision (app/ai_dispatcher.py)
    "override",  # the dispatcher changed a unit by hand (app/overrides.py)
    "disruption",  # a breakdown, delay, closure, fog, ... hit this call: the re-plan entries follow it
]
TimelineBy = Literal["caller", "ai", "rules", "engine", "dispatcher", "crew"]
AiMode = Literal["assisted", "autonomous"]  # per world (app/ai_dispatcher.py)
UnitRole = Literal["ambulance", "doctor", "helicopter", "van"]
AssignedBy = Literal["engine", "ai", "dispatcher"]


class CallTriage(BaseModel):
    """How the call was graded: by Claude (ai), by the keyword rules (rules), or by the dispatcher."""

    by: TriageBy
    at: datetime
    severity: CallSeverity
    condition: str | None = None
    condition_label: str | None = None
    modifiers: list[str] = Field(default_factory=list)
    needs_doctor: bool = False
    reason_en: str = ""  # one clinical sentence
    reason_sl: str = ""
    took_s: float | None = None  # how long the triage took (real seconds), for the timeline's detail


class CallRecord(BaseModel):
    """The request behind a trip: a 112 call (caller's words, address) or a hospital's request."""

    call_id: str  # "112-0042" (per-world counter); hospital requests "REQ-0007"
    kind: CallKind = "112"
    received_at: datetime
    caller_name: str | None = None  # fictional
    address: str | None = None  # e.g. "Zaloška cesta 45, Moste"
    text_sl: str = ""  # the caller's words
    text_en: str = ""
    triage: CallTriage | None = None


class TimelineEntry(BaseModel):
    at: datetime
    kind: TimelineKind
    by: TimelineBy
    text: str
    vehicle_id: str | None = None
    run_id: str | None = None
    # Who exactly, in a few words: "rules engine, 0.1 s", "Claude, 12 s, checked by the engine",
    # "dispatcher override", "keyword rules" (engine/timeline.py fills a default from `by`).
    detail: str | None = None
    # Re-plans (the case card's re-plan box): the event behind the entry, the unit it replaced, and the
    # trip's next arrival before and after (at the patient / pickup, or at the hospital once on board).
    event_id: str | None = None
    unit_before: str | None = None
    eta_before: datetime | None = None
    eta_after: datetime | None = None
    eta_of: Literal["patient", "pickup", "hospital"] | None = None


class Trip(BaseModel):
    id: str
    kind: TripKind = "patient"  # "equipment" = prevoz opreme: carries cargo, no patient
    patient: str | None = None  # pseudonymous label, never real data; None for equipment
    cargo: str | None = None  # equipment only, e.g. "ventilator", "blood products"
    priority: Priority
    needs: Needs
    pickup_id: str
    dropoff_id: str
    pickup_after: datetime  # patient (or equipment) ready from
    due_by: datetime  # must arrive at drop-off by
    note: str | None = None
    status: TripStatus = "unassigned"
    vehicle_id: str | None = None
    eta_pickup: datetime | None = None
    eta_dropoff: datetime | None = None
    delay_min: float | None = None  # predicted (or final) lateness vs due_by
    dispatched_at: datetime | None = None  # set when the engine dispatched this call itself (sim time)
    # Severity level (docs/DISPATCH_PRIORITIES.md): critical | serious | urgent | routine. Critical and
    # serious are priority "emergency", urgent is "urgent", routine is "scheduled". None = from priority.
    severity: CallSeverity | None = None
    condition: str | None = None  # e.g. "cardiac_arrest", "stroke", "fracture", "transfer" (engine.severity.CONDITIONS)
    condition_label: str | None = None  # short English label, e.g. "Cardiac arrest"
    modifiers: list[str] = Field(default_factory=list)  # child, multiple_patients, deteriorating, ...
    response_target_min: float | None = None  # minutes from the call to reach the patient (None = by appointment)
    times_displaced: int = 0  # how often a unit was diverted away from this call (at most once)
    # Doctor on scene (engine.severity.DOCTOR_CONDITIONS): a doctor car, or the helicopter (doctor on board).
    needs_doctor: bool = False
    doctor_vehicle_id: str | None = None  # the doctor car supporting this call, or "H1" when the helicopter serves it
    doctor_eta: datetime | None = None  # when the doctor reaches (or reached) the patient
    doctor_target_min: float | None = None  # minutes from the call: the 15-min red reference
    # The 112 call or hospital request behind this trip (None: a plain booking or a scenario job), and
    # everything that happened to it, oldest first (bounded, see engine/timeline.py). Shared, not copied,
    # by what-if copies of the world (WorldState.clone_for_simulation); written only in the real world.
    call: CallRecord | None = None
    timeline: list[TimelineEntry] = Field(default_factory=list)
    # A further unit the dispatcher added to the same call (several patients): the trip it belongs to.
    linked_to: str | None = None
    # Why each unit serves this trip, written where the decision is made (engine/units.py):
    # {vehicle_id: {"reason", "assigned_by", "assigned_at"}}. Shown as `units` in the snapshot; shared
    # (not copied) by what-if copies and written only in the real world, like the timeline.
    unit_notes: dict[str, dict[str, Any]] = Field(default_factory=dict, exclude=True)

    @model_validator(mode="after")
    def _equipment_consistent(self) -> Trip:
        """kind="equipment" and needs="equipment" always go together (either one implies the other).
        severity and priority agree: a given severity sets the priority, else it follows from it."""
        if self.kind == "equipment" or self.needs == "equipment":
            self.kind, self.needs = "equipment", "equipment"
        from .engine import severity as sev  # no cycle: that module needs only geo

        self.condition = sev.normalise_condition(self.condition)
        self.modifiers = sev.normalise_modifiers(self.modifiers)
        self.severity = sev.severity_for(self.priority, self.severity, self.condition)  # type: ignore[assignment]
        self.priority = sev.SEVERITY_PRIORITY[self.severity]  # type: ignore[assignment,index]
        if self.condition and not self.condition_label:
            self.condition_label = sev.condition_label(self.condition)
        if self.response_target_min is None:
            self.response_target_min = sev.response_target(self.severity)  # type: ignore[arg-type]
        if sev.needs_doctor(self.kind, self.severity, self.condition):
            self.needs_doctor = True
        if self.needs_doctor and self.doctor_target_min is None:
            self.doctor_target_min = sev.DOCTOR_TARGET_MIN
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def time_weight(self) -> float:
        """Relative time sensitivity within the level (condition weight plus case modifiers)."""
        from .engine import severity as sev

        return sev.time_weight(self.severity or "routine", self.condition, self.modifiers)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def label(self) -> str:
        """How to refer to what is carried: the patient label, or the cargo for equipment."""
        if self.kind == "equipment":
            return f"equipment: {self.cargo or 'unspecified'}"
        return self.patient or self.id


class Incident(BaseModel):
    id: str
    kind: IncidentKind
    description: str
    lat: float
    lon: float
    radius_m: float
    created_at: datetime
    source: Literal["live", "injected"] = "injected"
    provider: str | None = None  # "tomtom", "promet.si" for live incidents; each feed replaces only its own
    active: bool = True
    # The affected road stretch, (lat, lon) along the road, for the map: a stretch of a unit's route,
    # a road snapped to near the point, or the feed's own geometry. None = not known (only the point).
    # The engine still treats the incident as the circle (lat, lon, radius_m).
    path: list[tuple[float, float]] | None = None
    until: datetime | None = None  # clears by itself at this world time (a demo traffic jam); None = until cleared


class WeatherNow(BaseModel):
    observed_at: datetime
    temperature_c: float
    precipitation_mm: float
    snowfall_cm: float
    wind_speed_kmh: float
    weather_code: int | None = None
    source: str


class WeatherHour(BaseModel):
    time: datetime
    temperature_c: float
    precipitation_mm: float
    snowfall_cm: float


class SourceStatus(BaseModel):
    """Freshness bookkeeping for one data feed. Ages are measured in real time."""

    name: str
    kind: SourceKind
    interval_s: float
    last_attempt: datetime | None = None
    last_success: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def age_s(self) -> float | None:
        if self.last_success is None:
            return None
        return round((utcnow() - self.last_success).total_seconds(), 1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def health(self) -> SourceHealth:
        age = self.age_s
        if age is None:
            return "down" if self.last_error else "starting"
        if age <= max(2 * self.interval_s, 10):
            return "fresh"
        if age <= max(6 * self.interval_s, 30):
            return "stale"
        return "down"


class Alert(BaseModel):
    id: str  # stable, e.g. "trip_late:TR-004", so clients can diff
    kind: Literal[
        "trip_unassigned",
        "trip_late",
        "vehicle_down",
        "weather_risk",
        "data_source_down",
        "hospital_over_capacity",
        "low_fuel",
        "red_response_over_15_min",  # a critical/serious call predicted to be reached after 15 min (Slovenian reference)
        "doctor_response_over_15_min",  # a call that needs a doctor: none on scene within its doctor_target_min
        "high_demand",  # the demand trigger (engine/surge.py): offer contracted surge capacity
    ]
    severity: Severity
    message: str
    trip_id: str | None = None
    vehicle_id: str | None = None


class EventRecord(BaseModel):
    id: str
    sim_time: datetime
    type: str
    payload: dict[str, Any]
    summary: str
    affected_trip_ids: list[str]
    kpis_before: dict[str, Any]
    kpis_after: dict[str, Any]
    generated: bool = False  # True for a call from the live-calls generator (not an operator report)


# --- Operator events (injected via POST /events) ------------------------------


class BreakdownEvent(BaseModel):
    type: Literal["breakdown"]
    vehicle_id: str
    note: str | None = None


class DelayEvent(BaseModel):
    type: Literal["delay"]
    vehicle_id: str
    minutes: float = Field(gt=0, le=240)
    note: str | None = None


class RoadClosureEvent(BaseModel):
    type: Literal["road_closure"]
    lat: float
    lon: float
    radius_m: float = Field(default=400, gt=0, le=5000)
    kind: IncidentKind = "road_closure"
    description: str = "Road closed"
    # Optional: the affected road stretch (lat, lon) for the map; derived from the roads when not given
    path: list[tuple[float, float]] | None = Field(default=None, max_length=400)
    duration_min: float | None = Field(default=None, gt=0, le=24 * 60)  # clears by itself after this long


class ClearIncidentEvent(BaseModel):
    type: Literal["clear_incident"]
    incident_id: str


class TaskRequestEvent(BaseModel):
    """A booked transport order (Part 1 of the brief: the plan is built from incoming orders).

    A hospital or the dispatcher books a patient or equipment transfer; the engine places it into the
    live plan (best vehicle and position by simulation). If no vehicle can take it without making a
    trip late, it stays unassigned and the AI is asked to replan. Emergencies use urgent_request.
    """

    type: Literal["task_request"]
    kind: TripKind = "patient"
    pickup_id: str
    dropoff_id: str
    needs: Needs = "seated"
    priority: Literal["scheduled", "urgent"] = "scheduled"
    ready_in_min: float = Field(default=15, ge=0, le=1440)  # patient/cargo ready this many minutes from now
    due_in_min: float | None = Field(default=None, gt=0, le=2880)  # deadline from now; None = sensible default
    label: str | None = None  # patient label (pseudonymous) or cargo description for equipment
    note: str | None = None
    auto_assign: bool = True
    # If no vehicle can take it on time: "leave" it unassigned for the AI/dispatcher, or put it on
    # the vehicle that can collect it "soonest" (late; used for live calls, which must be served).
    if_late: Literal["leave", "soonest"] = "leave"
    severity: Literal["urgent", "routine"] | None = None  # optional; sets the priority (urgent / scheduled)
    condition: str | None = None  # e.g. "transfer", "equipment"
    modifiers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _severity_sets_priority(self) -> TaskRequestEvent:
        if self.severity:
            self.priority = "urgent" if self.severity == "urgent" else "scheduled"
        return self


class UrgentRequestEvent(BaseModel):
    """A new urgent/emergency call. Give pickup_id, or lat+lon for an ad-hoc call location.

    The engine dispatches it at once: the free emergency unit that reaches the patient first
    (the helicopter only when it is clearly faster), see engine.events.dispatch_call.
    """

    type: Literal["urgent_request"]
    pickup_id: str | None = None
    lat: float | None = None
    lon: float | None = None
    place_name: str | None = Field(default=None, max_length=80)  # name for an ad-hoc call location
    dropoff_id: str = "ukc"
    needs: Needs = "stretcher"
    priority: Literal["emergency", "urgent"] = "emergency"
    note: str | None = None
    # Optional grading (docs/DISPATCH_PRIORITIES.md). severity sets the priority (critical/serious =
    # emergency, urgent = urgent); without it the condition's level, else serious/urgent by priority.
    severity: Literal["critical", "serious", "urgent"] | None = None
    condition: str | None = None  # e.g. "cardiac_arrest", "stroke", "stemi", "fracture"
    modifiers: list[str] = Field(default_factory=list)  # child, multiple_patients, deteriorating, ...
    # The call-taker (or the AI triage) asks for a doctor on scene even if the condition alone would not
    # (critical/serious calls only); the conditions in engine.severity.DOCTOR_CONDITIONS always get one.
    needs_doctor: bool = False

    @model_validator(mode="after")
    def _severity_sets_priority(self) -> UrgentRequestEvent:
        from .engine import severity as sev

        self.condition = sev.normalise_condition(self.condition)
        self.modifiers = sev.normalise_modifiers(self.modifiers)
        level = sev.severity_for(self.priority, self.severity, self.condition)
        if level in ("critical", "serious", "urgent"):
            self.severity = level  # type: ignore[assignment]
            self.priority = "urgent" if level == "urgent" else "emergency"
        return self


class WeatherOverrideEvent(BaseModel):
    """Force demo weather (e.g. a snowstorm). Send clear=true to go back to live weather."""

    type: Literal["weather_override"]
    clear: bool = False
    snowfall_cm: float = 2.0
    precipitation_mm: float = 2.0
    temperature_c: float = -1.0
    wind_speed_kmh: float = 20.0


class FogEvent(BaseModel):
    """Fog (megla) at the helicopter base: every helicopter is grounded for duration_min.

    An operational report, so it is allowed in both worlds. Trips not yet picked up are released.
    """

    type: Literal["fog"]
    duration_min: float = Field(default=60, gt=0, le=480)
    note: str | None = None


class PriorityChangeEvent(BaseModel):
    """Sprememba prioritete: a trip's priority or severity level changes (e.g. the patient gets worse).

    Give priority, or severity (which sets the priority; e.g. serious -> critical keeps "emergency"),
    optionally a new condition."""

    type: Literal["priority_change"]
    trip_id: str
    priority: Priority | None = None
    severity: CallSeverity | None = None
    condition: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _one_given(self) -> PriorityChangeEvent:
        from .engine import severity as sev

        self.condition = sev.normalise_condition(self.condition)
        if self.severity:
            self.priority = sev.SEVERITY_PRIORITY[self.severity]  # type: ignore[assignment]
        elif self.priority is None:
            raise ValueError("give priority or severity")
        return self


class HospitalCapacityEvent(BaseModel):
    """Zmanjšana kapaciteta: how many more patients a hospital can admit. capacity=null restores unlimited."""

    type: Literal["hospital_capacity"]
    place_id: str
    capacity: int | None = Field(default=None, ge=0, le=1000)
    note: str | None = None


OperatorEvent = Annotated[
    Union[
        BreakdownEvent,
        DelayEvent,
        RoadClosureEvent,
        ClearIncidentEvent,
        UrgentRequestEvent,
        TaskRequestEvent,
        WeatherOverrideEvent,
        FogEvent,
        PriorityChangeEvent,
        HospitalCapacityEvent,
    ],
    Field(discriminator="type"),
]


# --- Plans (what the agent proposes and the operator approves) ----------------


class PlanStep(BaseModel):
    trip_id: str
    vehicle_id: str
    position: int | None = None  # index in the vehicle's queue; None = append at the end
    interrupt_current: bool = False  # put this trip before the vehicle's current (not yet onboard) trip
    # Redirect the patient to another hospital (a general one with free capacity). On the trip's own
    # vehicle with position=None the trip keeps its place in the queue (works with the patient on board).
    dropoff_id: str | None = None
    # Set by the engine when it checks an option: the trip this one must come right before in the
    # vehicle's route (None = at the end). When set, it replaces position/interrupt_current, so an
    # approved plan keeps the order it was checked with even if the vehicle moved on meanwhile.
    before_trip_id: str | None = None


class Plan(BaseModel):
    steps: list[PlanStep] = Field(min_length=1)
    rationale: str | None = None


# --- Agent runs and recommendations -------------------------------------------


class AgentStep(BaseModel):
    at: datetime
    kind: Literal["info", "reasoning", "tool_call", "tool_result", "error"]
    text: str


class NotificationDraft(BaseModel):
    recipient: str
    message_sl: str
    message_en: str


class RecommendationOption(BaseModel):
    title: str
    summary: str
    steps: list[PlanStep]
    pros: list[str]
    cons: list[str]
    # Approving this option activates the contracted surge capacity (engine/surge.py) before its steps.
    activate_surge: bool = False
    # Filled in by the engine after the run, never by the model:
    feasible: bool | None = None
    errors: list[str] = Field(default_factory=list)
    kpis_after: dict[str, Any] | None = None
    trip_changes: list[dict[str, Any]] = Field(default_factory=list)
    # What each step really does, in step order (who, which stop of the vehicle's route, after which
    # trips, predicted pickup/drop-off and a one-line `text`). Approval is checked against these.
    step_details: list[dict[str, Any]] = Field(default_factory=list)


class Recommendation(BaseModel):
    situation: str
    options: list[RecommendationOption]
    recommended_index: int  # -1 when there are no options
    reasoning: str
    notifications: list[NotificationDraft] = Field(default_factory=list)
    escalation: str | None = None
    kpis_before: dict[str, Any] | None = None  # filled in by the engine
    checked_at: datetime | None = None  # world (sim) time the engine checked the options


class AgentRun(BaseModel):
    id: str
    trigger: str  # "event:EV-0003" or "operator"
    event_id: str | None = None
    question: str | None = None
    status: Literal["running", "done", "error", "superseded", "approved", "rejected"] = "running"
    engine: Literal["claude", "engine_fallback"] | None = None  # who produced the recommendation
    model: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    steps: list[AgentStep] = Field(default_factory=list)
    recommendation: Recommendation | None = None
    error: str | None = None
    decision: dict[str, Any] | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    # Set for an AI-dispatcher review of one case (app/ai_dispatcher.py): the trip reviewed.
    review_of: str | None = None

    def log(self, kind: str, text: str) -> None:
        self.steps.append(AgentStep(at=utcnow(), kind=kind, text=text[:600]))  # type: ignore[arg-type]


class AnalyzeRequest(BaseModel):
    question: str | None = None


class ApproveRequest(BaseModel):
    option_index: int


class RejectRequest(BaseModel):
    reason: str | None = None
