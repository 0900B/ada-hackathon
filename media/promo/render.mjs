// Renders the promo scene player (media/promo/index.html) to MP4, frame by frame, and the posters to PNG.
//
//   node media/promo/render.mjs promo        -> media/out/promo-60s.mp4
//   node media/promo/render.mjs bumper       -> media/out/ad-bumper-15s.mp4
//   node media/promo/render.mjs vertical     -> media/out/ad-vertical-20s.mp4
//   node media/promo/render.mjs posters      -> media/posters/{promo-60s,ad-bumper-15s,ad-vertical-20s}.png
//   node media/promo/render.mjs all          -> all of the above
//   node media/promo/render.mjs serve        -> preview server: http://127.0.0.1:5290/promo/index.html?cut=promo
//   options: --fps=30 --crf=20 --from=0 --to=<s> (render a time range, for checks) --frames=1,12.5 (PNG stills)
//
// Deterministic: the page has no clock in render mode; for every frame we call window.__player.seek(t)
// (CSS animations are paused and positioned by time, videos are seeked and awaited), take a screenshot
// and pipe it to ffmpeg (H.264, yuv420p, +faststart). A frame takes the same time to render no matter
// how slow the machine is, so there are no dropped frames.
import { createRequire } from "node:module";
import { mkdirSync, statSync } from "node:fs";
import { spawn } from "node:child_process";
import path from "node:path";
import { MEDIA, serve } from "./serve.mjs";

const require = createRequire(new URL("../tools/package.json", import.meta.url));
const { chromium } = require("playwright");
const ffmpeg = require("ffmpeg-static");

const OUT = path.join(MEDIA, "out");
const POSTERS = path.join(MEDIA, "posters");

const args = process.argv.slice(2);
const what = args.find((a) => !a.startsWith("--")) ?? "promo";
const opt = (k, d) => {
  const a = args.find((x) => x.startsWith(`--${k}=`));
  return a ? a.slice(k.length + 3) : d;
};
const FPS = Number(opt("fps", 30));
const CRF = Number(opt("crf", 20));

const OUTPUTS = {
  promo: "promo-60s.mp4",
  bumper: "ad-bumper-15s.mp4",
  vertical: "ad-vertical-20s.mp4",
};
const POSTER_FILES = {
  "poster-promo": "promo-60s.png",
  "poster-bumper": "ad-bumper-15s.png",
  "poster-vertical": "ad-vertical-20s.png",
};

async function openCut(browser, base, cut) {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  page.on("pageerror", (e) => console.error("[page]", e.message));
  await page.goto(`${base}/promo/index.html?cut=${cut}&render=1`);
  await page.waitForFunction(() => window.__player?.isReady, null, { timeout: 60000 });
  const size = await page.evaluate(() => window.__player.size);
  await page.setViewportSize({ width: size.w, height: size.h });
  return page;
}

async function renderVideo(browser, base, cut) {
  const page = await openCut(browser, base, cut);
  const total = await page.evaluate(() => window.__player.total);
  const from = Number(opt("from", 0));
  const to = Math.min(total, Number(opt("to", total)));
  const frames = Math.round((to - from) * FPS);
  mkdirSync(OUT, { recursive: true });
  const file = path.join(OUT, from > 0 || to < total ? OUTPUTS[cut].replace(".mp4", `-${from}-${to}.mp4`) : OUTPUTS[cut]);
  const ff = spawn(ffmpeg, [
    "-y", "-loglevel", "error",
    "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "mjpeg", "-i", "-",
    "-c:v", "libx264", "-preset", "slow", "-crf", String(CRF), "-pix_fmt", "yuv420p",
    "-movflags", "+faststart", "-r", String(FPS), file,
  ], { stdio: ["pipe", "inherit", "inherit"] });
  const done = new Promise((resolve, reject) => ff.on("close", (code) => (code === 0 ? resolve() : reject(new Error(`ffmpeg exited ${code}`)))));
  const t0 = Date.now();
  for (let i = 0; i < frames; i++) {
    const t = from + i / FPS;
    await page.evaluate((x) => window.__player.seek(x), t);
    const buf = await page.screenshot({ type: "jpeg", quality: 94 });
    if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once("drain", r));
    if (i % 150 === 0) process.stdout.write(`\r[render] ${cut} ${t.toFixed(1)}/${to.toFixed(1)} s`);
  }
  ff.stdin.end();
  await done;
  await page.close();
  const mb = statSync(file).size / 1e6;
  console.log(`\r[render] ${cut}: ${path.relative(MEDIA, file)} · ${(frames / FPS).toFixed(1)} s · ${mb.toFixed(1)} MB · ${((Date.now() - t0) / 1000).toFixed(0)} s to render`);
  return file;
}

async function stills(browser, base, cut, times) {
  const page = await openCut(browser, base, cut);
  mkdirSync(OUT, { recursive: true });
  for (const t of times) {
    await page.evaluate((x) => window.__player.seek(x), t);
    const file = path.join(OUT, `still-${cut}-${String(t).replace(".", "_")}.png`);
    await page.screenshot({ path: file });
    console.log("[still]", path.relative(MEDIA, file));
  }
  await page.close();
}

async function posters(browser, base) {
  mkdirSync(POSTERS, { recursive: true });
  for (const [cut, name] of Object.entries(POSTER_FILES)) {
    const page = await openCut(browser, base, cut);
    const total = await page.evaluate(() => window.__player.total);
    await page.evaluate((x) => window.__player.seek(x), total - 0.5);
    const file = path.join(POSTERS, name);
    await page.screenshot({ path: file });
    console.log(`[poster] ${path.relative(MEDIA, file)} · ${Math.round(statSync(file).size / 1024)} KB`);
    await page.close();
  }
}

const server = await serve(what === "serve" ? Number(opt("port", 5290)) : 0);
const base = `http://127.0.0.1:${server.address().port}`;
if (what === "serve") {
  console.log(`Preview: ${base}/promo/index.html?cut=promo  (cuts: promo, bumper, vertical, poster-promo, poster-bumper, poster-vertical; &t=12 starts at 12 s)`);
  console.log(`Stills:  ${base}/stills/`);
} else {
  const browser = await chromium.launch();
  try {
    const frames = opt("frames", null);
    if (frames) await stills(browser, base, what, frames.split(",").map(Number));
    else if (what === "posters") await posters(browser, base);
    else if (what === "all") {
      for (const cut of Object.keys(OUTPUTS)) await renderVideo(browser, base, cut);
      await posters(browser, base);
    } else if (OUTPUTS[what]) await renderVideo(browser, base, what);
    else throw new Error(`Unknown cut ${what}: use promo, bumper, vertical, posters, all or serve`);
  } finally {
    await browser.close();
    server.close();
  }
}
