// Captures the real-UI screenshots and short clips the promo and the ads use (media/promo/assets/).
//
//   node media/promo/capture-assets.mjs [BASE_URL] [--only=call,surge,closure,crew,tablet,audit,override]
//
// BASE_URL is the frontend (default http://localhost:5241). It drives the Simulation world through the
// UI only (Scenarios tab, New 112 call, Random failure, crew view, Analyse/Approve), so it works against
// a local dev server or a deployed frontend. It resets and stages the simulation: don't point it at a
// deployment someone is presenting from.
//
// Screens are JPEG (quality 85) to keep the committed assets small; clips are VP9 webm (headless
// Chromium plays webm, not H.264). The dashboard is captured at 1200x675 CSS px with a device scale of
// 1.6, i.e. 1920x1080 pixels with a UI large enough to read in a video.
import { createRequire } from "node:module";
import { mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(new URL("../tools/package.json", import.meta.url));
const { chromium } = require("playwright");
const ffmpeg = require("ffmpeg-static");

const args = process.argv.slice(2);
const BASE = (args.find((a) => !a.startsWith("--")) ?? process.env.BASE_URL ?? "http://localhost:5241").replace(/\/$/, "");
const only = (args.find((a) => a.startsWith("--only="))?.slice(7).split(",") ?? []).filter(Boolean);
const want = (step) => only.length === 0 || only.includes(step);

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(HERE, "assets");
const TMP = path.join(HERE, "..", "out", "_capture-tmp");
mkdirSync(OUT, { recursive: true });
mkdirSync(TMP, { recursive: true });

const DASH = { viewport: { width: 1200, height: 675 }, deviceScaleFactor: 1.6 };
const PHONE = { viewport: { width: 430, height: 932 }, deviceScaleFactor: 2.5, isMobile: true, hasTouch: true };
const TABLET = { viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1.5, hasTouch: true };

const browser = await chromium.launch();
const log = (...a) => console.log("[capture]", ...a);

// ---------------------------------------------------------------------------------------------
// Helpers (selectors by role and visible text, with fallbacks: the UI changes)

async function openSim(page) {
  await page.goto(`${BASE}/sim`);
  await page.waitForSelector(".side-tabs, [role=tablist]", { timeout: 30000 });
  await page.waitForTimeout(1200); // map tiles
}

async function tab(page, name) {
  const re = new RegExp(`^\\s*${name}`, "i");
  const t = page.getByRole("tab", { name: re });
  if (await t.count()) return t.first().click();
  return page.getByText(re).first().click();
}

async function scenario(page, label) {
  await tab(page, "Scenarios");
  await page.getByRole("button", { name: new RegExp(label, "i") }).first().click();
  await page.waitForTimeout(2500);
}

async function resetSim(page) {
  await tab(page, "Scenarios");
  await page.getByRole("button", { name: /Reset simulation/i }).click();
  await page.waitForTimeout(1500);
}

async function centre(page, id, zoomOut = 0) {
  const chip = page.locator(".vchip", { has: page.locator("strong", { hasText: new RegExp(`^${id}$`) }) });
  await chip.first().click();
  await page.locator(".vpop").getByRole("button", { name: /Centre/i }).click();
  await page.locator(".vpop .vc-close").click().catch(() => {});
  for (let i = 0; i < zoomOut; i++) await page.locator(".leaflet-control-zoom-out").click();
  await page.waitForTimeout(1200);
}

const hideToasts = (page) => page.addStyleTag({ content: ".toast{display:none!important}" });

/** A visible pointer for clips (headless Chromium draws none). */
const CURSOR = `
  addEventListener("DOMContentLoaded", () => {
    const c = document.createElement("div");
    c.id = "__cursor";
    c.style.cssText = "position:fixed;z-index:99999;left:-40px;top:-40px;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;background:rgba(255,255,255,.85);box-shadow:0 0 0 3px rgba(79,143,247,.9),0 2px 10px rgba(0,0,0,.6);pointer-events:none;transition:transform .12s,opacity .4s;opacity:0";
    document.body.appendChild(c);
    let idle;
    addEventListener("mousemove", (e) => {
      c.style.left = e.clientX + "px"; c.style.top = e.clientY + "px"; c.style.opacity = "1";
      clearTimeout(idle); idle = setTimeout(() => (c.style.opacity = "0"), 1600);
    }, true);
    addEventListener("mousedown", () => (c.style.transform = "scale(.7)"), true);
    addEventListener("mouseup", () => (c.style.transform = ""), true);
  });`;

/** Moves the pointer out of the way (bottom-right corner) and waits until the drawn pointer has faded. */
async function park(page) {
  const vp = page.viewportSize();
  await page.mouse.move(vp.width - 4, vp.height - 4, { steps: 4 });
  await page.waitForTimeout(2100);
}

async function moveClick(page, locator) {
  const box = await locator.boundingBox();
  if (box) {
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 18 });
    await page.waitForTimeout(250);
  }
  await locator.click();
}

async function shot(page, name, opts = {}) {
  const file = path.join(OUT, name);
  await page.evaluate(() => document.getElementById("__cursor")?.style.setProperty("display", "none"));
  await page.screenshot({ path: file, type: "jpeg", quality: 85, ...opts });
  await page.evaluate(() => document.getElementById("__cursor")?.style.removeProperty("display"));
  log("screen", name, `${Math.round(statSync(file).size / 1024)} KB`);
}

/**
 * Screenshot of the right-hand panel in a taller window (more of it visible), then back. `anchors`
 * ({key: locator}) are measured in the screenshot's pixels and saved to assets/layout.json, so the
 * promo can crop and highlight them wherever they land after a re-capture.
 */
async function panelShot(page, name, height = 1500, anchors = {}) {
  const vp = page.viewportSize();
  await page.setViewportSize({ width: vp.width, height });
  await page.waitForTimeout(700);
  const file = path.join(OUT, name);
  const aside = page.locator("aside.side, aside").first();
  await page.evaluate(() => document.getElementById("__cursor")?.style.setProperty("display", "none"));
  await aside.screenshot({ path: file, type: "jpeg", quality: 88 });
  await page.evaluate(() => document.getElementById("__cursor")?.style.removeProperty("display"));
  const dpr = await page.evaluate(() => devicePixelRatio);
  const a = await aside.boundingBox();
  const boxes = {};
  for (const [key, loc] of Object.entries(anchors)) {
    const b = await loc.first().boundingBox().catch(() => null);
    if (b) boxes[key] = { x: Math.round((b.x - a.x) * dpr), y: Math.round((b.y - a.y) * dpr), w: Math.round(b.width * dpr), h: Math.round(b.height * dpr) };
    else console.warn(`[capture] anchor ${name}:${key} not found`);
  }
  saveLayout(name, { width: Math.round(a.width * dpr), height: Math.round(a.height * dpr), boxes });
  log("panel", name, `${Math.round(statSync(file).size / 1024)} KB`, Object.keys(boxes).join(","));
  await page.setViewportSize(vp);
  await page.waitForTimeout(400);
}

const LAYOUT = path.join(OUT, "layout.json");
function saveLayout(name, entry) {
  let all = {};
  try {
    all = JSON.parse(readFileSync(LAYOUT, "utf8"));
  } catch {}
  all[name] = entry;
  writeFileSync(LAYOUT, JSON.stringify(all, null, 2));
}

/**
 * Records a clip: fn(page, mark) marks "start" and "end"; the clip is cut there and sped up by `speed`.
 * Playwright's recordVideo (and the CDP screencast) deliver frames at CSS-pixel size, which would lose
 * the 1.6x device scale; so frames are grabbed with Page.captureScreenshot in a loop (full device
 * pixels, about 15-20 per second), stamped with their time and encoded as a variable-frame-rate input.
 */
async function clip(name, ctxOpts, fn, { speed = 1 } = {}) {
  const ctx = await browser.newContext(ctxOpts);
  await ctx.addInitScript(CURSOR);
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  const frames = [];
  let grabbing = false;
  let grabber = Promise.resolve();
  const marks = {};
  const mark = (k) => {
    marks[k] = Date.now();
    if (k === "start") {
      grabbing = true;
      grabber = (async () => {
        while (grabbing) {
          const t = Date.now();
          const r = await cdp.send("Page.captureScreenshot", { format: "jpeg", quality: 90, optimizeForSpeed: true }).catch(() => null);
          if (r) frames.push({ t, data: r.data });
        }
      })();
    }
    if (k === "end") grabbing = false;
  };
  try {
    await fn(page, mark);
  } finally {
    grabbing = false;
    await grabber;
    await ctx.close();
  }
  const dir = path.join(TMP, name.replace(/\W/g, "_"));
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  const lines = [];
  frames.forEach((f, i) => {
    const file = `f${String(i).padStart(5, "0")}.jpg`;
    writeFileSync(path.join(dir, file), Buffer.from(f.data, "base64"));
    const next = frames[i + 1]?.t ?? marks.end ?? f.t + 50;
    lines.push(`file '${file}'`, `duration ${((next - f.t) / 1000).toFixed(4)}`);
  });
  lines.push(`file 'f${String(frames.length - 1).padStart(5, "0")}.jpg'`);
  writeFileSync(path.join(dir, "list.txt"), lines.join("\n"));
  const file = path.join(OUT, name);
  execFileSync(ffmpeg, [
    "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", path.join(dir, "list.txt"),
    "-vf", `setpts=PTS/${speed},fps=30,scale=1920:1080:flags=lanczos,format=yuv420p`,
    "-c:v", "libvpx-vp9", "-crf", "36", "-b:v", "0", "-row-mt", "1", "-deadline", "good", "-cpu-used", "3", "-an", file,
  ]);
  rmSync(dir, { recursive: true, force: true });
  const dur = (marks.end - marks.start) / 1000 / speed;
  log("clip", name, `${dur.toFixed(1)} s`, `${frames.length} frames (${(frames.length / (dur * speed)).toFixed(0)}/s captured)`, `${Math.round(statSync(file).size / 1024)} KB`);
}

async function step(name, fn) {
  if (!want(name)) return;
  log("step", name);
  try {
    await fn();
  } catch (e) {
    console.warn(`[capture] step ${name} failed: ${e.message.split("\n")[0]}`);
  }
}

// ---------------------------------------------------------------------------------------------
// Steps

const CALLER_WORDS = "Moj mož se je zgrudil in ne diha!";

await step("call", async () => {
  await clip("clip-112.webm", DASH, async (page, mark) => {
    await openSim(page);
    await resetSim(page);
    await hideToasts(page);
    await tab(page, "Calls");
    await page.waitForTimeout(800);
    mark("start");
    await moveClick(page, page.getByRole("button", { name: /New 112 call/i }).first());
    await page.waitForTimeout(500);
    await moveClick(page, page.locator("#call-words, textarea").first());
    await page.locator("#call-words, textarea").first().pressSequentially(CALLER_WORDS, { delay: 55 });
    await page.waitForTimeout(300);
    await moveClick(page, page.locator("#call-address").first());
    await page.locator("#call-address").first().pressSequentially("Bežigrad", { delay: 60 });
    await page.waitForTimeout(400);
    await moveClick(page, page.getByRole("button", { name: /Classify and dispatch/i }).first());
    await page.waitForTimeout(5200);
    mark("end");
    await shot(page, "call-112.jpg");
    await panelShot(page, "panel-112.jpg", 1350, {
      card: page.locator(".call-card").first(),
      timeline: page.locator(".timeline").first(),
    });
  });
});

await step("surge", async () => {
  await clip(
    "clip-surge.webm",
    DASH,
    async (page, mark) => {
      await openSim(page);
      await scenario(page, "Call surge");
      await hideToasts(page);
      await tab(page, "Calls");
      await centre(page, "A2", 1);
      await park(page);
      mark("start");
      await page.waitForTimeout(20000);
      mark("end");
      // a call card with the doctor car's dispatch in its timeline
      const card = page.locator(".call-card", { hasText: /Major trauma|Serious/ }).first();
      await card.locator(".call-summary").click().catch(() => {});
      await page.waitForTimeout(1200);
      await shot(page, "dash-surge.jpg");
    },
    { speed: 4 },
  );
  // tablet in a busy vehicle while the surge runs
  const ctx = await browser.newContext(TABLET);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/vehicle/A1?world=sim`);
  await page.waitForTimeout(6000);
  await shot(page, "tablet-a1.jpg");
  await ctx.close();
});

await step("closure", async () => {
  const ctx = await browser.newContext(DASH);
  const page = await ctx.newPage();
  await openSim(page);
  await scenario(page, "Stroke and closure");
  await hideToasts(page);
  await tab(page, "Calls");
  const card = page.locator(".call-card", { hasText: /stroke/i }).first();
  await card.locator(".call-summary").click().catch(() => {});
  await centre(page, "A2", 1);
  await page.mouse.move(-50, -50);
  await shot(page, "map-closure.jpg");
  await ctx.close();
});

await step("override", async () => {
  const ctx = await browser.newContext(DASH);
  const page = await ctx.newPage();
  await openSim(page);
  await scenario(page, "Priority override");
  await hideToasts(page);
  await tab(page, "Calls");
  const card = page.locator(".call-card", { hasText: /Cardiac arrest/i }).first();
  await card.locator(".call-summary").click().catch(() => {});
  await page.waitForTimeout(1500);
  await shot(page, "dash-override.jpg");
  await panelShot(page, "panel-override.jpg", 1350, {
    card: card,
    dispatched: page.locator(".timeline li", { hasText: /diverted|Dispatched/i }),
  });
  await ctx.close();
});

await step("crew", async () => {
  const dashCtx = await browser.newContext(DASH);
  const dash = await dashCtx.newPage();
  await openSim(dash);
  await scenario(dash, "Prepare crew demo");
  await hideToasts(dash);

  const phoneCtx = await browser.newContext(PHONE);
  const phone = await phoneCtx.newPage();
  await phone.goto(`${BASE}/crew/T1?world=sim`);
  await phone.waitForTimeout(2500);
  await shot(phone, "crew-phone.jpg");
  // No speech in headless Chromium: the quick button sends the same sentence
  await phone.getByRole("button", { name: /Vozilo je obstalo/i }).first().click();
  await phone.waitForTimeout(2500);
  await shot(phone, "crew-sent.jpg");
  await phoneCtx.close();

  await dash.waitForTimeout(600);
  await dash.keyboard.press("a"); // Analyse (the engine's plan when no AI key is set)
  await dash.waitForTimeout(4000);
  await tab(dash, "Dispatch");
  await dash.waitForTimeout(500);
  await shot(dash, "dash-options.jpg");
  const approveBtn = dash.getByRole("button", { name: /Approve option 1/i });
  await panelShot(dash, "panel-options.jpg", 1700, {
    waiting: dash.getByText(/Waiting for your decision/i),
    title: dash.locator(".side-body:not([hidden])").getByText(/broke down/i).nth(1),
    option: dash.locator(".side-body:not([hidden]) li, .side-body:not([hidden]) section, .side-body:not([hidden]) div", { has: approveBtn, hasText: /Recommended/ }).last(),
    approve: approveBtn,
  });
  await dashCtx.close();

  await clip("clip-approve.webm", DASH, async (page, mark) => {
    await openSim(page);
    await tab(page, "Dispatch");
    await hideToasts(page);
    await centre(page, "T1", 1);
    await tab(page, "Dispatch");
    await park(page);
    await page.locator(".side-body:not([hidden])").first().evaluate((el) => el.scrollTo(0, 260)).catch(() => {});
    await page.waitForTimeout(800);
    mark("start");
    await page.waitForTimeout(1500);
    await page.keyboard.press("y"); // approve the recommended option
    await page.waitForTimeout(6500);
    mark("end");
    await shot(page, "dash-approved.jpg");
  });
});

await step("audit", async () => {
  const ctx = await browser.newContext(DASH);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/audit`);
  await page.waitForTimeout(3000);
  await shot(page, "audit.jpg");
  await ctx.close();
});

await browser.close();
rmSync(TMP, { recursive: true, force: true });
log("done", OUT);
