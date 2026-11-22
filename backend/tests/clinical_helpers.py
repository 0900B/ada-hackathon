"""Shared helpers for the clinical tests: an offline world, a dispatched ER-bound trip, and payloads.

Import this module FIRST in a clinical test file (`import clinical_helpers  # noqa: F401`): it sets
the offline environment before any app module is imported, and puts backend/ on sys.path.
Tests built on it use their own fresh WorldState (never main.sim / main.live), so they leave no
state behind for other test files.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ["ROAD_ROUTING"] = "0"
os.environ["AGENT_AUTO"] = "0"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("SCHEDULED_DAY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.events import apply_event  # noqa: E402
from app.engine.projection import project_all  # noqa: E402
from app.models import Trip, UrgentRequestEvent  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402
from app.sim.simulator import tick  # noqa: E402
from app.state import WorldState  # noqa: E402

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def fresh_world() -> WorldState:
    """A new live-calls world (no trips yet), independent of main.sim / main.live."""
    w = WorldState("t")
    seed_world(w, 42, scheduled_day=False)
    return w


def er_trip(w: WorldState, note: str = "suspected stroke", priority: str = "emergency", pickup: str = "home_polje") -> Trip:
    """An emergency call to the ER: the nearest free ambulance is dispatched at once, so the trip has a vehicle."""
    record = apply_event(
        w,
        UrgentRequestEvent(type="urgent_request", pickup_id=pickup, priority=priority, needs="stretcher", note=note),  # type: ignore[arg-type]
    )
    return w.trips[record.affected_trip_ids[0]]


def drive(w: WorldState, minutes: float, until=None, step_s: float = 30) -> None:
    """Tick the world (and project, like the app does) for up to `minutes`; stop early when until() is true."""
    for _ in range(int(minutes * 60 / step_s)):
        tick(w, step_s)
        project_all(w)
        if until is not None and until():
            return


def entry(trip: Trip, **overrides) -> dict:
    """A valid API payload for a vitals entry from the trip's vehicle (shallow overrides on top)."""
    payload = {
        "case_id": trip.id,
        "unit": trip.vehicle_id,
        "source": "simulated_crew",
        "type": "vitals",
        "content": {"hr": 80, "spo2": 95},
    }
    payload.update(overrides)
    return payload


def stored_fields(**overrides) -> dict:
    """A minimal valid dict of ClinicalEntry fields without seq and entry_id (what ClinicalLog.append takes)."""
    fields = {
        "case_id": "TR-1",
        "type": "note",
        "content": {"text": "x"},
        "unit": "A1",
        "source": "crew_tap",
        "state": "heard",
        "t": _T0,
        "observed_t": _T0,
        "recorded_at": _T0,
        "verbatim": None,
        "confidence": None,
        "supersedes": None,
        "needs_check": False,
        "client_entry_id": None,
    }
    fields.update(overrides)
    return fields
