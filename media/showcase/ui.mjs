/**
 * Where things are in the Plan B UI. Every entry is a list of candidates, tried in order, so a
 * renamed tab or button needs one more candidate here, not a change in every script.
 * Candidates are CSS selectors or functions of a Page / FrameLocator returning a Locator.
 */
const rx = (s, flags = "i") => new RegExp(s, flags);
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * Zoom the dashboard map (mouse wheel, cursor visible) around the given markers' midpoint.
 * Each wheel notch of -50 px is one Leaflet zoom level. Returns false if there is no map.
 */
export async function zoomMapAround(s, markerCands, { levels = 2, root } = {}) {
  const map = await s.find(UI.map, { root, timeout: 4000 });
  const mb = map && (await map.boundingBox());
  if (!mb) return false;
  const pts = [];
  for (const c of markerCands) {
    const loc = await s.find(c, { root, timeout: 1500 });
    const b = loc && (await loc.boundingBox());
    if (b) pts.push({ x: b.x + b.width / 2, y: b.y + b.height / 2 });
  }
  const avg = (k) => pts.reduce((t, p) => t + p[k], 0) / pts.length;
  const m = 90;
  const x = Math.min(mb.x + mb.width - m, Math.max(mb.x + m, pts.length ? avg("x") : mb.x + mb.width / 2));
  const y = Math.min(mb.y + mb.height - m, Math.max(mb.y + m, pts.length ? avg("y") : mb.y + mb.height / 2));
  await s.point({ x, y });
  for (let i = 0; i < levels; i++) {
    await s.page.mouse.wheel(0, -50);
    await s.hold(750);
  }
  return true;
}

/**
 * Frame the selected vehicle's highlighted route (the thick polyline): drag the map so the route is
 * centred, then wheel-zoom in as far as it still fits. Cursor visible throughout.
 */
export async function frameRoute(s, { root, maxLevels = 2, fill = 0.72 } = {}) {
  const scope = root ?? s.page;
  const map = await s.find(UI.map, { root, timeout: 4000 });
  const mb = map && (await map.boundingBox());
  if (!mb) return false;
  const paths = scope.locator(".leaflet-overlay-pane path[stroke-width='4']");
  let box = null;
  for (let i = 0, n = await paths.count(); i < n; i++) {
    const b = await paths.nth(i).boundingBox().catch(() => null);
    if (!b || b.width + b.height < 4) continue;
    box = box
      ? { x1: Math.min(box.x1, b.x), y1: Math.min(box.y1, b.y), x2: Math.max(box.x2, b.x + b.width), y2: Math.max(box.y2, b.y + b.height) }
      : { x1: b.x, y1: b.y, x2: b.x + b.width, y2: b.y + b.height };
  }
  if (!box) return false;
  const C = { x: mb.x + mb.width / 2, y: mb.y + mb.height / 2 };
  const P = { x: (box.x1 + box.x2) / 2, y: (box.y1 + box.y2) / 2 };
  const dx = C.x - P.x;
  const dy = C.y - P.y;
  if (Math.hypot(dx, dy) > 30) {
    // grab the map at a point away from the markers' cluster and drag the route to the centre
    const from = { x: Math.min(mb.x + mb.width - 60, Math.max(mb.x + 60, C.x - dx / 2)), y: Math.min(mb.y + mb.height - 60, Math.max(mb.y + 60, C.y - dy / 2 + 90)) };
    await s.point(from);
    await s.page.mouse.down();
    await s.page.evaluate(([x, y]) => window.__pb?.cursor(x, y, 900), [from.x + dx, from.y + dy]);
    await s.page.mouse.move(from.x + dx, from.y + dy, { steps: 24 });
    await s.page.mouse.up();
    await s.hold(700);
  }
  const k = Math.min((mb.width * fill) / Math.max(40, box.x2 - box.x1), (mb.height * fill) / Math.max(40, box.y2 - box.y1));
  const levels = Math.max(0, Math.min(maxLevels, Math.floor(Math.log2(k))));
  await s.point(C, { ms: 450 });
  for (let i = 0; i < levels; i++) {
    await s.page.mouse.wheel(0, -50);
    await s.hold(800);
  }
  return true;
}

/** A side-panel tab by its label (the label may be followed by a badge, e.g. "Calls 3"). */
export const tab = (...names) =>
  names.flatMap((n) => [
    (p) => p.getByRole("tab", { name: rx(`^\\s*${esc(n)}\\b`) }),
    (p) => p.locator(".side-tab", { hasText: rx(`^\\s*${esc(n)}`) }),
  ]);

export const button = (...names) =>
  names.flatMap((n) => [(p) => p.getByRole("button", { name: rx(esc(n)) }), (p) => p.getByText(rx(esc(n)))]);

export const UI = {
  // The panel with the calls. Tonight's UI: "AI dispatcher" replaces "Calls".
  callsTab: tab("AI dispatcher", "Calls"),
  // The AI dispatcher's analysis and options (today's "Dispatch" tab).
  dispatchTab: tab("Dispatch", "AI dispatcher"),
  scenariosTab: tab("Scenarios"),
  eventsTab: tab("Events", "Report"),
  alertsTab: tab("Alerts"),

  newCall: [(p) => p.getByRole("button", { name: /New 112 call/i }), (p) => p.getByText(/New 112 call/i)],
  callWords: ["#call-words", (p) => p.getByLabel(/What the caller says/i), (p) => p.locator("textarea")],
  callAddress: ["#call-address", (p) => p.getByPlaceholder(/Address or place/i), (p) => p.getByLabel(/^Where/i)],
  callerName: [(p) => p.getByLabel(/Caller's name/i), (p) => p.getByPlaceholder(/Caller's name/i)],
  classify: [(p) => p.getByRole("button", { name: /Classify and dispatch/i }), (p) => p.getByRole("button", { name: /Classify|Dispatch call/i })],
  closedCalls: [(p) => p.getByRole("button", { name: /Closed in the last/i }), (p) => p.getByText(/Closed in the last/i)],
  callCard: (callId) => [(p) => p.locator(".call-summary", { hasText: callId }), (p) => p.getByRole("button", { name: rx(esc(callId)) })],

  randomCall: [(p) => p.getByRole("button", { name: /^\s*Random call/i }), (p) => p.locator(".split-main", { hasText: /Random call/i })],
  randomCallMenu: [(p) => p.getByRole("button", { name: /Random call: choose/i })],
  randomFailureMenu: [(p) => p.getByRole("button", { name: /Random failure: choose/i })],
  menuItem: (label) => [(p) => p.getByRole("menuitem", { name: rx(`^\\s*${esc(label)}\\s*$`) }), (p) => p.getByRole("menuitem", { name: rx(esc(label)) })],

  scenario: (label) => [(p) => p.getByRole("button", { name: rx(`^\\s*${esc(label)}`) }), (p) => p.locator(".scenario", { hasText: label })],
  resetSim: [(p) => p.getByRole("button", { name: /Reset simulation/i })],

  analyse: [(p) => p.getByRole("button", { name: /^\s*Analyse/i }), (p) => p.locator("button.analyze")],
  approveRecommended: [(p) => p.locator("button.approve.primary"), (p) => p.getByRole("button", { name: /Approve option/i })],
  recommendedOption: [(p) => p.locator(".option.recommended"), (p) => p.locator(".option").first(), (p) => p.getByText(/Recommended/i)],
  vehicleChip: (id) => [(p) => p.locator(".vchip", { hasText: rx(`^\\s*${esc(id)}\\b`) }), (p) => p.getByRole("toolbar", { name: /Vehicles/i }).getByText(id, { exact: true })],

  fogButton: [(p) => p.getByRole("button", { name: /Fog: ground/i }), (p) => p.getByRole("button", { name: /^\s*Fog/i })],
  surgeButton: [(p) => p.locator("button.surge-button"), (p) => p.getByRole("button", { name: /Activate contracted units/i })],

  vehicleMarker: (id) => [(p) => p.locator(".leaflet-marker-pane .veh-marker", { hasText: rx(`^\\s*${esc(id)}\\s*$`) }), (p) => p.locator(".leaflet-marker-pane .veh-marker", { hasText: id })],
  callMarker: [(p) => p.locator(".leaflet-marker-pane .call-mk")],
  map: [(p) => p.locator(".map-wrap .leaflet-container"), (p) => p.locator(".leaflet-container")],
  kpis: [(p) => p.locator(".kpis"), (p) => p.locator(".statusbar")],

  // Crew phone view (/crew/:id)
  crewQuick: (sl) => [(p) => p.locator(".crew-quick button", { hasText: sl }), (p) => p.getByRole("button", { name: rx(esc(sl)) })],
  crewInput: [(p) => p.getByLabel(/Message to the dispatcher/i), (p) => p.getByPlaceholder(/Sporočilo/i)],
  crewSend: [(p) => p.locator(".crew-form button[type=submit]"), (p) => p.getByRole("button", { name: /^\s*Send/i })],

  // Vehicle tablet (/vehicle/:id)
  navView: (label) => [(p) => p.getByRole("button", { name: rx(`^\\s*${esc(label)}`) }), (p) => p.getByText(rx(`^${esc(label)}$`))],
  acknowledge: [(p) => p.getByRole("button", { name: /Acknowledge/i })],
};
