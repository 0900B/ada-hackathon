import { test } from "node:test";
import assert from "node:assert/strict";
import { toWire } from "../../src/crew/clinicalWire.ts";
import type { ClinicalEntry } from "../../src/crew/clinicalLog.ts";

// The backend contract: docs/superpowers/specs/2026-11-22-er-dashboard-api-contract.md on the
// metelko-erdashboard branch (POST /{world}/clinical/entries).

const base: ClinicalEntry = {
  client_entry_id: "c1",
  case_id: "TR-002",
  unit: "A3",
  t: "2026-11-22T03:30:00+00:00",
  observed_t: null,
  recorded_at: "2026-11-22T03:15:00.000Z",
  source: "crew_tap",
  type: "note",
  content: {},
  verbatim: "",
  state: "confirmed",
  needs_check: false,
  supersedes: null,
  sync: "pending",
};
const make = (o: Partial<ClinicalEntry>): ClinicalEntry => ({ ...base, ...o });
const none = () => null;

test("toWire: the body carries only keys the backend takes (no local-only fields)", () => {
  const w = toWire(make({ type: "note", source: "crew_voice", state: "heard", verbatim: "bolnik je bled" }), none)!;
  assert.deepEqual(Object.keys(w).sort(), ["case_id", "client_entry_id", "content", "source", "state", "type", "unit", "verbatim"]);
  assert.equal(w.client_entry_id, "c1");
  assert.equal(w.case_id, "TR-002");
  assert.equal(w.unit, "A3");
  assert.equal(w.source, "crew_voice");
  assert.equal(w.state, "heard");
});

test("toWire: a spoken or typed note becomes {text} and keeps the words verbatim", () => {
  const w = toWire(make({ type: "note", source: "crew_voice", state: "heard", verbatim: "bolnik je nezavesten" }), none)!;
  assert.equal(w.type, "note");
  assert.deepEqual(w.content, { text: "bolnik je nezavesten" });
  assert.equal(w.verbatim, "bolnik je nezavesten");
});

test("toWire: a very long verbatim is cut to the 500 characters the backend allows", () => {
  const w = toWire(make({ verbatim: "x".repeat(900) }), none)!;
  assert.equal(w.verbatim!.length, 500);
});

test("toWire: vitals use the backend's key names and keep an implausible value as typed", () => {
  const w = toWire(
    make({ type: "vitals", content: { sbp: 120, dbp: 80, spo2: 920, hr: 90, rr: 16, gcs: 14, temp: 36.6, glucose: 5.5 } }),
    none,
  )!;
  assert.equal(w.type, "vitals");
  assert.deepEqual(w.content, { sbp: 120, dbp: 80, spo2: 920, hr: 90, rr: 16, gcs: 14, temp_c: 36.6, glucose_mmol: 5.5 });
});

test("toWire: a drug is {drug, dose, route} with the unit inside the dose text", () => {
  const w = toWire(make({ type: "drug_administered", content: { drug: "Morphine", dose: 5, unit: "mg", route: "i.v." } }), none)!;
  assert.equal(w.type, "drug_administered");
  assert.deepEqual(w.content, { drug: "Morphine", dose: "5 mg", route: "i.v." });
});

test("toWire: events the backend knows become {kind}", () => {
  const kinds: Record<string, string> = {
    cardiac_arrest: "arrest",
    cpr_started: "resuscitation_started",
    rosc: "rosc",
    airway_secured: "airway",
    stemi: "stemi",
    transfusion_started: "transfusion",
  };
  for (const [key, kind] of Object.entries(kinds)) {
    const w = toWire(make({ type: "event", content: { key, label: "x" } }), none)!;
    assert.equal(w.type, "event", key);
    assert.deepEqual(w.content, { kind }, key);
  }
});

test("toWire: stroke onset carries onset_t, the time it started, else the time it was logged", () => {
  const withObs = toWire(
    make({ type: "event", content: { key: "stroke_onset", label: "Stroke onset" }, observed_t: "2026-11-22T03:15:00.000Z" }),
    none,
  )!;
  assert.deepEqual(withObs.content, { kind: "stroke_onset", onset_t: "2026-11-22T03:15:00.000Z" });
  const without = toWire(make({ type: "event", content: { key: "stroke_onset", label: "Stroke onset" } }), none)!;
  assert.deepEqual(without.content, { kind: "stroke_onset", onset_t: "2026-11-22T03:30:00+00:00" });
});

test("toWire: an event the backend has no kind for is kept as a note with its name, never dropped", () => {
  for (const [key, label] of [["defibrillation", "Defibrillation"], ["patient_worse", "Patient worse"]]) {
    const w = toWire(make({ type: "event", content: { key, label } }), none)!;
    assert.equal(w.type, "note", key);
    assert.deepEqual(w.content, { text: label }, key);
  }
});

test("toWire: a confirmed copy supersedes the server's entry_id of the original, found by its client id", () => {
  const lookup = (id: string) => (id === "orig" ? "CE-00006" : null);
  const w = toWire(make({ type: "note", state: "confirmed", verbatim: "ok", supersedes: "orig" }), lookup)!;
  assert.equal(w.supersedes, "CE-00006");
  assert.equal(w.state, "confirmed");
});

test("toWire: a copy whose original never reached the server is sent on its own, without supersedes", () => {
  const w = toWire(make({ type: "note", verbatim: "ok", supersedes: "orig" }), none)!;
  assert.equal("supersedes" in w, false);
});

test("toWire: a discard marker becomes a note that supersedes the discarded entry", () => {
  const lookup = (id: string) => (id === "orig" ? "CE-00006" : null);
  const w = toWire(make({ type: "note", content: { discarded: true }, supersedes: "orig" }), lookup)!;
  assert.equal(w.type, "note");
  assert.equal(w.supersedes, "CE-00006");
  assert.equal(typeof (w.content as { text: string }).text, "string");
  assert.ok((w.content as { text: string }).text.length > 0);
});

test("toWire: a discard marker for an entry the server never took has nothing to retract (null)", () => {
  assert.equal(toWire(make({ type: "note", content: { discarded: true }, supersedes: "orig" }), none), null);
});

test("toWire: a handover entry is {note}", () => {
  const w = toWire(make({ type: "handover", content: { note: "Handed over to ER team" }, verbatim: "" }), none)!;
  assert.equal(w.type, "handover");
  assert.deepEqual(w.content, { note: "Handed over to ER team" });
});
