import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { trafficTileUrl, type VehicleDetail, type WorldSnapshot } from "./api";
import { fmtTime, vehicleStatusText } from "./format";

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

export function MapView({ state, mode, onMapClick, selectedId, onSelect, detail, centerOn }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layers = useRef<Layers | null>(null);
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
    const map = L.map(el.current).setView([46.056, 14.51], 12);
    // Standard OSM tiles, darkened with a CSS filter on .base-layer tiles (styles.css).
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
      className: "base-layer",
    }).addTo(map);
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
      .layers(undefined, { "🚦 Traffic flow (TomTom)": traffic, "⚠ Traffic incidents (TomTom)": trafficIncidents }, { position: "topright" })
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
    // Leaflet only tracks window resizes; re-measure whenever the map's own box changes size
    // (header wrapping, grid changes), otherwise tiles and markers are placed for the old size.
    const resize = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    resize.observe(el.current);
    mapRef.current = map;
    return () => {
      resize.disconnect();
      map.remove();
      mapRef.current = null;
      layers.current = null;
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
    Object.values(ls).forEach((g) => g.clearLayers());

    const placeById = new Map(state.places.map((p) => [p.id, p]));
    const tripById = new Map(state.trips.map((t) => [t.id, t]));
    const dim = selectedId !== null; // something is selected: fade everyone else's route

    for (const p of state.places) {
      const s = PLACE_STYLE[p.kind] ?? PLACE_STYLE.residential;
      L.circleMarker([p.lat, p.lon], { radius: s.r, color: s.color, fillColor: s.color, fillOpacity: 0.8, weight: 1 })
        .bindTooltip(p.name)
        .addTo(ls.places);
    }

    for (const inc of state.incidents) {
      const color = inc.kind === "congestion" ? "#fab005" : "#ff4d4f";
      L.circle([inc.lat, inc.lon], { radius: inc.radius_m, color, fillColor: color, fillOpacity: 0.2, dashArray: inc.source === "live" ? "4 4" : undefined })
        .bindTooltip(`${inc.id}: ${inc.description}`)
        .addTo(ls.incidents);
    }

    // Selected vehicle: its whole remaining day on real roads, with numbered stops
    if (detail && detail.vehicle.id === selectedId) {
      for (const leg of detail.legs) {
        if (leg.length > 1) L.polyline(leg, { color: "#000", weight: 9, opacity: 0.35 }).addTo(ls.highlight); // halo
      }
      detail.legs.forEach((leg, i) => {
        if (leg.length > 1) {
          L.polyline(leg, { color: HIGHLIGHT, weight: 5, opacity: i === 0 ? 1 : 0.75, dashArray: i === 0 ? undefined : "8 6" }).addTo(
            ls.highlight,
          );
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

    for (const v of state.vehicles) {
      const trip = v.current_trip_id ? tripById.get(v.current_trip_id) : undefined;
      const color = v.type === "ambulance" ? "#ff8787" : v.type === "helicopter" ? "#ffc078" : "#74c0fc";
      const dash = v.status === "to_pickup" ? "6 6" : undefined;
      const grounded = v.grounded_until != null; // the backend clears it when the fog lifts
      const opacity = dim && v.id !== selectedId ? 0.2 : 0.85;
      if (!(detail && v.id === selectedId)) {
        if (v.type === "helicopter") {
          // Helicopters fly straight (no road path): dashed flight line to the pickup, drop-off or base
          const targetId =
            v.status === "to_pickup" ? trip?.pickup_id : trip ? trip.dropoff_id : v.status === "returning" ? v.base_id : undefined;
          const target = targetId ? placeById.get(targetId) : undefined;
          if (target) {
            L.polyline(
              [
                [v.lat, v.lon],
                [target.lat, target.lon],
              ],
              { color, weight: 2, opacity, dashArray: "10 8" },
            ).addTo(ls.routes);
          }
        } else if (v.path && v.path.length > 1) {
          // Real road route still to drive
          L.polyline(v.path, { color, weight: 3, opacity, dashArray: dash }).addTo(ls.routes);
        } else if (trip) {
          // No road route cached yet: thin straight line to the target
          const target = placeById.get(v.status === "to_pickup" ? trip.pickup_id : trip.dropoff_id);
          if (target) {
            L.polyline(
              [
                [v.lat, v.lon],
                [target.lat, target.lon],
              ],
              { color, weight: 1, opacity: opacity * 0.6, dashArray: "2 6" },
            ).addTo(ls.routes);
          }
        }
      }
      const selected = v.id === selectedId;
      const icon = L.divIcon({
        className: "",
        html: `<div class="veh veh-${v.type} st-${v.status}${grounded ? " grounded" : ""}${selected ? " selected" : ""}${
          dim && !selected ? " faded" : ""
        }">${v.id}</div>`,
        iconSize: [32, 20],
        iconAnchor: [16, 10],
      });
      const groundedText = grounded ? ` · grounded by fog until ${fmtTime(v.grounded_until)}` : "";
      L.marker([v.lat, v.lon], { icon, zIndexOffset: selected ? 1000 : 0 })
        .bindTooltip(
          `${v.name} · ${vehicleStatusText(v, state.trips)}${trip ? ` · ${trip.id} (${trip.label})` : ""}${groundedText} · ⛽ ${Math.round(
            v.fuel_pct ?? 0,
          )}% · click for details`,
        )
        .on("click", () => selectRef.current(v.id))
        .addTo(ls.vehicles);
    }
  }, [state, selectedId, detail]);

  return <div ref={el} className="map" />; // constant on purpose, see the classList effect above
}
