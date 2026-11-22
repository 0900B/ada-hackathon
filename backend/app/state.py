"""In-memory state: one shared feed of real-world data, and two worlds that read it.

- FeedState: real weather, traffic, live incidents and data-source health (fetched once).
- WorldState "live": real time, real conditions only (no hypothetical weather or scenarios).
- WorldState "sim": the presentation sandbox (faster clock, overrides, demo scenarios).

Everything runs on one asyncio event loop, and no mutation awaits halfway through,
so no locks are needed. Keep Railway at a single replica: the state lives in memory.
"""
from __future__ import annotations

import copy
import itertools
from datetime import datetime, timedelta
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


SNAPSHOT_DONE_HOURS = 3  # finished trips stay in the snapshot this long (world time)


def new_ai_stats() -> dict[str, Any]:
    """Decision counters of one world since its reset (snapshot `ai_stats`; cases_active is computed)."""
    return {
        "dispatched": 0,  # units dispatched to a trip (timeline "dispatched")
        "reroutes": 0,  # detours and redirects (timeline "rerouted")
        "reassignments": 0,  # a trip moved to another unit (timeline "reassigned", "unit_replaced")
        "overrides": 0,  # the dispatcher changed a unit by hand (POST /trips/{id}/assign)
        "claude_reviews": 0,  # AI-dispatcher reviews Claude completed
        "claude_changes": 0,  # ... whose change was applied (autonomous mode)
        "last_decision_at": None,  # world time of the last decision on any timeline
    }


class FeedState:
    """Real-world data shared by every world."""

    def __init__(self) -> None:
        self.sources: dict[str, SourceStatus] = {}
        self.weather_now: WeatherNow | None = None
        self.weather_forecast: list[WeatherHour] = []
        self.traffic_factor: float = 1.0  # 1.0 = free flow; <1 = slower
        self.traffic_source: str = "time-of-day profile"
        self.traffic_samples: list[dict[str, Any]] = []  # per-road TomTom readings, when live
        self.incidents: dict[str, Incident] = {}  # live incidents (TomTom, promet.si), by provider

    def register_source(self, name: str, kind: SourceKind, interval_s: float) -> SourceStatus:
        status = self.sources.get(name)
        if status is None:
            status = SourceStatus(name=name, kind=kind, interval_s=interval_s)
            self.sources[name] = status
        return status


def _feed_attr(name: str) -> property:
    """A world attribute that reads and writes the shared feed (so fetchers can use any world)."""
    return property(lambda self: getattr(self.feed, name), lambda self, value: setattr(self.feed, name, value))


class WorldState:
    sources = _feed_attr("sources")
    weather_now = _feed_attr("weather_now")
    weather_forecast = _feed_attr("weather_forecast")
    traffic_factor = _feed_attr("traffic_factor")
    traffic_source = _feed_attr("traffic_source")
    traffic_samples = _feed_attr("traffic_samples")

    def __init__(
        self, name: str = "sim", feed: FeedState | None = None, speedup: float = 1.0, hypothetical: bool = True
    ) -> None:
        self.name = name
        self.feed = feed or FeedState()
        self.speedup = speedup  # simulated seconds per real second
        self.hypothetical = hypothetical  # False for "live": no invented weather or demo scenarios
        self.version = 0
        self.is_simulation = False  # True on what-if copies: they must not queue route fetches
        # Start an AI analysis automatically after events/scenarios/field messages? Off by default
        # (every analysis costs Claude tokens); the operator switches it on, or presses Analyse.
        from . import config  # config only reads environment variables

        self.auto_analyze = config.AGENT_AUTO
        # 112 calls (app/intake.py): triage generated and demo calls with Claude (guarded; else the
        # keyword rules). Off by default; survives a reset like auto_analyze.
        self.ai_triage = False
        # The AI dispatcher (app/ai_dispatcher.py): "assisted" (default: the AI proposes, the dispatcher
        # approves) or "autonomous" (Claude reviews every red call and every disruption of a case and its
        # recommendation is applied; the old autopilot switch is this mode). Survives a reset.
        self.ai_mode: str = "assisted"
        self.epoch = 0  # +1 on every reset: async work started before a reset is dropped
        # Operating mode: live calls (False, default) or a pre-planned scheduled day for the vans.
        # Set on (re)seeding: seed_world(..., scheduled_day=...), POST /{world}/admin/reset.
        self.scheduled_day = config.SCHEDULED_DAY
        from .sim.calls import CallGenerator  # no engine imports in that class

        # live-calls stream (reset by seed_world); the Simulation world starts with it off (config)
        self.calls = CallGenerator(enabled=config.SIM_CALLS_ENABLED if name == "sim" else config.CALLS_ENABLED)
        self._ids = itertools.count(1)
        self.reset_simulation()

    def reset_simulation(self) -> None:
        self.sim_time: datetime = utcnow().replace(microsecond=0)
        self.places: dict[str, Place] = {}
        self.vehicles: dict[str, Vehicle] = {}
        # Reserve units (a neighbouring station's ambulance, a private one): not part of the world (or
        # the snapshot) until a dispatcher's approved plan requests one; back here when it is home.
        self.reserve_vehicles: dict[str, Vehicle] = {}
        self.surge_until: datetime | None = None  # contracted surge capacity active until (engine/surge.py)
        self.demand_was_high = False  # the high-demand alert's last state seen by the loop (an analysis may start when it turns on)
        # High-demand alert with hysteresis (engine/surge.update_demand_alert): raw trigger on since /
        # off since (world time), and whether the alert is raised.
        self.demand_high_since: datetime | None = None
        self.demand_low_since: datetime | None = None
        self.demand_alert = False
        self.call_seq: dict[str, int] = {}  # per-world call id counters ("112", "REQ")
        self.followup_at: datetime | None = None  # next automatic follow-up check (engine/followup.py)
        # AI dispatcher (app/ai_dispatcher.py): the last review per case {trip_id: {run_id, at}}, and the
        # decision counters since the reset (engine/timeline.py counts the timeline's decisions).
        self.reviews: dict[str, dict[str, Any]] = {}
        self.ai_stats: dict[str, Any] = new_ai_stats()
        self.epoch = getattr(self, "epoch", 0) + 1
        self.trips: dict[str, Trip] = {}
        self.incidents: dict[str, Incident] = {}  # this world's operator-reported/injected incidents
        self.weather_override: WeatherNow | None = None
        self.alerts: list[Alert] = []
        self.events: list[EventRecord] = []
        self.agent_runs: list[AgentRun] = []
        self.pending_question: str | None = None  # a scenario's description, for the next Analyse
        self.pending_scenario_events: set[str] = set()  # the scenario's own event ids
        self.analysed_events = 0  # state.events[:analysed_events] have been seen by an analysis
        from .clinical.store import ClinicalLog  # local import: avoids a cycle
        self.clinical = ClinicalLog()
        self.bump()

    # --- helpers -------------------------------------------------------------

    @property
    def autopilot(self) -> bool:
        """The old autopilot switch: the same as the autonomous AI dispatcher mode."""
        return self.ai_mode == "autonomous"

    @autopilot.setter
    def autopilot(self, on: bool) -> None:
        self.ai_mode = "autonomous" if on else "assisted"

    def ai_stats_view(self) -> dict[str, Any]:
        """ai_stats for the snapshot: the counters plus the open 112 cases."""
        cases = sum(
            1 for t in self.trips.values()
            if t.call is not None and t.call.kind == "112" and t.status not in ("completed", "cancelled")
        )
        last = self.ai_stats.get("last_decision_at")
        return {**self.ai_stats, "cases_active": cases, "last_decision_at": last.isoformat() if last else None}

    def bump(self) -> None:
        """Mark the state as changed so SSE clients get a fresh snapshot."""
        self.version += 1

    def new_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._ids):04d}"

    def register_source(self, name: str, kind: SourceKind, interval_s: float) -> SourceStatus:
        return self.feed.register_source(name, kind, interval_s)

    @property
    def effective_weather(self) -> WeatherNow | None:
        return self.weather_override or self.weather_now

    def all_incidents(self) -> list[Incident]:
        """Live incidents from the feeds plus this world's own."""
        return [*self.feed.incidents.values(), *self.incidents.values()]

    def vehicle_path(self, v: Vehicle) -> list[list[float]] | None:
        """Remaining road geometry of the leg v is driving, for the map (None = no road route)."""
        from .roads import remaining_points
        from .routing import leg_route

        if not v.on_road or v.path_from is None or v.path_to is None:
            return None
        route = leg_route(self, v)
        if route is None:
            return None
        pts = remaining_points(route, v.path_progress)
        step = max(1, len(pts) // 60)  # keep the stream light
        thinned = pts[::step] if pts[-1] in pts[::step] else [*pts[::step], pts[-1]]
        return [[round(lat, 5), round(lon, 5)] for lat, lon in thinned]

    def clone_for_simulation(self) -> WorldState:
        """A what-if copy: vehicles and trips are copied, everything else is shared read-only.

        A trip's call record and timeline are shared, not copied (they are only ever written in the
        real world, see engine/timeline.py); its other fields are scalars, except the modifiers list."""
        clone = copy.copy(self)
        clone.vehicles = {k: v.model_copy(deep=True) for k, v in self.vehicles.items()}
        clone.reserve_vehicles = {k: v.model_copy(deep=True) for k, v in self.reserve_vehicles.items()}
        clone.trips = {k: t.model_copy(update={"modifiers": list(t.modifiers)}) for k, t in self.trips.items()}
        clone.places = dict(self.places)
        clone.incidents = dict(self.incidents)
        clone.alerts = []
        clone.events = []
        clone.agent_runs = []
        clone.is_simulation = True
        return clone

    # --- serialisation -------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        from . import config, hems  # local imports: these modules depend on this one's types
        from .engine import surge
        from .engine.projection import kpis
        from .engine.units import trip_view
        from .roads import ROADS
        from .clinical.projection import snapshot_extra

        def dump(items):
            return [i.model_dump(mode="json") for i in items]

        weather = self.effective_weather
        # Live calls accumulate all day: send open trips and those finished in the last few hours,
        # and only the call locations they use (everything stays in memory for the engine).
        horizon = self.sim_time - timedelta(hours=SNAPSHOT_DONE_HOURS)
        trips = [
            t
            for t in self.trips.values()
            if t.status not in ("completed", "cancelled") or (t.eta_dropoff is not None and t.eta_dropoff >= horizon)
        ]
        used = {t.pickup_id for t in trips} | {t.dropoff_id for t in trips}
        places = [p for p in self.places.values() if p.kind not in ("call_location", "incident_site") or p.id in used]
        return {
            "world": self.name,
            "hypothetical": self.hypothetical,
            "speedup": self.speedup,
            "version": self.version,
            "epoch": self.epoch,  # +1 on every reset (a scenario, Reset): clients drop selections of the old world
            "sim_time": self.sim_time.isoformat(),
            "real_time": utcnow().isoformat(),
            "mode": "scheduled_day" if self.scheduled_day else "live_calls",
            "calls": self.calls.status(self),
            "ai_triage": self.ai_triage,  # generated/demo calls triaged by Claude (guarded), else by the rules
            "ai_mode": self.ai_mode,  # assisted | autonomous (app/ai_dispatcher.py)
            "autopilot": self.autopilot,  # = ai_mode autonomous (the old switch)
            "ai_stats": self.ai_stats_view(),
            # Contracted surge capacity: active, until, units, what an activation would add (engine/surge.py)
            "surge": surge.status(self),
            "places": dump(places),
            # helicopters also: off_duty_until, unavailable ("night" | "fog" | None), unavailable_text, hours
            "vehicles": [
                {**v.model_dump(mode="json"), "path": self.vehicle_path(v), **hems.availability(v, self.sim_time)}
                for v in self.vehicles.values()
            ],
            "trips": [trip_view(self, t) for t in trips],  # with `units` (engine/units.py)
            "incidents": dump(i for i in self.all_incidents() if i.active),
            "weather": {
                "now": weather.model_dump(mode="json") if weather else None,
                "overridden": self.weather_override is not None,
                "forecast": dump(self.weather_forecast),
            },
            "traffic": {"factor": self.traffic_factor, "source": self.traffic_source, "samples": self.traffic_samples},
            "roads": ROADS.summary(),
            "sources": {k: s.model_dump(mode="json") for k, s in self.sources.items()},
            "alerts": dump(self.alerts),
            "kpis": kpis(self),
            "events": dump(self.events[-20:]),
            "agent": {
                "enabled": config.agent_enabled(),
                "model": config.AGENT_MODEL,
                "auto": self.auto_analyze,
                "runs": dump(reversed(self.shown_runs())),  # newest first
            },
            **snapshot_extra(self),
        }

    def shown_runs(self) -> list:
        """The last 5 analyses, plus the newest general one (review_of None) when the AI dispatcher's case
        reviews have pushed it out: the dashboard's "Situation review" shows that one, never a review."""
        recent = self.agent_runs[-5:]
        main = next((r for r in reversed(self.agent_runs) if r.review_of is None), None)
        if main is not None and all(r is not main for r in recent):
            recent = [main, *recent]
        return recent
