import { test } from "node:test";
import assert from "node:assert/strict";
import { crewStage, erEta, minutesUntil } from "../../src/crew/crewLogic.ts";

const patientTrip = { kind: "patient" } as const;
const equipmentTrip = { kind: "equipment" } as const;

test("crewStage: to_pickup with a patient trip is to_patient", () => {
  assert.equal(crewStage({ status: "to_pickup", type: "ambulance" }, patientTrip), "to_patient");
});

test("crewStage: loading and with_patient are with_patient", () => {
  assert.equal(crewStage({ status: "loading", type: "ambulance" }, patientTrip), "with_patient");
  assert.equal(crewStage({ status: "with_patient", type: "ambulance" }, patientTrip), "with_patient");
});

test("crewStage: no trip is no_patient", () => {
  assert.equal(crewStage({ status: "to_pickup", type: "ambulance" }, undefined), "no_patient");
  assert.equal(crewStage({ status: "with_patient", type: "ambulance" }, undefined), "no_patient");
});

test("crewStage: an equipment trip is no_patient even with status with_patient", () => {
  assert.equal(crewStage({ status: "with_patient", type: "ambulance" }, equipmentTrip), "no_patient");
  assert.equal(crewStage({ status: "to_pickup", type: "ambulance" }, equipmentTrip), "no_patient");
});

test("crewStage: idle is no_patient", () => {
  assert.equal(crewStage({ status: "idle", type: "ambulance" }, patientTrip), "no_patient");
  assert.equal(crewStage({ status: "idle", type: "ambulance" }, undefined), "no_patient");
});

test("crewStage: a doctor car with a patient trip follows the same stages", () => {
  assert.equal(crewStage({ status: "loading", type: "doctor" }, patientTrip), "with_patient");
  assert.equal(crewStage({ status: "to_pickup", type: "doctor" }, patientTrip), "to_patient");
});

test("minutesUntil: whole minutes, rounded up", () => {
  assert.equal(minutesUntil("2026-11-21T23:40:00Z", "2026-11-21T23:28:40Z"), 12);
  assert.equal(minutesUntil("2026-11-21T23:40:00Z", "2026-11-21T23:28:00Z"), 12);
  assert.equal(minutesUntil("2026-11-21T23:40:00Z", "2026-11-21T23:39:59Z"), 1);
});

test("minutesUntil: a past or equal time is 0, never negative", () => {
  assert.equal(minutesUntil("2026-11-21T23:10:00Z", "2026-11-21T23:28:40Z"), 0);
  assert.equal(minutesUntil("2026-11-21T23:28:40Z", "2026-11-21T23:28:40Z"), 0);
});

test("minutesUntil: missing or invalid times give null", () => {
  assert.equal(minutesUntil(null, "2026-11-21T23:28:40Z"), null);
  assert.equal(minutesUntil(undefined, "2026-11-21T23:28:40Z"), null);
  assert.equal(minutesUntil("garbage", "2026-11-21T23:28:40Z"), null);
  assert.equal(minutesUntil("2026-11-21T23:40:00Z", "garbage"), null);
  assert.equal(minutesUntil("2026-11-21T23:40:00Z", ""), null);
  assert.equal(minutesUntil("", "2026-11-21T23:28:40Z"), null);
});

test("erEta: 7.4 minutes of delay is late, rounded to 7", () => {
  const e = erEta({ eta_dropoff: "2026-11-21T23:40:00Z", delay_min: 7.4 }, "2026-11-21T23:28:40Z");
  assert.deepEqual(e, { minutes: 12, arriveAt: "2026-11-21T23:40:00Z", late: true, lateMin: 7 });
});

test("erEta: 2 minutes of delay is not late", () => {
  const e = erEta({ eta_dropoff: "2026-11-21T23:40:00Z", delay_min: 2 }, "2026-11-21T23:28:40Z");
  assert.equal(e.late, false);
  assert.equal(e.minutes, 12);
});

test("erEta: the late threshold is 5 minutes", () => {
  const at = (delay_min: number) => erEta({ eta_dropoff: "2026-11-21T23:40:00Z", delay_min }, "2026-11-21T23:28:40Z");
  assert.equal(at(4.9).late, false);
  assert.equal(at(5).late, true);
  assert.equal(at(5).lateMin, 5);
});

test("erEta: a missing delay is not late and never NaN", () => {
  const e = erEta({ eta_dropoff: "2026-11-21T23:40:00Z", delay_min: null }, "2026-11-21T23:28:40Z");
  assert.equal(e.late, false);
  assert.equal(e.lateMin, 0);
});

test("erEta: no drop-off ETA gives null minutes and null arriveAt", () => {
  const e = erEta({ eta_dropoff: null, delay_min: 7.4 }, "2026-11-21T23:28:40Z");
  assert.equal(e.minutes, null);
  assert.equal(e.arriveAt, null);
});

test("erEta: an invalid drop-off ETA gives null minutes and null arriveAt", () => {
  const e = erEta({ eta_dropoff: "garbage", delay_min: null }, "2026-11-21T23:28:40Z");
  assert.equal(e.minutes, null);
  assert.equal(e.arriveAt, null);
});

test("erEta: an invalid now gives null minutes but keeps a valid arriveAt", () => {
  const e = erEta({ eta_dropoff: "2026-11-21T23:40:00Z", delay_min: null }, "garbage");
  assert.equal(e.minutes, null);
  assert.equal(e.arriveAt, "2026-11-21T23:40:00Z");
});
