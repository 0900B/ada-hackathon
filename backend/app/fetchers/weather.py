"""Live weather for Ljubljana from Open-Meteo (free, no API key)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import httpx

from ..config import LJUBLJANA_LAT, LJUBLJANA_LON
from ..models import WeatherHour, WeatherNow, utcnow

if TYPE_CHECKING:
    from ..state import WorldState

URL = "https://api.open-meteo.com/v1/forecast"
PARAMS = {
    "latitude": LJUBLJANA_LAT,
    "longitude": LJUBLJANA_LON,
    "current": "temperature_2m,precipitation,snowfall,wind_speed_10m,weather_code",
    "hourly": "temperature_2m,precipitation,snowfall",
    "forecast_days": 2,
    "timezone": "UTC",
}


def _utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)


def _num(v) -> float:
    return float(v) if v is not None else 0.0


async def fetch_weather(state: WorldState, client: httpx.AsyncClient) -> None:
    r = await client.get(URL, params=PARAMS)
    r.raise_for_status()
    data = r.json()

    cur = data["current"]
    state.weather_now = WeatherNow(
        observed_at=_utc(cur["time"]),
        temperature_c=_num(cur.get("temperature_2m")),
        precipitation_mm=_num(cur.get("precipitation")),
        snowfall_cm=_num(cur.get("snowfall")),
        wind_speed_kmh=_num(cur.get("wind_speed_10m")),
        weather_code=cur.get("weather_code"),
        source="open-meteo",
    )

    hourly = data["hourly"]
    now = utcnow()
    state.weather_forecast = [
        WeatherHour(
            time=t,
            temperature_c=_num(hourly["temperature_2m"][i]),
            precipitation_mm=_num(hourly["precipitation"][i]),
            snowfall_cm=_num(hourly["snowfall"][i]),
        )
        for i, ts in enumerate(hourly["time"])
        if now - timedelta(hours=1) <= (t := _utc(ts)) <= now + timedelta(hours=6)
    ]
