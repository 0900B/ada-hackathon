import { useState, type ReactNode } from "react";
import {
  API_URL,
  postEvent,
  resetSimulation,
  useWorldState,
  type EventRecord,
  type Kpis,
  type Priority,
  type WorldSnapshot,
} from "./api";
import { MapView, type ClickMode } from "./MapView";

type Send = (event: Record<string, unknown>) => Promise<void>;

const PRIORITY_ORDER: Record<Priority, number> = { emergency: 0, urgent: 1, scheduled: 2 };

const fmtTime = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleTimeString("sl-SI", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Ljubljana" })
    : "–";

const unassignedTotal = (k: Kpis) => k.unassigned.emergency + k.unassigned.urgent + k.unassigned.scheduled;

function describe(rec: EventRecord): string {
  const b = rec.kpis_before;
  const a = rec.kpis_after;
  return (
    `${rec.summary}. ${rec.affected_trip_ids.length} trip(s) affected · ` +
    `late ${b.late_trips} → ${a.late_trips} · unassigned ${unassignedTotal(b)} → ${unassignedTotal(a)}`
  );
}

export default function App() {
  const { state, connected } = useWorldState();
  const [mode, setMode] = useState<ClickMode>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const send: Send = async (event) => {
    setBusy(true);
    try {
      setMessage({ kind: "ok", text: describe(await postEvent(event)) });
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

  if (!state) {
    return <div className="loading">Connecting to {API_URL} …</div>;
  }

  return (
    <div className="app">
      <Header state={state} connected={connected} />
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
          <MapView state={state} mode={mode} onMapClick={onMapClick} />
        </section>
        <aside className="side">
          <KpiRow kpis={state.kpis} />
          <Panel title="Inject event">
            <Controls state={state} busy={busy} mode={mode} setMode={setMode} send={send} setMessage={setMessage} />
            {message && <div className={`message ${message.kind}`}>{message.text}</div>}
          </Panel>
          <Panel title="AI dispatcher">
            <p className="muted">Recommendations from the Claude agent will appear here.</p>
          </Panel>
          <Panel title={`Alerts (${state.alerts.length})`}>
            <Alerts state={state} send={send} />
          </Panel>
          <Panel title="Event log">
            <EventLog events={state.events} />
          </Panel>
        </aside>
        <section className="trips">
          <TripTable state={state} />
        </section>
      </main>
    </div>
  );
}

function Header({ state, connected }: { state: WorldSnapshot; connected: boolean }) {
  const w = state.weather.now;
  return (
    <header className="header">
      <h1>🚑 Emergency Transport Assistant</h1>
      <div className="chips">
        <span className={`chip ${connected ? "ok" : "bad"}`}>{connected ? "● live" : "● reconnecting"}</span>
        <span className="chip">Sim time {fmtTime(state.sim_time)}</span>
        {w && (
          <span className={`chip ${state.weather.overridden ? "warn" : ""}`}>
            {w.snowfall_cm > 0 ? "❄" : w.precipitation_mm > 0 ? "🌧" : "☀"} {w.temperature_c.toFixed(1)} °C ·{" "}
            {w.precipitation_mm} mm · {state.weather.overridden ? "demo override" : w.source}
          </span>
        )}
        <span className="chip">Traffic ×{state.traffic.factor.toFixed(2)}</span>
        {Object.values(state.sources).map((s) => (
          <span key={s.name} className={`chip src-${s.health}`} title={s.last_error ?? `${s.kind} · ${s.age_s ?? "–"} s old`}>
            {s.name}: {s.health}
          </span>
        ))}
      </div>
    </header>
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

  const reset = async () => {
    try {
      await resetSimulation();
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
    </div>
  );
}

function Alerts({ state, send }: { state: WorldSnapshot; send: Send }) {
  if (state.alerts.length === 0 && state.incidents.length === 0) return <p className="muted">All clear.</p>;
  return (
    <ul className="alerts">
      {state.incidents.map((inc) => (
        <li key={inc.id} className="alert sev-high">
          ⛔ {inc.description}
          <button className="link" onClick={() => send({ type: "clear_incident", incident_id: inc.id })}>
            clear
          </button>
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

function TripTable({ state }: { state: WorldSnapshot }) {
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
            <tr key={t.id} className={t.status === "unassigned" ? "row-unassigned" : late ? "row-late" : ""}>
              <td>{t.id}</td>
              <td>{t.patient}</td>
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
