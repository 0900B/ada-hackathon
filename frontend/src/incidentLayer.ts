/**
 * Road incidents on the maps (dashboard MapView and the tablet's NavMap), drawn along the road they
 * affect (`path` from the backend) instead of as a circle:
 * - closure (blocked): a thick red line with a white dashed core, a no-entry roundel at its middle;
 * - crash: the same line when the road is blocked (our crashes block), a solid red line for a live
 *   accident that only slows; a warning-triangle marker;
 * - congestion / traffic jam: a dark-amber line with a dark dotted core (traffic style), a car marker.
 * The jam's amber (#c9940a, yellow-brown) is kept apart from the bright orange of detour legs
 * (#f0883e, thinner and solid). Live feed incidents are dashed. Without a path: only the marker.
 */
import L from "leaflet";
import type { Incident } from "./api";
import { escapeHtml } from "./format";
import { GLYPH } from "./glyphs";

export const CLOSURE_COLOR = "#e5484d";
export const ACCIDENT_COLOR = "#d6336c"; // a live accident that slows (not blocking): crimson, not orange
export const JAM_COLOR = "#c9940a"; // dark amber; detour legs are #f0883e
const CASING = "#0b0f14";

export type IncidentLook = "closure" | "crash" | "jam";

/** Which symbol: a crash (an accident, or a closure after one), a jam, or a plain closure. */
export function incidentLook(inc: Pick<Incident, "kind" | "description">): IncidentLook {
  if (inc.kind === "congestion") return "jam";
  if (inc.kind === "accident" || /crash|collision|accident|nesreč|trčenj/i.test(inc.description)) return "crash";
  return "closure";
}

/** The point halfway along a polyline (by length), for the marker. */
function midpoint(path: [number, number][]): [number, number] {
  const seg = path.slice(1).map((p, i) => L.latLng(path[i]).distanceTo(L.latLng(p)));
  let goal = seg.reduce((a, b) => a + b, 0) / 2;
  for (let i = 0; i < seg.length; i++) {
    if (goal <= seg[i] && seg[i] > 0) {
      const f = goal / seg[i];
      const [a, b] = [path[i], path[i + 1]];
      return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
    }
    goal -= seg[i];
  }
  return path[path.length - 1];
}

export function incidentMarkerHtml(look: IncidentLook, live: boolean): string {
  const inner = look === "closure" ? "<span></span>" : look === "crash" ? GLYPH.crash : GLYPH.jam;
  return `<div class="inc-mk ${look}${live ? " live" : ""}">${inner}</div>`;
}

/**
 * Draw one incident into `group`: its road stretch (when known) and a small marker. tooltip: the
 * plain text on hover, escaped here (null = not interactive, e.g. on the tablet).
 */
export function drawIncident(group: L.LayerGroup, inc: Incident, tooltip: string | null, scale = 1): void {
  const look = incidentLook(inc);
  const live = inc.source === "live";
  const blocked = inc.kind === "road_closure";
  const path = inc.path && inc.path.length > 1 ? inc.path : null;
  const interactive = tooltip !== null;
  const lines: L.Polyline[] = [];
  if (path) {
    const w = (n: number) => n * scale;
    const color = look === "jam" ? JAM_COLOR : blocked ? CLOSURE_COLOR : ACCIDENT_COLOR;
    lines.push(L.polyline(path, { color: CASING, weight: w(11), opacity: live ? 0.35 : 0.55, lineCap: "butt", interactive }));
    lines.push(
      L.polyline(path, { color, weight: w(7), opacity: 0.95, lineCap: "butt", dashArray: live ? "14 7" : undefined, interactive }),
    );
    if (look === "jam") {
      lines.push(L.polyline(path, { color: "#2a1d00", weight: w(2.5), opacity: 0.9, dashArray: "2 7", lineCap: "round", interactive }));
    } else if (blocked) {
      lines.push(L.polyline(path, { color: "#ffffff", weight: w(2), opacity: 0.95, dashArray: "6 6", lineCap: "butt", interactive }));
    }
    for (const l of lines) l.addTo(group);
  }
  const size = Math.round((look === "closure" ? 18 : 22) * scale);
  const marker = L.marker(path ? midpoint(path) : [inc.lat, inc.lon], {
    icon: L.divIcon({ className: "", html: incidentMarkerHtml(look, live), iconSize: [size, size], iconAnchor: [size / 2, size / 2] }),
    interactive,
    keyboard: false,
    zIndexOffset: -300, // under vehicles and call markers
  }).addTo(group);
  if (tooltip !== null) {
    const safe = escapeHtml(tooltip); // the description can come from a live traffic feed
    marker.bindTooltip(safe);
    for (const l of lines) l.bindTooltip(safe, { sticky: true });
  }
}
