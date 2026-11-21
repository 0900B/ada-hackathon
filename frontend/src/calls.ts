/**
 * Calls: every trip seen from the 112 call (or hospital request) that started it, followed to the
 * end. Uses Trip.call and Trip.timeline when the backend sends them; otherwise builds the same view
 * from the trip's own fields, so older backends still show a useful list.
 */
import type { AgentRun, TimelineEntry, Trip, Vehicle, WorldSnapshot } from "./api";
import { compareTrips } from "./severity";

export type CallStatus = "waiting" | "dispatched" | "en route" | "on scene" | "transporting" | "at hospital" | "closed" | "cancelled";

export interface CallUnit {
  id: string;
  role: "unit" | "doctor";
  type: Vehicle["type"] | null;
  eta: string | null; // when it reaches the patient (or the hospital once the patient is on board)
  etaLabel: string; // "at the patient" | "at UKC" | "on scene"
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
  reasonEn: string | null;
  reasonSl: string | null;
  status: CallStatus;
  units: CallUnit[];
  timeline: TimelineEntry[];
  closedAt: string | null;
  proposal: AgentRun | null; // a pending AI/engine plan that involves this call
}

const BOOKING = new Set(["transfer", "equipment"]);

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

export function callView(t: Trip, state: WorldSnapshot): CallView {
  const vehicles = new Map(state.vehicles.map((v) => [v.id, v]));
  const place = (id: string) => state.places.find((p) => p.id === id)?.name ?? id;
  const c = t.call ?? null;
  const booking = c ? c.kind === "hospital_request" : BOOKING.has(t.condition ?? "");
  const received = c?.received_at ?? (booking ? (t.dispatched_at ?? t.pickup_after) : t.pickup_after);
  const units: CallUnit[] = [];
  const onboard = t.status === "onboard";
  if (t.vehicle_id) {
    units.push({
      id: t.vehicle_id,
      role: "unit",
      type: vehicles.get(t.vehicle_id)?.type ?? null,
      eta: onboard ? t.eta_dropoff : t.eta_pickup,
      etaLabel: onboard ? `at ${place(t.dropoff_id).replace(/ Ljubljana$/, "")}` : "at the patient",
    });
  }
  if (t.doctor_vehicle_id && t.doctor_vehicle_id !== t.vehicle_id) {
    const dv = vehicles.get(t.doctor_vehicle_id);
    const there = dv && (dv.status === "loading" || dv.status === "with_patient");
    units.push({ id: t.doctor_vehicle_id, role: "doctor", type: dv?.type ?? "doctor", eta: there ? null : (t.doctor_eta ?? null), etaLabel: there ? "on scene" : "at the patient" });
  }
  const status = statusOf(t, vehicles);
  const timeline = t.timeline?.length ? [...t.timeline].sort((a, b) => a.at.localeCompare(b.at)) : synthTimeline(t, received, place);
  const closedEntry = [...timeline].reverse().find((e) => e.kind === "closed");
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

export const BY_LABEL: Record<string, string> = {
  caller: "Caller",
  ai: "AI",
  rules: "Rules",
  engine: "Engine",
  dispatcher: "Dispatcher",
  crew: "Crew",
};

export const STEP_LABEL: Record<string, string> = {
  received: "Call received",
  triaged: "Triaged",
  dispatched: "Dispatched",
  doctor_dispatched: "Doctor sent",
  rerouted: "Rerouted",
  reassigned: "Reassigned",
  delayed: "Delayed",
  unit_replaced: "Unit replaced",
  proposal: "Proposal",
  approved: "Approved",
  on_scene: "On scene",
  doctor_on_scene: "Doctor on scene",
  transporting: "Transporting",
  at_hospital: "At hospital",
  handover_done: "Handover done",
  closed: "Closed",
  note: "Note",
};
