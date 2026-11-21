/**
 * Crew tablet logic: which stage the crew is in, and the countdown to the ER.
 * Pure functions only. This file is run by `node --test` without any tooling, so it may only
 * `import type` from other files and must use erasable TypeScript (no enums, namespaces or
 * parameter properties). Time always comes from the caller (the world's `sim_time`), never from
 * `Date.now()`, so the tablet agrees with the dispatcher screen.
 */
import type { Trip, Vehicle } from "../api";

export type CrewStage = "no_patient" | "to_patient" | "with_patient";

/** A drop-off this many minutes or more behind plan is shown as late. */
const LATE_MIN = 5;

/**
 * The stage the crew is in. Only a patient trip counts: no trip, an equipment trip and an idle
 * (or returning, out-of-service) vehicle all mean "no patient". A doctor car on a patient trip
 * follows the same stages as the ambulance it joins.
 */
export function crewStage(
  v: Pick<Vehicle, "status" | "type">,
  trip: Pick<Trip, "kind"> | undefined,
): CrewStage {
  if (!trip || trip.kind !== "patient") return "no_patient";
  if (v.status === "to_pickup") return "to_patient";
  if (v.status === "loading" || v.status === "with_patient") return "with_patient";
  return "no_patient";
}

/** Whole minutes from `nowIso` until `iso`, rounded up and never below 0; null if either time is missing or invalid. */
export function minutesUntil(iso: string | null | undefined, nowIso: string): number | null {
  if (!iso || !nowIso) return null;
  const target = Date.parse(iso);
  const now = Date.parse(nowIso);
  if (!Number.isFinite(target) || !Number.isFinite(now)) return null;
  return Math.max(0, Math.ceil((target - now) / 60_000));
}

export interface ErEta {
  minutes: number | null; // whole minutes to the hospital, null when the ETA is missing or invalid
  arriveAt: string | null; // the ETA itself (ISO), null when missing or invalid
  late: boolean; // behind plan by LATE_MIN minutes or more
  lateMin: number; // delay in whole minutes (0 when unknown); show it only when `late`
}

/** The ETA to the ER with a late marker. A missing or invalid time shows as null, never NaN. */
export function erEta(trip: Pick<Trip, "eta_dropoff" | "delay_min">, nowIso: string): ErEta {
  const eta = trip.eta_dropoff;
  const arriveAt = eta && Number.isFinite(Date.parse(eta)) ? eta : null;
  const delay = trip.delay_min;
  const known = typeof delay === "number" && Number.isFinite(delay);
  return {
    minutes: minutesUntil(arriveAt, nowIso),
    arriveAt,
    late: known && delay >= LATE_MIN,
    lateMin: known ? Math.max(0, Math.round(delay)) : 0,
  };
}
