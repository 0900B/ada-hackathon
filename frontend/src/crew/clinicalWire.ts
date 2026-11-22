/**
 * The tablet's clinical entries as the ER backend takes them (POST /{world}/clinical/entries, see
 * docs/superpowers/specs/2026-11-22-er-dashboard-api-contract.md on the metelko-erdashboard branch).
 *
 * The tablet keeps its own entry shape (clinicalLog.ts); this is the one place that translates it,
 * so a change in the contract is a change here. Pure: `import type` only, erasable TypeScript, run
 * by `node --test`. Nothing is corrected or guessed: what the crew typed or said is sent as it is
 * (the backend decides what is plausible and sets `needs_check` itself).
 */
import type { ClinicalEntry } from "./clinicalLog";

/** What the backend accepts at the top level (unknown top-level keys are ignored, so none are sent). */
export interface WireBody {
  case_id: string;
  unit: string;
  source: ClinicalEntry["source"];
  type: string;
  content: Record<string, string | number>;
  state: ClinicalEntry["state"];
  client_entry_id: string;
  verbatim?: string;
  supersedes?: string;
}

/** The local event keys that have a backend `kind`. Others (defibrillation, patient worse) go as notes. */
const EVENT_KIND: Record<string, string> = {
  cardiac_arrest: "arrest",
  cpr_started: "resuscitation_started",
  rosc: "rosc",
  airway_secured: "airway",
  stroke_onset: "stroke_onset",
  stemi: "stemi",
  transfusion_started: "transfusion",
};

/** The vitals keys the backend names differently. */
const VITAL_KEY: Record<string, string> = { temp: "temp_c", glucose: "glucose_mmol" };
const VITAL_KEYS = ["hr", "sbp", "dbp", "spo2", "rr", "gcs", "temp", "glucose"];

const MAX_VERBATIM = 500;
const MAX_TEXT = 2000;
const DISCARDED_TEXT = "Discarded by crew";

const str = (v: unknown): string => (typeof v === "string" ? v : v === undefined || v === null ? "" : String(v));

/**
 * The request body for an entry, or null when there is nothing to send (a discard marker whose
 * target the server never stored, so there is nothing to retract).
 *
 * `serverIdOf` gives the server's `entry_id` for a client entry id once that entry was stored (a
 * confirmation or a discard names the entry it replaces by the server's id, not ours). A copy whose
 * original never got there is sent on its own.
 */
export function toWire(e: ClinicalEntry, serverIdOf: (clientEntryId: string) => string | null): WireBody | null {
  const c = e.content ?? {};
  const body: WireBody = {
    case_id: e.case_id,
    unit: e.unit,
    source: e.source,
    type: e.type,
    content: {},
    state: e.state,
    client_entry_id: e.client_entry_id,
  };
  const words = str(e.verbatim).trim();
  if (words) body.verbatim = words.slice(0, MAX_VERBATIM);
  const replaces = e.supersedes ? serverIdOf(e.supersedes) : null;
  if (replaces) body.supersedes = replaces;

  switch (e.type) {
    case "vitals": {
      const out: Record<string, number> = {};
      for (const k of VITAL_KEYS) {
        const v = c[k];
        if (typeof v === "number" && Number.isFinite(v)) out[VITAL_KEY[k] ?? k] = v;
      }
      body.content = out;
      return body;
    }
    case "drug_administered": {
      const dose = `${str(c.dose)} ${str(c.unit)}`.trim();
      body.content = { drug: str(c.drug), dose, route: str(c.route) };
      return body;
    }
    case "event": {
      const kind = EVENT_KIND[str(c.key)];
      if (!kind) {
        body.type = "note";
        body.content = { text: (str(c.label) || str(c.key) || "Event").slice(0, MAX_TEXT) };
        return body;
      }
      body.content = kind === "stroke_onset" ? { kind, onset_t: e.observed_t ?? e.t } : { kind };
      return body;
    }
    case "procedure":
      body.content = { name: (str(c.label) || str(c.name) || words || "Procedure").slice(0, 200) };
      return body;
    case "handover":
      body.content = { note: (str(c.note) || words || "Handover").slice(0, MAX_TEXT) };
      return body;
    case "note":
    default: {
      if (c.discarded === true) {
        if (!replaces) return null; // the server never stored the entry: nothing to retract
        body.type = "note";
        body.content = { text: DISCARDED_TEXT };
        return body;
      }
      body.type = "note";
      body.content = { text: (words || str(c.text) || "(empty)").slice(0, MAX_TEXT) };
      return body;
    }
  }
}
