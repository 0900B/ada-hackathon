/**
 * Doctors and outside units. In Slovenia a standard ambulance crew has no doctor (graduate nurse or
 * health technician + medical rescuer); for some red calls a doctor car (VUZ: doctor + nurse) drives
 * to the scene, joins the crew and escorts the patient to hospital. It never carries patients. The
 * helicopter has a doctor on board. When no own unit can reach a red call in time, dispatch can ask
 * a neighbouring station (mutual aid) or a private ambulance.
 * All fields are optional: older backends send none, and then nothing here shows.
 */
import type { Trip, Vehicle } from "./api";
import { liveRecord, t } from "./i18n";
import { conditionText, LEVEL_LABEL, levelOf } from "./severity";

/** Conditions that need a doctor (to preview it in the emergency picker before the backend answers). */
export const DOCTOR_CONDITIONS = new Set([
  "cardiac_arrest",
  "choking",
  "catastrophic_bleeding",
  "anaphylaxis",
  "stemi",
  "breathing_difficulty",
  "major_trauma",
]);
export const DOCTOR_TARGET_MIN = 15;

export const ORIGIN_LABEL: Record<string, string> = liveRecord(["mutual_aid", "private"] as const, (o) => t(`origin.${o}`));

export interface DoctorInfo {
  state: "needed" | "en_route" | "on_scene" | "helicopter";
  vehicle: string | null; // D1, D2 or H1
  minutes: number | null; // call to the doctor reaching the scene (null: none assigned yet)
  target: number;
  waited: number; // minutes since the call
  missed: boolean;
}

/** The doctor side of a call, or null when it needs no doctor (or the backend does not say). */
export function doctorOf(t: Trip, vehicles: Vehicle[], now: string): DoctorInfo | null {
  if (!t.needs_doctor) return null;
  const target = t.doctor_target_min ?? DOCTOR_TARGET_MIN;
  const start = Date.parse(t.pickup_after);
  const waited = Math.max(0, (Date.parse(now) - start) / 60_000);
  const id = t.doctor_vehicle_id ?? null;
  if (!id) return { state: "needed", vehicle: null, minutes: null, target, waited, missed: waited > target };
  const v = vehicles.find((x) => x.id === id);
  const minutes = t.doctor_eta ? Math.max(0, Math.round((Date.parse(t.doctor_eta) - start) / 60_000)) : null;
  const missed = minutes != null && minutes > target;
  if (v?.type === "helicopter" || (!v && id.startsWith("H"))) return { state: "helicopter", vehicle: id, minutes, target, waited, missed };
  const arrived =
    (v && (v.status === "loading" || v.status === "with_patient")) || (t.doctor_eta ? Date.parse(t.doctor_eta) <= Date.parse(now) : false);
  return { state: arrived ? "on_scene" : "en_route", vehicle: id, minutes, target, waited, missed };
}

/** "Dr D1 7/15", "Dr needed", "Dr on H1"; compact (the stethoscope stands for "Dr"): "D1 7/15", "needed", "on H1". */
export function doctorText(d: DoctorInfo, compact = false): string {
  if (d.state === "needed") return t(compact ? "dr.neededShort" : "dr.needed");
  if (d.state === "helicopter") return t(compact ? "dr.heliShort" : "dr.heli", { v: d.vehicle });
  const body = `${d.vehicle}${d.minutes != null ? ` ${d.minutes}/${d.target}` : ""}`;
  return compact ? body : t("dr.car", { v: body });
}

export function doctorTitle(d: DoctorInfo): string {
  if (d.state === "needed") return t("dr.titleNeeded", { waited: Math.round(d.waited), target: d.target });
  if (d.state === "helicopter") return t("dr.titleHeli", { v: d.vehicle });
  const when = d.minutes != null ? t("dr.whenAfter", { m: d.minutes }) : t("dr.whenUnknown");
  const over = d.missed && d.minutes != null ? d.minutes - d.target : null;
  const reached = d.state === "on_scene";
  const key = over != null ? (reached ? "dr.titleReachedOver" : "dr.titleReachesOver") : reached ? "dr.titleReached" : "dr.titleReaches";
  return t(key, { v: d.vehicle, when, target: d.target, over });
}

/** What a doctor car is doing, in a few words ("Joining A2 at Bežigrad", "Escorting A2 to UKC"). */
export function doctorJob(v: Vehicle, trip: Trip | undefined, place: (id: string) => string): string | null {
  if (v.type !== "doctor" || !trip) return null;
  const unit = trip.vehicle_id ?? t("dr.theAmbulance");
  if (v.status === "to_pickup") return t("dr.jobJoining", { unit, place: place(trip.pickup_id) });
  if (v.status === "loading") return t("dr.jobOnScene", { unit, place: place(trip.pickup_id) });
  if (v.status === "with_patient") return t("dr.jobEscorting", { unit, place: place(trip.dropoff_id) });
  return null;
}

/** The doctor car's job in one sentence: "Joining A2 at Bežigrad: P-112, Critical · Cardiac arrest". */
export function doctorJobLine(v: Vehicle, trip: Trip | undefined, place: (id: string) => string): string | null {
  const job = doctorJob(v, trip, place);
  if (!job || !trip) return null;
  const cond = conditionText(trip);
  return `${job}: ${trip.label}, ${LEVEL_LABEL[levelOf(trip)]}${cond ? ` · ${cond}` : ""}`;
}

/** Status words for a doctor car (the statuses are shared with ambulances). */
export const DOCTOR_STATUS: Record<string, string> = liveRecord(
  ["idle", "to_pickup", "loading", "with_patient", "returning", "out_of_service"] as const,
  (s) => t(`dstatus.${s}`),
);

/** Open critical calls whose doctor will miss the target, worst first. */
export function doctorMisses(trips: Trip[], vehicles: Vehicle[], now: string): { trip: Trip; d: DoctorInfo }[] {
  return trips
    .filter((t) => t.severity === "critical" && t.status !== "completed" && t.status !== "cancelled")
    .map((trip) => ({ trip, d: doctorOf(trip, vehicles, now) }))
    .filter((x): x is { trip: Trip; d: DoctorInfo } => x.d !== null && x.d.missed && x.d.state !== "on_scene")
    .sort((a, b) => b.d.waited - a.d.waited);
}
