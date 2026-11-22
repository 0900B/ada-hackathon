/**
 * The only module that talks to the backend. Types follow
 * docs/superpowers/specs/2026-11-22-er-dashboard-api-contract.md (derived from backend/app/clinical/).
 * To change how data arrives (stream instead of polling), change useBoard.ts; nothing else reads the network.
 */

export type World = "sim" | "live";

const DEFAULT_BASE = import.meta.env.DEV ? "http://localhost:8000" : "https://ada-hackathon-production.up.railway.app";
export const API_BASE: string = ((import.meta.env.VITE_API_URL as string | undefined) ?? DEFAULT_BASE).replace(/\/$/, "");

// ---- types ---------------------------------------------------------------------------------------

export type LevelValue = "red" | "yellow" | "scheduled";
export type VitalKey = "hr" | "sbp" | "dbp" | "spo2" | "rr" | "gcs" | "temp_c" | "glucose_mmol";
export type Team = "stroke" | "heart" | "trauma" | "resuscitation_room";
export type AlertSeverity = "critical" | "high" | "medium" | "low";

export interface Vital {
  value: number;
  age_min: number;
  state: "heard" | "inferred" | "confirmed";
  needs_check: boolean;
  seq: number;
}
export interface Treatment {
  seq: number;
  type: "drug_administered" | "procedure";
  content: { drug?: string; dose?: string; route?: string; name?: string };
  observed_t: string;
  state: string;
  needs_check: boolean;
}
export interface CaseEvent {
  kind: string;
  observed_t: string;
  onset_t: string | null;
  state: string;
}
export interface Handover {
  started_at: string;
  due_at: string;
  minutes_left: number | null;
  overdue: boolean;
  done_at: string | null;
}
export interface SuggestedAction {
  action: "acknowledge" | "bay_assigned" | "team_activated";
  team?: Team;
  reason: string;
}
export interface CaseCard {
  case_id: string;
  vehicle_id: string | null;
  patient_label: string;
  priority: "emergency" | "urgent" | "scheduled";
  level: { value: LevelValue; inferred: boolean; source: string | null };
  problem: { type: string | null; note: string | null };
  age_years: number | null;
  sex: "f" | "m" | "unknown" | null;
  eta_dropoff: string | null;
  minutes_to_arrival: number | null;
  arrived_at: string | null;
  stage: string | null;
  stage_inferred: boolean;
  severity: string | null;
  vitals: Partial<Record<VitalKey, Vital>>;
  treatments: Treatment[];
  events: CaseEvent[];
  acknowledged: boolean;
  bay: string | null;
  teams_activated: Team[];
  handover: Handover | null;
  suggested_actions: SuggestedAction[];
  alert_ids: string[];
}
export interface ErAlert {
  id: string;
  rule: string;
  severity: AlertSeverity;
  case_id: string;
  vehicle_id: string | null;
  message: string;
  since: string | null;
}
export interface LogEntry {
  seq: number;
  entry_id: string;
  case_id: string;
  type: string;
  content: Record<string, unknown>;
  unit: string;
  source: string;
  state: string;
  t: string;
  observed_t: string;
  verbatim: string | null;
  supersedes: string | null;
  needs_check: boolean;
}
export interface Board {
  world: string;
  as_of: string;
  seq: number;
  cases: CaseCard[];
  alerts: ErAlert[];
  entries_tail: LogEntry[];
}
export interface CaseDetailData {
  case: CaseCard;
  timeline: LogEntry[];
  alerts: ErAlert[];
}

// ---- demo lock (backend/app/admin_key.py): writes carry X-Plan-B-Key when a key is set ------------------

const KEY_STORAGE = "planb.adminKey";

/** `?key=...` in the address is kept on this device and removed from the bar (same convention as the dispatch UI). */
export function captureKeyFromUrl(): void {
  try {
    const url = new URL(window.location.href);
    const k = url.searchParams.get("key");
    if (!k) return;
    localStorage.setItem(KEY_STORAGE, k.trim());
    url.searchParams.delete("key");
    window.history.replaceState(null, "", url.toString());
  } catch {
    /* storage blocked: reading still works, writes need the key some other way */
  }
}
function storedKey(): string {
  try {
    return localStorage.getItem(KEY_STORAGE) ?? "";
  } catch {
    return "";
  }
}

// ---- requests --------------------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** `detail` is a string for rule refusals and an array of pydantic errors for a bad body (contract section 6). */
function detailText(body: unknown, fallback: string): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e) => (e as { msg?: string }).msg ?? "invalid").join("; ");
  return fallback;
}

async function request<T>(path: string, init?: RequestInit & { signal?: AbortSignal }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "Cannot reach the server");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401) throw new ApiError(401, "View only: open this page once with ?key=… to make changes");
    throw new ApiError(res.status, detailText(body, `Server answered ${res.status}`));
  }
  return body as T;
}

export const fetchBoard = (world: World, signal?: AbortSignal) => request<Board>(`/${world}/er/board`, { signal });

export const fetchCase = (world: World, caseId: string, signal?: AbortSignal) =>
  request<CaseDetailData>(`/${world}/er/cases/${encodeURIComponent(caseId)}`, { signal });

export interface ActionBody {
  action: "acknowledge" | "bay_assigned" | "team_activated";
  bay?: string;
  team?: Team;
  /** Stored with the entry (max 500). Used to mark calls the dashboard made by itself. */
  note?: string;
  /**
   * Idempotency key (scoped to unit "er" on the server). A person's click gets a random one; an automatic
   * call gets a fixed one per case and team, so two open dashboards cannot call the same team twice.
   */
  clientEntryId?: string;
}

export function postAction(world: World, caseId: string, body: ActionBody): Promise<LogEntry> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const key = storedKey();
  if (key) headers["X-Plan-B-Key"] = key;
  const { clientEntryId, ...rest } = body;
  return request<LogEntry>(`/${world}/er/cases/${encodeURIComponent(caseId)}/actions`, {
    method: "POST",
    headers,
    body: JSON.stringify({ ...rest, client_entry_id: clientEntryId ?? crypto.randomUUID() }),
  });
}

// ---- live tracking of the unit on a case ---------------------------------------------------------------

export type LatLng = [number, number];
export interface VehicleStop {
  kind: "pickup" | "dropoff" | "base" | string;
  trip_id: string | null;
  label?: string;
  place?: string;
  lat: number;
  lon: number;
  eta?: string;
}
export interface VehicleTrack {
  vehicle: { id: string; name: string; type: string; lat: number; lon: number; status: string; current_trip_id: string | null };
  stops: VehicleStop[];
  /** legs[i] is the road line from the previous point (the vehicle for i = 0) to stops[i]. */
  legs: LatLng[][];
}

export const fetchVehicle = (world: World, vehicleId: string, signal?: AbortSignal) =>
  request<VehicleTrack>(`/${world}/vehicles/${encodeURIComponent(vehicleId)}`, { signal });
