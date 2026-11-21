"""Seed a Ljubljana EMS fleet: places, vehicles and crews, plus (scheduled-day mode only) a
pre-planned day of booked trips. In live-calls mode (the default) the day starts empty and calls
come from sim/calls.py.

All coordinates are approximate and all patients are synthetic. Replace with
Epilog's data if they provide it.
"""
from __future__ import annotations

import random
from datetime import timedelta
from typing import TYPE_CHECKING

from ..engine.actions import can_serve
from ..engine.projection import LATE_ALERT_MIN, project_all, project_route, route_trip_ids
from ..engine.service_times import EQUIPMENT_PICKUP_MIN, VAN_PATIENT_PICKUP_MIN
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
    # Bases of the reserve units, outside our own fleet (approximate).
    ("base_domzale", "Ambulance station Domžale", "base", 46.1393, 14.5952),  # neighbouring region
    ("base_private", "Private ambulance base Brezovica", "base", 46.0236, 14.4128),
    ("base_private_vic", "Private ambulance base Vič", "base", 46.0430, 14.4950),
    ("base_private_vans", "Private patient transport base Moste", "base", 46.0590, 14.5480),
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
    # Doctor cars (VUZ, ZD Ljubljana): an emergency physician and a nurse who join the ambulance crew.
    ("D1", "Doctor car 1", "doctor", "zd_center"),
    ("D2", "Doctor car 2", "doctor", "zd_siska"),
]
# Reserve units: not in the world until the dispatcher requests them (an approved plan step).
# (id, name, type, base, origin)
RESERVE = [
    ("M1", "Mutual aid ambulance (Domžale)", "ambulance", "base_domzale", "mutual_aid"),
    ("P1", "Private ambulance 1", "ambulance", "base_private", "private"),
    # Contracted surge capacity (engine/surge.py): activated together by the dispatcher for a few hours.
    # P1 belongs to it too (and can still be requested for a single red call).
    ("P2", "Private ambulance 2", "ambulance", "base_private_vic", "private"),
    ("PV1", "Private van 1", "transport", "base_private_vans", "private"),
    ("PV2", "Private van 2", "transport", "base_private_vans", "private"),
    ("PV3", "Private van 3", "transport", "base_private_vans", "private"),
]

DESTINATIONS = ["ukc", "onko", "zd_center", "zd_siska", "zd_vic"]
# Scheduled day: booked pickups every 5 min over the next SCHEDULED_WINDOW_SLOTS * 5 min, due at the
# destination within the direct drive + pickup time + this slack (min). With the service times in
# engine/service_times.py a 4-hour window left one trip late; over 6 hours the default seed's day starts
# with none (other seeds may start with one or two: the local search cannot always fix them).
SCHEDULED_WINDOW_SLOTS = 72
SCHEDULED_SLACK_MIN = (15, 35)
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


def seed_world(state: WorldState, seed: int, n_trips: int = 24, scheduled_day: bool | None = None) -> None:
    """Places, fleet and crews; every unit idle at its base.

    scheduled_day (None = keep the world's current mode): True also books and pre-plans a day of
    scheduled trips on the vans (the brief's "initial plan"); False = live calls, no trips at all.
    """
    if scheduled_day is not None:
        state.scheduled_day = scheduled_day
    state.reset_simulation()

    for pid, name, kind, lat, lon in PLACES:
        state.places[pid] = Place(id=pid, name=name, kind=kind, lat=lat, lon=lon, specialty=SPECIALTY.get(pid))  # type: ignore[arg-type]
    for vid, name, vtype, base in FLEET:
        b = state.places[base]
        state.vehicles[vid] = Vehicle(id=vid, name=name, type=vtype, base_id=base, lat=b.lat, lon=b.lon)  # type: ignore[arg-type]
    for vid, name, vtype, base, origin in RESERVE:
        b = state.places[base]
        state.reserve_vehicles[vid] = Vehicle(
            id=vid, name=name, type=vtype, origin=origin, base_id=base, lat=b.lat, lon=b.lon  # type: ignore[arg-type]
        )
    equip_fleet(state, seed)  # crew, fuel, shift (own RNG: trips stay identical)
    if state.scheduled_day:
        _scheduled_day(state, random.Random(seed), n_trips)
    state.calls.reset(seed, state.name, state.sim_time)

    project_all(state)
    state.bump()


def _scheduled_day(state: WorldState, rng: random.Random, n_trips: int) -> None:
    """Book n_trips scheduled patient trips and the equipment runs, and pre-plan them on the vans."""
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
        pickup_after = state.sim_time + timedelta(minutes=5 * rng.randint(1, SCHEDULED_WINDOW_SLOTS))  # next 5 min .. 6 h
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
                due_by=pickup_after + timedelta(minutes=direct + VAN_PATIENT_PICKUP_MIN + rng.randint(*SCHEDULED_SLACK_MIN)),
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
                due_by=pickup_after + timedelta(minutes=direct + EQUIPMENT_PICKUP_MIN + slack_min),
                note=note,
            )
        )

    # Pre-plan the day greedily, like a dispatcher would: each booked trip goes to the transport
    # van where it would be least late. Vans do the whole scheduled day (stretcher patients and
    # equipment too); ambulances and the helicopter start the day free at their bases, for the
    # emergencies and urgent calls that come in during the day.
    for trip in sorted(trips, key=lambda t: t.pickup_after):
        state.trips[trip.id] = trip
        best = None
        for v in state.vehicles.values():
            ok, _ = can_serve(v, trip)
            if not ok or v.type != "transport":
                continue
            leg = project_route(state, v, route_trip_ids(v) + [trip.id])[-1]
            late = leg.delay_min >= LATE_ALERT_MIN
            score = (late, leg.delay_min, leg.eta_dropoff)
            if best is None or score < best[0]:
                best = (score, v)
        if best:
            v = best[1]
            v.queue.append(trip.id)
            trip.vehicle_id, trip.status = v.id, "assigned"
    _improve_day(state, [v for v in state.vehicles.values() if v.type == "transport"])


def _better(gain: tuple) -> bool:
    """A move is better if it removes a late trip, or cuts delay, or (no delay added) evens out the load."""
    late, delay, balance = gain
    return late > 0 or (late == 0 and delay > 0.5) or (late == 0 and delay > -0.05 and balance > 0)


def _improve_day(state: WorldState, vans: list, max_passes: int = 6) -> None:
    """Local search on the pre-planned day: move single trips to another place (any van, any
    position), or swap two trips between vans, while that lowers (late trips, total delay) or
    evens out the vans' load without adding delay. The trips themselves stay the same."""

    def cost(v) -> tuple[int, float, int]:
        legs = project_route(state, v)
        late = sum(1 for leg in legs if leg.delay_min >= LATE_ALERT_MIN)
        return late, sum(leg.delay_min for leg in legs), len(legs) ** 2

    def plus(a: tuple, b: tuple) -> tuple:
        return tuple(x + y for x, y in zip(a, b))

    def gain_of(before: tuple, after: tuple) -> tuple:
        return tuple(x - y for x, y in zip(before, after))

    costs = {v.id: cost(v) for v in vans}
    for _ in range(max_passes):
        improved = False
        for src in vans:
            for tid in list(src.queue):
                i = src.queue.index(tid)
                src.queue.pop(i)
                without = cost(src)
                best = None
                for dst in vans:
                    if not can_serve(dst, state.trips[tid])[0]:
                        continue
                    before = costs[src.id] if dst is src else plus(costs[src.id], costs[dst.id])
                    for pos in range(len(dst.queue) + 1):
                        if dst is src and pos == i:
                            continue
                        dst.queue.insert(pos, tid)
                        new = cost(dst)
                        dst.queue.pop(pos)
                        after = new if dst is src else plus(without, new)
                        gain = gain_of(before, after)
                        if _better(gain) and (best is None or gain > best[0]):
                            best = (gain, dst, pos)
                if best is None:
                    src.queue.insert(i, tid)  # no better place: put it back
                    continue
                _, dst, pos = best
                dst.queue.insert(pos, tid)
                state.trips[tid].vehicle_id = dst.id
                costs[src.id], costs[dst.id] = cost(src), cost(dst)
                improved = True
        # Swaps: exchange two trips between two vans (each takes the other's place).
        for a_i, a in enumerate(vans):
            for b in vans[a_i + 1 :]:
                for i in range(len(a.queue)):
                    for j in range(len(b.queue)):
                        ta, tb = a.queue[i], b.queue[j]
                        if not (can_serve(a, state.trips[tb])[0] and can_serve(b, state.trips[ta])[0]):
                            continue
                        a.queue[i], b.queue[j] = tb, ta
                        ca, cb = cost(a), cost(b)
                        before, after = plus(costs[a.id], costs[b.id]), plus(ca, cb)
                        if _better(gain_of(before, after)):
                            state.trips[tb].vehicle_id, state.trips[ta].vehicle_id = a.id, b.id
                            costs[a.id], costs[b.id] = ca, cb
                            improved = True
                        else:
                            a.queue[i], b.queue[j] = ta, tb
        if not improved:
            break
