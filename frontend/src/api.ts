import { useEffect, useState } from "react";

export const API_URL = (
  import.meta.env.VITE_API_URL ?? "https://ada-hackathon-production.up.railway.app"
).replace(/\/$/, "");

// --- Types mirroring the backend snapshot (backend/app/models.py) -----------

export type Priority = "emergency" | "urgent" | "scheduled";
export type Needs = "stretcher" | "wheelchair" | "seated";
export type Severity = "critical" | "high" | "medium" | "low";
export type SourceHealth = "starting" | "fresh" | "stale" | "down";

export interface Place {
  id: string;
  name: string;
  kind: string;
  lat: number;
  lon: number;
}

export interface Vehicle {
  id: string;
  name: string;
  type: "ambulance" | "transport" | "helicopter";
  base_id: string;
  lat: number;
  lon: number;
  status: string;
  current_trip_id: string | null;
  queue: string[];
  busy_until: string | null;
  grounded_until?: string | null; // helicopters: grounded by fog until then (no new flights)
  on_road: boolean;
  path_progress: number;
  path: [number, number][] | null; // remaining road geometry of the current leg (null = no road route)
}

export interface Trip {
  id: string;
  patient: string;
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
}

export interface EventRecord {
  id: string;
  sim_time: string;
  type: string;
  summary: string;
  affected_trip_ids: string[];
  kpis_before: Kpis;
  kpis_after: Kpis;
}

export interface PlanStep {
  trip_id: string;
  vehicle_id: string;
  position: number | null;
  interrupt_current: boolean;
}

export interface TripChange {
  trip_id: string;
  patient: string;
  priority: Priority;
  vehicle_before: string | null;
  vehicle_after: string | null;
  delay_before_min: number | null;
  delay_after_min: number | null;
  eta_dropoff_after: string | null;
}

export interface RecommendationOption {
  title: string;
  summary: string;
  steps: PlanStep[];
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
  decision: { option_index?: number; title?: string; reason?: string | null } | null;
  usage: Record<string, number>;
}

export type World = "live" | "sim";

export interface WorldSnapshot {
  world: World;
  hypothetical: boolean;
  speedup: number;
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
export const resetWorld = (world: World) => post<{ ok: boolean }>(`/${world}/admin/reset`);
export const analyzeNow = (world: World, question?: string) =>
  post<AgentRun>(`/${world}/agent/analyze`, { question: question ?? null });
export const approveOption = (world: World, runId: string, optionIndex: number) =>
  post<AgentRun>(`/${world}/agent/runs/${runId}/approve`, { option_index: optionIndex });
export const rejectRun = (world: World, runId: string) =>
  post<AgentRun>(`/${world}/agent/runs/${runId}/reject`, { reason: null });
export const runScenario = (name: string) =>
  post<{ scenario: string; title: string; run_id: string }>(`/sim/admin/scenario/${name}`);

export const SCENARIOS = [
  { name: "stranded_patient", label: "🚐 Stranded patient", title: "Van breaks down with a patient on board" },
  { name: "stroke_rush_hour", label: "🧠 Stroke + closure", title: "Stroke emergency with a road closure near UKC" },
  { name: "snow_cascade", label: "❄️ Snow cascade", title: "Snowstorm, a delayed van and an emergency at once" },
];
