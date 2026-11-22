"""Crew simulator: plays an ambulance crew (and the dispatcher's triage) through the public API.

A test and demo CLIENT, never imported by the server and never importing from `app.*`: it polls
GET {base}/{world}/state and posts what a real tablet would to POST {base}/{world}/clinical/entries,
so the real contract (unit must be the case's vehicle, idempotent client_entry_id, ...) is exercised.

    python tools/crew_sim.py --base http://localhost:8000 --world sim --interval 2

Per ER-bound patient trip that has a vehicle (nothing for equipment, other drop-offs, unassigned or
cancelled trips), seeded by random.Random(trip_id) so a run is repeatable:

    dispatcher   triage as soon as a vehicle is assigned (red for emergency, yellow for urgent)
    onboard      patient_info and severity once; vitals every VITALS_EVERY_MIN world-minutes from
                 pickup; one drug for emergencies after the first vitals; stroke_onset for a stroke
                 note; for one emergency in six an arrest with the first vitals, then rosc
    arrived      handover, then free (the engine marks a trip completed the moment it arrives, so
                 only these two entries move the ER card on to PREDAJA PACIENTA and then PROST)

Every payload carries a deterministic client_entry_id, so plan_entries is a pure function of the
snapshot and the ids already sent; a restarted simulator just gets 200 for what the server has.
"""
from __future__ import annotations

import argparse
import random
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx

# All times are WORLD minutes (the sim world runs at 5x real time).
# assumption: handover takes 10-15 min, docs/OPERATIONS_DETAILS.md
VITALS_EVERY_MIN = 5  # the first set is taken at pickup, then every 5 minutes
HANDOVER_AFTER_MIN = 10  # the crew records the handover this long after the unit arrived
FREE_AFTER_MIN = 15  # and reports itself free this long after arriving

ER_PLACE_ID = "ukc"  # the emergency department's place id (same as app.clinical.config.ER_PLACE_IDS)
ENTRIES_PATH = "/clinical/entries"
STROKE_ONSET_BEFORE_PICKUP_MIN = 40  # a stroke started this long before the crew reached the patient

# Dispatcher triage: level per trip priority (scheduled transports get none) and the problem type
# from the first keyword found in the note (lower case). Anything else is "other".
TRIAGE_LEVEL = {"emergency": "red", "urgent": "yellow"}
PROBLEM_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("stroke", ("stroke", "drooping", "slurred")),
    ("chest_pain", ("chest pain",)),
    ("resuscitation", ("not breathing", "cpr")),  # before breathing: an arrest is not "difficulty breathing"
    ("breathing_difficulty", ("breath",)),
    ("severe_head_injury", ("head injury",)),
    ("polytrauma", ("accident", "fall from height")),
)
SEVERITY = {"emergency": "orange", "urgent": "green", "scheduled": "blue"}
DRUGS = (("Sodium chloride 0.9%", "500 ml", "IV"), ("Fentanyl", "50 mcg", "IV"), ("Oxygen", "10 L/min", "mask"))
ACTIVE = {"assigned", "en_route_pickup", "onboard", "completed"}  # a trip with a vehicle that is not cancelled


def _problem_type(note: str | None) -> str:
    text = (note or "").lower()
    for problem, words in PROBLEM_KEYWORDS:
        if any(word in text for word in words):
            return problem
    return "other"


def _profile(trip_id: str) -> dict[str, Any]:
    """Everything the trip's own random stream decides, always drawn in the same order."""
    rng = random.Random(trip_id)
    return {
        "age": rng.randint(18, 90),
        "sex": rng.choice(("f", "m")),
        "arrest": rng.randrange(6) == 0,  # one in six emergencies
        "drug": rng.choice(DRUGS),
        "hr": rng.randint(68, 104),
        "sbp": rng.randint(112, 150),
        "dbp": rng.randint(68, 90),
        "spo2": rng.randint(94, 99),
        "rr": rng.randint(12, 20),
        "gcs": rng.choice((14, 15, 15)),
    }


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _vitals(trip_id: str, base: dict[str, Any], n: int) -> dict[str, int]:
    """Reading number n (1 = at pickup): the trip's baseline drifting slowly, plus a little noise from (trip, n)."""
    rng = random.Random(f"{trip_id}-vitals-{n}")
    drift = n - 1
    return {
        "hr": _clamp(base["hr"] + 2 * drift + rng.randint(-3, 3), 40, 180),
        "sbp": _clamp(base["sbp"] - drift // 2 + rng.randint(-4, 4), 80, 200),
        "dbp": _clamp(base["dbp"] - drift // 3 + rng.randint(-3, 3), 40, 120),
        "spo2": _clamp(base["spo2"] - drift // 4 + rng.randint(-1, 1), 88, 100),
        "rr": _clamp(base["rr"] + drift // 3 + rng.randint(-1, 1), 8, 30),
        "gcs": _clamp(base["gcs"] - (1 if rng.random() < 0.1 else 0), 3, 15),
    }


def _item(case_id: str, unit: str, source: str, state: str, suffix: str, entry_type: str, content: dict) -> dict:
    return {
        "path": ENTRIES_PATH,
        "json": {
            "case_id": case_id,
            "unit": unit,
            "source": source,
            "state": state,
            "type": entry_type,
            "content": content,
            "client_entry_id": f"sim-{case_id}-{suffix}",  # no observed_t: the server stamps it
        },
    }


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _plan_trip(trip: dict, now: datetime) -> list[dict]:
    case_id, vehicle = trip["id"], trip["vehicle_id"]
    status, priority = trip["status"], trip.get("priority")
    problem = _problem_type(trip.get("note"))
    out: list[dict] = []

    def crew(suffix: str, entry_type: str, content: dict) -> None:
        out.append(_item(case_id, vehicle, "simulated_crew", "heard", suffix, entry_type, content))

    if priority in TRIAGE_LEVEL:
        out.append(
            _item(case_id, "dispatch", "dispatcher", "confirmed", "triage", "triage",
                  {"level": TRIAGE_LEVEL[priority], "problem_type": problem})
        )

    if status == "onboard":
        pickup = _when(trip.get("eta_pickup")) or now  # for an onboard trip eta_pickup is when the patient was picked up
        if now >= pickup:
            profile = _profile(case_id)
            emergency = priority == "emergency"
            crew("patient_info", "patient_info", {"age_years": profile["age"], "sex": profile["sex"]})
            if priority in SEVERITY:
                crew("severity", "severity", {"value": SEVERITY[priority]})
            if problem == "stroke":
                onset = pickup - timedelta(minutes=STROKE_ONSET_BEFORE_PICKUP_MIN)
                crew("stroke_onset", "event", {"kind": "stroke_onset", "onset_t": onset.isoformat()})
            for n in range(1, (now - pickup) // timedelta(minutes=VITALS_EVERY_MIN) + 2):
                crew(f"vitals-{n}", "vitals", _vitals(case_id, profile, n))
                if n == 1 and emergency:
                    drug, dose, route = profile["drug"]
                    crew("drug", "drug_administered", {"drug": drug, "dose": dose, "route": route})
                if emergency and profile["arrest"] and n in (1, 2):
                    crew("arrest" if n == 1 else "rosc", "event", {"kind": "arrest" if n == 1 else "rosc"})

    if status == "completed":
        arrived = _when(trip.get("eta_dropoff"))
        if arrived is not None:
            if now >= arrived + timedelta(minutes=HANDOVER_AFTER_MIN):
                crew("handover", "handover", {"note": "Patient handed over to the ER team."})
            if now >= arrived + timedelta(minutes=FREE_AFTER_MIN):
                crew("free", "free", {"note": "Unit free and back in service."})
    return out


def plan_entries(snapshot: dict, sent: set[str]) -> list[dict]:
    """What to post now: `{"path", "json"}` items, in posting order, skipping ids already in `sent`.

    A pure function of the snapshot (its world time, not the wall clock) and `sent`: the caller adds
    the ids it posted to `sent`.
    """
    now = datetime.fromisoformat(snapshot["sim_time"])
    planned: list[dict] = []
    for trip in snapshot.get("trips", []):
        if (
            trip.get("kind") == "patient"
            and trip.get("dropoff_id") == ER_PLACE_ID
            and trip.get("vehicle_id")
            and trip.get("status") in ACTIVE
        ):
            planned += _plan_trip(trip, now)
    return [item for item in planned if item["json"]["client_entry_id"] not in sent]


def run_once(get: Callable[[str], dict], post: Callable[[str, dict], None], sent: set[str]) -> int:
    """One cycle: read the snapshot, post what is due, remember it in `sent`; returns how many were posted.

    A failed `post` raises (and its id stays out of `sent`, so the next cycle tries it again); a
    duplicate answered 200 is a success like any other 2xx.
    """
    posted = 0
    for item in plan_entries(get("/state"), sent):
        post(item["path"], item["json"])
        sent.add(item["json"]["client_entry_id"])
        posted += 1
    return posted


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Post simulated crew entries for ER-bound trips through the public API.")
    parser.add_argument("--base", default="http://localhost:8000", help="server address (default %(default)s)")
    parser.add_argument("--world", default="sim", help="world to follow, e.g. sim or live (default %(default)s)")
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between polls (default %(default)s)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = f"{args.base.rstrip('/')}/{args.world}"
    sent: set[str] = set()
    with httpx.Client(timeout=10.0) as client:

        def get(path: str) -> dict:
            response = client.get(f"{root}{path}")
            response.raise_for_status()
            return response.json()

        def post(path: str, body: dict) -> None:
            client.post(f"{root}{path}", json=body).raise_for_status()

        try:
            while True:
                try:
                    count = run_once(get, post, sent)
                except httpx.HTTPError as exc:  # a restarting server must not end the demo; the failure is shown, then retried
                    print(f"error: {exc}", flush=True)
                else:
                    print(f"posted {count} entries ({len(sent)} sent so far)", flush=True)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
