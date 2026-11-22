/**
 * Severity levels and per-case urgency (docs/DISPATCH_PRIORITIES.md): every call has a level
 * (critical, serious, urgent, routine), a condition with a time-sensitivity weight (1-10) and case
 * modifiers. The backend sends these on each trip; older backends only send `priority`, so every
 * helper here falls back to it (emergency -> serious, urgent -> urgent, scheduled -> routine).
 */
import type { Priority, Trip } from "./api";
import { getLang, hasKey, liveRecord, t as tx } from "./i18n";

export type Level = "critical" | "serious" | "urgent" | "routine";

export const LEVELS: Level[] = ["critical", "serious", "urgent", "routine"];
export const LEVEL_RANK: Record<Level, number> = { critical: 0, serious: 1, urgent: 2, routine: 3 };
/** "Critical" / "Kritično" (follows the UI language at the time of reading). */
export const LEVEL_LABEL: Record<Level, string> = liveRecord(LEVELS, (l) => tx(`level.${l}`));
/** "CRIT" / "KRIT" for strips and dense lists. */
export const LEVEL_SHORT: Record<Level, string> = liveRecord(LEVELS, (l) => tx(`levelShort.${l}`));
/** What each level means, for tooltips. */
export const LEVEL_HELP: Record<Level, string> = liveRecord(LEVELS, (l) => tx(`levelHelp.${l}`));

const capitalise = (code: string) => code.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

/** A condition code's label in the UI language ("Cardiac arrest" / "Srčni zastoj"). */
export function conditionLabel(code: string): string {
  const key = `cond.${code}`;
  return hasKey(key) ? tx(key) : capitalise(code);
}
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

/** A condition whose label follows the UI language. */
const condition = (code: string, level: Level, weight: number): Condition => ({
  code,
  level,
  weight,
  get label() {
    return conditionLabel(code);
  },
});

/** Conditions by level, most time-critical first (the codes the UI sends with a new call). */
export const CONDITIONS: Condition[] = [
  condition("cardiac_arrest", "critical", 10),
  condition("choking", "critical", 9),
  condition("catastrophic_bleeding", "critical", 8),
  condition("anaphylaxis", "critical", 8),
  condition("stroke", "serious", 6),
  condition("stemi", "serious", 6),
  condition("breathing_difficulty", "serious", 5),
  condition("major_trauma", "serious", 5),
  condition("seizure", "serious", 4),
  condition("sepsis", "serious", 4),
  condition("fall", "urgent", 2),
  condition("fracture", "urgent", 2),
];

export interface Modifier {
  code: string;
  label: string;
}
const modifier = (code: string): Modifier => ({
  code,
  get label() {
    return modifierLabel(code);
  },
});
/** Case modifiers that move a call up within its level (the first three can be set on a new call). */
export const MODIFIERS: Modifier[] = ["child", "deteriorating", "multiple_patients", "late_stroke_window", "no_bystander_cpr"].map(modifier);

export function modifierLabel(code: string): string {
  const key = `mod.${code}`;
  return hasKey(key) ? tx(key) : capitalise(code);
}

/** What the helpers need from a trip (all severity fields optional: older backends lack them). */
export type Graded = Pick<Trip, "priority"> &
  Partial<Pick<Trip, "severity" | "condition" | "condition_label" | "time_weight" | "response_target_min" | "modifiers">>;

export function levelOf(t: Graded): Level {
  if (t.severity && t.severity in LEVEL_RANK) return t.severity;
  return t.priority === "emergency" ? "serious" : t.priority === "urgent" ? "urgent" : "routine";
}

/**
 * The call's condition for display. English keeps the backend's label as before; Slovenian maps the
 * condition code to its Slovenian label (the backend's label is English), falling back to the label.
 */
export function conditionText(t: Graded): string | null {
  if (getLang() === "sl" && t.condition) {
    const key = `cond.${t.condition}`;
    if (hasKey(key)) return tx(key);
  }
  if (t.condition_label) return t.condition_label;
  if (!t.condition) return null;
  return conditionLabel(t.condition);
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
  if (r.minutes == null) return tx("resp.none", { target: r.target });
  return tx(r.reached ? "resp.reached" : "resp.reaches", { m: r.minutes, target: r.target });
}

/** The tooltip for a call's response line. */
export function responseTitle(r: ResponseInfo): string {
  if (r.minutes == null) return tx("resp.titleNone", { waited: Math.round(r.waited), target: r.target });
  return r.missed
    ? tx("resp.titleOver", { m: r.minutes, target: r.target, over: r.minutes - r.target })
    : tx("resp.titleTimed", { m: r.minutes, target: r.target });
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
