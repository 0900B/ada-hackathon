import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { trafficTileUrl, type Vehicle, type VehicleDetail, type WorldSnapshot } from "./api";
import { baseMaps, saveBase, savedBase, type BaseId } from "./basemaps";
import { flightTarget, fmtTime, vehicleStatusText } from "./format";
import { GLYPH, vehicleGlyph } from "./glyphs";

export type ClickMode = "closure" | "emergency" | null;

// Places: small, restrained markers; red is reserved for hospitals and emergency call locations
const PLACE_STYLE: Record<string, { r: number; color: string; fill: string }> = {
  hospital: { r: 6, color: "#f2555a", fill: "#3a1417" },
  health_centre: { r: 4, color: "#a9b6c6", fill: "#18202a" },
  base: { r: 5, color: "#8cb6ff", fill: "#132443" },
  residential: { r: 2.5, color: "#6e7a88", fill: "#6e7a88" },
  incident_site: { r: 6, color: "#f0883e", fill: "#3a2312" },
  call_location: { r: 7, color: "#f2555a", fill: "#f2555a" },
};

const HIGHLIGHT = "#5b9bff"; // the selected vehicle's legs
const DETOUR = "#f0883e"; // legs that go around a road closure
const EN_ROUTE = "#4f8ff7"; // to the pickup
const LOADED = "#3fb950"; // patient or load on board
const GROUNDED = "#8f9cab";
const VEH_W = 56; // vehicle marker width; markers parked on the same spot are fanned out by this much

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

/** Map marker: a dark plate with the type glyph and the callsign; the border colour is the status. */
function vehicleHtml(v: Vehicle, cls: string, flying: boolean, grounded: boolean, held: boolean): string {
  const tag = grounded ? '<span class="vm-tag">Fog</span>' : flying ? '<span class="vm-tag air">Air</span>' : "";
  return (
    `<div class="vm type-${v.type} st-${v.status}${grounded ? " grounded" : ""}${held ? " held" : ""}${cls}">` +
    `${vehicleGlyph(v.type)}<span class="vm-id">${v.id}</span>${tag}</div>`
  );
}

const INCIDENT_LABEL: Record<string, string> = { road_closure: "Road closure", accident: "Accident", congestion: "Congestion" };

export function MapView({ state, mode, onMapClick, selectedId, onSelect, detail, centerOn }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layers = useRef<Layers | null>(null);
  const [zoomTick, setZoomTick] = useState(0);
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
      saveBase(id);
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
        { "Traffic flow (TomTom)": traffic, "Traffic incidents (TomTom)": trafficIncidents },
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
      setZoomTick((t) => t + 1); // re-place fanned-out markers for the new zoom (pixel offsets)
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
        L.circleMarker([p.lat, p.lon], { radius: s.r, color: s.color, fillColor: s.fill, fillOpacity: 0.9, weight: 1.5 })
          .bindTooltip(p.name + cap)
          .addTo(ls.places);
      }
    }
    const incidentsKey = state.incidents.map((i) => `${i.id}:${i.active}`).join(",");
    if (drawn.current.incidents !== incidentsKey) {
      drawn.current.incidents = incidentsKey;
      ls.incidents.clearLayers();
      for (const inc of state.incidents) {
        const color = inc.kind === "congestion" ? "#d6a23a" : "#f2555a";
        L.circle([inc.lat, inc.lon], { radius: inc.radius_m, color, weight: 1.5, fillColor: color, fillOpacity: 0.15, dashArray: inc.source === "live" ? "4 4" : undefined })
          .bindTooltip(`${INCIDENT_LABEL[inc.kind] ?? "Incident"}: ${inc.description}`)
          .addTo(ls.incidents);
      }
    }

    ls.routes.clearLayers();
    ls.highlight.clearLayers();

    // Selected vehicle: its whole remaining day on real roads, with numbered stops
    if (detail && detail.vehicle.id === selectedId) {
      for (const leg of detail.legs) {
        if (leg.length > 1) L.polyline(leg, { color: "#05080c", weight: 8, opacity: 0.6, interactive: false }).addTo(ls.highlight); // casing
      }
      const detours = new Set(detail.detour_legs ?? []);
      detail.legs.forEach((leg, i) => {
        if (leg.length > 1) {
          const line = L.polyline(leg, {
            color: detours.has(i) ? DETOUR : HIGHLIGHT,
            weight: 4,
            opacity: i === 0 ? 1 : 0.6,
            dashArray: i === 0 ? undefined : "6 6",
          }).addTo(ls.highlight);
          if (detours.has(i)) line.bindTooltip("Detour around a road closure");
        }
      });
      detail.stops.forEach((s, i) => {
        const icon = L.divIcon({
          className: "",
          html: `<div class="stop-num stop-${s.kind}">${s.kind === "base" ? GLYPH.base : i + 1}</div>`,
          iconSize: [18, 18],
          iconAnchor: [9, 9],
        });
        L.marker([s.lat, s.lon], { icon, interactive: true })
          .bindTooltip(`${i + 1}. ${s.kind} · ${s.place}${s.trip_id ? ` · ${s.trip_id}` : ""}${s.eta ? ` · ${fmtTime(s.eta)}` : ""}`)
          .addTo(ls.highlight);
      });
    }

    // Vehicles standing close together on screen (parked at a base, or at UKC right next to Base
    // Center) are fanned out side by side, so no callsign hides another. Only stationary ones: a
    // moving vehicle is never offset, so nothing jumps when one drives off. Grouping is by screen
    // distance at the current zoom (recomputed on zoomend), not by identical coordinates.
    const stationary = (v: Vehicle) =>
      v.status === "idle" || v.status === "loading" || v.status === "out_of_service" || Boolean(v.busy_until) || Boolean(v.waiting_until);
    const map = mapRef.current;
    const fanned = new Map<string, L.LatLng>(); // vehicle id -> display position
    if (map) {
      const parked = state.vehicles
        .filter(stationary)
        .sort((a, b) => a.id.localeCompare(b.id))
        .map((v) => ({ v, p: map.latLngToLayerPoint([v.lat, v.lon]) }));
      const overlaps = (a: L.Point, b: L.Point) => Math.abs(a.x - b.x) < VEH_W && Math.abs(a.y - b.y) < 26;
      const groups: (typeof parked)[] = [];
      for (const item of parked) {
        const group = groups.find((g) => g.some((m) => overlaps(m.p, item.p)));
        if (group) group.push(item);
        else groups.push([item]);
      }
      for (const g of groups) {
        if (g.length < 2) continue;
        const cx = g.reduce((sum, m) => sum + m.p.x, 0) / g.length;
        const cy = g.reduce((sum, m) => sum + m.p.y, 0) / g.length;
        g.forEach((m, i) => fanned.set(m.v.id, map.layerPointToLatLng(L.point(cx + (i - (g.length - 1) / 2) * VEH_W, cy))));
      }
    }

    const seen = new Set<string>();
    for (const v of state.vehicles) {
      seen.add(v.id);
      const trip = v.current_trip_id ? tripById.get(v.current_trip_id) : undefined;
      const heli = v.type === "helicopter";
      const color = v.status === "to_pickup" ? EN_ROUTE : LOADED;
      const grounded = v.grounded_until != null; // the backend clears it when the fog lifts
      const selected = v.id === selectedId;
      const faded = dim && !selected;
      const opacity = faded ? 0.2 : 0.85;
      const target = heli ? flightTarget(v, trip, placeById) : null;
      const flying = target !== null && !v.busy_until;

      if (heli && target && !(detail && selected)) {
        // Helicopters fly straight (no road path): a dashed line to the pickup, drop-off or base,
        // plus a ring on the landing spot
        const lineColor = grounded ? GROUNDED : v.status === "to_pickup" ? EN_ROUTE : LOADED;
        L.polyline(
          [
            [v.lat, v.lon],
            [target.place.lat, target.place.lon],
          ],
          { color: "#05080c", weight: 6, opacity: faded ? 0.1 : 0.5, interactive: false },
        ).addTo(ls.routes);
        L.polyline(
          [
            [v.lat, v.lon],
            [target.place.lat, target.place.lon],
          ],
          { color: lineColor, weight: 2.5, opacity: faded ? 0.25 : 1, dashArray: "8 6", className: "flight-line", interactive: false },
        ).addTo(ls.routes);
        L.circleMarker([target.place.lat, target.place.lon], {
          radius: 9,
          color: lineColor,
          weight: 1.5,
          fill: false,
          opacity: faded ? 0.25 : 1,
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
      const held = Boolean(v.busy_until) && v.status !== "loading" && !(v.status === "returning" && !v.current_trip_id);
      const html = vehicleHtml(v, cls, heli && flying && !grounded, grounded, held);
      const size: [number, number] = [heli ? 72 : 60, 24];
      const anchor: [number, number] = [size[0] / 2, size[1] / 2]; // constant: the element is never re-created
      // The fan-out is a pixel offset of the marker's position, so changes glide like normal movement
      const pos = fanned.get(v.id) ?? L.latLng(v.lat, v.lon);
      const key = html;
      const where = target ? ` · ${target.kind === "base" ? "flying home" : `flying to ${target.kind}`}: ${target.place.name}` : "";
      const groundedText = grounded ? ` · grounded by fog until ${fmtTime(v.grounded_until)}` : "";
      const tip = `${v.name} · ${vehicleStatusText(v, state.trips)}${trip ? ` · ${trip.id} (${trip.label})` : ""}${
        heli ? where : ""
      }${groundedText} · fuel ${Math.round(v.fuel_pct ?? 0)}% · click for details`;
      const z = selected ? 2000 : heli ? 1000 : 0;

      const existing = markers.current.get(v.id);
      if (!existing) {
        const icon = L.divIcon({ className: "veh-marker", html, iconSize: size, iconAnchor: anchor });
        const marker = L.marker(pos, { icon, zIndexOffset: z, riseOnHover: true })
          .bindTooltip(tip, { direction: "top", offset: [0, -size[1] / 2] })
          .on("click", () => selectRef.current(v.id))
          .addTo(ls.vehicles);
        markers.current.set(v.id, { marker, key });
      } else {
        const { marker } = existing;
        const ll = marker.getLatLng();
        if (ll.lat !== pos.lat || ll.lng !== pos.lng) marker.setLatLng(pos);
        if (existing.key !== key) {
          // Status or selection changed: update the content in place. Replacing the icon would
          // create a new element, which skips the glide (or animates in from the map's corner).
          const node = marker.getElement();
          if (node) node.innerHTML = html;
          else marker.setIcon(L.divIcon({ className: "veh-marker", html, iconSize: size, iconAnchor: anchor }));
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
  }, [state, selectedId, detail, zoomTick]);

  return <div ref={el} className="map" />; // constant on purpose, see the classList effect above
}
