/**
 * Edit: builds the pitch demo from take A (scenes 1-4, 6) and take B (scene 5).
 *   node media/pitch-video/edit.mjs <takeA> <takeB>
 * -> media/out/pitch-demo.mp4 (labels), media/out/pitch-demo-clean.mp4 (no lower-thirds, no corner
 *    badge), media/out/pitch-demo-poster.png. Audio: media/out/pitch-raw/audio/*.wav (make-audio.sh).
 *
 * Every segment is a stretch of real recording; only waits are sped up, and those carry a "×N" badge.
 * Crops are in CSS pixels of the 1280x720 page (the screencast frames are 1280x720, so K = 1).
 */
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { chromium, FFMPEG, MEDIA, RAW, framesToMp4, log } from "./rec.mjs";

const [A = "a2", B = "b1"] = process.argv.slice(2);
const OUT = path.join(MEDIA, "out");
const WORK = path.join(RAW, "edit");
const AUD = path.join(RAW, "audio");
fs.mkdirSync(WORK, { recursive: true });
const FPS = 30;
const K = Number(process.env.FRAME_SCALE ?? 1); // frame pixels per CSS pixel (the screencast delivers 1x)

function ff(args, what) {
  const r = spawnSync(FFMPEG, ["-hide_banner", "-loglevel", "error", "-y", ...args], { encoding: "utf8", maxBuffer: 1 << 26 });
  if (r.status !== 0) throw new Error(`ffmpeg ${what}: ${r.stderr}`);
}
function dur(file) {
  const r = spawnSync(FFMPEG, ["-hide_banner", "-i", file], { encoding: "utf8" });
  const m = /Duration: (\d+):(\d+):([\d.]+)/.exec(r.stderr);
  return m ? +m[1] * 3600 + +m[2] * 60 + +m[3] : 0;
}

// --- sources --------------------------------------------------------------------------------------
function source(take, page) {
  const dir = path.join(RAW, take, page);
  const mp4 = path.join(RAW, take, `${page}.mp4`);
  const meta = path.join(RAW, take, `${page}.t0.json`);
  if (!fs.existsSync(mp4) || !fs.existsSync(meta)) {
    log(`frames -> ${mp4}`);
    // the screencast sends no frame while the page is still: hold the last frame until the "end" mark
    const marks = JSON.parse(fs.readFileSync(path.join(RAW, take, "marks.json"), "utf8"));
    const r = framesToMp4(dir, mp4, { end: marks.end ? marks.end + 0.5 : undefined });
    fs.writeFileSync(meta, JSON.stringify(r));
  }
  return { mp4, t0: JSON.parse(fs.readFileSync(meta, "utf8")).t0 };
}
const marksA = JSON.parse(fs.readFileSync(path.join(RAW, A, "marks.json"), "utf8"));
const marksB = JSON.parse(fs.readFileSync(path.join(RAW, B, "marks.json"), "utf8"));
const sa = source(A, "dash");
const sb = source(B, "dash");
const sp = source(B, "phone");
const ta = (m, d = 0) => marksA[m] - sa.t0 + d; // seconds into take A's video
const tb = (m, d = 0) => marksB[m] - sb.t0 + d;
const tp = (m, d = 0) => marksB[m] - sp.t0 + d;
const RA = marksA.rects ?? {};
const IA = marksA.info ?? {};
const IB = marksB.info ?? {};

// a 16:9 crop of the right half (map edge + the AI dispatcher panel), placed around a rect's top
const W = 720, H = 405;
const panelCrop = (rect, pad = 14) => ({ x: 1280 - W, y: Math.max(0, Math.min(720 - H, Math.round((rect?.y ?? 180) - pad))), w: W, h: H });
const full = { x: 0, y: 0, w: 1280, h: 720 };

// --- the timeline: [{src, a, b, speed, crop | layout}] ----------------------------------------------
const seg = [];
const add = (o) => seg.push({ speed: 1, crop: full, ...o });
// 1. title over the live map
add({ id: "map", src: "A", a: ta("start", -0.2), b: ta("newcall", 0.3) });
// 2. the 112 call: open the form, the call, typing in sync, classify
add({ id: "form", src: "A", a: ta("newcall", 0.3), b: ta("submit", 0.2), crop: { x: 1280 - W, y: Math.max(0, Math.min(720 - H, Math.round((RA.form?.y ?? 310) - 70))), w: W, h: H } });
add({ id: "result", src: "A", a: ta("submit", 0.2), b: ta("box", 0.3), crop: { x: 1280 - W, y: 720 - H, w: W, h: H } });
add({ id: "box", src: "A", a: ta("box", 0.3), b: ta("claude1", 3.8), crop: panelCrop(RA.box2 ?? RA.box) });
// 3. the crew tablet
add({ id: "tablet", src: "A", a: ta("tablet", -0.6), b: ta("tablet", 9.6) });
// 4. something breaks
add({ id: "fail", src: "A", a: ta("failStart", -0.3), b: ta("dbox", 0.2), crop: RA.target ? { x: 1280 - W, y: Math.max(0, Math.min(720 - H, Math.round(RA.target.y - 40))), w: W, h: H } : full });
add({ id: "dbox", src: "A", a: ta("dbox", 0.2), b: ta("claude2", 3.2), crop: panelCrop(RA.dbox2 ?? RA.dbox) });
add({ id: "dmap", src: "A", a: ta("claude2", 3.2), b: Math.min(ta("mapEnd"), ta("claude2", 8.7)), crop: { x: 240, y: 140, w: 640, h: 360 } });
// 5. the crew speaks (split screen)
const analysisS = tb("options") - tb("pressA");
const lapse = analysisS > 6 ? Math.max(2, Math.round(analysisS / 3.5)) : 1;
add({ id: "crew", src: "B", a: tb("start", 0), b: tb("crewResp", 3), layout: "split" });
add({ id: "crew2", src: "B", a: tb("dashSees", -0.5), b: tb("pressA", 0.6), layout: "split" });
// the analysis and the options: zoomed onto the panel (the phone shows nothing new meanwhile)
const optCrop = { x: 480, y: Math.max(0, Math.min(270, Math.round((marksB.rects?.option?.y ?? 234) - 6))), w: 800, h: 450 };
add({ id: "analyse", src: "B", a: tb("pressA", 0.6), b: tb("options", 0), crop: optCrop, speed: lapse, badge: lapse > 1 ? `×${lapse}` : null });
add({ id: "options", src: "B", a: tb("options", 0), b: tb("pressY", 0.4), crop: optCrop });
add({ id: "approve", src: "B", a: tb("pressY", 0.4), b: tb("approved", 5.5), layout: "split" });
// 6. ER board
add({ id: "er", src: "A", a: ta("er", -0.5), b: marksA.erOpen ? ta("erOpen", 5.5) : ta("end"), crop: { x: 0, y: 0, w: 1060, h: 596 } });
// 7. closing card (a still)
add({ id: "close", card: "close", len: 7.5 });

// output time of each segment, and of a source mark
let tcur = 0;
for (const s of seg) {
  s.len = s.card ? s.len : (s.b - s.a) / s.speed;
  s.t = tcur;
  tcur += s.len;
}
const TOTAL = tcur;
const at = (id, srcT) => {
  const s = seg.find((x) => x.id === id);
  return s.t + (srcT - s.a) / s.speed;
};
const segT = (id) => seg.find((x) => x.id === id).t;
const segEnd = (id) => { const s = seg.find((x) => x.id === id); return s.t + s.len; };
log(seg.map((s) => `${s.id} ${s.t.toFixed(1)}-${(s.t + s.len).toFixed(1)}${s.speed > 1 ? ` x${s.speed}` : ""}`).join(" | "), `TOTAL ${TOTAL.toFixed(1)}`);

// --- Claude timings from the boxes (as shown on screen) -----------------------------------------
const num = (re, txt, dflt) => (re.exec(txt ?? "") ?? [])[1] ?? dflt;
const triageS = num(/Classified\s+Claude\s*·\s*([\d.]+)\s*s/i, IA.box1, null);
const check1S = num(/Claude check\s+Claude\s*·\s*([\d.]+)\s*s/i, IA.box1, null);
const check2S = num(/Claude check\s+Claude\s*·\s*([\d.]+)\s*s/i, IA.box2, null);
const changed2 = /Claude changed it/i.test(IA.box2 ?? "");
const switched = /Switched to|Reassigned/i.test(IA.box2 ?? "");

// --- labels: [text, start, end, small?] ----------------------------------------------------------
const L = [];
const lab = (text, a, b, sub) => L.push({ text, a, b, sub });
lab("112 call in Slovenian", at("form", ta("ring")), at("form", ta("typed")), "simulated call audio");
lab(triageS ? `Claude triages · ${triageS} s` : "Claude triages", at("result", ta("submit", 0.4)), segEnd("result") + 1.2);
lab("Engine dispatches · <0.1 s", segT("box") + 1.3, segT("box") + 4.2);
lab(check1S ? `Claude double-checks · ${check1S} s` : "Claude double-checks", segT("box") + 4.3, segEnd("box"));
lab("Crew tablet: navigation to the patient", segT("tablet") + 0.6, segEnd("tablet") - 0.3);
lab("Unit delayed +10 min", at("fail", ta("inject", -0.5)), segEnd("fail") + 0.4);
const replanEnd = Math.max(segEnd("fail") + 2.9, at("dbox", ta("claude2", 0.3)));
lab(switched ? "AI re-plans instantly" : "Engine re-plans · <0.1 s", segEnd("fail") + 0.5, replanEnd);
lab(changed2 ? `Claude finds a faster unit · ${check2S ?? "?"} s` : `Claude confirms · ${check2S ?? "?"} s`, replanEnd + 0.1, segEnd("dmap") - 0.3);
lab("New scene: T1 carries blood products", segT("crew") + 0.3, at("crew", tb("radio", 0.2)));
lab("Crew reports by voice", at("crew", tb("radio", 0.3)), segEnd("crew"));
lab("Claude weighs complete plans", segT("analyse") - 0.6 > segT("crew2") ? segT("analyse") - 0.6 : segT("analyse"), segEnd("analyse") + 0.4);
lab("Every number from our engine", segT("options") + 0.6, segEnd("options"));
lab("Dispatcher approves · one key", segT("approve"), segEnd("approve") - 0.3);
lab("Hospital sees them coming", segT("er") + 0.5, segEnd("er") - 0.3);

// --- overlay PNGs -----------------------------------------------------------------------------------
const FONT = fs.readFileSync(path.join(MEDIA, "assets", "fonts", "inter-latin-wght-normal.woff2")).toString("base64");
const FONT2 = fs.readFileSync(path.join(MEDIA, "assets", "fonts", "inter-latin-ext-wght-normal.woff2")).toString("base64");
const CSS = `@font-face{font-family:I;font-weight:100 900;src:url(data:font/woff2;base64,${FONT}) format("woff2");unicode-range:U+0000-00FF,U+2000-206F,U+2212,U+00D7}
@font-face{font-family:I;font-weight:100 900;src:url(data:font/woff2;base64,${FONT2}) format("woff2");unicode-range:U+0100-02BA,U+1E00-1EFF}
*{box-sizing:border-box;margin:0}html,body{width:1920px;height:1080px;background:transparent;overflow:hidden;font-family:I,system-ui,sans-serif;color:#fff;-webkit-font-smoothing:antialiased}`;
const pages = {
  label: (t, sub) => `<div style="position:absolute;left:64px;bottom:84px;display:flex;flex-direction:column;align-items:flex-start;gap:10px">
    <div style="display:flex;align-items:center;gap:18px;padding:16px 30px 16px 22px;background:rgba(8,12,17,.94);border-left:8px solid #4f8ff7;border-radius:10px;box-shadow:0 12px 40px rgba(0,0,0,.55);font-size:50px;font-weight:720;letter-spacing:-.01em">${t}</div>
    ${sub ? `<div style="padding:7px 14px;background:rgba(8,12,17,.85);border-radius:7px;font-size:24px;font-weight:600;color:#c9d3de;letter-spacing:.02em">${sub}</div>` : ""}</div>`,
  corner: () => `<div style="position:absolute;right:28px;bottom:26px;padding:9px 16px;background:rgba(8,12,17,.82);border:1px solid #3a4757;border-radius:8px;font-size:22px;font-weight:650;color:#d5dde6;letter-spacing:.02em"><span style="color:#8cb6ff">●</span> Real Claude · simulated fleet</div>`,
  badge: (t) => `<div style="position:absolute;right:28px;top:26px;padding:10px 18px;background:rgba(214,162,58,.95);border-radius:9px;font-size:40px;font-weight:800;color:#1a1204">${t}</div>`,
  title: () => `<div style="position:absolute;inset:0;background:linear-gradient(90deg,rgba(6,9,13,.93) 0%,rgba(6,9,13,.82) 45%,rgba(6,9,13,.25) 80%)"></div>
    <div style="position:absolute;left:120px;top:0;bottom:0;display:flex;flex-direction:column;justify-content:center">
    <div style="display:flex;align-items:center;gap:22px"><div style="width:12px;height:120px;border-radius:5px;background:#4f8ff7"></div>
    <div style="font-size:120px;font-weight:780;letter-spacing:-.03em;line-height:1">Bypass <span style="color:#8f9cab;font-weight:500">—</span> AI dispatcher</div></div>
    <div style="margin-top:34px;margin-left:34px;font-size:40px;font-weight:550;color:#b8c4d1">Real Claude · simulated fleet · Ljubljana</div></div>`,
  close: () => `<div style="position:absolute;inset:0;background:radial-gradient(1200px 700px at 20% 40%,rgba(37,99,235,.25),transparent 60%),linear-gradient(180deg,#0b0f14,#06090d)"></div>
    <div style="position:absolute;left:130px;top:0;bottom:0;display:flex;flex-direction:column;justify-content:center;gap:26px">
    <div style="font-size:92px;font-weight:760;letter-spacing:-.025em;line-height:1.12">AI proposes.<br>Engine computes.<br><span style="color:#8cb6ff">Dispatcher decides.</span></div>
    <div style="margin-top:30px;display:flex;align-items:center;gap:18px;font-size:56px;font-weight:760"><div style="width:10px;height:58px;border-radius:4px;background:#4f8ff7"></div>Bypass</div></div>`,
  splitbg: () => `<div style="position:absolute;inset:0;background:radial-gradient(700px 700px at 82% 45%,rgba(37,99,235,.16),transparent 70%),#06090d"></div>
    <div style="position:absolute;left:1371px;top:39px;width:470px;height:1012px;border-radius:16px;border:4px solid #2c3846;box-shadow:0 30px 80px rgba(0,0,0,.65)"></div>
    <div style="position:absolute;left:30px;top:47px;width:1304px;height:986px;border-radius:10px;border:2px solid #242e3a"></div>`,
};
async function renderPngs(list) {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  for (const { file, html, opaque } of list) {
    await page.setContent(`<!doctype html><html><head><meta charset="utf-8"><style>${CSS}</style></head><body>${html}</body></html>`);
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: file, omitBackground: !opaque });
  }
  await browser.close();
}
const png = (n) => path.join(WORK, `${n}.png`);
const pngList = [
  { file: png("title"), html: pages.title() },
  { file: png("close"), html: pages.close(), opaque: true },
  { file: png("corner"), html: pages.corner() },
  { file: png("splitbg"), html: pages.splitbg(), opaque: true },
  ...L.map((l, i) => ({ file: png(`label${i}`), html: pages.label(l.text, l.sub) })),
  ...seg.filter((s) => s.badge).map((s) => ({ file: png(`badge-${s.id}`), html: pages.badge(s.badge) })),
];
await renderPngs(pngList);

// --- render each segment to 1920x1080 -----------------------------------------------------------------
const srcOf = { A: sa.mp4, B: sb.mp4 };
const segFiles = [];
for (const [i, s] of seg.entries()) {
  const out = path.join(WORK, `seg${String(i).padStart(2, "0")}-${s.id}.mp4`);
  segFiles.push(out);
  const pts = `setpts=(PTS-STARTPTS)/${s.speed}`;
  const enc = ["-r", String(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-an", out];
  if (s.card) {
    ff(["-loop", "1", "-t", s.len.toFixed(3), "-i", png(s.card), "-vf", `fps=${FPS},format=yuv420p`, ...enc], s.id);
  } else if (s.layout === "split") {
    const pa = tp("start") - tb("start"); // phone video offset vs. dashboard video
    const c = { x: 380, y: 40, w: 900, h: 680 };
    const fc =
      `[0:v]trim=start=${s.a.toFixed(3)}:end=${s.b.toFixed(3)},${pts},crop=${c.w * K}:${c.h * K}:${c.x * K}:${c.y * K},scale=1300:982:flags=lanczos[d];` +
      `[1:v]trim=start=${(s.a + pa).toFixed(3)}:end=${(s.b + pa).toFixed(3)},${pts},scale=462:1000:flags=lanczos[p];` +
      `[2:v]fps=${FPS}[bg];[bg][d]overlay=31:48:shortest=1[x];[x][p]overlay=1375:45:shortest=1`;
    ff(["-i", sb.mp4, "-i", sp.mp4, "-loop", "1", "-i", png("splitbg"), "-filter_complex", fc, "-t", s.len.toFixed(3), ...enc], s.id);
  } else {
    const c = s.crop;
    const vf = `trim=start=${s.a.toFixed(3)}:end=${s.b.toFixed(3)},${pts},crop=${c.w * K}:${c.h * K}:${c.x * K}:${c.y * K},scale=1920:1080:flags=lanczos,fps=${FPS}`;
    ff(["-i", srcOf[s.src], "-vf", vf, ...enc], s.id);
  }
  log(`segment ${s.id}: ${dur(out).toFixed(2)} s (planned ${s.len.toFixed(2)})`);
}
// re-time from the real segment lengths
tcur = 0;
for (const [i, s] of seg.entries()) {
  const real = dur(segFiles[i]);
  s.drift = real - s.len;
  tcur += real;
}
const list = path.join(WORK, "segs.txt");
fs.writeFileSync(list, segFiles.map((f) => `file '${f.replace(/\\/g, "/")}'`).join("\n"));
const base = path.join(WORK, "base.mp4");
ff(["-f", "concat", "-safe", "0", "-i", list, "-c", "copy", base], "concat");
const REAL = dur(base);
log(`base ${REAL.toFixed(2)} s`);

// --- audio: ring, caller, crew radio -------------------------------------------------------------
const ringT = at("form", ta("ring"));
const voiceT = at("form", ta("voice"));
const radioT = at("crew", tb("radio"));
const audio = path.join(WORK, "audio.wav");
ff([
  "-i", path.join(AUD, "ring.wav"), "-i", path.join(AUD, "caller_phone.wav"), "-i", path.join(AUD, "crew_radio.wav"),
  "-filter_complex",
  `[0]atrim=0:${Math.max(0.5, voiceT - ringT - 0.15).toFixed(2)},afade=t=out:st=${Math.max(0.3, voiceT - ringT - 0.45).toFixed(2)}:d=0.3,volume=0.55,adelay=${Math.round(ringT * 1000)}[r];` +
  `[1]volume=1.0,adelay=${Math.round(voiceT * 1000)}[v];[2]volume=1.0,adelay=${Math.round(radioT * 1000)}[c];` +
  `[r][v][c]amix=inputs=3:normalize=0:duration=longest,volume=6dB,alimiter=limit=0.95,apad,atrim=0:${REAL.toFixed(3)},aresample=48000[a]`,
  "-map", "[a]", "-ac", "2", audio,
], "audio");

// --- final passes: clean (title + ×N badges) and main (+ labels, corner badge) ----------------------
function finalPass(out, withLabels) {
  const inputs = ["-i", base, "-i", audio];
  const chains = [];
  let last = "[0:v]";
  let n = 2;
  const over = (file, a, b, fade = 0.25) => {
    // only as many frames as the overlay is on screen, shifted to its start
    const len = Math.max(0.2, b - a);
    inputs.push("-loop", "1", "-framerate", String(FPS), "-t", len.toFixed(3), "-i", file);
    const lbl = `o${n}`;
    chains.push(`[${n}:v]format=rgba,fade=t=in:st=0:d=${fade}:alpha=1,fade=t=out:st=${Math.max(0, len - fade).toFixed(2)}:d=${fade}:alpha=1,setpts=PTS+${a.toFixed(3)}/TB[${lbl}]`);
    chains.push(`${last}[${lbl}]overlay=0:0:eof_action=pass[v${n}]`);
    last = `[v${n}]`;
    n++;
  };
  over(png("title"), 0, segEnd("map") - 0.2, 0.4);
  for (const s of seg.filter((x) => x.badge)) over(png(`badge-${s.id}`), s.t, s.t + s.len, 0.15);
  if (withLabels) {
    L.forEach((l, i) => over(png(`label${i}`), l.a, l.b));
    over(png("corner"), segEnd("map"), segT("close"), 0.3);
  }
  chains.push(`${last}fade=t=in:st=0:d=0.4,fade=t=out:st=${(REAL - 0.6).toFixed(2)}:d=0.6,format=yuv420p[vout]`);
  ff([...inputs, "-filter_complex", chains.join(";"), "-map", "[vout]", "-map", "1:a", "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-t", REAL.toFixed(3), out], out);
  log(`${out}: ${dur(out).toFixed(2)} s, ${(fs.statSync(out).size / 1048576).toFixed(1)} MB`);
}
finalPass(path.join(OUT, "pitch-demo-clean.mp4"), false);
finalPass(path.join(OUT, "pitch-demo.mp4"), true);
ff(["-ss", (segT("box") + 6.5).toFixed(2), "-i", path.join(OUT, "pitch-demo.mp4"), "-frames:v", "1", path.join(OUT, "pitch-demo-poster.png")], "poster");

const fmt = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;
const report = {
  total: fmt(REAL),
  scenes: seg.map((s) => `${fmt(s.t)}–${fmt(s.t + s.len)} ${s.id}${s.speed > 1 ? ` (×${s.speed})` : ""}`),
  labels: L.map((l) => `${fmt(l.a)}–${fmt(l.b)} ${l.text}`),
  audio: { ring: fmt(ringT), voice: fmt(voiceT), radio: fmt(radioT) },
  claude: { triageS, check1S, check2S, changed2, analysisS: analysisS.toFixed(1), lapse },
};
fs.writeFileSync(path.join(WORK, "report.json"), JSON.stringify(report, null, 1));
console.log(JSON.stringify(report, null, 1));
