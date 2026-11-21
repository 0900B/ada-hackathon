"""Traffic speed factor.

Without TOMTOM_API_KEY this time-of-day profile for Ljubljana is the traffic source
(marked "fallback" in /health). With a key, fetchers/tomtom.py provides live data and
falls back to this profile whenever TomTom is unavailable.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from ..state import WorldState

LJUBLJANA_TZ = ZoneInfo("Europe/Ljubljana")


def profile_factor(dt: datetime) -> float:
    local = dt.astimezone(LJUBLJANA_TZ)
    h = local.hour + local.minute / 60
    weekday = local.weekday() < 5
    if weekday and (6.5 <= h < 8.5 or 14.5 <= h < 17.5):
        return 0.65  # rush hour
    if h >= 22 or h < 5.5:
        return 1.1  # night
    return 0.85 if weekday else 0.95


async def update_traffic(state: WorldState) -> None:
    state.traffic_factor = profile_factor(state.sim_time)
    state.traffic_source = "time-of-day profile"
    state.traffic_samples = []
