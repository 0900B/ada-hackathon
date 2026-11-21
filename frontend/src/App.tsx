import { useEffect, useState, type ReactNode } from "react";
import { Link, Navigate, NavLink, Route, Routes } from "react-router";
import {
  API_URL,
  postEvent,
  resetWorld,
  runScenario,
  SCENARIOS,
  useWorldState,
  type EventRecord,
  type Kpis,
  type Priority,
  fetchVehicle,
  type VehicleDetail,
  type World,
  type WorldSnapshot,
} from "./api";
import { AgentPanel } from "./AgentPanel";
import { BRAND } from "./brand";
import { FieldMessage } from "./FieldMessage";
import { FogControl } from "./FogControl";
import { VehicleCard } from "./VehicleCard";
import { OpsControls } from "./OpsControls";
import { fmtTime } from "./format";
import { MapView, type ClickMode } from "./MapView";
import { AuditPage } from "./pages/AuditPage";
import { FleetPage } from "./pages/FleetPage";

type Send = (event: Record<string, unknown>) => Promise<void>;

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

/** Layout: header with navigation, then the routed page. Each page opens its own live connection. */
export default function App() {
  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <h1>🚑 {BRAND.product}</h1>
          <span className="brand-sub">
            {BRAND.tagline} · <strong>{BRAND.operator}</strong>
          </span>
        </div>
        <nav className="nav">
          <NavLink to="/live">● Live</NavLink>
          <NavLink to="/sim">Simulation</NavLink>
          <NavLink to="/fleet">Fleet</NavLink>
          <NavLink to="/audit">Audit</NavLink>
        </nav>
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
  const { state, connected } = useWorldState("live");
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
  const [mode, setMode] = useState<ClickMode>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<VehicleDetail | null>(null);
  const [centerOn, setCenterOn] = useState<{ lat: number; lon: number; n: number } | null>(null);

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
      setMessage({ kind: "ok", text: describe(await postEvent(world, event)) });
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  const onMapClick = (lat: number, lon: number) => {
    if (mode === "closure") {
      void send({ type: "road_closure", lat, lon, radius_m: 400, description: "Road closed (operator report)" });
    } else if (mode === "emergency") {
      void send({ type: "urgent_request", lat, lon, priority: "emergency", needs: "stretcher", dropoff_id: "ukc" });
    }
    setMode(null);
  };

  return (
    <main className="main">
        <section className="map-wrap">
          {mode && (
            <div className="map-hint">
              Click the map to place the {mode === "closure" ? "road closure" : "emergency call"} ·{" "}
              <button className="link" onClick={() => setMode(null)}>
                cancel
              </button>
            </div>
          )}
          <MapView
            state={state}
            mode={mode}
            onMapClick={onMapClick}
            selectedId={selectedId}
            onSelect={setSelectedId}
            detail={detail}
            centerOn={centerOn}
          />
          {detail && selectedId && (
            <VehicleCard
              detail={detail}
              busy={busy}
              send={send}
              onClose={() => setSelectedId(null)}
              onCenter={() => setCenterOn({ lat: detail.vehicle.lat, lon: detail.vehicle.lon, n: Date.now() })}
            />
          )}
        </section>
        <aside className="side">
          <KpiRow kpis={state.kpis} />
          {message && <div className={`message ${message.kind}`}>{message.text}</div>}
          {!state.hypothetical && (
            <Panel title="Live conditions">
              <Conditions state={state} />
            </Panel>
          )}
          <Panel title="Message from the field">
            <FieldMessage state={state} />
          </Panel>
          <Panel title="AI dispatcher">
            <AgentPanel state={state} notify={setMessage} />
          </Panel>
          <Panel title={state.hypothetical ? "Inject event (hypothetical)" : "Report event"}>
            <Controls state={state} busy={busy} mode={mode} setMode={setMode} send={send} setMessage={setMessage} />
          </Panel>
          <Panel title="Priority & capacity">
            <OpsControls state={state} send={send} busy={busy} />
          </Panel>
          <Panel title={`Alerts (${state.alerts.length})`}>
            <Alerts state={state} send={send} />
          </Panel>
          <Panel title="Event log">
            <EventLog events={state.events} />
          </Panel>
        </aside>
        <section className="trips">
          <TripTable state={state} selectedId={selectedId} onSelect={setSelectedId} />
        </section>
    </main>
  );
}

function StatusBar({ state, connected }: { state: WorldSnapshot; connected: boolean }) {
  const w = state.weather.now;
  return (
    <div className={`statusbar ${state.hypothetical ? "is-sim" : "is-live"}`}>
      <span className="mode-badge">
        {state.hypothetical ? `SIMULATION · hypothetical · ${state.speedup}× speed` : "LIVE · real weather, traffic and incidents"}
      </span>
      <div className="chips">
        <span className={`chip ${connected ? "ok" : "bad"}`}>{connected ? "● connected" : "● reconnecting"}</span>
        <span className="chip">{state.hypothetical ? "Sim time" : "Time"} {fmtTime(state.sim_time)}</span>
        {w && (
          <span className={`chip ${state.weather.overridden ? "warn" : ""}`}>
            {w.snowfall_cm > 0 ? "❄" : w.precipitation_mm > 0 ? "🌧" : "☀"} {w.temperature_c.toFixed(1)} °C ·{" "}
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
          🚗 Traffic ×{state.traffic.factor.toFixed(2)} · {state.traffic.source === "tomtom" ? "TomTom live" : "profile"}
        </span>
        {Object.values(state.sources).map((s) => (
          <span key={s.name} className={`chip src-${s.health}`} title={s.last_error ?? `${s.kind} · ${s.age_s ?? "–"} s old`}>
            {s.name}: {s.health}
          </span>
        ))}
        <span className="chip" title="Road routes cached (OSRM / TomTom)">
          🛣 roads: {state.roads.routes_cached} routes
        </span>
      </div>
    </div>
  );
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
            {w.snowfall_cm > 0 ? "❄" : w.precipitation_mm > 0 ? "🌧" : "☀"} {w.temperature_c.toFixed(1)} °C
          </strong>{" "}
          · {w.precipitation_mm} mm · wind {Math.round(w.wind_speed_kmh)} km/h <span className="muted">({w.source})</span>
          {nextHours.length > 0 && (
            <div className="muted">
              Next hours:{" "}
              {nextHours
                .map((h) => `${fmtTime(h.time)} ${Math.round(h.temperature_c)}° ${h.snowfall_cm > 0 ? "❄" : h.precipitation_mm > 0 ? "🌧" : ""}`)
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
            {i.kind === "road_closure" ? "⛔" : i.kind === "accident" ? "💥" : "🚦"} {i.description}
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
    ["Total delay", `${Math.round(kpis.total_delay_min)} min`, kpis.total_delay_min >= 15],
    ["Unassigned", unassignedTotal(kpis), unassignedTotal(kpis) > 0],
    ["Vehicles", kpis.vehicles_in_service, false],
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
    <div className="panel">
      <h2>{title}</h2>
      {children}
    </div>
  );
}

function Controls({
  state,
  busy,
  mode,
  setMode,
  send,
  setMessage,
}: {
  state: WorldSnapshot;
  busy: boolean;
  mode: ClickMode;
  setMode: (m: ClickMode) => void;
  send: Send;
  setMessage: (m: { kind: "ok" | "error"; text: string } | null) => void;
}) {
  const inService = state.vehicles.filter((v) => v.status !== "out_of_service");
  const [picked, setPicked] = useState("");
  const [minutes, setMinutes] = useState(20);
  const vehicleId = inService.some((v) => v.id === picked) ? picked : (inService[0]?.id ?? "");
  const snowing = state.weather.overridden;

  const sim = state.hypothetical;
  const reset = async () => {
    try {
      await resetWorld(state.world);
      setMessage({ kind: "ok", text: "Simulation reset" });
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof Error ? e.message : String(e) });
    }
  };

  return (
    <div className="controls">
      <div className="row">
        <select value={vehicleId} onChange={(e) => setPicked(e.target.value)}>
          {inService.map((v) => (
            <option key={v.id} value={v.id}>
              {v.id} · {v.name} ({v.status.replace(/_/g, " ")})
            </option>
          ))}
        </select>
      </div>
      <div className="row">
        <button
          disabled={busy || !vehicleId}
          onClick={() => send({ type: "breakdown", vehicle_id: vehicleId, note: "reported by operator" })}
        >
          🔧 Breakdown
        </button>
        <input type="number" min={1} max={240} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} />
        <button disabled={busy || !vehicleId} onClick={() => send({ type: "delay", vehicle_id: vehicleId, minutes })}>
          ⏱ Delay
        </button>
      </div>
      <div className="row">
        <button className={mode === "emergency" ? "active" : ""} onClick={() => setMode(mode === "emergency" ? null : "emergency")}>
          🚨 Emergency (click map)
        </button>
        <button className={mode === "closure" ? "active" : ""} onClick={() => setMode(mode === "closure" ? null : "closure")}>
          ⛔ Closure (click map)
        </button>
      </div>
      <FogControl send={send} busy={busy} />
      {!sim && <p className="muted">Live uses real weather and traffic. Hypothetical scenarios run in Simulation.</p>}
      {sim && (
        <div className="row">
          <button
            disabled={busy}
            onClick={() => send(snowing ? { type: "weather_override", clear: true } : { type: "weather_override", snowfall_cm: 2 })}
          >
            {snowing ? "☀ End snowstorm" : "❄ Snowstorm"}
          </button>
          <button className="ghost" disabled={busy} onClick={reset}>
            ↺ Reset simulation
          </button>
        </div>
      )}
      {sim && <div className="scenario-label muted">🎬 Demo scenarios (reset + several events + one AI analysis)</div>}
      <div className="row">
        {(sim ? SCENARIOS : []).map((s) => (
          <button
            key={s.name}
            title={s.title}
            disabled={busy}
            onClick={async () => {
              try {
                const r = await runScenario(s.name);
                setMessage({ kind: "ok", text: `Scenario started: ${r.title}` });
              } catch (e) {
                setMessage({ kind: "error", text: e instanceof Error ? e.message : String(e) });
              }
            }}
          >
            {s.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function Alerts({ state, send }: { state: WorldSnapshot; send: Send }) {
  if (state.alerts.length === 0 && state.incidents.length === 0) return <p className="muted">All clear.</p>;
  return (
    <ul className="alerts">
      {state.incidents.map((inc) => (
        <li key={inc.id} className={`alert ${inc.kind === "congestion" ? "sev-medium" : "sev-high"}`}>
          {inc.kind === "road_closure" ? "⛔" : inc.kind === "accident" ? "💥" : "🚦"} {inc.description}
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
    <table>
      <thead>
        <tr>
          <th>Trip</th>
          <th>Patient</th>
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
          return (
            <tr
              key={t.id}
              className={`${t.status === "unassigned" ? "row-unassigned" : late ? "row-late" : ""}${
                t.vehicle_id && t.vehicle_id === selectedId ? " row-selected" : ""
              }${t.vehicle_id ? " clickable" : ""}`}
              onClick={() => t.vehicle_id && onSelect(t.vehicle_id)}
              title={t.vehicle_id ? `Show ${t.vehicle_id} on the map` : undefined}
            >
              <td>{t.id}</td>
              <td>{t.label ?? t.patient}</td>
              <td>
                <span className={`prio prio-${t.priority}`}>{t.priority}</span>
              </td>
              <td>{t.needs}</td>
              <td>
                {place.get(t.pickup_id) ?? t.pickup_id} → {place.get(t.dropoff_id) ?? t.dropoff_id}
              </td>
              <td>{t.vehicle_id ?? "—"}</td>
              <td>{t.status.replace(/_/g, " ")}</td>
              <td>{fmtTime(t.due_by)}</td>
              <td>{fmtTime(t.eta_dropoff)}</td>
              <td>{t.delay_min == null ? "—" : late ? `+${Math.round(t.delay_min)} min` : "on time"}</td>
            </tr>
          );
        })}
      </tbody>
      <tfoot>
        <tr>
          <td colSpan={10} className="muted">
            {open.length} open · {done} completed
          </td>
        </tr>
      </tfoot>
    </table>
  );
}
