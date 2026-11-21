import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { trafficTileUrl, type Vehicle, type VehicleDetail, type WorldSnapshot } from "./api";
import { flightTarget, fmtTime, vehicleStatusText } from "./format";

export type ClickMode = "closure" | "emergency" | null;

const PLACE_STYLE: Record<string, { r: number; color: string }> = {
  hospital: { r: 7, color: "#ff6b6b" },
  health_centre: { r: 5, color: "#ffa94d" },
  base: { r: 6, color: "#9775fa" },
  residential: { r: 3, color: "#868e96" },
  incident_site: { r: 7, color: "#ffd43b" },
  call_location: { r: 8, color: "#ff0054" },
};

const HIGHLIGHT = "#ffd43b";
const DETOUR = "#ff922b"; // highlighted legs that go around a road closure
const HELI = "#ff922b";
const HELI_GROUNDED = "#adb5bd";
const VEH_W = 34; // vehicle marker width; markers parked on the same spot are fanned out by this much

interface Layers {
  places: L.LayerGroup;
  incidents: L.LayerGroup;
  routes: L.LayerGroup;
  highlight: L.LayerGroup;
  vehicles: L.LayerGroup;
}

interface Props {
  state: WorldSnapshot;
  mode: ClickMode;
  onMapClick: (lat: number, lon: number) => void;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  detail: VehicleDetail | null; // route of the selected vehicle, highlighted
  centerOn: { lat: number; lon: number; n: number } | null; // bump n to re-center
}

type BaseId = "dark" | "standard" | "satellite" | "hybrid" | "terrain";
const BASE_KEY = "planb.basemap";
const OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const ESRI_ATTR = "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community";
const esri = (service: string) => `https://server.arcgisonline.com/ArcGIS/rest/services/${service}/MapServer/tile/{z}/{y}/{x}`;

/** The base maps of the layer switcher (Google-Maps style), all keyless. */
function baseMaps(): Record<BaseId, { label: string; layer: L.Layer }> {
  const imagery = () => L.tileLayer(esri("World_Imagery"), { attribution: ESRI_ATTR, maxZoom: 19 });
  return {
    dark: { label: "🌙 Dark", layer: L.tileLayer(OSM, { attribution: OSM_ATTR, maxZoom: 19, className: "base-layer dark-layer" }) },
    standard: { label: "🗺 Standard", layer: L.tileLayer(OSM, { attribution: OSM_ATTR, maxZoom: 19, className: "base-layer" }) },
    satellite: { label: "🛰 Satellite", layer: imagery() },
    hybrid: {
      label: "🛰 Hybrid (satellite + labels)",
      layer: L.layerGroup([
        imagery(),
        L.tileLayer(esri("Reference/World_Transportation"), { maxZoom: 19 }),
        L.tileLayer(esri("Reference/World_Boundaries_and_Places"), { maxZoom: 19 }),
      ]),
    },
    terrain: {
      label: "⛰ Terrain",
      layer: L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
        subdomains: "abc",
        maxNativeZoom: 17,
        maxZoom: 19,
        attribution: `${OSM_ATTR}, SRTM | style &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)`,
      }),
    },
  };
}

function savedBase(): BaseId {
  try {
    const v = localStorage.getItem(BASE_KEY);
    if (v === "dark" || v === "standard" || v === "satellite" || v === "hybrid" || v === "terrain") return v;
  } catch {
    // storage blocked: use the default
  }
  return "dark";
}

function vehicleHtml(v: Vehicle, cls: string, flying: boolean, grounded: boolean): string {
  if (v.type !== "helicopter") return `<div class="veh veh-${v.type} st-${v.status}${cls}">${v.id}</div>`;
  return (
    `<div class="heli st-${v.status}${flying ? " flying" : ""}${grounded ? " grounded" : ""}${cls}">` +
    `<span class="heli-rotor"></span><span class="heli-body">🚁</span><span class="heli-id">${v.id}</span>` +
    (grounded ? `<span class="heli-fog">🌫 grounded</span>` : "") +
    `</div>`
  );
}

export function MapView({ state, mode, onMapClick, selectedId, onSelect, detail, centerOn }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layers = useRef<Layers | null>(null);
  // Vehicle markers live across snapshots (moved, not re-created), so a click never lands on a
  // marker that is being replaced, tooltips stay open, and CSS can animate the movement.
  const markers = useRef(new Map<string, { marker: L.Marker; key: string }>());
  const drawn = useRef({ places: "", incidents: "" });
  const clickRef = useRef(onMapClick);
  const selectRef = useRef(onSelect);
  const modeRef = useRef(mode);

  useEffect(() => {
    clickRef.current = onMapClick;
    selectRef.current = onSelect;
    modeRef.current = mode;
  });

  // Toggle the class directly: if React owned className, every re-render would wipe the classes
  // Leaflet adds to this element (leaflet-container etc.), which is what clips the map.
  useEffect(() => {
    el.current?.classList.toggle("picking", mode !== null);
  }, [mode]);

  // Create the map once.
  useEffect(() => {
    if (!el.current) return;
    const box = el.current;
    const map = L.map(box).setView([46.056, 14.51], 12);
    // Base maps (keyless tile services). Only "Dark" gets the CSS invert filter (.dark-layer in styles.css).
    const bases = baseMaps();
    const initial = savedBase();
    bases[initial].layer.addTo(map);
    box.dataset.base = initial;
    map.on("baselayerchange", (e: L.LayersControlEvent) => {
      const id = (Object.keys(bases) as BaseId[]).find((k) => bases[k].layer === e.layer);
      if (!id) return;
      box.dataset.base = id; // lets the CSS outline routes on bright base maps
      try {
        localStorage.setItem(BASE_KEY, id);
      } catch {
        // storage blocked (private window): the choice just isn't remembered
      }
    });
    // Live traffic from TomTom (through our backend; transparent overlays, no colour filter)
    const traffic = L.tileLayer(trafficTileUrl("flow"), {
      opacity: 0.9,
      minZoom: 9,
      maxZoom: 19,
      maxNativeZoom: 18,
      attribution: "Traffic &copy; TomTom",
      className: "traffic-layer",
    }).addTo(map);
    const trafficIncidents = L.tileLayer(trafficTileUrl("incidents"), {
      minZoom: 9,
      maxZoom: 19,
      maxNativeZoom: 18,
      className: "traffic-layer",
    });
    L.control
      .layers(
        Object.fromEntries((Object.keys(bases) as BaseId[]).map((k) => [bases[k].label, bases[k].layer])),
        { "🚦 Traffic flow (TomTom)": traffic, "⚠ Traffic incidents (TomTom)": trafficIncidents },
        { position: "topright" },
      )
      .addTo(map);
    layers.current = {
      places: L.layerGroup().addTo(map),
      incidents: L.layerGroup().addTo(map),
      routes: L.layerGroup().addTo(map),
      highlight: L.layerGroup().addTo(map),
      vehicles: L.layerGroup().addTo(map),
    };
    map.on("click", (e: L.LeafletMouseEvent) => {
      if (modeRef.current) clickRef.current(e.latlng.lat, e.latlng.lng);
      else selectRef.current(null); // click on empty map: deselect
    });
    // Vehicles glide between position updates (styles.css: .map.smooth), except while zooming,
    // when Leaflet repositions every marker and a slow transition would make them drift.
    box.classList.add("smooth");
    let smoothTimer: ReturnType<typeof setTimeout> | undefined;
    map.on("zoomstart viewreset zoomanim", () => {
      clearTimeout(smoothTimer);
      box.classList.remove("smooth");
    });
    map.on("zoomend", () => {
      clearTimeout(smoothTimer);
      smoothTimer = setTimeout(() => box.classList.add("smooth"), 400);
    });
    // Leaflet only tracks window resizes; re-measure whenever the map's own box changes size
    // (header wrapping, grid changes), otherwise tiles and markers are placed for the old size.
    const resize = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    resize.observe(box);
    mapRef.current = map;
    const vehicleMarkers = markers.current;
    const drawnLayers = drawn.current;
    return () => {
      clearTimeout(smoothTimer);
      resize.disconnect();
      map.remove();
      mapRef.current = null;
      layers.current = null;
      vehicleMarkers.clear();
      drawnLayers.places = drawnLayers.incidents = "";
    };
  }, []);

  // Re-center when asked (vehicle card "Center" button)
  useEffect(() => {
    if (centerOn && mapRef.current) mapRef.current.setView([centerOn.lat, centerOn.lon], Math.max(mapRef.current.getZoom(), 14));
  }, [centerOn]);

  // Redraw on every snapshot (a few dozen objects, so this is cheap).
  useEffect(() => {
    const ls = layers.current;
    if (!ls) return;

    const placeById = new Map(state.places.map((p) => [p.id, p]));
    const tripById = new Map(state.trips.map((t) => [t.id, t]));
    const dim = selectedId !== null; // something is selected: fade everyone else's route

    // Places and incidents change rarely: redraw them only when they do (keeps their tooltips usable)
    const placesKey = state.places.map((p) => `${p.id}:${p.capacity}`).join(",");
    if (drawn.current.places !== placesKey) {
      drawn.current.places = placesKey;
      ls.places.clearLayers();
      for (const p of state.places) {
        const s = PLACE_STYLE[p.kind] ?? PLACE_STYLE.residential;
        const cap = p.kind === "hospital" && p.capacity != null ? ` · can admit ${p.capacity}` : "";
        L.circleMarker([p.lat, p.lon], { radius: s.r, color: s.color, fillColor: s.color, fillOpacity: 0.8, weight: 1 })
          .bindTooltip(p.name + cap)
          .addTo(ls.places);
      }
    }
    const incidentsKey = state.incidents.map((i) => `${i.id}:${i.active}`).join(",");
    if (drawn.current.incidents !== incidentsKey) {
      drawn.current.incidents = incidentsKey;
      ls.incidents.clearLayers();
      for (const inc of state.incidents) {
        const color = inc.kind === "congestion" ? "#fab005" : "#ff4d4f";
        L.circle([inc.lat, inc.lon], { radius: inc.radius_m, color, fillColor: color, fillOpacity: 0.2, dashArray: inc.source === "live" ? "4 4" : undefined })
          .bindTooltip(`${inc.kind === "road_closure" ? "⛔" : inc.kind === "accident" ? "💥" : "🚦"} ${inc.description}`)
          .addTo(ls.incidents);
      }
    }

    ls.routes.clearLayers();
    ls.highlight.clearLayers();

    // Selected vehicle: its whole remaining day on real roads, with numbered stops
    if (detail && detail.vehicle.id === selectedId) {
      for (const leg of detail.legs) {
        if (leg.length > 1) L.polyline(leg, { color: "#000", weight: 9, opacity: 0.35, interactive: false }).addTo(ls.highlight); // halo
      }
      const detours = new Set(detail.detour_legs ?? []);
      detail.legs.forEach((leg, i) => {
        if (leg.length > 1) {
          const line = L.polyline(leg, {
            color: detours.has(i) ? DETOUR : HIGHLIGHT,
            weight: 5,
            opacity: i === 0 ? 1 : 0.75,
            dashArray: i === 0 ? undefined : "8 6",
          }).addTo(ls.highlight);
          if (detours.has(i)) line.bindTooltip("Detour around a road closure");
        }
      });
      detail.stops.forEach((s, i) => {
        const icon = L.divIcon({
          className: "",
          html: `<div class="stop-num stop-${s.kind}">${i + 1}</div>`,
          iconSize: [20, 20],
          iconAnchor: [10, 10],
        });
        L.marker([s.lat, s.lon], { icon, interactive: true })
          .bindTooltip(`${i + 1}. ${s.kind} · ${s.place}${s.trip_id ? ` · ${s.trip_id}` : ""}${s.eta ? ` · ${fmtTime(s.eta)}` : ""}`)
          .addTo(ls.highlight);
      });
    }

    // Vehicles parked on the same spot (e.g. at a base) are fanned out side by side
    const spots = new Map<string, string[]>();
    for (const v of state.vehicles) {
      const k = `${v.lat.toFixed(4)},${v.lon.toFixed(4)}`;
      spots.set(k, [...(spots.get(k) ?? []), v.id]);
    }

    const seen = new Set<string>();
    for (const v of state.vehicles) {
      seen.add(v.id);
      const trip = v.current_trip_id ? tripById.get(v.current_trip_id) : undefined;
      const heli = v.type === "helicopter";
      const color = v.type === "ambulance" ? "#ff8787" : heli ? HELI : "#74c0fc";
      const grounded = v.grounded_until != null; // the backend clears it when the fog lifts
      const selected = v.id === selectedId;
      const faded = dim && !selected;
      const opacity = faded ? 0.2 : 0.85;
      const target = heli ? flightTarget(v, trip, placeById) : null;
      const flying = target !== null && !v.busy_until;

      if (heli && target && !(detail && selected)) {
        // Helicopters fly straight (no road path): a moving dotted line to the pickup, drop-off or
        // base, plus a ring on the landing spot
        const lineColor = grounded ? HELI_GROUNDED : HELI;
        L.polyline(
          [
            [v.lat, v.lon],
            [target.place.lat, target.place.lon],
          ],
          { color: "#000", weight: 7, opacity: faded ? 0.1 : 0.35, interactive: false },
        ).addTo(ls.routes);
        L.polyline(
          [
            [v.lat, v.lon],
            [target.place.lat, target.place.lon],
          ],
          { color: lineColor, weight: 3, opacity: faded ? 0.25 : 1, dashArray: "2 9", lineCap: "round", className: "flight-line", interactive: false },
        ).addTo(ls.routes);
        L.circleMarker([target.place.lat, target.place.lon], {
          radius: 11,
          color: lineColor,
          weight: 2,
          fill: false,
          opacity: faded ? 0.25 : 1,
          dashArray: "3 3",
        })
          .bindTooltip(`${v.id} ${target.kind === "base" ? "flying home to" : `${target.kind}:`} ${target.place.name}`)
          .addTo(ls.routes);
      } else if (!heli && !(detail && selected)) {
        const dash = v.status === "to_pickup" ? "6 6" : undefined;
        if (v.path && v.path.length > 1) {
          // Real road route still to drive
          L.polyline(v.path, { color, weight: 3, opacity, dashArray: dash, interactive: false }).addTo(ls.routes);
        } else if (trip) {
          // No road route cached yet: thin straight line to the target
          const to = placeById.get(v.status === "to_pickup" ? trip.pickup_id : trip.dropoff_id);
          if (to) {
            L.polyline(
              [
                [v.lat, v.lon],
                [to.lat, to.lon],
              ],
              { color, weight: 1, opacity: opacity * 0.6, dashArray: "2 6", interactive: false },
            ).addTo(ls.routes);
          }
        }
      }

      const cls = `${selected ? " selected" : ""}${faded ? " faded" : ""}`;
      const html = vehicleHtml(v, cls, flying, grounded);
      const spot = spots.get(`${v.lat.toFixed(4)},${v.lon.toFixed(4)}`) ?? [v.id];
      const shift = spot.length > 1 ? (spot.indexOf(v.id) - (spot.length - 1) / 2) * VEH_W : 0;
      const size: [number, number] = heli ? [40, 40] : [32, 20];
      const anchor: [number, number] = [size[0] / 2 - shift, size[1] / 2];
      const key = `${html}|${anchor[0]}`;
      const where = target ? ` · ${target.kind === "base" ? "flying home" : `flying to ${target.kind}`}: ${target.place.name}` : "";
      const groundedText = grounded ? ` · 🌫 grounded by fog until ${fmtTime(v.grounded_until)}` : "";
      const tip = `${v.name} · ${vehicleStatusText(v, state.trips)}${trip ? ` · ${trip.id} (${trip.label})` : ""}${
        heli ? where : ""
      }${groundedText} · ⛽ ${Math.round(v.fuel_pct ?? 0)}% · click for details`;
      const z = selected ? 2000 : heli ? 1000 : 0;

      const existing = markers.current.get(v.id);
      if (!existing) {
        const icon = L.divIcon({ className: "veh-marker", html, iconSize: size, iconAnchor: anchor });
        const marker = L.marker([v.lat, v.lon], { icon, zIndexOffset: z, riseOnHover: true })
          .bindTooltip(tip, { direction: "top", offset: [0, -size[1] / 2] })
          .on("click", () => selectRef.current(v.id))
          .addTo(ls.vehicles);
        markers.current.set(v.id, { marker, key });
      } else {
        const { marker } = existing;
        const ll = marker.getLatLng();
        if (ll.lat !== v.lat || ll.lng !== v.lon) marker.setLatLng([v.lat, v.lon]);
        if (existing.key !== key) {
          marker.setIcon(L.divIcon({ className: "veh-marker", html, iconSize: size, iconAnchor: anchor }));
          existing.key = key;
        }
        marker.setTooltipContent(tip);
        marker.setZIndexOffset(z);
      }
    }
    for (const [id, { marker }] of markers.current) {
      if (!seen.has(id)) {
        marker.remove();
        markers.current.delete(id);
      }
    }
  }, [state, selectedId, detail]);

  return <div ref={el} className="map" />; // constant on purpose, see the classList effect above
}
