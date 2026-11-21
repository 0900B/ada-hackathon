"""Official Slovenian traffic events (DARS / promet.si) from the National Access Point (NAP).

Access needs a free NAP account with approved dataset permissions (www.nap.si):
OAuth2 password grant at /uc/user/token, then GET /data/<dataset> with a bearer token.
The data is DATEX II 2.3 XML. The parser is namespace-agnostic and searches each
situationRecord for its type, coordinates and public comment, so it tolerates
profile differences. It has not yet been checked against live NAP data.
"""
from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any

import httpx

from ..models import Incident, IncidentKind, utcnow
from .tomtom import replace_provider_incidents

if TYPE_CHECKING:
    from ..state import WorldState

TOKEN_URL = "https://b2b.nap.si/uc/user/token"
DATA_URL = "https://b2b.nap.si/data/{dataset}"
PROVIDER = "promet.si"
BBOX = (45.97, 14.35, 46.16, 14.72)  # min lat, min lon, max lat, max lon (Ljubljana area)
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

CLOSURE_TYPES = {"roadClosed", "carriagewayClosures", "closedPermanentlyForTheWinter", "useOfSpecifiedCarriagewayOrLaneAllowed"}
LANE_TYPES = {"laneClosures", "narrowLanes", "singleAlternateLineTraffic", "contraflow", "hardShoulderRunningInOperation"}
CONGESTION_RECORDS = {"AbnormalTraffic", "MaintenanceWorks", "ConstructionWorks", "Roadworks",
                      "VehicleObstruction", "GeneralObstruction", "AnimalPresenceObstruction",
                      "InfrastructureDamageObstruction", "EnvironmentalObstruction"}

READABLE = {
    "Accident": "Accident",
    "RoadOrCarriagewayOrLaneManagement": "Road or lane closure",
    "AbnormalTraffic": "Congestion",
    "MaintenanceWorks": "Roadworks",
    "ConstructionWorks": "Construction works",
    "Roadworks": "Roadworks",
    "VehicleObstruction": "Vehicle obstruction",
    "GeneralObstruction": "Obstruction on the road",
    "AnimalPresenceObstruction": "Animals on the road",
    "InfrastructureDamageObstruction": "Road damage",
    "EnvironmentalObstruction": "Obstruction (environment)",
}

_token: dict[str, Any] = {"access": None, "expires": 0.0}


def nap_credentials() -> tuple[str, str] | None:
    user, pw = os.getenv("NAP_USERNAME"), os.getenv("NAP_PASSWORD")
    return (user, pw) if user and pw else None


def nap_datasets() -> list[str]:
    return [d.strip() for d in os.getenv("NAP_DATASETS", "b2b.events").split(",") if d.strip()]


async def _get_token(client: httpx.AsyncClient, force: bool = False) -> str:
    if not force and _token["access"] and time.time() < _token["expires"] - 300:
        return _token["access"]
    creds = nap_credentials()
    if not creds:
        raise RuntimeError("NAP_USERNAME / NAP_PASSWORD not set")
    try:
        r = await client.post(
            TOKEN_URL,
            data={"grant_type": "password", "username": creds[0], "password": creds[1]},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except httpx.HTTPError as e:
        raise RuntimeError(f"NAP token request failed ({type(e).__name__})") from None
    if r.status_code != 200:
        raise RuntimeError(f"NAP login returned HTTP {r.status_code} (check credentials and approval)")
    body = r.json()
    _token["access"] = body["access_token"]
    _token["expires"] = time.time() + float(body.get("expires_in", 3600))
    return _token["access"]


async def _get_dataset(client: httpx.AsyncClient, dataset: str) -> bytes:
    for attempt in (0, 1):
        token = await _get_token(client, force=attempt == 1)
        try:
            r = await client.get(DATA_URL.format(dataset=dataset), headers={"Authorization": f"bearer {token}"})
        except httpx.HTTPError as e:
            raise RuntimeError(f"NAP {dataset} request failed ({type(e).__name__})") from None
        if r.status_code == 401 and attempt == 0:
            continue  # token expired or revoked: log in again once
        if r.status_code == 403:
            raise RuntimeError(f"NAP {dataset}: HTTP 403 (dataset permission not approved yet?)")
        if r.status_code != 200:
            raise RuntimeError(f"NAP {dataset} returned HTTP {r.status_code}")
        return r.content
    raise RuntimeError(f"NAP {dataset}: still unauthorised after re-login")


# --- DATEX II parsing ----------------------------------------------------------------


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_text(el: ET.Element, names: set[str]) -> str | None:
    for sub in el.iter():
        if _local(sub.tag) in names and sub.text and sub.text.strip():
            return sub.text.strip()
    return None


def _coordinates(rec: ET.Element) -> tuple[float, float] | None:
    lat = lon = None
    for sub in rec.iter():
        name = _local(sub.tag)
        try:
            if name == "latitude" and lat is None:
                lat = float(sub.text or "")
            elif name == "longitude" and lon is None:
                lon = float(sub.text or "")
        except ValueError:
            continue
        if lat is not None and lon is not None:
            return lat, lon
    return None


def _comment(rec: ET.Element) -> str | None:
    """Public comment, English preferred, else Slovenian/any."""
    scope = next((s for s in rec.iter() if _local(s.tag) == "generalPublicComment"), rec)
    texts: dict[str, str] = {}
    for sub in scope.iter():
        if _local(sub.tag) == "value" and sub.text and sub.text.strip():
            texts.setdefault((sub.get("lang") or "").lower()[:2], sub.text.strip())
    return texts.get("en") or texts.get("sl") or next(iter(texts.values()), None)


def classify(record_type: str, rec: ET.Element) -> IncidentKind | None:
    if record_type == "Accident":
        return "accident"
    if record_type == "RoadOrCarriagewayOrLaneManagement":
        mgmt = _first_text(rec, {"roadOrCarriagewayOrLaneManagementType"})
        if mgmt in CLOSURE_TYPES:
            return "road_closure"
        if mgmt in LANE_TYPES:
            return "congestion"
        return None
    if record_type in CONGESTION_RECORDS:
        return "congestion"
    return None  # weather/road conditions, speed limits, rerouting advice: not used for routing


def parse_datex(xml_bytes: bytes) -> list[Incident]:
    root = ET.fromstring(xml_bytes)
    incidents = []
    for rec in root.iter():
        if _local(rec.tag) != "situationRecord":
            continue
        record_type = _local(rec.get(XSI_TYPE, "")).split(":")[-1]
        if (_first_text(rec, {"validityStatus"}) or "active") == "suspended":
            continue
        kind = classify(record_type, rec)
        coords = _coordinates(rec)
        if kind is None or coords is None:
            continue
        lat, lon = coords
        if not (BBOX[0] <= lat <= BBOX[2] and BBOX[1] <= lon <= BBOX[3]):
            continue
        text = _comment(rec) or READABLE.get(record_type, record_type)
        incidents.append(
            Incident(
                id=f"PR-{rec.get('id', len(incidents))}"[:40],
                kind=kind,
                description=f"{text[:140]} [promet.si]",
                lat=lat,
                lon=lon,
                radius_m=400.0 if kind == "road_closure" else 300.0,
                created_at=utcnow(),
                source="live",
                provider=PROVIDER,
            )
        )
    return incidents


async def fetch_events(state: WorldState, client: httpx.AsyncClient) -> None:
    fresh: dict[str, Incident] = {}
    for dataset in nap_datasets():
        try:
            items = parse_datex(await _get_dataset(client, dataset))
        except ET.ParseError:
            raise RuntimeError(f"NAP {dataset}: response is not valid XML") from None
        fresh.update((i.id, i) for i in items)
    replace_provider_incidents(state, PROVIDER, fresh)
