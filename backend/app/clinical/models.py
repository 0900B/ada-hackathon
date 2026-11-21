"""Clinical log entries: what a client may send (EntryIn) and what is stored (ClinicalEntry).

Nothing here interprets or corrects clinical values. A vitals reading outside its plausible
range is kept as entered and flagged by needs_check(); a dose or a drug name is just a string.
"""
from typing import Annotated, Any, Literal, Union

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from . import config

Level = Literal["red", "yellow", "scheduled"]
Source = Literal["crew_voice", "crew_tap", "monitor", "dispatcher", "er_reception", "system", "simulated_crew"]
EntryState = Literal["heard", "inferred", "confirmed"]
ProblemType = Literal[
    "chest_pain", "stemi", "stroke", "breathing_difficulty", "severe_head_injury",
    "resuscitation", "polytrauma", "sepsis", "poisoning", "other",
]

ShortStr = Annotated[str, Field(min_length=1, max_length=200)]
LongStr = Annotated[str, Field(min_length=1, max_length=2000)]
Metric = Annotated[float | None, Field(allow_inf_nan=False)]


# --- Content, one model per entry type ---------------------------------------------------------

class _Content(BaseModel):
    # An unknown key would be silently dropped from a clinical record, so refuse it instead.
    model_config = ConfigDict(extra="forbid")


class TriageContent(_Content):
    level: Level
    problem_type: ProblemType = "other"


class PatientInfoContent(_Content):
    age_years: int | None = Field(None, ge=0, le=120)
    sex: Literal["f", "m", "unknown"] | None = None


class VitalsContent(_Content):
    hr: Metric = None
    sbp: Metric = None
    dbp: Metric = None
    spo2: Metric = None
    rr: Metric = None
    gcs: Metric = None
    temp_c: Metric = None
    glucose_mmol: Metric = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "VitalsContent":
        if all(getattr(self, name) is None for name in config.PLAUSIBLE):
            raise ValueError("vitals needs at least one reading")
        return self


class DrugContent(_Content):
    # Free text exactly as given; never parsed or checked against a formulary.
    drug: ShortStr
    dose: ShortStr
    route: ShortStr


class ProcedureContent(_Content):
    name: ShortStr


class SeverityContent(_Content):
    value: Literal["blue", "green", "orange", "red", "arrest"]


class EventContent(_Content):
    kind: Literal["arrest", "resuscitation_started", "rosc", "airway", "stroke_onset", "stemi", "transfusion"]
    onset_t: AwareDatetime | None = None

    @model_validator(mode="after")
    def _stroke_onset_needs_time(self) -> "EventContent":
        if self.kind == "stroke_onset" and self.onset_t is None:
            raise ValueError("onset_t is required for a stroke_onset event")
        return self


class HandoverContent(_Content):
    note: LongStr


class FreeContent(_Content):
    note: LongStr


class NoteContent(_Content):
    text: LongStr


class ERActionContent(_Content):
    action: Literal["acknowledge", "bay_assigned", "team_activated"]
    bay: ShortStr | None = None
    team: str | None = None

    @model_validator(mode="after")
    def _bay_and_team(self) -> "ERActionContent":
        if self.action == "bay_assigned" and self.bay is None:
            raise ValueError("bay is required for bay_assigned")
        if self.action == "team_activated" and self.team is None:
            raise ValueError("team is required for team_activated")
        if self.team is not None and self.team not in config.TEAMS:
            raise ValueError(f"team must be one of {', '.join(config.TEAMS)}")
        return self


# --- Entries a client may send -----------------------------------------------------------------

class EntryBase(BaseModel):
    case_id: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    source: Source
    state: EntryState = "heard"
    observed_t: AwareDatetime | None = None
    verbatim: str | None = Field(None, max_length=500)
    confidence: float | None = Field(None, ge=0, le=1)
    supersedes: str | None = None
    client_entry_id: str | None = Field(None, max_length=64)


class TriageIn(EntryBase):
    type: Literal["triage"]
    content: TriageContent


class PatientInfoIn(EntryBase):
    type: Literal["patient_info"]
    content: PatientInfoContent


class VitalsIn(EntryBase):
    type: Literal["vitals"]
    content: VitalsContent


class DrugIn(EntryBase):
    type: Literal["drug_administered"]
    content: DrugContent


class ProcedureIn(EntryBase):
    type: Literal["procedure"]
    content: ProcedureContent


class SeverityIn(EntryBase):
    type: Literal["severity"]
    content: SeverityContent


class EventIn(EntryBase):
    type: Literal["event"]
    content: EventContent


class HandoverIn(EntryBase):
    type: Literal["handover"]
    content: HandoverContent


class FreeIn(EntryBase):
    type: Literal["free"]
    content: FreeContent


class NoteIn(EntryBase):
    type: Literal["note"]
    content: NoteContent


class ERActionIn(EntryBase):
    type: Literal["er_action"]
    content: ERActionContent


EntryIn = Annotated[
    Union[
        TriageIn, PatientInfoIn, VitalsIn, DrugIn, ProcedureIn, SeverityIn,
        EventIn, HandoverIn, FreeIn, NoteIn, ERActionIn,
    ],
    Field(discriminator="type"),
]
ENTRY_IN: TypeAdapter = TypeAdapter(EntryIn)


# --- Stored entry ------------------------------------------------------------------------------

class ClinicalEntry(BaseModel):
    seq: int
    entry_id: str
    case_id: str
    type: str
    content: dict[str, Any]
    unit: str
    source: Source
    state: EntryState
    t: AwareDatetime  # world time the entry was recorded
    observed_t: AwareDatetime | None
    recorded_at: AwareDatetime  # real time
    verbatim: str | None
    confidence: float | None
    supersedes: str | None
    needs_check: bool
    client_entry_id: str | None


def needs_check(entry_type: str, content: dict) -> bool:
    """True when a vitals reading lies outside its plausible range. Flags only; never alters."""
    if entry_type != "vitals":
        return False
    for name, (low, high) in config.PLAUSIBLE.items():
        value = content.get(name)
        if value is not None and not low <= value <= high:
            return True
    return False
