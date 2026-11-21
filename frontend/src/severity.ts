/**
 * Severity levels and per-case urgency (docs/DISPATCH_PRIORITIES.md): every call has a level
 * (critical, serious, urgent, routine), a condition with a time-sensitivity weight (1-10) and case
 * modifiers. The backend sends these on each trip; older backends only send `priority`, so every
 * helper here falls back to it (emergency -> serious, urgent -> urgent, scheduled -> routine).
 */
import type { Priority, Trip } from "./api";

export type Level = "critical" | "serious" | "urgent" | "routine";

export const LEVELS: Level[] = ["critical", "serious", "urgent", "routine"];
export const LEVEL_RANK: Record<Level, number> = { critical: 0, serious: 1, urgent: 2, routine: 3 };
export const LEVEL_LABEL: Record<Level, string> = { critical: "Critical", serious: "Serious", urgent: "Urgent", routine: "Routine" };
export const LEVEL_SHORT: Record<Level, string> = { critical: "CRIT", serious: "SER", urgent: "URG", routine: "RTN" };
/** What each level means, for tooltips. */
export const LEVEL_HELP: Record<Level, string> = {
  critical: "Life-threatening now (e.g. cardiac arrest). Target: at the patient within 8 min in the city.",
  serious: "May become life-threatening soon (e.g. stroke, heart attack, major trauma). Target: within 18 min.",
  urgent: "Possibly dangerous, not immediately (e.g. fractures, urgent transfers). Target: within 60 min.",
  routine: "Planned or non-urgent transport, by appointment.",
};
/** Plan B's response targets (minutes from the call to reaching the patient), used when the backend sends none. */
export const LEVEL_TARGET_MIN: Record<Level, number | null> = { critical: 8, serious: 18, urgent: 60, routine: null };
/** The old three-step priority each level maps to (what older backends understand). */
export const LEVEL_PRIORITY: Record<Level, Priority> = { critical: "emergency", serious: "emergency", urgent: "urgent", routine: "scheduled" };

export interface Condition {
  code: string;
  label: string;
  level: Level;
  weight: number; // time sensitivity within the level, 1-10
}

/** Conditions by level, most time-critical first (the codes the UI sends with a new call). */
export const CONDITIONS: Condition[] = [
  { code: "cardiac_arrest", label: "Cardiac arrest", level: "critical", weight: 10 },
  { code: "choking", label: "Choking", level: "critical", weight: 9 },
  { code: "catastrophic_bleeding", label: "Catastrophic bleeding", level: "critical", weight: 8 },
  { code: "anaphylaxis", label: "Anaphylaxis", level: "critical", weight: 8 },
  { code: "stroke", label: "Stroke", level: "serious", weight: 6 },
  { code: "stemi", label: "Heart attack (STEMI)", level: "serious", weight: 6 },
  { code: "breathing_difficulty", label: "Severe breathing difficulty", level: "serious", weight: 5 },
  { code: "major_trauma", label: "Major trauma", level: "serious", weight: 5 },
  { code: "seizure", label: "Ongoing seizure", level: "serious", weight: 4 },
  { code: "sepsis", label: "Suspected sepsis", level: "serious", weight: 4 },
  { code: "fall", label: "Fall or fracture", level: "urgent", weight: 2 },
];

export interface Modifier {
  code: string;
  label: string;
}
/** Case modifiers that move a call up within its level (the first three can be set on a new call). */
export const MODIFIERS: Modifier[] = [
  { code: "child", label: "Child" },
  { code: "deteriorating", label: "Getting worse" },
  { code: "multiple_patients", label: "Several patients" },
  { code: "late_stroke_window", label: "Late in the stroke window" },
  { code: "no_bystander_cpr", label: "No bystander CPR" },
];

export const modifierLabel = (code: string) =>
  MODIFIERS.find((m) => m.code === code)?.label ?? code.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

/** What the helpers need from a trip (all severity fields optional: older backends lack them). */
export type Graded = Pick<Trip, "priority"> &
  Partial<Pick<Trip, "severity" | "condition" | "condition_label" | "time_weight" | "response_target_min" | "modifiers">>;

export function levelOf(t: Graded): Level {
  if (t.severity && t.severity in LEVEL_RANK) return t.severity;
  return t.priority === "emergency" ? "serious" : t.priority === "urgent" ? "urgent" : "routine";
}

export function conditionText(t: Graded): string | null {
  if (t.condition_label) return t.condition_label;
  if (!t.condition) return null;
  return CONDITIONS.find((c) => c.code === t.condition)?.label ?? t.condition.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

/** Time sensitivity 1-10 within the level, or null when unknown. */
export function timeWeight(t: Graded): number | null {
  if (typeof t.time_weight === "number") return t.time_weight;
  return CONDITIONS.find((c) => c.code === t.condition)?.weight ?? null;
}

export function targetMin(t: Graded): number | null {
  return typeof t.response_target_min === "number" ? t.response_target_min : LEVEL_TARGET_MIN[levelOf(t)];
}

/** Open trips first by level, then by time sensitivity, then by due time. */
export function compareTrips(a: Trip, b: Trip): number {
  return (
    LEVEL_RANK[levelOf(a)] - LEVEL_RANK[levelOf(b)] ||
    (timeWeight(b) ?? 0) - (timeWeight(a) ?? 0) ||
    a.due_by.localeCompare(b.due_by)
  );
}

/** True once the backend sends severity on trips (then the UI offers all four levels). */
export const severitySupported = (trips: Trip[]) => trips.some((t) => typeof t.severity === "string");

/** One level up (for "patient worse"), or null at the top. */
export function levelUp(level: Level): Level | null {
  const i = LEVELS.indexOf(level);
  return i > 0 ? LEVELS[i - 1] : null;
}

export interface ResponseInfo {
  minutes: number | null; // call (or ready time) to reaching the patient; null = no unit yet
  target: number;
  waited: number; // minutes since the call so far
  reached: boolean;
  missed: boolean; // will miss (or missed) the target
}

/**
 * Whether a call reaches its patient within the response target. Measured from when the patient is
 * ready (for a new call: the call itself) to the pickup ETA, or the actual pickup once on board.
 */
export function responseOf(t: Trip, now: string): ResponseInfo | null {
  const target = targetMin(t);
  if (target == null || t.status === "cancelled") return null;
  const start = Date.parse(t.pickup_after);
  const waited = Math.max(0, (Date.parse(now) - start) / 60_000);
  const reached = t.status === "onboard" || t.status === "completed";
  if (!t.eta_pickup) return { minutes: null, target, waited, reached: false, missed: waited > target };
  const minutes = Math.max(0, Math.round((Date.parse(t.eta_pickup) - start) / 60_000));
  return { minutes, target, waited, reached, missed: minutes > target };
}

/** "reached in 11 min · target 8", "reaches in 6 min · target 8", "no unit yet · target 8". */
export function responseText(r: ResponseInfo): string {
  if (r.minutes == null) return `no unit yet · target ${r.target} min`;
  return `${r.reached ? "reached" : "reaches"} in ${r.minutes} min · target ${r.target}`;
}

/** Open critical and serious calls not yet reached that will miss their target, worst first. */
export function targetMisses(trips: Trip[], now: string): { trip: Trip; r: ResponseInfo }[] {
  return trips
    .filter((t) => {
      const l = levelOf(t);
      return (l === "critical" || l === "serious") && t.status !== "completed" && t.status !== "cancelled" && t.status !== "onboard";
    })
    .map((trip) => ({ trip, r: responseOf(trip, now) }))
    .filter((x): x is { trip: Trip; r: ResponseInfo } => x.r !== null && x.r.missed)
    .sort((a, b) => compareTrips(a.trip, b.trip));
}
