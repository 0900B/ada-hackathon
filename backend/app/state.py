"""The in-memory world state: one shared instance, read by the API and the agent.

Everything runs on one asyncio event loop, and no mutation awaits halfway through,
so no locks are needed. Keep Railway at a single replica: the state lives in memory.
"""
from __future__ import annotations

import copy
import itertools
from datetime import datetime
from typing import Any

from .models import (
    AgentRun,
    Alert,
    EventRecord,
    Incident,
    Place,
    SourceKind,
    SourceStatus,
    Trip,
    Vehicle,
    WeatherHour,
    WeatherNow,
    utcnow,
)


class WorldState:
    def __init__(self) -> None:
        # Live feeds survive a simulation reset.
        self.sources: dict[str, SourceStatus] = {}
        self.weather_now: WeatherNow | None = None
        self.weather_forecast: list[WeatherHour] = []
        self.traffic_factor: float = 1.0  # 1.0 = free flow; <1 = slower
        self.traffic_source: str = "time-of-day profile"
        self.traffic_samples: list[dict[str, Any]] = []  # per-road TomTom readings, when live
        self.version = 0
        self._ids = itertools.count(1)
        self.reset_simulation()

    def reset_simulation(self) -> None:
        live = {k: v for k, v in getattr(self, "incidents", {}).items() if v.source == "live"}  # real-world feed
        self.sim_time: datetime = utcnow().replace(microsecond=0)
        self.places: dict[str, Place] = {}
        self.vehicles: dict[str, Vehicle] = {}
        self.trips: dict[str, Trip] = {}
        self.incidents: dict[str, Incident] = live
        self.weather_override: WeatherNow | None = None
        self.alerts: list[Alert] = []
        self.events: list[EventRecord] = []
        self.agent_runs: list[AgentRun] = []
        self.bump()

    # --- helpers -------------------------------------------------------------

    def bump(self) -> None:
        """Mark the state as changed so SSE clients get a fresh snapshot."""
        self.version += 1

    def new_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._ids):04d}"

    def register_source(self, name: str, kind: SourceKind, interval_s: float) -> SourceStatus:
        status = self.sources.get(name)
        if status is None:
            status = SourceStatus(name=name, kind=kind, interval_s=interval_s)
            self.sources[name] = status
        return status

    @property
    def effective_weather(self) -> WeatherNow | None:
        return self.weather_override or self.weather_now

    def clone_for_simulation(self) -> WorldState:
        """A what-if copy: vehicles and trips are deep-copied, everything else is shared read-only."""
        clone = copy.copy(self)
        clone.vehicles = {k: v.model_copy(deep=True) for k, v in self.vehicles.items()}
        clone.trips = {k: t.model_copy(deep=True) for k, t in self.trips.items()}
        clone.places = dict(self.places)
        clone.incidents = dict(self.incidents)
        clone.alerts = []
        clone.events = []
        clone.agent_runs = []
        return clone

    # --- serialisation -------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        from . import config  # local imports: these modules depend on this one's types
        from .engine.projection import kpis

        def dump(items):
            return [i.model_dump(mode="json") for i in items]

        weather = self.effective_weather
        return {
            "version": self.version,
            "sim_time": self.sim_time.isoformat(),
            "real_time": utcnow().isoformat(),
            "places": dump(self.places.values()),
            "vehicles": dump(self.vehicles.values()),
            "trips": dump(self.trips.values()),
            "incidents": dump(i for i in self.incidents.values() if i.active),
            "weather": {
                "now": weather.model_dump(mode="json") if weather else None,
                "overridden": self.weather_override is not None,
                "forecast": dump(self.weather_forecast),
            },
            "traffic": {"factor": self.traffic_factor, "source": self.traffic_source, "samples": self.traffic_samples},
            "sources": {k: s.model_dump(mode="json") for k, s in self.sources.items()},
            "alerts": dump(self.alerts),
            "kpis": kpis(self),
            "events": dump(self.events[-20:]),
            "agent": {
                "enabled": config.agent_enabled(),
                "model": config.AGENT_MODEL,
                "auto": config.AGENT_AUTO,
                "runs": dump(reversed(self.agent_runs[-5:])),  # newest first
            },
        }
