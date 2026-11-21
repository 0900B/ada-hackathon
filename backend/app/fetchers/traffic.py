"""Traffic speed factor.

For now this is a time-of-day profile for Ljubljana (marked "fallback" in /health).
To go live, replace update_traffic with a call to TomTom/HERE traffic flow, and keep
this profile as the fallback when that call fails.
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
