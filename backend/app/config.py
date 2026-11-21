"""Runtime settings, read from environment variables (Railway -> Variables)."""
import os


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


SIM_TICK_S = _float("SIM_TICK_S", 2.0)  # real seconds between simulation ticks
SIM_SPEEDUP = _float("SIM_SPEEDUP", 5.0)  # simulated seconds per real second
WEATHER_INTERVAL_S = _float("WEATHER_INTERVAL_S", 600)
TRAFFIC_INTERVAL_S = _float("TRAFFIC_INTERVAL_S", 30)
RANDOM_SEED = int(os.getenv("RANDOM_SEED", "42"))
# MET Norway asks API clients to identify themselves; add a contact address here if you like.
HTTP_USER_AGENT = os.getenv("HTTP_USER_AGENT", "adahack-transport-backend/0.1")

# Claude agent
AGENT_MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-5-5")
# Sonnet 5.5 defaults to "high"; "medium" is the recommended start for multi-step tool use.
AGENT_EFFORT = os.getenv("AGENT_EFFORT", "medium")  # low | medium | high | xhigh | max
AGENT_AUTO = os.getenv("AGENT_AUTO", "1") == "1"  # analyse disruptive events automatically
AGENT_MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", "10"))
AGENT_TIMEOUT_S = _float("AGENT_TIMEOUT_S", 120)


def agent_enabled() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


# Ljubljana Bezigrad, the point the ARSO hackathon kit uses for Open-Meteo calls.
LJUBLJANA_LAT = 46.0655
LJUBLJANA_LON = 14.5127
