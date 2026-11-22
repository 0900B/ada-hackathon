/**
 * Showcase recorder: scripted Playwright sessions against the real Plan B UI, recorded with
 * Playwright's recordVideo and cut into an MP4 with ffmpeg (ffmpeg-static).
 *
 * What a script gets (see the showcase-*.mjs files for examples):
 *   - an on-screen caption bar (step n/N, text, "Prototype · simulated data" tag),
 *   - a visible mouse cursor that glides to each element before the click, a click ripple,
 *   - a key cap for every hotkey pressed, a "Time-lapse" badge while waiting is sped up,
 *   - intro and outro title cards, a poster PNG made from a hero screenshot,
 *   - API helpers (reset, call stream, state polling) against the backend the frontend uses.
 *
 * Common options (flags or env): --base <frontend URL> (BASE_URL, default http://localhost:5240),
 * --api <backend URL> (API_URL; default: discovered from the frontend's own requests),
 * --out <dir> (default media/out), --headed, --keep-raw, --no-setup (skip the API reset),
 * --gif (also write a short GIF preview).
 */
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import { spawnSync } from "node:child_process";

const require = createRequire(new URL("../tools/package.json", import.meta.url));
const { chromium } = require("playwright");
const FFMPEG = require("ffmpeg-static");

export const MEDIA = fileURLToPath(new URL("..", import.meta.url));
const FONT_DIR = path.join(MEDIA, "assets", "fonts");
const MAX_MB = 24;

// --- options ---------------------------------------------------------------------------------

export function options() {
  const argv = process.argv.slice(2);
  const get = (name) => {
    const i = argv.findIndex((a) => a === `--${name}` || a.startsWith(`--${name}=`));
    if (i < 0) return undefined;
    const a = argv[i];
    if (a.includes("=")) return a.slice(a.indexOf("=") + 1);
    return argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[i + 1] : "true";
  };
  const strip = (u) => (u ? u.replace(/\/+$/, "") : u);
  return {
    base: strip(get("base") ?? process.env.BASE_URL ?? "http://localhost:5240"),
    api: strip(get("api") ?? process.env.API_URL ?? "") || null,
    out: path.resolve(get("out") ?? process.env.OUT_DIR ?? path.join(MEDIA, "out")),
    headed: get("headed") === "true",
    keepRaw: get("keep-raw") === "true",
    setup: get("no-setup") !== "true",
    gif: get("gif") === "true",
  };
}

const log = (...a) => console.log(`[${new Date().toISOString().slice(11, 19)}]`, ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// --- fonts (embedded, so file:// pages need no network and no CORS) ---------------------------

let fontCss = null;
export function interFontCss() {
  if (fontCss) return fontCss;
  const face = (file, range) =>
    `@font-face{font-family:"Inter Variable";font-style:normal;font-display:block;font-weight:100 900;` +
    `src:url(data:font/woff2;base64,${fs.readFileSync(path.join(FONT_DIR, file)).toString("base64")}) format("woff2");unicode-range:${range};}`;
  fontCss =
    face("inter-latin-wght-normal.woff2", "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD") +
    face("inter-latin-ext-wght-normal.woff2", "U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF");
  return fontCss;
}

// --- the overlay injected into the recorded page (top frame only) ----------------------------

const OVERLAY = String.raw`(() => {
  if (window.top !== window || window.__pb) return;
  const css = ${JSON.stringify(`
#pb-root{--pb-l:0px;--pb-r:0px;position:fixed;inset:0;pointer-events:none;z-index:2147483646;font-family:"Inter Variable",Inter,system-ui,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
#pb-root *{box-sizing:border-box}
#pb-capwrap{position:absolute;left:var(--pb-l);right:var(--pb-r);bottom:22px;display:flex;justify-content:center;padding:0 36px}
#pb-cap{display:flex;align-items:center;gap:16px;max-width:1460px;padding:14px 20px 14px 16px;background:rgba(8,12,17,.95);border:1px solid #354253;border-left:4px solid #4f8ff7;border-radius:10px;box-shadow:0 14px 44px rgba(0,0,0,.6);color:#e6ebf1;font-size:25px;font-weight:500;line-height:1.35;letter-spacing:-.005em;transition:opacity .28s ease,transform .28s ease}
#pb-cap.pb-hidden{opacity:0;transform:translateY(14px)}
#pb-cap.pb-swap{opacity:.0;transform:translateY(4px)}
#pb-step{flex:none;font-size:13px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#8cb6ff;background:rgba(79,143,247,.13);border:1px solid rgba(79,143,247,.38);padding:7px 9px;border-radius:6px;font-variant-numeric:tabular-nums}
#pb-step:empty{display:none}
#pb-text b{color:#fff;font-weight:700}
#pb-text q{quotes:"»" "«";color:#ffd9a0;font-weight:600}
#pb-tag{flex:none;align-self:stretch;display:flex;align-items:center;margin-left:6px;padding-left:16px;border-left:1px solid #2c3846;font-size:12px;font-weight:600;letter-spacing:.09em;text-transform:uppercase;color:#7d8a99;line-height:1.3;text-align:left;max-width:150px}
#pb-badge{position:absolute;right:calc(var(--pb-r) + 36px);bottom:108px;display:flex;align-items:center;gap:8px;padding:8px 13px;border-radius:8px;background:rgba(214,162,58,.16);border:1px solid rgba(214,162,58,.55);color:#f2c56a;font-size:14px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;transition:opacity .25s}
#pb-badge i{display:inline-block;width:0;height:0;border-top:7px solid transparent;border-bottom:7px solid transparent;border-left:10px solid #f2c56a;margin-right:-6px}
#pb-badge i+i{margin-right:4px}
#pb-badge.pb-hidden{opacity:0}
#pb-key{position:absolute;left:calc(var(--pb-l) + 36px);bottom:108px;display:flex;align-items:center;gap:14px;padding:10px 16px 10px 10px;border-radius:12px;background:rgba(8,12,17,.95);border:1px solid #354253;box-shadow:0 10px 30px rgba(0,0,0,.5);color:#e6ebf1;font-size:20px;font-weight:600;transition:opacity .25s,transform .25s}
#pb-key.pb-hidden{opacity:0;transform:translateY(10px)}
#pb-key kbd{display:inline-grid;place-items:center;min-width:52px;height:52px;padding:0 12px;border-radius:9px;background:linear-gradient(#2a3442,#1a222c);border:1px solid #4a5a6e;border-bottom-width:4px;color:#fff;font:700 26px/1 "Inter Variable",Inter,system-ui,sans-serif}
#pb-key.pb-press kbd{transform:translateY(2px);border-bottom-width:2px}
#pb-cursor{position:absolute;left:0;top:0;width:30px;height:30px;transform:translate(-100px,-100px);transition-property:transform;transition-timing-function:cubic-bezier(.45,.05,.25,1);opacity:0;filter:drop-shadow(0 2px 3px rgba(0,0,0,.6))}
#pb-cursor.pb-on{opacity:1}
#pb-ripple{position:absolute;left:0;top:0;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;border:3px solid #4f8ff7;opacity:0}
#pb-ripple.pb-go{animation:pbRipple .55s ease-out}
@keyframes pbRipple{from{opacity:.95;transform:var(--pb-at) scale(.3)}to{opacity:0;transform:var(--pb-at) scale(1.5)}}
#pb-card{position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;padding:0 150px;background:radial-gradient(1200px 700px at 18% 40%,rgba(37,99,235,.20),transparent 60%),linear-gradient(180deg,#0b0f14,#070a0e);color:#e6ebf1;transition:opacity .6s ease}
#pb-card.pb-hidden{opacity:0}
#pb-card .pb-mark{display:flex;align-items:center;gap:18px;font-size:34px;font-weight:700;letter-spacing:-.01em}
#pb-card .pb-mark:before{content:"";width:7px;height:44px;border-radius:3px;background:#4f8ff7}
#pb-card .pb-mark span{font-weight:500;color:#8f9cab;font-size:22px;margin-left:6px}
#pb-card h1{margin:34px 0 0;font-size:86px;line-height:1.04;font-weight:750;letter-spacing:-.025em;max-width:1500px}
#pb-card p{margin:26px 0 0;font-size:32px;line-height:1.35;color:#aab6c4;max-width:1400px;font-weight:450}
#pb-card .pb-foot{position:absolute;left:150px;right:150px;bottom:70px;display:flex;justify-content:space-between;gap:30px;font-size:18px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:#6f7c8b}
#pb-card .pb-pill{display:inline-block;margin-top:30px;padding:9px 14px;border-radius:8px;border:1px solid #354253;color:#8cb6ff;font-size:17px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;width:max-content}
`)};
  const root = document.createElement("div");
  root.id = "pb-root";
  root.innerHTML =
    "<style>" + css + "</style>" +
    '<div id="pb-capwrap"><div id="pb-cap" class="pb-hidden"><span id="pb-step"></span><span id="pb-text"></span><span id="pb-tag"></span></div></div>' +
    '<div id="pb-badge" class="pb-hidden"><i></i><i></i>Time-lapse</div>' +
    '<div id="pb-key" class="pb-hidden"><kbd></kbd><span></span></div>' +
    '<div id="pb-ripple"></div>' +
    '<div id="pb-cursor"><svg width="30" height="30" viewBox="0 0 24 24"><path d="M3.5 2.2v17.2l4.4-4.1 3.1 6.7 2.9-1.3-3-6.6h6.3z" fill="#fff" stroke="#0b0f14" stroke-width="1.5" stroke-linejoin="round"/></svg></div>' +
    '<div id="pb-card" class="pb-hidden"></div>';
  const $ = (id) => root.querySelector("#" + id);
  const mount = () => {
    if (!document.body) return void setTimeout(mount, 30);
    document.body.appendChild(root);
    // stay the last child of body, so the overlay is never under the app's own layers
    new MutationObserver(() => {
      if (root.parentNode !== document.body || document.body.lastElementChild !== root) document.body.appendChild(root);
    }).observe(document.body, { childList: true });
  };
  mount();
  let swapTimer = 0;
  let keyTimer = 0;
  let pos = { x: -100, y: -100 };
  window.__pb = {
    area(l, r) {
      root.style.setProperty("--pb-l", (l || 0) + "px");
      root.style.setProperty("--pb-r", (r || 0) + "px");
    },
    caption(html, step, tag) {
      const cap = $("pb-cap");
      const apply = () => {
        $("pb-text").innerHTML = html;
        $("pb-step").textContent = step || "";
        $("pb-tag").textContent = tag || "";
        cap.classList.remove("pb-swap", "pb-hidden");
      };
      clearTimeout(swapTimer);
      if (!html) return void cap.classList.add("pb-hidden");
      if (cap.classList.contains("pb-hidden")) return apply();
      cap.classList.add("pb-swap");
      swapTimer = setTimeout(apply, 230);
    },
    badge(on) { $("pb-badge").classList.toggle("pb-hidden", !on); },
    key(k, label) {
      const box = $("pb-key");
      box.querySelector("kbd").textContent = k;
      box.querySelector("span").textContent = label || "";
      box.classList.remove("pb-hidden");
      box.classList.add("pb-press");
      setTimeout(() => box.classList.remove("pb-press"), 180);
      clearTimeout(keyTimer);
      keyTimer = setTimeout(() => box.classList.add("pb-hidden"), 2200);
    },
    cursor(x, y, ms) {
      const c = $("pb-cursor");
      c.classList.add("pb-on");
      c.style.transitionDuration = (ms || 0) + "ms";
      c.style.transform = "translate(" + (x - 4) + "px," + (y - 3) + "px)";
      pos = { x, y };
    },
    hideCursor() { $("pb-cursor").classList.remove("pb-on"); },
    ripple() {
      const r = $("pb-ripple");
      r.style.setProperty("--pb-at", "translate(" + pos.x + "px," + pos.y + "px)");
      r.style.transform = "translate(" + pos.x + "px," + pos.y + "px)";
      r.classList.remove("pb-go");
      void r.offsetWidth;
      r.classList.add("pb-go");
    },
    card(html) {
      const c = $("pb-card");
      if (html) { c.innerHTML = html; c.classList.remove("pb-hidden"); }
      else c.classList.add("pb-hidden");
    },
  };
})();`;

// --- small helpers ----------------------------------------------------------------------------

/** Make a caption safe for innerHTML, with **bold** and »quotes« support. */
export function fmt(text) {
  const esc = String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/»(.+?)«/g, "<q>$1</q>");
}

function sizeMb(file) {
  return fs.statSync(file).size / 1024 / 1024;
}

function ffmpeg(args, what) {
  const r = spawnSync(FFMPEG, ["-hide_banner", "-loglevel", "error", "-y", ...args], { encoding: "utf8", maxBuffer: 1 << 26 });
  if (r.status !== 0) throw new Error(`ffmpeg (${what}) failed: ${r.stderr || r.error}`);
  return r;
}

export function probeDuration(file) {
  const r = spawnSync(FFMPEG, ["-hide_banner", "-i", file], { encoding: "utf8" });
  const m = /Duration: (\d+):(\d+):([\d.]+)/.exec(r.stderr || "");
  return m ? Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) : null;
}

// --- API -----------------------------------------------------------------------------------------

async function discoverApi(browser, base) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  let found = null;
  page.on("request", (r) => {
    if (found) return;
    const u = r.url();
    const m = /^(https?:\/\/[^?#]*?)\/(?:sim|live)\/(?:state|stream)\b/.exec(u) || /^(https?:\/\/[^?#]*?)\/health(?:$|\?)/.exec(u);
    if (m) found = m[1];
  });
  await page.goto(`${base}/sim`, { waitUntil: "domcontentloaded" }).catch(() => undefined);
  for (let i = 0; i < 100 && !found; i++) await page.waitForTimeout(200);
  await ctx.close();
  if (!found) throw new Error(`Could not find the backend URL from ${base}/sim's requests: pass --api <backend URL>`);
  return found;
}

export function apiClient(url, world = "sim") {
  const call = async (method, p, body) => {
    const res = await fetch(url + p, {
      method,
      headers: { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const err = new Error(`${method} ${p}: HTTP ${res.status} ${JSON.stringify(data?.detail ?? data)}`);
      err.status = res.status;
      throw err;
    }
    return data;
  };
  return {
    url,
    world,
    get: (p) => call("GET", p),
    post: (p, body = {}) => call("POST", p, body),
    state: () => call("GET", `/${world}/state`),
    reset: (scheduledDay = false) => call("POST", `/${world}/admin/reset`, { scheduled_day: scheduledDay }),
    calls: (enabled) => call("POST", `/${world}/admin/calls`, { enabled }),
    scenario: (name) => call("POST", `/${world}/admin/scenario/${name}`, {}),
    call: (body) => call("POST", `/${world}/calls`, body),
    autoAnalyse: (enabled) => call("POST", `/${world}/agent/auto`, { enabled }).catch(() => null),
  };
}

// --- the session ---------------------------------------------------------------------------------

/**
 * Start a recorded session. `stage` (optional) is HTML for a 1920x1080 "stage" page that embeds the
 * app in iframes (phone or tablet frames); without it, the recorded page is the app itself.
 */
export async function startSession({ name, title, subtitle, width = 1920, height = 1080, opts = options(), tag = "Prototype · simulated data", captionArea = [0, 0] }) {
  fs.mkdirSync(opts.out, { recursive: true });
  const rawDir = path.join(opts.out, "raw", name);
  fs.rmSync(rawDir, { recursive: true, force: true });
  fs.mkdirSync(rawDir, { recursive: true });
  const browser = await chromium.launch({ headless: !opts.headed, args: ["--hide-scrollbars", "--force-color-profile=srgb"] });
  const apiUrl = opts.api ?? (await discoverApi(browser, opts.base));
  log(`${name}: frontend ${opts.base} · backend ${apiUrl}`);
  const api = apiClient(apiUrl);
  const ctx = await browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: 1,
    recordVideo: { dir: rawDir, size: { width, height } },
    colorScheme: "dark",
    locale: "en-GB",
    timezoneId: "Europe/Ljubljana",
  });
  await ctx.addInitScript({ content: OVERLAY });
  const s = new Session({ name, title, subtitle, width, height, opts, browser, ctx, api, rawDir, tag, captionArea });
  await s._open();
  return s;
}

export class Session {
  constructor(o) {
    Object.assign(this, o);
    this.cuts = []; // {a, b, f}: video seconds a..b played at f× speed
    this.segStart = null; // start of the current 1× segment (null before begin())
    this.cap = { html: "", step: "" };
    this.stepNo = 0;
    this.stepTotal = 0;
    this.heroShot = null;
    this.capArea = o.captionArea ?? [0, 0]; // [left, right] px kept free of the caption bar
    this.notes = []; // what the recording actually showed (for the report)
  }

  async _open() {
    this.page = await this.ctx.newPage();
    this.t0 = Date.now();
    this.page.on("dialog", (d) => void d.accept().catch(() => undefined)); // confirm() for surge etc.
    this.page.on("pageerror", (e) => log("page error:", e.message));
  }

  now() {
    return (Date.now() - this.t0) / 1000;
  }

  /** Start of the part of the recording that goes into the video. */
  begin() {
    this.segStart = this.now();
  }

  _close(f = 1) {
    if (this.segStart == null) return;
    const b = this.now();
    if (b - this.segStart > 0.05) this.cuts.push({ a: this.segStart, b, f });
    this.segStart = b;
  }

  /** Open a URL (relative to --base) in the recorded page and re-apply the overlay state. */
  async goto(url, { wait = "domcontentloaded" } = {}) {
    const full = /^(https?|file):/.test(url) ? url : `${this.opts.base}${url.startsWith("/") ? "" : "/"}${url}`;
    await this.page.goto(full, { waitUntil: wait });
    await this.page.waitForFunction(() => Boolean(window.__pb), null, { timeout: 15000 });
    await this._restore();
  }

  /** Open a stage page (HTML string) that embeds the app; `{{BASE}}` is replaced with --base. */
  async stage(html, { captionArea = [0, 0] } = {}) {
    const file = path.join(this.rawDir, "stage.html");
    fs.writeFileSync(file, html.replaceAll("{{BASE}}", this.opts.base).replace("/*FONTS*/", interFontCss()));
    this.capArea = captionArea;
    await this.goto(pathToFileURL(file).href);
  }

  frame(selector) {
    return this.page.frameLocator(selector);
  }

  async _restore() {
    await this.page.evaluate(([l, r]) => window.__pb.area(l, r), this.capArea);
    if (this.cap.html) await this.page.evaluate(([h, s, t]) => window.__pb.caption(h, s, t), [this.cap.html, this.cap.step, this.tag]);
  }

  async _pb(fn, ...args) {
    try {
      await this.page.evaluate(([f, a]) => window.__pb?.[f]?.(...a), [fn, args]);
    } catch {
      /* navigation in progress: the next goto restores the overlay */
    }
  }

  /** Set the caption (supports **bold** and »quotes«). */
  async say(text, { step } = {}) {
    this.cap = { html: text ? fmt(text) : "", step: step ?? this.cap.step };
    log(`caption: ${text}`);
    await this._pb("caption", this.cap.html, this.cap.step, this.tag);
  }

  async hold(ms) {
    await this.page.waitForTimeout(ms);
  }

  /** Title card over the page (intro/outro). */
  async card({ title, text, pill, foot = ["AdaHack 2026 · Epilog Challenge 3", "Ljubljana Demo EMS (fictional) · simulated fleet and calls"] }) {
    const html =
      `<div class="pb-mark">Plan B<span>AI dispatch co-pilot</span></div>` +
      (title ? `<h1>${fmt(title)}</h1>` : "") +
      (text ? `<p>${fmt(text)}</p>` : "") +
      (pill ? `<div class="pb-pill">${fmt(pill)}</div>` : "") +
      `<div class="pb-foot"><span>${fmt(foot[0] ?? "")}</span><span>${fmt(foot[1] ?? "")}</span></div>`;
    await this._pb("card", html);
  }

  async hideCard() {
    await this._pb("card", "");
  }

  /** Find the first visible match among candidate locators (functions of the page or frame). */
  async find(cands, { timeout = 10000, root } = {}) {
    const list = Array.isArray(cands) ? cands : [cands];
    const scope = root ?? this.page;
    const until = Date.now() + timeout;
    for (;;) {
      for (const c of list) {
        const loc = (typeof c === "function" ? c(scope) : scope.locator(c)).first();
        if (await loc.isVisible().catch(() => false)) return loc;
      }
      if (Date.now() > until) return null;
      await sleep(250);
    }
  }

  /** Glide the visible cursor to an element (or {x, y}). */
  async point(target, { ms = 650 } = {}) {
    let x, y;
    if (target && typeof target.x === "number") ({ x, y } = target);
    else {
      await target.scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => undefined);
      const box = await target.boundingBox();
      if (!box) return null;
      x = box.x + box.width / 2;
      y = box.y + box.height / 2;
    }
    await this._pb("cursor", x, y, ms);
    await sleep(ms + 60);
    await this.page.mouse.move(x, y);
    return { x, y };
  }

  /** Move to and click the first visible candidate. Returns false when `optional` and not found. */
  async click(cands, { what = "element", optional = false, timeout = 10000, root, pause = 250 } = {}) {
    const loc = await this.find(cands, { timeout, root });
    if (!loc) {
      if (optional) {
        log(`(optional) not found: ${what}`);
        return false;
      }
      throw new Error(`Not found: ${what}`);
    }
    const at = await this.point(loc);
    await sleep(pause);
    await this._pb("ripple");
    if (at) await this.page.mouse.click(at.x, at.y);
    else await loc.click();
    return true;
  }

  /** Click a field and type into it, key by key. */
  async type(cands, text, { what = "field", delay = 42, root } = {}) {
    const loc = await this.find(cands, { root });
    if (!loc) throw new Error(`Not found: ${what}`);
    await this.point(loc);
    await this._pb("ripple");
    await loc.click();
    await loc.fill("");
    await loc.pressSequentially(text, { delay });
  }

  /** Press a key with an on-screen key cap. `focus`: a locator to focus first (e.g. in an iframe). */
  async key(k, label, { focus } = {}) {
    await this._pb("key", k.length === 1 ? k.toUpperCase() : k, label);
    await sleep(350);
    if (focus) await focus.press(k);
    else await this.page.keyboard.press(k);
  }

  /** Poll the backend state until `test(state)` returns a truthy value (returned). */
  async until(test, { timeout = 120000, every = 800, what = "condition" } = {}) {
    const until = Date.now() + timeout;
    for (;;) {
      const st = await this.api.state().catch(() => null);
      const v = st && test(st);
      if (v) return v;
      if (Date.now() > until) throw new Error(`Timed out waiting for ${what}`);
      await sleep(every);
    }
  }

  /** Speed up a wait: whatever `fn` waits for plays back in about `show` seconds. */
  async timelapse(fn, { show = 6, badge = true } = {}) {
    this._close(1);
    const a = this.now();
    if (badge) await this._pb("badge", true);
    let result;
    try {
      result = await fn();
    } finally {
      if (badge) await this._pb("badge", false);
    }
    const b = this.now();
    const f = Math.max(1, (b - a) / show);
    this.cuts.push({ a, b, f });
    this.segStart = b;
    log(`time-lapse ${(b - a).toFixed(1)} s -> ${((b - a) / f).toFixed(1)} s (${f.toFixed(1)}x)`);
    return result;
  }

  /** Leave a wait out of the video entirely (e.g. a page load). */
  async skip(fn) {
    this._close(1);
    const result = await fn();
    this.segStart = this.now();
    return result;
  }

  /** Screenshot without the overlay, used for the poster (and as a still). */
  async hero() {
    const file = path.join(this.rawDir, "hero.png");
    // The overlay is hidden while the screenshot is taken: cut that moment out of the video, with a
    // margin on both sides (the video's clock and ours differ by a fraction of a second).
    const recording = this.segStart != null;
    if (recording) {
      const a = this.now() - 0.5;
      if (a - this.segStart > 0.05) this.cuts.push({ a: this.segStart, b: a, f: 1 });
      this.segStart = null;
    }
    await this.page.screenshot({ path: file, style: "#pb-root{visibility:hidden!important}" });
    await sleep(1000);
    if (recording) this.segStart = this.now();
    this.heroShot = file;
    log("hero screenshot taken");
  }

  /**
   * Run the steps: [{ say, run, hold }]. `say` is the caption (string or function of the session),
   * `run` an async function, `hold` ms to stay on the step after `run` (default 3500).
   */
  async steps(list) {
    this.stepTotal = list.length;
    for (const [i, st] of list.entries()) {
      this.stepNo = i + 1;
      const step = `${i + 1}/${list.length}`;
      if (st.say) await this.say(typeof st.say === "function" ? await st.say(this) : st.say, { step });
      else this.cap.step = step;
      if (st.run) await st.run(this);
      await this.hold(st.hold ?? 3500);
    }
  }

  /** Close the recording, cut the MP4, write the poster. Returns {mp4, poster, seconds, mb}. */
  async finish({ poster } = {}) {
    this._close(1);
    const video = this.page.video();
    await this.ctx.close();
    const raw = await video.path();
    const outFile = path.join(this.opts.out, `${this.name}.mp4`);
    const seconds = encodeCuts(raw, this.cuts, outFile);
    const mb = sizeMb(outFile);
    log(`${outFile}: ${seconds.toFixed(1)} s, ${mb.toFixed(1)} MB`);
    let posterFile = null;
    if (poster) {
      posterFile = path.join(MEDIA, "posters", `${this.name}.png`);
      await renderPoster(this.browser, { shot: this.heroShot ?? (await frameAt(outFile, seconds * 0.6, this.rawDir)), out: posterFile, width: this.width, height: this.height, ...poster });
      log(`poster: ${posterFile}`);
    }
    if (this.opts.gif) gifPreview(outFile, path.join(this.opts.out, `${this.name}.gif`));
    await this.browser.close();
    if (!this.opts.keepRaw) fs.rmSync(this.rawDir, { recursive: true, force: true });
    return { mp4: outFile, poster: posterFile, seconds, mb };
  }

  /** Abort: keep the raw video for debugging. */
  async fail(err) {
    log(`FAILED: ${err?.stack ?? err}`);
    try {
      await this.page.screenshot({ path: path.join(this.rawDir, "failure.png") });
    } catch {
      /* ignore */
    }
    await this.ctx.close().catch(() => undefined);
    await this.browser.close().catch(() => undefined);
    log(`raw video and failure.png kept in ${this.rawDir}`);
    process.exitCode = 1;
  }
}

// --- video -------------------------------------------------------------------------------------

/** Cut and speed up the raw recording per `cuts`, then encode H.264 (yuv420p, faststart). */
export function encodeCuts(raw, cuts, outFile, { fps = 30 } = {}) {
  if (!cuts.length) throw new Error("Nothing recorded (begin() was never called?)");
  const total = cuts.reduce((t, c) => t + (c.b - c.a) / c.f, 0);
  const parts = cuts.map((c, i) => `[s${i}]trim=start=${c.a.toFixed(3)}:end=${c.b.toFixed(3)},setpts=(PTS-STARTPTS)/${c.f.toFixed(5)}[p${i}]`);
  const filter =
    `[0:v]split=${cuts.length}${cuts.map((_, i) => `[s${i}]`).join("")};` +
    parts.join(";") +
    `;${cuts.map((_, i) => `[p${i}]`).join("")}concat=n=${cuts.length}:v=1:a=0,fps=${fps},` +
    `fade=t=in:st=0:d=0.5,fade=t=out:st=${Math.max(0, total - 0.7).toFixed(2)}:d=0.7,format=yuv420p[v]`;
  for (const crf of [21, 24, 27, 30]) {
    ffmpeg(["-i", raw, "-filter_complex", filter, "-map", "[v]", "-c:v", "libx264", "-preset", "slow", "-crf", String(crf), "-movflags", "+faststart", outFile], "encode");
    if (sizeMb(outFile) <= MAX_MB) break;
    log(`${(sizeMb(outFile)).toFixed(1)} MB at CRF ${crf}: re-encoding smaller`);
  }
  return probeDuration(outFile) ?? total;
}

export function frameAt(video, t, dir) {
  const file = path.join(dir, `frame-${Math.round(t * 10)}.png`);
  ffmpeg(["-ss", t.toFixed(2), "-i", video, "-frames:v", "1", file], "frame");
  return file;
}

export function gifPreview(mp4, gif, { start = 4, seconds = 10, width = 640 } = {}) {
  const pal = gif.replace(/\.gif$/, ".palette.png");
  ffmpeg(["-ss", String(start), "-t", String(seconds), "-i", mp4, "-vf", `fps=10,scale=${width}:-1:flags=lanczos,palettegen`, pal], "palette");
  ffmpeg(["-ss", String(start), "-t", String(seconds), "-i", mp4, "-i", pal, "-lavfi", `fps=10,scale=${width}:-1:flags=lanczos[x];[x][1:v]paletteuse`, gif], "gif");
  fs.rmSync(pal, { force: true });
  log(`gif: ${gif}`);
}

// --- poster ------------------------------------------------------------------------------------

/** A poster: the hero screenshot with a title panel (same look as the intro card). */
export async function renderPoster(browser, { shot, out, width = 1920, height = 1080, title, subtitle, kicker = "Real UI showcase", duration, crop }) {
  fs.mkdirSync(path.dirname(out), { recursive: true });
  if (crop) {
    // inset layout: the cropped screenshot framed on the right, the title on the left
    const cropped = shot.replace(/\.png$/, ".crop.png");
    ffmpeg(["-i", shot, "-vf", `crop=${crop.w}:${crop.h}:${crop.x}:${crop.y}`, cropped], "crop");
    const cimg = `data:image/png;base64,${fs.readFileSync(cropped).toString("base64")}`;
    const iw = Math.min(1060, Math.round((crop.w / crop.h) * 760));
    return posterPage(browser, out, width, height, `
  .shot{position:absolute;right:80px;top:50%;width:${iw}px;transform:translateY(-50%);border-radius:18px;box-shadow:0 40px 100px rgba(0,0,0,.7),0 0 0 1px #2c3846}
  .shade{position:absolute;inset:0;background:radial-gradient(900px 700px at 72% 50%,rgba(37,99,235,.16),transparent 70%)}
  .txt{width:${width - iw - 80 - 110 - 60}px}`, `<div class="shade"></div><img class="shot" src="${cimg}">`, { title, subtitle, kicker, duration });
  }
  const img = `data:image/png;base64,${fs.readFileSync(shot).toString("base64")}`;
  return posterPage(browser, out, width, height, `.shot{position:absolute;inset:0;background:url(${img}) center/cover no-repeat}`, `<div class="shot"></div><div class="shade"></div>`, { title, subtitle, kicker, duration });
}

async function posterPage(browser, out, width, height, extraCss, layers, { title, subtitle, kicker, duration }) {
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>${interFontCss()}
  *{box-sizing:border-box}html,body{margin:0;width:${width}px;height:${height}px;overflow:hidden;background:#0b0f14}
  body{font-family:"Inter Variable",Inter,system-ui,sans-serif;color:#e6ebf1;-webkit-font-smoothing:antialiased}
  .shade{position:absolute;inset:0;background:linear-gradient(90deg,rgba(7,10,14,.97) 0%,rgba(7,10,14,.93) 34%,rgba(7,10,14,.55) 56%,rgba(7,10,14,.08) 78%)}
  .txt{position:absolute;left:110px;top:0;bottom:0;width:860px;display:flex;flex-direction:column;justify-content:center}
  .mark{display:flex;align-items:center;gap:16px;font-size:30px;font-weight:700}
  .mark:before{content:"";width:7px;height:40px;border-radius:3px;background:#4f8ff7}
  .mark span{font-weight:500;color:#8f9cab;font-size:21px}
  .kick{margin-top:40px;font-size:17px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#8cb6ff}
  h1{margin:16px 0 0;font-size:76px;line-height:1.04;font-weight:760;letter-spacing:-.025em}
  p{margin:24px 0 0;font-size:28px;line-height:1.38;color:#aab6c4}
  .meta{margin-top:36px;display:flex;gap:12px;flex-wrap:wrap}
  .meta span{padding:8px 13px;border-radius:8px;border:1px solid #354253;background:rgba(17,22,29,.8);font-size:16px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:#9aa8b8}
  .play{position:absolute;right:120px;bottom:110px;width:120px;height:120px;border-radius:50%;background:rgba(37,99,235,.92);box-shadow:0 18px 50px rgba(0,0,0,.55);display:grid;place-items:center}
  .play:after{content:"";margin-left:10px;border-top:26px solid transparent;border-bottom:26px solid transparent;border-left:40px solid #fff}
  ${extraCss}
  </style></head><body>${layers}
  <div class="txt"><div class="mark">Plan B <span>AI dispatch co-pilot</span></div><div class="kick">${fmt(kicker)}</div>
  <h1>${fmt(title)}</h1>${subtitle ? `<p>${fmt(subtitle)}</p>` : ""}
  <div class="meta">${duration ? `<span>${fmt(duration)}</span>` : ""}<span>Prototype · simulated data</span><span>AdaHack 2026 · Epilog Challenge 3</span></div></div>
  <div class="play"></div></body></html>`;
  const tmp = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "planb-poster-")), "poster.html");
  fs.writeFileSync(tmp, html);
  const page = await browser.newPage({ viewport: { width, height } });
  await page.goto(pathToFileURL(tmp).href);
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: out });
  await page.close();
}

export { sleep, log };
