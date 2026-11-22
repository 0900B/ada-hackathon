"""Clinical log and ER read-model settings: tables, not code.

Thresholds and ranges below are working values for a prototype. Every one marked PLACEHOLDER is
not clinical guidance: ER staff must set it before this is used with real patients.
"""
import os


def enabled() -> bool:
    """Kill switch, read on every call (not at import): on unless CLINICAL_ENABLED is "0"."""
    return os.environ.get("CLINICAL_ENABLED", "1") != "0"


# Places that count as the emergency department; only trips ending here appear on the ER board.
ER_PLACE_IDS = frozenset({"ukc"})

# Legal maximum for handing a patient over after arrival [S per OPERATIONS_DETAILS.md].
HANDOVER_LIMIT_MIN = 15.0
# PLACEHOLDER (not clinical guidance; ER staff must set): minutes an inbound patient may go
# unacknowledged by reception before the board raises an alert.
ARRIVING_UNACKED_MIN = 10.0
# PLACEHOLDER (not clinical guidance; ER staff must set): minutes onboard a red case may go
# without any recorded vitals before the board raises an alert.
NO_VITALS_RED_MIN = 10.0
# PLACEHOLDER (not clinical guidance; ER staff must set): the time window, in minutes from stroke
# onset, for the `stroke_window` alert ONLY (it shows how long is left and closes at this limit).
# Nothing else reads it: whether a stroke team is still worth calling later is a clinical decision
# for the ER, not something this value decides.
STROKE_WINDOW_MIN = 270.0
# How many of the newest clinical entries the shared snapshot carries.
SNAPSHOT_TAIL = 50

# Level shown on a case when no triage entry exists (marked inferred); the national scheme is
# under revision, hence a table. Keys are the existing trip priorities.
LEVEL_BY_PRIORITY = {"emergency": "red", "urgent": "yellow", "scheduled": "scheduled"}

# The Slovenian status chain, in order.
STAGES = (
    "SPREJETO",
    "NA POTI",
    "NA KRAJU",
    "PRI PACIENTU",
    "S KRAJA",
    "NA CILJU",
    "PREDAJA PACIENTA",
    "PROST",
)

# Sources that speak for an ambulance crew; their unit must be the trip's own vehicle.
CREW_SOURCES = frozenset({"crew_voice", "crew_tap", "monitor", "simulated_crew"})

# What reception can record against a case, and the teams it can activate.
ER_ACTIONS = ("acknowledge", "bay_assigned", "team_activated")
TEAMS = ("stroke", "heart", "trauma", "resuscitation_room")

# Which team to suggest for a problem type.
SUGGESTED_TEAM_BY_PROBLEM = {
    "stroke": "stroke",
    "stemi": "heart",
    "chest_pain": "heart",
    "polytrauma": "trauma",
    "severe_head_injury": "trauma",
    "resuscitation": "resuscitation_room",
}

# Physically possible ranges (inclusive), per vital sign. A value outside is kept as entered and
# flagged "check this" (needs_check); it is never corrected or dropped.
PLAUSIBLE: dict[str, tuple[float, float]] = {
    "hr": (0, 300),
    "sbp": (0, 300),
    "dbp": (0, 200),
    "spo2": (0, 100),
    "rr": (0, 80),
    "gcs": (3, 15),
    "temp_c": (25, 45),
    "glucose_mmol": (0, 60),
}

# PLACEHOLDER, not clinical guidance; ER staff must set. (low, high) alert limits per vital sign,
# None meaning no limit on that side.
VITAL_LIMITS: dict[str, tuple[float | None, float | None]] = {
    "spo2": (90, None),
    "sbp": (90, 180),
    "hr": (40, 130),
    "rr": (8, 30),
    "gcs": (9, None),
}
