"""112 calls from the first second to the end (app/intake.py, engine/timeline.py, engine/followup.py,
sim/incidents.py, the autopilot in agent/runner.py, the high-demand hysteresis in engine/surge.py).

Run from backend/:  python tests/test_calls.py   (or: python -m pytest tests)
Offline: road routing off, no real Claude (a fake client stands in where the AI is tested).

- A whole call on its timeline: received, triaged, dispatched, doctor, on scene, transporting, at
  hospital, handover done, closed (by caller / rules / engine / crew).
- Intake: Claude's triage (fake client) incl. the red-flag safety net and a doctor asked for; the
  keyword rules when the guard is limited or Claude fails; unknown address -> 422.
- The generator: every caller text grades to its condition; the call stream is unchanged by the words.
- Automatic follow-up (112 calls only): re-dispatch after a breakdown, a faster free unit after a
  delay, a doctor car replaced; scenario jobs without a call record are left alone.
- Autopilot: approves the recommended option about an active call through the dispatcher's path.
- Demo buttons: random-call and random-incident hit sensible targets; 400 in live; next best kind.
- High-demand alert: raised after 5 sustained world-minutes with patients affected, cleared 5 min after.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
import traceback
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace as NS

os.environ["ROAD_ROUTING"] = "0"
os.environ["AGENT_AUTO"] = "0"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("SCHEDULED_DAY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, intake, main  # noqa: E402
from app.agent import runner  # noqa: E402
from app.agent.messages import grade_text  # noqa: E402
from app.agent.triage import triage_rules  # noqa: E402
from app.engine import followup, surge  # noqa: E402
from app.engine.events import apply_event, crosses  # noqa: E402
from app.engine.projection import project_all  # noqa: E402
from app.engine.severity import CONDITIONS, DOCTOR_CONDITIONS  # noqa: E402
from app.guard import GUARD  # noqa: E402
from app.models import (  # noqa: E402
    AgentRun,
    BreakdownEvent,
    DelayEvent,
    PlanStep,
    Recommendation,
    RecommendationOption,
    UrgentRequestEvent,
    utcnow,
)
from app.sim import calls  # noqa: E402
from app.sim.seed import seed_world  # noqa: E402
from app.sim.simulator import tick  # noqa: E402

for noisy in ("httpx", "httpx2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
client = TestClient(main.app)
W = main.sim


def fresh() -> None:
    seed_world(W, config.RANDOM_SEED, scheduled_day=False)
    W.auto_analyze = False
    W.calls.enabled = False
    W.ai_triage = W.autopilot = False
    GUARD.reset()


def run(minutes: float, until=None, step_s: float = 30) -> bool:
    for _ in range(int(minutes * 60 / step_s)):
        tick(W, step_s)
        project_all(W)
        if until and until():
            return True
    return False


def post_call(text: str, **where) -> dict:
    r = client.post("/sim/calls", json={"text": text, **where})
    assert r.status_code == 200, r.text
    return r.json()


def trip_of(body: dict):
    return W.trips[body["trip"]["id"]]


def kinds(trip) -> list[str]:
    return [e.kind for e in trip.timeline]


def entries(trip, kind: str) -> list:
    return [e for e in trip.timeline if e.kind == kind]


class FakeClaude:
    """Stands in for the Anthropic client: answers the triage request with a fixed JSON (or fails)."""

    def __init__(self, answer: dict | None = None, fail: bool = False) -> None:
        self.answer, self.fail, self.requests = answer, fail, []
        self.beta = NS(messages=NS(create=self.create))

    async def create(self, **kw):
        self.requests.append(kw)
        if self.fail:
            raise RuntimeError("API down")
        return NS(stop_reason="end_turn", content=[NS(type="text", text=json.dumps(self.answer))])


def with_claude(fake: FakeClaude):
    """Context: Claude 'enabled' (a key is set) and answered by the fake."""

    class _Ctx:
        def __enter__(self):
            self.prev = runner._get_client
            os.environ["ANTHROPIC_API_KEY"] = "test-key-not-used"
            runner._get_client = lambda: fake
            return fake

        def __exit__(self, *exc):
            runner._get_client = self.prev
            os.environ.pop("ANTHROPIC_API_KEY", None)

    return _Ctx()


def ai_answer(**kw) -> dict:
    base = {"severity": "serious", "condition": "seizure", "modifiers": [], "needs_doctor": False,
            "reason_en": "Ongoing seizure in a child: anticonvulsant needed soon.",
            "reason_sl": "Napad pri otroku, ki traja: potrebno je zdravilo.", "text_en": "My daughter is convulsing.",
            "address": "Celovška cesta 100, Šiška"}
    return {**base, **kw}


# --- A whole call ---------------------------------------------------------------------------------


def test_a_call_from_the_first_second_to_the_end():
    fresh()
    W.vehicles["H1"].status = "out_of_service"  # (else the helicopter may be the closest unit: doctor on board)
    body = post_call("Moj mož se je zgrudil, ne diha in se ne odziva!", address="Dunajska cesta 50, Bežigrad", caller_name="Ana Novak")
    t = trip_of(body)
    assert body["trip"]["id"] == body["id"] and "summary" in body, "the trip is also at the top level"
    c = t.call
    assert re.fullmatch(r"112-\d{4}", c.call_id) and c.kind == "112" and c.caller_name == "Ana Novak", c
    assert c.address == "Dunajska cesta 50, Bežigrad" and c.text_sl.startswith("Moj mož")
    tr = c.triage
    assert tr.by == "rules" and tr.severity == "critical" and tr.condition == "cardiac_arrest" and tr.needs_doctor, tr
    assert tr.reason_en.startswith("Cardiac arrest: ") and tr.reason_sl.startswith("Srčni zastoj: "), tr
    assert t.severity == "critical" and t.vehicle_id and t.doctor_vehicle_id, t
    assert kinds(t)[:4] == ["received", "triaged", "dispatched", "doctor_dispatched"], kinds(t)
    first = t.timeline
    assert (first[0].by, first[1].by, first[2].by) == ("caller", "rules", "engine")
    assert first[2].text.startswith(f"Dispatched {t.vehicle_id}") and first[2].vehicle_id == t.vehicle_id, first[2]
    assert "Triaged by the keyword rules (AI off: no API key)" in body["summary"]
    snap = next(x for x in client.get("/sim/state").json()["trips"] if x["id"] == t.id)
    assert snap["call"]["call_id"] == c.call_id and snap["timeline"][0]["kind"] == "received"

    assert run(180, until=lambda: any(e.kind == "closed" for e in t.timeline)), kinds(t)
    order = ["received", "triaged", "dispatched", "on_scene", "transporting", "at_hospital", "handover_done", "closed"]
    seen = kinds(t)
    assert all(k in seen for k in order + ["doctor_on_scene"]), seen
    assert [seen.index(k) for k in order] == sorted(seen.index(k) for k in order), seen
    by = {e.kind: e.by for e in t.timeline}
    assert by["on_scene"] == by["transporting"] == by["at_hospital"] == by["handover_done"] == "crew" and by["closed"] == "engine"
    at = {e.kind: e.at for e in t.timeline}
    assert abs((at["handover_done"] - at["at_hospital"]).total_seconds() / 60 - 15) <= 1, "15-min handover"
    assert at["closed"] == at["handover_done"] and t.status == "completed"
    assert len(t.timeline) <= 40


def test_unknown_address_is_refused_and_a_map_point_works():
    fresh()
    r = client.post("/sim/calls", json={"text": "Padla je.", "address": "Nekje 12"})
    assert r.status_code == 422 and "Address not found" in r.json()["detail"], r.text
    body = post_call("Babica je padla doma in ne more vstati.", lat=46.06, lon=14.52)
    t = trip_of(body)
    assert t.severity == "urgent" and t.condition == "fall" and t.call.address.startswith("Map point near"), t.call
    body = post_call("Sum na kap, povešen ustni kot.", place_id="home_vic")
    assert trip_of(body).pickup_id == "home_vic" and trip_of(body).call.address == "Vič"
    body = post_call("Krči.", address="Celovška cesta 12, Šiška")  # an area's street: near the area
    t = trip_of(body)
    p = W.places[t.pickup_id]
    assert abs(p.lat - W.places["home_siska"].lat) < 0.01 and abs(p.lon - W.places["home_siska"].lon) < 0.01


# --- Intake: Claude, and the rules when Claude is limited or fails ---------------------------------


def test_intake_with_claude_and_the_rules_when_limited():
    fresh()
    fake = FakeClaude(ai_answer(needs_doctor=True))
    with with_claude(fake):
        body = post_call("Hči ima krče že deset minut.", address="Celovška cesta 100, Šiška")
        t = trip_of(body)
        tr = t.call.triage
        assert tr.by == "ai" and tr.condition == "seizure" and tr.reason_en.startswith("Ongoing seizure"), tr
        assert t.call.text_en == "My daughter is convulsing." and t.call.text_sl.startswith("Hči ima krče")
        assert t.needs_doctor and t.doctor_vehicle_id, "a doctor asked for by the triage (serious level) is sent"
        assert fake.requests[0]["output_config"]["format"]["type"] == "json_schema"
        # Safety net: the red-flag words keep the higher level the model missed.
        fake.answer = ai_answer(severity="urgent", condition="fall")
        t2 = trip_of(post_call("Oče je padel in ne diha!", address="Zaloška cesta 3, Moste"))
        assert t2.severity == "critical" and t2.condition == "cardiac_arrest" and t2.call.triage.by == "ai", t2.call.triage
        assert "red-flag" in t2.call.triage.reason_en
        # Limited: the rules triage, the call is dispatched anyway.
        GUARD.per_window, before = 0, len(fake.requests)
        try:
            body = post_call("Sosed ima hudo bolečino v prsih.", address="Vojkova cesta 5, Bežigrad")
        finally:
            GUARD.per_window = 12
        t3 = trip_of(body)
        assert len(fake.requests) == before and t3.call.triage.by == "rules" and t3.condition == "stemi", t3.call.triage
        assert t3.vehicle_id and "AI limit reached" in body["summary"]
        # Claude fails: the rules again.
        fake.fail = True
        body = post_call("Mama se duši!", address="Jamova cesta 1, Vič")
        t4 = trip_of(body)
        assert t4.call.triage.by == "rules" and t4.condition == "choking" and "AI unavailable" in body["summary"]


def test_triage_schema_has_no_union_types():
    from app.agent.triage import TRIAGE_SCHEMA

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_parse_schema import union_params

    assert union_params(TRIAGE_SCHEMA) == 0
    assert set(TRIAGE_SCHEMA["required"]) == set(TRIAGE_SCHEMA["properties"]) and TRIAGE_SCHEMA["additionalProperties"] is False


# --- The generator --------------------------------------------------------------------------------


MODIFIER_CONDITIONS = {  # which conditions the generator gives each modifier (sim/calls._modifiers)
    "no_bystander_cpr": {"cardiac_arrest"}, "late_stroke_window": {"stroke"}, "multiple_patients": {"major_trauma"},
}


def test_every_caller_text_grades_to_its_condition():
    checked = 0
    for words, child in ((calls.CALLER_WORDS, False), (calls.CHILD_WORDS, True)):
        for condition, texts in words.items():
            for sl, en in texts:
                assert en and sl, condition
                usable = [m for m in calls.MODIFIER_WORDS if condition in MODIFIER_CONDITIONS.get(m, {condition})]
                for extra in [[], *[[m] for m in usable], usable]:
                    mods = (["child"] if child else []) + extra
                    text = sl + "".join(f" {calls.MODIFIER_WORDS[m][0]}" for m in extra)
                    if condition == "cardiac_arrest" and "no_bystander_cpr" not in extra:
                        text += f" {calls.CPR_GIVEN[0]}"
                    got = grade_text(text)
                    assert (got[0], got[1], sorted(got[2])) == (condition, CONDITIONS[condition][1], sorted(mods)), (text, got)
                    checked += 1
    for sl, _en in [*calls.REMOTE_WORDS.values(), *[(e[3], e[4]) for e in calls.REMOTE_EXTRA]]:
        assert grade_text(sl) == ("major_trauma", "serious", []), sl
    lib = intake.library()
    assert len(lib) >= 25 and sum(1 for e in lib if e[3]) >= 3, len(lib)
    assert sum(1 for e in lib if e[0] in DOCTOR_CONDITIONS) >= 3
    assert {e[0] for e in lib} >= set(c for c in CONDITIONS if c not in ("transfer", "equipment"))
    assert checked > 100


NATURAL = {  # how callers really say it (not the generator's templates): each must grade to its condition
    "cardiac_arrest": ["Mož se je zgrudil in ne diha.", "Nima utripa!", "Srce mu je zastalo.", "Ne diše več, ne odziva se.",
                       "Moja žena ne kaže znakov življenja.", "He collapsed and is not breathing."],
    "choking": ["Otrok se je zadušil s kosom jabolka.", "Nekaj mu je obtičalo v grlu.", "Zataknilo se mu je v grlu, ne more dihati.",
                "He is choking on food."],
    "catastrophic_bleeding": ["Kri brizga iz rane.", "Ne moremo ustaviti krvavitve.", "Povsod je ogromno krvi.",
                              "Hudo krvavi iz glave.", "He is bleeding a lot."],
    "anaphylaxis": ["Po piku čebele je ves otekel in težko diha.", "Pičila ga je osa, oteka mu grlo.",
                    "Huda alergijska reakcija, otekle ustnice.", "Ima alergični šok.", "Bee sting, his throat is swelling."],
    "stroke": ["Mama ne more govoriti, obraz ji je povešen na eni strani.", "Oče nerazločno govori in se mu zapleta jezik.",
               "Ne čuti leve roke in noge.", "Nenadoma je šibka na eni strani telesa.", "Zadela ga je kap.",
               "Govori zmedeno in mu visi ustnica.", "Desna stran telesa mu je ohromela.",
               "Her face is drooping and her speech is slurred."],
    "stemi": ["Stiska ga v prsih.", "Huda bolečina v prsnem košu, seva v levo roko.", "Boli ga srce in je ves poten.",
              "Pritisk na prsih.", "Crushing chest pain."],
    "breathing_difficulty": ["Ne more dihati.", "Ne dobi zraka.", "Ima hud astmatični napad.", "Lovi sapo in je moder.",
                             "Duši ga astma.", "She can't breathe."],
    "major_trauma": ["Avto je zbil pešca.", "Padel je z lestve na glavo.", "Motorist je padel, leži na cesti.",
                     "Trčenje dveh avtomobilov, voznik je ukleščen.", "Padel je s strehe.", "Hit by a car."],
    "seizure": ["Ima krče.", "Trese ga po celem telesu.", "Ima božjast.", "She is having a fit."],
    "sepsis": ["Ima sepso.", "Zastrupitev krvi, zdravnik je rekel."],
    "fracture": ["Zlomil si je nogo.", "Mislim, da je roka zlomljena.", "Broken arm."],
    "fall": ["Babica je padla doma in ne more vstati.", "Padel je po stopnicah.", "She fell in the bathroom."],
}


def test_natural_phrasings_grade_to_their_condition():
    misses = [(c, t, grade_text(t)[:2]) for c, texts in NATURAL.items() for t in texts if grade_text(t)[:2] != (c, CONDITIONS[c][1])]
    assert not misses, misses
    for t in ("Leži na tleh in se ne odziva.", "Ni pri zavesti.", "He is unconscious."):
        assert grade_text(t)[:2] == (None, "serious"), t  # unconscious, cause unknown: at least serious
    tr = triage_rules("Mama ne more govoriti, obraz ji je povešen na eni strani.", W.sim_time)
    assert (tr.severity, tr.condition) == ("serious", "stroke"), tr


def test_generated_calls_have_words_and_the_stream_is_unchanged():
    import random

    fresh()
    a, b = random.Random(7), random.Random(7)
    for _ in range(200):
        e1 = calls.build_call(W, a)
        e2, call = calls.build_call_with_record(W, b, random.Random(99))
        d1, d2 = e1.model_dump(), e2.model_dump()
        assert {k: v for k, v in d1.items() if k not in ("place_name",)} == {k: v for k, v in d2.items() if k not in ("place_name",)}
        assert call.caller_name and call.address and call.text_sl and call.text_en and call.triage.by == "rules"
        if call.kind == "112":
            assert (call.triage.condition, call.triage.severity) == (e2.condition, e2.severity), (call.text_sl, e2)
        else:
            assert call.call_id.startswith("REQ-") and call.triage.condition in ("transfer", "equipment")
    assert a.random() == b.random(), "the call stream draws exactly what it drew before"
    # Through the generator, as the app loop runs it: every call has its record and the rules' triage,
    # and its timeline runs to the end.
    W.calls.enabled = True
    for _ in range(int(4 * 3600 / 30)):
        tick(W, 30)
        main.take_calls(W)
        followup.check(W)
        project_all(W)
    generated = [t for t in W.trips.values()]
    assert len(generated) >= 10, len(generated)
    assert all(t.call is not None and t.timeline and t.timeline[0].kind == "received" for t in generated)
    for t in generated:
        if t.call.kind == "112":
            assert grade_text(t.call.text_sl)[0] == t.condition, (t.call.text_sl, t.condition)
    closed = [t for t in generated if t.status == "completed"]
    assert closed and all(kinds(t)[-2:] == ["handover_done", "closed"] for t in closed), [kinds(t) for t in closed][:3]
    assert any(t.call.kind == "hospital_request" for t in generated), "hospital requests too"


def test_generated_calls_with_ai_triage_on():
    fresh()
    W.ai_triage = True
    fake = FakeClaude(ai_answer(severity="critical", condition="anaphylaxis", needs_doctor=True))
    seen: list = []

    async def go():
        W.calls.enabled, W.calls.next_at = True, W.sim_time
        out = calls.step(W, intake=lambda s, e, c: intake.defer_generated(s, e, c, lambda _s, r: seen.append(r)))
        await asyncio.gather(*list(intake._pending))
        return out

    with with_claude(fake):
        # Force the first call to be a 112 call.
        orig = calls.build_call_with_record
        calls.build_call_with_record = lambda s, r, tr, kind=None: orig(s, r, tr, kind or "emergency")
        try:
            out = asyncio.run(go())
        finally:
            calls.build_call_with_record = orig
    assert out == [] and len(seen) == 1, (out, seen)
    t = W.trips[seen[0].affected_trip_ids[0]]
    assert t.call.triage.by == "ai" and t.severity == "critical" and t.condition == "anaphylaxis" and seen[0].generated
    assert kinds(t)[:3] == ["received", "triaged", "dispatched"]


# --- Automatic follow-up --------------------------------------------------------------------------


def test_breakdown_redispatches_a_112_call_at_once_but_not_a_scenario_job():
    fresh()
    t = trip_of(post_call("Babica ima povešen ustni kot, sum na kap.", address="Proletarska cesta 4, Moste"))
    first = t.vehicle_id
    rec = apply_event(W, BreakdownEvent(type="breakdown", vehicle_id=first, note="engine failure"), reported_by="crew")
    assert t.vehicle_id not in (None, first) and t.status == "assigned", rec.summary
    e = entries(t, "unit_replaced")
    assert e and e[-1].by == "engine" and f"{first} out of service" in e[-1].text, kinds(t)
    # A scenario job (no call record) keeps the old behaviour: released for the dispatcher/AI.
    rec = apply_event(W, UrgentRequestEvent(type="urgent_request", pickup_id="home_rudnik", severity="serious",
                                            condition="seizure", priority="emergency"))
    job = W.trips[rec.affected_trip_ids[0]]
    unit = job.vehicle_id
    apply_event(W, BreakdownEvent(type="breakdown", vehicle_id=unit))
    assert job.status == "unassigned" and job.call is None
    assert followup.check(W, force=True) == [] or job.vehicle_id is None, "the follow-up leaves it alone"
    assert job.vehicle_id is None and entries(job, "note") and "out of service" in entries(job, "note")[-1].text


def test_a_free_unit_takes_over_when_it_is_3_min_sooner():
    fresh()
    t = trip_of(post_call("Sosed ima hudo bolečino v prsih, ves je poten.", address="Slovenska cesta 10"))
    first = t.vehicle_id
    assert first in ("A1", "A2"), first  # both at the Center base: the other one is free and as close
    apply_event(W, DelayEvent(type="delay", vehicle_id=first, minutes=2, note="stuck in traffic"))
    assert entries(t, "delayed"), kinds(t)
    followup.check(W, force=True)
    assert t.vehicle_id == first, "2 min later is not worth a switch"
    apply_event(W, DelayEvent(type="delay", vehicle_id=first, minutes=20, note="stuck behind a crash"))
    done = followup.check(W, force=True)
    assert t.vehicle_id not in (None, first) and done, (t.vehicle_id, done)
    e = entries(t, "reassigned")[-1]
    assert e.by == "engine" and "min sooner than" in e.text and "released" in e.text, e
    old = W.vehicles[first]
    assert old.current_trip_id is None and not old.queue


def test_a_doctor_car_that_drops_out_is_replaced():
    fresh()
    W.vehicles["H1"].status = "out_of_service"  # an ambulance and a doctor car, not the helicopter's doctor
    t = trip_of(post_call("Oče je med večerjo izgubil zavest in ne diha več.", address="Jamova cesta 20, Vič"))
    d = t.doctor_vehicle_id
    assert d in ("D1", "D2"), d
    other = "D2" if d == "D1" else "D1"
    apply_event(W, BreakdownEvent(type="breakdown", vehicle_id=d))
    assert t.doctor_vehicle_id == other, t.doctor_vehicle_id
    assert f"Doctor car {d} out of service: doctor car {other} sent instead" in entries(t, "doctor_dispatched")[-1].text
    # Both out: none now; when one is back, the follow-up sends it.
    apply_event(W, BreakdownEvent(type="breakdown", vehicle_id=other))
    assert t.doctor_vehicle_id is None
    W.vehicles[other].status = "idle"
    followup.check(W, force=True)
    assert t.doctor_vehicle_id == other and entries(t, "doctor_dispatched")[-1].by == "engine"


# --- Proposals and the autopilot ------------------------------------------------------------------


def _run_moving(trip, vehicle_id: str, surge_option: bool = False) -> AgentRun:
    options = [RecommendationOption(title=f"Send {vehicle_id} instead", summary="", pros=[], cons=[],
                                    steps=[PlanStep(trip_id=trip.id, vehicle_id=vehicle_id)])]
    if surge_option:
        options.insert(0, RecommendationOption(title="Activate surge capacity", summary="", pros=[], cons=[], steps=[],
                                               activate_surge=True))
    rec = Recommendation(situation="test", options=options, recommended_index=0, reasoning="test")
    r = AgentRun(id=W.new_id("RUN"), trigger="test", started_at=utcnow())
    W.agent_runs.append(r)
    runner._finish(W, r, rec, engine="claude")
    return r


def test_autopilot_approves_the_recommended_option_about_a_call():
    fresh()
    t = trip_of(post_call("Kolesarja je zbil avto, leži na cesti.", address="Ižanska cesta 30, Rudnik"))
    other = next(v for v in ("A1", "A2", "A3") if v != t.vehicle_id)
    r = _run_moving(t, other)  # autopilot off: a proposal only
    assert r.status == "done" and t.vehicle_id != other
    p = entries(t, "proposal")[-1]
    assert p.run_id == r.id and p.by == "ai" and f"Send {other} instead" in p.text
    W.autopilot = True
    r2 = _run_moving(t, other)
    assert r2.status == "approved" and r2.decision["by"] == "autopilot" and t.vehicle_id == other, (r2.status, r2.steps[-1])
    a = entries(t, "approved")[-1]
    assert a.by == "engine" and a.run_id == r2.id and kinds(t)[-1] == "reassigned"
    # Contracted surge capacity stays the dispatcher's decision.
    third = next(v for v in ("A1", "A2", "A3") if v not in (other,))
    r3 = _run_moving(t, third, surge_option=True)
    assert r3.status == "done" and "left to the dispatcher" in r3.steps[-1].text and not surge.active(W)
    # The dispatcher's own approval logs "approved" by the dispatcher.
    W.autopilot = False
    r4 = _run_moving(t, third)
    resp = client.post(f"/sim/agent/runs/{r4.id}/approve", json={"option_index": 0})
    assert resp.status_code == 200, resp.text
    assert entries(t, "approved")[-1].by == "dispatcher" and t.vehicle_id == third


# --- Demo buttons ---------------------------------------------------------------------------------


def test_random_calls():
    fresh()
    # A remote call: the helicopter goes.
    name, lat, lon, _ = calls.REMOTE[0]
    t = trip_of(post_call(calls.REMOTE_WORDS[name][0], lat=lat, lon=lon, address=name))
    assert t.vehicle_id == "H1", t.timeline[2].text
    for sev in ("critical", "serious", "urgent"):
        r = client.post("/sim/admin/random-call", json={"severity": sev})
        assert r.status_code == 200, r.text
        body = r.json()
        t = trip_of(body)
        c = t.call
        assert t.severity == sev and c.kind == "112" and c.caller_name and c.address and c.text_sl and c.text_en, c
        assert c.triage.by == "rules" and body["summary"].startswith("New ") and t.vehicle_id, body["summary"]
    assert client.post("/sim/admin/random-call").status_code == 200, "no body: any severity"
    assert client.post("/live/admin/random-call", json={}).status_code == 400
    # With ai_triage on, Claude triages a random call; a second click right after gets the rules.
    W.ai_triage = True
    intake._last_ai_random.clear()
    with with_claude(FakeClaude(ai_answer(severity="critical", condition="choking", needs_doctor=True))):
        t1 = trip_of(client.post("/sim/admin/random-call", json={"severity": "critical"}).json())
        t2 = trip_of(client.post("/sim/admin/random-call", json={"severity": "critical"}).json())
    assert t1.call.triage.by == "ai" and t2.call.triage.by == "rules", (t1.call.triage.by, t2.call.triage.by)


def _incident(kind: str | None) -> dict:
    r = client.post("/sim/admin/random-incident", json={"kind": kind} if kind else {})
    assert r.status_code == 200, r.text
    return r.json()


def test_random_incidents_hit_current_operations():
    fresh()
    r = client.post("/sim/admin/random-incident", json={"kind": "fog"})
    assert r.status_code == 409 and "random call" in r.json()["detail"], r.text
    assert client.post("/live/admin/random-incident", json={}).status_code == 400

    t = trip_of(post_call("Prometna nesreča, voznik je ukleščen.", address="Ižanska cesta 80, Rudnik"))
    unit = W.vehicles[t.vehicle_id]
    assert run(3, until=lambda: unit.status == "to_pickup" and unit.busy_until is None and unit.path_to is not None)
    body = _incident("crash")
    ev = body["event"]
    assert body["kind"] == "crash" and ev["payload"]["vehicle_id"] == unit.id and ev["affected_trip_ids"][0] == t.id, body
    inc = next(reversed(W.incidents.values()))
    assert inc.kind == "road_closure" and crosses(W, unit, inc), "placed on the route it is driving"
    assert entries(t, "delayed") or entries(t, "rerouted"), kinds(t)

    body = _incident("delay")
    assert body["kind"] == "delay" and body["event"]["payload"]["vehicle_id"] in W.vehicles
    assert 10 <= body["event"]["payload"]["minutes"] <= 25

    # Fog while the helicopter has a job: released to a road unit.
    name, lat, lon, _ = calls.REMOTE[0]
    h = trip_of(post_call(calls.REMOTE_WORDS[name][0], lat=lat, lon=lon, address=name))
    assert h.vehicle_id == "H1"
    body = _incident("fog")
    assert body["kind"] == "fog" and body["event"]["payload"]["vehicle_id"] == "H1" and body["event"]["affected_trip_ids"][0] == h.id
    assert h.vehicle_id != "H1"

    body = _incident("capacity")
    assert body["kind"] == "capacity" and body["event"]["payload"]["place_id"] == "ukc"
    over = body["event"]["affected_trip_ids"][0]
    assert W.trips[over].dropoff_id == "ukc" and W.places["ukc"].capacity is not None

    body = _incident("breakdown")
    v = body["event"]["payload"]["vehicle_id"]
    assert body["kind"] == "breakdown" and W.vehicles[v].status == "out_of_service" and W.vehicles[v].type == "ambulance"
    hit = W.trips[body["event"]["affected_trip_ids"][0]]
    assert hit.call is not None and (entries(hit, "unit_replaced") or entries(hit, "note")), kinds(hit)

    # Nothing for the asked-for kind: the next best one, and the summary says so.
    body = _incident("equipment")
    assert body["kind"] != "equipment" and body["summary"].startswith("No equipment possible"), body["summary"]

    # A van with equipment on board: stranded equipment (left for the dispatcher/AI).
    assert client.post("/sim/admin/scenario/equipment_en_route").status_code == 200
    body = _incident("equipment")
    van = body["event"]["payload"]["vehicle_id"]
    stranded = W.trips[body["event"]["affected_trip_ids"][0]]
    assert body["kind"] == "equipment" and W.vehicles[van].type == "transport" and stranded.kind == "equipment"
    assert stranded.status == "unassigned", "the stranded-equipment decision stays"


# --- The vehicle card -----------------------------------------------------------------------------


def test_vehicle_card_responding_to_and_crew_roles():
    fresh()
    assert client.get("/sim/vehicles/A1").json()["responding_to"] is None
    t = trip_of(post_call("Sodelavec si je z motorno žago prerezal nogo, močno krvavi.", address="Derčeva ulica 5, Šiška"))
    card = client.get(f"/sim/vehicles/{t.vehicle_id}").json()
    assert card["responding_to"] == {"trip_id": t.id, "call_id": t.call.call_id, "severity": "critical",
                                     "condition_label": "Catastrophic bleeding", "address": "Derčeva ulica 5, Šiška",
                                     "dropoff_name": "UKC Ljubljana"}, card["responding_to"]
    doc = client.get(f"/sim/vehicles/{t.doctor_vehicle_id}").json()["responding_to"]
    assert doc["trip_id"] == t.id
    roles = {v: [m["role"] for m in client.get(f"/sim/vehicles/{v}").json()["vehicle"]["crew"]] for v in ("A1", "T1", "H1", "D1")}
    assert roles == {
        "A1": ["Medical technician (team leader)", "Medical rescuer (driver)"],
        "T1": ["Driver", "Patient attendant"],
        "H1": ["Pilot", "Co-pilot", "Emergency physician", "Nurse"],
        "D1": ["Emergency physician", "Nurse (driver)"],
    }, roles
    assert [m.role for m in W.reserve_vehicles["M1"].crew] == roles["A1"] and [m.role for m in W.reserve_vehicles["PV1"].crew] == roles["T1"]
    assert all(m.name.endswith("(fictional)") for m in W.vehicles["H1"].crew)


def test_switches_in_the_snapshot():
    fresh()
    snap = client.get("/sim/state").json()
    assert snap["ai_triage"] is False and snap["autopilot"] is False
    assert client.post("/sim/admin/ai-triage", json={"enabled": True}).json() == {"world": "sim", "ai_triage": True}
    assert client.post("/sim/admin/autopilot", json={"enabled": True}).json() == {"world": "sim", "autopilot": True}
    snap = client.get("/sim/state").json()
    assert snap["ai_triage"] is True and snap["autopilot"] is True
    assert client.get("/live/state").json()["autopilot"] is False, "per world"
    W.ai_triage = W.autopilot = False


# --- High-demand hysteresis -----------------------------------------------------------------------


def test_high_demand_alert_has_hysteresis():
    fresh()

    def alert():
        return next((a for a in W.alerts if a.kind == "high_demand"), None)

    for v in ("A1", "A2", "A3", "H1"):
        W.vehicles[v].status = "out_of_service"
    W.vehicles["A3"].status = "idle"
    W.vehicles["A3"].lat, W.vehicles["A3"].lon = W.places["sb_novo_mesto"].lat, W.places["sb_novo_mesto"].lon
    rec = apply_event(W, UrgentRequestEvent(type="urgent_request", pickup_id="home_polje", severity="serious",
                                            condition="seizure", priority="emergency"))
    t = W.trips[rec.affected_trip_ids[0]]
    assert surge.demand(W)["high"] and alert() is None, "on, but not for 5 min yet"
    W.sim_time += timedelta(minutes=surge.DEMAND_RAISE_AFTER_MIN - 1)
    project_all(W)
    assert alert() is None
    W.sim_time += timedelta(minutes=1)
    project_all(W)
    assert alert() is not None and alert().severity == "critical" and alert().trip_id == t.id
    # The trigger goes off: the alert stays (easing) for under 5 min, then clears.
    for v in ("A1", "A2"):
        W.vehicles[v].status = "idle"
    t.status = "completed"
    project_all(W)
    assert not surge.demand(W)["high"] and alert() is not None and alert().severity == "medium", alert()
    W.sim_time += timedelta(minutes=surge.DEMAND_CLEAR_AFTER_MIN - 1)
    project_all(W)
    assert alert() is not None
    W.sim_time += timedelta(minutes=1)
    project_all(W)
    assert alert() is None and not surge.alert_on(W)
    # A short blip (under 5 min) never raises it.
    for v in ("A1", "A2", "A3"):
        W.vehicles[v].status = "out_of_service"
    project_all(W)
    W.sim_time += timedelta(minutes=2)
    project_all(W)
    for v in ("A1", "A2"):
        W.vehicles[v].status = "idle"
    project_all(W)
    assert alert() is None and W.demand_high_since is None


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
