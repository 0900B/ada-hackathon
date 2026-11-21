import { useState } from "react";
import type { WorldSnapshot } from "./api";
import { FogControl } from "./FogControl";
import type { ClickMode } from "./MapView";

type Send = (event: Record<string, unknown>) => Promise<void>;

/** Operator events: breakdown/delay of a vehicle, emergency call or road closure on the map, weather. */
export function EventsPanel({
  state,
  busy,
  mode,
  setMode,
  send,
  picked,
  setPicked,
}: {
  state: WorldSnapshot;
  busy: boolean;
  mode: ClickMode;
  setMode: (m: ClickMode) => void;
  send: Send;
  picked: string;
  setPicked: (id: string) => void;
}) {
  const inService = state.vehicles.filter((v) => v.status !== "out_of_service");
  const [minutes, setMinutes] = useState(20);
  const vehicleId = inService.some((v) => v.id === picked) ? picked : (inService[0]?.id ?? "");
  const sim = state.hypothetical;
  const snowing = state.weather.overridden;

  return (
    <div className="controls">
      <div className="field-label">Vehicle</div>
      <div className="row">
        <select aria-label="Vehicle" value={vehicleId} onChange={(e) => setPicked(e.target.value)}>
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
        <input
          type="number"
          aria-label="Delay in minutes"
          title="Delay in minutes"
          min={1}
          max={240}
          value={minutes}
          onChange={(e) => setMinutes(Math.max(1, Math.round(Number(e.target.value) || 1)))}
        />
        <button disabled={busy || !vehicleId} onClick={() => send({ type: "delay", vehicle_id: vehicleId, minutes })}>
          ⏱ Delay
        </button>
      </div>

      <div className="field-label">On the map</div>
      <div className="row">
        <button
          className={mode === "emergency" ? "active" : ""}
          aria-pressed={mode === "emergency"}
          onClick={() => setMode(mode === "emergency" ? null : "emergency")}
          title="Then click the map where the patient is (hotkey E)"
        >
          🚨 Emergency (click map)
        </button>
        <button
          className={mode === "closure" ? "active" : ""}
          aria-pressed={mode === "closure"}
          onClick={() => setMode(mode === "closure" ? null : "closure")}
          title="Then click the map where the road is closed (hotkey C)"
        >
          ⛔ Closure (click map)
        </button>
      </div>

      <div className="field-label">Weather</div>
      <div className="row">
        <FogControl send={send} busy={busy} />
        {sim && (
          <button
            disabled={busy}
            onClick={() => send(snowing ? { type: "weather_override", clear: true } : { type: "weather_override", snowfall_cm: 2 })}
          >
            {snowing ? "☀ End snowstorm" : "❄ Snowstorm"}
          </button>
        )}
      </div>
      {!sim && <p className="muted small">Live uses real weather and traffic. Hypothetical scenarios run in Simulation.</p>}
    </div>
  );
}
