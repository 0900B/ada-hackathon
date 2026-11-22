/**
 * What the tap pads (drug, vitals, event) do with a touch, as pure functions. Run by `node --test`
 * without tooling, so this file may only `import type` and must use erasable TypeScript.
 *
 * Nothing here corrects a number: what the crew typed is what is saved. A value outside its
 * plausible range is kept and marked "check this" by `makeEntry`, never changed.
 */
import type { VitalKey } from "./clinicalLog";

/** The vitals, in the order the pad shows them and the entry stores them. */
export const VITAL_KEYS: VitalKey[] = ["sbp", "dbp", "spo2", "hr", "rr", "temp", "glucose", "gcs"];

/** The longest number the pad takes (a dose or a vital never needs more). */
const MAX_LEN = 6;

/**
 * The value after one key press. Keys are "0" to "9", "." and "back". A lone "0" is replaced by the
 * next digit, "." works only when `allowDecimal` and only once (an empty value becomes "0."), and
 * anything else leaves the value as it is.
 */
export function padKey(value: string, key: string, allowDecimal: boolean): string {
  if (key === "back") return value.slice(0, -1);
  if (key === ".") {
    if (!allowDecimal || value.includes(".")) return value;
    if (value.length >= MAX_LEN) return value;
    return value === "" ? "0." : `${value}.`;
  }
  if (!/^[0-9]$/.test(key)) return value;
  if (value.length >= MAX_LEN) return value;
  return value === "0" ? key : value + key;
}

/** The number the typed text stands for: digits with at most one point; "", "." and the rest give null. */
export function parsePadNumber(value: string): number | null {
  if (!/^[0-9]+\.?[0-9]*$/.test(value) && !/^\.[0-9]+$/.test(value)) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** The `content` of a vitals entry: the filled fields as numbers, in vitals order; empty ones are left out. */
export function vitalsContent(fields: Partial<Record<VitalKey, string>>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const k of VITAL_KEYS) {
    const n = parsePadNumber(fields[k] ?? "");
    if (n !== null) out[k] = n;
  }
  return out;
}

/** Whether the drug pad can save: a drug name, a dose and a unit and route chosen. A zero dose can be saved (it is marked, not blocked). */
export function canSaveDrug(d: { drug: string; dose: string; unit: string; route: string }): boolean {
  return d.drug.trim() !== "" && parsePadNumber(d.dose) !== null && d.unit !== "" && d.route !== "";
}

/** The world time `minutesAgo` before `simTime` (ISO, UTC), or null when either is unreadable. */
export function observedAt(simTime: string, minutesAgo: number): string | null {
  const ms = Date.parse(simTime);
  if (!Number.isFinite(ms) || !Number.isFinite(minutesAgo) || minutesAgo < 0) return null;
  return new Date(ms - minutesAgo * 60_000).toISOString();
}
