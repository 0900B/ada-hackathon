/** Shared formatting helpers. */
import { DOCTOR_STATUS } from "./doctor";
import { t, tOr } from "./i18n";
import type { Place, Trip, Vehicle } from "./api";

export const fmtTime = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleTimeString("sl-SI", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Ljubljana" })
    : "–";

export const humanize = (s: string) => s.replace(/_/g, " ");

/** A vehicle status code in the UI language ("to pickup" / "na poti k pacientu"); unknown codes humanized. */
export const vehicleStatusLabel = (status: string) => tOr(`vstatus.${status}`, humanize(status));

/** A trip (call) status code in the UI language ("on board" / "pacient v vozilu"); unknown codes humanized. */
export const tripStatusLabel = (status: string) => tOr(`tstatus.${status}`, humanize(status));

/** A vehicle type in the UI language ("ambulance" / "reševalno vozilo"). */
export const vehicleTypeLabel = (type: string) => tOr(`vtype.${type}`, humanize(type));

/** A helicopter off duty at night (backend `off_duty_until`, not while fog grounds it): "Unavailable at night until 08:00". */
export const nightText = (v: Pick<Vehicle, "off_duty_until" | "grounded_until">): string | null =>
  v.off_duty_until && !v.grounded_until ? t("heli.night", { time: fmtTime(v.off_duty_until) }) : null;

/** No new flights now: fog or night (the greyed "grounded" look). */
export const heliDown = (v: Pick<Vehicle, "off_duty_until" | "grounded_until">): boolean => Boolean(v.grounded_until || v.off_duty_until);

/** A vehicle's status for display: one loaded with equipment is "with equipment", not "with patient". */
export function vehicleStatusText(v: Vehicle, trips: Trip[]): string {
  if (v.type === "doctor") return DOCTOR_STATUS[v.status] ?? vehicleStatusLabel(v.status);
  const current = v.current_trip_id ? trips.find((t) => t.id === v.current_trip_id) : undefined;
  if (v.status === "with_patient" && current?.kind === "equipment") return vehicleStatusLabel("with_equipment");
  return vehicleStatusLabel(v.status);
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
