# Plan B: promo, ads and showcase videos

Videos for promotion, social posts and as a fallback if the live demo fails. Sources live here;
rendered videos go to `media/out/` (git-ignored, regenerate them with the commands below).

Everything shows the prototype honestly: a fictional operator ("Ljubljana Demo EMS"), a simulated
fleet and simulated calls. Claude understands, triages and proposes; the deterministic engine computes
every number; the dispatcher decides. No benchmark numbers are used; if you add any, say "in
simulation" with them (see `docs/BENCHMARK.md`, "Limits").

```
media/
  tools/        Playwright + ffmpeg-static (npm), isolated from the app
  showcase/     scripted real-UI recordings (lib.mjs, ui.mjs, showcase-*.mjs)
  promo/        the animated scene player for the promo and the two ads, its renderer, captured assets
  stills/       1080x1080 still ads (HTML sources + PNG)
  posters/      thumbnails/posters (PNG) for every video
  assets/fonts/ Inter (OFL), embedded into generated pages
  out/          rendered MP4s (git-ignored)
```

## One-time setup

```sh
cd media/tools
npm install
npx playwright install chromium
```

## Run the app locally (for recording)

Two terminals, from the repository root (any free ports; the scripts default to 5240):

```sh
# backend (no ANTHROPIC_API_KEY locally: AI features fall back to the engine and the keyword rules)
cd backend && PORT=8040 PYTHONIOENCODING=utf-8 python -m app
# frontend
cd frontend && npm install && VITE_API_URL=http://localhost:8040 npm run dev -- --port 5240 --strictPort
```

## What gets rendered

| File (in `media/out/`) | Format | Length | Poster (`media/posters/`) |
|---|---|---|---|
| `promo-60s.mp4` | 1920x1080 | 60 s | `promo-60s.png` |
| `ad-bumper-15s.mp4` | 1920x1080 | 15 s | `ad-bumper-15s.png` |
| `ad-vertical-20s.mp4` | 1080x1920 | 20 s | `ad-vertical-20s.png` |
| `showcase-112-to-hospital.mp4` | 1920x1080 | ~100 s | `showcase-112-to-hospital.png` |
| `showcase-crew-replan.mp4` | 1920x1080 | ~60 s | `showcase-crew-replan.png` |
| `showcase-vehicle-tablet.mp4` | 1920x1080 | ~53 s | `showcase-vehicle-tablet.png` |
| `showcase-chaos.mp4` | 1920x1080 | ~73 s | `showcase-chaos.png` |

Still ads (1080x1080, committed): `media/stills/still-1-kaos.png`, `still-2-crew.png`,
`still-3-control.png`. All MP4s are H.264, yuv420p, `+faststart`, under 25 MB.

## Promo and ads (animated scene player)

`media/promo/index.html` is a timed scene player (CSS animations, large type, real screenshots and
short real-UI clips from `media/promo/assets/`). One page holds every cut:
`?cut=promo | bumper | vertical | poster-promo | poster-bumper | poster-vertical`.
`render.mjs` renders it deterministically: for each frame it seeks the player to time t (paused CSS
animations, seeked clips), takes a screenshot and pipes it to ffmpeg, so no frame is ever dropped.

```sh
node media/promo/render.mjs promo      # -> media/out/promo-60s.mp4
node media/promo/render.mjs bumper     # -> media/out/ad-bumper-15s.mp4
node media/promo/render.mjs vertical   # -> media/out/ad-vertical-20s.mp4
node media/promo/render.mjs posters    # -> media/posters/promo-60s.png, ad-bumper-15s.png, ad-vertical-20s.png
node media/promo/render.mjs all        # everything, about 6 minutes
node media/promo/render.mjs serve      # preview: http://127.0.0.1:5290/promo/index.html?cut=promo (&t=30 to jump)
node media/stills/render.mjs           # the three 1080x1080 still ads
```

Re-capture the real-UI screenshots and clips the promo uses (drives the UI only; resets and stages
the Simulation world, so not while someone presents from that backend):

```sh
node media/promo/capture-assets.mjs http://localhost:5240
node media/promo/capture-assets.mjs https://<your-frontend-url>
node media/promo/capture-assets.mjs http://localhost:5240 --only=call,surge,closure,override,crew,audit
```

The crops and highlight boxes in the promo follow `assets/layout.json`, which the capture writes, so a
re-capture against the final UI repositions them as long as the elements still exist (the "Approve
option 1" button, the "Waiting for your decision" line, the call card and its "Dispatched" line).
Then re-render.

## Showcase videos (real UI)

Each script drives the real UI with Playwright (1920x1080, `recordVideo`), injects a caption bar,
a visible cursor with click ripples and key caps for hotkeys, and cuts the recording with ffmpeg
(long waits become a marked time-lapse). Output: `media/out/<name>.mp4` (H.264, yuv420p, faststart,
re-encoded smaller if over 24 MB) and `media/posters/<name>.png`.

| Video | Command | Length |
|---|---|---|
| a. From 112 call to hospital | `node media/showcase/showcase-112-to-hospital.mjs` | ~100 s |
| b. The crew speaks, Plan B re-plans | `node media/showcase/showcase-crew-replan.mjs` | ~60 s |
| c. In the vehicle (tablet) | `node media/showcase/showcase-vehicle-tablet.mjs` | ~53 s |
| d. Chaos on demand | `node media/showcase/showcase-chaos.mjs` | ~73 s |
| all four, one after the other | `node media/showcase/record-all.mjs` | |

Options (flags, or the environment variable in brackets):

- `--base <url>` (`BASE_URL`): the frontend, default `http://localhost:5240`.
- `--api <url>` (`API_URL`): the backend. Default: discovered from the frontend's own requests.
- `--out <dir>`: default `media/out`.
- `--headed`: watch the browser while it records. `--keep-raw`: keep the raw WebM and stage page in `media/out/raw/`.
- `--no-setup`: don't reset the simulation first (by default each script resets the Simulation world,
  switches the synthetic call stream off and stages what it needs through the API).
- `--gif`: also write a 10 s GIF preview next to the MP4.
- Tablet only: `--unit A2` to film another ambulance.

How long it takes: (a) waits for a whole call (on scene, transport, handover) at the simulation's
speed, about 10 minutes at 5x; (b) about 3 minutes; (c) and (d) about 2 minutes each.

### Against the final UI (tonight's "AI dispatcher" tab)

Run the same commands after pulling the new UI. Where things are is in one file,
`media/showcase/ui.mjs`: every entry is a list of candidates tried in order (role and visible text
first, CSS classes as fallbacks). The calls panel is already looked up as "AI dispatcher", then
"Calls"; the analysis as "Dispatch", then "AI dispatcher". If a button was renamed, add one more
candidate there. The steps of each video are a plain list in its script (`s.steps([...])`: caption,
action, hold time), easy to reorder or retime. Run with `--headed --keep-raw` to see what happens; a
failed run keeps `failure.png` and the raw video in `media/out/raw/<name>/`.

### Against a deployed site

```sh
node media/showcase/showcase-chaos.mjs --base https://<your-frontend-url>
# optional, if discovery fails: --api https://<your-backend-url>
```

The backend URL is read from the frontend's own requests. Note that the scripts **reset the
Simulation world** of that backend (the Live world is never touched): don't run them while someone
is presenting or rehearsing on it. With Claude configured there, scripts (a), (b) and (c) use it like
the dispatcher would: one triage per typed 112 call and, in (b), one message reading and one analysis.
The captions adapt: they say "Claude" only when the backend answered with Claude, otherwise "keyword
rules" or "the engine's own plan".

### Known limits of the local recordings

- No Claude key locally: triage is by the keyword rules, crew messages use the quick-button fallback,
  plans are the engine's own. The captions and the promo say so. Recording against a backend with the
  key shows the AI path (the captions switch automatically).
- No TomTom key locally: a road closure slows the unit instead of drawing an orange detour.
- Headless Chromium has no microphone: nobody speaks in these videos; the Slovenian sentence is shown
  as text.
- Scenario and random outcomes vary between runs (e.g. Priority override may divert A1 from a fall or
  A2 from a serious call); captions are built from whatever the engine did.
- `recordVideo` only captures at device scale 1; the showcases record at 1920x1080, scale 1.

### What the captions claim

Captions that describe a system action are built from the backend's own answer at recording time:
who was dispatched, AI or rules triage, detour or slowdown after a closure, the recommended option,
what was approved, the engine's summary of each failure. Locally there is no TomTom key, so a closure
slows the unit instead of drawing a detour, and the caption says so.
