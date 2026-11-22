"""Severity levels, per-condition time sensitivity and response targets (docs/DISPATCH_PRIORITIES.md).

A model built from published dispatch practice (SloIn NMP priorities, UK ARP categories, MPDS),
not medical advice. All numbers used by the dispatch rules live here.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ..geo import haversine_km

if TYPE_CHECKING:
    from ..models import Trip
    from ..state import WorldState

CallSeverity = Literal["critical", "serious", "urgent", "routine"]
SEVERITIES: tuple[CallSeverity, ...] = ("critical", "serious", "urgent", "routine")
SEVERITY_RANK: dict[str, int] = {s: i for i, s in enumerate(SEVERITIES)}  # 0 = most severe
# Compatibility with the older three-level priority.
SEVERITY_PRIORITY = {"critical": "emergency", "serious": "emergency", "urgent": "urgent", "routine": "scheduled"}
DEFAULT_SEVERITY = {"emergency": "serious", "urgent": "urgent", "scheduled": "routine"}

# Response targets: minutes from the call until a unit reaches the patient.
RESPONSE_TARGET_MIN: dict[str, float | None] = {"critical": 8.0, "serious": 18.0, "urgent": 60.0, "routine": None}
CRITICAL_TARGET_OUTSIDE_MIN = 15.0  # critical calls outside the city
CITY_RADIUS_KM = 10.0  # "in the city" = within this distance of UKC
# Slovenian reference for red calls (critical and serious): a unit on scene within 15 min. Our own
# critical city target is tighter (8 min); a red call predicted over 15 min raises an alert and the
# engine fallback escalates (ask a neighbouring station). See docs/DISPATCH_PRIORITIES.md.
RED_REFERENCE_MIN = 15.0
HANDOVER_MAX_MIN = 15.0  # Slovenian rule: handover at the hospital within 15 min (service_times.HANDOVER_MIN uses it)

# condition code -> (label, level, time-sensitivity weight, one-sentence clinical reason)
CONDITIONS: dict[str, tuple[str, CallSeverity, float, str]] = {
    "cardiac_arrest": ("Cardiac arrest", "critical", 10, "about 6% survival lost per minute without defibrillation"),
    "choking": ("Choking", "critical", 9, "minutes to hypoxic brain damage"),
    "catastrophic_bleeding": ("Catastrophic bleeding", "critical", 8, "rapid loss of circulating volume"),
    "anaphylaxis": ("Anaphylaxis", "critical", 8, "can progress to arrest within minutes"),
    "stroke": ("Suspected stroke", "serious", 6, "clot-dissolving treatment within 4.5 h at the stroke centre, with a pre-alert"),
    "stemi": ("Suspected heart attack", "serious", 6, "first contact to the catheter lab within 90 min"),
    "breathing_difficulty": ("Severe breathing difficulty", "serious", 5, "may deteriorate quickly"),
    "major_trauma": ("Major trauma", "serious", 5, "golden-hour target to definitive care"),
    "seizure": ("Ongoing seizure", "serious", 4, "time to anticonvulsant matters"),
    "sepsis": ("Suspected sepsis", "serious", 4, "time to antibiotics matters, over hours rather than minutes"),
    "fracture": ("Fracture", "urgent", 2, "pain and immobility, rarely time-critical"),
    "fall": ("Fall injury", "urgent", 2, "pain and immobility, rarely time-critical"),
    "transfer": ("Urgent transfer", "urgent", 1.5, "per the requesting hospital's time window"),
    "equipment": ("Equipment", "urgent", 1, "per the requesting hospital's time window"),
}
DEFAULT_WEIGHT = {"critical": 8.0, "serious": 4.0, "urgent": 1.5, "routine": 0.5}
# Case modifiers raise the weight within the level.
MODIFIERS: dict[str, tuple[str, float]] = {
    "child": ("a child", 1.0),
    "multiple_patients": ("several patients", 1.0),
    "deteriorating": ("getting worse", 1.0),
    "late_stroke_window": ("near the end of the stroke treatment window", 1.5),
    "no_bystander_cpr": ("no bystander CPR or AED", 1.0),
}
MODIFIER_SHORT = {  # for one-line summaries
    "child": "child", "multiple_patients": "several patients", "deteriorating": "getting worse",
    "late_stroke_window": "late stroke window", "no_bystander_cpr": "no bystander CPR",
}
# Older or alternative codes accepted on input.
CONDITION_ALIASES = {"breathing": "breathing_difficulty"}
MODIFIER_ALIASES = {"stroke_window_end": "late_stroke_window"}


def normalise_condition(condition: str | None) -> str | None:
    return CONDITION_ALIASES.get(condition, condition) if condition else None


def normalise_modifiers(modifiers: list[str] | None) -> list[str]:
    out: list[str] = []
    for m in modifiers or []:
        m = MODIFIER_ALIASES.get(m, m)
        if m not in out:
            out.append(m)
    return out


def call_label(trip: Trip) -> str:
    """'Cardiac arrest, child' for summaries: the condition label and the case modifiers."""
    parts = [trip.condition_label] if trip.condition_label else []
    parts += [MODIFIER_SHORT.get(m, m.replace("_", " ")) for m in trip.modifiers]
    return ", ".join(parts)
# Conditions judged by arrival at the hospital (definitive care), not only at the scene.
DEFINITIVE_CARE_CONDITIONS = {"stroke", "stemi"}
# Red calls that also get a doctor car (VUZ: an emergency physician and a nurse, driving separately
# and joining the ambulance crew on scene). Slovenian dispatch sends the nurse-and-rescuer ambulance
# first; a doctor is really needed in only 10 to 30 % of top-priority interventions. A stroke gets
# no doctor car: the time to the stroke centre matters more (ambulance with a pre-alert).
DOCTOR_CONDITIONS = frozenset(
    {"cardiac_arrest", "choking", "catastrophic_bleeding", "anaphylaxis", "stemi", "breathing_difficulty", "major_trauma"}
)
DOCTOR_TARGET_MIN = 15.0  # the doctor on scene within the Slovenian red reference (RED_REFERENCE_MIN)


def needs_doctor(kind: str, severity: str | None, condition: str | None) -> bool:
    return kind == "patient" and severity in ("critical", "serious") and condition in DOCTOR_CONDITIONS

# Dispatch rules (doc section 3).
BUSY_UNIT_MIN_GAIN_MIN = 3.0  # rule 1: a busy unit must beat the best free one by this much
OVERRIDE_MIN_SAVING_MIN = {"critical": 3.0, "serious": 5.0}  # rule 2: time saved to divert from a lower level
NEAR_PATIENT_MIN = 2.0  # rule 5: never divert a unit this close to (or at) its current patient
HELICOPTER_GAIN_MIN = {"critical": 0.0, "serious": 10.0, "urgent": 15.0, "routine": float("inf")}  # rule 6
HELICOPTER_REMOTE_KM = 15.0  # rule 6: urgent calls fly only this far from their destination hospital
SWAP_MIN_GAIN_MIN = 5.0  # rule 4: propose a same-level swap if it saves at least this much
WEIGHT_CLEARLY_HIGHER = 1.5  # rule 4: weights differing by at least this are "not comparable"


def severity_for(priority: str, severity: str | None = None, condition: str | None = None) -> str:
    """The call's level: given, else the condition's, else the default for the priority."""
    if severity in SEVERITY_RANK:
        return severity  # type: ignore[return-value]
    if condition in CONDITIONS:
        return CONDITIONS[condition][1]
    return DEFAULT_SEVERITY.get(priority, "routine")


def condition_label(condition: str | None) -> str | None:
    return CONDITIONS[condition][0] if condition in CONDITIONS else (condition.replace("_", " ").capitalize() if condition else None)


def time_weight(severity: str, condition: str | None, modifiers: list[str] | None = None) -> float:
    base = CONDITIONS[condition][2] if condition in CONDITIONS else DEFAULT_WEIGHT.get(severity, 1.0)
    return round(base + sum(MODIFIERS[m][1] for m in (modifiers or []) if m in MODIFIERS), 1)


def response_target(severity: str, in_city: bool = True) -> float | None:
    if severity == "critical" and not in_city:
        return CRITICAL_TARGET_OUTSIDE_MIN
    return RESPONSE_TARGET_MIN.get(severity)


def clinical_reason(trip: Trip) -> str:
    """One sentence on why this call is time-critical (or not), for summaries and options."""
    if trip.condition in CONDITIONS:
        label, _, _, why = CONDITIONS[trip.condition]
        text = f"{label.lower()}: {why}"
    else:
        text = {"critical": "life-threatening now", "serious": "may become life-threatening soon",
                "urgent": "urgent, not life-threatening", "routine": "planned transport"}.get(trip.severity or "", "")
    mods = [MODIFIERS[m][0] for m in trip.modifiers if m in MODIFIERS]
    return text + (f" ({', '.join(mods)})" if mods else "")


def grade(state: WorldState, trip: Trip) -> Trip:
    """Fill in label, weight and response target from the trip's level, condition and place."""
    trip.severity = severity_for(trip.priority, trip.severity, trip.condition)  # type: ignore[assignment]
    trip.priority = SEVERITY_PRIORITY[trip.severity]  # type: ignore[assignment]
    if trip.condition and not trip.condition_label:
        trip.condition_label = condition_label(trip.condition)
    p, ukc = state.places.get(trip.pickup_id), state.places.get("ukc")
    in_city = not (p and ukc) or haversine_km(p.lat, p.lon, ukc.lat, ukc.lon) <= CITY_RADIUS_KM
    trip.response_target_min = response_target(trip.severity, in_city)
    trip.needs_doctor = needs_doctor(trip.kind, trip.severity, trip.condition)
    trip.doctor_target_min = DOCTOR_TARGET_MIN if trip.needs_doctor else None
    return trip
