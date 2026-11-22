// Plan B promo scene player.
//
// index.html?cut=promo|bumper|vertical|poster-promo|poster-bumper|poster-vertical
//   Preview: plays in real time, scaled to the window (click to pause, arrow keys to step 1 s).
//   &render=1: no clock; render.mjs calls window.__player.seek(t) for every frame.
//
// Scenes are <section class="scene" data-dur="7"> in a <template id="cut-NAME">. Consecutive scenes
// overlap by FADE seconds (cross-fade). Inside a scene every animation is a paused CSS animation whose
// position comes from --lt (scene-local time, set here) minus --d (its start): see player.css.
// <video data-src="assets/x.webm" data-rate="1" style="--d:0.5"> is seeked to (lt - d) * rate.
// [data-words="1.2"] splits its text into words that appear from 1.2 s, data-step apart.
// .global[data-from][data-to] elements live outside scenes on the cut's own clock.

const FADE = 0.4;

const CUTS = {
  promo: { w: 1920, h: 1080 },
  bumper: { w: 1920, h: 1080 },
  vertical: { w: 1080, h: 1920 },
  "poster-promo": { w: 1920, h: 1080, tpl: "cut-poster-promo" },
  "poster-bumper": { w: 1920, h: 1080, tpl: "cut-poster-bumper" },
  "poster-vertical": { w: 1080, h: 1920, tpl: "cut-poster-vertical" },
};

// Lucide-style icons (stroke 2, 24x24)
const ICONS = {
  wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
  fog: '<path d="M4 14.9A7 7 0 1 1 15.7 8h1.8a4.5 4.5 0 0 1 2.5 8.24"/><path d="M16 17H7"/><path d="M17 21H9"/>',
  closure: '<polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><path d="M7 12h10"/>',
  phone: '<polyline points="16 2 16 8 22 8"/><line x1="22" x2="16" y1="2" y2="8"/><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.8 19.8 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/>',
  mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
  car: '<path d="M5 17H3v-5l2.5-5.5A2 2 0 0 1 7.3 5h9.4a2 2 0 0 1 1.8 1.5L21 12v5h-2"/><path d="M3 12h18"/><circle cx="7" cy="17" r="2"/><circle cx="17" cy="17" r="2"/><path d="M9 17h6"/>',
  route: '<circle cx="6" cy="19" r="3"/><path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"/><circle cx="18" cy="5" r="3"/>',
  sparkles: '<path d="M12 3l1.9 5.8L20 10l-6.1 1.2L12 17l-1.9-5.8L4 10l6.1-1.2z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  user: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><polyline points="16 11 18 13 22 9"/>',
  log: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8M16 17H8M10 9H8"/>',
  stethoscope: '<path d="M4.8 2.3A.3.3 0 1 0 5 2H4a2 2 0 0 0-2 2v5a6 6 0 0 0 6 6 6 6 0 0 0 6-6V4a2 2 0 0 0-2-2h-1a.2.2 0 1 0 .3.3"/><path d="M8 15v1a6 6 0 0 0 6 6 6 6 0 0 0 6-6v-4"/><circle cx="20" cy="10" r="2"/>',
  timer: '<line x1="10" x2="14" y1="2" y2="2"/><line x1="12" x2="15" y1="14" y2="11"/><circle cx="12" cy="14" r="8"/>',
  ambulance: '<path d="M10 10H6M8 8v4"/><path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/><path d="M19 18h2a1 1 0 0 0 1-1v-3.28a1 1 0 0 0-.68-.95l-1.9-.64a1 1 0 0 1-.6-.53L17.5 8.6A1 1 0 0 0 16.6 8H14"/><path d="M8 18h6"/><circle cx="17" cy="18" r="2"/><circle cx="7" cy="18" r="2"/>',
  alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  cpu: '<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2M15 20v2M2 15h2M2 9h2M20 15h2M20 9h2M9 2v2M9 20v2"/>',
  arrow: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
};
const svg = (name) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] ?? ""}</svg>`;

const params = new URLSearchParams(location.search);
const cutName = params.get("cut") || "promo";
const cut = CUTS[cutName] ?? CUTS.promo;
const renderMode = params.has("render");
const poster = cutName.startsWith("poster");
const stage = document.getElementById("stage");
stage.style.width = `${cut.w}px`;
stage.style.height = `${cut.h}px`;
document.body.classList.add(`cut-${cutName}`, cut.w >= cut.h ? "landscape" : "portrait");
const tpl = document.getElementById(cut.tpl ?? `cut-${cutName}`);
stage.appendChild(tpl.content.cloneNode(true));

for (const el of stage.querySelectorAll("[data-icon]")) {
  el.classList.add("icon");
  el.innerHTML = svg(el.dataset.icon);
}
for (const el of stage.querySelectorAll("[data-words]")) {
  const start = Number(el.dataset.words);
  const step = Number(el.dataset.step ?? 0.14);
  const words = el.textContent.trim().split(/\s+/);
  el.innerHTML = words.map((w, i) => `<span class="a-word" style="--d:${(start + i * step).toFixed(3)}">${w}</span>`).join(" ");
}
for (const el of stage.querySelectorAll(".wave")) {
  el.innerHTML = Array.from({ length: Number(el.dataset.bars ?? 14) }, (_, i) => `<i style="--w:${(-i * 0.13).toFixed(2)}"></i>`).join("");
}

// Scene timing: sequential with a cross-fade overlap
const scenes = [...stage.querySelectorAll(".scene")];
let t = 0;
for (const s of scenes) {
  const dur = Number(s.dataset.dur ?? 5);
  s._start = t;
  s._end = t + dur;
  t += dur - FADE;
}
const total = scenes.length ? scenes[scenes.length - 1]._end : 1;
const globals = [...stage.querySelectorAll(".global")].map((g) => {
  g._from = Number(g.dataset.from ?? 0);
  g._to = g.dataset.to === "end" || g.dataset.to == null ? total : Number(g.dataset.to);
  return g;
});

const videos = [...stage.querySelectorAll("video")];
for (const v of videos) {
  v.muted = true;
  v.playsInline = true;
  v.preload = "auto";
  v.src = v.dataset.src;
}

const clamp01 = (x) => Math.max(0, Math.min(1, x));
const fade = (T, a, b, first, last) => (first ? 1 : clamp01((T - a) / FADE)) * (last ? 1 : clamp01((b - T) / FADE));

function seekVideo(v, lt) {
  const d = Number(getComputedStyle(v).getPropertyValue("--d") || v.dataset.d || 0);
  const rate = Number(v.dataset.rate ?? 1);
  const from = Number(v.dataset.from ?? 0);
  let vt = from + Math.max(0, lt - d) * rate;
  const dur = v.duration || 0;
  if (dur) vt = v.dataset.loop != null ? vt % dur : Math.min(vt, dur - 0.05);
  if (Math.abs(v.currentTime - vt) < 0.002) return null;
  if (!renderMode && v.seeking) return null;
  return new Promise((resolve) => {
    const done = () => resolve();
    v.addEventListener("seeked", done, { once: true });
    setTimeout(done, 1500);
    v.currentTime = vt;
  });
}

async function seek(T) {
  const waits = [];
  scenes.forEach((s, i) => {
    const visible = T >= s._start - 1e-6 && T <= s._end + 1e-6;
    s.style.display = visible ? "" : "none";
    if (!visible) return;
    const lt = T - s._start;
    s.style.setProperty("--lt", lt.toFixed(4));
    // The first scene starts at full opacity (no black first frame); the last one fades out at the end
    s.style.opacity = poster ? "1" : String(fade(T, s._start, s._end, i === 0, false));
    for (const v of s.querySelectorAll("video")) {
      const p = seekVideo(v, lt);
      if (p) waits.push(p);
    }
  });
  for (const g of globals) {
    const visible = T >= g._from && T <= g._to;
    g.style.display = visible ? "" : "none";
    if (!visible) continue;
    g.style.setProperty("--lt", (T - g._from).toFixed(4));
    g.style.opacity = String(fade(T, g._from, g._to, g._from === 0, g._to >= total));
  }
  if (renderMode) {
    await Promise.all(waits);
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  }
}

/**
 * Crops that follow the captured UI (assets/layout.json, written by capture-assets.mjs):
 *   <img data-layout="panel-options.jpg" data-align="option:40">   puts the option's top 40 px into the frame
 *   <img ... data-pan="waiting:60,approve:1080">                    sets --y0/--y1 for .a-pan between two anchors
 *   <div class="hl" data-box="approve" data-pad="10">               sized around that anchor in the same frame
 */
async function applyLayout() {
  const layout = await fetch("assets/layout.json").then((r) => r.json()).catch(() => ({}));
  const anchor = (img, spec) => {
    const [key, at] = spec.split(":");
    const info = layout[img.dataset.layout];
    const box = info?.boxes?.[key];
    if (!box) return null;
    const k = img.offsetWidth / info.width;
    return { k, box, at: Number(at) };
  };
  for (const img of stage.querySelectorAll("img[data-layout]")) {
    if (img.dataset.align) {
      const a = anchor(img, img.dataset.align);
      if (a) img.style.top = `${(a.at - a.box.y * a.k).toFixed(1)}px`;
    }
    if (img.dataset.pan) {
      const [from, to] = img.dataset.pan.split(",").map((s) => anchor(img, s));
      if (from) img.style.setProperty("--y0", `${(from.at - from.box.y * from.k).toFixed(1)}px`);
      if (to) img.style.setProperty("--y1", `${(to.at - to.box.y * to.k).toFixed(1)}px`);
    }
  }
  for (const hl of stage.querySelectorAll("[data-box]")) {
    const img = hl.closest(".frame")?.querySelector("img[data-layout]");
    const info = img && layout[img.dataset.layout];
    const box = info?.boxes?.[hl.dataset.box];
    if (!box) {
      hl.style.display = "none";
      continue;
    }
    const k = img.offsetWidth / info.width;
    const pad = Number(hl.dataset.pad ?? 10);
    const top = parseFloat(img.style.top || "0");
    const left = parseFloat(img.style.left || "0");
    Object.assign(hl.style, {
      left: `${(left + box.x * k - pad).toFixed(1)}px`,
      top: `${(top + box.y * k - pad).toFixed(1)}px`,
      width: `${(box.w * k + 2 * pad).toFixed(1)}px`,
      height: `${(box.h * k + 2 * pad).toFixed(1)}px`,
    });
  }
}

async function ready() {
  await applyLayout();
  await document.fonts.ready;
  await Promise.all([...stage.querySelectorAll("img")].map((img) => img.decode().catch(() => undefined)));
  await Promise.all(
    videos.map((v) =>
      v.readyState >= 2 ? undefined : new Promise((r) => { v.addEventListener("loadeddata", r, { once: true }); v.addEventListener("error", r, { once: true }); }),
    ),
  );
}

window.__player = { cut: cutName, size: cut, total, seek, isReady: false };
ready().then(async () => {
  await seek(0);
  window.__player.isReady = true;
  if (renderMode) return;
  // Preview: scale to the window, play in real time, loop
  const fit = () => {
    const k = Math.min(innerWidth / cut.w, innerHeight / cut.h);
    stage.style.transform = `translate(${(innerWidth - cut.w * k) / 2}px, ${(innerHeight - cut.h * k) / 2}px) scale(${k})`;
  };
  fit();
  addEventListener("resize", fit);
  let paused = false;
  let at = Number(params.get("t") ?? 0);
  let last = performance.now();
  addEventListener("click", () => (paused = !paused));
  addEventListener("keydown", (e) => {
    if (e.key === " ") paused = !paused;
    if (e.key === "ArrowRight") at = Math.min(total, at + 1);
    if (e.key === "ArrowLeft") at = Math.max(0, at - 1);
  });
  const loop = (now) => {
    if (!paused) at += (now - last) / 1000;
    last = now;
    if (at > total) at = 0;
    void seek(at);
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
});
