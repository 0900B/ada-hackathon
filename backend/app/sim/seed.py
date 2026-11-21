"""Seed a plausible morning for a Ljubljana patient-transport fleet.

All coordinates are approximate and all patients are synthetic. Replace with
Epilog's data if they provide it.
"""
from __future__ import annotations

import random
from datetime import timedelta
from typing import TYPE_CHECKING

from ..engine.actions import can_serve
from ..engine.candidates import spends_helicopter
from ..engine.projection import LATE_ALERT_MIN, LOAD_MIN, project_all, project_route, route_trip_ids
from ..models import Needs, Place, Trip, Vehicle
from ..routing import travel_minutes
from .fleet_details import equip_fleet

if TYPE_CHECKING:
    from ..state import WorldState

# (id, name, kind, lat, lon) - approximate locations, for simulation only
PLACES = [
    ("ukc", "UKC Ljubljana", "hospital", 46.0563, 14.5232),
    ("onko", "Oncology Institute Ljubljana", "hospital", 46.0538, 14.5222),
    ("dialysis", "Dialysis centre (simulated)", "hospital", 46.0610, 14.5290),
    # Regional general hospitals: where patients go when UKC cannot admit them (approximate).
    ("sb_trbovlje", "General Hospital Trbovlje (approx.)", "hospital", 46.1580, 15.0590),
    ("sb_novo_mesto", "General Hospital Novo mesto (approx.)", "hospital", 45.8030, 15.1750),
    ("zd_center", "Health centre Ljubljana Center", "health_centre", 46.0573, 14.5155),
    ("zd_siska", "Health centre Šiška", "health_centre", 46.0705, 14.4930),
    ("zd_vic", "Health centre Vič", "health_centre", 46.0445, 14.4905),
    ("base_center", "Ambulance base Center", "base", 46.0580, 14.5265),
    ("base_west", "Ambulance base West", "base", 46.0690, 14.4800),
    ("home_siska", "Šiška", "residential", 46.0735, 14.4790),
    ("home_vic", "Vič", "residential", 46.0400, 14.4820),
    ("home_moste", "Moste", "residential", 46.0560, 14.5420),
    ("home_bezigrad", "Bežigrad", "residential", 46.0720, 14.5110),
    ("home_rudnik", "Rudnik", "residential", 46.0270, 14.5300),
    ("home_crnuce", "Črnuče", "residential", 46.1020, 14.5320),
    ("home_polje", "Polje", "residential", 46.0620, 14.5900),
    ("home_domzale", "Domžale", "residential", 46.1380, 14.5940),
    ("home_medvode", "Medvode", "residential", 46.1420, 14.4130),
    ("home_vrhnika", "Vrhnika", "residential", 45.9650, 14.2950),
    ("home_grosuplje", "Grosuplje", "residential", 45.9550, 14.6580),
    ("home_skofljica", "Škofljica", "residential", 45.9840, 14.5770),
]

FLEET = [
    ("A1", "Ambulance 1", "ambulance", "base_center"),
    ("A2", "Ambulance 2", "ambulance", "base_center"),
    ("A3", "Ambulance 3", "ambulance", "base_west"),
    ("T1", "Transport 1", "transport", "base_center"),
    ("T2", "Transport 2", "transport", "base_west"),
    ("T3", "Transport 3", "transport", "base_center"),
    ("T4", "Transport 4", "transport", "base_west"),
    ("T5", "Transport 5", "transport", "base_center"),
    ("H1", "Helicopter 1", "helicopter", "ukc"),  # HNMP, based at the hospital
]

DESTINATIONS = ["ukc", "onko", "zd_center", "zd_siska", "zd_vic"]
NEEDS: list[Needs] = ["seated", "wheelchair", "stretcher"]
# Specialised hospitals are never chosen as a redirect target for an over-capacity hospital.
SPECIALTY = {"onko": "oncology", "dialysis": "dialysis"}

# Equipment transfers (prevoz opreme), not patients:
# (cargo, pickup, dropoff, priority, ready in min, slack min beyond the direct drive, note)
# Times chosen so the pre-planned day still starts with no late trips (default seed).
EQUIPMENT = [
    ("blood products", "ukc", "onko", "urgent", 20, 15, "for a transfusion"),
    ("defibrillator", "ukc", "zd_vic", "scheduled", 60, 45, "replacement unit"),
    ("lab samples", "zd_siska", "ukc", "scheduled", 75, 30, "to the central lab"),
    ("ventilator", "ukc", "sb_trbovlje", "scheduled", 180, 30, "ICU loan to a regional hospital"),
]


def seed_world(state: WorldState, seed: int, n_trips: int = 24) -> None:
    rng = random.Random(seed)
    state.reset_simulation()

    for pid, name, kind, lat, lon in PLACES:
        state.places[pid] = Place(id=pid, name=name, kind=kind, lat=lat, lon=lon, specialty=SPECIALTY.get(pid))  # type: ignore[arg-type]
    for vid, name, vtype, base in FLEET:
        b = state.places[base]
        state.vehicles[vid] = Vehicle(id=vid, name=name, type=vtype, base_id=base, lat=b.lat, lon=b.lon)  # type: ignore[arg-type]
    equip_fleet(state, seed)  # crew, fuel, shift (own RNG: trips stay identical)

    homes = [p for p in state.places.values() if p.kind == "residential"]
    trips: list[Trip] = []
    for i in range(n_trips):
        kind = rng.choices(["dialysis", "discharge", "outpatient"], weights=[3, 3, 4])[0]
        home = rng.choice(homes).id
        if kind == "dialysis":
            pickup, dropoff = home, "dialysis"
            needs = rng.choices(NEEDS, weights=[6, 4, 0])[0]
        elif kind == "discharge":
            pickup, dropoff = rng.choice(["ukc", "onko"]), home
            needs = rng.choices(NEEDS, weights=[4, 3, 3])[0]
        else:
            pickup, dropoff = home, rng.choice(DESTINATIONS)
            needs = rng.choices(NEEDS, weights=[5, 3.5, 1.5])[0]
        pickup_after = state.sim_time + timedelta(minutes=5 * rng.randint(1, 48))  # next 5 min .. 4 h
        a, b = state.places[pickup], state.places[dropoff]
        direct = travel_minutes(state, a.lat, a.lon, b.lat, b.lon, "transport")
        trips.append(
            Trip(
                id=f"TR-{i + 1:03d}",
                patient=f"P-{100 + i}",
                priority="scheduled",
                needs=needs,
                pickup_id=pickup,
                dropoff_id=dropoff,
                pickup_after=pickup_after,
                due_by=pickup_after + timedelta(minutes=direct + LOAD_MIN + rng.randint(15, 35)),
                note=kind,
            )
        )
    for cargo, pickup, dropoff, priority, ready_min, slack_min, note in EQUIPMENT:  # fixed, no rng draws
        pickup_after = state.sim_time + timedelta(minutes=ready_min)
        a, b = state.places[pickup], state.places[dropoff]
        direct = travel_minutes(state, a.lat, a.lon, b.lat, b.lon, "transport")
        trips.append(
            Trip(
                id=f"TR-{len(trips) + 1:03d}",
                kind="equipment",
                cargo=cargo,
                priority=priority,  # type: ignore[arg-type]
                needs="equipment",
                pickup_id=pickup,
                dropoff_id=dropoff,
                pickup_after=pickup_after,
                due_by=pickup_after + timedelta(minutes=direct + LOAD_MIN + slack_min),
                note=note,
            )
        )

    # Pre-plan the day greedily, like a dispatcher would: each trip goes to the
    # compatible vehicle where it would be least late. Ambulances only take stretcher
    # cases, keeping them free for emergencies. The helicopter only gets a routine trip
    # when no road vehicle can do it on time.
    for trip in sorted(trips, key=lambda t: t.pickup_after):
        state.trips[trip.id] = trip
        best = None
        for v in state.vehicles.values():
            ok, _ = can_serve(v, trip)
            if not ok or (v.type == "ambulance" and trip.needs != "stretcher"):
                continue
            leg = project_route(state, v, route_trip_ids(v) + [trip.id])[-1]
            keep_free = spends_helicopter(state, v.type, trip)
            late = leg.delay_min >= LATE_ALERT_MIN
            score = (late or keep_free, leg.delay_min, keep_free, leg.eta_dropoff)
            if best is None or score < best[0]:
                best = (score, v)
        if best:
            v = best[1]
            v.queue.append(trip.id)
            trip.vehicle_id, trip.status = v.id, "assigned"

    project_all(state)
    state.bump()
