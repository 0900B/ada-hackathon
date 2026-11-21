import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useMatch, useSearchParams } from "react-router";
import {
  API_URL,
  postEvent,
  useWorldState,
  type EventRecord,
  type Kpis,
  type Priority,
  fetchVehicle,
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
import { TabletPage } from "./pages/TabletPage";
import { ScenariosPanel } from "./ScenariosPanel";
import { VehicleCard } from "./VehicleCard";
import { VehicleStrip } from "./VehicleStrip";
import { OpsControls } from "./OpsControls";
import { fmtTime } from "./format";
import { MapView, type ClickMode } from "./MapView";
import { AuditPage } from "./pages/AuditPage";
import { FleetPage } from "./pages/FleetPage";

type Send = (event: Record<string, unknown>) => Promise<void>;
type Toast = { kind: "ok" | "error"; text: string; sticky: boolean; n: number };
type Notify = (kind: "ok" | "error", text: string, sticky?: boolean) => void;
type Tab = "dispatch" | "scenarios" | "events" | "book" | "alerts";

const PRIORITY_ORDER: Record<Priority, number> = { emergency: 0, urgent: 1, scheduled: 2 };

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
        <Route path="/vehicle/:vehicleId?" element={<TabletPage />} />
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
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [cardOpen, setCardOpen] = useState(false); // full vehicle card (marker / trip row) vs the strip's drop-down
  const [detail, setDetail] = useState<VehicleDetail | null>(null);
  const [centerOn, setCenterOn] = useState<{ lat: number; lon: number; n: number } | null>(null);
  const [picked, setPicked] = useState(""); // vehicle chosen in the Events tab dropdown
  const [help, setHelp] = useState(false);
  const [tab, setTab] = useState<Tab>("dispatch");
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
    if (tab === "book") setUnseenRun(true);
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
    if (!selectedVehicle) notify("error", `Select a vehicle first (click its marker or a trip row), then press the key to ${what}.`);
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
    b: () => onSelected("report a breakdown", (id) => void send({ type: "breakdown", vehicle_id: id, note: "reported by operator (hotkey)" })),
    d: () =>
      onSelected("delay it 10 min", (id) => void send({ type: "delay", vehicle_id: id, minutes: 10, note: "reported by operator (hotkey)" })),
    f: () => void send({ type: "fog", duration_min: 60 }),
    e: () => setMode((m) => (m === "emergency" ? null : "emergency")),
    c: () => setMode((m) => (m === "closure" ? null : "closure")),
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
      void send({ type: "urgent_request", lat, lon, priority: "emergency", needs: "stretcher", dropoff_id: "ukc" });
    }
    setMode(null);
  };

  const alertCount = state.alerts.length + state.incidents.filter((i) => i.active).length;
  const critical = state.alerts.some((a) => a.severity === "critical");
  const tabs: { id: Tab; label: string; badge?: string; hot?: boolean }[] = [
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
          send={send}
          busy={busy}
        />
        <div className="map-wrap">
        {mode && (
          <div className="map-hint">
            {mode === "closure" ? <Construction /> : <CircleAlert />}
            Click the map to place the {mode === "closure" ? "road closure" : "emergency call"} ·{" "}
            <button className="link" onClick={() => setMode(null)}>
              cancel (Esc)
            </button>
          </div>
        )}
        <MapView
          state={state}
          mode={mode}
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
        <div className="side-body" hidden={tab !== "dispatch"}>
          <FieldMessage state={state} micToggleRef={micToggle} />
          <AgentPanel state={state} notify={notify} keysRef={agentKeys} />
        </div>
        {sim && (
          <div className="side-body" hidden={tab !== "scenarios"}>
            <Panel title="Scenarios">
              <ScenariosPanel state={state} notify={notify} />
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
            <EventLog events={state.events} />
          </Panel>
        </div>
      </aside>
      <section className="trips">
        <TripTable state={state} selectedId={selectedId} onSelect={(id) => select(id)} />
      </section>
    </main>
  );
}

function MapLegend() {
  return (
    <div className="map-legend" aria-label="Map legend">
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
        <span
          className={`chip ${unhealthy.some((s) => s.health === "down") ? "bad" : unhealthy.length ? "warn" : "ok"}`}
          title={sourcesTitle}
        >
          <Database />
          {unhealthy.length
            ? unhealthy.map((s) => `${s.name}: ${s.health}`).join(" · ")
            : `Data feeds fresh (${sources.map((s) => s.name).join(", ")})`}
        </span>
      </div>
    </div>
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

function Alerts({ state, send }: { state: WorldSnapshot; send: Send }) {
  const incidents = state.incidents.filter((i) => i.active);
  if (state.alerts.length === 0 && incidents.length === 0) return <p className="muted">All clear.</p>;
  return (
    <ul className="alerts">
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

function EventLog({ events }: { events: EventRecord[] }) {
  if (events.length === 0) return <p className="muted">No events yet.</p>;
  return (
    <ul className="events">
      {[...events].reverse().map((e) => (
        <li key={e.id}>
          <span className="muted">{fmtTime(e.sim_time)}</span> {describe(e)}
        </li>
      ))}
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
  const open = state.trips
    .filter((t) => t.status !== "completed" && t.status !== "cancelled")
    .sort(
      (a, b) =>
        Number(b.status === "unassigned") - Number(a.status === "unassigned") ||
        PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority] ||
        a.due_by.localeCompare(b.due_by),
    );
  const done = state.trips.length - open.length;

  return (
    <table className="trip-table">
      <thead>
        <tr>
          <th>Trip</th>
          <th>Patient / load</th>
          <th>Priority</th>
          <th>Needs</th>
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
              <td className="cell-clip" title={t.label ?? t.patient ?? ""}>
                {t.label ?? t.patient}
              </td>
              <td>
                <span className={`prio prio-${t.priority}`}>{t.priority}</span>
              </td>
              <td>{t.needs}</td>
              <td className="cell-clip cell-route" title={route}>
                {route}
              </td>
              <td className={t.vehicle_id ? "id" : "muted"}>{t.vehicle_id ?? "—"}</td>
              <td>{t.status.replace(/_/g, " ")}</td>
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
