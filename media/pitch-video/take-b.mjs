/**
 * Take B (scene 5): "Prepare crew demo" (T1 carries blood products), the crew reports the breakdown
 * from the phone, the dispatcher runs the situation review (A), Claude's options, approve (Y).
 * Two pages recorded at the same time: the dashboard (1280x720) and the crew phone (390x844).
 *
 *   PLANB_KEY=... node media/pitch-video/take-b.mjs [takeName]
 */
import path from "node:path";
import { Rec, api, state, until, sleep, log, BASE } from "./rec.mjs";

const TAKE = process.argv[2] ?? "b1";
const UNIT = "T1";
const r = new Rec(TAKE);
const rects = {};
const info = { take: TAKE };
const rectOf = async (loc) => (loc ? await loc.boundingBox().catch(() => null) : null);

try {
  await api("POST", "/sim/admin/reset", { scheduled_day: false });
  await api("POST", "/sim/admin/calls", { enabled: false });
  await api("POST", "/sim/admin/ai-mode", { mode: "autonomous" });
  await api("POST", "/sim/admin/ai-triage", { enabled: true });
  await api("POST", "/sim/admin/scenario/equipment_en_route", {});
  await api("POST", "/sim/admin/calls", { enabled: false }).catch(() => undefined);
  await until((st) => {
    const v = st.vehicles.find((x) => x.id === UNIT);
    const t = v && st.trips.find((x) => x.id === v.current_trip_id);
    return t?.kind === "equipment" && t.status === "onboard" && v.status === "with_patient";
  }, { timeout: 240000, what: `${UNIT} driving with the equipment` });
  const st0 = await state();
  info.preTrips = st0.trips.map((t) => `${t.id}:${t.kind}:${t.vehicle_id ?? "-"}`);
  const runsBefore = st0.agent?.runs?.length ?? 0;

  await r.launch({ headed: process.env.HEADED === "1" });
  const d = await r.page("dash");
  const ph = await r.page("phone", { width: 390, height: 844, dpr: 2, mobile: true });
  await d.page.goto(`${BASE}/sim`, { waitUntil: "domcontentloaded" });
  await ph.page.goto(`${BASE}/crew/${UNIT}?world=sim`, { waitUntil: "domcontentloaded" });
  await d.page.locator(".leaflet-tile-loaded").first().waitFor({ timeout: 30000 }).catch(() => undefined);
  await ph.page.locator(".crew-quick").first().waitFor({ timeout: 30000 });
  await r.click(d, [(p) => p.getByRole("tab", { name: /AI dispatcher/i })], { what: "AI dispatcher tab", ms: 1 });
  await r.click(d, [(p) => p.locator(".vchip", { hasText: new RegExp(`^\\s*${UNIT}\\b`) })], { what: `${UNIT} chip`, ms: 1, optional: true });
  await sleep(2000);
  await r.hideCursor(d);

  await r.startRec(d);
  await r.startRec(ph);
  await sleep(400);
  r.mark("start");
  await sleep(2500);
  r.mark("radio"); // crew voice starts here in the edit (beep + ~4.6 s)
  await sleep(2600);
  await r.click(ph, [(p) => p.locator(".crew-quick button", { hasText: "Vozilo je obstalo." }), (p) => p.getByRole("button", { name: /Vozilo je obstalo/i })], { what: "quick button", ms: 500 });
  r.mark("sent");
  await ph.page.locator(".crew-response").first().waitFor({ timeout: 60000 }).catch((e) => log("crew response:", e.message));
  r.mark("crewResp");
  info.crewResp = (await ph.page.locator(".crew-response").first().innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 300);
  await r.hideCursor(ph);
  await sleep(4000);
  // the dashboard: what happened (an autonomous re-plan box may already be there)
  r.mark("dashSees");
  info.panelAfterBreakdown = (await d.page.locator(".side, aside, [class*=panel]").first().innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 600);
  await sleep(2500);
  // Situation review: press A
  await r.click(d, [(p) => p.locator(".kpis"), (p) => p.locator(".statusbar")], { what: "focus dashboard", ms: 400, optional: true });
  await sleep(300);
  r.mark("pressA");
  await d.page.keyboard.press("a");
  const aAt = Date.now();
  const run = await until((st) => {
    const x = st.agent?.runs?.[0];
    return st.agent?.runs?.length > runsBefore && ["done", "error"].includes(x?.status) ? x : null;
  }, { timeout: 150000, what: "analysis" });
  r.mark("options");
  info.analysisSeconds = (Date.now() - aAt) / 1000;
  info.runStatus = run.status;
  const rec = run.recommendation;
  info.options = (rec?.options ?? []).map((o) => o.title);
  info.recommended = rec?.recommended_index;
  info.by = run.by ?? run.source ?? rec?.by;
  await sleep(800);
  const opt = await r.find(d, [(p) => p.locator(".option.recommended"), (p) => p.locator(".option").first()], { timeout: 8000 });
  if (opt) {
    await opt.scrollIntoViewIfNeeded().catch(() => undefined);
    rects.option = await rectOf(opt);
    await r.point(d, opt, { ms: 700 });
  }
  rects.panel = await rectOf(d.page.locator(".side-panel, aside").first());
  info.optionText = opt ? (await opt.innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 400) : "";
  await sleep(5500);
  r.mark("pressY");
  await d.page.keyboard.press("y");
  const ap = await until((st) => st.agent.runs.find((x) => x.id === run.id && x.status !== "done"), { timeout: 30000, what: "approval" }).catch((e) => (log(e.message), null));
  r.mark("approved");
  info.approved = ap ? `${ap.status} ${ap.decision?.title ?? ""} | ${(ap.decision?.executed ?? []).join(" | ")}` : "no";
  await r.hideCursor(d);
  await sleep(16000);
  r.mark("end");
  info.tripsEnd = (await state()).trips.map((t) => `${t.id}:${t.kind}:${t.vehicle_id ?? "-"}:${t.status}`);
} catch (e) {
  log("FAILED:", e.stack ?? e);
  for (const p of r.pages) await p.page.screenshot({ path: path.join(r.dir, `failure-${p.name}.png`) }).catch(() => undefined);
  process.exitCode = 1;
} finally {
  r.marks.rects = rects;
  r.marks.info = info;
  if (r.browser) await r.stopAll();
  log(JSON.stringify(info, null, 1));
}
