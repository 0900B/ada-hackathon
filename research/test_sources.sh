#!/usr/bin/env bash
# Throwaway: re-fetch one sample per no-key live data source into research/samples/.
# Not production code. Keep request counts tiny and respect each service's policy.
# Usage: bash research/test_sources.sh   (from repo root)
set -u
cd "$(dirname "$0")/samples"
UA="ada-hackathon-research/0.1 (AdaHack 2026 test; github.com/0900B/ada-hackathon)"
get() { printf '%-40s ' "$1"; curl -s -m 60 -A "$UA" -o "$1" -w "%{http_code} %{size_download}B\n" "${@:2}"; }

# Weather
get aviationweather_metar.json "https://aviationweather.gov/api/data/metar?ids=LJLJ,LJMB,LJPZ&format=json"
get aviationweather_taf.json   "https://aviationweather.gov/api/data/taf?ids=LJLJ&format=json"
get open-meteo.json            "https://api.open-meteo.com/v1/forecast?latitude=46.05&longitude=14.51&hourly=visibility,cloud_cover_low,wind_gusts_10m&forecast_days=2"
get open-meteo_multi.json      "https://api.open-meteo.com/v1/forecast?latitude=46.05,46.22,46.48&longitude=14.51,14.46,15.69&current=visibility,cloud_cover_low,wind_gusts_10m,weather_code"
get arso_observation_si_latest.xml "https://meteo.arso.gov.si/uploads/probase/www/observ/surface/text/sl/observation_si_latest.xml"

# Traffic (public Atom feed; the b2b.dogodki.* feeds now need NAP credentials)
get promet_roadevents_sl.atom.xml "https://www.promet.si/dc/PROMET.ROADEVENTS.PP.RSS.SL"

# Routing and places
get osrm_route.json "https://router.project-osrm.org/route/v1/driving/14.5225,46.0569;14.4688,46.0754?overview=simplified&geometries=geojson"
get osrm_table.json "https://router.project-osrm.org/table/v1/driving/14.5225,46.0569;14.4688,46.0754;14.9500,46.2400?annotations=duration,distance"
get nominatim_koseze.json  "https://nominatim.openstreetmap.org/search?q=Koseze,+Ljubljana&format=jsonv2&limit=1&countrycodes=si"
sleep 1.5  # Nominatim: max 1 request/second
get nominatim_vransko.json "https://nominatim.openstreetmap.org/search?q=Vransko&format=jsonv2&limit=1&countrycodes=si"

# Overpass: main server often answers 502; mail.ru mirror worked. Bbox covers SI plus border areas.
Q='data=[out:json][timeout:50][bbox:45.42,13.37,46.88,16.61];(nwr["amenity"="hospital"];nwr["aeroway"="helipad"];);out center tags;'
get overpass_hospitals_helipads.json --data-urlencode "$Q" "https://maps.mail.ru/osm/tools/overpass/api/interpreter"

# Keyed sources: only if set in a local .env (never committed)
[ -f ../../.env ] && set -a && . ../../.env && set +a
if [ -n "${TOMTOM_API_KEY:-}" ]; then
  get tomtom_incidents.json "https://api.tomtom.com/traffic/services/5/incidentDetails?key=${TOMTOM_API_KEY}&bbox=14.35,45.97,14.72,46.16&fields=%7Bincidents%7Btype,geometry%7Btype,coordinates%7D,properties%7BiconCategory,magnitudeOfDelay,delay,from,to,roadNumbers%7D%7D%7D&language=en-GB"
fi
