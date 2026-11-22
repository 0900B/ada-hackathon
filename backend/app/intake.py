"""112 calls in: the caller's words and address -> triage -> the normal dispatch path.

- POST /{world}/calls (a call-taker types the call): triage by Claude whenever it is available (through
  the usage guard), else by the keyword rules; the call is never lost.
- POST /sim/admin/random-call (demo button): one call from the library in sim/calls.py; Claude triages
  it only when the world's ai_triage switch is on, the guard allows it and the button was not pressed
  within RANDOM_CALL_AI_GAP_S (repeated clicks get the rules).
- Generated calls (sim/calls.step): the rules by default; with ai_triage on, Claude triages them first
  (defer_generated) while the guard keeps AI_TRIAGE_RESERVE requests free for analyses.

Every call becomes an urgent_request applied by engine/events.apply_event with its CallRecord, so the
dispatch rules, the doctor car and the timeline are exactly those of any other call.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
import zlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from pydantic import BaseModel, Field

from . import config
from .agent.triage import TriageResult, triage
from .audit import AUDIT
from .engine.candidates import nearest_place_name
from .engine.events import apply_event
from .engine.severity import CONDITIONS
from .guard import GUARD
from .models import CallRecord, EventRecord, UrgentRequestEvent
from .sim import calls as gen

if TYPE_CHECKING:
    from .state import WorldState

log = logging.getLogger(__name__)

RANDOM_CALL_AI_GAP_S = 20.0  # real seconds: a random call within this of the last AI-triaged one gets the rules
AI_TRIAGE_RESERVE = 4  # generated calls use Claude only while more than this many guarded requests are left
ADDRESS_JITTER = (0.003, 0.0045)  # a street address within about 300 m of its area's centre (lat, lon degrees)

# Well-known central Ljubljana streets (approximate coordinates), besides the areas' streets in sim/calls.py.
CENTRAL_STREETS: dict[str, tuple[float, float]] = {
    "Prešernov trg": (46.0514, 14.5060), "Kongresni trg": (46.0503, 14.5037), "Slovenska cesta": (46.0530, 14.5030),
    "Čopova ulica": (46.0520, 14.5045), "Trubarjeva cesta": (46.0525, 14.5090), "Miklošičeva cesta": (46.0545, 14.5080),
    "Šmartinska cesta": (46.0640, 14.5300), "Litijska cesta": (46.0450, 14.5350), "Gerbičeva ulica": (46.0410, 14.4960),
    "Njegoševa cesta": (46.0560, 14.5200), "Poljanska cesta": (46.0490, 14.5170), "Karlovška cesta": (46.0440, 14.5110),
    "Rimska cesta": (46.0480, 14.4990), "Aškerčeva cesta": (46.0460, 14.4970), "Bohoričeva ulica": (46.0570, 14.5160),
    "Vošnjakova ulica": (46.0590, 14.5000), "Zaloška cesta": (46.0560, 14.5420), "Dunajska cesta": (46.0720, 14.5110),
    "Celovška cesta": (46.0735, 14.4790), "Tržaška cesta": (46.0400, 14.4820),
}


class LocationError(ValueError):
    """The patient's location could not be found; safe to show to the operator."""


class CallRequest(BaseModel):
    text: str = Field(min_length=2, max_length=1000)  # the caller's words
    address: str | None = Field(default=None, max_length=200)
    place_id: str | None = None
    lat: float | None = None
    lon: float | None = None
    caller_name: str | None = Field(default=None, max_length=80)
    dropoff_id: str | None = None


@dataclass
class Location:
    pickup_id: str | None
    lat: float
    lon: float
    label: str  # the address as shown


def _norm(text: str) -> str:
    """Lower case without diacritics: 'Zaloška cesta' -> 'zaloska cesta'."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c)).strip()


def _jitter(text: str) -> tuple[float, float]:
    h = zlib.crc32(_norm(text).encode())
    return ((h % 1000) / 999 - 0.5) * 2 * ADDRESS_JITTER[0], (((h // 1000) % 1000) / 999 - 0.5) * 2 * ADDRESS_JITTER[1]


def _street_in(street: str, n: str) -> bool:
    """The street is named in the normalized text n: in full, or the way callers often say it, without
    "cesta"/"ulica" ("Dunajska 100" for Dunajska cesta 100), as a whole word."""
    s = _norm(street)
    if s in n:
        return True
    words = s.split()
    return (
        len(words) == 2 and words[1] in ("cesta", "ulica") and len(words[0]) >= 6
        and re.search(rf"\b{re.escape(words[0])}\b", n) is not None
    )


def _area_place(state: WorldState, area: str):
    return next((p for p in state.places.values() if p.kind == "residential" and p.name == area), None)


def resolve_address(state: WorldState, address: str) -> Location | None:
    """A typed address -> a location: a known place by name, a street we know (central streets, the
    areas' streets) or an area name. None if nothing matches."""
    n = _norm(address)
    if not n:
        return None
    named = [p for p in state.places.values() if p.kind not in ("call_location", "incident_site")]
    exact = next((p for p in named if _norm(p.name) == n), None)
    if exact is not None:
        return Location(exact.id, exact.lat, exact.lon, exact.name)
    area = next((a for a in gen.STREETS if re.search(rf"\b{re.escape(_norm(a))}\b", n)), None)
    street_area = next((a for a, streets in gen.STREETS.items() for s in streets if _street_in(s, n)), None)
    central = next((s for s in CENTRAL_STREETS if _street_in(s, n)), None)
    dlat, dlon = _jitter(n)
    where = area or (None if central else street_area)
    if where and (p := _area_place(state, where)) is not None:
        return Location(None, round(p.lat + dlat, 5), round(p.lon + dlon, 5), address.strip())
    if central:
        lat, lon = CENTRAL_STREETS[central]
        return Location(None, round(lat + dlat / 3, 5), round(lon + dlon / 3, 5), address.strip())
    inside = next((p for p in named if len(_norm(p.name)) >= 3 and _norm(p.name) in n), None)
    if inside is not None:
        return Location(inside.id, inside.lat, inside.lon, address.strip())
    return None


def resolve(state: WorldState, address: str | None, place_id: str | None, lat: float | None, lon: float | None) -> Location | None:
    if place_id:
        p = state.places.get(place_id)
        if p is None:
            raise LocationError(f"Unknown place {place_id}")
        return Location(p.id, p.lat, p.lon, (address or "").strip() or p.name)
    if lat is not None and lon is not None:
        return Location(None, lat, lon, (address or "").strip() or f"Map point near {nearest_place_name(state, lat, lon)}")
    return resolve_address(state, address) if address else None


NOT_FOUND = "Address not found: pick a known place or a point on the map (or name the area, e.g. 'Zaloška cesta 45, Moste')"


# --- From the triage to the dispatch -------------------------------------------------------------


def call_event(loc: Location, result: TriageResult, dropoff_id: str | None, note: str | None) -> UrgentRequestEvent:
    tr = result.triage
    red = tr.severity in ("critical", "serious")
    needs = "stretcher" if red or tr.condition != "fracture" else "seated"
    return UrgentRequestEvent(
        type="urgent_request", pickup_id=loc.pickup_id, lat=None if loc.pickup_id else loc.lat,
        lon=None if loc.pickup_id else loc.lon, place_name=None if loc.pickup_id else loc.label[:80],
        dropoff_id=dropoff_id or "ukc", needs=needs, priority="emergency" if red else "urgent",  # type: ignore[arg-type]
        severity=tr.severity, condition=tr.condition, modifiers=list(tr.modifiers),  # type: ignore[arg-type]
        needs_doctor=tr.needs_doctor, note=(note or "")[:200] or None,
    )


def _apply(state: WorldState, loc: Location, result: TriageResult, call: CallRecord, dropoff_id: str | None,
           note: str | None) -> EventRecord:
    call.triage = result.triage
    if result.text_en:
        call.text_en = result.text_en
    record = apply_event(state, call_event(loc, result, dropoff_id, note), call)
    by = {"ai": "Claude", "rules": "the keyword rules"}.get(result.triage.by, result.triage.by)
    extra = f" ({result.fallback})" if result.fallback else ""
    AUDIT.record(state.name, "call", f"Call {call.call_id} triaged by {by}{extra}: {record.summary}", ref=record.id,
                 payload={"call": call, "event": record})
    return record


def response(state: WorldState, record: EventRecord, result: TriageResult) -> dict[str, Any]:
    """{trip, summary} (the trip's fields are repeated at the top level for older clients)."""
    from .engine.units import trip_view

    trip = state.trips[record.affected_trip_ids[0]]
    data = trip_view(state, trip)  # with `units`
    note = f" Triaged by the keyword rules ({result.fallback})." if result.fallback else ""
    return {**data, "trip": data, "summary": record.summary + note, "event_id": record.id}


async def take_call(state: WorldState, req: CallRequest) -> tuple[EventRecord, TriageResult]:
    """A call typed by the call-taker: Claude triages it when available, else the rules. Raises
    LocationError if the patient's location cannot be found."""
    received = state.sim_time
    loc = resolve(state, req.address, req.place_id, req.lat, req.lon)
    if loc is None and not (config.agent_enabled() and GUARD.available()):
        raise LocationError(NOT_FOUND)  # the AI could not help either: ask before spending anything
    if req.dropoff_id and req.dropoff_id not in state.places:
        raise LocationError(f"Unknown destination {req.dropoff_id}")
    result = await triage(state, req.text, req.address, use_ai=True)
    if loc is None and result.address:
        loc = resolve_address(state, result.address)
    if loc is None:
        raise LocationError(NOT_FOUND)
    call = CallRecord(
        call_id=gen.new_call_id(state, "112"), kind="112", received_at=received,
        caller_name=(req.caller_name or "").strip() or None, address=result.address or loc.label,
        text_sl=req.text.strip(), text_en=req.text.strip(),
    )
    return _apply(state, loc, result, call, req.dropoff_id, result.text_en or req.text), result


# --- Demo: a random call --------------------------------------------------------------------------


def library() -> list[tuple[str, str, str, tuple[str, float, float] | None]]:
    """The random calls: (condition, Slovenian words, English, remote spot or None for a street address)."""
    out: list[tuple[str, str, str, tuple[str, float, float] | None]] = []
    for words in (gen.CALLER_WORDS, gen.CHILD_WORDS):
        for condition, texts in words.items():
            out += [(condition, sl, en, None) for sl, en in texts]
    for name, lat, lon, _note in gen.REMOTE:
        sl, en = gen.REMOTE_WORDS[name]
        out.append(("major_trauma", sl, en, (name, lat, lon)))
    out += [("major_trauma", sl, en, (name, lat, lon)) for name, lat, lon, sl, en in gen.REMOTE_EXTRA]
    return out


_last_ai_random: dict[str, float] = {}


async def random_call(state: WorldState, severity: str | None = None) -> tuple[EventRecord, TriageResult]:
    rng = state.calls.text_rng
    pool = [e for e in library() if severity is None or CONDITIONS[e[0]][1] == severity]
    condition, sl, en, remote = rng.choice(pool)
    if remote is not None:
        name, lat, lon = remote
        loc = Location(None, lat, lon, name)
    else:
        area_id = rng.choice(gen.SUBURBS if rng.random() < 0.2 else gen.CITY)
        p = state.places[area_id]
        loc = Location(None, round(p.lat + rng.uniform(-0.004, 0.004), 5), round(p.lon + rng.uniform(-0.006, 0.006), 5),
                       gen.street_address(rng, p.name))
    now = time.monotonic()
    use_ai = state.ai_triage and now - _last_ai_random.get(state.name, -1e9) >= RANDOM_CALL_AI_GAP_S
    if use_ai:
        _last_ai_random[state.name] = now
    received = state.sim_time
    result = await triage(state, sl, loc.label, use_ai=use_ai)
    if not result.text_en:
        result.text_en = en
    call = CallRecord(call_id=gen.new_call_id(state, "112"), kind="112", received_at=received,
                      caller_name=gen.caller_name(rng), address=loc.label, text_sl=sl, text_en=en)
    return _apply(state, loc, result, call, None, en), result


# --- Generated calls with AI triage -----------------------------------------------------------------

_pending: set[asyncio.Task] = set()


def defer_generated(state: WorldState, ev: UrgentRequestEvent, call: CallRecord,
                    on_record: Callable[[WorldState, EventRecord], None]) -> bool:
    """sim/calls.step hook: with ai_triage on, Claude triages a generated 112 call before it is
    dispatched (a few seconds). Returns False (the rules triage it now) when the switch is off, Claude
    is off, or fewer than AI_TRIAGE_RESERVE guarded requests are left."""
    if not state.ai_triage or not config.agent_enabled() or GUARD.headroom() <= AI_TRIAGE_RESERVE:
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    task = loop.create_task(_triage_generated(state, ev, call, state.epoch, on_record))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
    return True


async def _triage_generated(state: WorldState, ev: UrgentRequestEvent, call: CallRecord, epoch: int,
                            on_record: Callable[[WorldState, EventRecord], None]) -> None:
    try:
        result = await triage(state, call.text_sl, call.address, use_ai=True)
        if state.epoch != epoch:
            return  # the world was reset meanwhile
        call.triage = result.triage
        if result.text_en:
            call.text_en = result.text_en
        tr = result.triage
        red = tr.severity in ("critical", "serious")
        data = {**ev.model_dump(), "severity": tr.severity, "condition": tr.condition, "modifiers": list(tr.modifiers),
                "needs_doctor": tr.needs_doctor, "priority": "emergency" if red else "urgent"}
        record = apply_event(state, UrgentRequestEvent(**data), call)
        record.generated = True
        on_record(state, record)
    except Exception:  # noqa: BLE001 - never lose a call: apply it as generated
        log.exception("AI triage of a generated call failed; applying it with the rules")
        if state.epoch == epoch and not any(t.call is call for t in state.trips.values()):
            from .agent.triage import triage_rules

            call.triage = triage_rules(call.text_sl, state.sim_time)
            record = apply_event(state, ev, call)
            record.generated = True
            on_record(state, record)
