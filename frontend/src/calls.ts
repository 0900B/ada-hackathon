/**
 * Cases: every trip seen from the 112 call (or hospital request) that started it, followed to the
 * end, as the AI dispatcher handles it. Uses Trip.call, Trip.timeline and Trip.units when the backend
 * sends them; otherwise builds the same view from the trip's own fields, so older backends still show
 * a useful list. Also says, honestly, who did what: Claude, the rules engine, or the dispatcher.
 */
import type { AgentRun, TimelineEntry, Trip, Vehicle, WorldSnapshot } from "./api";
import { compareTrips } from "./severity";

export type CallStatus = "waiting" | "dispatched" | "en route" | "on scene" | "transporting" | "at hospital" | "closed" | "cancelled";

export type Phase = "next" | "to_scene" | "on_scene" | "to_hospital" | "escort" | "done";

export interface CaseUnit {
  id: string;
  role: string; // ambulance | doctor | helicopter | transport
  roleLabel: string; // "Ambulance", "Doctor car", "Helicopter (doctor on board)"
  type: Vehicle["type"] | null;
  name: string;
  phase: Phase;
  step: string; // current step: "En route to the patient"
  eta: string | null; // the next arrival shown: at the patient, or at the hospital once transporting
  etaLabel: string; // "at the patient" | "at UKC"
  progress: number | null; // 0..1 of the current leg (null = unknown)
  reason: string | null; // why this unit (the AI's reason)
  by: string | null; // who assigned it: engine | ai/claude | dispatcher
  source: string; // "Rules engine · 0.1 s", "Claude · 12 s", "Dispatcher"
  assignedAt: string | null;
}

export interface CallView {
  trip: Trip;
  id: string; // call id ("112-0042"), or the trip id on older backends
  kind: "112" | "hospital_request";
  received: string;
  address: string | null;
  caller: string | null;
  textSl: string | null;
  textEn: string | null;
  triageBy: "ai" | "rules" | "dispatcher" | null;
  triageDetail: string | null;
  reasonEn: string | null;
  reasonSl: string | null;
  status: CallStatus;
  units: CaseUnit[];
  timeline: TimelineEntry[];
  closedAt: string | null;
  proposal: AgentRun | null; // a pending AI/engine plan that involves this call
}

const BOOKING = new Set(["transfer", "equipment"]);
const ASSIGN_KINDS = new Set(["dispatched", "reassigned", "unit_replaced", "doctor_dispatched", "override"]);
const INTERVENTIONS = new Set(["override", "reassigned", "unit_replaced", "dispatched", "doctor_dispatched", "rerouted", "approved"]);

/** Who did it, for people: Claude is Claude, the deterministic parts are named as rules. */
export const BY_LABEL: Record<string, string> = {
  caller: "Caller",
  ai: "Claude",
  claude: "Claude",
  rules: "Keyword rules",
  engine: "Rules engine",
  rules_engine: "Rules engine",
  autopilot: "Autopilot",
  dispatcher: "Dispatcher",
  crew: "Crew",
};

/** Short form for the timeline's "who" column. */
export const BY_SHORT: Record<string, string> = {
  caller: "Caller",
  ai: "Claude",
  claude: "Claude",
  rules: "Rules",
  engine: "Engine",
  rules_engine: "Engine",
  autopilot: "Autopilot",
  dispatcher: "Dispatcher",
  crew: "Crew",
};

export const isClaude = (by: string | null | undefined) => by === "ai" || /^claude/i.test(by ?? "");

/** "Rules engine · 0.1 s" from who and the timeline's detail ("rules engine, 0.1 s"). */
export function sourceText(by: string | null | undefined, detail?: string | null): string {
  const who = by ? (BY_LABEL[by] ?? by) : "Rules engine";
  if (!detail) return who;
  const d = detail.trim();
  // the detail usually names the actor already ("rules engine, 0.1 s"): don't say it twice
  if (d.toLowerCase().startsWith(who.toLowerCase()) || (isClaude(by) && /^claude/i.test(d))) return d[0].toUpperCase() + d.slice(1).replace(/,\s*/, " · ");
  if (d.toLowerCase() === "dispatcher") return who;
  return `${who} · ${d}`;
}

export const STEP_LABEL: Record<string, string> = {
  received: "Call received",
  triaged: "Classified",
  dispatched: "Dispatched",
  doctor_dispatched: "Doctor sent",
  rerouted: "Rerouted",
  reassigned: "Reassigned",
  delayed: "Delayed",
  unit_replaced: "Unit replaced",
  proposal: "Proposal",
  approved: "Approved",
  reviewed: "Claude review",
  override: "Override",
  on_scene: "On scene",
  doctor_on_scene: "Doctor on scene",
  transporting: "Transporting",
  at_hospital: "At hospital",
  handover_done: "Handover done",
  closed: "Closed",
  note: "Note",
};

const ROLE_LABEL: Record<string, string> = {
  ambulance: "Ambulance",
  transport: "Transport van",
  helicopter: "Helicopter",
  doctor: "Doctor car",
};

function statusOf(t: Trip, vehicles: Map<string, Vehicle>): CallStatus {
  if (t.status === "cancelled") return "cancelled";
  if (t.status === "completed") return t.timeline?.some((e) => e.kind === "closed") === false ? "at hospital" : "closed";
  if (t.status === "unassigned") return "waiting";
  if (t.status === "onboard") {
    const v = t.vehicle_id ? vehicles.get(t.vehicle_id) : undefined;
    return v && v.status === "with_patient" ? "transporting" : "on scene";
  }
  if (t.status === "en_route_pickup") return "en route";
  return "dispatched";
}

/** The timeline from the trip's own fields (older backends without Trip.timeline). */
function synthTimeline(t: Trip, received: string, place: (id: string) => string): TimelineEntry[] {
  const out: TimelineEntry[] = [{ at: received, kind: "received", by: "caller", text: `Call received: ${t.note ?? t.label}` }];
  if (t.vehicle_id) out.push({ at: t.dispatched_at ?? received, kind: "dispatched", by: "engine", text: `${t.vehicle_id} dispatched`, vehicle_id: t.vehicle_id });
  if (t.doctor_vehicle_id && t.doctor_vehicle_id !== t.vehicle_id)
    out.push({ at: t.dispatched_at ?? received, kind: "doctor_dispatched", by: "engine", text: `Doctor ${t.doctor_vehicle_id} sent`, vehicle_id: t.doctor_vehicle_id });
  if ((t.status === "onboard" || t.status === "completed") && t.eta_pickup)
    out.push({ at: t.eta_pickup, kind: "on_scene", by: "crew", text: `${t.vehicle_id ?? "Unit"} on scene`, vehicle_id: t.vehicle_id });
  if (t.status === "completed" && t.eta_dropoff) {
    out.push({ at: t.eta_dropoff, kind: "at_hospital", by: "crew", text: `At ${place(t.dropoff_id)}`, vehicle_id: t.vehicle_id });
    out.push({ at: t.eta_dropoff, kind: "closed", by: "engine", text: "Closed" });
  }
  return out;
}

/** A plan waiting for the dispatcher that moves this call (the newest one). */
function pendingProposal(t: Trip, runs: AgentRun[]): AgentRun | null {
  for (const run of runs) {
    if (run.status !== "done" || !run.recommendation) continue;
    const rec = run.recommendation;
    const opt = rec.options[rec.recommended_index];
    if (opt && opt.feasible !== false && opt.steps.some((s) => s.trip_id === t.id)) return run;
  }
  return null;
}

/** "Dispatched A1 (nearest free ambulance): at the patient 14:09" -> "Nearest free ambulance · at the patient 14:09". */
export function shortReason(text: string): string {
  const m = /^(?:Dispatched|Re-evaluated: dispatched|Placed on)\s+\S+\s+\(([^)]+)\)(?::\s*(.*))?$/i.exec(text.trim());
  if (!m) return text;
  const why = m[1][0].toUpperCase() + m[1].slice(1);
  const when = m[2] ? m[2].replace(/\s*\(in \d+ min\)/, "").split(",")[0] : "";
  return when ? `${why} · ${when}` : why;
}

const mins = (a: number, b: number) => (a - b) / 60_000;

function unitPhase(t: Trip, v: Vehicle | undefined, role: string): Phase {
  if (t.status === "completed" || t.status === "cancelled") return "done";
  if (!v) return t.status === "onboard" ? "to_hospital" : "to_scene";
  const mine = v.current_trip_id === t.id;
  if (!mine && v.queue.includes(t.id)) return "next";
  if (role === "doctor" && v.type === "doctor") {
    if (v.status === "loading") return "on_scene";
    if (v.status === "with_patient") return "escort";
    return "to_scene";
  }
  if (t.status === "onboard") return v.status === "with_patient" ? "to_hospital" : "on_scene";
  return "to_scene";
}

const PHASE_STEP: Record<Phase, string> = {
  next: "Next: finishing another job first",
  to_scene: "En route to the patient",
  on_scene: "On scene",
  to_hospital: "Transporting",
  escort: "Escorting the ambulance",
  done: "Done",
};

function buildUnit(
  t: Trip,
  vid: string,
  roleIn: string | null | undefined,
  state: WorldSnapshot,
  vehicles: Map<string, Vehicle>,
  timeline: TimelineEntry[],
  place: (id: string) => string,
  extra?: { status_text?: string | null; eta_scene?: string | null; eta_hospital?: string | null; reason?: string | null; assigned_by?: string | null; assigned_at?: string | null },
): CaseUnit {
  const v = vehicles.get(vid);
  const doctorSlot = vid === t.doctor_vehicle_id && vid !== t.vehicle_id;
  let role = roleIn && roleIn !== "unit" ? roleIn : doctorSlot ? "doctor" : (v?.type ?? "ambulance");
  if (doctorSlot && v?.type === "helicopter") role = "helicopter";
  const doctorOnBoard = v?.type === "helicopter" && t.doctor_vehicle_id === vid; // the helicopter brings the doctor
  const roleLabel = doctorOnBoard ? "Helicopter (doctor on board)" : (ROLE_LABEL[role] ?? role);
  const phase = unitPhase(t, v, doctorSlot ? "doctor" : role);
  const entry = [...timeline].reverse().find((e) => e.vehicle_id === vid && ASSIGN_KINDS.has(e.kind));
  const by = extra?.assigned_by ?? entry?.by ?? (t.vehicle_id === vid && t.dispatched_at ? "engine" : null);
  const assignedAt = extra?.assigned_at ?? entry?.at ?? t.dispatched_at ?? null;
  const etaScene = extra?.eta_scene ?? (doctorSlot ? (t.doctor_eta ?? null) : t.eta_pickup);
  const etaHospital = doctorSlot ? null : (extra?.eta_hospital ?? t.eta_dropoff);
  const hospital = place(t.dropoff_id).replace(/ Ljubljana$/, "");
  const now = Date.parse(state.sim_time);
  let eta: string | null = null;
  let etaLabel = "at the patient";
  let progress: number | null = null;
  if (phase === "to_scene" || phase === "next") {
    eta = etaScene;
    if (phase === "to_scene" && etaScene && assignedAt) {
      const total = mins(Date.parse(etaScene), Date.parse(assignedAt));
      progress = total > 0 ? Math.min(1, Math.max(0, mins(now, Date.parse(assignedAt)) / total)) : 1;
    } else progress = 0;
  } else if (phase === "to_hospital") {
    eta = etaHospital;
    etaLabel = `at ${hospital}`;
    const left = [...timeline].reverse().find((e) => e.kind === "transporting")?.at ?? null;
    if (etaHospital && left) {
      const total = mins(Date.parse(etaHospital), Date.parse(left));
      progress = total > 0 ? Math.min(1, Math.max(0, mins(now, Date.parse(left)) / total)) : 1;
    }
  } else if (phase === "on_scene") {
    eta = doctorSlot ? null : etaHospital;
    etaLabel = doctorSlot ? "on scene" : `at ${hospital}`;
    progress = 1;
  } else if (phase === "escort") {
    eta = t.eta_dropoff;
    etaLabel = `at ${hospital}`;
  }
  let rawReason = extra?.reason ?? entry?.text ?? null;
  // "Dispatcher override: A2 replaces A1, …" next to the "Dispatcher" tag: say it once
  if (rawReason && by === "dispatcher") rawReason = rawReason.replace(/^Dispatcher(?: override)?:\s*/i, "Override: ");
  return {
    id: vid,
    role,
    roleLabel,
    type: v?.type ?? (role === "doctor" ? "doctor" : null),
    name: v?.name ?? vid,
    phase,
    step: extra?.status_text || PHASE_STEP[phase],
    eta,
    etaLabel,
    progress,
    reason: rawReason ? shortReason(rawReason) : null,
    by,
    source: sourceText(by, entry?.detail),
    assignedAt,
  };
}

export function callView(t: Trip, state: WorldSnapshot): CallView {
  const vehicles = new Map(state.vehicles.map((v) => [v.id, v]));
  const place = (id: string) => state.places.find((p) => p.id === id)?.name ?? id;
  const c = t.call ?? null;
  const booking = c ? c.kind === "hospital_request" : BOOKING.has(t.condition ?? "");
  const received = c?.received_at ?? (booking ? (t.dispatched_at ?? t.pickup_after) : t.pickup_after);
  const status = statusOf(t, vehicles);
  const timeline = t.timeline?.length ? [...t.timeline].sort((a, b) => a.at.localeCompare(b.at)) : synthTimeline(t, received, place);
  let units: CaseUnit[];
  if (t.units?.length) {
    units = t.units.map((u) => buildUnit(t, u.vehicle_id, u.role, state, vehicles, timeline, place, u));
  } else {
    units = [];
    if (t.vehicle_id) units.push(buildUnit(t, t.vehicle_id, null, state, vehicles, timeline, place));
    if (t.doctor_vehicle_id && t.doctor_vehicle_id !== t.vehicle_id) units.push(buildUnit(t, t.doctor_vehicle_id, null, state, vehicles, timeline, place));
  }
  const closedEntry = [...timeline].reverse().find((e) => e.kind === "closed");
  const triaged = timeline.find((e) => e.kind === "triaged");
  return {
    trip: t,
    id: c?.call_id ?? t.id,
    kind: booking ? "hospital_request" : "112",
    received,
    address: c?.address ?? place(t.pickup_id),
    caller: c?.caller_name ?? null,
    textSl: c?.text_sl ?? null,
    textEn: c?.text_en ?? (c ? null : t.note),
    triageBy: c?.triage?.by ?? null,
    triageDetail: triaged?.detail ?? null,
    reasonEn: c?.triage?.reason_en ?? null,
    reasonSl: c?.triage?.reason_sl ?? null,
    status,
    units,
    timeline,
    closedAt: t.status === "completed" || t.status === "cancelled" ? (closedEntry?.at ?? t.eta_dropoff ?? null) : null,
    proposal: pendingProposal(t, state.agent.runs),
  };
}

/** Active calls (most severe and urgent first) and those closed in the last `hours`. */
export function callsOf(state: WorldSnapshot, hours = 3): { active: CallView[]; closed: CallView[] } {
  const now = Date.parse(state.sim_time);
  const open = state.trips.filter((t) => t.status !== "completed" && t.status !== "cancelled").sort(compareTrips);
  const done = state.trips
    .filter((t) => t.status === "completed" || t.status === "cancelled")
    .map((t) => callView(t, state))
    .filter((c) => !c.closedAt || now - Date.parse(c.closedAt) <= hours * 3_600_000)
    .sort((a, b) => (b.closedAt ?? "").localeCompare(a.closedAt ?? ""));
  return { active: open.map((t) => callView(t, state)), closed: done };
}

// --- Who did what -------------------------------------------------------------------------------

export type BadgeTone = "claude" | "rules" | "dispatcher" | "warn" | "idle";

export interface Badge {
  key: string;
  label: string; // "AI dispatched"
  src: string | null; // the honest source: "rules engine", "Claude"
  tone: BadgeTone;
  title: string; // full explanation (hover)
  check?: boolean; // Claude reviewed and agreed
}

const fmtHm = (iso: string) =>
  new Date(iso).toLocaleTimeString("sl-SI", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Ljubljana" });

function srcOf(entries: TimelineEntry[]): { src: string; tone: BadgeTone } {
  const claude = entries.some((e) => isClaude(e.by));
  const rules = entries.some((e) => !isClaude(e.by));
  return claude && rules ? { src: "rules engine + Claude", tone: "claude" } : claude ? { src: "Claude", tone: "claude" } : { src: "rules engine", tone: "rules" };
}

const lines = (entries: TimelineEntry[]) =>
  entries.map((e) => `${fmtHm(e.at)} ${e.text}${e.detail || e.by ? ` (${sourceText(e.by, e.detail)})` : ""}`).join("\n");

/** The case's "who did what" badges, from the triage and the timeline. */
export function badgesOf(c: CallView): Badge[] {
  const tl = c.timeline;
  const out: Badge[] = [];
  const triaged = tl.find((e) => e.kind === "triaged");
  if (c.kind === "112" && (c.triageBy || triaged)) {
    const by = c.triageBy ?? triaged?.by ?? null;
    const how = sourceText(by === "rules" ? "rules" : by, c.triageDetail);
    if (by === "dispatcher") out.push({ key: "class", label: "Dispatcher classified", src: null, tone: "dispatcher", title: `Classified by the dispatcher${triaged ? `\n${triaged.text}` : ""}` });
    else
      out.push({
        key: "class",
        label: "AI classified",
        src: isClaude(by) ? "Claude" : "rules",
        tone: isClaude(by) ? "claude" : "rules",
        title: `Classified by ${how}${isClaude(by) ? "" : "\nNot Claude: AI triage is off, or Claude was unavailable"}${triaged ? `\n${triaged.text}` : ""}`,
      });
  }
  const disp = tl.find((e) => e.kind === "dispatched");
  if (disp) {
    if (disp.by === "dispatcher") out.push({ key: "disp", label: "Dispatcher dispatched", src: null, tone: "dispatcher", title: lines([disp]) });
    else {
      const s = srcOf([disp]);
      out.push({ key: "disp", label: "AI dispatched", src: s.src, tone: s.tone, title: `Dispatched by ${sourceText(disp.by, disp.detail)}\n${disp.text}` });
    }
  } else if (c.status === "waiting") {
    out.push({ key: "disp", label: "Waiting for a unit", src: null, tone: "warn", title: "No unit could take this call yet: the AI keeps looking" });
  }
  const reroutes = tl.filter((e) => e.kind === "rerouted" && e.by !== "dispatcher");
  if (reroutes.length) {
    const s = srcOf(reroutes);
    out.push({ key: "rer", label: `AI rerouted ${reroutes.length}×`, src: s.src, tone: s.tone, title: lines(reroutes) });
  }
  const reassigned = tl.filter((e) => (e.kind === "reassigned" || e.kind === "unit_replaced") && e.by !== "dispatcher");
  if (reassigned.length) {
    const s = srcOf(reassigned);
    out.push({ key: "rea", label: `AI reassigned ${reassigned.length}×`, src: s.src, tone: s.tone, title: lines(reassigned) });
  }
  const reviews = tl.filter((e) => e.kind === "reviewed");
  const lastReview = reviews[reviews.length - 1];
  if (lastReview) {
    const changed = !/no change|agrees?|confirmed|keeps?\b/i.test(lastReview.text) && /chang|instead|swap|moved|replac|redirect/i.test(lastReview.text);
    out.push(
      changed
        ? { key: "claude", label: `Claude changed: ${lastReview.text.replace(/^Claude (changed|reviewed)[^:]*:\s*/i, "")}`, src: null, tone: "claude", title: lines(reviews) }
        : { key: "claude", label: "Claude reviewed", src: null, tone: "claude", title: lines(reviews), check: true },
    );
  } else {
    const proposals = tl.filter((e) => e.kind === "proposal");
    if (proposals.length) {
      const s = srcOf(proposals);
      out.push({ key: "claude", label: "AI proposed a plan", src: s.src, tone: s.tone, title: lines(proposals) });
    }
  }
  const auto = tl.filter((e) => e.kind === "approved" && e.by !== "dispatcher");
  if (auto.length) out.push({ key: "auto", label: "AI applied the plan", src: "autopilot", tone: "rules", title: lines(auto) });
  // The dispatcher's interventions in the AI's work (entering the call or reporting a delay is not one)
  const mine = tl.filter((e) => e.by === "dispatcher" && INTERVENTIONS.has(e.kind));
  const overrides = mine.filter((e) => e.kind === "override" || e.kind === "reassigned" || e.kind === "unit_replaced");
  const approvals = mine.filter((e) => e.kind === "approved");
  if (overrides.length) {
    out.push({ key: "me", label: `Dispatcher overrode at ${fmtHm(overrides[overrides.length - 1].at)}`, src: null, tone: "dispatcher", title: lines(overrides) });
  } else if (approvals.length) {
    out.push({ key: "me", label: `Dispatcher approved at ${fmtHm(approvals[approvals.length - 1].at)}`, src: null, tone: "dispatcher", title: lines(approvals) });
  } else if (mine.length) {
    const last = mine[mine.length - 1];
    out.push({ key: "me", label: `Dispatcher acted at ${fmtHm(last.at)}`, src: null, tone: "dispatcher", title: lines(mine) });
  } else {
    out.push({ key: "me", label: "Dispatcher: —", src: null, tone: "idle", title: "The dispatcher has not intervened on this case" });
  }
  return out;
}

// --- Stats ---------------------------------------------------------------------------------------

/** ai_stats from the backend, or the same counts from the timelines in the snapshot. */
export function aiStatsOf(state: WorldSnapshot) {
  const s = state.ai_stats ?? {};
  const active = state.trips.filter((t) => t.status !== "completed" && t.status !== "cancelled");
  let reroutes = 0;
  let reassignments = 0;
  let overrides = 0;
  let reviews = 0;
  let changes = 0;
  let dispatched = 0;
  for (const t of state.trips) {
    for (const e of t.timeline ?? []) {
      if (e.kind === "dispatched") dispatched++;
      else if (e.kind === "rerouted" && e.by !== "dispatcher") reroutes++;
      else if ((e.kind === "reassigned" || e.kind === "unit_replaced") && e.by !== "dispatcher") reassignments++;
      else if (e.kind === "override" || (e.by === "dispatcher" && (e.kind === "reassigned" || e.kind === "unit_replaced"))) overrides++;
      else if (e.kind === "reviewed") {
        reviews++;
        if (!/no change/i.test(e.text)) changes++;
      }
    }
  }
  return {
    cases_active: s.cases_active ?? active.length,
    dispatched: s.dispatched ?? dispatched,
    reroutes: s.reroutes ?? reroutes,
    reassignments: s.reassignments ?? reassignments,
    overrides: s.overrides ?? overrides,
    claude_reviews: s.claude_reviews ?? reviews,
    claude_changes: s.claude_changes ?? changes,
    last_decision_at: s.last_decision_at ?? null,
  };
}

// --- A vehicle's part in its call (vehicle card, strip pop-over) ----------------------------------

/** The call this vehicle is on (current, next, or as the doctor) and its unit entry there. */
export function unitOnCall(state: WorldSnapshot, v: Vehicle): { call: CallView; unit: CaseUnit } | null {
  const tripId = v.current_trip_id ?? v.queue[0] ?? null;
  const trip =
    (tripId ? state.trips.find((t) => t.id === tripId) : undefined) ??
    state.trips.find((t) => t.doctor_vehicle_id === v.id && t.status !== "completed" && t.status !== "cancelled");
  if (!trip) return null;
  const call = callView(trip, state);
  const unit = call.units.find((u) => u.id === v.id);
  return unit ? { call, unit } : null;
}
