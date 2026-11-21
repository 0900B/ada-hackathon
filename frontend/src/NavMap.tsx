import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { trafficTileUrl, type Incident, type Navigation, type Vehicle, type VehicleDetail } from "./api";
import { baseMaps, saveBase, savedBase, type BaseId } from "./basemaps";

const ROUTE = "#4dabf7"; // the leg being driven
const DETOUR = "#ff922b"; // legs that go around a road closure
const HELI = "#ff922b";

interface Props {
  vehicle: Vehicle;
  detail: VehicleDetail | null;
  nav: Navigation | null;
  incidents: Incident[];
  follow: boolean;
  onUserMove: () => void; // the user panned: stop following until re-centred
}

/** Heading in degrees from a to b (0 = north), for the vehicle arrow. */
function heading(a: [number, number], b: [number, number]): number {
  const p1 = (a[0] * Math.PI) / 180;
  const p2 = (b[0] * Math.PI) / 180;
  const dl = ((b[1] - a[1]) * Math.PI) / 180;
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

/** The first point of a polyline at least `minM` metres away from its start (for the heading). */
function aheadPoint(line: [number, number][], minM = 15): [number, number] | null {
  const [a] = line;
  for (const p of line.slice(1)) {
    const dy = (p[0] - a[0]) * 111_320;
    const dx = (p[1] - a[1]) * 111_320 * Math.cos((a[0] * Math.PI) / 180);
    if (Math.hypot(dx, dy) >= minM) return p;
  }
  return null;
}

/**
 * Navigation map for the in-vehicle tablet: follows the vehicle, shows the leg being driven bright
 * (detours orange), the rest of the day dimmed, numbered stops, closures and incidents. The
 * helicopter gets a straight flight line instead.
 */
export function NavMap({ vehicle, detail, nav, incidents, follow, onUserMove }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layers = useRef<{ route: L.LayerGroup; incidents: L.LayerGroup; marker: L.Marker | null; markerKey: string } | null>(null);
  const moveRef = useRef(onUserMove);
  const lastHeading = useRef(0);
  const heli = vehicle.type === "helicopter";

  useEffect(() => {
    moveRef.current = onUserMove;
  });

  useEffect(() => {
    if (!el.current) return;
    const box = el.current;
    const map = L.map(box, { zoomControl: false }).setView([vehicle.lat, vehicle.lon], heli ? 12 : 16);
    L.control.zoom({ position: "bottomright" }).addTo(map);
    const bases = baseMaps();
    const initial = savedBase();
    bases[initial].layer.addTo(map);
    box.dataset.base = initial;
    map.on("baselayerchange", (e: L.LayersControlEvent) => {
      const id = (Object.keys(bases) as BaseId[]).find((k) => bases[k].layer === e.layer);
      if (id) {
        box.dataset.base = id;
        saveBase(id);
      }
    });
    const traffic = L.tileLayer(trafficTileUrl("flow"), {
      opacity: 0.9,
      minZoom: 9,
      maxZoom: 19,
      maxNativeZoom: 18,
      attribution: "Traffic &copy; TomTom",
      className: "traffic-layer",
    });
    if (!heli) traffic.addTo(map);
    L.control
      .layers(
        Object.fromEntries((Object.keys(bases) as BaseId[]).map((k) => [bases[k].label, bases[k].layer])),
        { "🚦 Traffic (TomTom)": traffic },
        { position: "topright" },
      )
      .addTo(map);
    layers.current = { route: L.layerGroup().addTo(map), incidents: L.layerGroup().addTo(map), marker: null, markerKey: "" };
    map.on("dragstart", () => moveRef.current());
    // The vehicle glides between updates; no glide while zooming (Leaflet repositions markers then)
    box.classList.add("smooth");
    let timer: ReturnType<typeof setTimeout> | undefined;
    map.on("zoomstart viewreset zoomanim", () => {
      clearTimeout(timer);
      box.classList.remove("smooth");
    });
    map.on("zoomend", () => {
      clearTimeout(timer);
      timer = setTimeout(() => box.classList.add("smooth"), 400);
    });
    const resize = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    resize.observe(box);
    mapRef.current = map;
    return () => {
      clearTimeout(timer);
      resize.disconnect();
      map.remove();
      mapRef.current = null;
      layers.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- once per vehicle (the page is keyed by it)

  // Route, stops and the flight line (refreshed with the vehicle detail, every few seconds)
  useEffect(() => {
    const ls = layers.current;
    if (!ls) return;
    ls.route.clearLayers();
    const legs = detail?.vehicle.id === vehicle.id ? detail.legs : [];
    const detours = new Set(detail?.detour_legs ?? []);
    // the rest of the day first (dimmed), then the leg being driven on top
    legs.slice(1).forEach((leg, i) => {
      if (leg.length > 1)
        L.polyline(leg, { color: detours.has(i + 1) ? DETOUR : "#adb5bd", weight: 4, opacity: 0.35, dashArray: "6 8", interactive: false }).addTo(ls.route);
    });
    // The leg being driven: the snapshot's live remaining path (every tick), else the detail's
    const current = vehicle.path && vehicle.path.length > 1 ? vehicle.path : legs[0];
    if (heli && nav?.target) {
      const line: [number, number][] = [
        [vehicle.lat, vehicle.lon],
        [nav.target.lat, nav.target.lon],
      ];
      L.polyline(line, { color: "#000", weight: 10, opacity: 0.4, interactive: false }).addTo(ls.route);
      L.polyline(line, { color: HELI, weight: 5, dashArray: "2 12", lineCap: "round", className: "flight-line", interactive: false }).addTo(ls.route);
    } else if (current && current.length > 1) {
      L.polyline(current, { color: "#0b1220", weight: 13, opacity: 0.55, interactive: false }).addTo(ls.route);
      L.polyline(current, { color: detours.has(0) ? DETOUR : ROUTE, weight: 8, opacity: 1, interactive: false }).addTo(ls.route);
    }
    (detail?.vehicle.id === vehicle.id ? detail.stops : []).forEach((s, i) => {
      const icon = L.divIcon({
        className: "",
        html: `<div class="nav-stop nav-stop-${s.kind}${i === 0 ? " next" : ""}">${s.kind === "base" ? "🏠" : i + 1}</div>`,
        iconSize: [30, 30],
        iconAnchor: [15, 15],
      });
      L.marker([s.lat, s.lon], { icon, interactive: false, keyboard: false }).addTo(ls.route);
    });
  }, [detail, nav?.target, vehicle.id, vehicle.lat, vehicle.lon, vehicle.path, heli]);

  // Closures and incidents
  useEffect(() => {
    const ls = layers.current;
    if (!ls) return;
    ls.incidents.clearLayers();
    for (const inc of incidents) {
      if (!inc.active) continue;
      const color = inc.kind === "congestion" ? "#fab005" : "#ff4d4f";
      L.circle([inc.lat, inc.lon], { radius: inc.radius_m, color, weight: 3, fillColor: color, fillOpacity: 0.25, interactive: false }).addTo(ls.incidents);
      L.marker([inc.lat, inc.lon], {
        icon: L.divIcon({ className: "", html: `<div class="nav-incident">${inc.kind === "road_closure" ? "⛔" : inc.kind === "accident" ? "💥" : "🚦"}</div>`, iconSize: [26, 26], iconAnchor: [13, 13] }),
        interactive: false,
        keyboard: false,
      }).addTo(ls.incidents);
    }
  }, [incidents]);

  // The vehicle itself: an arrow pointing where it is heading; the map follows it
  useEffect(() => {
    const ls = layers.current;
    const map = mapRef.current;
    if (!ls || !map) return;
    const pos: [number, number] = [vehicle.lat, vehicle.lon];
    const towards =
      heli && nav?.target
        ? ([nav.target.lat, nav.target.lon] as [number, number])
        : aheadPoint(vehicle.path && vehicle.path.length > 1 ? vehicle.path : [pos, ...(detail?.legs[0] ?? []).slice(1)]);
    if (towards) lastHeading.current = heading(pos, towards);
    const down = vehicle.status === "out_of_service";
    const html = heli
      ? `<div class="nav-veh heli${vehicle.grounded_until ? " grounded" : ""}"><span>🚁</span></div>`
      : `<div class="nav-veh${down ? " down" : ""}" style="transform: rotate(${Math.round(lastHeading.current)}deg)"><svg viewBox="0 0 40 40"><path d="M20 3 L34 35 L20 27 L6 35 Z"/></svg></div>`;
    const key = html;
    if (!ls.marker) {
      ls.marker = L.marker(pos, {
        icon: L.divIcon({ className: "veh-marker", html, iconSize: [44, 44], iconAnchor: [22, 22] }),
        interactive: false,
        keyboard: false,
        zIndexOffset: 1000,
      }).addTo(map);
      ls.markerKey = key;
    } else {
      ls.marker.setLatLng(pos);
      if (ls.markerKey !== key) {
        ls.marker.setIcon(L.divIcon({ className: "veh-marker", html, iconSize: [44, 44], iconAnchor: [22, 22] }));
        ls.markerKey = key;
      }
    }
    if (follow) map.panTo(pos, { animate: true, duration: 1.8, easeLinearity: 1 });
  }, [vehicle.lat, vehicle.lon, vehicle.path, vehicle.status, vehicle.grounded_until, detail, nav?.target, follow, heli]);

  return <div ref={el} className="nav-map" />;
}
