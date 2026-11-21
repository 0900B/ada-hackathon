import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { WorldSnapshot } from "./api";

export type ClickMode = "closure" | "emergency" | null;

const PLACE_STYLE: Record<string, { r: number; color: string }> = {
  hospital: { r: 7, color: "#ff6b6b" },
  health_centre: { r: 5, color: "#ffa94d" },
  base: { r: 6, color: "#9775fa" },
  residential: { r: 3, color: "#868e96" },
  incident_site: { r: 7, color: "#ffd43b" },
  call_location: { r: 8, color: "#ff0054" },
};

interface Layers {
  places: L.LayerGroup;
  incidents: L.LayerGroup;
  routes: L.LayerGroup;
  vehicles: L.LayerGroup;
}

interface Props {
  state: WorldSnapshot;
  mode: ClickMode;
  onMapClick: (lat: number, lon: number) => void;
}

export function MapView({ state, mode, onMapClick }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const layers = useRef<Layers | null>(null);
  const clickRef = useRef(onMapClick);
  const modeRef = useRef(mode);

  useEffect(() => {
    clickRef.current = onMapClick;
    modeRef.current = mode;
  });

  // Create the map once.
  useEffect(() => {
    if (!el.current) return;
    const map = L.map(el.current).setView([46.056, 14.51], 12);
    // Standard OSM tiles, darkened with a CSS filter (.leaflet-tile-pane in styles.css).
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }).addTo(map);
    layers.current = {
      places: L.layerGroup().addTo(map),
      incidents: L.layerGroup().addTo(map),
      routes: L.layerGroup().addTo(map),
      vehicles: L.layerGroup().addTo(map),
    };
    map.on("click", (e: L.LeafletMouseEvent) => {
      if (modeRef.current) clickRef.current(e.latlng.lat, e.latlng.lng);
    });
    return () => {
      map.remove();
      layers.current = null;
    };
  }, []);

  // Redraw on every snapshot (a few dozen objects, so this is cheap).
  useEffect(() => {
    const ls = layers.current;
    if (!ls) return;
    Object.values(ls).forEach((g) => g.clearLayers());

    const placeById = new Map(state.places.map((p) => [p.id, p]));
    const tripById = new Map(state.trips.map((t) => [t.id, t]));

    for (const p of state.places) {
      const s = PLACE_STYLE[p.kind] ?? PLACE_STYLE.residential;
      L.circleMarker([p.lat, p.lon], { radius: s.r, color: s.color, fillColor: s.color, fillOpacity: 0.8, weight: 1 })
        .bindTooltip(p.name)
        .addTo(ls.places);
    }

    for (const inc of state.incidents) {
      L.circle([inc.lat, inc.lon], { radius: inc.radius_m, color: "#ff4d4f", fillColor: "#ff4d4f", fillOpacity: 0.2 })
        .bindTooltip(`${inc.id}: ${inc.description}`)
        .addTo(ls.incidents);
    }

    for (const v of state.vehicles) {
      const trip = v.current_trip_id ? tripById.get(v.current_trip_id) : undefined;
      if (trip) {
        const target = placeById.get(v.status === "to_pickup" ? trip.pickup_id : trip.dropoff_id);
        if (target) {
          L.polyline(
            [
              [v.lat, v.lon],
              [target.lat, target.lon],
            ],
            {
              color: v.type === "ambulance" ? "#ff8787" : "#74c0fc",
              weight: 2,
              opacity: 0.8,
              dashArray: v.status === "to_pickup" ? "6 6" : undefined,
            },
          ).addTo(ls.routes);
        }
      }
      const icon = L.divIcon({
        className: "",
        html: `<div class="veh veh-${v.type} st-${v.status}">${v.id}</div>`,
        iconSize: [32, 20],
        iconAnchor: [16, 10],
      });
      L.marker([v.lat, v.lon], { icon })
        .bindTooltip(`${v.name} · ${v.status.replace(/_/g, " ")}${trip ? ` · ${trip.id}` : ""}`)
        .addTo(ls.vehicles);
    }
  }, [state]);

  return <div ref={el} className={`map${mode ? " picking" : ""}`} />;
}
