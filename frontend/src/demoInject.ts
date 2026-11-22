/**
 * Demo injections into the running simulation (Simulation world only): a random 112 call and a
 * random failure. Older backends lack the endpoints: the buttons show in the simulation and hide
 * themselves for good once an endpoint answers 404 (no probing, so no console noise).
 */
import { useState } from "react";
import { controlFetch } from "./adminKey";
import { API_URL, MissingEndpoint, type EventRecord, type Trip } from "./api";
import { t } from "./i18n";
import { LEVEL_LABEL } from "./severity";

export { MissingEndpoint };

/** A menu option whose label follows the UI language. */
const option = (value: string, label: () => string) => ({
  value,
  get label() {
    return label();
  },
});

export const CALL_LEVELS: readonly { value: string; label: string }[] = [
  option("", () => t("dash.demo.any")),
  option("critical", () => LEVEL_LABEL.critical),
  option("serious", () => LEVEL_LABEL.serious),
  option("urgent", () => LEVEL_LABEL.urgent),
];

export const FAILURES: readonly { value: string; label: string }[] = [
  option("", () => t("dash.demo.any")),
  option("crash", () => t("dash.demo.crash")),
  option("closure", () => t("dash.demo.closure")),
  option("jam", () => t("dash.demo.jam")),
  option("fog", () => t("dash.demo.fog")),
  option("breakdown", () => t("dash.demo.breakdown")),
  option("delay", () => t("dash.demo.delay")),
  option("capacity", () => t("dash.demo.capacity")),
  option("equipment", () => t("dash.demo.equipment")),
];

export interface DemoApi {
  call: boolean; // POST /sim/admin/random-call exists
  incident: boolean; // POST /sim/admin/random-incident exists
}

export function useDemoApi(enabled: boolean): [DemoApi, (kind: keyof DemoApi) => void] {
  const [api, setApi] = useState<DemoApi>({ call: true, incident: true });
  const missing = (kind: keyof DemoApi) => setApi((a) => ({ ...a, [kind]: false }));
  return [enabled ? api : { call: false, incident: false }, missing];
}

async function post(path: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
  const res = await controlFetch(`${API_URL}${path}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
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
  return {
    trip,
    summary: String(data.summary ?? (trip ? t("dash.demo.newCallId", { id: trip.call?.call_id ?? trip.id }) : t("dash.demo.newCall"))),
  };
}

/** A random failure (optionally of one kind). The backend answers {event, summary} or the event record. */
export async function randomIncident(kind?: string): Promise<{ event: EventRecord | null; summary: string }> {
  const data = await post("/sim/admin/random-incident", kind ? { kind } : {});
  const event = (data.event as EventRecord | undefined) ?? ("affected_trip_ids" in data ? (data as unknown as EventRecord) : null);
  return { event, summary: String(data.summary ?? event?.summary ?? t("dash.demo.failureInjected")) };
}
