"""HTTP routes for the clinical log and the ER board, mounted under /{world}/ (live, sim, ...).

    POST /{world}/clinical/entries              crew or system writes an entry (201 new, 200 replay)
    POST /{world}/clinical/entries/{seq}/confirm  a tap on "heard" / "inferred": a confirmed copy
    GET  /{world}/clinical/entries              catch-up read: ?since_seq=0&case_id=&limit=500
    GET  /{world}/er/board                      the ER read model (the same dict the snapshot carries)
    GET  /{world}/er/cases/{case_id}            one card plus its full timeline
    POST /{world}/er/cases/{case_id}/actions    reception: acknowledge, assign a bay, activate a team

This module only translates HTTP to and from the service and the projection; every rule lives in
service.py and every card in projection.py, so the screens cannot disagree. Every handler is an
`async def` with no await inside: service.py relies on the single event loop (no threadpool) for
its check-then-append to be atomic, and reads share it so they never see a half-applied write.

`mount` is called by the app (a one-line seam in main.py). It does nothing when the clinical
feature is switched off, looked up at call time. It never imports app.main. The routes are added
straight to the app (no APIRouter), so they are plain APIRoute entries in `app.routes` on every
FastAPI version, whether or not that version flattens an included router.
"""
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..models import Trip
from ..state import WorldState
from . import config
from .models import ENTRY_IN, EntryBase, EntryIn, ERActionContent, Source
from .projection import board, build_case, er_case_trips
from .service import ClinicalError, confirm_entry, record_entry
from .store import get_log

PREFIX = "/{world}"


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit: str = Field(min_length=1)
    source: Source = "crew_tap"


class ERActionBody(ERActionContent):
    """What reception sends: the action and its bay/team (the same rules as the stored content,
    inherited), plus a free-text note and an optional idempotency key."""

    note: str | None = Field(None, max_length=500)  # stored as the entry's verbatim text
    client_entry_id: str | None = Field(None, max_length=64)


def _refused(exc: ClinicalError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


def _invalid(exc: ValidationError) -> HTTPException:
    """A pydantic error raised inside a handler, in the same shape FastAPI gives for a bad body."""
    detail = [
        {"loc": ["body", *(p for p in err["loc"] if p not in ("er_action", "content"))], "msg": err["msg"], "type": err["type"]}
        for err in exc.errors(include_url=False, include_context=False, include_input=False)
    ]
    return HTTPException(status_code=422, detail=detail)


def _er_case(state: WorldState, case_id: str) -> Trip:
    """The case on the ER board with this id: 404 for an unknown trip and for one not bound for an ER place."""
    for trip in er_case_trips(state):
        if trip.id == case_id:
            return trip
    raise HTTPException(status_code=404, detail=f"No ER case {case_id!r} in this world.")


def _store(state: WorldState, entry: EntryBase, response: Response) -> dict[str, Any]:
    try:
        stored, created = record_entry(state, entry)
    except ClinicalError as exc:
        raise _refused(exc) from exc
    response.status_code = 201 if created else 200  # a replay returns the entry the first request made
    return stored.model_dump(mode="json")


def mount(app: FastAPI, worlds: dict[str, WorldState]) -> None:
    """Add the clinical routes to `app`; `worlds` maps the {world} path segment to its state."""
    if not config.enabled():
        return

    async def world_state(world: str = Path(..., description="a world name, e.g. live or sim")) -> WorldState:
        state = worlds.get(world)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Unknown world {world!r}.")
        return state

    World = Depends(world_state)
    replayable = {200: {"description": "Already recorded: the earlier entry."}}

    # `entry` is deliberately not given a `= Body(...)` default: that would drop EntryIn's
    # discriminator and turn one clear error into one error per entry type.
    @app.post(f"{PREFIX}/clinical/entries", status_code=201, responses=replayable)
    async def post_entry(response: Response, entry: EntryIn, state: WorldState = World) -> dict[str, Any]:
        return _store(state, entry, response)

    @app.post(f"{PREFIX}/clinical/entries/{{seq}}/confirm")
    async def confirm(seq: int, body: ConfirmBody, state: WorldState = World) -> dict[str, Any]:
        try:
            return confirm_entry(state, seq, body.unit, body.source).model_dump(mode="json")
        except ClinicalError as exc:
            raise _refused(exc) from exc

    @app.get(f"{PREFIX}/clinical/entries")
    async def list_entries(
        since_seq: int = Query(0, ge=0, description="only entries after this seq"),
        case_id: str | None = Query(None, description="only this case's entries"),
        limit: int = Query(500, ge=1, le=2000),
        state: WorldState = World,
    ) -> list[dict[str, Any]]:
        return [e.model_dump(mode="json") for e in get_log(state).since(since_seq, case_id, limit)]

    @app.get(f"{PREFIX}/er/board")
    async def er_board(state: WorldState = World) -> dict[str, Any]:
        return board(state)

    @app.get(f"{PREFIX}/er/cases/{{case_id}}")
    async def er_case(case_id: str, state: WorldState = World) -> dict[str, Any]:
        trip = _er_case(state, case_id)
        entries = get_log(state).for_case(trip.id)
        return {"case": build_case(state, trip, entries), "timeline": [e.model_dump(mode="json") for e in entries]}

    @app.post(f"{PREFIX}/er/cases/{{case_id}}/actions", status_code=201, responses=replayable)
    async def er_action(case_id: str, body: ERActionBody, response: Response, state: WorldState = World) -> dict[str, Any]:
        trip = _er_case(state, case_id)
        try:
            entry = ENTRY_IN.validate_python(
                {
                    "case_id": trip.id,
                    "unit": "er",
                    "source": "er_reception",
                    "type": "er_action",
                    "state": "confirmed",
                    "content": {"action": body.action, "bay": body.bay, "team": body.team},
                    "verbatim": body.note,
                    "client_entry_id": body.client_entry_id,
                }
            )
        except ValidationError as exc:
            raise _invalid(exc) from exc
        return _store(state, entry, response)

