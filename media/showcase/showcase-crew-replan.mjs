/**
 * Showcase b: "The crew speaks, Bypass re-plans" (~60 s, 1920x1080).
 * Dashboard (left) and the crew's phone view of T1 (right) side by side. Prepare crew demo -> the
 * crew reports a breakdown with equipment on board -> analysis -> options -> approve -> vehicles move.
 *
 *   node media/showcase/showcase-crew-replan.mjs [--base http://localhost:5240] [--api http://localhost:8040]
 *
 * Headless Chromium has no microphone. With the Claude key, the crew's sentence is typed into the
 * phone's message box (the same text speech would produce) and the AI reads it; without the key the
 * crew taps the quick button "Vozilo je obstalo.", which reports the breakdown directly. The captions
 * say which one happened.
 */
import { options, startSession } from "./lib.mjs";
import { UI, frameRoute } from "./ui.mjs";

const NAME = "showcase-crew-replan";
const SENTENCE = "Vozilo je obstalo. Oprema je še v njem.";
const UNIT = "T1";

const STAGE = `<!doctype html><html><head><meta charset="utf-8"><style>/*FONTS*/
*{box-sizing:border-box}
html,body{margin:0;width:1920px;height:1080px;overflow:hidden;background:#06090d;font-family:"Inter Variable",Inter,system-ui,sans-serif;color:#e6ebf1;-webkit-font-smoothing:antialiased}
#dash{position:absolute;left:0;top:0;width:1440px;height:1080px;border:0;background:#0b0f14}
.col{position:absolute;left:1440px;top:0;width:480px;height:1080px;border-left:1px solid #242e3a;background:radial-gradient(520px 520px at 50% 34%,rgba(37,99,235,.13),transparent 70%),#070a0e;display:flex;flex-direction:column;align-items:center}
.label{margin-top:24px;font-size:15px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#8f9cab}
.label b{color:#e6ebf1}
.phone{margin-top:14px;width:424px;height:912px;border-radius:52px;padding:12px;background:#141a22;border:1px solid #2c3846;box-shadow:0 30px 80px rgba(0,0,0,.65),inset 0 0 0 2px #0b0f14}
.phone iframe{width:398px;height:886px;border:0;border-radius:40px;background:#0b0f14;display:block}
.foot{margin-top:14px;font-size:13px;color:#6f7c8b;letter-spacing:.03em}
</style></head><body>
<iframe id="dash" src="{{BASE}}/sim"></iframe>
<div class="col"><div class="label">Crew phone · <b>${UNIT}</b></div><div class="phone"><iframe id="crew" src="{{BASE}}/crew/${UNIT}?world=sim"></iframe></div><div class="foot">Crew view (/crew/${UNIT}), as on the crew's phone</div></div>
</body></html>`;

const opts = options();
const s = await startSession({ name: NAME, opts });
const latestRun = (st) => st.agent?.runs?.[0];
let aiOn = false;

try {
  // --- set-up (not in the video): T1 carries blood products, driving ---
  if (opts.setup) {
    await s.api.reset(false);
    await s.api.calls(false);
    await s.api.autoAnalyse(false);
    await s.api.scenario("equipment_en_route");
    await s.until(
      (st) => {
        const v = st.vehicles.find((x) => x.id === UNIT);
        const t = v && st.trips.find((x) => x.id === v.current_trip_id);
        return t?.kind === "equipment" && t.status === "onboard" && v.status === "with_patient";
      },
      { timeout: 300000, what: `${UNIT} driving with the equipment` },
    );
  }
  const st0 = await s.api.state();
  aiOn = Boolean(st0.agent?.enabled);
  const runsBefore = st0.agent?.runs?.length ?? 0;
  // captions over the map only: the dashboard's side panel (~380 px at this width) and the phone stay visible
  await s.stage(STAGE, { captionArea: [0, 480 + 385] });
  const dash = s.frame("#dash");
  const crew = s.frame("#crew");
  await dash.locator(".leaflet-tile-loaded").first().waitFor({ timeout: 25000 }).catch(() => undefined);
  await crew.locator(".crew-quick").first().waitFor({ timeout: 25000 });
  await s.click(UI.vehicleChip(UNIT), { root: dash, what: `${UNIT} chip`, optional: true, pause: 0 });
  await s.hold(2500);

  s.begin();
  await s.card({
    title: "The crew speaks. Bypass re-plans.",
    text: "A van breaks down with blood products on board. The crew says it in Slovenian; the dispatcher gets a new plan to approve.",
    pill: "Real UI · simulated fleet",
  });
  await s.hold(4200);
  await s.hideCard();
  await s.hold(700);

  await s.steps([
    {
      say: `**${UNIT}** is driving blood products from UKC to the Oncology Institute. The crew has Bypass on a phone.`,
      run: async () => {
        await s.click(UI.vehicleChip(UNIT), { root: dash, what: `${UNIT} chip`, optional: true });
        await s.hold(1200);
        await frameRoute(s, { root: dash, maxLevels: 2 });
        await s.page.mouse.move(1000, 1000);
      },
      hold: 3000,
    },
    {
      say: aiOn
        ? `The van stops. The crew holds the mic and says: »${SENTENCE}«`
        : `The van stops. The crew would hold the mic and say »${SENTENCE}« No microphone in this recording: they tap the quick button.`,
      run: async () => {
        if (aiOn) {
          await s.type(UI.crewInput, SENTENCE, { root: crew, what: "crew message", delay: 45 });
          await s.click(UI.crewSend, { root: crew, what: "Send" });
        } else {
          await s.click(UI.crewQuick("Vozilo je obstalo."), { root: crew, what: "quick button 1" });
        }
        const out = await s.find([(p) => p.locator(".crew-response .applied"), (p) => p.locator(".crew-response")], { root: crew, timeout: 60000 });
        await s.hold(900);
        if (aiOn) {
          const sl = await crew.locator(".crew-response").innerText().catch(() => "");
          s.notes.push(`crew response: ${sl.replace(/\s+/g, " ").slice(0, 200)}`);
          await s.say("**Claude** reads it: T1 broke down, the equipment is still inside. The breakdown is applied at once.");
        } else {
          await s.say("The breakdown reaches dispatch at once. (With the Claude key, the AI reads the spoken sentence; here the quick button reports it directly.)");
        }
        if (out) await s.point(out);
      },
      hold: 5500,
    },
    {
      say: `Dispatch sees it: **${UNIT}** out of service, the blood products still on board, its next job at risk.`,
      run: async () => {
        await s.click(UI.dispatchTab, { root: dash, what: "Dispatch tab", optional: true });
      },
      hold: 4500,
    },
    {
      say: "The dispatcher presses **A** to analyse.",
      run: async () => {
        // focus the dashboard frame (a click on the KPI row, which does nothing), then the hotkey
        await s.click(UI.kpis, { root: dash, what: "dashboard", optional: true, pause: 100 });
        await s.key("a", "Analyse", { focus: dash.locator("body") });
        await s.hold(800);
        await s.say(
          aiOn
            ? "**Claude** checks who can reach the breakdown site and simulates complete plans with the engine."
            : "Claude is not connected in this recording, so the **engine's own plan** is shown: same options, fully simulated.",
        );
        const done = () => s.until((st) => st.agent.runs.length > runsBefore && ["done", "error"].includes(latestRun(st)?.status) && latestRun(st), { timeout: 120000, what: "analysis" });
        const run = aiOn ? await s.timelapse(done, { show: 5 }) : await done();
        s.agentRun = run;
      },
      hold: 3000,
    },
    {
      say: async () => {
        const rec = s.agentRun?.recommendation;
        const opt = rec?.options?.[rec.recommended_index];
        const n = rec?.options?.length ?? 0;
        const count = n === 1 ? "One option" : n > 1 ? `${n} options` : "The plan";
        return `${count}, every number simulated by the engine${n > 1 ? ". Recommended" : ""}: **${opt?.title ?? "the first option"}**.`;
      },
      run: async () => {
        const o = await s.find(UI.recommendedOption, { root: dash, timeout: 8000 });
        if (o) await s.point(o);
        await s.hero();
      },
      hold: 6500,
    },
    {
      say: "The dispatcher stays in control: approve with one key, **Y**.",
      run: async () => {
        await s.key("y", "Approve recommended", { focus: dash.locator("body") });
        const run = await s.until((st) => st.agent.runs.find((r) => r.id === s.agentRun?.id && r.status !== "done"), { timeout: 30000, what: "approval" });
        await s.hold(800);
        const lines = run.decision?.executed ?? [];
        s.notes.push(`approved: ${run.status} ${run.decision?.title ?? ""} | ${lines.join(" | ")}`);
        await s.say(
          run.status === "approved"
            ? `Approved. The vehicles do exactly what the steps say${lines.length ? `: ${lines.slice(0, 2).map((l) => l.replace(/: picks up /, " to pick up ").replace(/\.$/, "")).join("; ")}` : ""}.`
            : `Not approved: ${run.decision?.reason ?? run.error ?? run.status}. Bypass refuses a plan that no longer fits.`,
        );
      },
      hold: 6000,
    },
    {
      say: "Time-lapse: the new plan runs on the map.",
      run: async () => {
        await s.timelapse(() => s.hold(25000), { show: 5 });
      },
      hold: 1500,
    },
  ]);

  await s.say("");
  await s.card({
    title: "When things go wrong, a new plan in seconds.",
    text: "The crew speaks; the AI understands and proposes; the engine computes every number; the dispatcher decides.",
    pill: "Bypass · prototype",
  });
  await s.hold(4500);

  const r = await s.finish({
    poster: { title: "The crew speaks. Bypass re-plans.", subtitle: "A breakdown reported from the crew's phone, a new plan with before/after numbers, approved with one key.", duration: "Showcase · about 60 s" },
  });
  console.log(JSON.stringify({ ...r, notes: s.notes }, null, 1));
} catch (e) {
  await s.fail(e);
}
