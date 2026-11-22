import { useEffect, useState } from "react";
import { KEY_HEADER, controlFetch } from "./adminKey";

export const API_URL = (
  import.meta.env.VITE_API_URL ?? "https://ada-hackathon-production.up.railway.app"
).replace(/\/$/, "");

// --- Types mirroring the backend snapshot (backend/app/models.py) -----------

export type Priority = "emergency" | "urgent" | "scheduled";
export type Needs = "stretcher" | "wheelchair" | "seated" | "equipment";
export type TripKind = "patient" | "equipment";
export type Severity = "critical" | "high" | "medium" | "low";
export type SourceHealth = "starting" | "fresh" | "stale" | "down";

export interface Place {
  id: string;
  name: string;
  kind: string;
  lat: number;
  lon: number;
  capacity: number | null; // hospitals: admissions it can still take (null = unlimited)
  specialty: string | null; // e.g. "oncology"; null = general hospital
}

export interface Vehicle {
  id: string;
  name: string;
  type: "ambulance" | "transport" | "helicopter" | "doctor"; // doctor: a doctor car (VUZ), never carries patients
  origin?: "own" | "mutual_aid" | "private"; // mutual aid from a neighbouring station, or a private ambulance
  contract_until?: string | null; // contracted surge capacity: in the fleet until then (then finishes its job and leaves)
  contract_ended?: boolean;
  base_id: string;
  lat: number;
  lon: number;
  status: string;
  current_trip_id: string | null;
  queue: string[];
  busy_until: string | null;
  // Why busy_until is set: turnout (crew to the vehicle: normal, shown neutrally), on_scene, handover
  // (handover and cleaning), delay (held up: shown as held). Absent on older backends.
  busy_reason?: "turnout" | "on_scene" | "handover" | "delay" | null;
  grounded_until?: string | null; // helicopters: grounded by fog until then (no new flights)
  // Helicopter (HNMP, daytime only; backend app/hems.py): off duty at night until then (no new calls)
  off_duty_until?: string | null;
  unavailable?: "night" | "fog" | null;
  unavailable_text?: string | null; // English, e.g. "Unavailable (night): flies 08:00-16:30, available 08:00"
  hours?: string | null; // flying hours, "08:00-16:30"
  waiting_until?: string | null; // standing at a pickup until the patient is ready
  on_road: boolean;
  path_progress: number;
  path: [number, number][] | null; // remaining road geometry of the current leg (null = no road route)
  crew: { name: string; role: string }[];
  fuel_pct: number;
  km_today: number;
  shift_end: string | null;
}

export interface Trip {
  id: string;
  kind: TripKind;
  patient: string | null; // null for equipment
  cargo: string | null; // equipment only, e.g. "ventilator"
  label: string; // what to show: the patient label, or "equipment: ventilator"
  priority: Priority;
  needs: Needs;
  pickup_id: string;
  dropoff_id: string;
  pickup_after: string;
  due_by: string;
  note: string | null;
  status: string;
  vehicle_id: string | null;
  eta_pickup: string | null;
  eta_dropoff: string | null;
  delay_min: number | null;
  dispatched_at?: string | null; // when the engine dispatched this call itself (sim time)
  // Severity and per-case urgency (docs/DISPATCH_PRIORITIES.md); missing on older backends:
  // severity.ts falls back to `priority` for all of them
  severity?: "critical" | "serious" | "urgent" | "routine" | null;
  condition?: string | null; // e.g. "cardiac_arrest", "stroke"
  condition_label?: string | null; // e.g. "Cardiac arrest"
  time_weight?: number | null; // 1-10: time sensitivity within the level
  response_target_min?: number | null; // to reach the patient
  modifiers?: string[]; // e.g. "child", "deteriorating", "multiple_patients"
  // A doctor joins some red calls in a separate doctor car (or on the helicopter); missing on older backends
  needs_doctor?: boolean;
  doctor_vehicle_id?: string | null; // D1, D2, or H1 (the helicopter has a doctor on board)
  doctor_eta?: string | null; // the doctor's arrival at the scene
  doctor_target_min?: number | null; // minutes from the call (15)
  // The 112 call (or hospital request) behind the trip and its history; missing on older backends
  call?: CallInfo | null;
  timeline?: TimelineEntry[];
  // Every unit on the call with the AI's reason for it (AI dispatcher backend); missing on older
  // backends: calls.ts builds the same from vehicle_id, doctor_vehicle_id and the timeline
  units?: TripUnit[];
}

/** One unit on a call, as the AI dispatcher sees it. */
export interface TripUnit {
  vehicle_id: string;
  role?: string | null; // "ambulance" | "doctor" | "helicopter" | "transport" | "unit"
  status_text?: string | null; // the unit's current step, e.g. "En route to the patient"
  eta_scene?: string | null;
  eta_hospital?: string | null;
  reason?: string | null; // why this unit: "Nearest free ambulance"
  assigned_by?: string | null; // "engine" (rules engine) | "claude" / "ai" | "dispatcher"
  assigned_at?: string | null;
}

export interface CallTriage {
  by: "ai" | "rules" | "dispatcher";
  at: string;
  severity: Trip["severity"];
  condition: string | null;
  condition_label: string | null;
  modifiers: string[];
  needs_doctor: boolean;
  reason_en: string | null;
  reason_sl: string | null;
}

export interface CallInfo {
  call_id: string; // "112-0042"
  kind: "112" | "hospital_request";
  received_at: string;
  caller_name: string | null;
  address: string | null;
  text_sl: string | null; // the caller's words
  text_en: string | null;
  triage: CallTriage | null;
}

export type TimelineKind =
  | "received" | "triaged" | "dispatched" | "doctor_dispatched" | "rerouted" | "reassigned" | "delayed" | "unit_replaced"
  | "proposal" | "approved" | "reviewed" | "override" | "on_scene" | "doctor_on_scene" | "transporting" | "at_hospital"
  | "handover_done" | "closed" | "note";

export interface TimelineEntry {
  at: string;
  kind: TimelineKind | string;
  by: "caller" | "ai" | "claude" | "rules" | "engine" | "dispatcher" | "crew" | string;
  text: string;
  vehicle_id?: string | null;
  run_id?: string | null; // proposals and approvals: the AI run
  detail?: string | null; // who exactly and how long it took: "rules engine, 0.1 s", "Claude, 12 s"
}

export interface Incident {
  id: string;
  kind: string;
  description: string;
  lat: number;
  lon: number;
  radius_m: number;
  active: boolean;
  source: "live" | "injected";
  provider: string | null;
  path?: [number, number][] | null; // the affected road stretch (lat, lon), drawn along the road; null = only the point
  until?: string | null; // clears by itself at this time (a demo traffic jam)
}

export interface WeatherNow {
  observed_at: string;
  temperature_c: number;
  precipitation_mm: number;
  snowfall_cm: number;
  wind_speed_kmh: number;
  source: string;
}

export interface SourceStatus {
  name: string;
  kind: string;
  age_s: number | null;
  last_error: string | null;
  health: SourceHealth;
}

export interface Alert {
  id: string;
  kind: string;
  severity: Severity;
  message: string;
  trip_id: string | null;
  vehicle_id: string | null;
}

export interface Kpis {
  open_trips: number;
  late_trips: number;
  late_non_scheduled: number;
  total_delay_min: number;
  max_delay_min: number;
  unassigned: Record<Priority, number>;
  vehicles_in_service: number;
  over_capacity: number; // patients heading to a hospital that cannot admit them
}

export interface EventRecord {
  id: string;
  sim_time: string;
  type: string;
  summary: string;
  affected_trip_ids: string[];
  kpis_before: Kpis;
  kpis_after: Kpis;
  generated?: boolean; // a call from the live-calls generator, not an operator report
}

export interface PlanStep {
  trip_id: string;
  vehicle_id: string;
  position: number | null;
  interrupt_current: boolean;
  dropoff_id?: string | null; // redirect to this hospital
}

export interface TripChange {
  trip_id: string;
  patient: string | null;
  label: string;
  priority: Priority;
  vehicle_before: string | null;
  vehicle_after: string | null;
  delay_before_min: number | null;
  delay_after_min: number | null;
  eta_dropoff_after: string | null;
  redirected_to: string | null; // hospital id when the plan redirects this patient
}

/** What a plan step really does, from the engine's simulation of the whole option. */
export interface StepDetail {
  trip_id: string;
  vehicle_id: string;
  action: "now" | "divert" | "next" | "queued" | "redirect" | string;
  when: string;
  text: string; // e.g. "A1 goes now: picks up P-102 at 18:57, at Dialysis centre 19:06"
  delay_min?: number | null;
}

export interface RecommendationOption {
  title: string;
  summary: string;
  steps: PlanStep[];
  step_details?: StepDetail[];
  pros: string[];
  cons: string[];
  feasible: boolean | null;
  errors: string[];
  kpis_after: Kpis | null;
  trip_changes: TripChange[];
}

export interface Recommendation {
  situation: string;
  options: RecommendationOption[];
  recommended_index: number;
  reasoning: string;
  notifications: { recipient: string; message_sl: string; message_en: string }[];
  escalation: string | null;
  kpis_before: Kpis | null;
}

export interface AgentStep {
  at: string;
  kind: "info" | "reasoning" | "tool_call" | "tool_result" | "error";
  text: string;
}

export interface AgentRun {
  id: string;
  trigger: string;
  event_id: string | null;
  question: string | null;
  status: "running" | "done" | "error" | "superseded" | "approved" | "rejected";
  engine: "claude" | "engine_fallback" | null;
  model: string | null;
  started_at: string;
  finished_at: string | null;
  steps: AgentStep[];
  recommendation: Recommendation | null;
  error: string | null;
  decision: {
    option_index?: number;
    title?: string;
    reason?: string | null;
    at?: string;
    event_id?: string | null;
    executed?: string[]; // what each step did as applied (same wording as step_details[].text)
  } | null;
  usage: Record<string, number>;
  // Set for the AI dispatcher's review of one case (the trip reviewed): shown on that case's card,
  // never as the "Situation review" (the general analysis has review_of null).
  review_of?: string | null;
}

/** The general analysis shown in "Situation review" (and acted on by A/Y/N): the newest run that is
 * not a single case's review. Case reviews live on their case cards. */
export const generalRun = (runs: AgentRun[]): AgentRun | undefined => runs.find((r) => !r.review_of);

export type World = "live" | "sim";

/** live_calls (default): no pre-planned day, a stream of calls dispatched at once. */
export type OperationsMode = "live_calls" | "scheduled_day";

export interface CallsStatus {
  enabled: boolean;
  active: boolean; // generating now (live-calls mode and switched on)
  per_hour: number;
  next_at: string | null;
  paused_until: string | null; // calls pause for a while after a scenario starts
  generated: number;
}

/** Contracted surge capacity (backend engine/surge.py): activated only by the dispatcher. */
export interface SurgeStatus {
  active: boolean;
  until: string | null;
  units: string[];
  available: { ambulances: string[]; vans: string[] };
  offer: string; // "Activate surge capacity for 2 h: contracted ambulances P1 (Brezovica), ..."
  default: { ambulances: number; vans: number; hours: number };
}

export interface WorldSnapshot {
  world: World;
  hypothetical: boolean;
  speedup: number;
  mode?: OperationsMode;
  calls?: CallsStatus;
  surge?: SurgeStatus;
  version: number;
  epoch?: number; // +1 on every reset of the world (scenario, Reset); missing on older backends
  sim_time: string;
  places: Place[];
  vehicles: Vehicle[];
  trips: Trip[];
  incidents: Incident[];
  weather: {
    now: WeatherNow | null;
    overridden: boolean;
    forecast: { time: string; temperature_c: number; precipitation_mm: number; snowfall_cm: number }[];
  };
  roads: { enabled: boolean; routes_cached: number; matrix_places: number; pending: number; osrm: number; tomtom: number };
  traffic: {
    factor: number;
    source: string;
    samples: { road: string; current_kmh: number; free_flow_kmh: number; ratio: number }[];
  };
  sources: Record<string, SourceStatus>;
  alerts: Alert[];
  kpis: Kpis;
  events: EventRecord[];
  agent: { enabled: boolean; model: string; auto: boolean; runs: AgentRun[] };
  ai_triage?: boolean; // 112 calls classified by the AI (else by rules); missing on older backends
  autopilot?: boolean; // the engine applies the AI's recommended plans by itself
  ai_mode?: AiMode; // autonomous: the AI dispatcher handles each case; assisted: it proposes, you approve
  ai_stats?: Partial<AiStats>;
}

export type AiMode = "autonomous" | "assisted";

/** What the AI dispatcher has done (counts over the calls in the snapshot). */
export interface AiStats {
  cases_active: number;
  dispatched: number;
  reroutes: number;
  reassignments: number;
  overrides: number; // the dispatcher overrode the AI
  claude_reviews: number;
  claude_changes: number; // reviews where Claude changed the rules engine's decision
  last_decision_at: string | null;
}

// --- Live state over server-sent events, with a polling fallback ----------------

// Some networks (a proxy, an antivirus web shield, venue Wi-Fi) hold back a streaming response while plain
// requests go through: the page would hang on "Connecting…". When the stream has delivered nothing for
// STREAM_STALL_MS, the hook fetches /{world}/state every POLL_MS instead, and stops as soon as the stream speaks.
const STREAM_STALL_MS = 5000;
const POLL_MS = 1500;

export function useWorldState(world: World) {
  const [state, setState] = useState<WorldSnapshot | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    setState(null);
    let closed = false;
    let lastStreamMsg = 0; // 0: nothing yet, so the first poll comes after POLL_MS if the stream is silent
    let shown: { epoch?: number; version?: number } | null = null;
    let inflight = false;
    let lastPollOk = 0;

    // Never let an older snapshot replace a newer one (a poll can land after a stream message).
    const apply = (s: WorldSnapshot) => {
      const snap = s as WorldSnapshot & { epoch?: number; version?: number };
      if (shown && snap.epoch === shown.epoch && (snap.version ?? 0) < (shown.version ?? 0)) return;
      shown = { epoch: snap.epoch, version: snap.version };
      setState(s);
      setConnected(true);
    };

    const es = new EventSource(`${API_URL}/${world}/stream`); // reconnects automatically
    es.onopen = () => setConnected(true);
    es.onerror = () => {
      if (Date.now() - lastPollOk > 2 * POLL_MS) setConnected(false); // while polling works, stay "Connected"
    };
    es.onmessage = (msg) => {
      lastStreamMsg = Date.now();
      apply(JSON.parse(msg.data) as WorldSnapshot);
    };

    const poll = async () => {
      if (closed || inflight || Date.now() - lastStreamMsg < STREAM_STALL_MS) return;
      inflight = true;
      try {
        const res = await fetch(`${API_URL}/${world}/state`, { cache: "no-store" });
        if (closed) return;
        if (res.ok) {
          const s = (await res.json()) as WorldSnapshot;
          lastPollOk = Date.now();
          if (!closed && Date.now() - lastStreamMsg >= STREAM_STALL_MS) apply(s);
        } else setConnected(false);
      } catch {
        if (!closed) setConnected(false);
      } finally {
        inflight = false;
      }
    };
    const timer = window.setInterval(() => void poll(), POLL_MS);

    return () => {
      closed = true;
      window.clearInterval(timer);
      es.close();
    };
  }, [world]);

  return { state, connected };
}

// --- Commands ------------------------------------------------------------------

// Every control request (POST/PUT/PATCH/DELETE) goes through controlFetch (adminKey.ts): it sends the
// demo-lock key this device holds, and a 401 opens the key prompt and throws "View only: …".

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await controlFetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (data as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail ?? res.statusText));
  }
  return data as T;
}

export const postEvent = (world: World, event: Record<string, unknown>) => post<EventRecord>(`/${world}/events`, event);
/** The dispatcher activates contracted surge capacity (ambulances, private vans) for some hours. */
export const activateSurge = (world: World, body?: { ambulances?: number; vans?: number; hours?: number }) =>
  post<{ surge: SurgeStatus; event: EventRecord | null }>(`/${world}/admin/surge`, body ?? {});
/** End the contract now: the contracted units finish their current job, return and leave. */
export const standDownSurge = (world: World) =>
  post<{ surge: SurgeStatus; event: EventRecord | null }>(`/${world}/admin/surge/stand-down`);
/** Reset (re-seed) a world; scheduledDay switches the mode, undefined keeps the current one. */
export const resetWorld = (world: World, scheduledDay?: boolean) =>
  post<{ ok: boolean; mode: OperationsMode }>(
    `/${world}/admin/reset`,
    scheduledDay === undefined ? undefined : { scheduled_day: scheduledDay },
  );
/** Live-calls generator: switch it on/off or change the rate (calls per world hour). */
export const setCalls = (world: World, body: { enabled?: boolean; per_hour?: number }) =>
  post<CallsStatus>(`/${world}/admin/calls`, body);
export const analyzeNow = (world: World, question?: string) =>
  post<AgentRun>(`/${world}/agent/analyze`, { question: question ?? null });
export const approveOption = (world: World, runId: string, optionIndex: number) =>
  post<AgentRun>(`/${world}/agent/runs/${runId}/approve`, { option_index: optionIndex });
export const rejectRun = (world: World, runId: string) =>
  post<AgentRun>(`/${world}/agent/runs/${runId}/reject`, { reason: null });
/** Turn automatic analysis of events on/off for one world. Older backends answer 404 (no such endpoint). */
export async function setAgentAuto(world: World, enabled: boolean): Promise<{ world: World; auto: boolean } | "unsupported"> {
  const res = await controlFetch(`${API_URL}/${world}/agent/auto`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (res.status === 404 || res.status === 405) return "unsupported";
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (data as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail ?? res.statusText));
  }
  return data as { world: World; auto: boolean };
}
/** Numeric part of a world-scoped id (EV-0012, RUN-0013): events and runs share one counter per world. */
export const idSeq = (id: string | null | undefined) => Number(/(\d+)$/.exec(id ?? "")?.[1] ?? -1);
export interface VehicleStop {
  kind: "pickup" | "dropoff" | "base";
  trip_id: string | null;
  label: string | null;
  priority: Priority | null;
  place: string;
  lat: number;
  lon: number;
  eta: string | null;
  delay_min?: number | null;
  ready_at?: string; // pickups: the patient is ready from (arriving earlier means waiting)
}

export interface VehicleDetail {
  vehicle: Vehicle;
  base: string;
  capabilities: string[];
  fuel: { pct: number; range_km: number | null; low: boolean };
  current_trip: Trip | null;
  stops: VehicleStop[];
  legs: [number, number][][];
  detour_legs?: number[]; // indexes into legs that go around a road closure
  responding_to?: { trip_id: string; call_id: string; severity: Trip["severity"]; condition_label: string | null; address: string | null; dropoff_name: string } | null;
}

/** In-vehicle tablet: next manoeuvres on the current leg (GET /{world}/vehicles/{id}/navigation). */
export interface NavStep {
  type: string; // OSRM manoeuvre: turn, new name, continue, merge, fork, end of road, roundabout, arrive, …
  modifier: string | null; // left, slight right, straight, uturn, …
  exit: number | null; // roundabouts
  name: string;
  ref: string | null;
  lat: number;
  lon: number;
  distance_m: number; // from the vehicle to this manoeuvre
}

export interface Navigation {
  vehicle_id: string;
  sim_time: string;
  mode: "road" | "flight" | "none";
  status: "ok" | "pending" | "unavailable" | "arrived" | "no_leg" | "out_of_service";
  target: { kind: "pickup" | "dropoff" | "base"; place_id: string; name: string; lat: number; lon: number; trip_id: string | null } | null;
  steps: NavStep[];
  remaining_m?: number;
  remaining_s?: number;
  eta?: string;
  waiting?: boolean;
  bearing_deg?: number; // flight mode
  detour?: boolean;
  error?: string | null;
}

export async function fetchNavigation(world: World, id: string): Promise<Navigation> {
  const res = await fetch(`${API_URL}/${world}/vehicles/${encodeURIComponent(id)}/navigation`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as Navigation;
}

export async function fetchVehicle(world: World, id: string): Promise<VehicleDetail> {
  const res = await fetch(`${API_URL}/${world}/vehicles/${id}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as VehicleDetail;
}

export const trafficTileUrl = (layer: "flow" | "incidents") => `${API_URL}/tiles/traffic/${layer}/{z}/{x}/{y}.png`;

export interface MessageResult {
  understood_sl: string;
  understood_en: string;
  needs_clarification: string | null;
  events: Record<string, unknown>[];
  applied: EventRecord[];
  run_id: string | null;
  error?: string;
}
export const sendFieldMessage = (world: World, text: string, senderVehicleId: string | null) =>
  post<MessageResult>(`/${world}/messages`, { text, sender_vehicle_id: senderVehicleId, apply: true });

/** A new 112 call: the caller's words and where. Returns the trip with its call and timeline. */
export const postCall = (
  world: World,
  body: { text: string; address?: string; place_id?: string; lat?: number; lon?: number; caller_name?: string; dropoff_id?: string },
) => post<Trip>(`/${world}/calls`, body);
export const setAiTriage = (world: World, enabled: boolean) => post<{ ai_triage: boolean }>(`/${world}/admin/ai-triage`, { enabled });
export const setAutopilot = (world: World, enabled: boolean) => post<{ autopilot: boolean }>(`/${world}/admin/autopilot`, { enabled });
/** Autonomous (the AI dispatcher handles each case) or Assisted (it proposes, the dispatcher approves). */
export const setAiMode = (world: World, mode: AiMode) => post<{ ai_mode: AiMode }>(`/${world}/admin/ai-mode`, { mode });

// --- Dispatcher override of the AI: alternatives for a unit, and the assignment ---------------

/** Thrown when the backend has no such endpoint (HTTP 404 "Not Found"): the caller hides that action. */
export class MissingEndpoint extends Error {}

/** One unit that could take the role instead (or in addition), ranked by the engine. */
export interface Alternative {
  vehicle_id: string;
  name?: string | null;
  vehicle_type?: Vehicle["type"] | string | null;
  eta_scene?: string | null; // when it would reach the patient
  eta?: string | null; // (same, older spelling)
  delta_min?: number | null; // vs the current unit: + later, - sooner
  delta_vs_current_min?: number | null; // (same, other spellings)
  delta?: number | null;
  cost_text?: string | null; // what it costs elsewhere: "takes the last free ambulance"
  feasible?: boolean | null;
}

export interface Alternatives {
  current: { vehicle_id: string | null; eta_scene?: string | null } | null;
  alternatives: Alternative[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const control = init?.method !== undefined && !["GET", "HEAD"].includes(init.method.toUpperCase());
  const res = await (control ? controlFetch(`${API_URL}${path}`, init) : fetch(`${API_URL}${path}`, init));
  const data = await res.json().catch(() => ({}));
  const detail = (data as { detail?: unknown }).detail;
  if ((res.status === 404 && detail === "Not Found") || res.status === 405) throw new MissingEndpoint(path);
  if (!res.ok) throw new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
  return data as T;
}

/** GET /{world}/trips/{id}/alternatives?role=…: the units that could take this role, best first. */
export async function fetchAlternatives(world: World, tripId: string, role: string): Promise<Alternatives> {
  const data = await request<Alternatives | Alternative[]>(
    `/${world}/trips/${encodeURIComponent(tripId)}/alternatives?role=${encodeURIComponent(role)}`,
  );
  return Array.isArray(data) ? { current: null, alternatives: data } : { current: data.current ?? null, alternatives: data.alternatives ?? [] };
}

/** POST /{world}/trips/{id}/assign: the dispatcher replaces a unit or adds one. Returns the engine's summary. */
export const assignUnit = (world: World, tripId: string, body: { vehicle_id: string; mode: "replace" | "add"; role?: string; replaces?: string }) =>
  request<{ summary?: string; trip?: Trip }>(`/${world}/trips/${encodeURIComponent(tripId)}/assign`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });

/** Which optional endpoints this backend has, from its OpenAPI schema (fetched once; null = unknown). */
export interface ApiCaps {
  alternatives: boolean;
  assign: boolean;
  aiMode: boolean;
}
let capsPromise: Promise<ApiCaps | null> | null = null;
export function apiCaps(): Promise<ApiCaps | null> {
  capsPromise ??= fetch(`${API_URL}/openapi.json`)
    .then((r) => (r.ok ? r.json() : null))
    .then((spec: { paths?: Record<string, unknown> } | null) => {
      const paths = Object.keys(spec?.paths ?? {});
      if (!paths.length) return null;
      const has = (re: RegExp) => paths.some((p) => re.test(p));
      return {
        alternatives: has(/\/trips\/\{[^}]+\}\/alternatives$/),
        assign: has(/\/trips\/\{[^}]+\}\/assign$/),
        aiMode: has(/\/admin\/ai-mode$/),
      };
    })
    .catch(() => null);
  return capsPromise;
}

// --- Demo lock (backend/app/admin_key.py) -----------------------------------------

/** Does the backend have an ADMIN_KEY (from /health)? null: unknown (unreachable, older backend). */
export async function fetchAdminLock(): Promise<boolean | null> {
  try {
    const res = await fetch(`${API_URL}/health`);
    if (!res.ok) return null;
    const h = (await res.json()) as { admin_lock?: unknown };
    return typeof h.admin_lock === "boolean" ? h.admin_lock : null;
  } catch {
    return null;
  }
}

/**
 * Would this key be accepted? POST /lock/check changes nothing. "unknown": backend unreachable or without
 * the lock (older backend answers 404/405: nothing to unlock).
 */
export async function checkAdminKey(key: string): Promise<"ok" | "rejected" | "unknown"> {
  try {
    const res = await fetch(`${API_URL}/lock/check`, { method: "POST", headers: key ? { [KEY_HEADER]: key } : {} });
    if (res.status === 401) return "rejected";
    return res.ok ? "ok" : "unknown";
  } catch {
    return "unknown";
  }
}

export const runScenario = (name: string) =>
  post<{ scenario: string; title: string; run_id: string | null; note?: string; vehicle_id?: string | null }>(
    `/sim/admin/scenario/${name}`,
  );

export const SCENARIOS = [
  { name: "stranded_patient", label: "Stranded patient", title: "Van breaks down with an urgent patient on board" },
  { name: "stroke_rush_hour", label: "Stroke and closure", title: "Stroke near a closure: an ambulance finishing at UKC goes next" },
  { name: "priority_override", label: "Priority override", title: "Cardiac arrest next to an ambulance on its way to a fall" },
  { name: "same_level", label: "Same level, different urgency", title: "Two serious calls, one close ambulance: heart attack before seizure" },
  { name: "surge", label: "Call surge", title: "Surge: seven calls at once, including a cardiac arrest" },
  { name: "doctor_rendezvous", label: "Doctor rendezvous", title: "Chest pain in Bežigrad: ambulance and doctor start from different bases" },
  { name: "nothing_free", label: "Nothing free", title: "Critical call with every unit busy: mutual aid, private ambulance or helicopter" },
  { name: "remote_emergency", label: "Remote emergency", title: "Remote emergency in the mountains: the helicopter turns around" },
  { name: "snow_cascade", label: "Snow cascade", title: "Snowstorm, a stuck van and an emergency at once" },
  { name: "stranded_equipment", label: "Stranded equipment", title: "Van breaks down with blood products on board" },
  { name: "hospital_full", label: "UKC full", title: "UKC can admit only two more patients as a patient becomes an emergency" },
  {
    name: "equipment_en_route",
    label: "Prepare crew demo",
    title: "Prep for the live crew demo: T1 is carrying blood products",
  },
];
