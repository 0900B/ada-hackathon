/**
 * Record all four showcases one after the other (they share the backend's Simulation world, so
 * never in parallel). Flags are passed through, e.g.:
 *   node media/showcase/record-all.mjs --base https://<frontend-url>
 *   node media/showcase/record-all.mjs --only chaos,tablet
 */
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const SCRIPTS = {
  chaos: "showcase-chaos.mjs",
  tablet: "showcase-vehicle-tablet.mjs",
  crew: "showcase-crew-replan.mjs",
  call: "showcase-112-to-hospital.mjs",
};
const argv = process.argv.slice(2);
const i = argv.findIndex((a) => a === "--only" || a.startsWith("--only="));
let only = Object.keys(SCRIPTS);
if (i >= 0) {
  const v = argv[i].includes("=") ? argv[i].split("=")[1] : argv[i + 1];
  only = v.split(",").map((x) => x.trim());
  argv.splice(i, argv[i].includes("=") ? 1 : 2);
}
const failed = [];
for (const key of only) {
  const file = fileURLToPath(new URL(SCRIPTS[key], import.meta.url));
  console.log(`\n=== ${key}: ${SCRIPTS[key]} ===`);
  const r = spawnSync(process.execPath, [file, ...argv], { stdio: "inherit" });
  if (r.status !== 0) failed.push(key);
}
if (failed.length) {
  console.log(`\nFailed: ${failed.join(", ")}`);
  process.exitCode = 1;
}
