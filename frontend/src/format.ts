/** Shared formatting helpers. */
import type { Place, Trip, Vehicle } from "./api";

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

/** Where a helicopter is heading right now: pickup, drop-off or home base (null = parked). */
export function flightTarget(
  v: Vehicle,
  trip: Trip | undefined,
  places: Map<string, Place>,
  next?: Trip, // the first queued trip: after a drop-off it flies there, not home
): { place: Place; kind: "pickup" | "drop-off" | "base" } | null {
  const at = (id: string | undefined, kind: "pickup" | "drop-off" | "base") => {
    const place = id ? places.get(id) : undefined;
    return place ? { place, kind } : null;
  };
  if (v.status === "to_pickup") return at(trip?.pickup_id, "pickup");
  if (v.status === "with_patient" || v.status === "loading") return at(trip?.dropoff_id, "drop-off");
  if (v.status === "returning") return next ? at(next.pickup_id, "pickup") : at(v.base_id, "base");
  return null;
}
