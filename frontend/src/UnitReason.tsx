import { Repeat } from "lucide-react";
import type { Vehicle, WorldSnapshot } from "./api";
import { BY_SHORT, isClaude, unitOnCall } from "./calls";
import { fmtTime } from "./format";
import { useT } from "./i18n";

/**
 * Under "Responding to …" on the vehicle card and the strip's drop-down: why the AI dispatcher sent this
 * unit ("AI: nearest free ambulance", the source on hover: rules engine, Claude or the dispatcher) and a
 * shortcut to override it in the case card.
 */
export function UnitReason({
  v,
  state,
  onOverride,
}: {
  v: Vehicle;
  state: WorldSnapshot;
  onOverride?: (tripId: string, vehicleId: string) => void;
}) {
  const t = useT();
  const on = unitOnCall(state, v);
  if (!on) return null;
  const { call, unit } = on;
  const done = call.status === "closed" || call.status === "cancelled";
  const who = t(unit.by === "dispatcher" ? "ops.unit.dispatcher" : "ops.unit.ai");
  return (
    <div className="unit-reason">
      <span
        className={`ut-reason${unit.by === "dispatcher" ? " by-dispatcher" : ""}`}
        title={`${t("ops.unit.decidedBy", { source: unit.source })}${unit.assignedAt ? t("ops.unit.at", { time: fmtTime(unit.assignedAt) }) : ""}${
          unit.reason ? `\n${unit.reason}` : ""
        }`}
      >
        <span className={`ai-tag${unit.by === "dispatcher" ? " dispatcher" : isClaude(unit.by) ? " claude" : ""}`}>{who}</span>
        <span className="ut-reason-text">{unit.reason ?? t("ops.unit.roleOn", { role: unit.roleLabel, call: call.id })}</span>
        {unit.by !== "dispatcher" && <span className="ut-src">{unit.by ? (BY_SHORT[unit.by] ?? unit.by) : (BY_SHORT.engine ?? "Engine")}</span>}
      </span>
      {onOverride && !done && (
        <button className="sm" onClick={() => onOverride(call.trip.id, v.id)} title={t("ops.unit.overrideTitle", { call: call.id, unit: v.id })}>
          <Repeat /> {t("ops.unit.override")}
        </button>
      )}
    </div>
  );
}
