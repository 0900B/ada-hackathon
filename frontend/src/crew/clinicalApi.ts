import { API_URL, type World } from "../api";
import { controlHeaders } from "../adminKey";
import type { ClinicalEntry, SyncState } from "./clinicalLog";
import { toWire } from "./clinicalWire";

/**
 * The only place the clinical log talks to the backend: `POST /{world}/clinical/entries`
 * (contract: docs/superpowers/specs/2026-11-22-er-dashboard-api-contract.md on the
 * metelko-erdashboard branch). The entry is translated by `toWire`. Until the endpoint is deployed
 * every entry answers 404 and stays pending on the tablet.
 */

const TIMEOUT_MS = 10_000;

// A confirmation or a discard names the entry it replaces by the server's `entry_id`, which only
// the server's answer tells us. Kept per world in this browser, next to the log itself.
const idsKey = (world: World) => `crew-server-ids:${world}`;

function readIds(world: World): Record<string, string> {
  try {
    const v: unknown = JSON.parse(localStorage.getItem(idsKey(world)) ?? "{}");
    return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, string>) : {};
  } catch {
    return {};
  }
}

function rememberId(world: World, clientEntryId: string, entryId: string): void {
  try {
    localStorage.setItem(idsKey(world), JSON.stringify({ ...readIds(world), [clientEntryId]: entryId }));
  } catch {
    /* storage blocked: a later confirmation is then sent on its own */
  }
}

/**
 * Post one entry. "sent" when the backend stored it (201) or had it already (200), and for an entry
 * with nothing to send. "pending" (tried again later) for 404 (endpoint or case not there yet),
 * 401 (the demo lock needs the admin key: unlock it with the lock chip), 408, 429, any 5xx, a
 * timeout or no signal. "rejected" for any other 4xx (409 a unit that is not on the case, 422 a body
 * the backend refuses): it looked at the entry and said no, so it is not retried.
 */
export async function postClinicalEntry(world: World, e: ClinicalEntry): Promise<SyncState> {
  const ids = readIds(world);
  const body = toWire(e, (clientId) => ids[clientId] ?? null);
  if (!body) return "sent";
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${API_URL}/${world}/clinical/entries`, {
      method: "POST",
      headers: controlHeaders({ "content-type": "application/json" }),
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (res.ok) {
      try {
        const stored = (await res.json()) as { entry_id?: unknown };
        if (typeof stored.entry_id === "string") rememberId(world, e.client_entry_id, stored.entry_id);
      } catch {
        /* an answer we cannot read still means it was stored */
      }
      return "sent";
    }
    const s = res.status;
    if (s === 404 || s === 401 || s === 408 || s === 429 || s >= 500) return "pending";
    if (s >= 400) return "rejected";
    return "pending";
  } catch {
    return "pending";
  } finally {
    clearTimeout(timer);
  }
}
