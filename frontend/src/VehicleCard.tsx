import type { VehicleDetail, WorldSnapshot } from "./api";
import { flightTarget, fmtTime, vehicleStatusText } from "./format";

type Send = (event: Record<string, unknown>) => Promise<void>;

const STOP_ICON = { pickup: "⬆", dropoff: "⬇", base: "🏠" } as const;

/** Floating card for the selected vehicle: crew, fuel, current job, upcoming stops, quick actions. */
export function VehicleCard({
  detail,
  state,
  onClose,
  onCenter,
  send,
  busy,
}: {
  detail: VehicleDetail;
  state: WorldSnapshot;
  onClose: () => void;
  onCenter: () => void;
  send: Send;
  busy: boolean;
}) {
  const v = detail.vehicle;
  const t = detail.current_trip;
  const fuelClass = detail.fuel.pct < 10 ? "bad" : detail.fuel.low ? "warn" : "ok";
  const down = v.status === "out_of_service";
  const heli = v.type === "helicopter";
  const flight = heli
    ? flightTarget(v, t ?? undefined, new Map(state.places.map((p) => [p.id, p])))
    : null;

  return (
    <div className="vehicle-card-float">
      <div className="vc-head">
        <span className={heli ? "veh veh-helicopter" : `veh veh-${v.type}`}>{heli ? `🚁 ${v.id}` : v.id}</span>
        <strong>{v.name}</strong>
        <span className="muted">· {vehicleStatusText(v, state.trips)}</span>
        <button className="link vc-close" onClick={onClose} title="Close (Esc)">
          ✕
        </button>
      </div>

      {heli && (
        <div className={`vc-flight${v.grounded_until ? " grounded" : ""}`}>
          {v.grounded_until
            ? `🌫 Grounded by fog until ${fmtTime(v.grounded_until)}: no new flights${flight ? ` (finishing: ${flight.kind} ${flight.place.name})` : ""}`
            : flight
              ? `✈ ${v.busy_until ? "On the ground, next" : "Flying"} to ${flight.kind === "base" ? "base" : flight.kind}: ${flight.place.name} · straight line, 200 km/h`
              : "✈ Parked at base, ready to fly (straight line, 200 km/h)"}
        </div>
      )}

      <div className="vc-fuel">
        <div className="vc-fuel-label">
          ⛽ Fuel {detail.fuel.pct.toFixed(0)}%{detail.fuel.range_km != null && <span className="muted"> · ~{detail.fuel.range_km} km range</span>}
        </div>
        <div className="vc-bar">
          <div className={`vc-bar-fill ${fuelClass}`} style={{ width: `${Math.max(2, detail.fuel.pct)}%` }} />
        </div>
        <div className="muted">
          {v.km_today.toFixed(1)} km today · base {detail.base}
          {v.shift_end ? ` · shift until ${fmtTime(v.shift_end)}` : ""}
        </div>
      </div>

      <div className="vc-section">
        <div className="vc-title">Crew</div>
        {v.crew.map((c) => (
          <div key={c.name}>
            {c.name.replace(" (fictional)", "")} <span className="muted">· {c.role}</span>
          </div>
        ))}
        <div className="muted vc-small">{detail.capabilities.join(" · ")}</div>
      </div>

      <div className="vc-section">
        <div className="vc-title">Now</div>
        {t ? (
          <div>
            <strong>{t.id}</strong> {t.label ?? t.patient} <span className={`prio prio-${t.priority}`}>{t.priority}</span>
          </div>
        ) : (
          <div className="muted">{down ? "Out of service" : "No active job"}</div>
        )}
        {(detail.detour_legs?.length ?? 0) > 0 && (
          <div className="vc-detour">
            ↪ {detail.detour_legs?.includes(0) ? "Rerouted" : "Will be rerouted"} around a road closure (orange on the map)
          </div>
        )}
      </div>

      {detail.stops.length > 0 && (
        <div className="vc-section">
          <div className="vc-title">Next stops (highlighted on the map)</div>
          <ol className="vc-stops">
            {detail.stops.map((s, i) => (
              <li key={i} className={(s.delay_min ?? 0) >= 5 ? "late" : ""}>
                <span className="vc-num">{i + 1}</span> {STOP_ICON[s.kind]} {s.eta ? fmtTime(s.eta) : "—"} · {s.place}
                {s.trip_id && <span className="muted"> · {s.trip_id}</span>}
                {(s.delay_min ?? 0) >= 5 && <span> · +{Math.round(s.delay_min ?? 0)} min</span>}
              </li>
            ))}
          </ol>
        </div>
      )}

      <div className="row vc-actions">
        <button onClick={onCenter}>🎯 Center</button>
        <button
          disabled={busy || down}
          title="Delay this vehicle by 10 minutes (hotkey D)"
          onClick={() => send({ type: "delay", vehicle_id: v.id, minutes: 10, note: "reported from vehicle card" })}
        >
          ⏱ +10 min
        </button>
        <button
          disabled={busy || down}
          title="Report a breakdown of this vehicle (hotkey B)"
          onClick={() => send({ type: "breakdown", vehicle_id: v.id, note: "reported from vehicle card" })}
        >
          🔧 Breakdown
        </button>
      </div>
      <div className="vc-links">
        <a className="button-link" href={`/vehicle/${encodeURIComponent(v.id)}?world=${state.world}`} target="_blank" rel="noopener">
          🖥 Tablet view ↗
        </a>
        <a className="button-link" href={`/crew/${encodeURIComponent(v.id)}?world=${state.world}`} target="_blank" rel="noopener">
          📱 Crew phone ↗
        </a>
      </div>
    </div>
  );
}
