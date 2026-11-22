"""Service times: every minute a unit spends not driving. Values and sources: docs/SERVICE_TIMES.md.

Used everywhere a time is predicted or simulated: the simulator, the projection (ETAs, delays,
"available soon"), dispatch, navigation (through the vehicle's busy_until) and the doctor cars.
Before these, the model used 5 min to load and 3 min to unload, for every trip.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..hems import HEMS_ACTIVATION_MIN

if TYPE_CHECKING:
    from ..models import Trip, Vehicle

# Activation (turnout): from rest at its base (status idle) until the unit drives off. 0 when it is
# already driving (e.g. returning from a job). Vans: none. The helicopter: the call-to-take-off time
# from its base at Brnik (app/hems.py, 13 min); airborne (flying home after a job) it is re-tasked
# without it. Its landings are in each flight leg (routing.flight_minutes).
TURNOUT_MIN: dict[str, float] = {"ambulance": 1.0, "doctor": 5.0, "helicopter": HEMS_ACTIVATION_MIN}

# On scene: from arrival at the patient until the unit drives off with them (assessment, treatment,
# loading). Ambulance and helicopter crews, by severity; a few conditions differ.
ON_SCENE_MIN: dict[str, float] = {"critical": 20.0, "serious": 15.0, "urgent": 12.0, "routine": 8.0}
ON_SCENE_CONDITION_MIN: dict[str, float] = {
    "cardiac_arrest": 25.0,  # resuscitation on scene
    "stroke": 12.0,  # kept short on purpose: time to the stroke centre
}
VAN_PATIENT_PICKUP_MIN = 8.0  # a transport van collecting a patient (routine or urgent transport)
EQUIPMENT_PICKUP_MIN = 5.0  # loading equipment or cargo

# At the destination.
HANDOVER_MIN = 15.0  # an ambulance (or helicopter) patient handed over at the hospital
VAN_UNLOAD_MIN = 5.0  # a van unloading a transport patient
EQUIPMENT_DROPOFF_MIN = 5.0
# After a patient transport the unit is cleaned and restocked: "returning", but not yet available.
CLEANING_MIN: dict[str, float] = {"ambulance": 10.0, "helicopter": 10.0, "transport": 5.0}


def turnout_min(v: Vehicle) -> float:
    """Minutes before v drives off to a new job: its turnout from rest, 0 if it is already moving."""
    return TURNOUT_MIN.get(v.type, 0.0) if v.status == "idle" else 0.0


def on_scene_for(kind: str, severity: str | None, condition: str | None, vehicle_type: str = "ambulance") -> float:
    """Minutes at the pickup before the unit leaves with the patient (or cargo)."""
    if kind == "equipment":
        return EQUIPMENT_PICKUP_MIN
    if vehicle_type == "transport":
        return VAN_PATIENT_PICKUP_MIN
    if condition in ON_SCENE_CONDITION_MIN:
        return ON_SCENE_CONDITION_MIN[condition]  # type: ignore[index]
    return ON_SCENE_MIN.get(severity or "routine", ON_SCENE_MIN["routine"])


def on_scene_min(trip: Trip, vehicle_type: str = "ambulance") -> float:
    return on_scene_for(trip.kind, trip.severity, trip.condition, vehicle_type)


def handover_min(trip: Trip, vehicle_type: str) -> float:
    """Minutes at the destination: the patient handover (or unloading)."""
    if trip.kind == "equipment":
        return EQUIPMENT_DROPOFF_MIN
    return VAN_UNLOAD_MIN if vehicle_type == "transport" else HANDOVER_MIN


def cleaning_min(trip: Trip, vehicle_type: str) -> float:
    """Minutes of cleaning and restocking after the trip (patients only)."""
    return 0.0 if trip.kind == "equipment" else CLEANING_MIN.get(vehicle_type, 0.0)


def after_dropoff_min(trip: Trip, vehicle_type: str) -> float:
    """Minutes from arrival at the destination until the unit can take its next job."""
    return handover_min(trip, vehicle_type) + cleaning_min(trip, vehicle_type)
