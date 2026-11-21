"""Runtime settings, read from environment variables (Railway -> Variables)."""
import os


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


SIM_TICK_S = _float("SIM_TICK_S", 2.0)  # real seconds between simulation ticks
SIM_SPEEDUP = _float("SIM_SPEEDUP", 5.0)  # simulation world: simulated seconds per real second
LIVE_SPEEDUP = _float("LIVE_SPEEDUP", 1.0)  # live world runs on the real clock
WEATHER_INTERVAL_S = _float("WEATHER_INTERVAL_S", 600)
TRAFFIC_INTERVAL_S = _float("TRAFFIC_INTERVAL_S", 30)  # time-of-day profile (no TomTom key)
# TomTom (when TOMTOM_API_KEY is set). Free plan, per month: Flow Segment Data 20,000 requests,
# Incident Details 2,500. Defaults: 6 flow points every 5 min (~1,730/day) and incidents every
# 10 min (~145/day), with daily caps; when a cap is hit the time-of-day profile takes over.
TOMTOM_INTERVAL_S = _float("TOMTOM_INTERVAL_S", 300)  # flow
TOMTOM_INCIDENTS_INTERVAL_S = _float("TOMTOM_INCIDENTS_INTERVAL_S", 600)
TOMTOM_DAILY_FLOW_CAP = int(os.getenv("TOMTOM_DAILY_FLOW_CAP", "2000"))
TOMTOM_DAILY_INCIDENT_CAP = int(os.getenv("TOMTOM_DAILY_INCIDENT_CAP", "150"))
# TomTom routing is only the backup router (OSRM is primary); free plan 20,000/month.
TOMTOM_DAILY_ROUTING_CAP = int(os.getenv("TOMTOM_DAILY_ROUTING_CAP", "500"))
# Traffic map tiles (free plan: 200,000/month), served through our cached proxy.
TOMTOM_DAILY_TILE_CAP = int(os.getenv("TOMTOM_DAILY_TILE_CAP", "3000"))
# NAP / promet.si (when NAP_USERNAME + NAP_PASSWORD are set); NAP updates events about every minute.
NAP_INTERVAL_S = _float("NAP_INTERVAL_S", 120)
RANDOM_SEED = int(os.getenv("RANDOM_SEED", "42"))
# Operating mode of both worlds after start/reset (POST /{world}/admin/reset {"scheduled_day": ...}
# switches one world). 0 = live calls (default): no pre-planned day, calls come in and are
# dispatched at once. 1 = scheduled day: the vans start with a pre-planned list of booked trips.
SCHEDULED_DAY = os.getenv("SCHEDULED_DAY", "0") == "1"
# Live-calls mode: the call generator (emergencies, urgent transports, urgent equipment runs).
CALLS_ENABLED = os.getenv("CALLS_ENABLED", "1") == "1"
CALLS_PER_HOUR = _float("CALLS_PER_HOUR", 8.0)  # in world (sim) time: about one call every 7-8 min
# MET Norway asks API clients to identify themselves; add a contact address here if you like.
HTTP_USER_AGENT = os.getenv("HTTP_USER_AGENT", "adahack-transport-backend/0.1")

# Claude agent
AGENT_MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-5-5")
# Sonnet 5.5 defaults to "high"; "medium" is the recommended start for multi-step tool use.
AGENT_EFFORT = os.getenv("AGENT_EFFORT", "medium")  # low | medium | high | xhigh | max
AGENT_AUTO = os.getenv("AGENT_AUTO", "0") == "1"  # default for each world's auto-analyse switch (off: saves tokens)
AGENT_MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", "10"))
AGENT_TIMEOUT_S = _float("AGENT_TIMEOUT_S", 120)


def agent_enabled() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


# Ljubljana Bezigrad, the point the ARSO hackathon kit uses for Open-Meteo calls.
LJUBLJANA_LAT = 46.0655
LJUBLJANA_LON = 14.5127
