// Renders the 1080x1080 still ads: media/stills/still-*.html -> media/stills/still-*.png
//   node media/stills/render.mjs            (all)
//   node media/stills/render.mjs still-2    (names containing "still-2")
// The stills use real screenshots from media/promo/assets/ (re-capture them with capture-assets.mjs).
import { createRequire } from "node:module";
import { readdirSync, statSync } from "node:fs";
import path from "node:path";
import { MEDIA, serve } from "../promo/serve.mjs";

const require = createRequire(new URL("../tools/package.json", import.meta.url));
const { chromium } = require("playwright");

const DIR = path.join(MEDIA, "stills");
const filter = process.argv[2] ?? "";
const pages = readdirSync(DIR).filter((f) => /^still-.*\.html$/.test(f) && f.includes(filter));

const server = await serve(0);
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();
try {
  for (const name of pages) {
    const page = await browser.newPage({ viewport: { width: 1080, height: 1080 } });
    await page.goto(`${base}/stills/${name}`);
    await page.waitForFunction(() => !document.querySelector("script[data-wait]") || document.body.dataset.ready, null, { timeout: 10000 });
    await page.evaluate(async () => {
      await document.fonts.ready;
      await Promise.all([...document.images].map((i) => i.decode().catch(() => undefined)));
    });
    const out = path.join(DIR, name.replace(".html", ".png"));
    await page.screenshot({ path: out });
    console.log(`[still] stills/${path.basename(out)} · ${Math.round(statSync(out).size / 1024)} KB`);
    await page.close();
  }
} finally {
  await browser.close();
  server.close();
}
