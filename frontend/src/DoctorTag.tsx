import { Stethoscope } from "lucide-react";
import type { Trip, Vehicle } from "./api";
import { doctorOf, doctorText, doctorTitle, ORIGIN_LABEL } from "./doctor";
import { fmtTime } from "./format";
import { useLang, useT } from "./i18n";

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
  useLang(); // re-render on a language switch
  const d = doctorOf(trip, vehicles, now);
  if (!d) return null;
  const cls = d.state === "needed" ? "needed" : d.missed ? "missed" : d.state === "on_scene" ? "arrived" : "met";
  const text = doctorText(d);
  return (
    <span className={`drtag drtag-${size} ${cls}`} title={doctorTitle(d)} aria-label={text}>
      <Stethoscope aria-hidden />
      {compact ? doctorText(d, true) : text}
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
  const t = useT();
  if (!v?.origin || v.origin === "own") return null;
  const until = v.contract_until ? fmtTime(v.contract_until) : null;
  const title =
    v.origin === "mutual_aid"
      ? t("origin.titleMutualAid")
      : until
        ? v.contract_ended
          ? t("origin.titleContractEnded")
          : t("origin.titleContract", { until })
        : t("origin.titlePrivate");
  const label = compact ? t(v.origin === "mutual_aid" ? "origin.mutual_aidShort" : "origin.privateShort") : (ORIGIN_LABEL[v.origin] ?? v.origin);
  return (
    <span className={`origin-tag ${v.origin}`} title={title}>
      {label}
      {until && (compact ? ` ${until}` : v.contract_ended ? t("origin.leaving") : t("origin.until", { until }))}
    </span>
  );
}
