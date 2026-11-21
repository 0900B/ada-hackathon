"""Part 3 of the brief: a field message (Slovenian or English) -> structured events -> new plan.

Claude only translates the message into events, picking vehicle/place/trip ids from the
current situation. The engine validates and applies them, and the dispatcher agent replans.
If the message is ambiguous, the parser asks back instead of guessing.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from .. import config
from ..engine.actions import LJ
from ..engine.candidates import nearest_place_name
from ..engine.projection import DONE
from ..models import OperatorEvent

if TYPE_CHECKING:
    from ..state import WorldState


class MessageError(ValueError):
    """The message could not be turned into valid events; safe to show to the operator."""


PARSE_SYSTEM = """\
You turn short messages from ambulance crews and dispatchers in Ljubljana (usually Slovenian, \
sometimes English) into structured events for an emergency medical transport dispatch system.

Rules:
- Use only vehicle, place and trip ids that appear in the context. Never invent ids.
- If the message doesn't name a vehicle, use the sender's vehicle when one is given. Otherwise \
infer it from the context only when exactly one vehicle fits (for example the only vehicle with \
equipment on board when the message says the equipment is still inside) and say so in the \
summaries. If several fit, return no events and ask in needs_clarification.
- "Obstalo", "pokvarilo", "okvara", "ne vžge" mean a breakdown. "Zamuja", "zastoj", "gneča" mean \
a delay (estimate the minutes only if the message gives a number; otherwise use 15 and say so).
- "Zaprta cesta", "zapora", "nesreča na cesti" mean a road closure or accident: use \
near_place_id for the closest known place, or lat/lon if you are confident about the street.
- A new urgent patient ("nujno", "sum na kap", "padec", "nezavesten") is an urgent_request: \
emergency for life-threatening cases, otherwise urgent; stretcher unless the patient can sit.
- Fog ("megla") at the helicopter base or "helikopter ne more vzleteti" is a fog event: it \
grounds the helicopters, 60 minutes unless the message says otherwise.
- A patient getting worse ("stanje se je poslabšalo", "pacient je nestabilen") or better is a \
priority_change of that patient's trip (the sender's current trip if not named): worse means \
emergency if life-threatening, otherwise urgent.
- A hospital that can admit only a few more patients ("UKC ima samo še 2 prosti postelji", \
"urgenca je polna") is a hospital_capacity event for that hospital (full = 0).
- A booking or order for a planned, not life-threatening transport ("naročam prevoz", "prosim za \
prevoz", "potrebujemo prevoz opreme") is a task_request: kind equipment for cargo (put the cargo \
in label), otherwise patient; ready_in_min = minutes from now_local_time (in the context) until \
the time mentioned (0 if "zdaj"); priority urgent \
only if the message says so. Life-threatening cases stay urgent_request.
- Put what was said about cargo (patient, equipment) in the event's note.
- understood_sl and understood_en: one short sentence each, saying what you understood and any \
assumption you made. Be factual.
"""

_NULLABLE_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NULLABLE_NUM = {"anyOf": [{"type": "number"}, {"type": "null"}]}


def _event(type_name: str, props: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"type": {"type": "string", "const": type_name}, **props},
        "required": ["type", *props.keys()],
        "additionalProperties": False,
    }


EVENT_SCHEMAS = [
    _event("breakdown", {"vehicle_id": {"type": "string"}, "note": _NULLABLE_STR}),
    _event("delay", {"vehicle_id": {"type": "string"}, "minutes": {"type": "integer"}, "note": _NULLABLE_STR}),
    _event(
        "road_closure",
        {
            "kind": {"type": "string", "enum": ["road_closure", "accident", "congestion"]},
            "near_place_id": _NULLABLE_STR,
            "lat": _NULLABLE_NUM,
            "lon": _NULLABLE_NUM,
            "description": {"type": "string"},
        },
    ),
    _event(
        "urgent_request",
        {
            "pickup_place_id": _NULLABLE_STR,
            "lat": _NULLABLE_NUM,
            "lon": _NULLABLE_NUM,
            "dropoff_id": _NULLABLE_STR,
            "needs": {"type": "string", "enum": ["stretcher", "wheelchair", "seated"]},
            "priority": {"type": "string", "enum": ["emergency", "urgent"]},
            "note": _NULLABLE_STR,
        },
    ),
    _event("fog", {"duration_min": {"type": "integer"}, "note": _NULLABLE_STR}),
    _event(
        "priority_change",
        {
            "trip_id": {"type": "string"},
            "priority": {"type": "string", "enum": ["emergency", "urgent", "scheduled"]},
            "note": _NULLABLE_STR,
        },
    ),
    _event("hospital_capacity", {"place_id": {"type": "string"}, "capacity": {"type": "integer"}, "note": _NULLABLE_STR}),
    _event(
        "task_request",
        {
            "kind": {"type": "string", "enum": ["patient", "equipment"]},
            "pickup_place_id": {"type": "string"},
            "dropoff_id": {"type": "string"},
            "needs": {"type": "string", "enum": ["stretcher", "wheelchair", "seated", "equipment"]},
            "priority": {"type": "string", "enum": ["scheduled", "urgent"]},
            "ready_in_min": {"type": "integer"},
            "label": _NULLABLE_STR,
            "note": _NULLABLE_STR,
        },
    ),
]

PARSE_SCHEMA = {
    "type": "object",
    "properties": {
        "understood_sl": {"type": "string"},
        "understood_en": {"type": "string"},
        "events": {"type": "array", "items": {"anyOf": EVENT_SCHEMAS}},
        "needs_clarification": _NULLABLE_STR,
    },
    "required": ["understood_sl", "understood_en", "events", "needs_clarification"],
    "additionalProperties": False,
}


class FieldMessage(BaseModel):
    text: str = Field(min_length=2, max_length=1000)
    sender_vehicle_id: str | None = None  # the crew's unit, when the message comes from a vehicle
    apply: bool = True  # False: only show the interpretation


class ParsedMessage(BaseModel):
    understood_sl: str
    understood_en: str
    events: list[dict[str, Any]]
    needs_clarification: str | None = None


def build_context(state: WorldState, sender_vehicle_id: str | None) -> dict[str, Any]:
    trips = state.trips
    vehicles = []
    for v in state.vehicles.values():
        current = trips.get(v.current_trip_id) if v.current_trip_id else None
        on_board = None
        if current and current.status == "onboard":
            kind = getattr(current, "kind", "patient")
            cargo = getattr(current, "cargo", None)
            on_board = f"{kind}{f' ({cargo})' if cargo else ''} for trip {current.id}"
        vehicles.append(
            {
                "id": v.id,
                "name": v.name,
                "type": v.type,
                "status": v.status,
                "near": nearest_place_name(state, v.lat, v.lon),
                "on_board": on_board,
                "current_trip": v.current_trip_id,
            }
        )
    return {
        "now_local_time": state.sim_time.astimezone(LJ).strftime("%H:%M"),  # for "ob 18h" -> minutes from now
        "sender_vehicle_id": sender_vehicle_id,
        "vehicles": vehicles,
        "places": [
            {"id": p.id, "name": p.name, "kind": p.kind, **({"capacity": p.capacity} if getattr(p, "capacity", None) is not None else {})}
            for p in state.places.values()
        ],
        "open_trips": [
            {"id": t.id, "label": t.patient, "priority": t.priority, "vehicle": t.vehicle_id, "status": t.status}
            for t in trips.values()
            if t.status not in DONE
        ],
    }


async def parse_message(state: WorldState, text: str, sender_vehicle_id: str | None = None) -> ParsedMessage:
    from .runner import FALLBACK_BETA, _get_client  # shared Anthropic client

    context = json.dumps(build_context(state, sender_vehicle_id), ensure_ascii=False, separators=(",", ":"))
    response = await _get_client().beta.messages.create(
        model=config.AGENT_MODEL,
        max_tokens=4000,
        system=PARSE_SYSTEM,
        messages=[{"role": "user", "content": f"Context:\n{context}\n\nMessage:\n{text}"}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": PARSE_SCHEMA}},
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise MessageError("The AI declined to interpret this message; please use the event buttons")
    if response.stop_reason == "max_tokens":
        raise MessageError("The AI's answer was cut off; please shorten the message")
    raw = "".join(b.text for b in response.content if b.type == "text").strip()
    try:
        return ParsedMessage.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as e:
        raise MessageError(f"Could not read the AI's interpretation ({type(e).__name__})") from None


_event_adapter = TypeAdapter(OperatorEvent)


def to_operator_events(state: WorldState, parsed: ParsedMessage) -> list[Any]:
    """Map the parser's events onto the engine's event models, resolving place ids to coordinates."""
    out = []
    for raw in parsed.events:
        ev = dict(raw)
        if ev["type"] == "road_closure":
            place = state.places.get(ev.pop("near_place_id") or "")
            if place and (ev.get("lat") is None or ev.get("lon") is None):
                ev["lat"], ev["lon"] = place.lat, place.lon
            if ev.get("lat") is None or ev.get("lon") is None:
                raise MessageError("The message mentions a closure but not where; please name the street or place")
        elif ev["type"] == "urgent_request":
            pickup = ev.pop("pickup_place_id")
            if pickup:
                if pickup not in state.places:
                    raise MessageError(f"Unknown place {pickup}")
                ev["pickup_id"] = pickup
            if not ev.get("dropoff_id"):
                ev.pop("dropoff_id", None)  # model default: UKC
        elif ev["type"] in ("breakdown", "delay") and ev["vehicle_id"] not in state.vehicles:
            raise MessageError(f"Unknown vehicle {ev['vehicle_id']}")
        elif ev["type"] == "task_request":
            ev["pickup_id"] = ev.pop("pickup_place_id")
            for key_ in ("pickup_id", "dropoff_id"):
                if ev[key_] not in state.places:
                    raise MessageError(f"Unknown place {ev[key_]}")
        elif ev["type"] == "priority_change" and ev["trip_id"] not in state.trips:
            raise MessageError(f"Unknown trip {ev['trip_id']}")
        elif ev["type"] == "hospital_capacity" and ev["place_id"] not in state.places:
            raise MessageError(f"Unknown place {ev['place_id']}")
        clean = {k: v for k, v in ev.items() if v is not None}
        try:
            out.append(_event_adapter.validate_python(clean))
        except ValidationError as e:
            raise MessageError(f"The interpreted {ev['type']} event is incomplete: {e.errors()[0]['msg']}") from None
    return out
