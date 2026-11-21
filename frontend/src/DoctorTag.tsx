import { Stethoscope } from "lucide-react";
import type { Trip, Vehicle } from "./api";
import { doctorOf, doctorText, doctorTitle, ORIGIN_LABEL } from "./doctor";
import { fmtTime } from "./format";

/** Compact doctor status of a call: "Dr D1 7/15" (red when it misses the target), "Dr needed", "Dr on H1". */
export function DoctorTag({
  trip,
  vehicles,
  now,
  size = "sm",
  compact = false,
}: {
  trip: Trip;
  vehicles: Vehicle[];
  now: string;
  size?: "sm" | "md" | "lg";
  compact?: boolean; // dense tables: the stethoscope stands for "Dr" ("D1 7/15", "needed", "on H1")
}) {
  const d = doctorOf(trip, vehicles, now);
  if (!d) return null;
  const cls = d.state === "needed" ? "needed" : d.missed ? "missed" : d.state === "on_scene" ? "arrived" : "met";
  const text = doctorText(d);
  return (
    <span className={`drtag drtag-${size} ${cls}`} title={doctorTitle(d)} aria-label={text}>
      <Stethoscope aria-hidden />
      {compact ? text.replace(/^Dr /, "") : text}
    </span>
  );
}

/** "Mutual aid" / "Private" for units that are not our own; contracted surge units add "until HH:MM". */
export function OriginTag({
  v,
  compact = false,
}: {
  v: Pick<Vehicle, "origin" | "contract_until" | "contract_ended"> | undefined;
  compact?: boolean;
}) {
  if (!v?.origin || v.origin === "own") return null;
  const until = v.contract_until ? fmtTime(v.contract_until) : null;
  const title =
    v.origin === "mutual_aid"
      ? "Mutual aid: an ambulance from a neighbouring station"
      : until
        ? v.contract_ended
          ? "Contracted surge capacity: the contract has ended; it finishes its current job and leaves"
          : `Contracted surge capacity until ${until}: then it finishes its current job, returns and leaves`
        : "A private ambulance, called in because no own unit could reach the call in time";
  const label = compact ? (v.origin === "mutual_aid" ? "Aid" : "Priv") : (ORIGIN_LABEL[v.origin] ?? v.origin);
  return (
    <span className={`origin-tag ${v.origin}`} title={title}>
      {label}
      {until && (compact ? ` ${until}` : v.contract_ended ? " · leaving" : ` until ${until}`)}
    </span>
  );
}
