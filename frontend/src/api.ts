import { useEffect, useState } from "react";

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
  base_id: string;
  lat: number;
  lon: number;
  status: string;
  current_trip_id: string | null;
  queue: string[];
  busy_until: string | null;
  grounded_until?: string | null; // helicopters: grounded by fog until then (no new flights)
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
  | "proposal" | "approved" | "on_scene" | "doctor_on_scene" | "transporting" | "at_hospital" | "handover_done" | "closed" | "note";

export interface TimelineEntry {
  at: string;
  kind: TimelineKind | string;
  by: "caller" | "ai" | "rules" | "engine" | "dispatcher" | "crew" | string;
  text: string;
  vehicle_id?: string | null;
  run_id?: string | null; // proposals and approvals: the AI run
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
}

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

export interface WorldSnapshot {
  world: World;
  hypothetical: boolean;
  speedup: number;
  mode?: OperationsMode;
  calls?: CallsStatus;
  version: number;
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
}

// --- Live state over server-sent events --------------------------------------

export function useWorldState(world: World) {
  const [state, setState] = useState<WorldSnapshot | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    setState(null);
    const es = new EventSource(`${API_URL}/${world}/stream`); // reconnects automatically
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (msg) => {
      setState(JSON.parse(msg.data) as WorldSnapshot);
      setConnected(true);
    };
    return () => es.close();
  }, [world]);

  return { state, connected };
}

// --- Commands ------------------------------------------------------------------

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
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
  const res = await fetch(`${API_URL}/${world}/agent/auto`, {
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
