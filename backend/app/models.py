"""Data models for the world state, operator events and plans."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, computed_field, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


PlaceKind = Literal["hospital", "health_centre", "residential", "base", "incident_site", "call_location"]
VehicleType = Literal["ambulance", "transport", "helicopter"]
VehicleStatus = Literal["idle", "to_pickup", "loading", "with_patient", "returning", "out_of_service"]
Priority = Literal["emergency", "urgent", "scheduled"]
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
    type: VehicleType  # ambulance/helicopter: any patient incl. stretcher/emergency; transport: seated/wheelchair only
    base_id: str
    lat: float
    lon: float
    status: VehicleStatus = "idle"
    current_trip_id: str | None = None
    queue: list[str] = Field(default_factory=list)  # upcoming trip ids, in order
    busy_until: datetime | None = None  # loading/unloading, or stuck after an injected delay
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
    # Operational details for the vehicle card (synthetic crew; fuel falls with distance driven).
    crew: list[CrewMember] = Field(default_factory=list)
    fuel_pct: float = 100.0
    km_today: float = 0.0
    shift_end: datetime | None = None


class CrewMember(BaseModel):
    name: str  # fictional
    role: str  # e.g. "Driver / paramedic", "Emergency physician", "Pilot"


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

    @model_validator(mode="after")
    def _equipment_consistent(self) -> Trip:
        """kind="equipment" and needs="equipment" always go together (either one implies the other)."""
        if self.kind == "equipment" or self.needs == "equipment":
            self.kind, self.needs = "equipment", "equipment"
        return self

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


class UrgentRequestEvent(BaseModel):
    """A new urgent/emergency transport. Give pickup_id, or lat+lon for an ad-hoc call location."""

    type: Literal["urgent_request"]
    pickup_id: str | None = None
    lat: float | None = None
    lon: float | None = None
    dropoff_id: str = "ukc"
    needs: Needs = "stretcher"
    priority: Literal["emergency", "urgent"] = "emergency"
    note: str | None = None


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
    """Sprememba prioritete: a trip's priority changes (e.g. the patient's condition worsens)."""

    type: Literal["priority_change"]
    trip_id: str
    priority: Priority
    note: str | None = None


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

    def log(self, kind: str, text: str) -> None:
        self.steps.append(AgentStep(at=utcnow(), kind=kind, text=text[:600]))  # type: ignore[arg-type]


class AnalyzeRequest(BaseModel):
    question: str | None = None


class ApproveRequest(BaseModel):
    option_index: int


class RejectRequest(BaseModel):
    reason: str | None = None
