import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { Crosshair } from "lucide-react";
import { fetchVehicle } from "./api";
import type { CaseCard, LatLng, VehicleTrack, World } from "./api";
import { clock } from "./format";

const UKC: LatLng = [46.0563, 14.5232]; // UKC Ljubljana, used when the unit has no drop-off stop left
const TRACK_MS = 2000;

const STATUS_TEXT: Record<string, string> = {
  idle: "Waiting at base",
  returning: "Returning to base",
  en_route: "On the way to the patient",
  en_route_pickup: "On the way to the patient",
  loading: "At the patient",
  with_patient: "Patient on board, driving to the ER",
  waiting: "Waiting at the scene",
};

/** Position, route and stops of the unit on one case, refreshed every 2 s while the popup is open. */
function useTrack(world: World, vehicleId: string | null) {
  const [track, setTrack] = useState<VehicleTrack | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setTrack(null);
    setError(null);
    if (!vehicleId) return;
    let stopped = false;
    let busy = false;
    const ctl = new AbortController();
    const tick = async () => {
      if (busy || document.hidden) return;
      busy = true;
      try {
        const t = await fetchVehicle(world, vehicleId, ctl.signal);
        if (!stopped) {
          setTrack(t);
          setError(null);
        }
      } catch (e) {
        if (!stopped && (e as Error).name !== "AbortError") setError((e as Error).message);
      } finally {
        busy = false;
      }
    };
    tick();
    const id = window.setInterval(tick, TRACK_MS);
    return () => {
      stopped = true;
      ctl.abort();
      window.clearInterval(id);
    };
  }, [world, vehicleId]);
  return { track, error };
}

/** Leaflet puts icon HTML and string tooltips into the page as markup, and the texts here come from the
 * server (vehicle ids, pickup addresses typed by callers): escape them, and give tooltips as text nodes. */
const esc = (s: string) => s.replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch] as string);
const textNode = (s: string) => {
  const span = document.createElement("span");
  span.textContent = s;
  return span;
};
const icon = (cls: "pin-unit" | "pin-er" | "pin-patient", label: string, size: number) =>
  L.divIcon({ className: "", html: `<div class="pin ${cls}">${esc(label)}</div>`, iconSize: [size, size], iconAnchor: [size / 2, size / 2] });

export function MapPanel({ world, c }: { world: World; c: CaseCard }) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const trail = useRef<LatLng[]>([]);
  const fitted = useRef<string>("");
  const { track, error } = useTrack(world, c.vehicle_id);

  // create the map once
  useEffect(() => {
    if (!el.current) return;
    const m = L.map(el.current, { zoomControl: true, attributionControl: true }).setView(UKC, 12);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      className: "dark-tiles",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(m);
    layer.current = L.layerGroup().addTo(m);
    map.current = m;
    const ro = new ResizeObserver(() => m.invalidateSize());
    ro.observe(el.current);
    return () => {
      ro.disconnect();
      m.remove();
      map.current = null;
      layer.current = null;
    };
  }, []);

  // a different unit means a different trail
  useEffect(() => {
    trail.current = [];
    fitted.current = "";
  }, [c.case_id, c.vehicle_id]);

  // redraw on every fresh position
  useEffect(() => {
    const m = map.current;
    const g = layer.current;
    if (!m || !g) return;
    g.clearLayers();
    const points: LatLng[] = [];

    const mine = track?.stops.filter((s) => s.trip_id === c.case_id) ?? [];
    const dropIdx = track?.stops.findIndex((s) => s.trip_id === c.case_id && s.kind === "dropoff") ?? -1;
    const pickup = mine.find((s) => s.kind === "pickup");
    const drop = mine.find((s) => s.kind === "dropoff");
    const hospital: LatLng = drop ? [drop.lat, drop.lon] : UKC;

    if (track && dropIdx >= 0) {
      // the road from the unit to this case's drop-off, leg by leg (a leg ends at the stop with the same index)
      track.legs.slice(0, dropIdx + 1).forEach((leg) => {
        if (leg.length > 1) {
          L.polyline(leg, { color: "#5a9bff", weight: 5, opacity: 0.9 }).addTo(g);
          points.push(...leg);
        }
      });
    }
    if (trail.current.length > 1) L.polyline(trail.current, { color: "#94a1b0", weight: 3, opacity: 0.7, dashArray: "2 7" }).addTo(g);

    if (pickup) {
      L.marker([pickup.lat, pickup.lon], { icon: icon("pin-patient", "P", 28), title: "Patient" })
        .bindTooltip(textNode(pickup.place ?? "Patient"), { direction: "top" })
        .addTo(g);
      points.push([pickup.lat, pickup.lon]);
    }
    L.marker(hospital, { icon: icon("pin-er", "ER", 34), title: "Emergency department" }).bindTooltip("Emergency department", { direction: "top" }).addTo(g);
    points.push(hospital);

    if (track) {
      const pos: LatLng = [track.vehicle.lat, track.vehicle.lon];
      const last = trail.current[trail.current.length - 1];
      if (!last || last[0] !== pos[0] || last[1] !== pos[1]) trail.current = [...trail.current.slice(-120), pos];
      L.marker(pos, { icon: icon("pin-unit", track.vehicle.id, 38), zIndexOffset: 1000, title: track.vehicle.name })
        .bindTooltip(textNode(track.vehicle.name), { direction: "top" })
        .addTo(g);
      points.push(pos);
    }

    // frame everything once per unit and stage; after that the person can pan and zoom freely
    const fitKey = `${c.case_id}|${c.vehicle_id}|${c.stage}`;
    if (points.length && fitted.current !== fitKey) {
      fitted.current = fitKey;
      m.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 15 });
    }
  }, [track, c.case_id, c.vehicle_id, c.stage]);

  const recentre = () => {
    const m = map.current;
    if (!m || !track) return;
    m.setView([track.vehicle.lat, track.vehicle.lon], Math.max(m.getZoom(), 14));
  };

  const nextStop = track?.stops.find((s) => s.trip_id === c.case_id);
  return (
    <section className="map-panel" aria-label="Live tracking">
      <div className="map-box">
        <div ref={el} className="map" role="application" aria-label="Map with the ambulance and its route" />
        {track && (
          <button type="button" className="btn map-btn" onClick={recentre} title="Centre the map on the ambulance">
            <Crosshair size={16} aria-hidden /> Follow unit
          </button>
        )}
        {!c.vehicle_id && <div className="map-note">No unit is assigned yet, so there is nothing to track. The map starts as soon as dispatch assigns one.</div>}
      </div>
      <div className="map-meta" role="status">
        {c.vehicle_id ? (
          error && !track ? (
            <span className="bad">Tracking unavailable: {error}</span>
          ) : track ? (
            <>
              <strong>{track.vehicle.name}</strong>
              <span>{STATUS_TEXT[track.vehicle.status] ?? track.vehicle.status.replace(/_/g, " ")}</span>
              {nextStop?.eta && <span className="dim">next stop {clock(nextStop.eta)}</span>}
              {error && <span className="bad">Connection lost, position may be old</span>}
            </>
          ) : (
            <span className="dim">Locating {c.vehicle_id}…</span>
          )
        ) : null}
      </div>
    </section>
  );
}
