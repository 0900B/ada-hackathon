"""Data models for the world state, operator events and plans."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, computed_field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


PlaceKind = Literal["hospital", "health_centre", "residential", "base", "incident_site", "call_location"]
VehicleType = Literal["ambulance", "transport"]
VehicleStatus = Literal["idle", "to_pickup", "loading", "with_patient", "returning", "out_of_service"]
Priority = Literal["emergency", "urgent", "scheduled"]
Needs = Literal["stretcher", "wheelchair", "seated"]
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


class Vehicle(BaseModel):
    id: str
    name: str
    type: VehicleType  # ambulance: any patient incl. stretcher/emergency; transport: seated/wheelchair only
    base_id: str
    lat: float
    lon: float
    status: VehicleStatus = "idle"
    current_trip_id: str | None = None
    queue: list[str] = Field(default_factory=list)  # upcoming trip ids, in order
    busy_until: datetime | None = None  # loading/unloading, or stuck after an injected delay


class Trip(BaseModel):
    id: str
    patient: str  # pseudonymous label, never real data
    priority: Priority
    needs: Needs
    pickup_id: str
    dropoff_id: str
    pickup_after: datetime  # patient ready from
    due_by: datetime  # must arrive at drop-off by
    note: str | None = None
    status: TripStatus = "unassigned"
    vehicle_id: str | None = None
    eta_pickup: datetime | None = None
    eta_dropoff: datetime | None = None
    delay_min: float | None = None  # predicted (or final) lateness vs due_by


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
    kind: Literal["trip_unassigned", "trip_late", "vehicle_down", "weather_risk", "data_source_down"]
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


OperatorEvent = Annotated[
    Union[
        BreakdownEvent,
        DelayEvent,
        RoadClosureEvent,
        ClearIncidentEvent,
        UrgentRequestEvent,
        WeatherOverrideEvent,
    ],
    Field(discriminator="type"),
]


# --- Plans (what the agent proposes and the operator approves) ----------------


class PlanStep(BaseModel):
    trip_id: str
    vehicle_id: str
    position: int | None = None  # index in the vehicle's queue; None = append at the end
    interrupt_current: bool = False  # put this trip before the vehicle's current (not yet onboard) trip


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


class Recommendation(BaseModel):
    situation: str
    options: list[RecommendationOption]
    recommended_index: int  # -1 when there are no options
    reasoning: str
    notifications: list[NotificationDraft] = Field(default_factory=list)
    escalation: str | None = None
    kpis_before: dict[str, Any] | None = None  # filled in by the engine


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
