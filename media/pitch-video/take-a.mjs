/**
 * Take A (scenes 1-4 and 6): the map, the 112 call typed in sync with the caller's voice, Claude's
 * triage and the dispatch, the crew tablet, a delay injected on the unit, the re-plan and Claude's
 * check, the ER board. One dashboard page (1280x720, device scale 2), navigated between views.
 *
 *   PLANB_KEY=... node media/pitch-video/take-a.mjs [takeName]
 */
import fs from "node:fs";
import path from "node:path";
import { Rec, api, state, until, sleep, log, BASE } from "./rec.mjs";

const TAKE = process.argv[2] ?? "a1";
const WORDS = "Halo, reševalci? Mož se je zgrudil na dvorišču, ne diha! Nihče ne dela oživljanja. Naslov je Šmarska cesta 3, Škofljica.";
const WHERE = "Šmarska cesta 3, Škofljica";
const VOICE_S = Number(process.env.VOICE_S ?? 10.9); // length of the caller's sentence (audio/caller_phone.wav)
const RING_S = 2.6; // ring before she speaks

const r = new Rec(TAKE);
const rects = {};
const rectOf = async (loc) => (loc ? await loc.boundingBox().catch(() => null) : null);
const info = { take: TAKE };

try {
  // --- set-up (not recorded) ---
  await api("POST", "/sim/admin/reset", { scheduled_day: false });
  await api("POST", "/sim/admin/calls", { enabled: false });
  await api("POST", "/sim/admin/ai-mode", { mode: "autonomous" });
  await api("POST", "/sim/admin/ai-triage", { enabled: true });
  const st0 = await state();
  info.preTrips = st0.trips.length;
  log(`before the take: ${st0.trips.length} trips, call stream ${JSON.stringify(st0.calls_enabled ?? st0.call_stream ?? "?")}`);
  if (st0.trips.length) throw new Error(`world not clean: ${st0.trips.length} trips after reset`);
  await r.launch({ headed: process.env.HEADED === "1" });
  const d = await r.page("dash");
  const pg = d.page;
  await pg.goto(`${BASE}/sim`, { waitUntil: "domcontentloaded" });
  await pg.locator(".leaflet-tile-loaded").first().waitFor({ timeout: 30000 }).catch(() => undefined);
  await r.click(d, [(p) => p.getByRole("tab", { name: /AI dispatcher/i })], { what: "AI dispatcher tab", ms: 1 });
  await sleep(2500);
  await r.hideCursor(d);

  // --- scene 1: the live map ---
  await r.startRec(d);
  await sleep(400);
  r.mark("start");
  await sleep(5500);

  // --- scene 2: the 112 call ---
  r.mark("newcall");
  await r.click(d, [(p) => p.getByRole("button", { name: /New 112 call/i })], { what: "New 112 call" });
  await sleep(500);
  const words = pg.locator("#call-words");
  await r.point(d, words);
  await words.click();
  r.mark("ring"); // the ring starts here in the edit
  await sleep(RING_S * 1000);
  r.mark("voice"); // the caller's voice starts here
  await sleep(450);
  // type in sync with her voice: one sentence at a time, at the sentence's share of the voice length
  const parts = WORDS.match(/[^?!.]+[?!.]\s*/g);
  const per = (VOICE_S - 0.9) / WORDS.length;
  for (const part of parts) {
    const t0 = Date.now();
    await words.pressSequentially(part, { delay: Math.round(per * 1000 * 0.82) });
    const left = part.length * per * 1000 - (Date.now() - t0);
    if (left > 0) await sleep(left);
  }
  r.mark("typed");
  rects.form = await rectOf(pg.locator(".call-form"));
  const addr = pg.locator("#call-address");
  await r.point(d, addr, { ms: 450 });
  await addr.click();
  await addr.pressSequentially(WHERE, { delay: 38 });
  await pg.keyboard.press("Escape").catch(() => undefined); // close the datalist suggestions
  await sleep(500);
  r.mark("submit");
  await r.click(d, [(p) => p.getByRole("button", { name: /Classify and dispatch/i })], { what: "Classify and dispatch", ms: 450 });
  const sentAt = Date.now();
  await pg.locator(".call-result").first().waitFor({ timeout: 60000 });
  r.mark("classified");
  info.triageSeconds = (Date.now() - sentAt) / 1000;
  rects.result = await rectOf(pg.locator(".call-form"));
  await r.hideCursor(d);
  // the blue "New call" box
  const box = pg.locator("section.replan.new").first();
  await box.waitFor({ timeout: 30000 });
  r.mark("box");
  await sleep(400);
  rects.box = await rectOf(box);
  const final = /v-(agreed|changed|refused|unavailable|override)/;
  const claudeAt = Date.now();
  await pg.waitForFunction((re) => {
    const el = document.querySelector("section.replan.new .decision-claude");
    return el && new RegExp(re).test(el.className);
  }, final.source, { timeout: 90000 });
  r.mark("claude1");
  info.claude1Seconds = (Date.now() - claudeAt) / 1000;
  rects.box2 = await rectOf(box);
  info.box1 = (await box.innerText().catch(() => "")).replace(/\s+/g, " ");
  log("box1:", info.box1);
  await sleep(3500);

  // which unit(s) went
  const st = await state();
  const trip = [...st.trips].reverse().find((t) => t.vehicle_id && t.status !== "completed");
  const unit = trip?.vehicle_id ?? "A1";
  info.unit = unit;
  info.trip = trip?.id;
  log(`dispatched: ${unit} on ${trip?.id}`);

  // --- scene 3: the crew tablet ---
  r.mark("tabletNav");
  await pg.goto(`${BASE}/vehicle/${unit}?world=sim`, { waitUntil: "domcontentloaded" });
  await pg.locator(".leaflet-tile-loaded").first().waitFor({ timeout: 20000 }).catch(() => undefined);
  await r.click(d, [(p) => p.getByRole("button", { name: /Heading up|Smer vožnje/i }), (p) => p.locator("button[title*='Heading up']")], { what: "heading up", optional: true, timeout: 4000 });
  await sleep(800);
  r.mark("tablet");
  await r.hideCursor(d);
  await sleep(10500);
  r.mark("tabletEnd");

  // --- scene 4: something breaks ---
  await pg.goto(`${BASE}/sim`, { waitUntil: "domcontentloaded" });
  await pg.locator(".leaflet-tile-loaded").first().waitFor({ timeout: 30000 }).catch(() => undefined);
  await r.click(d, [(p) => p.getByRole("tab", { name: /AI dispatcher/i })], { what: "AI dispatcher tab", ms: 1, optional: true });
  // wait until the unit has left its base
  const minWait = 24000 - (Date.now() - sentAt); // past the turnout
  if (minWait > 0) await sleep(minWait);
  await until((s) => s.vehicles.find((x) => x.id === unit && x.status === "to_pickup"), { timeout: 30000, what: `${unit} on the road` }).catch((e) => log(e.message));
  await sleep(800);
  r.mark("failStart");
  await r.click(d, [(p) => p.getByRole("button", { name: /Random failure: choose/i })], { what: "Random failure caret" });
  await sleep(500);
  await r.click(d, [(p) => p.getByRole("menuitem", { name: /Choose unit/i })], { what: "Choose unit" });
  await sleep(700);
  rects.target = await rectOf(pg.locator(".target-pop"));
  await r.click(d, [(p) => p.locator(".target-units button[role=radio]", { hasText: new RegExp(`^\\s*${unit}\\b`) }), (p) => p.locator(".target-units button[role=radio]").first()], { what: "unit" });
  await sleep(500);
  await r.click(d, [(p) => p.locator(".target-kinds button", { hasText: /Delay/ })], { what: "Delay" });
  await sleep(600);
  r.mark("inject");
  await r.click(d, [(p) => p.locator(".target-actions button.primary")], { what: "Inject" });
  const dbox = pg.locator("section.replan:not(.new)").first();
  await dbox.waitFor({ timeout: 30000 });
  r.mark("dbox");
  await r.hideCursor(d);
  await sleep(300);
  rects.dbox = await rectOf(dbox);
  const dAt = Date.now();
  await pg.waitForFunction((re) => {
    const el = document.querySelector("section.replan:not(.new) .decision-claude");
    return el && new RegExp(re).test(el.className);
  }, final.source, { timeout: 90000 }).catch((e) => log("disruption verdict:", e.message));
  r.mark("claude2");
  info.claude2Seconds = (Date.now() - dAt) / 1000;
  rects.dbox2 = await rectOf(dbox);
  info.box2 = (await dbox.innerText().catch(() => "")).replace(/\s+/g, " ");
  log("box2:", info.box2);
  rects.map = await rectOf(pg.locator(".map-wrap .leaflet-container").first());
  await sleep(6000);
  r.mark("mapEnd");

  // --- scene 6: the ER board ---
  r.mark("erNav");
  await pg.goto(`${BASE}/er/?world=sim`, { waitUntil: "domcontentloaded" });
  await sleep(3500);
  r.mark("er");
  await sleep(4500);
  const tile = await r.find(d, [(p) => p.locator("[class*=case]").filter({ hasText: unit }), (p) => p.locator("button[class*=case], [class*=tile]")], { timeout: 3000 });
  if (tile) {
    await r.click(d, [() => tile], { what: "ER tile", optional: true });
    r.mark("erOpen");
    await sleep(6000);
  }
  r.mark("end");
  await sleep(500);
  info.tripsEnd = (await state()).trips.map((t) => `${t.id}:${t.kind ?? ""}:${t.vehicle_id ?? "-"}:${(t.call?.text ?? t.notes ?? "").slice(0, 40)}`);
  info.er = await pg.locator("body").innerText().then((t) => t.replace(/\s+/g, " ").slice(0, 400)).catch(() => "");
} catch (e) {
  log("FAILED:", e.stack ?? e);
  try {
    await r.pages[0]?.page.screenshot({ path: path.join(r.dir, "failure.png") });
  } catch {}
  process.exitCode = 1;
} finally {
  r.marks.rects = rects;
  r.marks.info = info;
  await r.stopAll();
  log(JSON.stringify(info, null, 1));
}
