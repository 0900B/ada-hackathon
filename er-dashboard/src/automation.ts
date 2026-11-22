import { useEffect, useRef, useState } from "react";
import { postAction } from "./api";
import type { Board, Team, World } from "./api";
import { playCritical, playHigh } from "./sound";
import { TEAM_LABEL } from "./labels";

/** Remembers a switch on this device (a per-viewer convenience, so storage failures are ignored). */
export function usePersistentFlag(key: string, initial: boolean): [boolean, (v: boolean) => void] {
  const [value, setValue] = useState<boolean>(() => {
    try {
      const s = localStorage.getItem(key);
      return s === null ? initial : s === "1";
    } catch {
      return initial;
    }
  });
  const set = (v: boolean) => {
    setValue(v);
    try {
      localStorage.setItem(key, v ? "1" : "0");
    } catch {
      /* kept in memory only */
    }
  };
  return [value, set];
}

/**
 * Sounds an alarm for each NEW alert: critical (cardiac arrest) gets the siren, high (life-threatening
 * findings) gets two chimes. Alerts already on screen when the page opens, or after a world switch, stay
 * silent: only things that appear while someone is watching make a noise.
 */
export function useAlertSound(world: World, board: Board | null, enabled: boolean): void {
  const seen = useRef<Set<string> | null>(null);
  const lastSeq = useRef<number>(0);

  useEffect(() => {
    seen.current = null; // new world: start silent again
  }, [world]);

  useEffect(() => {
    if (!board) return;
    if (board.seq < lastSeq.current) seen.current = null; // the world was reset
    lastSeq.current = board.seq;
    if (seen.current === null) {
      seen.current = new Set(board.alerts.map((a) => a.id));
      return;
    }
    const fresh = board.alerts.filter((a) => !seen.current!.has(a.id));
    fresh.forEach((a) => seen.current!.add(a.id));
    if (!enabled || fresh.length === 0) return;
    if (fresh.some((a) => a.severity === "critical")) playCritical();
    else if (fresh.some((a) => a.severity === "high")) playHigh();
  }, [board, enabled]);
}

export interface AutoCallState {
  /** Set when an automatic call was refused (for example view-only without the admin key). */
  error: string | null;
  /** How many teams this tab has called automatically since it opened. */
  called: number;
}

/**
 * Calls the ER teams that the backend suggests for each case. The choice is the backend's rule table
 * (problem type and key events: stroke, heart, trauma, resuscitation room), not a second copy of it here.
 * Every automatic call is stored with a note saying so, and uses a fixed idempotency key per case and
 * team, so several open dashboards cannot call the same team twice. A person can still call teams by hand.
 */
export function useAutoTeams(world: World, board: Board | null, enabled: boolean, onDone: () => void): AutoCallState {
  const tried = useRef<Set<string>>(new Set());
  const lastSeq = useRef<number>(0);
  const [state, setState] = useState<AutoCallState>({ error: null, called: 0 });

  useEffect(() => {
    tried.current = new Set();
    setState({ error: null, called: 0 });
  }, [world]);

  useEffect(() => {
    if (!board) return;
    if (board.seq < lastSeq.current) tried.current = new Set(); // reset: case ids start again
    lastSeq.current = board.seq;
    if (!enabled) return;

    for (const c of board.cases) {
      for (const s of c.suggested_actions) {
        if (s.action !== "team_activated" || !s.team) continue;
        const team: Team = s.team;
        const key = `${c.case_id}:${team}`;
        if (tried.current.has(key)) continue;
        tried.current.add(key); // one attempt per case and team; a refusal is shown, not retried in a loop
        postAction(world, c.case_id, {
          action: "team_activated",
          team,
          note: `Called automatically: ${s.reason}`.slice(0, 500),
          clientEntryId: `auto-${c.case_id}-${team}`,
        })
          .then(() => {
            setState((p) => ({ error: null, called: p.called + 1 }));
            onDone();
          })
          .catch((e: Error) => setState((p) => ({ ...p, error: `${TEAM_LABEL[team]} for ${c.case_id}: ${e.message}` })));
      }
    }
  }, [board, enabled, world, onDone]);

  return state;
}
