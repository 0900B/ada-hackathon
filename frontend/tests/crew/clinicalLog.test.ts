import { test } from "node:test";
import assert from "node:assert/strict";
import {
  VITAL_LIMITS,
  VITALS_DUE_MIN,
  DRUGS,
  ROUTES,
  UNITS,
  EVENTS,
  makeEntry,
  appendEntry,
  confirmEntry,
  discardEntry,
  visibleEntries,
  latestOf,
  ageMinutes,
  vitalsStatus,
  entryLabel,
  isConfirmPhrase,
  storageKey,
  parseLog,
  syncPending,
  timers,
  handoverLines,
  type ClinicalEntry,
  type SyncState,
} from "../../src/crew/clinicalLog.ts";

const T0 = "2026-11-21T12:00:00.000Z";
/** An ISO time `sec` seconds after T0 (negative for before). */
const at = (sec: number): string => new Date(Date.parse(T0) + sec * 1000).toISOString();

type Input = Parameters<typeof makeEntry>[0];
let counter = 0;
/** A valid entry with a unique id, a unique verbatim and a unique recorded_at unless overridden. */
function mk(over: Partial<Input> = {}, d: { id?: string; recordedAt?: string } = {}): ClinicalEntry {
  counter += 1;
  return makeEntry(
    { case_id: "TR-001", unit: "A3", t: T0, source: "crew_tap", type: "note", content: {}, verbatim: `text ${counter}`, ...over },
    { id: d.id ?? `e${counter}`, recordedAt: d.recordedAt ?? at(counter * 60) },
  );
}

// makeEntry --------------------------------------------------------------------------------

test("makeEntry: a tap is confirmed, a voice entry is heard", () => {
  assert.equal(mk({ source: "crew_tap" }).state, "confirmed");
  assert.equal(mk({ source: "crew_voice" }).state, "heard");
});

test("makeEntry: fills the fixed fields from the input and the injected id and time", () => {
  const e = makeEntry(
    { case_id: "TR-007", unit: "A9", t: T0, source: "crew_voice", type: "note", content: {}, verbatim: "bolnik je bled" },
    { id: "abc", recordedAt: at(5) },
  );
  assert.equal(e.client_entry_id, "abc");
  assert.equal(e.recorded_at, at(5));
  assert.equal(e.case_id, "TR-007");
  assert.equal(e.unit, "A9");
  assert.equal(e.t, T0);
  assert.equal(e.observed_t, null);
  assert.equal(e.verbatim, "bolnik je bled");
  assert.equal(e.supersedes, null);
  assert.equal(e.sync, "pending");
  assert.equal(e.needs_check, false);
});

test("makeEntry: verbatim defaults to an empty string and observed_t is kept when given", () => {
  const e = mk({ type: "event", content: { key: "stroke_onset", label: "Stroke onset" }, verbatim: undefined, observed_t: at(-900) });
  assert.equal(e.verbatim, "");
  assert.equal(e.observed_t, at(-900));
});

test("makeEntry: copies the content, so changing the input afterwards does not change the entry", () => {
  const content: Record<string, number> = { spo2: 92 };
  const e = mk({ type: "vitals", content });
  content.spo2 = 50;
  assert.equal(e.content.spo2, 92);
});

test("makeEntry: spo2 920 is kept as 920 and marked needs_check; 92 is not", () => {
  const bad = mk({ type: "vitals", content: { spo2: 920 } });
  assert.equal(bad.needs_check, true);
  assert.equal(bad.content.spo2, 920); // never corrected
  const ok = mk({ type: "vitals", content: { spo2: 92 } });
  assert.equal(ok.needs_check, false);
  assert.equal(ok.content.spo2, 92);
});

test("makeEntry: every vital limit is inclusive and one step outside is needs_check", () => {
  for (const [key, { min, max }] of Object.entries(VITAL_LIMITS)) {
    assert.equal(mk({ type: "vitals", content: { [key]: min } }).needs_check, false, `${key} at min`);
    assert.equal(mk({ type: "vitals", content: { [key]: max } }).needs_check, false, `${key} at max`);
    assert.equal(mk({ type: "vitals", content: { [key]: min - 1 } }).needs_check, true, `${key} below min`);
    assert.equal(mk({ type: "vitals", content: { [key]: max + 1 } }).needs_check, true, `${key} above max`);
  }
});

test("makeEntry: a vital that is not a finite number is needs_check and kept as given", () => {
  const text = mk({ type: "vitals", content: { sbp: 120, hr: "ninety" } });
  assert.equal(text.needs_check, true);
  assert.equal(text.content.hr, "ninety");
  assert.equal(mk({ type: "vitals", content: { hr: Number.NaN } }).needs_check, true);
  assert.equal(mk({ type: "vitals", content: { hr: Number.POSITIVE_INFINITY } }).needs_check, true);
});

test("makeEntry: a full plausible set of vitals is not needs_check, and a vitals entry with no readings is", () => {
  const full = mk({ type: "vitals", content: { sbp: 120, dbp: 80, spo2: 92, hr: 96, rr: 16, temp: 36.6, glucose: 5.5, gcs: 15 } });
  assert.equal(full.needs_check, false);
  assert.equal(mk({ type: "vitals", content: {} }).needs_check, true);
});

test("makeEntry: a drug needs drug, a positive dose, a known unit and a known route, otherwise needs_check", () => {
  const ok = { drug: "Morphine", dose: 5, unit: "mg", route: "i.v." };
  assert.equal(mk({ type: "drug_administered", content: ok }).needs_check, false);
  assert.equal(mk({ type: "drug_administered", content: { ...ok, dose: 0 } }).needs_check, true);
  assert.equal(mk({ type: "drug_administered", content: { ...ok, dose: -5 } }).needs_check, true);
  assert.equal(mk({ type: "drug_administered", content: { ...ok, dose: Number.NaN } }).needs_check, true);
  assert.equal(mk({ type: "drug_administered", content: { ...ok, unit: "furlongs" } }).needs_check, true);
  assert.equal(mk({ type: "drug_administered", content: { ...ok, route: "rectal-ish" } }).needs_check, true);
  assert.equal(mk({ type: "drug_administered", content: { drug: "Morphine", dose: 5, unit: "mg" } }).needs_check, true);
  assert.equal(mk({ type: "drug_administered", content: { ...ok, drug: "" } }).needs_check, true);
  // a drug that is not in the placeholder list is free text from the "Other" chip, so it is not flagged
  assert.equal(mk({ type: "drug_administered", content: { ...ok, drug: "Something unlisted" } }).needs_check, false);
});

test("makeEntry: notes, events and procedures are not needs_check", () => {
  assert.equal(mk({ type: "note", source: "crew_voice", content: {}, verbatim: "dva tisoč" }).needs_check, false);
  assert.equal(mk({ type: "event", content: { key: "rosc", label: "ROSC" } }).needs_check, false);
  assert.equal(mk({ type: "procedure", content: { label: "IV access" } }).needs_check, false);
});

test("the placeholder tables hold the agreed values", () => {
  assert.deepEqual(VITAL_LIMITS, {
    sbp: { min: 40, max: 260 },
    dbp: { min: 20, max: 160 },
    spo2: { min: 50, max: 100 },
    hr: { min: 20, max: 250 },
    rr: { min: 4, max: 60 },
    temp: { min: 30, max: 43 },
    glucose: { min: 1, max: 40 },
    gcs: { min: 3, max: 15 },
  });
  assert.deepEqual(VITALS_DUE_MIN, { critical: 5, serious: 10, urgent: 15, routine: 15 });
  assert.deepEqual(ROUTES, ["i.v.", "i.o.", "i.m.", "s.c.", "p.o.", "inhaled", "s.l."]);
  assert.deepEqual(UNITS, ["mg", "mcg", "ml", "g", "IU"]);
  assert.deepEqual(EVENTS, [
    { key: "cardiac_arrest", label: "Cardiac arrest" },
    { key: "rosc", label: "ROSC" },
    { key: "cpr_started", label: "CPR started" },
    { key: "defibrillation", label: "Defibrillation" },
    { key: "airway_secured", label: "Airway secured" },
    { key: "stroke_onset", label: "Stroke onset" },
    { key: "stemi", label: "STEMI" },
    { key: "transfusion_started", label: "Transfusion started" },
    { key: "patient_worse", label: "Patient worse" },
  ]);
  assert.ok(DRUGS.includes("Morphine"));
  assert.equal(new Set(DRUGS).size, DRUGS.length);
});

// appendEntry ------------------------------------------------------------------------------

test("appendEntry: adds an entry and returns a new array without touching the input", () => {
  const a = mk();
  const b = mk();
  const log: readonly ClinicalEntry[] = Object.freeze([a]);
  const out = appendEntry(log, b);
  assert.deepEqual(out.map((e) => e.client_entry_id), [a.client_entry_id, b.client_entry_id]);
  assert.notEqual(out, log);
  assert.equal(log.length, 1);
});

test("appendEntry: the same client_entry_id twice gives one entry (double tap)", () => {
  const e = mk();
  const once = appendEntry([], e);
  const twice = appendEntry(once, e);
  assert.equal(twice.length, 1);
  assert.notEqual(twice, once); // still a new array
});

test("appendEntry: an identical entry within 2000 ms is dropped, 2500 ms later it is kept (double tap)", () => {
  const first = mk({ type: "event", content: { key: "rosc", label: "ROSC" }, verbatim: "" }, { id: "x1", recordedAt: at(0) });
  const log = appendEntry([], first);
  const quick = mk({ type: "event", content: { key: "rosc", label: "ROSC" }, verbatim: "" }, { id: "x2", recordedAt: at(1) });
  assert.equal(appendEntry(log, quick).length, 1);
  const edge = mk({ type: "event", content: { key: "rosc", label: "ROSC" }, verbatim: "" }, { id: "x3", recordedAt: at(2) });
  assert.equal(appendEntry(log, edge).length, 1, "exactly 2000 ms apart still counts as a double tap");
  const slow = mk({ type: "event", content: { key: "rosc", label: "ROSC" }, verbatim: "" }, { id: "x4", recordedAt: at(2.5) });
  assert.equal(appendEntry(log, slow).length, 2);
});

test("appendEntry: a quick entry that differs in case, type, content, verbatim or source is kept", () => {
  const base = { type: "note", content: {}, verbatim: "same words", case_id: "TR-001", source: "crew_voice" } as const;
  const first = mk(base, { id: "y1", recordedAt: at(0) });
  const log = appendEntry([], first);
  const variants: Partial<Input>[] = [
    { case_id: "TR-002" },
    { type: "procedure" },
    { content: { extra: 1 } },
    { verbatim: "other words" },
    { source: "crew_tap" },
  ];
  variants.forEach((v, i) => {
    const other = mk({ ...base, ...v }, { id: `y-other-${i}`, recordedAt: at(0.5) });
    assert.equal(appendEntry(log, other).length, 2, JSON.stringify(v));
  });
});

test("appendEntry: with an unreadable recorded_at a repeat is not treated as a double tap", () => {
  const first = mk({ verbatim: "w" }, { id: "z1", recordedAt: "garbage" });
  const second = mk({ verbatim: "w" }, { id: "z2", recordedAt: "garbage" });
  assert.equal(appendEntry(appendEntry([], first), second).length, 2);
});

// confirmEntry -----------------------------------------------------------------------------

test("confirmEntry: appends a confirmed copy that supersedes the heard entry and keeps t", () => {
  const heard = mk({ source: "crew_voice", verbatim: "bolnik je bled", t: at(30), observed_t: at(-60) });
  const log: readonly ClinicalEntry[] = Object.freeze([heard]);
  const out = confirmEntry(log, heard.client_entry_id, { id: "c1", recordedAt: at(900) });
  assert.equal(log.length, 1, "input is untouched");
  assert.equal(heard.state, "heard", "the original is untouched");
  assert.equal(out.length, 2);
  const copy = out[1];
  assert.equal(copy.client_entry_id, "c1");
  assert.equal(copy.recorded_at, at(900));
  assert.equal(copy.supersedes, heard.client_entry_id);
  assert.equal(copy.state, "confirmed");
  assert.equal(copy.t, heard.t);
  assert.equal(copy.observed_t, heard.observed_t);
  assert.equal(copy.verbatim, heard.verbatim);
  assert.equal(copy.type, heard.type);
  assert.equal(copy.case_id, heard.case_id);
  assert.equal(copy.sync, "pending");
});

test("confirmEntry: twice on one id gives one confirmation and visibleEntries shows only the confirmed copy (double tap)", () => {
  const heard = mk({ source: "crew_voice", verbatim: "bolnik je bled", t: at(30) });
  const once = confirmEntry([heard], heard.client_entry_id, { id: "c1", recordedAt: at(900) });
  const twice = confirmEntry(once, heard.client_entry_id, { id: "c2", recordedAt: at(901) });
  assert.equal(twice.length, 2);
  assert.equal(twice.filter((e) => e.supersedes === heard.client_entry_id).length, 1);
  const shown = visibleEntries(twice);
  assert.equal(shown.length, 1);
  assert.equal(shown[0].client_entry_id, "c1");
  assert.equal(shown[0].state, "confirmed");
  assert.equal(shown[0].t, heard.t);
});

test("confirmEntry: no-op for an already confirmed entry, an unknown id and a discarded entry", () => {
  const tap = mk({ source: "crew_tap" });
  const heard = mk({ source: "crew_voice" });
  const discarded = discardEntry([heard], heard.client_entry_id, { id: "d1", recordedAt: at(10) });
  assert.equal(confirmEntry([tap], tap.client_entry_id, { id: "c1", recordedAt: at(1) }).length, 1);
  assert.equal(confirmEntry([tap], "nope", { id: "c2", recordedAt: at(1) }).length, 1);
  assert.equal(confirmEntry(discarded, heard.client_entry_id, { id: "c3", recordedAt: at(1) }).length, 2);
});

test("confirmEntry: a no-op still returns a new array", () => {
  const tap = mk({ source: "crew_tap" });
  const log = [tap];
  assert.notEqual(confirmEntry(log, "nope", { id: "c", recordedAt: at(1) }), log);
});

// discardEntry -----------------------------------------------------------------------------

test("discardEntry: hides the entry and the marker, and leaves the input unchanged", () => {
  const keep = mk({ verbatim: "keep me", t: at(10) });
  const gone = mk({ source: "crew_voice", verbatim: "wrong", t: at(20) });
  const log: readonly ClinicalEntry[] = Object.freeze([keep, gone]);
  const out = discardEntry(log, gone.client_entry_id, { id: "d1", recordedAt: at(500) });
  assert.equal(log.length, 2, "input is untouched");
  assert.equal(out.length, 3);
  const marker = out[2];
  assert.equal(marker.type, "note");
  assert.equal(marker.content.discarded, true);
  assert.equal(marker.supersedes, gone.client_entry_id);
  assert.equal(marker.client_entry_id, "d1");
  assert.equal(marker.case_id, gone.case_id);
  assert.deepEqual(visibleEntries(out).map((e) => e.client_entry_id), [keep.client_entry_id]);
});

test("discardEntry: twice, or an unknown id, adds no second marker", () => {
  const e = mk({ source: "crew_voice" });
  const once = discardEntry([e], e.client_entry_id, { id: "d1", recordedAt: at(1) });
  assert.equal(discardEntry(once, e.client_entry_id, { id: "d2", recordedAt: at(2) }).length, 2);
  assert.equal(discardEntry([e], "nope", { id: "d3", recordedAt: at(2) }).length, 1);
});

test("discardEntry: a confirmed entry can be discarded too", () => {
  const e = mk({ source: "crew_tap" });
  const out = discardEntry([e], e.client_entry_id, { id: "d1", recordedAt: at(1) });
  assert.deepEqual(visibleEntries(out), []);
});

// visibleEntries and latestOf --------------------------------------------------------------

test("visibleEntries: newest t first, the log's own order does not matter", () => {
  const a = mk({ t: at(10) });
  const b = mk({ t: at(30) });
  const c = mk({ t: at(20) });
  assert.deepEqual(visibleEntries([a, b, c]).map((e) => e.t), [at(30), at(20), at(10)]);
});

test("visibleEntries: equal t shows the later logged entry first; an unreadable t sorts last", () => {
  const first = mk({ t: at(10) });
  const second = mk({ t: at(10) });
  const broken = mk({ t: "garbage" });
  assert.deepEqual(
    visibleEntries([broken, first, second]).map((e) => e.client_entry_id),
    [second.client_entry_id, first.client_entry_id, broken.client_entry_id],
  );
});

test("visibleEntries: does not mutate the input and hides every superseded link of a chain", () => {
  const a = mk({ source: "crew_voice", t: at(10) });
  const log1 = confirmEntry([a], a.client_entry_id, { id: "c1", recordedAt: at(100) });
  const order = log1.map((e) => e.client_entry_id);
  const shown = visibleEntries(log1);
  assert.deepEqual(log1.map((e) => e.client_entry_id), order);
  assert.deepEqual(shown.map((e) => e.client_entry_id), ["c1"]);
});

test("latestOf: the newest visible entry of a type, ignoring discarded and other types", () => {
  const older = mk({ type: "vitals", content: { hr: 80 }, t: at(10) });
  const newer = mk({ type: "vitals", content: { hr: 90 }, t: at(60) });
  const note = mk({ type: "note", t: at(120) });
  const log = [older, newer, note];
  assert.equal(latestOf(log, "vitals")?.client_entry_id, newer.client_entry_id);
  const afterDiscard = discardEntry(log, newer.client_entry_id, { id: "d1", recordedAt: at(200) });
  assert.equal(latestOf(afterDiscard, "vitals")?.client_entry_id, older.client_entry_id);
  assert.equal(latestOf(log, "drug_administered"), undefined);
  assert.equal(latestOf([], "vitals"), undefined);
});

// ageMinutes and vitalsStatus --------------------------------------------------------------

test("ageMinutes: floor of whole minutes, 6 for 6 min 40 s", () => {
  assert.equal(ageMinutes({ t: T0, observed_t: null }, at(400)), 6);
  assert.equal(ageMinutes({ t: T0, observed_t: null }, at(59)), 0);
  assert.equal(ageMinutes({ t: T0, observed_t: null }, at(60)), 1);
});

test("ageMinutes: never negative, 0 when t is in the future", () => {
  assert.equal(ageMinutes({ t: at(300), observed_t: null }, T0), 0);
});

test("ageMinutes: null for an invalid t, an invalid or empty now, and an unreadable observed_t (Review Focus 5)", () => {
  assert.equal(ageMinutes({ t: "garbage", observed_t: null }, T0), null);
  assert.equal(ageMinutes({ t: "", observed_t: null }, T0), null);
  assert.equal(ageMinutes({ t: T0, observed_t: null }, "garbage"), null);
  assert.equal(ageMinutes({ t: T0, observed_t: null }, ""), null);
  assert.equal(ageMinutes({ t: T0, observed_t: "garbage" }, at(600)), null, "does not silently fall back to t");
  for (const age of [
    ageMinutes({ t: "garbage", observed_t: null }, "garbage"),
    ageMinutes({ t: T0, observed_t: null }, "garbage"),
  ]) {
    assert.ok(age === null || (Number.isFinite(age) && age >= 0));
  }
});

test("ageMinutes: uses observed_t when set", () => {
  assert.equal(ageMinutes({ t: at(600), observed_t: T0 }, at(900)), 15);
  assert.equal(ageMinutes({ t: at(600), observed_t: null }, at(900)), 5);
});

test("vitalsStatus: no vitals gives a null age and overdue", () => {
  assert.deepEqual(vitalsStatus([], T0, "critical"), { ageMin: null, overdue: true });
  const noVitals = [mk({ type: "note" })];
  assert.deepEqual(vitalsStatus(noVitals, T0, "routine"), { ageMin: null, overdue: true });
});

test("vitalsStatus: critical is overdue from 5 min, so 4 min is fine and 6 min is overdue", () => {
  const v = mk({ type: "vitals", content: { hr: 90 }, t: T0 });
  assert.deepEqual(vitalsStatus([v], at(240), "critical"), { ageMin: 4, overdue: false });
  assert.deepEqual(vitalsStatus([v], at(299), "critical"), { ageMin: 4, overdue: false });
  assert.deepEqual(vitalsStatus([v], at(300), "critical"), { ageMin: 5, overdue: true });
  assert.deepEqual(vitalsStatus([v], at(360), "critical"), { ageMin: 6, overdue: true });
});

test("vitalsStatus: each level uses its own interval", () => {
  const v = mk({ type: "vitals", content: { hr: 90 }, t: T0 });
  assert.equal(vitalsStatus([v], at(9 * 60), "serious").overdue, false);
  assert.equal(vitalsStatus([v], at(10 * 60), "serious").overdue, true);
  assert.equal(vitalsStatus([v], at(14 * 60), "urgent").overdue, false);
  assert.equal(vitalsStatus([v], at(15 * 60), "urgent").overdue, true);
  assert.equal(vitalsStatus([v], at(14 * 60), "routine").overdue, false);
  assert.equal(vitalsStatus([v], at(15 * 60), "routine").overdue, true);
});

test("vitalsStatus: uses the newest vitals and ignores a discarded one", () => {
  const old = mk({ type: "vitals", content: { hr: 80 }, t: T0 });
  const fresh = mk({ type: "vitals", content: { hr: 90 }, t: at(240) });
  assert.deepEqual(vitalsStatus([old, fresh], at(300), "critical"), { ageMin: 1, overdue: false });
  const dropped = discardEntry([old, fresh], fresh.client_entry_id, { id: "d1", recordedAt: at(1) });
  assert.deepEqual(vitalsStatus(dropped, at(300), "critical"), { ageMin: 5, overdue: true });
});

test("vitalsStatus: an unreadable time gives a null age and counts as overdue, never NaN (Review Focus 5)", () => {
  const v = mk({ type: "vitals", content: { hr: 90 }, t: T0 });
  assert.deepEqual(vitalsStatus([v], "garbage", "critical"), { ageMin: null, overdue: true });
  const badT = mk({ type: "vitals", content: { hr: 90 }, t: "garbage" });
  assert.deepEqual(vitalsStatus([badT], T0, "routine"), { ageMin: null, overdue: true });
});

test("vitalsStatus: an unknown level falls back to the shortest interval", () => {
  const v = mk({ type: "vitals", content: { hr: 90 }, t: T0 });
  // @ts-expect-error a level the type does not allow, as a corrupt or future backend value would be
  assert.equal(vitalsStatus([v], at(5 * 60), "unknown").overdue, true);
  // @ts-expect-error same
  assert.equal(vitalsStatus([v], at(4 * 60), undefined).overdue, false);
});

// entryLabel -------------------------------------------------------------------------------

test("entryLabel: vitals read as BP, SpO2 and HR with the values as entered", () => {
  const v = mk({ type: "vitals", content: { sbp: 120, dbp: 80, spo2: 92, hr: 96 } });
  assert.equal(entryLabel(v), "BP 120/80 · SpO2 92 · HR 96");
});

test("entryLabel: every vital has a label, in a fixed order, and a mis-typed value is shown as entered", () => {
  const v = mk({ type: "vitals", content: { gcs: 14, glucose: 5.5, temp: 36.6, rr: 16, hr: 96, spo2: 920, dbp: 80, sbp: 120 } });
  assert.equal(entryLabel(v), "BP 120/80 · SpO2 920 · HR 96 · RR 16 · Temp 36.6 · Glucose 5.5 · GCS 14");
});

test("entryLabel: a lone systolic or diastolic is not shown as a pair, and empty vitals fall back to a word", () => {
  assert.equal(entryLabel(mk({ type: "vitals", content: { sbp: 120 } })), "SBP 120");
  assert.equal(entryLabel(mk({ type: "vitals", content: { dbp: 80 } })), "DBP 80");
  assert.equal(entryLabel(mk({ type: "vitals", content: {}, verbatim: "" })), "Vitals");
});

test("entryLabel: a drug reads as name, dose, unit, route", () => {
  const d = mk({ type: "drug_administered", content: { drug: "Morphine", dose: 5, unit: "mg", route: "i.v." } });
  assert.equal(entryLabel(d), "Morphine 5 mg i.v.");
  const partial = mk({ type: "drug_administered", content: { drug: "Aspirin", dose: 300, unit: "mg" } });
  assert.equal(entryLabel(partial), "Aspirin 300 mg");
});

test("entryLabel: an event shows its label, falling back to the table, the key, then the verbatim text", () => {
  assert.equal(entryLabel(mk({ type: "event", content: { key: "rosc", label: "ROSC" } })), "ROSC");
  assert.equal(entryLabel(mk({ type: "event", content: { key: "stemi" } })), "STEMI");
  assert.equal(entryLabel(mk({ type: "event", content: { key: "custom_thing" } })), "custom_thing");
  assert.equal(entryLabel(mk({ type: "event", content: {}, verbatim: "something happened" })), "something happened");
  assert.equal(entryLabel(mk({ type: "event", content: {}, verbatim: "" })), "Event");
});

test("entryLabel: a note is its verbatim text, and an empty one gets a word", () => {
  assert.equal(entryLabel(mk({ type: "note", source: "crew_voice", verbatim: "bolnik je bled" })), "bolnik je bled");
  assert.equal(entryLabel(mk({ type: "note", verbatim: "" })), "Note");
});

test("entryLabel: procedure and handover use their label or verbatim text, an unknown type does not throw", () => {
  assert.equal(entryLabel(mk({ type: "procedure", content: { label: "IV access" } })), "IV access");
  assert.equal(entryLabel(mk({ type: "procedure", content: {}, verbatim: "splint left arm" })), "splint left arm");
  assert.equal(entryLabel(mk({ type: "procedure", content: {}, verbatim: "" })), "Procedure");
  assert.equal(entryLabel(mk({ type: "handover", content: {}, verbatim: "handover done" })), "handover done");
  assert.equal(entryLabel(mk({ type: "handover", content: {}, verbatim: "" })), "Handover");
  const odd = { ...mk({ verbatim: "" }), type: "mystery" } as unknown as ClinicalEntry;
  assert.equal(entryLabel(odd), "Entry");
  assert.equal(entryLabel({ ...odd, verbatim: "words" }), "words");
});

// isConfirmPhrase --------------------------------------------------------------------------

test("isConfirmPhrase: potrjeno and confirmed, ignoring case, spaces and punctuation", () => {
  assert.equal(isConfirmPhrase("Potrjeno."), true);
  assert.equal(isConfirmPhrase(" confirmed "), true);
  assert.equal(isConfirmPhrase("POTRJENO!"), true);
  assert.equal(isConfirmPhrase("Confirmed, "), true);
  assert.equal(isConfirmPhrase("  po trjeno "), true);
});

test("isConfirmPhrase: anything else is false, including a longer line and non-text", () => {
  assert.equal(isConfirmPhrase("potrjeno morfin"), false);
  assert.equal(isConfirmPhrase("morfin potrjeno"), false);
  assert.equal(isConfirmPhrase("confirm"), false);
  assert.equal(isConfirmPhrase(""), false);
  assert.equal(isConfirmPhrase("   "), false);
  assert.equal(isConfirmPhrase("..."), false);
  assert.equal(isConfirmPhrase(undefined as unknown as string), false);
  assert.equal(isConfirmPhrase(null as unknown as string), false);
});

// storageKey -------------------------------------------------------------------------------

test("storageKey: a different trip or world gives a different key (Review Focus 4)", () => {
  const keys = [storageKey("sim", "TR-001"), storageKey("sim", "TR-002"), storageKey("live", "TR-001")];
  assert.equal(new Set(keys).size, 3);
  assert.equal(storageKey("sim", "TR-001"), storageKey("sim", "TR-001"), "stable for the same trip");
});

test("storageKey: parts that contain the separator cannot collide", () => {
  assert.notEqual(storageKey("a:b", "c"), storageKey("a", "b:c"));
  assert.notEqual(storageKey("sim", ""), storageKey("sim", "TR-001"));
});

// parseLog ---------------------------------------------------------------------------------

test("parseLog: missing, broken or wrong-shaped storage gives an empty log, never a throw (Review Focus 1)", () => {
  assert.deepEqual(parseLog(null), []);
  assert.deepEqual(parseLog(""), []);
  assert.deepEqual(parseLog("{"), []);
  assert.deepEqual(parseLog('{"a":1}'), []);
  assert.deepEqual(parseLog("null"), []);
  assert.deepEqual(parseLog("42"), []);
  assert.deepEqual(parseLog('"text"'), []);
  assert.deepEqual(parseLog("[1,2,3]"), []);
  assert.deepEqual(parseLog("[null,[],{}]"), []);
  assert.deepEqual(parseLog(undefined as unknown as string), []);
});

test("parseLog: a JSON round trip of a log returns it equal (Review Focus 1)", () => {
  const heard = mk({ source: "crew_voice", verbatim: "bolnik je bled", t: at(10) });
  let log: ClinicalEntry[] = appendEntry([], heard);
  log = appendEntry(log, mk({ type: "vitals", content: { sbp: 120, dbp: 80, spo2: 920, hr: 96 }, t: at(20), observed_t: at(-30) }));
  log = appendEntry(log, mk({ type: "drug_administered", content: { drug: "Morphine", dose: 5, unit: "mg", route: "i.v." }, t: at(30) }));
  log = appendEntry(log, mk({ type: "event", content: { key: "rosc", label: "ROSC" }, t: at(40) }));
  log = confirmEntry(log, heard.client_entry_id, { id: "c1", recordedAt: at(500) });
  log = discardEntry(log, log[1].client_entry_id, { id: "d1", recordedAt: at(501) });
  assert.deepEqual(parseLog(JSON.stringify(log)), log);
});

test("parseLog: an empty stored array is an empty log", () => {
  assert.deepEqual(parseLog("[]"), []);
});

test("parseLog: keeps the good entries and drops the unusable ones around them", () => {
  const good1 = mk({ verbatim: "one" });
  const good2 = mk({ verbatim: "two" });
  const noId = { ...mk(), client_entry_id: undefined };
  const badType = { ...mk(), type: "mystery" };
  const badState = { ...mk(), state: "maybe" };
  const badSync = { ...mk(), sync: "later" };
  const badSource = { ...mk(), source: "robot" };
  const badContent = { ...mk(), content: "nope" };
  const arrayContent = { ...mk(), content: [1] };
  const nullContent = { ...mk(), content: null };
  const badTime = { ...mk(), t: 12 };
  const badSupersedes = { ...mk(), supersedes: 5 };
  const badNeeds = { ...mk(), needs_check: "yes" };
  const json = JSON.stringify([good1, noId, badType, badState, badSync, badSource, badContent, arrayContent, nullContent, badTime, badSupersedes, badNeeds, good2]);
  assert.deepEqual(parseLog(json), [good1, good2]);
});

test("parseLog: a repeated client_entry_id keeps the first one only", () => {
  const a = mk({ verbatim: "first" }, { id: "same" });
  const b = mk({ verbatim: "second" }, { id: "same" });
  assert.deepEqual(parseLog(JSON.stringify([a, b])), [a]);
});

test("parseLog: a content value that did not survive JSON is dropped and the entry is marked needs_check", () => {
  const e = mk({ type: "vitals", content: { sbp: 120, hr: Number.NaN } });
  const back = parseLog(JSON.stringify([e]));
  assert.equal(back.length, 1);
  assert.deepEqual(back[0].content, { sbp: 120 });
  assert.equal(back[0].needs_check, true);
});

test("parseLog: a restored log keeps working with the log functions", () => {
  const heard = mk({ source: "crew_voice", verbatim: "x" });
  const restored = parseLog(JSON.stringify([heard]));
  const out = confirmEntry(restored, heard.client_entry_id, { id: "c1", recordedAt: at(5) });
  assert.equal(visibleEntries(out)[0].state, "confirmed");
});

// syncPending ------------------------------------------------------------------------------

function threePending(): ClinicalEntry[] {
  return [mk({ verbatim: "one" }), mk({ verbatim: "two" }), mk({ verbatim: "three" })];
}

test("syncPending: posts every pending entry, oldest first, and marks them sent", async () => {
  const log = threePending();
  const calls: string[] = [];
  const out = await syncPending(log, async (e) => {
    calls.push(e.client_entry_id);
    return "sent";
  });
  assert.deepEqual(calls, log.map((e) => e.client_entry_id));
  assert.deepEqual(out.map((e) => e.sync), ["sent", "sent", "sent"]);
  assert.deepEqual(out.map((e) => e.client_entry_id), log.map((e) => e.client_entry_id));
  assert.deepEqual(log.map((e) => e.sync), ["pending", "pending", "pending"], "input is untouched");
});

test("syncPending: a pending result stops the queue, the rest stay pending and post is not called for them (Review Focus 2)", async () => {
  const log = threePending();
  const calls: string[] = [];
  const out = await syncPending(log, async (e) => {
    calls.push(e.verbatim);
    return e.verbatim === "two" ? "pending" : "sent";
  });
  assert.deepEqual(calls, ["one", "two"], "post is never called for the third");
  assert.deepEqual(out.map((e) => e.sync), ["sent", "pending", "pending"]);
});

test("syncPending: a post that throws counts as offline, stops the queue and loses nothing (Review Focus 2)", async () => {
  const log = threePending();
  const calls: string[] = [];
  const out = await syncPending(log, async (e) => {
    calls.push(e.verbatim);
    if (e.verbatim === "one") throw new Error("offline");
    return "sent";
  });
  assert.deepEqual(calls, ["one"]);
  assert.deepEqual(out.map((e) => e.sync), ["pending", "pending", "pending"]);
  assert.equal(out.length, 3);
});

test("syncPending: a rejected entry is marked rejected and the queue continues (Review Focus 2)", async () => {
  const log = threePending();
  const calls: string[] = [];
  const out = await syncPending(log, async (e) => {
    calls.push(e.verbatim);
    return e.verbatim === "two" ? "rejected" : "sent";
  });
  assert.deepEqual(calls, ["one", "two", "three"]);
  assert.deepEqual(out.map((e) => e.sync), ["sent", "rejected", "sent"]);
});

test("syncPending: sent and rejected entries are not posted again, so a rejected one is not retried forever", async () => {
  const log = threePending();
  const first = await syncPending(log, async (e) => (e.verbatim === "two" ? "rejected" : "pending"));
  assert.deepEqual(first.map((e) => e.sync), ["pending", "pending", "pending"]);
  const mixed = threePending().map((e, i): ClinicalEntry => ({ ...e, sync: (["sent", "rejected", "pending"] as SyncState[])[i] }));
  const calls: string[] = [];
  const out = await syncPending(mixed, async (e) => {
    calls.push(e.verbatim);
    return "sent";
  });
  assert.deepEqual(calls, ["three"]);
  assert.deepEqual(out.map((e) => e.sync), ["sent", "rejected", "sent"]);
});

test("syncPending: a result that is not a known state is treated as pending and stops the queue", async () => {
  const log = threePending();
  const calls: string[] = [];
  const out = await syncPending(log, async (e) => {
    calls.push(e.verbatim);
    return undefined as unknown as SyncState;
  });
  assert.deepEqual(calls, ["one"]);
  assert.deepEqual(out.map((e) => e.sync), ["pending", "pending", "pending"]);
});

test("syncPending: an empty log, or one with nothing pending, makes no calls", async () => {
  let calls = 0;
  const post = async (): Promise<SyncState> => {
    calls += 1;
    return "sent";
  };
  assert.deepEqual(await syncPending([], post), []);
  const done = threePending().map((e): ClinicalEntry => ({ ...e, sync: "sent" }));
  assert.deepEqual((await syncPending(done, post)).map((e) => e.sync), ["sent", "sent", "sent"]);
  assert.equal(calls, 0);
});

test("syncPending: only the sync mark changes, every other field is kept", async () => {
  const [a] = threePending();
  const [out] = await syncPending([a], async () => "sent");
  assert.deepEqual({ ...out, sync: "pending" }, a);
});

// --- timers: elapsed minutes only, never advice ------------------------------------------------

const ev = (key: string, t: string, over: Partial<Input> = {}) => mk({ type: "event", content: { key, label: key }, t, ...over });
const drugAt = (t: string) => mk({ type: "drug_administered", content: { drug: "Morphine", dose: 5, unit: "mg", route: "i.v." }, t });

test("timers: minutes since the last drug", () => {
  const r = timers([drugAt(at(-600)), drugAt(at(-240))], at(0));
  assert.equal(r.lastDrugMin, 4);
});

test("timers: CPR running counts from CPR started", () => {
  assert.equal(timers([ev("cpr_started", at(-720))], at(0)).cprMin, 12);
});

test("timers: a later ROSC stops the CPR timer, an earlier one does not", () => {
  assert.equal(timers([ev("cpr_started", at(-720)), ev("rosc", at(-60))], at(0)).cprMin, null);
  assert.equal(timers([ev("rosc", at(-900)), ev("cpr_started", at(-300))], at(0)).cprMin, 5);
});

test("timers: stroke onset counts from when it started (observed_t), not when it was logged", () => {
  const e = ev("stroke_onset", at(-60), { observed_t: at(-960) });
  assert.equal(timers([e], at(0)).strokeOnsetMin, 16);
});

test("timers: nothing logged gives all null", () => {
  assert.deepEqual(timers([], at(0)), { lastDrugMin: null, cprMin: null, strokeOnsetMin: null });
});

test("timers: a discarded entry does not count, and an unreadable time gives null, never NaN", () => {
  const d = drugAt(at(-120));
  const log = discardEntry([d], d.client_entry_id, { id: "x", recordedAt: at(1) });
  assert.equal(timers(log, at(0)).lastDrugMin, null);
  assert.equal(timers([drugAt(at(-120))], "garbage").lastDrugMin, null);
});

// --- handover: what the crew reads out at the hospital, oldest first -----------------------------

/** The `HH:MM` the handover shows for an ISO time (the crew's own clock). */
const hm = (iso: string): string => {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

test("handoverLines: oldest first, one 'HH:MM label' per entry", () => {
  const late = mk({ type: "note", t: at(600), verbatim: "pain easing" });
  const early = mk({ type: "drug_administered", t: at(60), content: { drug: "Morphine", dose: 5, unit: "mg", route: "i.v." } });
  assert.deepEqual(handoverLines([late, early]), [`${hm(at(60))} Morphine 5 mg i.v.`, `${hm(at(600))} pain easing`]);
});

test("handoverLines: an entry that needs a check ends with ' (check)'", () => {
  const e = mk({ type: "vitals", t: at(0), content: { hr: 920 } });
  assert.equal(e.needs_check, true);
  assert.deepEqual(handoverLines([e]), [`${hm(at(0))} ${entryLabel(e)} (check)`]);
  assert.ok(entryLabel(e).includes("920"));
});

test("handoverLines: heard entries are included, discarded and superseded ones and the handover marker are not", () => {
  const heard = mk({ source: "crew_voice", type: "note", t: at(60), verbatim: "heard words" });
  const gone = mk({ type: "note", t: at(120), verbatim: "gone" });
  const old = mk({ type: "note", t: at(180), verbatim: "old text" });
  const marker = mk({ type: "handover", t: at(900), verbatim: "" });
  let log = [heard, gone, old, marker];
  log = discardEntry(log, gone.client_entry_id, { id: "d1", recordedAt: at(121) });
  log = confirmEntry(log, old.client_entry_id, { id: "c1", recordedAt: at(181) });
  const lines = handoverLines(log);
  assert.equal(lines.length, 2);
  assert.ok(lines[0].endsWith("heard words"), lines[0]);
  assert.ok(lines[1].endsWith("old text"), lines[1]);
});

test("handoverLines: an empty log, or an unreadable time, never gives NaN", () => {
  assert.deepEqual(handoverLines([]), []);
  const e = mk({ type: "note", t: "garbage", verbatim: "no time" });
  assert.deepEqual(handoverLines([e]), ["--:-- no time"]);
});
