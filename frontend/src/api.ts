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
  type: "ambulance" | "transport";
  base_id: string;
  lat: number;
  lon: number;
  status: string;
  current_trip_id: string | null;
  queue: string[];
  busy_until: string | null;
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

export interface WorldSnapshot {
  version: number;
  sim_time: string;
  places: Place[];
  vehicles: Vehicle[];
  trips: Trip[];
  incidents: Incident[];
  weather: { now: WeatherNow | null; overridden: boolean };
  traffic: { factor: number };
  sources: Record<string, SourceStatus>;
  alerts: Alert[];
  kpis: Kpis;
  events: EventRecord[];
}

// --- Live state over server-sent events --------------------------------------

export function useWorldState() {
  const [state, setState] = useState<WorldSnapshot | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const es = new EventSource(`${API_URL}/stream`); // reconnects automatically
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (msg) => {
      setState(JSON.parse(msg.data) as WorldSnapshot);
      setConnected(true);
    };
    return () => es.close();
  }, []);

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

export const postEvent = (event: Record<string, unknown>) => post<EventRecord>("/events", event);
export const resetSimulation = () => post<{ ok: boolean }>("/admin/reset");
