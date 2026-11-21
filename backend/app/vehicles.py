"""Vehicle card data: crew, fuel, capabilities, upcoming stops with ETAs and the road geometry
of every remaining leg (for highlighting the vehicle's route on the map)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .engine.projection import project_route
from .roads import ROADS, key
from .routing import flies, resolve_route
from .sim.fleet_details import LOW_FUEL_PCT, fuel_rate

if TYPE_CHECKING:
    from .models import Vehicle
    from .state import WorldState

CAPABILITIES = {
    "ambulance": ["Emergencies", "Stretcher, wheelchair and seated patients", "Equipment transfers"],
    "transport": ["Seated and wheelchair patients", "Equipment transfers", "No emergencies or stretchers"],
    "helicopter": ["Emergencies and long transfers", "Stretcher patients", "No equipment transfers", "Grounded by fog"],
}


def _geometry(
    state: WorldState, v: Vehicle, a: tuple[float, float], b: tuple[float, float], first: bool
) -> tuple[list[list[float]], bool]:
    """The leg a -> b as a polyline (the remaining road path if v is driving it, else the cached
    road route, around closures where a detour is known), and whether it is a detour."""
    if flies(v.type):
        return [list(a), list(b)], False
    if first and v.path_to is not None and tuple(v.path_to) == key(*b):
        remaining = state.vehicle_path(v)
        if remaining:
            return remaining, bool(v.path_avoid) and ROADS.detour(*v.path_from, *v.path_to, v.path_avoid) is not None
    route, is_detour = resolve_route(state, a[0], a[1], b[0], b[1])
    if route is None:
        return [list(a), list(b)], False
    step = max(1, len(route.points) // 80)
    pts = route.points[::step] + [route.points[-1]]
    return [[round(lat, 5), round(lon, 5)] for lat, lon in pts], is_detour


def vehicle_detail(state: WorldState, v: Vehicle) -> dict[str, Any]:
    places = state.places
    stops: list[dict[str, Any]] = []
    legs: list[list[list[float]]] = []
    detour_legs: list[int] = []  # indexes into legs that go around a road closure

    def add_leg(geometry: tuple[list[list[float]], bool]) -> None:
        if geometry[1]:
            detour_legs.append(len(legs))
        legs.append(geometry[0])
    cur = (v.lat, v.lon)
    first = True
    if v.status != "out_of_service":
        for leg in project_route(state, v):
            trip = state.trips[leg.trip_id]
            label = getattr(trip, "label", None) or trip.patient
            if not (trip.status == "onboard" and trip.vehicle_id == v.id):
                p = places[trip.pickup_id]
                add_leg(_geometry(state, v, cur, (p.lat, p.lon), first))
                first, cur = False, (p.lat, p.lon)
                stops.append({"kind": "pickup", "trip_id": trip.id, "label": label, "priority": trip.priority,
                              "place": p.name, "lat": p.lat, "lon": p.lon, "eta": leg.eta_pickup})
            d = places[trip.dropoff_id]
            add_leg(_geometry(state, v, cur, (d.lat, d.lon), first))
            first, cur = False, (d.lat, d.lon)
            stops.append({"kind": "dropoff", "trip_id": trip.id, "label": label, "priority": trip.priority,
                          "place": d.name, "lat": d.lat, "lon": d.lon, "eta": leg.eta_dropoff, "delay_min": leg.delay_min})
        base = places.get(v.base_id)
        if base and stops:
            add_leg(_geometry(state, v, cur, (base.lat, base.lon), first))
            stops.append({"kind": "base", "trip_id": None, "label": None, "priority": None,
                          "place": base.name, "lat": base.lat, "lon": base.lon, "eta": None})

    current = state.trips.get(v.current_trip_id) if v.current_trip_id else None
    range_km = v.fuel_pct / fuel_rate(v.type) if fuel_rate(v.type) else None
    return {
        "vehicle": {**v.model_dump(mode="json"), "path": state.vehicle_path(v)},
        "base": places[v.base_id].name if v.base_id in places else v.base_id,
        "capabilities": CAPABILITIES.get(v.type, []),
        "fuel": {"pct": round(v.fuel_pct, 1), "range_km": round(range_km) if range_km is not None else None,
                 "low": v.fuel_pct < LOW_FUEL_PCT},
        "current_trip": current.model_dump(mode="json") if current else None,
        "stops": [{**s, "eta": s["eta"].isoformat() if s.get("eta") else None} for s in stops],
        "legs": legs,
        "detour_legs": detour_legs,
    }
