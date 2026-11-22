import { Repeat } from "lucide-react";
import type { Vehicle, WorldSnapshot } from "./api";
import { BY_SHORT, isClaude, unitOnCall } from "./calls";
import { fmtTime } from "./format";

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
  const on = unitOnCall(state, v);
  if (!on) return null;
  const { call, unit } = on;
  const done = call.status === "closed" || call.status === "cancelled";
  const who = unit.by === "dispatcher" ? "Dispatcher" : "AI";
  return (
    <div className="unit-reason">
      <span
        className={`ut-reason${unit.by === "dispatcher" ? " by-dispatcher" : ""}`}
        title={`Decided by ${unit.source}${unit.assignedAt ? ` at ${fmtTime(unit.assignedAt)}` : ""}${unit.reason ? `\n${unit.reason}` : ""}`}
      >
        <span className={`ai-tag${unit.by === "dispatcher" ? " dispatcher" : isClaude(unit.by) ? " claude" : ""}`}>{who}</span>
        <span className="ut-reason-text">{unit.reason ?? `${unit.roleLabel} on ${call.id}`}</span>
        {unit.by !== "dispatcher" && <span className="ut-src">{unit.by ? (BY_SHORT[unit.by] ?? unit.by) : "Engine"}</span>}
      </span>
      {onOverride && !done && (
        <button className="sm" onClick={() => onOverride(call.trip.id, v.id)} title={`Open ${call.id} and choose another unit instead of ${v.id}`}>
          <Repeat /> Override
        </button>
      )}
    </div>
  );
}
