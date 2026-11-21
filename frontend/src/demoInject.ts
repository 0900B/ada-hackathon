/**
 * Demo injections into the running simulation (Simulation world only): a random 112 call and a
 * random failure. Older backends lack the endpoints: the buttons show in the simulation and hide
 * themselves for good once an endpoint answers 404 (no probing, so no console noise).
 */
import { useState } from "react";
import { API_URL, type EventRecord, type Trip } from "./api";

export const CALL_LEVELS = [
  { value: "", label: "Any" },
  { value: "critical", label: "Critical" },
  { value: "serious", label: "Serious" },
  { value: "urgent", label: "Urgent" },
] as const;

export const FAILURES = [
  { value: "", label: "Any" },
  { value: "crash", label: "Car crash" },
  { value: "closure", label: "Road closure" },
  { value: "fog", label: "Fog" },
  { value: "breakdown", label: "Engine failure" },
  { value: "delay", label: "Delay" },
  { value: "capacity", label: "Hospital full" },
  { value: "equipment", label: "Stranded equipment" },
] as const;

export interface DemoApi {
  call: boolean; // POST /sim/admin/random-call exists
  incident: boolean; // POST /sim/admin/random-incident exists
}

/** Thrown when the backend has no such endpoint (HTTP 404): the caller hides that button. */
export class MissingEndpoint extends Error {}

export function useDemoApi(enabled: boolean): [DemoApi, (kind: keyof DemoApi) => void] {
  const [api, setApi] = useState<DemoApi>({ call: true, incident: true });
  const missing = (kind: keyof DemoApi) => setApi((a) => ({ ...a, [kind]: false }));
  return [enabled ? api : { call: false, incident: false }, missing];
}

async function post(path: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_URL}${path}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (res.status === 404 && (data as { detail?: unknown }).detail === "Not Found") throw new MissingEndpoint(path);
  if (!res.ok) {
    const detail = (data as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
  }
  return data as Record<string, unknown>;
}

/** A random call (optionally of one severity). The backend answers {trip, summary} or the trip itself. */
export async function randomCall(severity?: string): Promise<{ trip: Trip | null; summary: string }> {
  const data = await post("/sim/admin/random-call", severity ? { severity } : {});
  const trip = (data.trip as Trip | undefined) ?? ("id" in data && "pickup_id" in data ? (data as unknown as Trip) : null);
  return { trip, summary: String(data.summary ?? (trip ? `New call ${trip.call?.call_id ?? trip.id}` : "New call")) };
}

/** A random failure (optionally of one kind). The backend answers {event, summary} or the event record. */
export async function randomIncident(kind?: string): Promise<{ event: EventRecord | null; summary: string }> {
  const data = await post("/sim/admin/random-incident", kind ? { kind } : {});
  const event = (data.event as EventRecord | undefined) ?? ("affected_trip_ids" in data ? (data as unknown as EventRecord) : null);
  return { event, summary: String(data.summary ?? event?.summary ?? "Failure injected") };
}
