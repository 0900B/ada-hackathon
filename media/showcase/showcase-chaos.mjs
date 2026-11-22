/**
 * Showcase d: "Chaos on demand" (~60-70 s, 1920x1080).
 * Random call x2 -> Random failure: engine failure -> fog -> Call surge with contracted units ->
 * Priority override. Every caption after an action is made from the engine's own summary.
 *
 *   node media/showcase/showcase-chaos.mjs [--base http://localhost:5240] [--api http://localhost:8040]
 */
import { options, startSession } from "./lib.mjs";
import { UI } from "./ui.mjs";

const NAME = "showcase-chaos";
const SIDE_PANEL = 470; // keep the caption bar off the right-hand panel
const opts = options();
const s = await startSession({ name: NAME, opts, captionArea: [0, SIDE_PANEL] });

// --- captions from the engine's summaries (fall back to a shortened summary) ---

function short(summary, max = 170) {
  let t = String(summary ?? "").replace(/\s*Triaged by[^.]*\.?/g, "").trim();
  if (t.length > max) {
    const cut = t.lastIndexOf(";", max);
    t = (cut > 60 ? t.slice(0, cut) : t.slice(0, max - 1).replace(/\s+\S*$/, "")) + " …";
  }
  return t;
}
/** Who the engine sent, how soon, and whether it was diverted: [unit, minutes, divertedFromLevel] (any may be null). */
const reach = (sum) => [
  /dispatched (\w+)/.exec(sum)?.[1] ?? null,
  /at the patient [\d:]+ \(in (\d+) min\)/.exec(sum)?.[1] ?? null,
  /diverted from TR-\d+ \((\w+)\)/.exec(sum)?.[1] ?? null,
];
const takenOver = (sum) => /taken over by (\w+) \([^)]*within its ([\d-]+ ?min) target\)/.exec(sum);

function callCaption(sum) {
  const m = /^New (\w+) call TR-\d+ \(([^)]+)\): (.+?) → [^;]+?; dispatched (\w+)(?: \(([^)]*)\))?: at the patient [\d:]+ \(in (\d+) min\)/.exec(sum);
  if (!m) return short(sum);
  const where = m[3].split(",").slice(-1)[0].replace(/\s*\(call\)/, "").trim();
  const doc = /\+ doctor (D\d)/.exec(sum);
  const why = m[5] ? ` (${m[5].replace(/;/g, ",")})` : "";
  return `**${m[1][0].toUpperCase()}${m[1].slice(1)}** · ${m[2]}, ${where}. **${m[4]}** dispatched${why}, at the patient in ${m[6]} min${doc ? `, doctor car **${doc[1]}** too` : ""}.`;
}

function breakdownCaption(sum) {
  const head = sum.split(";")[0].trim();
  const [unit, mins, from] = reach(sum);
  const t = takenOver(sum);
  if (!/broke down/.test(head) || !unit) return short(sum, 190);
  return (
    `**${head}.** Its call goes to **${unit}** at once${from ? ` (diverted from an ${from} call)` : ""}${mins ? `, at the patient in ${mins} min` : ""}` +
    (t && from ? `; **${t[1]}** takes the ${from} call, within its ${t[2]} target.` : ".")
  );
}

function fogCaption(ev) {
  const sum = ev.summary ?? "";
  if (ev.type !== "fog") return `No helicopter was flying, so the demo picked another failure: ${short(sum, 150)}`;
  const g = /(Helicopter \d+|H\d) grounded for (\d+) min/.exec(sum);
  const [unit, mins] = reach(sum);
  return `**Fog: ${g ? `${g[1]} grounded for ${g[2]} min` : "the helicopter is grounded"}.**` + (unit ? ` Its call goes to **${unit}** by road${mins ? `, at the patient in ${mins} min` : ""}.` : " Its trips go to road units at once.");
}

/** Click, then wait for a new event; returns the first new event. */
async function act(clickFn, what) {
  const before = new Set((await s.api.state()).events.map((e) => e.id));
  await clickFn();
  const ev = await s.until((st) => st.events.find((e) => !before.has(e.id)), { timeout: 30000, what });
  s.notes.push(`${what}: ${ev.summary}`);
  await s.hold(700);
  return ev;
}

const failure = (label) => async () => {
  await s.click(UI.randomFailureMenu, { what: "Random failure menu" });
  await s.hold(450);
  await s.click(UI.menuItem(label), { what: label });
};

try {
  if (opts.setup) {
    await s.api.reset(false);
    await s.api.calls(false);
    await s.api.autoAnalyse(false);
    // something to disrupt: a call on the road, and a remote call that the helicopter flies to
    await s.api.post("/sim/admin/random-call", { severity: "serious" }).catch(() => undefined);
    await s.api
      .call({ text: "Planinec je padel s skale, krvavi iz glave in je zmeden.", address: "Kamniška Bistrica", lat: 46.307, lon: 14.596, caller_name: "Gorski vodnik" })
      .catch((e) => s.notes.push(`remote call failed: ${e.message}`));
  }
  await s.goto("/sim");
  await s.page.locator(".leaflet-tile-loaded").first().waitFor({ timeout: 20000 }).catch(() => undefined);
  await s.click(UI.callsTab, { what: "calls tab", optional: true, pause: 0 });
  await s.hold(2500);

  s.begin();
  await s.card({
    title: "Chaos on demand",
    text: "Random 112 calls, an engine failure, fog, a surge of calls, a cardiac arrest next to a busy ambulance. Plan B answers each one at once.",
    pill: "Real UI · simulated fleet and calls",
  });
  await s.hold(3600);
  await s.hideCard();
  await s.hold(600);

  await s.steps([
    {
      say: "**Random call** (R): a 112 call from the demo library, triaged and dispatched at once.",
      run: async () => {
        const ev = await act(() => s.click(UI.randomCall, { what: "Random call" }), "random call 1");
        await s.say(`Call 1 · ${callCaption(ev.summary)}`);
      },
      hold: 4800,
    },
    {
      say: "And another.",
      run: async () => {
        const ev = await act(() => s.click(UI.randomCall, { what: "Random call" }), "random call 2");
        await s.say(`Call 2 · ${callCaption(ev.summary)}`);
      },
      hold: 4800,
    },
    {
      say: "**Random failure → Engine failure**: a unit on a job breaks down.",
      run: async () => {
        const ev = await act(failure("Engine failure"), "engine failure");
        await s.say(breakdownCaption(ev.summary ?? ""));
      },
      hold: 6000,
    },
    {
      say: "**Random failure → Fog** over the helicopter base.",
      run: async () => {
        const ev = await act(failure("Fog"), "fog");
        await s.say(fogCaption(ev));
      },
      hold: 5200,
    },
    {
      say: "**Call surge** (Scenarios): seven calls in about three minutes, including a cardiac arrest. Three own ambulances.",
      run: async () => {
        await s.click(UI.scenariosTab, { what: "Scenarios tab" });
        await s.hold(500);
        await s.click(UI.scenario("Call surge"), { what: "Call surge" });
        await s.until((st) => st.trips.length >= 5, { timeout: 30000, what: "surge calls" });
        await s.hold(1200);
        await s.click(UI.alertsTab, { what: "Alerts tab", optional: true });
        const st = await s.api.state();
        const red = st.alerts.filter((a) => a.severity === "critical" || /red call/i.test(a.message)).length;
        await s.say(`Alerts: ${red ? `${red} red call${red > 1 ? "s" : ""} would be reached late. ` : ""}The engine offers contracted surge capacity; it never activates it by itself.`);
      },
      hold: 5000,
    },
    {
      say: "The dispatcher decides: **activate contracted units**.",
      run: async () => {
        await s.until((x) => x.alerts.some((a) => a.kind === "high_demand"), { timeout: 20000, what: "high-demand alert" }).catch(() => null);
        const ok = await s.click(UI.surgeButton, { what: "Activate contracted units", optional: true, timeout: 10000 });
        const st = ok ? await s.until((x) => x.surge?.active && x, { timeout: 20000, what: "surge active" }).catch(() => null) : null;
        const ev = st && [...st.events].reverse().find((e) => /surge capacity active/i.test(e.summary ?? ""));
        if (ev) {
          s.notes.push(`surge: ${ev.summary}`);
          const moved = (ev.summary.match(/TR-\d+ → \w+/g) ?? []).length;
          const units = /contracted ambulances ([^;]+?); private vans ([^;]+?);/.exec(ev.summary);
          await s.hold(500);
          await s.say(
            `Contracted units join${units ? `: ambulances ${units[1]}, vans ${units[2]}` : ""}.` + (moved ? ` **${moved} waiting calls** move to them at once, each reached sooner.` : ""),
          );
          await s.hold(1500);
          await s.hero();
        } else {
          s.notes.push("surge: no high-demand offer shown");
          await s.say("The alerts say what is late and why; the dispatcher can ask for mutual aid or contracted units.");
        }
      },
      hold: 6000,
    },
    {
      say: "**Priority override** (Scenarios): a cardiac arrest is reported right next to an ambulance that is on its way to a less urgent call.",
      run: async () => {
        await s.click(UI.scenariosTab, { what: "Scenarios tab" });
        await s.hold(500);
        await s.click(UI.scenario("Priority override"), { what: "Priority override" });
        const st = await s.until((x) => x.trips.some((t) => t.condition === "cardiac_arrest" && t.vehicle_id) && x, { timeout: 30000, what: "override" });
        const arrest = st.trips.find((t) => t.condition === "cardiac_arrest");
        const ev = [...st.events].reverse().find((e) => e.affected_trip_ids?.includes(arrest.id) && /divert/i.test(e.summary)) ?? [...st.events].reverse().find((e) => e.affected_trip_ids?.includes(arrest.id));
        const sum = ev?.summary ?? "";
        s.notes.push(`override: ${sum}`);
        await s.click(UI.callsTab, { what: "calls tab", optional: true });
        await s.hold(700);
        const m = /(\w+),? diverted from (TR-\d+) \(([a-z]+)\)(?:[^;]*?(\d+ min sooner than \w+))?/i.exec(sum);
        const t = takenOver(sum);
        await s.say(
          m
            ? `Automatic, by the rules: **${m[1]} diverted** from the ${m[3]} call to the cardiac arrest${m[4] ? `, ${m[4]}` : ""}` +
                (t ? `; **${t[1]}** takes the ${m[3]} call, still within its ${t[2]} target.` : ".")
            : short(sum, 190),
        );
      },
      hold: 7000,
    },

  ]);

  await s.say("");
  await s.card({
    title: "Kaos na terenu. A new plan in seconds.",
    text: "Calls, failures, fog, surges and priorities: the engine re-plans at once and explains why. The dispatcher stays in charge.",
    pill: "Plan B · prototype",
  });
  await s.hold(4500);

  const r = await s.finish({
    poster: { title: "Chaos on demand", subtitle: "Random calls, an engine failure, fog, a call surge and a priority override: how Plan B answers each one.", duration: "Showcase · about 75 s" },
  });
  console.log(JSON.stringify({ ...r, notes: s.notes }, null, 1));
} catch (e) {
  await s.fail(e);
}
