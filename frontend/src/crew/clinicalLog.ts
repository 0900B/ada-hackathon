/**
 * The crew's clinical log: entries, the rules that keep it honest, and the offline queue.
 * Pure functions only. This file is run by `node --test` without any tooling, so it may only
 * `import type` from other files (it imports nothing) and must use erasable TypeScript (no enums,
 * namespaces or parameter properties).
 *
 * Rules this module keeps:
 * - Nothing is guessed or corrected. A value that looks wrong is kept as entered and the entry is
 *   marked `needs_check`. Speech is stored word for word in `verbatim`; nothing here parses it.
 * - Time is the world's clock, passed in as ISO strings (`t`, `nowIso`). Ids and the real clock
 *   (`recordedAt`) are passed in too, and storage is a string handed to `parseLog`, so there is no
 *   `Date.now()`, `crypto`, `window` or `localStorage` in here. An invalid or missing time gives
 *   `null` or a safe value, never `NaN` or a negative age.
 * - Entries are never edited or removed. A correction is a new entry whose `supersedes` names the
 *   old one; a discard is a marker note. Every function returns a new array and leaves its input
 *   alone.
 * - Saving or confirming twice makes one entry, and a rejected or offline entry is never lost.
 */

export type EntryType = "vitals" | "drug_administered" | "procedure" | "event" | "note" | "handover";
export type EntryState = "heard" | "confirmed";
export type SyncState = "pending" | "sent" | "rejected";

export interface ClinicalEntry {
  client_entry_id: string;
  case_id: string; // the trip id
  unit: string;
  t: string; // world time when logged (state.sim_time)
  observed_t: string | null; // when it happened, if different (e.g. stroke onset)
  recorded_at: string; // real clock, ISO
  source: "crew_voice" | "crew_tap";
  type: EntryType;
  content: Record<string, string | number | boolean>;
  verbatim: string;
  state: EntryState;
  needs_check: boolean;
  supersedes: string | null;
  sync: SyncState;
}

// ---------------------------------------------------------------------------------------------
// PLACEHOLDER TABLES. The limits, intervals, drugs, routes, units and events below are labelled
// placeholders: they need an EMS clinician to confirm them before any real use (spec section 9).
// `needs_check` only flags data-entry sanity (a likely typo such as SpO2 920). It is not a clinical
// alarm and says nothing about whether a value is dangerous for the patient.
// ---------------------------------------------------------------------------------------------

export type VitalKey = "sbp" | "dbp" | "spo2" | "hr" | "rr" | "temp" | "glucose" | "gcs";

/** Plausible entry range for each vital, inclusive. Outside it the entry is `needs_check`. */
export const VITAL_LIMITS: Record<VitalKey, { min: number; max: number }> = {
  sbp: { min: 40, max: 260 },
  dbp: { min: 20, max: 160 },
  spo2: { min: 50, max: 100 },
  hr: { min: 20, max: 250 },
  rr: { min: 4, max: 60 },
  temp: { min: 30, max: 43 },
  glucose: { min: 1, max: 40 },
  gcs: { min: 3, max: 15 },
};

/** Minutes after which a new set of vitals is shown as overdue, by the case's severity level. */
export const VITALS_DUE_MIN: Record<"critical" | "serious" | "urgent" | "routine", number> = {
  critical: 5,
  serious: 10,
  urgent: 15,
  routine: 15,
};

/** Drug chips for the pad. Names only; the pad also takes free text for anything not listed. */
export const DRUGS: string[] = [
  "Morphine",
  "Fentanyl",
  "Adrenaline",
  "Amiodarone",
  "Aspirin",
  "Atropine",
  "Midazolam",
  "Naloxone",
  "Salbutamol",
  "Glucose",
];
export const ROUTES: string[] = ["i.v.", "i.o.", "i.m.", "s.c.", "p.o.", "inhaled", "s.l."];
export const UNITS: string[] = ["mg", "mcg", "ml", "g", "IU"];
export const EVENTS: { key: string; label: string }[] = [
  { key: "cardiac_arrest", label: "Cardiac arrest" },
  { key: "rosc", label: "ROSC" },
  { key: "cpr_started", label: "CPR started" },
  { key: "defibrillation", label: "Defibrillation" },
  { key: "airway_secured", label: "Airway secured" },
  { key: "stroke_onset", label: "Stroke onset" },
  { key: "stemi", label: "STEMI" },
  { key: "transfusion_started", label: "Transfusion started" },
  { key: "patient_worse", label: "Patient worse" },
];

/** An identical entry recorded within this many milliseconds of an existing one is a double tap. */
const DOUBLE_TAP_MS = 2000;

/** Order the vitals appear in a label; blood pressure comes first and is built from sbp and dbp. */
const VITAL_LABELS: [Exclude<VitalKey, "sbp" | "dbp">, string][] = [
  ["spo2", "SpO2"],
  ["hr", "HR"],
  ["rr", "RR"],
  ["temp", "Temp"],
  ["glucose", "Glucose"],
  ["gcs", "GCS"],
];

/** What a row says when an entry has no content and no words. */
const FALLBACK_LABEL: Record<EntryType, string> = {
  vitals: "Vitals",
  drug_administered: "Drug",
  procedure: "Procedure",
  event: "Event",
  note: "Note",
  handover: "Handover",
};

const ENTRY_TYPES: readonly string[] = ["vitals", "drug_administered", "procedure", "event", "note", "handover"];
const ENTRY_STATES: readonly string[] = ["heard", "confirmed"];
const SYNC_STATES: readonly string[] = ["pending", "sent", "rejected"];
const SOURCES: readonly string[] = ["crew_voice", "crew_tap"];

// ---------------------------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------------------------

/** Milliseconds for an ISO time, or null when it is missing or unreadable. */
function parseMs(iso: unknown): number | null {
  if (typeof iso !== "string" || iso === "") return null;
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? ms : null;
}

function has(obj: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function isSuperseded(log: readonly ClinicalEntry[], id: string): boolean {
  return log.some((e) => e.supersedes === id);
}

function isDiscardMarker(e: ClinicalEntry): boolean {
  return e.type === "note" && e.content.discarded === true;
}

/** True when the entry looks like a typo or is incomplete: this is data-entry sanity only. */
function checkNeeded(type: EntryType, content: ClinicalEntry["content"]): boolean {
  if (type === "vitals") {
    let readings = 0;
    for (const key of Object.keys(VITAL_LIMITS) as VitalKey[]) {
      if (!has(content, key)) continue;
      readings += 1;
      const v = content[key];
      const { min, max } = VITAL_LIMITS[key];
      if (!isFiniteNumber(v) || v < min || v > max) return true;
    }
    return readings === 0;
  }
  if (type === "drug_administered") {
    const { drug, dose, unit, route } = content;
    const named = typeof drug === "string" && drug.trim() !== "";
    const doseOk = isFiniteNumber(dose) && dose > 0;
    const unitOk = typeof unit === "string" && UNITS.includes(unit);
    const routeOk = typeof route === "string" && ROUTES.includes(route);
    return !(named && doseOk && unitOk && routeOk);
  }
  return false;
}

// ---------------------------------------------------------------------------------------------
// Making and changing the log
// ---------------------------------------------------------------------------------------------

/**
 * A new entry. A tap is `confirmed` (the crew entered it), speech is `heard` (it still needs a
 * confirmation). The id and the real-clock time are passed in, never generated here.
 */
export function makeEntry(
  i: {
    case_id: string;
    unit: string;
    t: string;
    source: ClinicalEntry["source"];
    type: EntryType;
    content: ClinicalEntry["content"];
    verbatim?: string;
    observed_t?: string | null;
  },
  d: { id: string; recordedAt: string },
): ClinicalEntry {
  const content = { ...i.content };
  return {
    client_entry_id: d.id,
    case_id: i.case_id,
    unit: i.unit,
    t: i.t,
    observed_t: i.observed_t ?? null,
    recorded_at: d.recordedAt,
    source: i.source,
    type: i.type,
    content,
    verbatim: i.verbatim ?? "",
    state: i.source === "crew_tap" ? "confirmed" : "heard",
    needs_check: checkNeeded(i.type, content),
    supersedes: null,
    sync: "pending",
  };
}

function sameContent(a: ClinicalEntry["content"], b: ClinicalEntry["content"]): boolean {
  const ka = Object.keys(a);
  if (ka.length !== Object.keys(b).length) return false;
  return ka.every((k) => has(b, k) && Object.is(a[k], b[k]));
}

/**
 * Add an entry. The same `client_entry_id` is added once, and an identical entry (same case, type,
 * content, verbatim and source) recorded within 2000 ms of an existing one is dropped as a double
 * tap; exactly 2000 ms apart still counts. If either `recorded_at` is unreadable nothing is
 * treated as a repeat.
 */
export function appendEntry(log: readonly ClinicalEntry[], e: ClinicalEntry): ClinicalEntry[] {
  if (log.some((x) => x.client_entry_id === e.client_entry_id)) return [...log];
  const at = parseMs(e.recorded_at);
  if (at !== null) {
    const repeat = log.some((x) => {
      const xAt = parseMs(x.recorded_at);
      return (
        xAt !== null &&
        Math.abs(at - xAt) <= DOUBLE_TAP_MS &&
        x.case_id === e.case_id &&
        x.type === e.type &&
        x.source === e.source &&
        x.verbatim === e.verbatim &&
        sameContent(x.content, e.content)
      );
    });
    if (repeat) return [...log];
  }
  return [...log, e];
}

/**
 * Confirm a heard entry by appending a confirmed copy that supersedes it (same `t`, same words).
 * Nothing happens (a new array of the same entries comes back) if the entry is unknown, already
 * confirmed, already superseded (confirmed, edited or discarded) or if `d.id` is already in use,
 * so a double tap makes one confirmation.
 */
export function confirmEntry(
  log: readonly ClinicalEntry[],
  id: string,
  d: { id: string; recordedAt: string },
): ClinicalEntry[] {
  const target = log.find((e) => e.client_entry_id === id);
  if (!target || target.state === "confirmed" || isSuperseded(log, id)) return [...log];
  if (log.some((e) => e.client_entry_id === d.id)) return [...log];
  const copy: ClinicalEntry = {
    ...target,
    content: { ...target.content },
    client_entry_id: d.id,
    recorded_at: d.recordedAt,
    state: "confirmed",
    supersedes: id,
    sync: "pending",
  };
  return [...log, copy];
}

/**
 * Discard an entry by appending a marker note `{ discarded: true }` that supersedes it. Nothing
 * happens if the entry is unknown or already superseded, or if `d.id` is already in use.
 */
export function discardEntry(
  log: readonly ClinicalEntry[],
  id: string,
  d: { id: string; recordedAt: string },
): ClinicalEntry[] {
  const target = log.find((e) => e.client_entry_id === id);
  if (!target || isSuperseded(log, id)) return [...log];
  if (log.some((e) => e.client_entry_id === d.id)) return [...log];
  const marker: ClinicalEntry = {
    client_entry_id: d.id,
    case_id: target.case_id,
    unit: target.unit,
    t: target.t,
    observed_t: null,
    recorded_at: d.recordedAt,
    source: "crew_tap",
    type: "note",
    content: { discarded: true },
    verbatim: "",
    state: "confirmed",
    needs_check: false,
    supersedes: id,
    sync: "pending",
  };
  return [...log, marker];
}

// ---------------------------------------------------------------------------------------------
// Reading the log
// ---------------------------------------------------------------------------------------------

/**
 * What the timeline shows: newest `t` first, without superseded entries and discard markers. Equal
 * times show the entry logged later first; an unreadable `t` sorts last.
 */
export function visibleEntries(log: readonly ClinicalEntry[]): ClinicalEntry[] {
  const superseded = new Set<string>();
  for (const e of log) if (e.supersedes) superseded.add(e.supersedes);
  return log
    .map((e, index) => ({ e, index, ms: parseMs(e.t) ?? -Infinity }))
    .filter(({ e }) => !superseded.has(e.client_entry_id) && !isDiscardMarker(e))
    .sort((a, b) => (a.ms !== b.ms ? (a.ms > b.ms ? -1 : 1) : b.index - a.index))
    .map(({ e }) => e);
}

/** The newest visible entry of a type (a discarded or superseded one does not count). */
export function latestOf(log: readonly ClinicalEntry[], type: EntryType): ClinicalEntry | undefined {
  return visibleEntries(log).find((e) => e.type === type);
}

/**
 * Whole minutes (rounded down) from when it happened (`observed_t` if set, else `t`) to `nowIso`.
 * Never negative: a time in the future is 0. Null if either time is missing or unreadable; an
 * unreadable `observed_t` is null, it does not fall back to `t`.
 */
export function ageMinutes(e: Pick<ClinicalEntry, "t" | "observed_t">, nowIso: string): number | null {
  const then = parseMs(e.observed_t == null ? e.t : e.observed_t);
  const now = parseMs(nowIso);
  if (then === null || now === null) return null;
  return Math.max(0, Math.floor((now - then) / 60_000));
}

const eventKey = (e: ClinicalEntry): unknown => (e.type === "event" && e.content ? e.content.key : undefined);

/**
 * Elapsed minutes for the timers panel: since the last drug, since CPR started (until a later ROSC),
 * and since stroke onset (counted from when it started, `observed_t`, not from when it was logged).
 * Elapsed time only, never advice. Discarded and superseded entries do not count; an unreadable time
 * gives null.
 */
export function timers(
  log: readonly ClinicalEntry[],
  nowIso: string,
): { lastDrugMin: number | null; cprMin: number | null; strokeOnsetMin: number | null } {
  const vis = visibleEntries(log);
  const drug = vis.find((e) => e.type === "drug_administered");
  const cpr = vis.find((e) => eventKey(e) === "cpr_started");
  const rosc = vis.find((e) => eventKey(e) === "rosc");
  const stroke = vis.find((e) => eventKey(e) === "stroke_onset");
  const happened = (e: ClinicalEntry) => parseMs(e.observed_t == null ? e.t : e.observed_t);
  const roscAfterCpr = !!cpr && !!rosc && (happened(rosc) ?? -Infinity) > (happened(cpr) ?? Infinity);
  return {
    lastDrugMin: drug ? ageMinutes(drug, nowIso) : null,
    cprMin: cpr && !roscAfterCpr ? ageMinutes(cpr, nowIso) : null,
    strokeOnsetMin: stroke ? ageMinutes(stroke, nowIso) : null,
  };
}

/**
 * How old the newest vitals are and whether a new set is due. Overdue from the level's interval
 * on (`ageMin >= VITALS_DUE_MIN[level]`, as `ageMin` is rounded down). No vitals, or an age that
 * cannot be worked out, is overdue with a null age: the screen cannot show that they are recent.
 * An unknown level uses the shortest interval.
 */
export function vitalsStatus(
  log: readonly ClinicalEntry[],
  nowIso: string,
  level: keyof typeof VITALS_DUE_MIN,
): { ageMin: number | null; overdue: boolean } {
  const latest = latestOf(log, "vitals");
  if (!latest) return { ageMin: null, overdue: true };
  const ageMin = ageMinutes(latest, nowIso);
  if (ageMin === null) return { ageMin: null, overdue: true };
  const due = VITALS_DUE_MIN[level] ?? Math.min(...Object.values(VITALS_DUE_MIN));
  return { ageMin, overdue: ageMin >= due };
}

/** The words on a timeline row. Values are shown exactly as entered. */
export function entryLabel(e: ClinicalEntry): string {
  const c = e.content && typeof e.content === "object" ? e.content : {};
  const words = typeof e.verbatim === "string" && e.verbatim.trim() !== "" ? e.verbatim : "";
  const fallback = (FALLBACK_LABEL as Record<string, string | undefined>)[e.type] ?? "Entry";
  const text = (v: unknown): string => (typeof v === "string" ? v.trim() : "");

  if (e.type === "vitals") {
    const parts: string[] = [];
    const sbp = has(c, "sbp") ? String(c.sbp) : null;
    const dbp = has(c, "dbp") ? String(c.dbp) : null;
    if (sbp !== null && dbp !== null) parts.push(`BP ${sbp}/${dbp}`);
    else if (sbp !== null) parts.push(`SBP ${sbp}`);
    else if (dbp !== null) parts.push(`DBP ${dbp}`);
    for (const [key, label] of VITAL_LABELS) if (has(c, key)) parts.push(`${label} ${String(c[key])}`);
    return parts.length > 0 ? parts.join(" · ") : words || fallback;
  }
  if (e.type === "drug_administered") {
    const parts = [c.drug, c.dose, c.unit, c.route].filter((v) => v !== undefined && String(v).trim() !== "");
    return parts.length > 0 ? parts.map(String).join(" ") : words || fallback;
  }
  if (e.type === "event") {
    const fromTable = EVENTS.find((x) => x.key === c.key)?.label;
    return text(c.label) || fromTable || text(c.key) || words || fallback;
  }
  if (e.type === "procedure") return text(c.label) || words || fallback;
  return words || fallback;
}

/** True for a line that is only "potrjeno" or "confirmed", ignoring case, spaces and punctuation. */
export function isConfirmPhrase(text: string): boolean {
  if (typeof text !== "string") return false;
  const word = text.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
  return word === "potrjeno" || word === "confirmed";
}

// ---------------------------------------------------------------------------------------------
// Storage and the offline queue
// ---------------------------------------------------------------------------------------------

/** The storage key for one trip's log in one world, so a new trip never shows another patient. */
export const storageKey = (world: string, caseId: string): string =>
  `crew-log:v1:${encodeURIComponent(world)}:${encodeURIComponent(caseId)}`;

/** An entry from storage if it has the right shape, else null. Extra fields are not carried over. */
function readEntry(raw: unknown): ClinicalEntry | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;
  const { client_entry_id, case_id, unit, t, observed_t, recorded_at, source, type, verbatim, state, needs_check, supersedes, sync } = r;
  if (
    typeof client_entry_id !== "string" ||
    typeof case_id !== "string" ||
    typeof unit !== "string" ||
    typeof t !== "string" ||
    !(observed_t === null || typeof observed_t === "string") ||
    typeof recorded_at !== "string" ||
    typeof source !== "string" || !SOURCES.includes(source) ||
    typeof type !== "string" || !ENTRY_TYPES.includes(type) ||
    typeof verbatim !== "string" ||
    typeof state !== "string" || !ENTRY_STATES.includes(state) ||
    typeof needs_check !== "boolean" ||
    !(supersedes === null || typeof supersedes === "string") ||
    typeof sync !== "string" || !SYNC_STATES.includes(sync)
  ) {
    return null;
  }
  const rawContent = r.content;
  if (typeof rawContent !== "object" || rawContent === null || Array.isArray(rawContent)) return null;
  // JSON turns NaN and Infinity into null; a value that did not survive is dropped and flagged.
  const content: ClinicalEntry["content"] = {};
  let lost = false;
  for (const [k, v] of Object.entries(rawContent)) {
    if (typeof v === "string" || typeof v === "boolean" || isFiniteNumber(v)) content[k] = v;
    else lost = true;
  }
  return {
    client_entry_id,
    case_id,
    unit,
    t,
    observed_t,
    recorded_at,
    source: source as ClinicalEntry["source"],
    type: type as EntryType,
    content,
    verbatim,
    state: state as EntryState,
    needs_check: needs_check || lost,
    supersedes,
    sync: sync as SyncState,
  };
}

/**
 * The log from its stored JSON. Missing, broken or wrong-shaped input gives an empty log, never a
 * throw. Entries with the wrong shape are skipped and the rest are kept; a repeated
 * `client_entry_id` keeps the first.
 */
export function parseLog(json: string | null): ClinicalEntry[] {
  if (typeof json !== "string" || json === "") return [];
  let data: unknown;
  try {
    data = JSON.parse(json);
  } catch {
    return [];
  }
  if (!Array.isArray(data)) return [];
  const seen = new Set<string>();
  const out: ClinicalEntry[] = [];
  for (const raw of data) {
    const e = readEntry(raw);
    if (!e || seen.has(e.client_entry_id)) continue;
    seen.add(e.client_entry_id);
    out.push(e);
  }
  return out;
}

/**
 * Send the pending entries oldest first (the log's own order, so a correction always follows what
 * it corrects). `post` says what became of each one: "sent" and "rejected" are final and the queue
 * goes on; "pending" (no signal, backend missing) stops the queue so nothing is sent out of order.
 * A `post` that throws or answers something else counts as "pending". Entries already `sent` or
 * `rejected` are never posted again. Returns a new log; only `sync` marks change.
 */
export async function syncPending(
  log: readonly ClinicalEntry[],
  post: (e: ClinicalEntry) => Promise<SyncState>,
): Promise<ClinicalEntry[]> {
  const out = [...log];
  for (let i = 0; i < out.length; i++) {
    const e = out[i];
    if (e.sync !== "pending") continue;
    let result: SyncState;
    try {
      result = await post(e);
    } catch {
      break;
    }
    if (result !== "sent" && result !== "rejected") break;
    out[i] = { ...e, sync: result };
  }
  return out;
}
