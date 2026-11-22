import { useCallback, useEffect, useRef, useState } from "react";
import type { World } from "../api";
import {
  appendEntry,
  confirmEntry,
  discardEntry,
  isConfirmPhrase,
  makeEntry,
  parseLog,
  storageKey,
  syncPending,
  visibleEntries,
  type ClinicalEntry,
  type EntryType,
  type SyncState,
} from "./clinicalLog";
import { postClinicalEntry } from "./clinicalApi";

/**
 * The clinical log of the current trip, kept in this browser and sent when the backend takes it.
 *
 * - One log per world and trip (`storageKey`): a new trip starts an empty timeline and the old
 *   trip's entries stay in storage. `caseId === null` means nothing can be logged.
 * - The log and the key it belongs to live in one state value, so a log is never saved under
 *   another trip's key. Every change is a functional update on the latest state.
 * - Sync works on a snapshot; its results are merged back by `client_entry_id` (only the `sync`
 *   mark changes), so an entry added while a sync is in flight is never lost or reverted.
 * - Tried on mount, after each change, every 15 s and when the browser comes back online. After
 *   several runs in a row that leave entries pending (no endpoint yet, backend down, no signal)
 *   it tries once a minute instead, and never stops.
 */

const SYNC_MS = 15_000;
const SLOW_SYNC_MS = 60_000;
const SLOW_AFTER_FAILURES = 4;

/** A unique id: `crypto.randomUUID` exists only in a secure context, so there is a fallback. */
export function newId(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  } catch {
    /* fall through */
  }
  const rnd = () => Math.random().toString(36).slice(2, 10);
  return `${Date.now().toString(36)}-${rnd()}-${rnd()}`;
}

function readLog(key: string): ClinicalEntry[] {
  try {
    return parseLog(localStorage.getItem(key));
  } catch {
    return []; // storage blocked (private mode): an empty log, never a crash
  }
}

function writeLog(key: string, log: readonly ClinicalEntry[]): void {
  try {
    localStorage.setItem(key, JSON.stringify(log));
  } catch {
    /* storage blocked or full: the log stays in memory for this page */
  }
}

/** Apply sync results to the entries that are still pending; the same array when nothing changes. */
function mergeSync(log: ClinicalEntry[], results: ReadonlyMap<string, SyncState>): ClinicalEntry[] {
  let changed = false;
  const out = log.map((e) => {
    const r = results.get(e.client_entry_id);
    if (!r || e.sync !== "pending" || r === "pending") return e;
    changed = true;
    return { ...e, sync: r };
  });
  return changed ? out : log;
}

interface Held {
  key: string | null; // storageKey(world, caseId), null when logging is off
  log: ClinicalEntry[];
  fromStorage: boolean; // exactly what was loaded: no need to write it back
}

const load = (key: string | null): Held => ({ key, log: key ? readLog(key) : [], fromStorage: true });

export function useClinicalLog(world: World, caseId: string | null, unit: string, simTime: string) {
  const key = caseId ? storageKey(world, caseId) : null;
  const [held, setHeld] = useState<Held>(() => load(key));
  let cur = held;
  if (held.key !== key) {
    // The trip (or world) changed: show that trip's log right away (React re-renders before paint)
    cur = load(key);
    setHeld(cur);
  }

  const heldRef = useRef(cur);
  const worldRef = useRef(world);
  useEffect(() => {
    heldRef.current = held;
    worldRef.current = world;
  });

  // Save every change under the key the log belongs to
  useEffect(() => {
    if (held.key && !held.fromStorage) writeLog(held.key, held.log);
  }, [held]);

  /** Change the log of `forKey` only; a change meant for another trip is dropped. */
  const update = useCallback((forKey: string, fn: (log: ClinicalEntry[]) => ClinicalEntry[]) => {
    setHeld((prev) => {
      if (prev.key !== forKey) return prev;
      const next = fn(prev.log);
      if (next.length === prev.log.length && next.every((e, i) => e === prev.log[i])) return prev;
      return { key: prev.key, log: next, fromStorage: false };
    });
  }, []);

  // --- Sync ---------------------------------------------------------------------------------
  const syncing = useRef(false);
  const failures = useRef(0);
  const lastTry = useRef(0);
  const kick = useRef(false);

  const runSync = useCallback(async (force = false) => {
    if (syncing.current) return;
    const snap = heldRef.current;
    if (!snap.key || !snap.log.some((e) => e.sync === "pending")) {
      failures.current = 0;
      return;
    }
    const slow = failures.current >= SLOW_AFTER_FAILURES;
    if (!force && slow && Date.now() - lastTry.current < SLOW_SYNC_MS - 1000) return;
    syncing.current = true;
    lastTry.current = Date.now();
    try {
      const w = worldRef.current;
      const out = await syncPending(snap.log, (e) => postClinicalEntry(w, e));
      const results = new Map<string, SyncState>();
      out.forEach((e, i) => {
        if (e.sync !== snap.log[i].sync) results.set(e.client_entry_id, e.sync);
      });
      failures.current = out.some((e) => e.sync === "pending") ? failures.current + 1 : 0;
      if (results.size === 0) return;
      const snapKey = snap.key;
      if (heldRef.current.key === snapKey) {
        // Mark the ref now too, so a run starting before React commits does not post them again
        heldRef.current = { ...heldRef.current, log: mergeSync(heldRef.current.log, results) };
        setHeld((prev) => {
          if (prev.key !== snapKey) return prev;
          const log = mergeSync(prev.log, results);
          return log === prev.log ? prev : { key: prev.key, log, fromStorage: false };
        });
      } else {
        // The trip changed while sending: mark the old trip's entries in storage
        writeLog(snapKey, mergeSync(readLog(snapKey), results));
      }
    } finally {
      syncing.current = false;
    }
    // Entries added while this run was in flight: send them now if the backend is answering
    if (failures.current === 0) {
      const ids = new Set(snap.log.map((e) => e.client_entry_id));
      if (heldRef.current.log.some((e) => e.sync === "pending" && !ids.has(e.client_entry_id))) {
        window.setTimeout(() => void runSync(), 0);
      }
    }
  }, []);

  useEffect(() => {
    void runSync(true);
    const iv = window.setInterval(() => void runSync(), SYNC_MS);
    const online = () => {
      failures.current = 0;
      void runSync(true);
    };
    window.addEventListener("online", online);
    return () => {
      window.clearInterval(iv);
      window.removeEventListener("online", online);
    };
  }, [runSync]);

  // Try soon after an entry is added, once it is in the snapshot the sync reads
  useEffect(() => {
    if (!kick.current) return;
    kick.current = false;
    void runSync();
  }, [held, runSync]);

  // A newly loaded trip with entries left from before: try them now
  useEffect(() => {
    if (held.fromStorage) void runSync(true);
  }, [held.key, held.fromStorage, runSync]);

  // --- Changes ------------------------------------------------------------------------------
  const stamp = () => ({ id: newId(), recordedAt: new Date().toISOString() });

  const add = (
    type: EntryType,
    content: ClinicalEntry["content"],
    o: { source?: "crew_voice" | "crew_tap"; verbatim?: string; observed_t?: string | null } = {},
  ) => {
    if (!key || !caseId) return;
    const e = makeEntry(
      { case_id: caseId, unit, t: simTime, source: o.source ?? "crew_tap", type, content, verbatim: o.verbatim, observed_t: o.observed_t },
      stamp(),
    );
    kick.current = true;
    update(key, (prev) => appendEntry(prev, e));
  };

  /** Confirm or discard the entry the timeline shows; a stale id (already superseded) is a no-op. */
  const confirm = (id: string) => {
    if (!key) return;
    const d = stamp();
    kick.current = true;
    update(key, (prev) => confirmEntry(prev, id, d));
  };
  const discard = (id: string) => {
    if (!key) return;
    const d = stamp();
    kick.current = true;
    update(key, (prev) => discardEntry(prev, id, d));
  };

  /**
   * A spoken line. Exactly "potrjeno" / "confirmed" confirms the newest heard note instead of
   * becoming a note; anything else is kept word for word as a heard note.
   */
  const addSpoken = (text: string): "confirmed" | "added" | "nothing_to_confirm" => {
    if (!key || !caseId) return "nothing_to_confirm"; // the page does not offer the log mic then
    if (isConfirmPhrase(text)) {
      const now = heldRef.current.key === key ? heldRef.current.log : [];
      const target = visibleEntries(now).find((e) => e.type === "note" && e.state === "heard");
      if (!target) return "nothing_to_confirm";
      confirm(target.client_entry_id);
      return "confirmed";
    }
    add("note", {}, { source: "crew_voice", verbatim: text.trim() });
    return "added";
  };

  return {
    entries: visibleEntries(cur.log),
    add,
    addSpoken,
    confirm,
    discard,
    pending: cur.log.filter((e) => e.sync === "pending").length,
  };
}
