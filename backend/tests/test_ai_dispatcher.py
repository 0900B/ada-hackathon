"""The AI dispatcher: Claude runs each case, the dispatcher can intervene (app/ai_dispatcher.py,
app/overrides.py, engine/units.py, the timeline's `detail` and the world's ai_stats).

Run from backend/:  python tests/test_ai_dispatcher.py
Offline: road routing off, no real Claude (a fake client answers the triage and the review requests).

- Autonomous: a new red call's dispatch is reviewed by Claude; a change is applied through the approval
  path (by "ai", "Claude, N s, checked by the engine"); "keep" is logged as "reviewed".
- The guard refuses / Claude is too slow / no key: the engine's decision stands and the timeline says so.
- Assisted: no review without auto-analyse; with it, the review stays a proposal.
- Disruptions touching a case are reviewed too, one review per case at a time, not within 2 world-min.
- trip.units: reasons for a free unit, a unit available soon, a doctor car, the helicopter, an override.
- Alternatives: ranked, delta vs the current unit, cost texts; assign replace / add, refusals.
- ai_stats counters; ai_mode and the autopilot alias.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

os.environ["ROAD_ROUTING"] = "0"
os.environ["AGENT_AUTO"] = "0"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("SCHEDULED_DAY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, intake, main  # noqa: E402
from app.agent import runner  # noqa: E402
from app.agent.triage import triage_rules  # noqa: E402
from app.engine.events import apply_event  # noqa: E402
from app.engine.projection import project_all  # noqa: E402
from app.guard import GUARD  # noqa: E402
from app.models import CallRecord, DelayEvent, UrgentRequestEvent  # noqa: E402
from app.sim import calls  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402
from app.sim.simulator import tick  # noqa: E402

logging.disable(logging.WARNING)
client = TestClient(main.app)
W = main.sim
USAGE = NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
ARREST = "Moj mož se je zgrudil, ne diha in se ne odziva!"
ARREST_AT = "Dunajska cesta 50, Bežigrad"
DAY = datetime(2026, 11, 23, 9, 0, tzinfo=ZoneInfo("Europe/Ljubljana"))  # fixed clock, by day: the helicopter flies 08:00-16:30


def fresh(in_service: tuple[str, ...] | None = None) -> None:
    seed_world(W, config.RANDOM_SEED, scheduled_day=False, start=DAY)
    W.auto_analyze = False
    W.calls.enabled = False
    W.ai_triage = False
    W.ai_mode = "assisted"
    GUARD.reset()
    if in_service is not None:
        for v in W.vehicles.values():
            if v.id not in in_service:
                v.status = "out_of_service"


def run(minutes: float, until=None, step_s: float = 15) -> bool:
    for _ in range(int(minutes * 60 / step_s)):
        tick(W, step_s)
        project_all(W)
        if until and until():
            return True
    return False


def park(vid: str, place: str, status: str = "returning") -> None:
    v, p = W.vehicles[vid], W.places[place]
    v.lat, v.lon, v.status, v.path_from, v.path_to = p.lat, p.lon, status, None, None


def call112(severity: str, condition: str, text: str = "test", place_id: str | None = None,
            lat: float | None = None, lon: float | None = None):
    """A 112 call with its record (rules triage) through the normal event path; returns (record, trip)."""
    call = CallRecord(call_id=calls.new_call_id(W, "112"), kind="112", received_at=W.sim_time, address="test address",
                      text_sl=text, text_en=text, triage=triage_rules(text, W.sim_time))
    priority = "urgent" if severity == "urgent" else "emergency"
    ev = UrgentRequestEvent(type="urgent_request", pickup_id=place_id, lat=lat, lon=lon, place_name=None if place_id else "call",
                            priority=priority, severity=severity, condition=condition)  # type: ignore[arg-type]
    rec = apply_event(W, ev, call)
    return rec, W.trips[rec.affected_trip_ids[0]]


def kinds(trip) -> list[str]:
    return [e.kind for e in trip.timeline]


def last(trip, kind: str):
    return next((e for e in reversed(trip.timeline) if e.kind == kind), None)


def unit(trip, vehicle_id: str) -> dict:
    snap = next(x for x in W.snapshot()["trips"] if x["id"] == trip.id)
    return next(u for u in snap["units"] if u["vehicle_id"] == vehicle_id)


# --- A fake Claude ---------------------------------------------------------------------------------


def keep(reason: str = "The engine's unit is the closest one. Nothing is clearly better.") -> dict:
    return {"situation": "s", "options": [], "reasoning": reason, "recommended_option": 0, "notifications": [], "escalation": None}


def change(trip_id: str, vehicle_id: str, title: str | None = None) -> dict:
    step = {"trip_id": trip_id, "vehicle_id": vehicle_id, "position": None, "interrupt_current": False, "dropoff_id": None}
    opt = {"title": title or f"Send {vehicle_id} instead", "summary": "x", "steps": [step], "pros": ["p"], "cons": ["c"],
           "activate_surge": False}
    return {"situation": "s", "options": [opt], "reasoning": "Option 1 is better.", "recommended_option": 1,
            "notifications": [], "escalation": None}


class FakeClaude:
    """Answers the triage request with the keyword rules' grading, and every analysis (requests with tools)
    with `answer` (a dict, or a function of the request), optionally after a delay."""

    def __init__(self, answer=None, delay: float = 0.0) -> None:
        self.answer, self.delay, self.requests = answer, delay, []
        self.beta = NS(messages=NS(create=self.create))

    async def create(self, **kw):
        if "tools" not in kw:
            words = kw["messages"][0]["content"].split("\n\nAddress")[0].removeprefix("Caller's words:\n")
            tr = triage_rules(words, W.sim_time)
            data = {"severity": tr.severity, "condition": tr.condition or "other", "modifiers": tr.modifiers,
                    "needs_doctor": tr.needs_doctor, "reason_en": tr.reason_en, "reason_sl": tr.reason_sl,
                    "text_en": words, "address": ""}
            return NS(stop_reason="end_turn", content=[NS(type="text", text=json.dumps(data))], usage=USAGE)
        self.requests.append(kw)
        if self.delay:
            await asyncio.sleep(self.delay)
        ans = self.answer(kw) if callable(self.answer) else self.answer
        return NS(stop_reason="end_turn", content=[NS(type="text", text=json.dumps(ans))], usage=USAGE)


class claude_on:
    """Claude 'enabled' (a key is set) and answered by the fake."""

    def __init__(self, fake: FakeClaude) -> None:
        self.fake = fake

    def __enter__(self):
        self.prev = runner._get_client
        os.environ["ANTHROPIC_API_KEY"] = "test-key-not-used"
        runner._get_client = lambda: self.fake
        return self.fake

    def __exit__(self, *exc):
        runner._get_client = self.prev
        os.environ.pop("ANTHROPIC_API_KEY", None)


async def settle() -> None:
    """Wait for the background analyses of this world."""
    while tasks := [t for k, t in list(runner._tasks.items()) if k.startswith(f"{W.name}:")]:
        await asyncio.gather(*tasks, return_exceptions=True)


async def new_call(text: str = ARREST, address: str = ARREST_AT) -> dict:
    return await main.post_call(intake.CallRequest(text=text, address=address), W)


def reviews_of(trip) -> list:
    return [r for r in W.agent_runs if r.review_of == trip.id]


# --- Autonomous ------------------------------------------------------------------------------------


def test_autonomous_applies_claudes_change_through_the_approval_path():
    fresh()
    W.vehicles["H1"].status = "out_of_service"
    W.ai_mode = "autonomous"
    fake = FakeClaude()
    holder = {}

    def answer(kw):  # Claude prefers the other ambulance at the Center base
        t = holder["trip"]
        return change(t.id, next(v for v in ("A1", "A2", "A3") if v != t.vehicle_id), "Send the other ambulance")

    fake.answer = answer

    async def go():
        body = await new_call()
        holder["trip"] = W.trips[body["trip"]["id"]]
        holder["first"] = holder["trip"].vehicle_id
        await settle()

    with claude_on(fake):
        asyncio.run(go())
    t, first = holder["trip"], holder["first"]
    assert len(fake.requests) == 1 and "AI dispatcher review of new critical call" in fake.requests[0]["messages"][0]["content"]
    (r,) = reviews_of(t)
    assert r.status == "approved" and r.decision["by"] == "ai" and r.engine == "claude", (r.status, r.steps[-3:])
    assert t.vehicle_id not in (None, first)
    a = last(t, "reviewed")
    assert a.by == "ai" and a.detail.startswith("Claude, ") and a.detail.endswith("checked by the engine"), a
    assert a.text == f"AI dispatcher (Claude) changed: {t.vehicle_id} instead of {first} — Send the other ambulance", a.text
    assert a.run_id == r.id and "approved" not in kinds(t), kinds(t)
    moved = last(t, "reassigned")
    assert moved.by == "ai" and moved.vehicle_id == t.vehicle_id, kinds(t)
    u = unit(t, t.vehicle_id)
    assert u["assigned_by"] == "ai" and u["reason"] == "AI dispatcher (Claude): Send the other ambulance", u
    s = client.get("/sim/state").json()["ai_stats"]
    assert s["claude_reviews"] == 1 and s["claude_changes"] == 1 and s["reassignments"] >= 1, s


def test_autonomous_keep_is_logged_as_reviewed():
    fresh()
    W.vehicles["H1"].status = "out_of_service"
    W.ai_mode = "autonomous"
    fake = FakeClaude(keep("A1 is the closest free ambulance and D1 the closest doctor car. Keep."))
    holder = {}

    async def go():
        holder["body"] = await new_call()
        await settle()

    with claude_on(fake):
        asyncio.run(go())
    t = W.trips[holder["body"]["trip"]["id"]]
    e = last(t, "reviewed")
    assert e is not None and e.by == "ai" and e.detail.startswith("Claude, "), kinds(t)
    assert e.text == f"AI dispatcher (Claude) reviewed: no change — keep {t.vehicle_id} and doctor car {t.doctor_vehicle_id} " \
                     f"for {t.id} (A1 is the closest free ambulance and D1 the closest doctor car)", e.text
    assert reviews_of(t)[0].status == "done" and W.ai_stats["claude_reviews"] == 1 and W.ai_stats["claude_changes"] == 0
    assert not any(k in kinds(t) for k in ("approved", "reassigned", "proposal")), kinds(t)


def test_guard_refusal_or_slow_claude_leaves_the_engines_decision():
    # The guard has nothing left: the rules triage the call, the engine's dispatch stands, the timeline says so.
    fresh()
    W.ai_mode = "autonomous"
    fake = FakeClaude(keep())
    GUARD.per_window = 0
    try:
        with claude_on(fake):
            body = asyncio.run(new_call())
    finally:
        GUARD.per_window = 12
    t = W.trips[body["trip"]["id"]]
    note = last(t, "note")
    assert note.text == "AI dispatcher review not available (AI limit reached): the engine's decision stands", kinds(t)
    assert note.by == "engine" and fake.requests == [] and reviews_of(t) == [] and t.vehicle_id
    assert GUARD.status()["refused"]["auto_skipped"] == 1
    # Claude takes too long: the engine's fallback, nothing applied.
    fresh()
    W.ai_mode = "autonomous"
    fake = FakeClaude(change("TR-001", "A3"), delay=1.0)
    holder = {}

    async def go():
        holder["body"] = await new_call()
        holder["first"] = W.trips[holder["body"]["trip"]["id"]].vehicle_id
        await settle()

    old = config.AGENT_TIMEOUT_S
    config.AGENT_TIMEOUT_S = 0.2
    try:
        with claude_on(fake):
            asyncio.run(go())
    finally:
        config.AGENT_TIMEOUT_S = old
    t = W.trips[holder["body"]["trip"]["id"]]
    assert t.vehicle_id == holder["first"] and reviews_of(t)[0].engine == "engine_fallback"
    assert last(t, "note").text == "AI dispatcher review not available (Claude took too long): the engine's decision stands"
    assert W.ai_stats["claude_reviews"] == 0
    # No API key at all: the same, without a run.
    fresh()
    W.ai_mode = "autonomous"
    t = W.trips[asyncio.run(new_call())["trip"]["id"]]
    assert "(no API key)" in last(t, "note").text and reviews_of(t) == []


# --- Assisted --------------------------------------------------------------------------------------


def test_assisted_reviews_only_with_auto_analyse_and_they_stay_proposals():
    fresh()
    W.vehicles["H1"].status = "out_of_service"
    fake = FakeClaude()
    holder = {}

    def answer(kw):
        t = holder["trip"]
        return change(t.id, next(v for v in ("A1", "A2", "A3") if v != t.vehicle_id))

    fake.answer = answer

    async def go():
        body = await new_call()
        holder["trip"] = W.trips[body["trip"]["id"]]
        holder["first"] = holder["trip"].vehicle_id
        await settle()

    with claude_on(fake):
        asyncio.run(go())  # assisted, auto-analyse off: no review
        assert fake.requests == [] and reviews_of(holder["trip"]) == []
        W.auto_analyze = True
        asyncio.run(go())
    t = holder["trip"]
    (r,) = reviews_of(t)
    assert r.status == "done" and t.vehicle_id == holder["first"], "a proposal only"
    p = last(t, "proposal")
    assert p.by == "ai" and p.run_id == r.id and p.text.startswith("AI dispatcher (Claude) proposes: Send ") and p.detail.startswith("Claude, ")
    assert W.ai_stats["claude_reviews"] == 1 and W.ai_stats["claude_changes"] == 0
    resp = client.post(f"/sim/agent/runs/{r.id}/approve", json={"option_index": 0})
    assert resp.status_code == 200, resp.text
    assert t.vehicle_id != holder["first"] and last(t, "approved").by == "dispatcher"
    u = unit(t, t.vehicle_id)  # Claude's recommendation, but the dispatcher decided
    assert u["assigned_by"] == "dispatcher" and u["reason"].startswith("approved: Send "), u


# --- Disruptions -----------------------------------------------------------------------------------


def test_a_disruption_of_a_case_is_reviewed_once_at_a_time_and_not_too_often():
    fresh()
    W.vehicles["H1"].status = "out_of_service"
    W.ai_mode = "autonomous"
    fake = FakeClaude(keep())
    holder = {}

    async def go():
        body = await new_call()
        t = holder["trip"] = W.trips[body["trip"]["id"]]
        await settle()
        # Within 2 world-min of the call's review: not reviewed again.
        await main.post_event(DelayEvent(type="delay", vehicle_id=t.vehicle_id, minutes=4, note="traffic"), W)
        holder["after_delay_1"] = len(reviews_of(t))
        W.sim_time += timedelta(minutes=3)
        project_all(W)
        rec = await main.post_event(DelayEvent(type="delay", vehicle_id=t.vehicle_id, minutes=5, note="traffic"), W)
        holder["rec"] = rec
        # One review per case at a time: another disruption while it runs starts none.
        await main.post_event(DelayEvent(type="delay", vehicle_id=t.vehicle_id, minutes=1), W)
        holder["while_running"] = len(reviews_of(t))
        await settle()

    with claude_on(fake):
        asyncio.run(go())
    t = holder["trip"]
    assert holder["after_delay_1"] == 1 and holder["while_running"] == 2, holder
    second = reviews_of(t)[-1]
    assert second.event_id == holder["rec"].id and second.trigger == f"review:{t.id}"
    q = fake.requests[-1]["messages"][0]["content"]
    assert f"AI dispatcher review of critical call {t.id}" in q and "after this disruption" in q and "delayed by 5 min" in q, q
    assert [e.kind for e in t.timeline].count("reviewed") == 2


# --- trip.units ------------------------------------------------------------------------------------


def test_units_say_why_each_unit_was_chosen():
    fresh()
    W.vehicles["H1"].status = "out_of_service"
    _, t = call112("critical", "cardiac_arrest", place_id="home_bezigrad")
    snap = next(x for x in client.get("/sim/state").json()["trips"] if x["id"] == t.id)
    amb, doc = snap["units"]
    assert amb["vehicle_id"] == t.vehicle_id and amb["role"] == "ambulance" and amb["assigned_by"] == "engine"
    assert amb["reason"].startswith("nearest free ambulance, ") and amb["reason"].endswith(" min"), amb
    assert amb["status_text"] in ("turning out", "about to leave", "driving to the patient") and amb["eta_scene"] and amb["eta_hospital"]
    assert doc["vehicle_id"] == t.doctor_vehicle_id and doc["role"] == "doctor" and doc["eta_hospital"] is None
    assert doc["reason"].startswith("doctor needed for cardiac arrest: first doctor car on scene"), doc
    assert set(amb) >= {"vehicle_id", "role", "status_text", "eta_scene", "eta_hospital", "reason", "assigned_by", "assigned_at"}
    # The helicopter: one unit, with its doctor on board.
    fresh()
    name, lat, lon, _ = calls.REMOTE[0]
    _, h = call112("critical", "cardiac_arrest", lat=lat, lon=lon)
    assert h.vehicle_id == "H1" and h.doctor_vehicle_id == "H1"
    (u,) = next(x for x in W.snapshot()["trips"] if x["id"] == h.id)["units"]
    assert u["role"] == "helicopter" and u["reason"].startswith("helicopter") and "doctor on board" in u["reason"], u
    # Available soon: A1 finishing at UKC is clearly sooner than a free A3 far away.
    fresh(("A1", "A3"))
    _, x = call112("serious", "breathing_difficulty", place_id="home_bezigrad")
    a1 = W.vehicles["A1"]
    if x.vehicle_id != "A1":  # (the nearest unit took it; give it to A1)
        from app.engine.actions import assign_trip

        assign_trip(W, x.id, "A1")
    assert run(90, until=lambda: x.status == "completed" and a1.busy_until is not None
               and 0 < (a1.busy_until - W.sim_time).total_seconds() <= 180)
    park("A3", "home_medvode")
    p = W.places["zd_center"]
    _, s = call112("serious", "breathing_difficulty", lat=p.lat, lon=p.lon)
    assert s.vehicle_id == "A1"
    r = unit(s, "A1")["reason"]
    assert r.startswith("available soon: ready after handover and cleaning, ") and "sooner than A3" in r, r


# --- Alternatives and the dispatcher's override -----------------------------------------------------


def _arrest_next_to_a1_on_its_way_to_a_fall():
    """A1 drives to an urgent fall (with a hypothetical 5-min target, so the engine never diverts A1); a
    cardiac arrest right next to A1 goes to A3 (the helicopter and A2 are out of service)."""
    from app.engine.actions import assign_trip

    fresh(("A1", "A3", "D1", "D2", "T1"))
    park("A3", "zd_vic")
    _, fall = call112("urgent", "fall", place_id="home_polje")
    if fall.vehicle_id != "A1":
        assign_trip(W, fall.id, "A1")
    fall.response_target_min = 5.0
    run(2)
    a1 = W.vehicles["A1"]
    assert a1.current_trip_id == fall.id and fall.status == "en_route_pickup"
    _, t = call112("critical", "cardiac_arrest", lat=round(a1.lat + 0.003, 5), lon=round(a1.lon + 0.004, 5))
    assert t.vehicle_id == "A3" and t.doctor_vehicle_id in ("D1", "D2"), t.timeline[-1].text
    return fall, t


def alternatives(trip, role: str) -> list[dict]:
    r = client.get(f"/sim/trips/{trip.id}/alternatives", params={"role": role})
    assert r.status_code == 200, r.text
    return r.json()


def test_alternatives_are_ranked_by_the_engine_with_their_cost():
    fall, t = _arrest_next_to_a1_on_its_way_to_a_fall()
    alts = alternatives(t, "ambulance")
    by = {a["vehicle_id"]: a for a in alts}
    assert set(by) >= {"A1", "A2", "A3", "M1", "P1", "P2"}, list(by)
    feasible = [a for a in alts if a["feasible"]]
    assert alts[: len(feasible)] == feasible, "feasible first"
    assert [a["eta_minutes"] for a in feasible] == sorted(a["eta_minutes"] for a in feasible), "soonest first"
    cur = by["A3"]
    assert cur["current"] and cur["cost_text"] == "current unit" and cur["delta_min"] == 0 and cur["type"] == "ambulance"
    a1 = by["A1"]
    assert a1["feasible"] and not a1["free"] and a1["delta_min"] < 0, a1
    assert a1["cost_text"].startswith(f"diverts {fall.id} (urgent), which then waits ") and a1["cost_text"].endswith(" min longer"), a1
    assert a1["note"].startswith("turns around now"), a1
    assert by["M1"]["cost_text"] == "mutual aid from Domžale: requested for this call" and by["M1"]["delta_min"] > 0
    assert by["P1"]["cost_text"].startswith("private ambulance from ") and by["P1"]["feasible"]
    assert by["P2"]["cost_text"] == "private, needs surge capacity" and not by["P2"]["feasible"] and by["P2"]["eta_minutes"]
    assert not by["A2"]["feasible"] and by["A2"]["note"] == "Ambulance 2 is out of service" and by["A2"]["eta_scene"] is None
    (h1,) = alternatives(t, "helicopter")
    assert not h1["feasible"] and "out of service" in h1["note"]
    docs = {a["vehicle_id"]: a for a in alternatives(t, "doctor")}
    other = "D2" if t.doctor_vehicle_id == "D1" else "D1"
    assert docs[t.doctor_vehicle_id]["current"] and docs[other]["cost_text"] == "free" and docs[other]["delta_min"] > 0
    assert client.get(f"/sim/trips/{t.id}/alternatives", params={"role": "van"}).status_code == 422
    assert client.get("/sim/trips/TR-999/alternatives").status_code == 404
    # The helicopter (in service) for a serious call in the city: offered, with its doctor on board and
    # its activation at Brnik (13 min call to take-off), so much later than the ambulance.
    fresh()
    _, s = call112("serious", "stroke", place_id="home_moste")
    assert s.vehicle_id != "H1"
    (h1,) = alternatives(s, "helicopter")
    assert h1["feasible"] and h1["free"] and h1["cost_text"] == "helicopter, doctor on board, take-off in 13 min", h1
    assert h1["delta_min"] is not None and h1["delta_min"] > 10 and h1["eta_minutes"] > 13, h1
    # At night it is listed as unavailable, with why.
    W.sim_time = W.sim_time.replace(hour=20)  # 21:00 local
    (h1,) = alternatives(s, "helicopter")
    assert not h1["feasible"] and h1["cost_text"] == "not available" and "unavailable (night)" in h1["note"], h1


def test_the_dispatcher_replaces_and_adds_units_or_is_told_why_not():
    fall, t = _arrest_next_to_a1_on_its_way_to_a_fall()
    r = client.post(f"/sim/trips/{t.id}/assign", json={"vehicle_id": "A1", "mode": "replace"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trip"]["id"] == t.id and body["trip"]["vehicle_id"] == "A1" and t.vehicle_id == "A1"
    assert body["summary"].startswith("Dispatcher override: A1 instead of A3: at the patient ") and "min sooner" in body["summary"]
    assert f"diverts {fall.id}" in body["summary"], body["summary"]
    e = last(t, "override")
    assert e.by == "dispatcher" and e.detail == "dispatcher override" and e.vehicle_id == "A1"
    assert "reassigned" not in kinds(t), "the override entry says it once"
    u = next(u for u in body["trip"]["units"] if u["vehicle_id"] == "A1")
    assert u["assigned_by"] == "dispatcher" and u["reason"].startswith("dispatcher override (was A3): diverts"), u
    assert W.vehicles["A3"].current_trip_id is None and not W.vehicles["A3"].queue, "A3 released"
    assert fall.vehicle_id == "A1" and fall.times_displaced == 0, "the fall waits for A1 (the dispatcher's choice)"
    assert W.ai_stats["overrides"] == 1
    # Doctor cars: add refused while one goes; replace swaps them (the first stands down).
    d = t.doctor_vehicle_id
    other = "D2" if d == "D1" else "D1"
    r = client.post(f"/sim/trips/{t.id}/assign", json={"vehicle_id": other, "mode": "add"})
    assert r.status_code == 400 and r.json()["detail"] == f"{t.id} already has doctor car {d}: use replace to swap it", r.text
    r = client.post(f"/sim/trips/{t.id}/assign", json={"vehicle_id": other, "mode": "replace"})
    assert r.status_code == 200 and t.doctor_vehicle_id == other and W.vehicles[d].current_trip_id is None, r.text
    assert r.json()["summary"].startswith(f"Dispatcher override: doctor car {other} instead of {d}")
    assert next(u for u in r.json()["trip"]["units"] if u["role"] == "doctor")["reason"].startswith(f"dispatcher override (was {d})")
    # A doctor car busy with another call is never pulled off it.
    _, t2 = call112("critical", "choking", place_id="home_siska")
    assert t2.doctor_vehicle_id == d
    r = client.post(f"/sim/trips/{t2.id}/assign", json={"vehicle_id": other, "mode": "replace"})
    assert r.status_code == 400 and r.json()["detail"] == f"{other} is busy with {t.id}: a doctor car is never pulled off another call"
    # Add the helicopter: out of service -> refused; in service -> a linked trip for a further patient.
    r = client.post(f"/sim/trips/{t.id}/assign", json={"vehicle_id": "H1", "mode": "add"})
    assert r.status_code == 400 and "out of service" in r.json()["detail"], r.text
    W.vehicles["H1"].status = "idle"
    r = client.post(f"/sim/trips/{t.id}/assign", json={"vehicle_id": "H1", "mode": "add"})
    assert r.status_code == 200, r.text
    linked = W.trips[r.json()["linked_trip"]["id"]]
    assert linked.linked_to == t.id and linked.call is t.call and linked.vehicle_id == "H1" and not linked.needs_doctor
    assert r.json()["summary"].startswith(f"Dispatcher added H1 (helicopter) for a further patient: {linked.id}")
    units_now = {u["vehicle_id"]: u for u in r.json()["trip"]["units"]}
    assert set(units_now) == {"A1", other, "H1"} and units_now["H1"]["trip_id"] == linked.id
    assert units_now["H1"]["reason"] == "added by the dispatcher: helicopter, doctor on board, take-off in 13 min"
    assert kinds(linked)[:2] == ["received", "override"] and last(t, "override").text == r.json()["summary"].split("; ")[0]
    assert W.ai_stats["overrides"] == 3
    # Refusals.
    for vid, mode, why in (("A1", "replace", "A1 already serves"), ("T1", "replace", "transport van"),
                           ("P2", "replace", "activate surge capacity first"), ("A3", "sideways", "mode must be")):
        r = client.post(f"/sim/trips/{t.id}/assign", json={"vehicle_id": vid, "mode": mode})
        assert r.status_code in (400, 422) and (r.status_code == 422 or why in r.json()["detail"]), (vid, r.text)
    assert client.post(f"/sim/trips/{t.id}/assign", json={"vehicle_id": "X9"}).status_code == 404
    assert run(20, until=lambda: t.status == "onboard")
    r = client.post(f"/sim/trips/{t.id}/assign", json={"vehicle_id": "A3", "mode": "replace"})
    assert r.status_code == 400 and r.json()["detail"].startswith(f"The patient of {t.id} is on board A1"), r.text
    assert W.ai_stats["overrides"] == 3, "refusals are not counted"


def test_a_dispatcher_override_sticks_until_the_unit_drops_out():
    from app.engine import followup

    fresh()
    W.vehicles["H1"].status = "out_of_service"
    W.ai_mode = "autonomous"
    _, t = call112("serious", "breathing_difficulty", place_id="home_bezigrad")
    park("A3", "home_medvode", "idle")  # far away: the follow-up would normally take the call back from it
    r = client.post(f"/sim/trips/{t.id}/assign", json={"vehicle_id": "A3", "mode": "replace", "role": "ambulance",
                                                       "replaces": t.vehicle_id})
    assert r.status_code == 200 and t.vehicle_id == "A3", r.text
    better = [a for a in alternatives(t, "ambulance") if a["free"] and a["feasible"] and (a["delta_min"] or 0) <= -3]
    assert better, "a free ambulance is clearly sooner, so without the override the follow-up would switch"
    assert followup.check(W, force=True) == [] and t.vehicle_id == "A3", "the follow-up leaves the override alone"
    run(1)
    followup.check(W, force=True)
    assert t.vehicle_id == "A3"
    # Claude (autonomous) wants the faster unit back: refused, the dispatcher's decision stands.
    fake = FakeClaude(change(t.id, better[0]["vehicle_id"], "Faster unit"))

    async def go():
        W.sim_time += timedelta(minutes=3)
        project_all(W)
        await main.post_event(DelayEvent(type="delay", vehicle_id="A3", minutes=2, note="traffic"), W)
        await settle()

    with claude_on(fake):
        asyncio.run(go())
    assert t.vehicle_id == "A3" and fake.requests, kinds(t)
    assert "A3 (ambulance: dispatcher override (was " in fake.requests[-1]["messages"][0]["content"]
    assert "chosen by the dispatcher by hand: do not change it" in fake.requests[-1]["messages"][0]["content"]
    note = last(t, "note")
    assert note.by == "ai" and "not applied" in note.text and note.text.endswith("the dispatcher's decision stands"), note.text
    assert W.ai_stats["claude_changes"] == 0
    # The overriding unit drops out: replaced at once, and the engine follows the call up again.
    assert client.post("/sim/events", json={"type": "breakdown", "vehicle_id": "A3"}).status_code == 200
    assert t.vehicle_id not in (None, "A3") and last(t, "unit_replaced").text.startswith("A3 out of service")
    u = unit(t, t.vehicle_id)
    assert u["assigned_by"] == "engine" and u["reason"].startswith("replaces A3 (out of service); "), u
    # The body as the UI sends it: replaces is checked; role must match; a call with no unit gets one.
    r = client.post(f"/sim/trips/{t.id}/assign", json={"vehicle_id": "A2", "mode": "replace", "replaces": "A3"})
    assert r.status_code == 409 and r.json()["detail"].startswith(f"A3 no longer serves {t.id}"), r.text
    r = client.post(f"/sim/trips/{t.id}/assign", json={"vehicle_id": "D1", "mode": "add", "role": "ambulance"})
    assert r.status_code == 400 and r.json()["detail"] == "D1 is the wrong role: doctor, not ambulance", r.text
    fresh(("D1", "D2"))
    _, lone = call112("serious", "stroke", place_id="home_moste")
    assert lone.vehicle_id is None
    W.vehicles["A2"].status = "idle"
    r = client.post(f"/sim/trips/{lone.id}/assign", json={"vehicle_id": "A2", "mode": "replace", "role": "ambulance"})
    assert r.status_code == 200 and lone.vehicle_id == "A2" and r.json()["summary"].startswith("Dispatcher assigned A2"), r.text
    assert last(lone, "override").by == "dispatcher"


def test_a_unit_the_dispatcher_assigned_is_never_diverted_automatically():
    """A cardiac arrest right next to A1 would divert A1 from its urgent fall (the graded dispatch rule,
    test_emergency_dispatch case c). When the dispatcher put A1 on that fall by hand, the engine sends
    another unit and says why (the summary and the chosen unit's reason); Claude (autonomous) may not
    divert it either; the dispatcher still can, with Override."""
    fresh(("D1", "D2"))
    _, fall = call112("urgent", "fall", place_id="home_polje")
    assert fall.vehicle_id is None  # no ambulance in service yet: the dispatcher assigns one by hand
    for vid in ("A1", "A3"):
        W.vehicles[vid].status = "idle"
    park("A3", "home_medvode", "idle")
    r = client.post(f"/sim/trips/{fall.id}/assign", json={"vehicle_id": "A1", "mode": "replace", "role": "ambulance"})
    assert r.status_code == 200 and fall.vehicle_id == "A1", r.text
    run(2)
    a1 = W.vehicles["A1"]
    assert a1.current_trip_id == fall.id and fall.status == "en_route_pickup"
    W.ai_mode = "autonomous"
    fake = FakeClaude(lambda kw: change(holder["trip"].id, "A1", "Divert A1"))
    holder: dict = {}

    async def go():
        holder["rec"], holder["trip"] = call112("critical", "cardiac_arrest", lat=round(a1.lat + 0.003, 5), lon=round(a1.lon + 0.004, 5))
        main.ai_dispatcher.on_new_call(W, holder["rec"])
        await settle()

    with claude_on(fake):
        asyncio.run(go())
    rec, t = holder["rec"], holder["trip"]
    assert t.vehicle_id not in (None, "A1") and "diverted from" not in rec.summary, rec.summary
    note = f"A1 not diverted: assigned by the dispatcher to {fall.id} (Override to divert)"
    assert f"; {note}" in rec.summary, rec.summary
    assert unit(t, t.vehicle_id)["reason"].endswith(f"; {note}"), unit(t, t.vehicle_id)
    assert a1.current_trip_id == fall.id and fall.vehicle_id == "A1" and fall.times_displaced == 0
    # Claude wanted A1 for the arrest: refused, the dispatcher's decision stands.
    assert fake.requests and t.vehicle_id != "A1"
    refused = last(t, "note")
    assert refused is not None and "not applied" in refused.text and f"assigned A1 to {fall.id} by hand" in refused.text, kinds(t)
    # The dispatcher diverts it by hand: Override.
    r = client.post(f"/sim/trips/{t.id}/assign", json={"vehicle_id": "A1", "mode": "replace"})
    assert r.status_code == 200 and t.vehicle_id == "A1" and f"diverts {fall.id}" in r.json()["summary"], r.text


def test_the_general_analysis_stays_in_the_snapshot_next_to_case_reviews():
    """agent.runs (newest first, the last 5) always carries the newest general analysis (review_of None),
    even after more case reviews: the dashboard's Situation review shows that one (Y/N act on it), and
    each review shows on its own case card (review_of = the trip)."""
    from app.models import AgentRun, utcnow

    fresh()
    W.agent_runs.append(AgentRun(id="RUN-G", trigger="operator", started_at=utcnow(), status="done"))
    for i in range(6):
        W.agent_runs.append(AgentRun(id=f"RUN-R{i}", trigger=f"review:TR-00{i}", started_at=utcnow(), status="done",
                                     review_of=f"TR-00{i}"))
    W.bump()
    runs = client.get("/sim/state").json()["agent"]["runs"]
    assert [r["id"] for r in runs] == ["RUN-R5", "RUN-R4", "RUN-R3", "RUN-R2", "RUN-R1", "RUN-G"], [r["id"] for r in runs]
    assert runs[0]["review_of"] == "TR-005" and runs[-1]["review_of"] is None
    W.agent_runs.append(AgentRun(id="RUN-G2", trigger="operator", started_at=utcnow()))
    W.bump()
    assert [r["id"] for r in client.get("/sim/state").json()["agent"]["runs"]] == ["RUN-G2", "RUN-R5", "RUN-R4", "RUN-R3", "RUN-R2"]


# --- ai_stats, modes, detail -----------------------------------------------------------------------


def test_modes_stats_and_every_entry_says_its_source():
    fresh()
    s = client.get("/sim/state").json()
    assert s["ai_mode"] == "assisted" and s["autopilot"] is False
    assert s["ai_stats"] == {"dispatched": 0, "reroutes": 0, "reassignments": 0, "overrides": 0, "claude_reviews": 0,
                             "claude_changes": 0, "last_decision_at": None, "cases_active": 0}, s["ai_stats"]
    r = client.post("/sim/admin/ai-mode", json={"mode": "autonomous"})
    assert r.json() == {"world": "sim", "ai_mode": "autonomous", "autopilot": True}, r.text
    s = client.get("/sim/state").json()
    assert s["ai_mode"] == "autonomous" and s["autopilot"] is True and client.get("/live/state").json()["ai_mode"] == "assisted"
    assert client.post("/sim/admin/autopilot", json={"enabled": False}).json() == {"world": "sim", "autopilot": False}
    assert W.ai_mode == "assisted"
    assert client.post("/sim/admin/autopilot", json={"enabled": True}).json() == {"world": "sim", "autopilot": True}
    assert W.ai_mode == "autonomous"
    assert client.post("/sim/admin/ai-mode", json={"mode": "chaos"}).status_code == 422
    W.ai_mode = "assisted"
    # Counters: a dispatch, a unit replaced after a breakdown, a redirect, an override.
    body = client.post("/sim/calls", json={"text": ARREST, "address": ARREST_AT}).json()
    t = W.trips[body["trip"]["id"]]
    first = t.vehicle_id
    stats = W.ai_stats_view()
    assert stats["dispatched"] == 1 and stats["cases_active"] == 1 and stats["last_decision_at"], stats
    assert client.post("/sim/events", json={"type": "breakdown", "vehicle_id": first}).status_code == 200
    assert t.vehicle_id not in (None, first) and W.ai_stats["reassignments"] == 1
    assert unit(t, t.vehicle_id)["reason"].startswith(f"replaces {first} (out of service); "), unit(t, t.vehicle_id)
    r = client.post("/sim/plans/apply", json={"steps": [{"trip_id": t.id, "vehicle_id": t.vehicle_id, "position": None,
                                                         "dropoff_id": "sb_trbovlje"}]})
    assert r.status_code == 200, r.text
    assert W.ai_stats["reroutes"] == 1 and last(t, "rerouted").by == "dispatcher" and last(t, "rerouted").detail == "dispatcher plan"
    other = next(v for v in ("A1", "A2", "A3", "H1") if v not in (first, t.vehicle_id) and W.vehicles[v].status == "idle")
    assert client.post(f"/sim/trips/{t.id}/assign", json={"vehicle_id": other, "mode": "replace"}).status_code == 200
    s = client.get("/sim/state").json()["ai_stats"]
    assert (s["dispatched"], s["reassignments"], s["reroutes"], s["overrides"]) == (1, 1, 1, 1), s
    # Every timeline entry says its source.
    details = {e.kind: e.detail for e in t.timeline}
    assert all(e.detail for x in W.trips.values() for e in x.timeline)
    assert details["received"] == "112 call" and details["triaged"].startswith("keyword rules, "), details
    assert details["dispatched"].startswith("rules engine, ") and details["dispatched"].endswith(" s"), details
    assert details["override"] == "dispatcher override"
    snap = next(x for x in client.get("/sim/state").json()["trips"] if x["id"] == t.id)
    assert all("detail" in e for e in snap["timeline"])


def test_snapshot_epoch_changes_on_reset() -> None:
    """The dashboard drops its case selection when the world is reset (trip ids start again at TR-001):
    the snapshot's epoch changes on every reset and scenario, and only then."""
    fresh()
    first = client.get("/sim/state").json()["epoch"]
    assert client.get("/sim/state").json()["epoch"] == first
    assert client.post("/sim/admin/reset", json={}).status_code == 200
    second = client.get("/sim/state").json()["epoch"]
    assert second != first
    assert client.post("/sim/admin/scenario/same_level").status_code == 200
    assert client.get("/sim/state").json()["epoch"] not in (first, second)


if __name__ == "__main__":
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        t0 = time.time()
        try:
            fn()
            print(f"PASS {name} ({time.time() - t0:.1f}s)")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
