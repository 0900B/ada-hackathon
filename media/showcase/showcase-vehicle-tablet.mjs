/**
 * Showcase c: "In the vehicle" (~53 s, 1920x1080, the tablet view in a tablet frame).
 * Ambulance A1's tablet at base -> a 112 call is dispatched to it (message from dispatch) ->
 * acknowledge -> navigation: heading up, north up, overview -> quick status buttons.
 *
 *   node media/showcase/showcase-vehicle-tablet.mjs [--base http://localhost:5240] [--api http://localhost:8040] [--unit A1]
 *
 * The call is posted through the API (POST /sim/calls) while the tablet is open; it is placed where
 * the unit is the nearest ambulance (Polje for A1 at Base Center).
 */
import { options, startSession } from "./lib.mjs";
import { UI } from "./ui.mjs";

const NAME = "showcase-vehicle-tablet";
const argUnit = process.argv.find((a) => a.startsWith("--unit="))?.slice(7) ?? (process.argv.includes("--unit") ? process.argv[process.argv.indexOf("--unit") + 1] : null);
const UNIT = argUnit ?? "A1";
const CALL = {
  text: "Mama ne more govoriti, ima povešen ustni kot in ne more premakniti desne roke.",
  address: "Polje",
  caller_name: "Marko Zupan",
};

const stage = (unit) => `<!doctype html><html><head><meta charset="utf-8"><style>/*FONTS*/
*{box-sizing:border-box}
html,body{margin:0;width:1920px;height:1080px;overflow:hidden;font-family:"Inter Variable",Inter,system-ui,sans-serif;color:#e6ebf1;-webkit-font-smoothing:antialiased;
  background:radial-gradient(1100px 650px at 50% 42%,rgba(37,99,235,.14),transparent 70%),linear-gradient(180deg,#0b0f14,#05070a)}
.tab{position:absolute;left:300px;top:44px;width:1320px;height:840px;padding:20px;border-radius:34px;background:#12171e;border:1px solid #2c3846;box-shadow:0 40px 90px rgba(0,0,0,.7),inset 0 0 0 2px #070a0e}
.tab iframe{width:1280px;height:800px;border:0;border-radius:14px;display:block;background:#0b0f14}
.cam{position:absolute;left:50%;top:8px;width:7px;height:7px;margin-left:-3px;border-radius:50%;background:#2a3442}
.label{position:absolute;left:300px;top:12px;font-size:14px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#7d8a99}
.label b{color:#e6ebf1}
</style></head><body>
<div class="label">Vehicle tablet · <b>${unit}</b> · /vehicle/${unit}</div>
<div class="tab"><div class="cam"></div><iframe id="mdt" src="{{BASE}}/vehicle/${unit}?world=sim"></iframe></div>
</body></html>`;

const opts = options();
const s = await startSession({ name: NAME, opts });

try {
  if (opts.setup) {
    await s.api.reset(false);
    await s.api.calls(false);
  }
  await s.stage(stage(UNIT));
  const mdt = s.frame("#mdt");
  await mdt.locator(".leaflet-tile-loaded").first().waitFor({ timeout: 25000 }).catch(() => undefined);
  await s.hold(3000);

  s.begin();
  await s.card({
    title: "In the vehicle",
    text: "The crew's tablet: the job, the caller's words, navigation on real roads, and every change from dispatch.",
    pill: "Real UI · simulated fleet and calls",
  });
  await s.hold(4000);
  await s.hideCard();
  await s.hold(700);

  let trip = null;
  await s.steps([
    {
      say: `Ambulance **${UNIT}**'s tablet, waiting at its base for the next emergency.`,
      hold: 4000,
    },
    {
      say: "A 112 call comes in; the engine sends this ambulance.",
      run: async () => {
        const r = await s.api.call(CALL);
        trip = r.trip;
        s.notes.push(`call: ${r.summary}`);
        if (trip.vehicle_id !== UNIT) s.notes.push(`WARNING: the engine sent ${trip.vehicle_id}, not ${UNIT}; re-run with --unit ${trip.vehicle_id}`);
        const msg = await s.find(UI.acknowledge, { root: mdt, timeout: 15000 });
        await s.hold(600);
        await s.say(
          msg
            ? `**Message from dispatch**: a new job, ${(trip.condition_label ?? `${trip.severity ?? ""} call`).toLowerCase()} in ${CALL.address}, with a chime.`
            : `The engine dispatched ${trip.vehicle_id}: the job appears on the tablet.`,
        );
      },
      hold: 5500,
    },
    {
      say: "The crew acknowledges. The job card shows the caller's own words and the triage.",
      run: async () => {
        await s.click(UI.acknowledge, { root: mdt, what: "Acknowledge", optional: true, timeout: 3000 });
      },
      hold: 4500,
    },
    {
      say: "**Heading up**: the map turns with the ambulance, the route ahead in blue.",
      run: async () => {
        await s.click(UI.navView("Heading up"), { root: mdt, what: "Heading up", optional: true });
        await s.page.mouse.move(1700, 1000);
        await s.hold(2500);
        await s.hero();
      },
      hold: 3500,
    },
    {
      say: "**North up**, still following the vehicle.",
      run: async () => {
        await s.click(UI.navView("North up"), { root: mdt, what: "North up", optional: true });
      },
      hold: 5000,
    },
    {
      say: "**Overview**: the whole remaining route, to the patient and on to the hospital.",
      run: async () => {
        await s.click(UI.navView("Overview"), { root: mdt, what: "Overview", optional: true });
      },
      hold: 5500,
    },
    {
      say: "One tap reaches dispatch: breakdown, delay, road closed, patient worse. Or speak, in Slovenian or English.",
      run: async () => {
        const quick = await s.find([(p) => p.getByRole("button", { name: /Road ahead closed/i }), (p) => p.getByRole("button", { name: /Breakdown/i })], { root: mdt, timeout: 3000 });
        if (quick) await s.point(quick);
        await s.hold(1500);
        await s.click(UI.navView("Heading up"), { root: mdt, what: "Heading up", optional: true });
      },
      hold: 4000,
    },
  ]);

  await s.say("");
  await s.card({
    title: "The crew always knows the plan.",
    text: "Every change the dispatcher approves reaches the vehicle at once, with the reason.",
    pill: "Bypass · prototype",
  });
  await s.hold(4000);

  const r = await s.finish({
    poster: { title: "In the vehicle", subtitle: "The ambulance tablet: a new job from dispatch, the caller's words, navigation on real roads, one-tap status.", duration: "Showcase · about 50 s", crop: { x: 288, y: 32, w: 1344, h: 864 } },
  });
  console.log(JSON.stringify({ ...r, notes: s.notes }, null, 1));
} catch (e) {
  await s.fail(e);
}
