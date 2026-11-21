import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet-rotate"; // map bearing (patches the global L; this module is only loaded on the tablet route)
import { Crosshair, Map as MapIcon, Navigation as NavIcon, Route } from "lucide-react";
import { trafficTileUrl, type Incident, type Navigation, type Vehicle, type VehicleDetail } from "./api";
import { baseMaps, saveBase, savedBase, type BaseId } from "./basemaps";
import { GLYPH } from "./glyphs";

const ROUTE = "#4f8ff7"; // the leg being driven
const DETOUR = "#f0883e"; // legs that go around a road closure
const FLIGHT = "#4f8ff7";

/** heading: course-up, the map turns with the vehicle; north: north-up and following; overview: the whole route. */
export type NavView = "heading" | "north" | "overview";
const VIEW_KEY = "planb.navView";
const GLIDE_MS = 2000; // a snapshot arrives about every 2 s: the vehicle glides between them
const LOOKAHEAD_M = 70; // the heading is the direction of the road this far ahead
const AUTOZOOM_GAP_MS = 6000; // auto-zoom changes at most this often

function savedView(): NavView {
  try {
    const v = localStorage.getItem(VIEW_KEY);
    if (v === "heading" || v === "north" || v === "overview") return v;
  } catch {
    /* storage blocked */
  }
  return "heading";
}

interface Props {
  vehicle: Vehicle;
  detail: VehicleDetail | null;
  nav: Navigation | null;
  incidents: Incident[];
}

const toRad = (d: number) => (d * Math.PI) / 180;
const norm = (d: number) => ((d % 360) + 360) % 360;
/** Signed shortest turn from a to b in degrees (-180..180]: 359° -> 1° is +2°, not -358°. */
const turn = (a: number, b: number) => ((b - a + 540) % 360) - 180;

/** Bearing in degrees from a to b (0 = north, clockwise). */
function bearing(a: [number, number], b: [number, number]): number {
  const p1 = toRad(a[0]);
  const p2 = toRad(b[0]);
  const dl = toRad(b[1] - a[1]);
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return norm((Math.atan2(y, x) * 180) / Math.PI);
}

/** The point `m` metres along a polyline (or its end). */
function along(line: [number, number][], m: number): [number, number] | null {
  let left = m;
  for (let i = 1; i < line.length; i++) {
    const [alat, alon] = line[i - 1];
    const [blat, blon] = line[i];
    const d = Math.hypot((blat - alat) * 111_320, (blon - alon) * 111_320 * Math.cos(toRad(alat)));
    if (d >= left && d > 0) return [alat + ((blat - alat) * left) / d, alon + ((blon - alon) * left) / d];
    left -= d;
  }
  return line.length > 1 ? line[line.length - 1] : null;
}

type LL = [number, number];
const metres = (a: LL, b: LL) => Math.hypot((b[0] - a[0]) * 111_320, (b[1] - a[1]) * 111_320 * Math.cos(toRad(a[0])));
const lengthOf = (line: LL[]) => line.reduce((sum, p, i) => (i ? sum + metres(line[i - 1], p) : 0), 0);

/** Where p projects onto a polyline: distance along it and how far off it p is (metres). */
function project(line: LL[], p: LL): { d: number; off: number } {
  const kx = 111_320 * Math.cos(toRad(p[0]));
  let best = { d: 0, off: Infinity };
  let acc = 0;
  for (let i = 1; i < line.length; i++) {
    const ax = (line[i - 1][1] - p[1]) * kx;
    const ay = (line[i - 1][0] - p[0]) * 111_320;
    const dx = (line[i][1] - p[1]) * kx - ax;
    const dy = (line[i][0] - p[0]) * 111_320 - ay;
    const len2 = dx * dx + dy * dy;
    const t = len2 > 0 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2)) : 0;
    const off = Math.hypot(ax + t * dx, ay + t * dy);
    if (off < best.off) best = { d: acc + t * Math.sqrt(len2), off };
    acc += Math.sqrt(len2);
  }
  return best;
}

/** The part of a polyline between distances a and b along it. */
function slice(line: LL[], a: number, b: number): LL[] {
  const out: LL[] = [];
  const start = along(line, a);
  if (start) out.push(start);
  let acc = 0;
  for (let i = 1; i < line.length; i++) {
    acc += metres(line[i - 1], line[i]);
    if (acc >= b) break;
    if (acc > a) out.push(line[i]);
  }
  const end = along(line, b);
  if (end) out.push(end);
  return out;
}

/** The polylines joined end to end, from `m` metres along onwards (its first point is the point at m). */
function tail(lines: LL[][], m: number): LL[] {
  const out: LL[] = [];
  let left = m;
  let last: LL | null = null;
  for (const line of lines) {
    for (let i = 1; i < line.length; i++) {
      if (out.length) {
        out.push(line[i]);
        continue;
      }
      const d = metres(line[i - 1], line[i]);
      if (d > 0 && d >= left) {
        const f = left / d;
        out.push([line[i - 1][0] + (line[i][0] - line[i - 1][0]) * f, line[i - 1][1] + (line[i][1] - line[i - 1][1]) * f], line[i]);
      } else left -= d;
    }
    if (line.length) last = line[line.length - 1];
  }
  return out.length ? out : last ? [last] : [];
}

/** Map centre that puts the vehicle in the middle (north-up) or in the lower third (heading-up) at `zoom`. */
function followCentre(map: L.Map, s: { pos: LL; view: NavView; shownHeading: number }, zoom: number): LL {
  if (s.view !== "heading") return s.pos;
  const mpp = (40_075_016.686 * Math.cos(toRad(s.pos[0]))) / 2 ** (zoom + 8);
  return offset(s.pos, s.shownHeading, (map.getSize().y / 6) * mpp);
}

/** The point `m` metres from p in direction `deg`. */
function offset(p: [number, number], deg: number, m: number): [number, number] {
  return [p[0] + (m * Math.cos(toRad(deg))) / 111_320, p[1] + (m * Math.sin(toRad(deg))) / (111_320 * Math.cos(toRad(p[0])))];
}

/**
 * Navigation map for the in-vehicle tablet, like a car's navigation unit:
 * - heading-up (default while driving): the map turns so the road ahead points up, the vehicle sits
 *   in the lower third; north-up: centred on the vehicle; overview: the whole remaining route.
 * - The vehicle glides between position updates; heading and map bearing ease (the short way round)
 *   and come from the road geometry ahead, so nothing jitters or spins while standing still.
 * - Panning by hand pauses following (Re-centre resumes); zooming by hand stops auto-zoom.
 * Markers (vehicle, stops, closures) stay upright; only tiles and lines turn.
 */
export function NavMap({ vehicle, detail, nav, incidents }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layers = useRef<{
    route: L.LayerGroup;
    incidents: L.LayerGroup;
    marker: L.Marker | null;
    markerKey: string;
    driven: L.Polyline[] | null; // casing and line of the leg being driven (or the flight line)
  } | null>(null);
  const heli = vehicle.type === "helicopter";

  const [view, setViewState] = useState<NavView>(savedView);
  const [follow, setFollow] = useState(true);
  const [manualZoom, setManualZoom] = useState(false);
  const [compass, setCompass] = useState(0); // map bearing, for the compass needle
  const lastFollowView = useRef<"heading" | "north">(view === "north" ? "north" : "heading");

  // Everything the animation loop needs, without re-creating it
  const live = useRef({
    view,
    follow,
    to: [vehicle.lat, vehicle.lon] as LL, // the latest reported position
    pos: [vehicle.lat, vehicle.lon] as LL, // where the marker is drawn
    glide: [[vehicle.lat, vehicle.lon]] as LL[], // how the marker gets there: along the road it was on
    glideLen: 0,
    t0: 0,
    road: [] as LL[], // the road ahead from `to` (the snapshot's path) while driving
    moving: false,
    target: null as LL | null, // helicopter: where it flies
    lastTrim: 0,
    heading: 0, // target heading of the vehicle (deg)
    shownHeading: 0,
    shownBearing: 0, // map bearing as shown (deg)
    hasHeading: false,
    programmaticZoom: false,
    lastAutoZoom: 0,
    compassShown: 0,
  });
  live.current.view = view;
  live.current.follow = follow;

  const setView = (v: NavView) => {
    setViewState(v);
    if (v !== "overview") lastFollowView.current = v;
    setFollow(true);
    setManualZoom(false);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* not remembered */
    }
  };

  // --- the map -------------------------------------------------------------------------------
  useEffect(() => {
    if (!box.current) return;
    const el = box.current;
    const map = L.map(el, {
      zoomControl: false,
      rotate: true,
      bearing: 0,
      touchRotate: false,
      shiftKeyRotate: false,
      rotateControl: false,
    }).setView([vehicle.lat, vehicle.lon], heli ? 12 : 16);
    L.control.zoom({ position: "bottomright" }).addTo(map);
    const bases = baseMaps();
    const initial = savedBase();
    bases[initial].layer.addTo(map);
    el.dataset.base = initial;
    map.on("baselayerchange", (e: L.LayersControlEvent) => {
      const id = (Object.keys(bases) as BaseId[]).find((k) => bases[k].layer === e.layer);
      if (id) {
        el.dataset.base = id;
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
        { "Traffic (TomTom)": traffic },
        { position: "topright" },
      )
      .addTo(map);
    layers.current = { route: L.layerGroup().addTo(map), incidents: L.layerGroup().addTo(map), marker: null, markerKey: "", driven: null };
    // Panning by hand pauses following; zooming by hand stops auto-zoom (both until Re-centre)
    map.on("dragstart", () => setFollow(false));
    map.on("zoomstart", () => {
      if (!live.current.programmaticZoom) setManualZoom(true);
    });
    map.on("zoomend", () => {
      live.current.programmaticZoom = false;
    });
    const resize = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    resize.observe(el);
    mapRef.current = map;
    return () => {
      resize.disconnect();
      map.remove();
      mapRef.current = null;
      layers.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- once per vehicle (the page is keyed by it)

  // --- position and heading from each snapshot ----------------------------------------------
  useEffect(() => {
    const s = live.current;
    const now = performance.now();
    const to: LL = [vehicle.lat, vehicle.lon];
    const moving =
      ["to_pickup", "with_patient", "returning"].includes(vehicle.status) && !vehicle.busy_until && !vehicle.waiting_until;
    const leg = detail?.vehicle.id === vehicle.id ? detail.legs[0] : undefined;
    const road: LL[] =
      heli || !moving ? [] : vehicle.path && vehicle.path.length > 1 ? vehicle.path : leg && leg.length > 1 ? [to, ...leg.slice(1)] : [];
    if (to[0] !== s.to[0] || to[1] !== s.to[1]) {
      // Glide from where the marker is drawn now to the new position, along the road it was driving
      // (a straight line would cut corners at bends); a long jump (reset, new world) is not animated.
      const shown = tail([s.glide, s.road], Math.min(1, (now - s.t0) / GLIDE_MS) * s.glideLen)[0] ?? s.to;
      let glide: LL[] = [shown, to];
      if (metres(shown, to) > 3000) glide = [to];
      else if (s.road.length > 1) {
        const a = project(s.road, shown);
        const b = project(s.road, to);
        if (a.off < 40 && b.off < 40 && b.d >= a.d) glide = [shown, ...slice(s.road, a.d, b.d), to];
      }
      s.glide = glide;
      s.glideLen = lengthOf(glide);
      s.t0 = now;
      s.to = to;
    }
    s.road = road;
    s.moving = moving;
    s.target = heli && nav?.target ? [nav.target.lat, nav.target.lon] : null;
    // Before it first moves: face the road ahead or the next stop (afterwards a stop keeps the last heading)
    if (!s.hasHeading) {
      const ahead = road.length > 1 ? along(road, LOOKAHEAD_M) : nav?.target ? ([nav.target.lat, nav.target.lon] as LL) : null;
      if (ahead && metres(to, ahead) > 8) {
        s.heading = s.shownHeading = bearing(to, ahead);
        s.hasHeading = true;
      }
    }
  }, [vehicle.lat, vehicle.lon, vehicle.path, vehicle.status, vehicle.busy_until, vehicle.waiting_until, vehicle.id, heli, nav?.target, detail]);

  // --- the vehicle marker (upright; the arrow is turned by the animation loop) ----------------
  useEffect(() => {
    const ls = layers.current;
    const map = mapRef.current;
    if (!ls || !map) return;
    const down = vehicle.status === "out_of_service";
    const html = heli
      ? `<div class="nav-veh heli${vehicle.grounded_until ? " grounded" : ""}">${GLYPH.helicopter}</div>`
      : `<div class="nav-veh${down ? " down" : ""}"><svg viewBox="0 0 40 40"><path d="M20 3 L34 35 L20 27 L6 35 Z"/></svg></div>`;
    if (!ls.marker) {
      ls.marker = L.marker([vehicle.lat, vehicle.lon], {
        icon: L.divIcon({ className: "veh-marker", html, iconSize: [44, 44], iconAnchor: [22, 22] }),
        interactive: false,
        keyboard: false,
        zIndexOffset: 1000,
      }).addTo(map);
      ls.markerKey = html;
    } else if (ls.markerKey !== html) {
      const node = ls.marker.getElement();
      if (node) node.innerHTML = html;
      ls.markerKey = html;
    }
  }, [vehicle.status, vehicle.grounded_until, heli, vehicle.lat, vehicle.lon]);

  // --- animation loop: glide, ease heading and bearing, follow ---------------------------------
  useEffect(() => {
    let raf = 0;
    const step = (now: number) => {
      raf = requestAnimationFrame(step);
      const map = mapRef.current;
      const marker = layers.current?.marker;
      if (!map || !marker) return;
      const s = live.current;
      const f = Math.min(1, (now - s.t0) / GLIDE_MS);
      // the rest of the way from where the marker is now: the remaining glide, then the road ahead
      const rest = tail([s.glide, s.road], f * s.glideLen);
      const pos: LL = rest[0] ?? s.to;
      s.pos = pos;
      const zooming = Boolean((map as unknown as { _animatingZoom?: boolean })._animatingZoom);
      const ll = marker.getLatLng();
      // (not during a zoom animation: the marker is placed for the new zoom until it ends)
      if (!zooming && (Math.abs(ll.lat - pos[0]) > 1e-7 || Math.abs(ll.lng - pos[1]) > 1e-7)) marker.setLatLng(pos);

      // heading: the road LOOKAHEAD_M ahead of the drawn position (or the flight target); kept when stopped
      const ahead = s.target ?? (s.moving && rest.length > 1 ? along(rest, LOOKAHEAD_M) : null);
      if (ahead && metres(pos, ahead) > 8) {
        s.heading = bearing(pos, ahead);
        s.hasHeading = true;
      }

      // the line being driven starts at the marker (trimmed a few times a second)
      const driven = layers.current?.driven;
      if (driven && (s.moving || s.target) && now - s.lastTrim > 120 && !zooming) {
        s.lastTrim = now;
        const line = s.target ? [pos, s.target] : rest.length > 1 ? rest : null;
        if (line) for (const pl of driven) pl.setLatLngs(line);
      }

      // heading eases towards the road ahead (about a second for a 90° turn)
      const dh = turn(s.shownHeading, s.heading);
      if (Math.abs(dh) > 0.05) s.shownHeading = norm(s.shownHeading + dh * 0.08);

      // map bearing: heading-up turns the map against the heading; north-up and overview: 0
      const target = s.view === "heading" && s.follow ? norm(-s.shownHeading) : s.view === "heading" ? s.shownBearing : 0;
      const db = turn(s.shownBearing, target);
      if (Math.abs(db) > 0.05 && !zooming) {
        s.shownBearing = norm(s.shownBearing + (Math.abs(db) < 0.5 ? db : db * 0.12));
        map.setBearing(s.shownBearing);
      }
      if (Math.abs(turn(s.compassShown, s.shownBearing)) > 1) {
        s.compassShown = s.shownBearing;
        setCompass(Math.round(s.shownBearing));
      }

      // the arrow points along the heading on screen (straight up in heading-up mode)
      const arrow = marker.getElement()?.querySelector<HTMLElement>(".nav-veh:not(.heli)");
      if (arrow) arrow.style.transform = `rotate(${Math.round(norm(s.shownHeading + s.shownBearing) * 10) / 10}deg)`;

      // following: keep the vehicle centred (north-up) or in the lower third (heading-up)
      if (s.follow && s.view !== "overview" && !zooming) {
        const size = map.getSize();
        const p = map.latLngToContainerPoint(followCentre(map, s, map.getZoom()));
        const dx = p.x - size.x / 2;
        const dy = p.y - size.y / 2;
        if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) map.panBy([dx, dy], { animate: false });
      }
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, []);

  // --- overview: fit the whole remaining route, north-up ----------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || view !== "overview") return;
    const pts: [number, number][] = [[vehicle.lat, vehicle.lon]];
    for (const leg of detail?.legs ?? []) pts.push(...leg);
    for (const s of detail?.stops ?? []) pts.push([s.lat, s.lon]);
    if (nav?.target) pts.push([nav.target.lat, nav.target.lon]);
    live.current.shownBearing = 0;
    map.setBearing(0);
    live.current.programmaticZoom = true;
    map.fitBounds(L.latLngBounds(pts), { padding: [48, 48], maxZoom: 16, animate: true });
    // only when entering overview (and once the route is known), not on every update
  }, [view, Boolean(detail)]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- calm auto-zoom while following in heading-up mode ------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || heli || view !== "heading" || !follow || manualZoom) return;
    const next = nav?.steps[0]?.distance_m;
    const want = next == null ? 16 : next < 300 ? 17 : next < 2000 ? 16 : 15;
    const now = performance.now();
    if (want !== map.getZoom() && now - live.current.lastAutoZoom > AUTOZOOM_GAP_MS) {
      live.current.lastAutoZoom = now;
      live.current.programmaticZoom = true;
      // zoom about the follow position so the vehicle keeps its place on screen
      map.setView(followCentre(map, live.current, want), want, { animate: true });
    }
  }, [nav, view, follow, manualZoom, heli]);

  // --- re-entering a follow mode: back to the default zoom if the user zoomed or we were in overview
  const recentre = () => {
    const map = mapRef.current;
    setViewState(lastFollowView.current);
    setFollow(true);
    setManualZoom(false);
    if (map) {
      const zoom = heli ? 12 : 16;
      live.current.programmaticZoom = true;
      map.setView(followCentre(map, { ...live.current, view: lastFollowView.current }, zoom), zoom, { animate: true });
    }
  };

  // Closures and incidents
  useEffect(() => {
    const ls = layers.current;
    if (!ls) return;
    ls.incidents.clearLayers();
    for (const inc of incidents) {
      if (!inc.active) continue;
      const color = inc.kind === "congestion" ? "#d6a23a" : "#f2555a";
      L.circle([inc.lat, inc.lon], { radius: inc.radius_m, color, weight: 3, fillColor: color, fillOpacity: 0.2, interactive: false }).addTo(ls.incidents);
      L.marker([inc.lat, inc.lon], {
        icon: L.divIcon({ className: "", html: `<div class="nav-incident ${inc.kind}">${inc.kind === "congestion" ? GLYPH.cone : GLYPH.closure}</div>`, iconSize: [26, 26], iconAnchor: [13, 13] }),
        interactive: false,
        keyboard: false,
      }).addTo(ls.incidents);
    }
  }, [incidents]);

  // Route, stops and the flight line (refreshed with the vehicle detail and each snapshot)
  useEffect(() => {
    const ls = layers.current;
    if (!ls) return;
    ls.route.clearLayers();
    ls.driven = null;
    const legs = detail?.vehicle.id === vehicle.id ? detail.legs : [];
    const detours = new Set(detail?.detour_legs ?? []);
    // the rest of the day first (dimmed), then the leg being driven on top
    legs.slice(1).forEach((leg, i) => {
      if (leg.length > 1)
        L.polyline(leg, { color: detours.has(i + 1) ? DETOUR : "#9aa6b4", weight: 4, opacity: 0.4, dashArray: "6 8", interactive: false }).addTo(ls.route);
    });
    // The leg being driven: the snapshot's live remaining path (every tick), else the detail's
    // (the animation loop then keeps its start at the gliding marker)
    const current = vehicle.path && vehicle.path.length > 1 ? vehicle.path : legs[0];
    if (heli && nav?.target) {
      const line: [number, number][] = [
        [vehicle.lat, vehicle.lon],
        [nav.target.lat, nav.target.lon],
      ];
      ls.driven = [
        L.polyline(line, { color: "#05080c", weight: 9, opacity: 0.5, interactive: false }).addTo(ls.route),
        L.polyline(line, { color: FLIGHT, weight: 4, dashArray: "10 8", interactive: false }).addTo(ls.route),
      ];
    } else if (current && current.length > 1) {
      ls.driven = [
        L.polyline(current, { color: "#05080c", weight: 13, opacity: 0.55, interactive: false }).addTo(ls.route),
        L.polyline(current, { color: detours.has(0) ? DETOUR : ROUTE, weight: 8, opacity: 1, interactive: false }).addTo(ls.route),
      ];
    }
    live.current.lastTrim = 0; // trim the new lines on the next frame
    (detail?.vehicle.id === vehicle.id ? detail.stops : []).forEach((s, i) => {
      const icon = L.divIcon({
        className: "",
        html: `<div class="nav-stop nav-stop-${s.kind}${i === 0 ? " next" : ""}">${s.kind === "base" ? GLYPH.base : i + 1}</div>`,
        iconSize: [30, 30],
        iconAnchor: [15, 15],
      });
      L.marker([s.lat, s.lon], { icon, interactive: false, keyboard: false }).addTo(ls.route);
    });
  }, [detail, nav?.target, vehicle.id, vehicle.lat, vehicle.lon, vehicle.path, heli]);

  const paused = view === "overview" || !follow || manualZoom;
  return (
    <div className="nav-wrap">
      <div ref={box} className="nav-map" />
      <div className="nav-views" role="group" aria-label="Map view">
        <button
          className={`mdt-btn${view === "heading" ? " on" : ""}`}
          aria-pressed={view === "heading"}
          onClick={() => setView("heading")}
          title="Heading up: the map turns with the vehicle"
        >
          <NavIcon /> Heading up
        </button>
        <button
          className={`mdt-btn${view === "north" ? " on" : ""}`}
          aria-pressed={view === "north"}
          onClick={() => setView("north")}
          title="North up, following the vehicle"
        >
          <MapIcon /> North up
        </button>
        <button
          className={`mdt-btn${view === "overview" ? " on" : ""}`}
          aria-pressed={view === "overview"}
          onClick={() => setView("overview")}
          title="The whole remaining route"
        >
          <Route /> Overview
        </button>
      </div>
      <button className="mdt-btn nav-compass" onClick={() => setView("north")} title="North up" aria-label={`Compass, map bearing ${compass}°: tap for north up`}>
        <svg viewBox="0 0 40 40" style={{ transform: `rotate(${compass}deg)` }} aria-hidden>
          <path className="needle-n" d="M20 4 L26 20 L14 20 Z" />
          <path className="needle-s" d="M20 36 L26 20 L14 20 Z" />
        </svg>
      </button>
      {paused && (
        <button className="mdt-btn nav-recentre" onClick={recentre}>
          <Crosshair /> {view === "overview" ? "Follow" : "Re-centre"}
        </button>
      )}
    </div>
  );
}
