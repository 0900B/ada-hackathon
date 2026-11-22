import { useCallback, useEffect, useState } from "react";
import type { World } from "../api";
import { handoverPending } from "./crewLogic";

/**
 * Remembers, per world and vehicle, the last case that had a patient on board and whether it was
 * handed over (`crew-last:{world}:{vehicleId}` in this browser). The handover is `pending` once the
 * vehicle's trip is no longer that case and nobody tapped "Handover done"; `since` is when the trip
 * was first seen to be over (the 15:00 countdown starts there). A new patient on board replaces the
 * remembered case: handing the earlier one over was the crew's to do before that.
 *
 * `onBoardCase` is the case with a patient on board right now (null otherwise); `tripCase` is the
 * vehicle's current patient trip whether or not the patient is on board yet. Times are world time.
 */

interface Last {
  case: string;
  startedAt: string;
  endedAt: string | null;
  done: boolean;
}

const keyOf = (world: World, vehicleId: string): string => `crew-last:${world}:${vehicleId}`;

function read(key: string): Last | null {
  try {
    const v: unknown = JSON.parse(localStorage.getItem(key) ?? "null");
    if (!v || typeof v !== "object") return null;
    const o = v as Record<string, unknown>;
    if (typeof o.case !== "string" || o.case === "" || typeof o.startedAt !== "string") return null;
    return {
      case: o.case,
      startedAt: o.startedAt,
      endedAt: typeof o.endedAt === "string" ? o.endedAt : null,
      done: o.done === true,
    };
  } catch {
    return null; // storage blocked or broken JSON: nothing remembered
  }
}

function write(key: string, v: Last | null): void {
  try {
    if (v) localStorage.setItem(key, JSON.stringify(v));
    else localStorage.removeItem(key);
  } catch {
    /* storage blocked: it lives in memory for this page */
  }
}

export function useHandover(world: World, vehicleId: string, onBoardCase: string | null, tripCase: string | null, nowIso: string) {
  const key = keyOf(world, vehicleId);
  const [last, setLast] = useState<Last | null>(() => read(key));

  useEffect(() => {
    setLast((prev) => {
      let next = prev;
      if (onBoardCase && (!prev || prev.case !== onBoardCase)) {
        next = { case: onBoardCase, startedAt: nowIso, endedAt: null, done: false };
      } else if (prev && !prev.done && !prev.endedAt && prev.case !== tripCase) {
        next = { ...prev, endedAt: nowIso };
      }
      if (next !== prev) write(key, next);
      return next;
    });
  }, [key, onBoardCase, tripCase, nowIso]);

  const done = useCallback(() => {
    setLast((prev) => {
      if (!prev) return prev;
      const next = { ...prev, done: true };
      write(key, next);
      return next;
    });
  }, [key]);

  const pending = !!last && handoverPending(last.case, tripCase, last.done);
  return { pending, caseId: last?.case ?? null, since: last?.endedAt ?? nowIso, done };
}
