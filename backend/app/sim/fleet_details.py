"""Synthetic operational details per vehicle: crew, fuel, distance, shift.

Crew names are fictional. Fuel falls with the distance actually driven/flown (see the
simulator) and is topped up when a vehicle is idle at its base. Uses its own random
generator so the seeded trips (and the demo scenarios) stay exactly the same.
"""
from __future__ import annotations

import random
from datetime import timedelta
from typing import TYPE_CHECKING

from ..models import CrewMember, VehicleType

if TYPE_CHECKING:
    from ..state import WorldState

# Fuel used per km, in % of a full tank (ambulance ~550 km range, van ~650 km, helicopter ~170 km).
FUEL_PCT_PER_KM: dict[str, float] = {"ambulance": 0.18, "transport": 0.15, "helicopter": 0.6, "doctor": 0.12}
LOW_FUEL_PCT = 20.0
CRITICAL_FUEL_PCT = 10.0

_FIRST = ["Ana", "Luka", "Maja", "Nejc", "Tina", "Jure", "Eva", "Rok", "Nina", "Matej", "Sara", "Blaž", "Petra", "Gal", "Urša", "Žan"]
_LAST = ["Novak", "Horvat", "Kranjc", "Zupan", "Potočnik", "Kos", "Vidmar", "Golob", "Turk", "Kralj", "Zajc", "Božič"]

_ROLES: dict[str, list[str]] = {
    # Slovenian NRV crew: a medical technician leads, a medical rescuer drives. A doctor comes in a
    # separate doctor car (VUZ: an emergency physician and a nurse who drives) when the call needs one.
    # The same crews for mutual-aid and contracted (private) ambulances and vans.
    "ambulance": ["Medical technician (team leader)", "Medical rescuer (driver)"],
    "transport": ["Driver", "Patient attendant"],
    "helicopter": ["Pilot", "Emergency physician", "Nurse"],
    "doctor": ["Emergency physician", "Nurse (driver)"],
}
# Extra crew drawn from a second stream after everyone else, so the first stream (and the fuel and
# shifts it also draws) stays exactly as it was: (vehicle type, role, position in the crew list).
_EXTRA_ROLES = [("helicopter", "Co-pilot", 1)]


def _name(rng: random.Random, used: set[str]) -> str:
    while True:
        name = f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
        if name not in used:
            used.add(name)
            return name


def equip_fleet(state: WorldState, seed: int) -> None:
    """Crews, fuel and shifts for the fleet and for the reserve units (mutual aid, private)."""
    rng = random.Random(seed + 7919)  # separate stream: must not change the seeded trips
    used: set[str] = set()
    fleet = [*state.vehicles.values(), *state.reserve_vehicles.values()]
    for v in fleet:
        v.crew = [CrewMember(name=f"{_name(rng, used)} (fictional)", role=role) for role in _ROLES.get(v.type, ["Driver"])]
        v.fuel_pct = float(rng.randint(45, 95))
        v.km_today = 0.0
        v.shift_end = state.sim_time.replace(minute=0, second=0) + timedelta(hours=rng.choice([6, 8, 10]))
    extra = random.Random(seed + 104729)
    for v in fleet:
        for vtype, role, pos in _EXTRA_ROLES:
            if v.type == vtype:
                v.crew.insert(pos, CrewMember(name=f"{_name(extra, used)} (fictional)", role=role))


def fuel_rate(vehicle_type: VehicleType | str) -> float:
    return FUEL_PCT_PER_KM.get(vehicle_type, 0.18)
