import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useMatch, useSearchParams } from "react-router";
import {
  API_URL,
  postEvent,
  useWorldState,
  type EventRecord,
  type Kpis,
  fetchVehicle,
  type Trip,
  type VehicleDetail,
  type World,
  type WorldSnapshot,
} from "./api";
import { AgentPanel, type AgentKeys } from "./AgentPanel";
import { BookingForm } from "./BookingForm";
import {
  Car,
  CircleAlert,
  CircleCheck,
  CloudRain,
  CloudSnow,
  Construction,
  Database,
  Octagon,
  PhoneIncoming,
  Sun,
  TrafficCone,
  X,
} from "lucide-react";
import { BRAND } from "./brand";
import { EventsPanel } from "./EventsPanel";
import { FieldMessage } from "./FieldMessage";
import { useHotkeys } from "./hotkeys";
import { ShortcutsHelp } from "./ShortcutsHelp";
import { CrewPage } from "./pages/CrewPage";
import { ScenariosPanel } from "./ScenariosPanel";
import { EmergencyPicker } from "./EmergencyPicker";
import { CallsPanel } from "./CallsPanel";
import { DemoButtons } from "./DemoButtons";
import { MissingEndpoint, randomCall, randomIncident, useDemoApi } from "./demoInject";
import { bilingualLines } from "./ErrorText";
import { VehicleCard } from "./VehicleCard";
import { VehicleStrip } from "./VehicleStrip";
import { OpsControls } from "./OpsControls";
import { fmtTime } from "./format";
import { compareTrips, LEVEL_RANK, levelOf, targetMisses, type ResponseInfo } from "./severity";
import { ResponseLine, SeverityBadge } from "./SeverityBadge";
import { doctorMisses, type DoctorInfo } from "./doctor";
import { DoctorTag, OriginTag } from "./DoctorTag";
import { MapView, type ClickMode } from "./MapView";
import { AuditPage } from "./pages/AuditPage";
import { FleetPage } from "./pages/FleetPage";

// The tablet view loads separately: its navigation map patches Leaflet for rotation (leaflet-rotate)
const TabletPage = lazy(() => import("./pages/TabletPage").then((m) => ({ default: m.TabletPage })));

type Send = (event: Record<string, unknown>) => Promise<void>;
type Toast = { kind: "ok" | "error"; text: string; sticky: boolean; n: number };
type Notify = (kind: "ok" | "error", text: string, sticky?: boolean) => void;
type Tab = "calls" | "dispatch" | "scenarios" | "events" | "book" | "alerts";

const unassignedTotal = (k: Kpis) => k.unassigned.emergency + k.unassigned.urgent + k.unassigned.scheduled;

function describe(rec: EventRecord): string {
  const b = rec.kpis_before;
  const a = rec.kpis_after;
  return (
    `${rec.summary}. ${rec.affected_trip_ids.length} trip(s) affected · ` +
    `late ${b.late_trips} → ${a.late_trips} · unassigned ${unassignedTotal(b)} → ${unassignedTotal(a)}`
  );
}

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Layout: header with navigation, then the routed page. Each page opens its own live connection. */
export default function App() {
  const crew = useMatch("/crew/*");
  const tablet = useMatch("/vehicle/*");
  const { pathname } = useLocation();
  // Fleet and Crew view follow the world of the dashboard you came from
  const [lastWorld, setLastWorld] = useState<World>("live");
  useEffect(() => {
    if (pathname === "/sim" || pathname === "/live") setLastWorld(pathname === "/sim" ? "sim" : "live");
  }, [pathname]);

  if (crew || tablet) {
    // Crew view (phone) and in-vehicle tablet: full screen, without the dispatcher header
    return (
      <Routes>
        <Route path="/crew/:vehicleId?" element={<CrewPage />} />
        <Route
          path="/vehicle/:vehicleId?"
          element={
            <Suspense fallback={<div className="loading">Loading the tablet view…</div>}>
              <TabletPage />
            </Suspense>
          }
        />
      </Routes>
    );
  }
  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <h1 className="wordmark">{BRAND.product}</h1>
          <span className="brand-sub">
            {BRAND.tagline} · <strong>{BRAND.operator}</strong>
          </span>
        </div>
        <nav className="nav">
          <NavLink to="/live">Live</NavLink>
          <NavLink to="/sim">Simulation</NavLink>
          <NavLink to={`/fleet?world=${lastWorld}`}>Fleet</NavLink>
          <NavLink to="/audit">Audit</NavLink>
          <NavLink to={`/crew?world=${lastWorld === "live" ? "live" : "sim"}`}>Crew view</NavLink>
        </nav>
        <span className="header-help muted">
          Press <kbd>?</kbd> for shortcuts
        </span>
      </header>
      <Routes>
        <Route path="/" element={<Navigate to="/live" replace />} />
        <Route path="/live" element={<WorldPage key="live" world="live" />} />
        <Route path="/sim" element={<WorldPage key="sim" world="sim" />} />
        <Route path="/fleet" element={<FleetRoute />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </div>
  );
}

function WorldPage({ world }: { world: World }) {
  const { state, connected } = useWorldState(world);
  if (!state) return <div className="loading">Connecting to {API_URL} …</div>;
  return (
    <>
      <StatusBar state={state} connected={connected} />
      <Dashboard state={state} />
    </>
  );
}

function FleetRoute() {
  const [params] = useSearchParams();
  const world: World = params.get("world") === "sim" ? "sim" : "live";
  return <FleetWorld key={world} world={world} />;
}

function FleetWorld({ world }: { world: World }) {
  const { state, connected } = useWorldState(world);
  if (!state) return <div className="loading">Connecting to {API_URL} …</div>;
  return (
    <>
      <StatusBar state={state} connected={connected} />
      <FleetPage state={state} />
    </>
  );
}

function NotFound() {
  return (
    <main className="page">
      <h2>Page not found</h2>
      <Link to="/">Back to the dashboard</Link>
    </main>
  );
}

function Dashboard({ state }: { state: WorldSnapshot }) {
  const world = state.world;
  const sim = state.hypothetical;
  const [mode, setMode] = useState<ClickMode>(null);
  const [pendingCall, setPendingCall] = useState<{ lat: number; lon: number } | null>(null); // where the next emergency goes
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [cardOpen, setCardOpen] = useState(false); // full vehicle card (marker / trip row) vs the strip's drop-down
  const [detail, setDetail] = useState<VehicleDetail | null>(null);
  const [centerOn, setCenterOn] = useState<{ lat: number; lon: number; n: number } | null>(null);
  const [picked, setPicked] = useState(""); // vehicle chosen in the Events tab dropdown
  const [help, setHelp] = useState(false);
  const [tab, setTab] = useState<Tab>("calls"); // the panel starts from the calls
  const [callFocus, setCallFocus] = useState<{ tripId: string; n: number } | null>(null); // open this call's card
  const [callPoint, setCallPoint] = useState<{ lat: number; lon: number; n: number } | null>(null); // new call: map point
  const openCall = (tripId: string) => {
    setTab("calls");
    setCallFocus({ tripId, n: Date.now() });
  };
  // Demo injections (Simulation only; hidden until the backend has the endpoints)
  const [demo, demoMissing] = useDemoApi(sim);
  const [demoBusy, setDemoBusy] = useState(false);
  const injectCall = async (severity?: string) => {
    if (!demo.call || demoBusy) return;
    setDemoBusy(true);
    try {
      const { trip, summary } = await randomCall(severity);
      notify("ok", summary);
      if (trip) {
        openCall(trip.id);
        if (trip.vehicle_id) select(trip.vehicle_id, false);
      }
    } catch (e) {
      if (e instanceof MissingEndpoint) {
        demoMissing("call");
        notify("error", "Random calls need a newer backend: use E (emergency) instead.");
      } else notify("error", bilingualLines(errorText(e)));
    } finally {
      setTimeout(() => setDemoBusy(false), 600);
    }
  };
  const injectIncident = async (kind?: string) => {
    if (!demo.incident || demoBusy) return;
    setDemoBusy(true);
    try {
      const { event, summary } = await randomIncident(kind);
      notify("ok", summary);
      const tripId = event?.affected_trip_ids?.[0];
      const vehicleId = (event as { payload?: { vehicle_id?: string } } | null)?.payload?.vehicle_id;
      if (tripId) openCall(tripId);
      if (vehicleId) select(vehicleId, false);
      else if (tripId) {
        const v = state.trips.find((t) => t.id === tripId)?.vehicle_id;
        if (v) select(v, false);
      }
    } catch (e) {
      if (e instanceof MissingEndpoint) {
        demoMissing("incident");
        notify("error", "Random failures need a newer backend: use the Events tab instead.");
      } else notify("error", bilingualLines(errorText(e)));
    } finally {
      setTimeout(() => setDemoBusy(false), 600);
    }
  };
  const demoButtons = <DemoButtons api={demo} busy={demoBusy} onCall={(s) => void injectCall(s)} onIncident={(k) => void injectIncident(k)} />;
  const [unseenRun, setUnseenRun] = useState(false);
  const micToggle = useRef<(() => void) | null>(null);
  const agentKeys = useRef<AgentKeys | null>(null);

  // One selection for markers, trip rows and the vehicle strip; markers and rows open the full card
  const select = (id: string | null, card = true) => {
    setSelectedId(id);
    setCardOpen(id !== null && card);
  };
  const centerVehicle = (id: string) => {
    const v = state.vehicles.find((x) => x.id === id);
    if (v) setCenterOn({ lat: v.lat, lon: v.lon, n: Date.now() });
  };

  const notify: Notify = (kind, text, sticky = false) => setToast({ kind, text, sticky: sticky || kind === "error", n: Date.now() });

  // Toasts fade after a while; errors and notes marked sticky stay until closed or replaced
  useEffect(() => {
    if (!toast || toast.sticky) return;
    const timer = setTimeout(() => setToast((t) => (t?.n === toast.n ? null : t)), 9000);
    return () => clearTimeout(timer);
  }, [toast]);

  // A new AI analysis (scenario, field message, event, hotkey): bring the AI dispatcher into view,
  // except while booking, where switching would hide the booking result (a dot marks the tab instead)
  const latestRun = state.agent.runs[0];
  const lastRunId = useRef(latestRun?.id);
  useEffect(() => {
    if (!latestRun || latestRun.id === lastRunId.current) return;
    lastRunId.current = latestRun.id;
    if (tab === "book" || tab === "calls") setUnseenRun(true); // don't pull the dispatcher away from a form or a call
    else setTab("dispatch");
  }, [latestRun, tab]);
  useEffect(() => {
    if (tab === "dispatch") setUnseenRun(false);
  }, [tab]);

  // Selected vehicle: refresh its card and highlighted route every 3 s
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let stop = false;
    const load = () =>
      fetchVehicle(world, selectedId)
        .then((d) => !stop && setDetail(d))
        .catch(() => !stop && setDetail(null));
    void load();
    const timer = setInterval(load, 3000);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [world, selectedId]);

  const send: Send = async (event) => {
    setBusy(true);
    try {
      notify("ok", describe(await postEvent(world, event)));
    } catch (e) {
      notify("error", errorText(e));
    } finally {
      setBusy(false);
    }
  };

  // B/D act on the vehicle selected on the map (marker or trip row), never on some other vehicle
  const selectedVehicle = selectedId ? state.vehicles.find((v) => v.id === selectedId) : undefined;
  const onSelected = (what: string, fn: (id: string) => void) => {
    if (!selectedVehicle) notify("error", `Select a vehicle first (its marker, its chip above the map or a trip row), then press the key to ${what}.`);
    else if (selectedVehicle.status === "out_of_service") notify("error", `${selectedVehicle.name} is already out of service.`);
    else fn(selectedVehicle.id);
  };

  useHotkeys({
    m: () => {
      setTab("dispatch");
      micToggle.current?.();
    },
    a: () => {
      setTab("dispatch");
      agentKeys.current?.analyse();
    },
    y: () => {
      setTab("dispatch");
      agentKeys.current?.approveRecommended();
    },
    n: () => {
      setTab("dispatch");
      agentKeys.current?.reject();
    },
    b: () => onSelected("report a breakdown", (id) => void send({ type: "breakdown", vehicle_id: id, note: "reported by the operator, hotkey" })),
    d: () =>
      onSelected("delay it 10 min", (id) => void send({ type: "delay", vehicle_id: id, minutes: 10, note: "reported by the operator, hotkey" })),
    f: () => void send({ type: "fog", duration_min: 60 }),
    e: () => setMode((m) => (m === "emergency" ? null : "emergency")),
    c: () => setMode((m) => (m === "closure" ? null : "closure")),
    r: () => void injectCall(),
    x: () => void injectIncident(),
    Escape: () => {
      setMode(null);
      select(null);
      setToast(null);
    },
    "?": () => setHelp((h) => !h),
  });

  const onMapClick = (lat: number, lon: number) => {
    if (mode === "closure") {
      void send({ type: "road_closure", lat, lon, radius_m: 400, description: "Road closed (operator report)" });
    } else if (mode === "emergency") {
      setPendingCall({ lat, lon }); // what kind of emergency: the picker sends it
    } else if (mode === "call") {
      setCallPoint({ lat, lon, n: Date.now() }); // the new 112 call's location (the form in the Calls tab)
      setTab("calls");
    }
    setMode(null);
  };

  const misses = responseAlerts(state);
  const drMisses = doctorAlerts(state);
  const alertCount = misses.length + drMisses.length + state.alerts.length + state.incidents.filter((i) => i.active).length;
  const critical = misses.length > 0 || drMisses.length > 0 || state.alerts.some((a) => a.severity === "critical");
  const activeCalls = state.trips.filter((t) => t.status !== "completed" && t.status !== "cancelled").length;
  const waitingCalls = state.trips.filter((t) => t.status === "unassigned" && (t.severity === "critical" || t.severity === "serious")).length;
  const tabs: { id: Tab; label: string; badge?: string; hot?: boolean }[] = [
    { id: "calls", label: "Calls", badge: activeCalls ? String(activeCalls) : undefined, hot: waitingCalls > 0 },
    { id: "dispatch", label: "Dispatch", badge: unseenRun ? "New" : undefined, hot: unseenRun },
    ...(sim ? [{ id: "scenarios" as Tab, label: "Scenarios" }] : []),
    { id: "events", label: sim ? "Events" : "Report" },
    { id: "book", label: "Book" },
    { id: "alerts", label: "Alerts", badge: alertCount ? String(alertCount) : undefined, hot: critical },
  ];

  return (
    <main className="main">
      <ShortcutsHelp open={help} onClose={() => setHelp(false)} />
      <section className="map-col">
        <VehicleStrip
          state={state}
          selectedId={selectedId}
          onSelect={(id) => select(id, false)}
          onCenter={centerVehicle}
          onOpenCard={(id) => select(id, true)}
          onOpenCall={openCall}
          send={send}
          busy={busy}
        />
        <div className="map-wrap">
        {mode && (
          <div className="map-hint">
            {mode === "closure" ? <Construction /> : <CircleAlert />}
            Click the map to place the {mode === "closure" ? "road closure" : mode === "call" ? "112 call's location" : "emergency call"} ·{" "}
            <button className="link" onClick={() => setMode(null)}>
              cancel (Esc)
            </button>
          </div>
        )}
        {pendingCall && (
          <EmergencyPicker
            at={pendingCall}
            onCancel={() => setPendingCall(null)}
            onSend={(event) => {
              setPendingCall(null);
              void send(event);
            }}
          />
        )}
        <MapView
          state={state}
          mode={mode}
          pin={pendingCall}
          onMapClick={onMapClick}
          selectedId={selectedId}
          onSelect={(id) => select(id)}
          detail={detail}
          centerOn={centerOn}
        />
        <MapLegend />
        {detail && selectedId && cardOpen && (
          <VehicleCard
            detail={detail}
            state={state}
            busy={busy}
            send={send}
            onClose={() => select(null)}
            onOpenCall={openCall}
            onCenter={() => setCenterOn({ lat: detail.vehicle.lat, lon: detail.vehicle.lon, n: Date.now() })}
          />
        )}
        {toast && (
          <div className={`toast ${toast.kind}`} role="status" aria-live="polite">
            {toast.kind === "ok" ? <CircleCheck /> : <CircleAlert />}
            <span>{toast.text}</span>
            <button className="link toast-close" onClick={() => setToast(null)} aria-label="Dismiss">
              <X />
            </button>
          </div>
        )}
        </div>
      </section>
      <aside className="side">
        <KpiRow kpis={state.kpis} />
        <div className="side-tabs" role="tablist" aria-label="Dashboard sections">
          {tabs.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              className={`side-tab${tab === t.id ? " on" : ""}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
              {t.badge && <span className={`tab-badge${t.hot ? " hot" : ""}`}>{t.badge}</span>}
            </button>
          ))}
        </div>
        {/* Every tab stays mounted (hidden), so forms, results and the mic hotkey survive switching */}
        <div className="side-body" hidden={tab !== "calls"}>
          <CallsPanel
            state={state}
            focus={callFocus}
            picked={callPoint}
            onPickOnMap={() => setMode("call")}
            onSelectVehicle={(id, card) => select(id, card)}
            notify={notify}
            demo={demoButtons}
          />
        </div>
        <div className="side-body" hidden={tab !== "dispatch"}>
          <FieldMessage state={state} micToggleRef={micToggle} />
          <AgentPanel state={state} notify={notify} keysRef={agentKeys} />
        </div>
        {sim && (
          <div className="side-body" hidden={tab !== "scenarios"}>
            <Panel title="Scenarios">
              <ScenariosPanel state={state} notify={notify} extra={demoButtons} />
            </Panel>
          </div>
        )}
        <div className="side-body" hidden={tab !== "events"}>
          <Panel title={sim ? "What-if events (hypothetical)" : "Report an event"}>
            <EventsPanel state={state} busy={busy} mode={mode} setMode={setMode} send={send} picked={picked} setPicked={setPicked} />
          </Panel>
          <Panel title="Priority & capacity">
            <OpsControls state={state} send={send} busy={busy} />
          </Panel>
        </div>
        <div className="side-body" hidden={tab !== "book"}>
          <Panel title="Book transport">
            <BookingForm state={state} />
          </Panel>
        </div>
        <div className="side-body" hidden={tab !== "alerts"}>
          {!sim && (
            <Panel title="Live conditions">
              <Conditions state={state} />
            </Panel>
          )}
          <Panel title={`Alerts (${alertCount})`}>
            <Alerts state={state} send={send} />
          </Panel>
          <Panel title="Event log">
            <EventLog events={state.events} trips={state.trips} />
          </Panel>
        </div>
      </aside>
      <section className="trips">
        <TripTable state={state} selectedId={selectedId} onSelect={(id) => select(id)} />
      </section>
    </main>
  );
}

/** Where the calls come from: the demo's synthetic call stream (both worlds), or the scheduled day. */
function CallsChip({ state }: { state: WorldSnapshot }) {
  const c = state.calls;
  if (!c) return null;
  const text =
    state.mode === "scheduled_day"
      ? "Scheduled day (no call stream)"
      : !c.enabled
        ? "Call stream off"
        : c.paused_until
          ? `Synthetic calls paused until ${fmtTime(c.paused_until)}`
          : `Synthetic calls ${c.per_hour}/h`;
  const title =
    "Demo call generator: synthetic emergency calls and urgent transports, each dispatched at once by the engine" +
    (c.next_at ? `\nNext call ${fmtTime(c.next_at)}` : "") +
    `\n${c.generated} calls so far`;
  return (
    <span className="chip" title={title}>
      <PhoneIncoming /> {text}
    </span>
  );
}

function MapLegend() {
  return (
    <div className="map-legend" aria-label="Map legend">
      <span title="Open critical call (life-threatening now), until a unit reaches the patient">
        <i className="lg lg-crit" /> Critical call
      </span>
      <span title="Open serious call (may become life-threatening soon), until a unit reaches the patient">
        <i className="lg lg-ser" /> Serious call
      </span>
      <span title="Doctor car (doctor + nurse): drives to the scene, joins the ambulance crew, escorts the patient">
        <i className="lg lg-doctor" /> Doctor car
      </span>
      <span>
        <i className="lg lg-idle" /> Available
      </span>
      <span>
        <i className="lg lg-moving" /> To pickup
      </span>
      <span>
        <i className="lg lg-loaded" /> Patient on board
      </span>
      <span>
        <i className="lg lg-down" /> Out of service
      </span>
      <span>
        <i className="lg lg-detour" /> Detour
      </span>
      <span>
        <i className="lg lg-closure" /> Closure
      </span>
    </div>
  );
}

function StatusBar({ state, connected }: { state: WorldSnapshot; connected: boolean }) {
  const w = state.weather.now;
  const sources = Object.values(state.sources);
  const unhealthy = sources.filter((s) => s.health !== "fresh");
  const sourcesTitle =
    sources.map((s) => `${s.name}: ${s.health}${s.last_error ? ` (${s.last_error})` : ` · ${s.kind} · ${s.age_s ?? "–"} s old`}`).join("\n") +
    `\nRoad routes cached (OSRM / TomTom): ${state.roads.routes_cached}`;
  return (
    <div className={`statusbar ${state.hypothetical ? "is-sim" : "is-live"}`}>
      <span className="mode-badge">
        {state.hypothetical ? `Simulation · hypothetical · ${state.speedup}× speed` : "Live · real weather, traffic and incidents"}
      </span>
      <div className="chips">
        <span className={`chip ${connected ? "ok" : "bad"}`}>
          <i className="dot" /> {connected ? "Connected" : "Reconnecting"}
        </span>
        <span className="chip chip-strong">
          {state.hypothetical ? "Sim time" : "Time"} {fmtTime(state.sim_time)}
        </span>
        {w && (
          <span className={`chip ${state.weather.overridden ? "warn" : ""}`}>
            <WeatherIcon w={w} /> {w.temperature_c.toFixed(1)} °C ·{" "}
            {w.precipitation_mm} mm · {state.weather.overridden ? "demo override" : w.source}
          </span>
        )}
        <span
          className="chip"
          title={
            state.traffic.samples.map((s) => `${s.road}: ${s.current_kmh}/${s.free_flow_kmh} km/h`).join("\n") ||
            state.traffic.source
          }
        >
          <Car /> Traffic ×{state.traffic.factor.toFixed(2)} · {state.traffic.source === "tomtom" ? "TomTom live" : "profile"}
        </span>
        <CallsChip state={state} />
        <span
          className={`chip ${unhealthy.some((s) => s.health === "down") ? "bad" : unhealthy.length ? "warn" : "ok"}`}
          title={sourcesTitle}
        >
          <Database />
          {unhealthy.length
            ? unhealthy.map((s) => `${s.name}: ${s.health}`).join(" · ")
            : "Data feeds fresh"}
        </span>
        <TilesChip />
      </div>
    </div>
  );
}

/** The TomTom traffic layer's daily tile cap (from /health, once a minute): a quiet note when it's reached. */
function TilesChip() {
  const [tiles, setTiles] = useState<{ capped?: boolean; used?: string } | null>(null);
  useEffect(() => {
    let stop = false;
    const load = () =>
      fetch(`${API_URL}/health`)
        .then((r) => (r.ok ? r.json() : null))
        .then((h) => !stop && setTiles(h?.traffic_tiles ?? null))
        .catch(() => undefined);
    void load();
    const timer = setInterval(load, 60_000);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, []);
  if (!tiles?.capped) return null;
  return (
    <span className="chip warn" title={`TomTom traffic tiles today: ${tiles.used ?? "?"}. The free plan's quota is protected; the map shows no traffic colours until tomorrow (UTC).`}>
      <Car /> Traffic layer paused: daily tile limit
    </span>
  );
}

function WeatherIcon({ w }: { w: { snowfall_cm: number; precipitation_mm: number } }) {
  return w.snowfall_cm > 0 ? <CloudSnow /> : w.precipitation_mm > 0 ? <CloudRain /> : <Sun />;
}

function IncidentIcon({ kind }: { kind: string }) {
  return kind === "road_closure" ? <Octagon /> : kind === "accident" ? <CircleAlert /> : <TrafficCone />;
}

/** Live page: what the real world looks like right now. */
function Conditions({ state }: { state: WorldSnapshot }) {
  const w = state.weather.now;
  const nextHours = state.weather.forecast.filter((h) => new Date(h.time).getTime() > Date.now()).slice(0, 4);
  const live = state.incidents.filter((i) => i.source === "live");
  return (
    <div className="conditions">
      {w && (
        <div>
          <strong>
            <WeatherIcon w={w} /> {w.temperature_c.toFixed(1)} °C
          </strong>{" "}
          · {w.precipitation_mm} mm · wind {Math.round(w.wind_speed_kmh)} km/h <span className="muted">({w.source})</span>
          {nextHours.length > 0 && (
            <div className="muted">
              Next hours:{" "}
              {nextHours
                .map((h) => `${fmtTime(h.time)} ${Math.round(h.temperature_c)}°${h.snowfall_cm > 0 ? " snow" : h.precipitation_mm > 0 ? " rain" : ""}`)
                .join(" · ")}
            </div>
          )}
        </div>
      )}
      <div>
        <strong>Traffic ×{state.traffic.factor.toFixed(2)}</strong>{" "}
        <span className="muted">({state.traffic.source === "tomtom" ? "TomTom live" : state.traffic.source})</span>
        {state.traffic.samples.length > 0 && (
          <ul className="roads">
            {state.traffic.samples.map((s) => (
              <li key={s.road} className={s.ratio < 0.7 ? "slow" : ""}>
                {s.road}: {s.current_kmh}/{s.free_flow_kmh} km/h
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <strong>{live.length} live incident(s)</strong>
        {live.slice(0, 5).map((i) => (
          <div key={i.id} className="muted">
            <IncidentIcon kind={i.kind} /> {i.description}
          </div>
        ))}
      </div>
    </div>
  );
}

function KpiRow({ kpis }: { kpis: Kpis }) {
  const items: [string, string | number, boolean][] = [
    ["Open trips", kpis.open_trips, false],
    ["Late", kpis.late_trips, kpis.late_trips > 0],
    ["Delay min", Math.round(kpis.total_delay_min), kpis.total_delay_min >= 15],
    ["Unassigned", unassignedTotal(kpis), unassignedTotal(kpis) > 0],
    ["In service", kpis.vehicles_in_service, false],
  ];
  return (
    <div className="kpis">
      {items.map(([label, value, bad]) => (
        <div key={label} className={`kpi${bad ? " bad" : ""}`}>
          <div className="kpi-value">{value}</div>
          <div className="kpi-label">{label}</div>
        </div>
      ))}
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel">
      <h2 className="panel-title">{title}</h2>
      {children}
    </section>
  );
}

/** Critical and serious calls that will miss their response target (unless the backend already alerts on them). */
function responseAlerts(state: WorldSnapshot): { trip: Trip; r: ResponseInfo }[] {
  const covered = new Set(state.alerts.filter((a) => a.trip_id && /target|response/i.test(a.kind)).map((a) => a.trip_id));
  return targetMisses(state.trips, state.sim_time).filter((m) => !covered.has(m.trip.id));
}

/** Critical calls whose doctor (car or helicopter) will reach the scene after the target. */
function doctorAlerts(state: WorldSnapshot): { trip: Trip; d: DoctorInfo }[] {
  const covered = new Set(state.alerts.filter((a) => a.trip_id && /doctor/i.test(a.kind)).map((a) => a.trip_id));
  return doctorMisses(state.trips, state.vehicles, state.sim_time).filter((m) => !covered.has(m.trip.id));
}

function Alerts({ state, send }: { state: WorldSnapshot; send: Send }) {
  const incidents = state.incidents.filter((i) => i.active);
  const misses = responseAlerts(state);
  const drMisses = doctorAlerts(state);
  if (misses.length === 0 && drMisses.length === 0 && state.alerts.length === 0 && incidents.length === 0)
    return <p className="muted">All clear.</p>;
  return (
    <ul className="alerts">
      {misses.map(({ trip: t, r }) => (
        <li key={`target:${t.id}`} className={`alert target-miss lvl-${levelOf(t)}`}>
          <div className="target-miss-head">
            <SeverityBadge trip={t} modifiers={false} />
            <strong className="id">{t.id}</strong>
          </div>
          <div>
            {r.minutes == null
              ? `No unit yet: waiting ${Math.round(r.waited)} min, target ${r.target} min.`
              : `${t.vehicle_id ?? "The unit"} reaches the patient ${r.minutes} min after the call: target ${r.target} min, ${r.minutes - r.target} min over.`}
          </div>
        </li>
      ))}
      {drMisses.map(({ trip: t, d }) => (
        <li key={`doctor:${t.id}`} className={`alert target-miss lvl-${levelOf(t)}`}>
          <div className="target-miss-head">
            <SeverityBadge trip={t} weight={false} modifiers={false} />
            <strong className="id">{t.id}</strong>
            <DoctorTag trip={t} vehicles={state.vehicles} now={state.sim_time} />
          </div>
          <div>
            {d.minutes == null
              ? `Needs a doctor and none is free: waiting ${Math.round(d.waited)} min, target ${d.target} min to the scene.`
              : `Doctor ${d.vehicle} reaches the scene ${d.minutes} min after the call: target ${d.target} min, ${d.minutes - d.target} min over.`}
          </div>
        </li>
      ))}
      {incidents.map((inc) => (
        <li key={inc.id} className={`alert ${inc.kind === "congestion" ? "sev-medium" : "sev-high"}`}>
          <span>
            <IncidentIcon kind={inc.kind} /> {inc.description}
          </span>
          {inc.source === "injected" && (
            <button className="link" onClick={() => send({ type: "clear_incident", incident_id: inc.id })}>
              clear
            </button>
          )}
        </li>
      ))}
      {state.alerts.map((a) => (
        <li key={a.id} className={`alert sev-${a.severity}`}>
          {a.message}
        </li>
      ))}
    </ul>
  );
}

function EventLog({ events, trips }: { events: EventRecord[]; trips: Trip[] }) {
  if (events.length === 0) return <p className="muted">No events yet.</p>;
  const byId = new Map(trips.map((t) => [t.id, t]));
  // The most severe call an event touches (a new call, a priority change, a breakdown's patients…)
  const worst = (e: EventRecord) =>
    e.affected_trip_ids
      .map((id) => byId.get(id))
      .filter((t): t is Trip => Boolean(t))
      .sort((a, b) => LEVEL_RANK[levelOf(a)] - LEVEL_RANK[levelOf(b)])[0];
  return (
    <ul className="events">
      {[...events].reverse().map((e) => {
        const t = worst(e);
        return (
          <li key={e.id}>
            <span className="muted">{fmtTime(e.sim_time)}</span> {t && <SeverityBadge trip={t} compact />} {describe(e)}
          </li>
        );
      })}
    </ul>
  );
}

function TripTable({
  state,
  selectedId,
  onSelect,
}: {
  state: WorldSnapshot;
  selectedId: string | null;
  onSelect: (vehicleId: string | null) => void;
}) {
  const place = new Map(state.places.map((p) => [p.id, p.name]));
  const vehicleById = new Map(state.vehicles.map((v) => [v.id, v]));
  // Most severe first, then the most time-critical condition, then the earliest due
  const open = state.trips.filter((t) => t.status !== "completed" && t.status !== "cancelled").sort(compareTrips);
  const done = state.trips.length - open.length;

  return (
    <table className="trip-table">
      <thead>
        <tr>
          <th>Trip</th>
          <th>Patient / load</th>
          <th>Severity</th>
          <th title="Minutes from the call to reaching the patient / response target">Resp.</th>
          <th>Route</th>
          <th>Vehicle</th>
          <th>Status</th>
          <th>Due</th>
          <th>ETA</th>
          <th>Delay</th>
        </tr>
      </thead>
      <tbody>
        {open.map((t) => {
          const late = (t.delay_min ?? 0) >= 5;
          const route = `${place.get(t.pickup_id) ?? t.pickup_id} → ${place.get(t.dropoff_id) ?? t.dropoff_id}`;
          return (
            <tr
              key={t.id}
              className={`${t.status === "unassigned" ? "row-unassigned" : late ? "row-late" : ""}${
                t.vehicle_id && t.vehicle_id === selectedId ? " row-selected" : ""
              }${t.vehicle_id ? " clickable" : ""}`}
              onClick={() => t.vehicle_id && onSelect(t.vehicle_id)}
              title={t.vehicle_id ? `Show ${t.vehicle_id} on the map` : undefined}
            >
              <td className="id">{t.id}</td>
              <td className="cell-clip" title={`${t.label ?? t.patient ?? ""}${t.kind === "patient" ? ` · ${t.needs}` : ""}`}>
                {t.label ?? t.patient}
                {t.kind === "patient" && <span className="muted"> · {t.needs}</span>}
              </td>
              <td className="cell-sev">
                <SeverityBadge trip={t} />
              </td>
              <td className="cell-resp">
                <ResponseLine trip={t} now={state.sim_time} compact />
                <DoctorTag trip={t} vehicles={state.vehicles} now={state.sim_time} compact />
              </td>
              <td className="cell-clip cell-route" title={route}>
                {route}
              </td>
              <td className={t.vehicle_id ? "id" : "muted"}>
                {t.vehicle_id ?? "—"}
                <OriginTag v={vehicleById.get(t.vehicle_id ?? "")} compact />
              </td>
              <td>{t.status === "en_route_pickup" ? "to pickup" : t.status === "onboard" ? "on board" : t.status.replace(/_/g, " ")}</td>
              <td>{fmtTime(t.due_by)}</td>
              <td>{fmtTime(t.eta_dropoff)}</td>
              <td className={late ? "late" : ""}>{t.delay_min == null ? "—" : late ? `+${Math.round(t.delay_min)} min` : "on time"}</td>
            </tr>
          );
        })}
      </tbody>
      <tfoot>
        <tr>
          <td colSpan={10} className="muted">
            {open.length} open · {done} completed · click a row to show its vehicle
          </td>
        </tr>
      </tfoot>
    </table>
  );
}
