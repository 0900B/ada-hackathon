"""Live weather for Ljubljana, with a provider fallback chain.

1. Open-Meteo (free, no key). Note: api.open-meteo.com is unreachable from Railway's network.
2. MET Norway Locationforecast (free, no key; needs an identifying User-Agent).

The first provider that answers wins; WeatherNow.source records which one it was.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import httpx

from ..config import LJUBLJANA_LAT, LJUBLJANA_LON
from ..models import WeatherHour, WeatherNow, utcnow

if TYPE_CHECKING:
    from ..state import WorldState

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_PARAMS = {
    "latitude": LJUBLJANA_LAT,
    "longitude": LJUBLJANA_LON,
    "current": "temperature_2m,precipitation,snowfall,wind_speed_10m,weather_code",
    "hourly": "temperature_2m,precipitation,snowfall",
    "forecast_days": 2,
    "timezone": "UTC",
}
MET_NO_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
SNOW_RATIO_CM_PER_MM = 0.7  # rough snow depth per mm of water equivalent (same ratio Open-Meteo uses)
PROVIDER_TIMEOUT = httpx.Timeout(8.0, connect=4.0)


def _utc(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _num(v) -> float:
    return float(v) if v is not None else 0.0


def _in_window(t: datetime) -> bool:
    now = utcnow()
    return now - timedelta(hours=1) <= t <= now + timedelta(hours=6)


async def _open_meteo(client: httpx.AsyncClient) -> tuple[WeatherNow, list[WeatherHour]]:
    r = await client.get(OPEN_METEO_URL, params=OPEN_METEO_PARAMS, timeout=PROVIDER_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    cur = data["current"]
    now = WeatherNow(
        observed_at=_utc(cur["time"]),
        temperature_c=_num(cur.get("temperature_2m")),
        precipitation_mm=_num(cur.get("precipitation")),
        snowfall_cm=_num(cur.get("snowfall")),
        wind_speed_kmh=_num(cur.get("wind_speed_10m")),
        weather_code=cur.get("weather_code"),
        source="open-meteo",
    )
    hourly = data["hourly"]
    forecast = [
        WeatherHour(
            time=t,
            temperature_c=_num(hourly["temperature_2m"][i]),
            precipitation_mm=_num(hourly["precipitation"][i]),
            snowfall_cm=_num(hourly["snowfall"][i]),
        )
        for i, ts in enumerate(hourly["time"])
        if _in_window(t := _utc(ts))
    ]
    return now, forecast


def _met_no_snow_cm(symbol: str, temp_c: float, precip_mm: float) -> float:
    """MET's compact format has no snowfall field: infer it from the symbol and temperature."""
    if "snow" in symbol or ("sleet" in symbol and temp_c <= 0.5):
        return round(max(precip_mm, 0.1) * SNOW_RATIO_CM_PER_MM, 2)
    return 0.0


async def _met_no(client: httpx.AsyncClient) -> tuple[WeatherNow, list[WeatherHour]]:
    r = await client.get(
        MET_NO_URL, params={"lat": LJUBLJANA_LAT, "lon": LJUBLJANA_LON}, timeout=PROVIDER_TIMEOUT
    )
    r.raise_for_status()
    series = r.json()["properties"]["timeseries"]

    def parse(entry: dict) -> WeatherHour:
        inst = entry["data"]["instant"]["details"]
        nxt = entry["data"].get("next_1_hours") or {}
        precip = _num((nxt.get("details") or {}).get("precipitation_amount"))
        symbol = (nxt.get("summary") or {}).get("symbol_code", "")
        temp = _num(inst.get("air_temperature"))
        return WeatherHour(
            time=_utc(entry["time"]),
            temperature_c=temp,
            precipitation_mm=precip,
            snowfall_cm=_met_no_snow_cm(symbol, temp, precip),
        )

    first = series[0]
    h0 = parse(first)
    now = WeatherNow(
        observed_at=h0.time,
        temperature_c=h0.temperature_c,
        precipitation_mm=h0.precipitation_mm,
        snowfall_cm=h0.snowfall_cm,
        wind_speed_kmh=round(_num(first["data"]["instant"]["details"].get("wind_speed")) * 3.6, 1),
        source="met.no",
    )
    forecast = [h for e in series[:12] if _in_window((h := parse(e)).time)]
    return now, forecast


PROVIDERS = [("open-meteo", _open_meteo), ("met.no", _met_no)]


async def fetch_weather(state: WorldState, client: httpx.AsyncClient) -> None:
    errors = []
    for name, provider in PROVIDERS:
        try:
            state.weather_now, state.weather_forecast = await provider(client)
            return
        except Exception as e:  # noqa: BLE001 - try the next provider
            errors.append(f"{name}: {type(e).__name__}")
    raise RuntimeError("all weather providers failed (" + "; ".join(errors) + ")")
