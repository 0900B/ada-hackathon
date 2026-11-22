import { API_URL, type World } from "../api";
import type { ClinicalEntry, SyncState } from "./clinicalLog";

/**
 * The only place the clinical log talks to the backend. Until the ER backend ships
 * `POST /{world}/clinical/entries`, every entry answers 404 and stays pending on the tablet.
 */

const TIMEOUT_MS = 10_000;

/**
 * Post one entry (everything but its local `sync` mark). "sent" when the backend took it;
 * "pending" for a 404 (endpoint not there yet), a 5xx, a timeout or no signal, so it is tried
 * again later; "rejected" for any other 4xx (the backend looked at it and said no). 408 and 429
 * are a busy or slow backend, not a verdict on the entry, so they stay pending too.
 */
export async function postClinicalEntry(world: World, e: ClinicalEntry): Promise<SyncState> {
  const body: Partial<ClinicalEntry> = { ...e };
  delete body.sync;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${API_URL}/${world}/clinical/entries`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (res.ok) return "sent";
    const s = res.status;
    if (s === 404 || s === 408 || s === 429 || s >= 500) return "pending";
    if (s >= 400) return "rejected";
    return "pending";
  } catch {
    return "pending";
  } finally {
    clearTimeout(timer);
  }
}
