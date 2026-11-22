import { test } from "node:test";
import assert from "node:assert/strict";
import { canSaveDrug, observedAt, padKey, parsePadNumber, vitalsContent, VITAL_KEYS } from "../../src/crew/padLogic.ts";

// --- padKey: the number pad's typing rules ---------------------------------------------------

test("padKey: digits are appended", () => {
  assert.equal(padKey("", "1", false), "1");
  assert.equal(padKey("12", "3", false), "123");
});

test("padKey: a lone zero is replaced by the next digit, not stacked", () => {
  assert.equal(padKey("0", "5", false), "5");
  assert.equal(padKey("0", "0", false), "0");
});

test("padKey: the decimal point only works when allowed and only once", () => {
  assert.equal(padKey("", ".", true), "0.");
  assert.equal(padKey("7", ".", true), "7.");
  assert.equal(padKey("7.5", ".", true), "7.5");
  assert.equal(padKey("7", ".", false), "7");
  assert.equal(padKey("", ".", false), "");
});

test("padKey: back removes the last character and is safe on an empty value", () => {
  assert.equal(padKey("123", "back", false), "12");
  assert.equal(padKey("0.", "back", true), "0");
  assert.equal(padKey("", "back", false), "");
});

test("padKey: a value stops growing at 6 characters and an unknown key changes nothing", () => {
  assert.equal(padKey("123456", "7", false), "123456");
  assert.equal(padKey("12", "x", false), "12");
});

// --- parsePadNumber: what the typed text means -----------------------------------------------

test("parsePadNumber: empty or lone point is not a number", () => {
  assert.equal(parsePadNumber(""), null);
  assert.equal(parsePadNumber("."), null);
});

test("parsePadNumber: whole and decimal values, with or without a trailing point", () => {
  assert.equal(parsePadNumber("92"), 92);
  assert.equal(parsePadNumber("36.6"), 36.6);
  assert.equal(parsePadNumber("12."), 12);
  assert.equal(parsePadNumber("0."), 0);
});

test("parsePadNumber: anything the pad cannot type is rejected", () => {
  assert.equal(parsePadNumber("-5"), null);
  assert.equal(parsePadNumber("1e5"), null);
  assert.equal(parsePadNumber("abc"), null);
});

// --- vitalsContent: the entry the vitals pad saves -------------------------------------------

test("vitalsContent: only the fields that were filled become numbers", () => {
  assert.deepEqual(vitalsContent({ sbp: "120", dbp: "80", spo2: "" }), { sbp: 120, dbp: 80 });
});

test("vitalsContent: an implausible value is kept as typed, never corrected", () => {
  assert.deepEqual(vitalsContent({ spo2: "920" }), { spo2: 920 });
});

test("vitalsContent: nothing filled gives an empty object (the pad cannot save it)", () => {
  assert.deepEqual(vitalsContent({}), {});
  assert.deepEqual(vitalsContent({ hr: "", rr: "." }), {});
});

test("vitalsContent: keys come out in the fixed vitals order", () => {
  const c = vitalsContent({ gcs: "14", sbp: "110", hr: "88" });
  assert.deepEqual(Object.keys(c), VITAL_KEYS.filter((k) => k in c));
  assert.deepEqual(Object.keys(c), ["sbp", "hr", "gcs"]);
});

// --- canSaveDrug: Save stays off until all four are set -------------------------------------

const drug = { drug: "Morphine", dose: "5", unit: "mg", route: "i.v." };

test("canSaveDrug: all four set is saveable", () => {
  assert.equal(canSaveDrug(drug), true);
});

test("canSaveDrug: any missing part is not", () => {
  assert.equal(canSaveDrug({ ...drug, drug: "" }), false);
  assert.equal(canSaveDrug({ ...drug, drug: "   " }), false);
  assert.equal(canSaveDrug({ ...drug, dose: "" }), false);
  assert.equal(canSaveDrug({ ...drug, dose: "." }), false);
  assert.equal(canSaveDrug({ ...drug, unit: "" }), false);
  assert.equal(canSaveDrug({ ...drug, route: "" }), false);
});

test("canSaveDrug: a zero dose can be saved, so it is kept and marked check-this, not blocked or fixed", () => {
  assert.equal(canSaveDrug({ ...drug, dose: "0" }), true);
});

// --- observedAt: "it started N minutes ago" --------------------------------------------------

test("observedAt: subtracts the minutes from the world time", () => {
  assert.equal(observedAt("2026-11-22T10:30:00Z", 15), "2026-11-22T10:15:00.000Z");
  assert.equal(observedAt("2026-11-22T10:30:00Z", 0), "2026-11-22T10:30:00.000Z");
  assert.equal(observedAt("2026-11-22T10:30:00+00:00", 60), "2026-11-22T09:30:00.000Z");
});

test("observedAt: an unreadable world time or minutes gives null, never an Invalid Date", () => {
  assert.equal(observedAt("garbage", 15), null);
  assert.equal(observedAt("", 15), null);
  assert.equal(observedAt("2026-11-22T10:30:00Z", Number.NaN), null);
  assert.equal(observedAt("2026-11-22T10:30:00Z", -5), null);
});
