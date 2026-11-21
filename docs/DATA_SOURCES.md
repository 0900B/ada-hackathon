# Live data sources: research results

Tested 2026-11-21 from a laptop in Ljubljana. Each request was made only a few times. One real sample response per working source is in `research/samples/`; re-fetch them with `bash research/test_sources.sh`. The brief is in `docs/CHALLENGE.md`.

Already used in the repo: Open-Meteo, MET Norway, TomTom, NAP (`backend/app/fetchers/`). Everything else below is new.

## Summary

| # | Source | Provides | Key? | Status | Supports |
|---|---|---|---|---|---|
| 1 | aviationweather.gov METAR/TAF | Airport visibility, ceiling, weather codes (LJLJ Brnik, LJMB Maribor, LJPZ Portorož) | No | **WORKS** | Fog: helicopter grounded |
| 2 | Open-Meteo | Gridded forecast/current visibility, low cloud, gusts; several points per call | No | **WORKS** (unreachable from Railway, see repo) | Fog/wind at any point on a flight path |
| 3 | ARSO observations XML | 20 Slovenian stations: visibility (km), weather code (incl. *megla*), wind | No | **WORKS** | Fog, official Slovenian source |
| 4a | promet.si public Atom feed | ~180 live road events (works, jams, breakdowns, obstacles), Slovenian text | No | **WORKS** (no coordinates) | Road closures, delays |
| 4b | promet.si `b2b.dogodki.json/geojson` | Events with coordinates | Yes | **NEEDS APPROVAL** (401/403; now behind NAP) | Road closures |
| 5 | NAP Slovenija (b2b.nap.si) | DATEX II events, road works, travel times, DARS weather stations, counters | Account + per-dataset approval | **NEEDS APPROVAL** | Closures, delays, road weather |
| 6 | TomTom Traffic Incidents v5 | Incidents with geometry, delay, iconCategory (incl. fog, road closed, broken-down vehicle) | `TOMTOM_API_KEY` | **NEEDS KEY** (not in local `.env`; backend already supports it) | Closures, delays |
| 7 | openrouteservice | Directions with `avoid_polygons`, matrix, isochrones | `ORS_API_KEY` | **NEEDS KEY** (docs verified) | Rerouting around a closure |
| 8 | OSRM public demo | Road route + duration/distance table | No | **WORKS** (light use only) | Ambulance road travel times |
| 9 | Overpass API (OSM) | Hospitals (175) and helipads (128) in the SI bbox | No | **WORKS** via mirror (main server 502) | Realistic scenario: hospitals, landing sites |
| 10 | Nominatim | Geocoding of Slovenian place names | No | **WORKS** (1 req/s) | Place names in Slovenian driver messages |
| 11 | OpenAI transcription / Web Speech `sl-SI` | Slovenian speech-to-text | `OPENAI_API_KEY` / none | Documented only | Voice input for the AI assistant |
| 12 | Twilio | SMS | `TWILIO_*` | Documented only | Notify crews/hospital |
| 13 | Anthropic API | LLM | `ANTHROPIC_API_KEY` | Documented only (backend already uses it) | Slovenian message → event |

---

## 1. aviationweather.gov METAR/TAF: WORKS
- **Endpoints:** `https://aviationweather.gov/api/data/metar?ids=LJLJ,LJMB,LJPZ&format=json`, `https://aviationweather.gov/api/data/taf?ids=LJLJ&format=json`
- **Key:** none. US NOAA public service; send a descriptive User-Agent and keep the rate low.
- **Fields:** `visib` (statute miles, `"6+"` = ≥10 km), `clouds[].cover/base` (ft), `fltCat` (VFR/MVFR/IFR/LIFR), `rawOb` (contains `FG`/`BR` for fog/mist), `obsTime`. TAF: `fcsts[]` with `timeFrom/timeTo`, `visib`, `wxString`.
- **Sample at test time:** LJLJ/LJMB VFR; LJPZ **MVFR**, 6000 m with 2000 m to the NW.
- **Supports:** the **fog** event. LJLJ (Brnik) is the HEMS base, so `fltCat in (IFR, LIFR)` or `FG` in `rawOb` there means the helicopter is grounded. TAF gives the next few hours, which tells you how long the grounding will last.

## 2. Open-Meteo: WORKS
- **Endpoint:** `https://api.open-meteo.com/v1/forecast?latitude=46.05&longitude=14.51&hourly=visibility,cloud_cover_low,wind_gusts_10m`
- **Multiple points:** yes. Comma-separate `latitude=46.05,46.22,46.48&longitude=14.51,14.46,15.69` and the API returns a JSON array, one object per point (tested with `current=`).
- **Key:** none. Free for non-commercial use, ~10k calls/day; attribution **CC BY 4.0** ("Weather data by Open-Meteo.com").
- **Fields:** `visibility` (m), `cloud_cover_low` (%), `wind_gusts_10m` (km/h), `weather_code` (WMO; 45/48 = fog).
- **Caveat:** `backend/app/fetchers/weather.py` notes that api.open-meteo.com is unreachable from Railway; MET Norway is the fallback there.
- **Supports:** fog/wind **along a helicopter flight path**. Sample a few points between the base and the destination.

## 3. ARSO current observations: WORKS
- **Endpoint:** `https://meteo.arso.gov.si/uploads/probase/www/observ/surface/text/sl/observation_si_latest.xml` (20 main stations). There's a larger automatic-station feed at `.../observationAms_si_latest.xml` (~800 KB). Feed index: `https://meteo.arso.gov.si/met/sl/service/`; XML docs: `https://meteo.arso.gov.si/uploads/meteo/help/sl/xml_service.html`.
- **Key:** none. Attribution required: **"Vir: ARSO"**.
- **Fields per `<metData>`:** `domain_title`, `domain_lat/lon`, `vis_value` + `vis_unit` (km; blank at some stations), `wwsyn_shortText` / `wwsyn_icon` (present weather, e.g. *megla* = fog), `nn_shortText` (cloudiness), `ff_val_kmh`, `ffmax_val_kmh`, `t`, `tsValid_issued_UTC`.
- **Encoding:** UTF-8. Parse as UTF-8 explicitly (Windows Python defaults to cp1250).
- **Supports:** fog, from the official Slovenian source. Good for the pitch ("Vir: ARSO").

## 4. promet.si (DARS)
The URLs in the brief are dead: `https://www.promet.si/portal/sl/etd.aspx` and `.../B2B_full.pdf` both return 404. The developer page is now **https://www.promet.si/sl/vkljucki-razvijalci**. It documents DATEX II 2.3 profiles (Events, Geodevices, Truck parking) and points B2B users to NAP. Terms: you must credit the source and copyright on any product using the data.

### 4a. Public Atom feed: WORKS (no coordinates)
- **Endpoint:** `https://www.promet.si/dc/PROMET.ROADEVENTS.PP.RSS.SL`
- **Key:** none.
- **Fields per `<entry>`:** `title` (e.g. `A2-E61, Karavanke - Ljubljana: Okvara vozila`), `content` (Slovenian free text: road, section, direction, delay, length), `category@term` (*Delo* 157, *Ovire* 7, *Zastoj* 6, *Okvara vozila* 2, *Vreme* 2, *Tovornjaki* 2 at test time), `updated`, `id`.
- **No coordinates.** Locate events with Nominatim on the place names in the text, or with the LLM.
- **Supports:** road closures and delays (*zamuda: 5 min* is in the text). It's also real Slovenian text to show the AI assistant parsing.

### 4b. `b2b.dogodki.json` / `.geojson`: NEEDS APPROVAL
- `https://www.promet.si/dc/b2b.dogodki.json?...` → **401**, `.xml` → **403**. These feeds are no longer free or anonymous; access now goes through NAP (section 5). I didn't try to get around the auth.

## 5. NAP Slovenija: NEEDS APPROVAL
- **Portal:** https://www.nap.si/sl/datasets, DATEX II profiles at https://nap.si/sl/datexii, access guide (PDF) at https://nap.si/resources/doc/nap_B2B_sl.pdf
- **Auth (from the guide):** OAuth2 password grant. `POST https://b2b.nap.si/uc/user/token` with `grant_type=password&username=<email>&password=<pw>` (form-encoded) returns `access_token` (valid ~24 h) and `refresh_token`. Then `GET https://b2b.nap.si/data/<code>` with header `Authorization: bearer <token>`. Refresh with `grant_type=refresh_token`. Credentials are your **NAP login email + password** (not a client id/secret). This matches `backend/app/fetchers/nap.py` (`NAP_USERNAME`, `NAP_PASSWORD`, `NAP_DATASETS`).
- **Relevant datasets** (`https://nap.si/sl/datasets_details?id=<id>`; some IDs come from a partial page read, so check them):
  - Traffic events: *Prometni dogodki* (DATEX II v3.3 `25d05e67-…`, Slovenian JSON `fea346db-…`, also v2.3/GeoJSON/RSS), code `b2b.events`
  - Road works: *Delo na cesti* (DATEX II v3.3 `c579c4e6-…`, Slovenian JSON `ae40727b-…`), code `b2b.roadworks`
  - Travel times: *Potovalni časi AC* (DATEX II v3.3 `175740ef-…`); FCD segment state (MZIE/NCUP, `098a555a-…`)
  - Road weather: *DARS vremenske postaje* (v2.3 `3ca57351-…`, v3.3 `2b46144b-…`), also DRSI stations; wind code `b2b.wind`
  - Traffic counters: *Števci prometa* (v3.3 `8dc7e1df-…`, GeoJSON `73680a97-…`)
- **Registration steps:**
  1. Go to https://www.nap.si → user icon (top right) → **Registracija**. Fill in the form and confirm by email.
  2. Log in and open your profile (https://nap.si/sl/editprofile). Under the list of datasets, tick **"zaprosi"** for each one you want: Prometni dogodki, Delo na cesti, DARS vremenske postaje, Potovalni časi.
  3. At the bottom, choose a purpose (e.g. *osebni* or educational/hackathon), write a short description (≤100 chars, e.g. "AdaHack 2026 – študentski prototip načrtovanja reševalnih prevozov"), pick a period (1 month), accept the terms, then click **"Podaj zahtevek za uporabo podatkov"**.
  4. A NAP officer approves each request manually; the status appears in the "Pravice" column. **No approval time is stated, so it may not arrive before Sunday 11:00.**
  5. Put the email and password in Railway variables or a local `.env` as `NAP_USERNAME` / `NAP_PASSWORD`.
  - Support: ncup.mzie@gov.si, 01 4788 510.
- **Terms/fees:** not stated on the pages I could read. The promet.si terms require crediting the source.

## 6. TomTom Traffic Incident Details v5: NEEDS KEY
- **Endpoint:** `GET https://api.tomtom.com/traffic/services/5/incidentDetails?key=…&bbox=minLon,minLat,maxLon,maxLat&fields={incidents{type,geometry{type,coordinates},properties{iconCategory,magnitudeOfDelay,delay,from,to,roadNumbers}}}&language=en-GB`
- **Bounding box limit: 10,000 km².** The whole of Slovenia (13.37,45.42,16.61,46.88 ≈ 40,000 km²) is **too large**. Use the Ljubljana box (14.35,45.97,14.72,46.16, as the backend does) or split into tiles.
- **Fields:** `iconCategory` (1 accident, **2 fog**, 6 jam, 7 lane closed, **8 road closed**, 9 road works, **14 broken-down vehicle**), `magnitudeOfDelay` (0–4), `delay` (s vs free flow), `from`/`to`, `roadNumbers`, GeoJSON `geometry`.
- **Key:** sign up at https://my.tomtom.com/ (no credit card). **Free: 2,500 incident requests/month**; free tier is for evaluation. `research/test_sources.sh` tests it if `TOMTOM_API_KEY` is in `.env`.

## 7. openrouteservice: NEEDS KEY
- **Endpoint:** `POST https://api.openrouteservice.org/v2/directions/driving-car/geojson`, header `Authorization: <ORS_API_KEY>`.
- **`avoid_polygons`:** supported in `options`. Body: `{"coordinates":[[lon,lat],[lon,lat]],"options":{"avoid_polygons":{"type":"Polygon","coordinates":[[[...]]]}}}` ([docs](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/routing-options)).
- **Hosted limits** ([restrictions](https://giscience.github.io/openrouteservice/hosted-api-restrictions)): avoid polygon ≤200 km² and ≤20 km across; route ≤150 km when using avoid areas; matrix ≤3,500 cells (50×50).
- **Quota (free Standard plan, [plans](https://openrouteservice.org/plans/)):** directions 2,000/day and 40/min; matrix 500/day and 40/min; isochrones 500/day and 20/min. The daily window starts at your first request.
- **Key:** create a HeiGIT account at https://account.heigit.org and get the key from the dashboard (the signup page is JS-only, so the exact flow is unverified). Attribution: "© openrouteservice.org by HeiGIT | Map data © OpenStreetMap contributors".
- **Supports:** **road closure → reroute**. Draw a small polygon around the closed segment and request a new route.

## 8. OSRM public demo: WORKS
- **Endpoints:** `https://router.project-osrm.org/route/v1/driving/14.5225,46.0569;14.4688,46.0754?overview=simplified&geometries=geojson` (6.7 km, 567 s), `https://router.project-osrm.org/table/v1/driving/<3 points>?annotations=duration,distance`
- **Key:** none. Usage policy: demo server only, **light use** (≤1 req/s), no heavy or production traffic, may go down. No traffic awareness and no avoid areas.
- **Supports:** real road distances and durations for ambulances (the backend currently uses straight line × 1.35). Precompute a matrix between hospital and task locations once and cache it.

## 9. Overpass API: WORKS (via mirror)
- **Query:** `[out:json][timeout:50][bbox:45.42,13.37,46.88,16.61];(nwr["amenity"="hospital"];nwr["aeroway"="helipad"];);out center tags;`
- **Servers:** `overpass-api.de` returned **502** repeatedly; `overpass.private.coffee` timed out; **`https://maps.mail.ru/osm/tools/overpass/api/interpreter` worked** (~18 s).
- **Result:** 175 `amenity=hospital`, 128 `aeroway=helipad`. **Noisy:** the bbox includes AT/IT/HR, many health centres (*zdravstveni dom*) and private clinics are tagged as hospitals, and many helipads have no name. Filter by name or curate by hand.
- **Terms:** ODbL, credit "© OpenStreetMap contributors".
- **Supports:** a realistic scenario with real hospital and landing-site coordinates (e.g. *LJHJ, heliport Jesenice*). Fetch once and commit the cleaned list; don't call it live.

## 10. Nominatim: WORKS
- **Endpoint:** `https://nominatim.openstreetmap.org/search?q=Vransko&format=jsonv2&limit=1&countrycodes=si`
- "Koseze, Ljubljana" → 46.0713, 14.4696; "Vransko" → 46.2433, 14.9503.
- **Policy:** **max 1 request/second**, a **descriptive User-Agent is required**, cache results, no bulk geocoding. ODbL attribution.
- **Supports:** place names in Slovenian messages ("*obstal sem pri Vranskem*") → coordinates; also locating promet.si events.

## 11. Slovenian speech-to-text: documented only
- **OpenAI transcription** (`POST https://api.openai.com/v1/audio/transcriptions`, models `whisper-1` / `gpt-4o-transcribe`, `language=sl`). Key: https://platform.openai.com/api-keys. Paid per minute.
- **Chrome Web Speech API**: `webkitSpeechRecognition` with `lang='sl-SI'`. Free, no key, browser-only (Chrome sends the audio to Google), needs a network connection. Good enough for a live demo.

## 12. Twilio SMS: documented only
- Trial account at https://www.twilio.com/try-twilio gives `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and a trial number `TWILIO_FROM`. **Trial can only send to verified numbers** and prefixes messages with a trial note. Fine for texting a teammate's phone on stage.

## 13. Anthropic API: documented only
- Key at https://console.anthropic.com/ → `ANTHROPIC_API_KEY`. The backend already uses it (`AGENT_MODEL`, default `claude-sonnet-5-5`).

## Candidates (untested)
- **NIJZ data portal** (https://podatki.nijz.si): national health statistics, including hospital beds. Annual aggregates only, so it's useful for realistic *capacity* numbers, not live admissions. No live hospital-capacity feed was found.
- **HEMS rules / bases:** helicopters are based at Brnik (LJLJ) and Maribor (LJMB) and must respond within 15 min ([gov.si](https://gov.si/en/news/2022-10-06-revised-plan-for-activation-and-use-of-state-aircraft-for-emergency-tasks-of-protection-rescue-and-assistance), [Pravilnik HNMP, UL 81/2016](https://www.uradni-list.si/glasilo-uradni-list-rs/vsebina/2016-01-3442/pravilnik-o-pogojih-izvajanja-helikopterske-nujne-medicinske-pomoci)). Use these as the helicopter depots.
- **ARSO automatic stations** `observationAms_si_latest.xml`: many more stations, for denser fog coverage.
- **DARS road weather stations** via NAP: road-surface fog and visibility on motorways.
- **MET Norway Locationforecast** (already in the backend): fog-area fraction for any point.

## Key names
Put these in a local `.env` or Railway variables. Never commit them. `backend/.env.example` already lists `ANTHROPIC_API_KEY`, `TOMTOM_API_KEY`, `NAP_USERNAME`, `NAP_PASSWORD`, `NAP_DATASETS`.
```
ANTHROPIC_API_KEY=   # https://console.anthropic.com/
TOMTOM_API_KEY=      # https://my.tomtom.com/ (2,500 incident calls/month free)
ORS_API_KEY=         # https://account.heigit.org (openrouteservice)
NAP_USERNAME=        # NAP login email (www.nap.si, datasets must be approved)
NAP_PASSWORD=
OPENAI_API_KEY=      # https://platform.openai.com/api-keys (only for Whisper STT)
TWILIO_ACCOUNT_SID=  # https://www.twilio.com/try-twilio
TWILIO_AUTH_TOKEN=
TWILIO_FROM=
```

## Ideas: what live data enables
- **Brnik fog → helicopter grounded automatically.** If the LJLJ METAR is IFR/LIFR or contains `FG`, or ARSO reports *megla* near Brnik, raise the "fog" event; TAF suggests how long it lasts (the brief says 1 h).
- **Fog along the flight path.** Sample Open-Meteo visibility at 3–5 points on the straight line; if any is below ~1.5 km, flag that helicopter leg as infeasible and switch to an ambulance.
- **promet.si closure → reroute.** A *zapora*/*Ovire*/*Okvara* event on a road an ambulance is using (geocode the text with Nominatim) → build an `avoid_polygons` box → ORS gives a new route and ETA → replan.
- **Delays → time windows.** *Zastoj, zamuda: 5 min* from promet.si, or TomTom `delay` → add to ETAs and re-check time windows.
- **Real road matrix.** OSRM `table` once for the hospital and all task points gives realistic ambulance times instead of straight line × 1.35.
- **Slovenian message → event.** LLM + Nominatim: "*Vozilo je obstalo pri Vranskem, oprema je še v njem*" → `{type: breakdown, vehicle, location: 46.24,14.95, equipment_onboard: true}` → pickup task for another vehicle.
- **Real promet.si text as AI input.** Feed live Atom entries (Slovenian) to the assistant to show it reading real-world messages, not just scripted ones.
- **Realistic map.** Overpass hospitals and helipads as the scenario's hospitals and landing sites.

## Demo safety
- **Snapshot everything.** For each live source, save the last good response to disk (like `research/samples/`) and fall back to it when the call fails or the venue Wi-Fi drops. Show "live" / "snapshot" in the UI.
- **Record a fog snapshot in advance.** Live weather on demo day may well be clear. Keep a saved METAR/ARSO response *with* fog (or edit a copy, clearly labelled as simulated) to trigger the scenario on cue.
- Never depend on Overpass, the OSRM demo or Nominatim during the 3-minute demo. Precompute and cache.
- NAP approval may not arrive in time; promet.si Atom + TomTom are the fallback.
