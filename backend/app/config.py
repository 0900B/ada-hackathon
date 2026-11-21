"""Runtime settings, read from environment variables (Railway -> Variables)."""
import os


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


SIM_TICK_S = _float("SIM_TICK_S", 2.0)  # real seconds between simulation ticks
SIM_SPEEDUP = _float("SIM_SPEEDUP", 5.0)  # simulated seconds per real second
WEATHER_INTERVAL_S = _float("WEATHER_INTERVAL_S", 600)
TRAFFIC_INTERVAL_S = _float("TRAFFIC_INTERVAL_S", 30)
RANDOM_SEED = int(os.getenv("RANDOM_SEED", "42"))

# Ljubljana Bezigrad, the point the ARSO hackathon kit uses for Open-Meteo calls.
LJUBLJANA_LAT = 46.0655
LJUBLJANA_LON = 14.5127
