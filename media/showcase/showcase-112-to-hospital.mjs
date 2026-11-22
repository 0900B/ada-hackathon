/**
 * Showcase a: "From 112 call to hospital" (~100 s, 1920x1080).
 * New 112 call (typed Slovenian words) -> triage -> ambulance + doctor car -> routes on the map ->
 * random road closure -> re-plan -> on scene -> transport -> closed -> audit.
 *
 *   node media/showcase/showcase-112-to-hospital.mjs [--base http://localhost:5240] [--api http://localhost:8040]
 *
 * Captions that describe what the system did are built from the backend's own answer (who was
 * sent, AI or rules, detour or slowdown), so they stay true for any backend and any configuration.
 */
import { options, startSession } from "./lib.mjs";
import { UI, frameRoute, zoomMapAround } from "./ui.mjs";

const NAME = "showcase-112-to-hospital";
const WORDS = "Moj oče ima močno bolečino v prsih, ves je poten in težko diha.";
const WHERE = "Polje";
const CALLER = "Ana Novak";

const opts = options();
const s = await startSession({ name: NAME, opts, captionArea: [0, 470] }); // keep the right-hand panel visible
const tripOf = (st) => [...st.trips].reverse().find((t) => t.call?.text_sl === WORDS || t.note === WORDS);
const vehicle = (st, id) => st.vehicles.find((v) => v.id === id);
let trip = null;
let aiOn = false;

try {
  // --- set-up (not in the video) ---
  if (opts.setup) {
    await s.api.reset(false);
    await s.api.calls(false); // no unrelated calls in this film
  }
  aiOn = Boolean((await s.api.state()).agent?.enabled);
  await s.goto("/sim");
  await s.page.locator(".leaflet-tile-loaded").first().waitFor({ timeout: 20000 }).catch(() => undefined);
  await s.click(UI.callsTab, { what: "calls tab", optional: true, pause: 0 });
  await s.hold(2500);

  s.begin();
  await s.card({
    title: "From 112 call to hospital",
    text: "One call, followed end to end: the caller's words, triage, dispatch, a road closure on the way, transport and handover.",
    pill: "Real UI · simulated fleet and calls",
  });
  await s.hold(4200);
  await s.hideCard();
  await s.hold(700);

  await s.steps([
    {
      say: "Simulation world: **Ljubljana Demo EMS** (fictional). 11 units on real Ljubljana roads; calls are simulated.",
      hold: 4500,
    },
    {
      say: "A 112 call comes in. The call-taker opens **New 112 call**.",
      run: async () => {
        await s.click(UI.callsTab, { what: "calls tab", optional: true });
        await s.click(UI.newCall, { what: "New 112 call" });
      },
      hold: 1200,
    },
    {
      say: "They type what the caller says, in Slovenian, and where.",
      run: async () => {
        await s.type(UI.callWords, WORDS, { what: "caller's words", delay: 38 });
        await s.type(UI.callAddress, WHERE, { what: "address", delay: 70 });
        await s.page.keyboard.press("Escape").catch(() => undefined); // close the place suggestions
        await s.type(UI.callerName, CALLER, { what: "caller's name", delay: 50 }).catch(() => undefined);
      },
      hold: 1200,
    },
    {
      say: "One click: **Classify and dispatch**.",
      run: async () => {
        await s.click(UI.classify, { what: "Classify and dispatch" });
        trip = await s.until(tripOf, { timeout: 60000, what: "the new call" });
        const tri = trip.call?.triage ?? {};
        const level = (tri.severity ?? trip.severity ?? "").replace(/^./, (c) => c.toUpperCase());
        const cond = tri.condition_label ?? trip.condition_label ?? "";
        const who =
          tri.by === "ai"
            ? "Classified by **Claude** from the caller's words."
            : "Classified by the **keyword rules** (Claude is not connected in this recording; with it, the AI triages).";
        await s.hold(1800);
        await s.say(`Triage: **${level} · ${cond}**${tri.needs_doctor ? ", doctor needed" : ""}. ${who}`);
      },
      hold: 5200,
    },
    {
      say: async () => {
        const st = await s.api.state();
        trip = tripOf(st) ?? trip;
        const ev = [...st.events].reverse().find((e) => e.affected_trip_ids?.includes(trip.id));
        const heli = /H1 checked/.test(ev?.summary ?? "") ? " The helicopter was checked: not 10 min faster." : "";
        const doc = trip.doctor_vehicle_id && trip.doctor_vehicle_id !== trip.vehicle_id ? ` and doctor car **${trip.doctor_vehicle_id}**` : "";
        return `The engine dispatches at once: **${trip.vehicle_id ?? "the nearest unit"}**${doc}.${heli}`;
      },
      run: async () => {
        // frame the highlighted route (fallback: zoom around the unit's marker)
        if (!(await frameRoute(s, { maxLevels: 2 }))) await zoomMapAround(s, [UI.vehicleMarker(trip.vehicle_id ?? "A1")], { levels: 1 });
        await s.page.mouse.move(1200, 700); // move the real mouse off the markers (no tooltips)
        await s.hold(1500);
        await s.hero();
      },
      hold: 4500,
    },
    {
      say: "The call card follows it to the end: every step, and who did it: caller, triage, engine, crew, dispatcher.",
      run: async () => {
        const card = await s.find([(p) => p.locator(".call-card.open .timeline"), (p) => p.locator(".timeline").first()], { timeout: 3000 });
        if (card) await s.point(card);
      },
      hold: 4500,
    },
    {
      say: "**Kaos na terenu**: a road closes on the way. (Demo button: **Random failure → Road closure**.)",
      run: async () => {
        const before = (await s.api.state()).events.length;
        await s.click(UI.randomFailureMenu, { what: "Random failure menu" });
        await s.hold(500);
        await s.click(UI.menuItem("Road closure"), { what: "Road closure" });
        const ev = await s.until((st) => st.events.length > before && st.events[st.events.length - 1], { timeout: 20000, what: "the failure event" });
        const sum = ev.summary ?? "";
        const on = /on the route of ([^:;]+)/.exec(sum)?.[1]?.trim();
        let text;
        if (ev.type !== "road_closure") text = `Failure injected: ${sum.split(";")[0]}. The engine re-plans at once.`;
        else if (/rerouting around it/.test(sum)) text = `Road closed${on ? ` on the route of **${on}**` : ""}. The engine reroutes around it at once (orange detour).`;
        else
          text = `Road closed${on ? ` on the route of **${on}**` : ""}. The engine re-plans the arrival times with the closure's slowdown. (Detour routing needs the TomTom key, not set in this local recording.)`;
        s.notes.push(`closure: ${sum}`);
        await s.hold(800);
        await s.say(text);
      },
      hold: 6500,
    },
    {
      say: `Time-lapse: the ambulance reaches the patient; the doctor car joins on scene.`,
      run: async () => {
        await s.timelapse(() => s.until((st) => ["onboard", "completed"].includes(tripOf(st)?.status), { timeout: 900000, what: "on scene" }), { show: 6 });
      },
      hold: 2500,
    },
    {
      say: "On scene, then transport to **UKC Ljubljana** (catheter lab), with the doctor.",
      run: async () => {
        await s.timelapse(
          () =>
            s.until(
              (st) => {
                const t = tripOf(st);
                return t?.status === "completed" || (t?.vehicle_id && vehicle(st, t.vehicle_id)?.status === "with_patient");
              },
              { timeout: 1200000, what: "transporting" },
            ),
          { show: 5 },
        );
      },
      hold: 3000,
    },
    {
      say: "Handover at UKC: the call is closed, its whole timeline kept.",
      run: async () => {
        // closed = completed and (when the backend keeps a timeline) its "closed" entry, after the handover
        const closed = (t) => t?.status === "completed" && (!t.timeline?.length || t.timeline.some((e) => e.kind === "closed"));
        await s.timelapse(() => s.until((st) => closed(tripOf(st)), { timeout: 1500000, what: "closed" }), { show: 5 });
        await s.click(UI.callsTab, { what: "calls tab", optional: true });
        const id = trip.call?.call_id ?? trip.id;
        const isOpen = () => s.find([(p) => p.locator(".call-card.open", { hasText: id })], { timeout: 1200 });
        if (!(await isOpen())) {
          if (!(await s.find(UI.callCard(id), { timeout: 1200 }))) await s.click(UI.closedCalls, { what: "closed calls", optional: true, timeout: 4000 });
          await s.hold(600);
          if (!(await isOpen())) await s.click(UI.callCard(id), { what: "closed call card", optional: true, timeout: 4000 });
        }
        const tl = await s.find([(p) => p.locator(".call-card.open .timeline")], { timeout: 2000 });
        if (tl) await s.point(tl);
      },
      hold: 5500,
    },
    {
      say: "Every message, recommendation and decision is also in the **audit log**.",
      run: async () => {
        await s.click([(p) => p.getByRole("link", { name: /^Audit$/i }), (p) => p.locator("nav a", { hasText: "Audit" })], { what: "Audit page", optional: true });
      },
      hold: 4500,
    },
  ]);

  await s.say("");
  await s.card({
    title: "When things go wrong, a new plan in seconds.",
    text: (aiOn ? "Claude understands and proposes" : "AI understands and proposes") + "; the engine computes every number; the dispatcher decides.",
    pill: "Bypass · prototype",
  });
  await s.hold(4500);

  const r = await s.finish({
    poster: { title: "From 112 call to hospital", subtitle: "A Slovenian 112 call, triage, ambulance and doctor car, a road closure, transport and handover: the real UI, end to end.", duration: "Showcase · about 100 s" },
  });
  console.log(JSON.stringify({ ...r, notes: s.notes }, null, 1));
} catch (e) {
  await s.fail(e);
}
