/**
 * Pitch-video recorder: drives the real deployed Plan B UI with Playwright and records each page
 * with the Chrome DevTools screencast at device scale 2 (so crops/zooms in the edit stay sharp).
 * Frames land in media/out/pitch-raw/<take>/<page>/ with their timestamps; marks (named moments)
 * go to marks.json; frames.mjs turns a page's frames into a constant-frame-rate MP4.
 *
 * The admin key is read from the environment (PLANB_KEY) and put into localStorage before the app
 * loads, so it never appears in a URL or a recorded frame.
 */
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";
import { spawnSync } from "node:child_process";

const require = createRequire(new URL("../tools/package.json", import.meta.url));
export const { chromium } = require("playwright");
export const FFMPEG = require("ffmpeg-static");
export const MEDIA = fileURLToPath(new URL("..", import.meta.url));
export const RAW = path.join(MEDIA, "out", "pitch-raw");

export const BASE = (process.env.BASE_URL ?? "https://frontend-tau-rust-6kpoiztcvd.vercel.app").replace(/\/+$/, "");
export const API = (process.env.API_URL ?? "https://ada-hackathon-production.up.railway.app").replace(/\/+$/, "");
const KEY = process.env.PLANB_KEY ?? "";

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export const log = (...a) => console.log(`[${new Date().toISOString().slice(11, 19)}]`, ...a);

// --- API ---------------------------------------------------------------------------------------
export async function api(method, p, body) {
  const res = await fetch(API + p, {
    method,
    headers: { "content-type": "application/json", ...(KEY ? { "X-Plan-B-Key": KEY } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(`${method} ${p}: HTTP ${res.status} ${JSON.stringify(data?.detail ?? data).slice(0, 300)}`);
  return data;
}
export const state = () => api("GET", "/sim/state");
export async function until(test, { timeout = 120000, every = 700, what = "condition" } = {}) {
  const end = Date.now() + timeout;
  for (;;) {
    const st = await state().catch(() => null);
    const v = st && test(st);
    if (v) return v;
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await sleep(every);
  }
}

// --- cursor overlay (top frame only; a glide + click ripple, nothing else) -----------------------
const CURSOR = String.raw`(() => {
  if (window.top !== window || window.__cur) return;
  const root = document.createElement("div");
  root.id = "pv-root";
  root.innerHTML = '<style>#pv-root{position:fixed;inset:0;pointer-events:none;z-index:2147483646}#pv-c{position:absolute;left:0;top:0;width:26px;height:26px;opacity:0;transform:translate(-100px,-100px);transition-property:transform;transition-timing-function:cubic-bezier(.45,.05,.25,1);filter:drop-shadow(0 2px 3px rgba(0,0,0,.6))}#pv-c.on{opacity:1}#pv-r{position:absolute;left:0;top:0;width:40px;height:40px;margin:-20px 0 0 -20px;border-radius:50%;border:3px solid #4f8ff7;opacity:0}#pv-r.go{animation:pvr .55s ease-out}@keyframes pvr{from{opacity:.95;transform:var(--at) scale(.3)}to{opacity:0;transform:var(--at) scale(1.5)}}</style>' +
    '<div id="pv-r"></div><div id="pv-c"><svg width="26" height="26" viewBox="0 0 24 24"><path d="M3.5 2.2v17.2l4.4-4.1 3.1 6.7 2.9-1.3-3-6.6h6.3z" fill="#fff" stroke="#0b0f14" stroke-width="1.5" stroke-linejoin="round"/></svg></div>';
  const mount = () => {
    if (!document.body) return void setTimeout(mount, 30);
    document.body.appendChild(root);
    new MutationObserver(() => { if (document.body.lastElementChild !== root) document.body.appendChild(root); }).observe(document.body, { childList: true });
  };
  mount();
  let pos = { x: -100, y: -100 };
  window.__cur = {
    move(x, y, ms) { const c = root.querySelector("#pv-c"); c.classList.add("on"); c.style.transitionDuration = ms + "ms"; c.style.transform = "translate(" + (x - 4) + "px," + (y - 3) + "px)"; pos = { x, y }; },
    hide() { root.querySelector("#pv-c").classList.remove("on"); },
    ripple() { const r = root.querySelector("#pv-r"); r.style.setProperty("--at", "translate(" + pos.x + "px," + pos.y + "px)"); r.classList.remove("go"); void r.offsetWidth; r.classList.add("go"); },
  };
})();`;

// --- a recorded page -----------------------------------------------------------------------------
export class Rec {
  constructor(take) {
    this.take = take;
    this.dir = path.join(RAW, take);
    fs.rmSync(this.dir, { recursive: true, force: true });
    fs.mkdirSync(this.dir, { recursive: true });
    this.marks = {};
    this.pages = [];
  }
  async launch({ headed = false } = {}) {
    this.browser = await chromium.launch({ headless: !headed, args: ["--hide-scrollbars", "--force-color-profile=srgb"] });
  }
  /** A page (own context) with key + cursor; recording starts with startRec(). */
  async page(name, { width = 1280, height = 720, dpr = 2, mobile = false } = {}) {
    const ctx = await this.browser.newContext({
      viewport: { width, height },
      deviceScaleFactor: dpr,
      isMobile: mobile,
      hasTouch: mobile,
      colorScheme: "dark",
      locale: "en-GB",
      timezoneId: "Europe/Ljubljana",
    });
    await ctx.addInitScript((k) => {
      try {
        if (k) localStorage.setItem("planb.adminKey", k);
        localStorage.setItem("planb.lang", "en");
        localStorage.setItem("planb.lang.field", "en");
      } catch {}
    }, KEY);
    await ctx.addInitScript({ content: CURSOR });
    const page = await ctx.newPage();
    page.on("dialog", (d) => void d.accept().catch(() => undefined));
    page.on("pageerror", (e) => log(`${name} page error:`, e.message));
    const p = { name, ctx, page, width, height, dpr, frames: [], dir: path.join(this.dir, name), cdp: null, n: 0 };
    fs.mkdirSync(p.dir, { recursive: true });
    this.pages.push(p);
    return p;
  }
  async startRec(p) {
    p.cdp = await p.ctx.newCDPSession(p.page);
    p.cdp.on("Page.screencastFrame", async (f) => {
      const file = `${String(p.n++).padStart(6, "0")}.jpg`;
      fs.writeFile(path.join(p.dir, file), Buffer.from(f.data, "base64"), () => undefined);
      p.frames.push({ file, t: f.metadata.timestamp ?? Date.now() / 1000 });
      p.cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }).catch(() => undefined);
    });
    await p.cdp.send("Page.startScreencast", { format: "jpeg", quality: 88, maxWidth: p.width * p.dpr, maxHeight: p.height * p.dpr, everyNthFrame: 1 });
    log(`recording ${p.name}`);
  }
  mark(name) {
    this.marks[name] = Date.now() / 1000;
    log(`mark ${name}`);
  }
  async stopAll() {
    for (const p of this.pages) {
      if (p.cdp) await p.cdp.send("Page.stopScreencast").catch(() => undefined);
    }
    await sleep(500);
    for (const p of this.pages) fs.writeFileSync(path.join(p.dir, "frames.json"), JSON.stringify(p.frames));
    fs.writeFileSync(path.join(this.dir, "marks.json"), JSON.stringify(this.marks, null, 1));
    await this.browser.close().catch(() => undefined);
  }

  // --- interaction helpers (cursor visible) ---
  async find(p, cands, { timeout = 10000, root } = {}) {
    const scope = root ?? p.page;
    const end = Date.now() + timeout;
    for (;;) {
      for (const c of cands) {
        const loc = (typeof c === "function" ? c(scope) : scope.locator(c)).first();
        if (await loc.isVisible().catch(() => false)) return loc;
      }
      if (Date.now() > end) return null;
      await sleep(200);
    }
  }
  async point(p, target, { ms = 600 } = {}) {
    let x, y;
    if (typeof target?.x === "number") ({ x, y } = target);
    else {
      await target.scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => undefined);
      const b = await target.boundingBox();
      if (!b) return null;
      x = b.x + b.width / 2;
      y = b.y + b.height / 2;
    }
    await p.page.evaluate(([x, y, ms]) => window.__cur?.move(x, y, ms), [x, y, ms]).catch(() => undefined);
    await sleep(ms + 60);
    await p.page.mouse.move(x, y);
    return { x, y };
  }
  async click(p, cands, { what = "element", optional = false, timeout = 10000, ms = 600 } = {}) {
    const loc = await this.find(p, cands, { timeout });
    if (!loc) {
      if (optional) return log(`(optional) not found: ${what}`), false;
      throw new Error(`not found: ${what}`);
    }
    const at = await this.point(p, loc, { ms });
    await sleep(200);
    await p.page.evaluate(() => window.__cur?.ripple()).catch(() => undefined);
    if (at) await p.page.mouse.click(at.x, at.y);
    else await loc.click();
    return true;
  }
  async hideCursor(p) {
    await p.page.evaluate(() => window.__cur?.hide()).catch(() => undefined);
  }
}

/** Frames (variable rate, with timestamps) -> constant 30 fps MP4 starting at the first frame. */
export function framesToMp4(dir, out, { fps = 30, end } = {}) {
  const frames = JSON.parse(fs.readFileSync(path.join(dir, "frames.json"), "utf8"));
  if (!frames.length) throw new Error(`no frames in ${dir}`);
  const lines = ["ffconcat version 1.0"];
  for (let i = 0; i < frames.length; i++) {
    const next = i + 1 < frames.length ? frames[i + 1].t : end ?? frames[i].t + 1;
    lines.push(`file '${frames[i].file}'`, `duration ${Math.max(0.001, next - frames[i].t).toFixed(4)}`);
  }
  lines.push(`file '${frames[frames.length - 1].file}'`);
  fs.writeFileSync(path.join(dir, "list.ffconcat"), lines.join("\n"));
  const r = spawnSync(FFMPEG, ["-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", "list.ffconcat", "-vf", `fps=${fps},format=yuv420p`, "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", path.resolve(out)], { cwd: dir, encoding: "utf8" });
  if (r.status !== 0) throw new Error(`ffmpeg frames: ${r.stderr}`);
  return { t0: frames[0].t, n: frames.length };
}
