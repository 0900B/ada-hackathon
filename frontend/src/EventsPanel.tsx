import { useState } from "react";
import { CircleAlert, CloudSnow, Construction, Sun, Timer, Wrench } from "lucide-react";
import type { WorldSnapshot } from "./api";
import { FogControl } from "./FogControl";
import { vehicleStatusLabel } from "./format";
import { useT } from "./i18n";
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
  const t = useT();

  return (
    <div className="controls">
      <div className="field-label">{t("ops.ev.vehicle")}</div>
      <div className="row">
        <select aria-label={t("ops.ev.vehicle")} value={vehicleId} onChange={(e) => setPicked(e.target.value)}>
          {inService.map((v) => (
            <option key={v.id} value={v.id}>
              {v.id} · {v.name} ({vehicleStatusLabel(v.status)})
            </option>
          ))}
        </select>
      </div>
      <div className="row">
        <button
          disabled={busy || !vehicleId}
          onClick={() => send({ type: "breakdown", vehicle_id: vehicleId, note: "reported by operator" })}
        >
          <Wrench /> {t("ops.breakdown")}
        </button>
        <input
          type="number"
          aria-label={t("ops.ev.delayMinutes")}
          title={t("ops.ev.delayMinutes")}
          min={1}
          max={240}
          value={minutes}
          onChange={(e) => setMinutes(Math.max(1, Math.round(Number(e.target.value) || 1)))}
        />
        <button disabled={busy || !vehicleId} onClick={() => send({ type: "delay", vehicle_id: vehicleId, minutes })}>
          <Timer /> {t("ops.ev.delay")}
        </button>
      </div>

      <div className="field-label">{t("ops.ev.onMap")}</div>
      <div className="row">
        <button
          className={mode === "emergency" ? "active" : ""}
          aria-pressed={mode === "emergency"}
          onClick={() => setMode(mode === "emergency" ? null : "emergency")}
          title={t("ops.ev.emergencyTitle")}
        >
          <CircleAlert /> {t("ops.ev.emergency")}
        </button>
        <button
          className={mode === "closure" ? "active" : ""}
          aria-pressed={mode === "closure"}
          onClick={() => setMode(mode === "closure" ? null : "closure")}
          title={t("ops.ev.closureTitle")}
        >
          <Construction /> {t("ops.ev.closure")}
        </button>
      </div>

      <div className="field-label">{t("ops.ev.weather")}</div>
      <div className="row">
        <FogControl send={send} busy={busy} />
        {sim && (
          <button
            disabled={busy}
            onClick={() => send(snowing ? { type: "weather_override", clear: true } : { type: "weather_override", snowfall_cm: 2 })}
          >
            {snowing ? (
              <>
                <Sun /> {t("ops.ev.endSnow")}
              </>
            ) : (
              <>
                <CloudSnow /> {t("ops.ev.snow")}
              </>
            )}
          </button>
        )}
      </div>
      {!sim && <p className="muted small">{t("ops.ev.liveNote")}</p>}
    </div>
  );
}
