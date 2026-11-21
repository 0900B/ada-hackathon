/** Shared formatting helpers. */
import type { Trip, Vehicle } from "./api";

export const fmtTime = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleTimeString("sl-SI", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Ljubljana" })
    : "–";

export const humanize = (s: string) => s.replace(/_/g, " ");

/** A vehicle's status for display: one loaded with equipment is "with equipment", not "with patient". */
export function vehicleStatusText(v: Vehicle, trips: Trip[]): string {
  const current = v.current_trip_id ? trips.find((t) => t.id === v.current_trip_id) : undefined;
  if (v.status === "with_patient" && current?.kind === "equipment") return "with equipment";
  return humanize(v.status);
}
