import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, fetchBoard, fetchCase } from "./api";
import type { Board, CaseDetailData, World } from "./api";

const POLL_MS = 1500;

export interface BoardState {
  board: Board | null;
  /** When the last good board arrived (real clock, ms). */
  lastOk: number | null;
  /** Set while the latest poll failed; the last good board stays on screen. */
  error: string | null;
  /** The server answered but its clinical section reported an error (contract section 7, item 6). */
  featureOff: boolean;
}

/**
 * Polls GET /{world}/er/board. Always keeps the last good board (one failed poll must not blank the screen),
 * never overlaps two requests, and discards state when the world is switched.
 */
export function useBoard(world: World): BoardState & { refresh: () => void } {
  const [state, setState] = useState<BoardState>({ board: null, lastOk: null, error: null, featureOff: false });
  const inflight = useRef(false);
  const tickRef = useRef<() => void>(() => {});

  useEffect(() => {
    setState({ board: null, lastOk: null, error: null, featureOff: false });
    let stopped = false;
    const ctl = new AbortController();

    const tick = async () => {
      if (inflight.current || document.hidden) return;
      inflight.current = true;
      try {
        const board = await fetchBoard(world, ctl.signal);
        if (stopped) return;
        setState({ board, lastOk: Date.now(), error: null, featureOff: false });
      } catch (e) {
        if (stopped || (e as Error).name === "AbortError") return;
        const off = e instanceof ApiError && e.status === 404;
        setState((s) => ({
          ...s,
          error: off ? "The ER board is switched off on this server" : (e as Error).message,
          featureOff: off,
        }));
      } finally {
        inflight.current = false;
      }
    };

    tickRef.current = tick;
    tick();
    const id = window.setInterval(tick, POLL_MS);
    return () => {
      stopped = true;
      ctl.abort();
      inflight.current = false;
      window.clearInterval(id);
    };
  }, [world]);

  const refresh = useCallback(() => tickRef.current(), []);
  return { ...state, refresh };
}

export interface DetailState {
  data: CaseDetailData | null;
  /** True when the case has left the board (404): finished more than 3 world hours ago, or cancelled. */
  gone: boolean;
}

/** Timeline and alerts of one case. Reloads when the board's seq changes, so it never lags behind the board. */
export function useCaseDetail(world: World, caseId: string | null, seq: number | null): DetailState & { reload: () => void } {
  const [state, setState] = useState<DetailState>({ data: null, gone: false });
  const [nudge, setNudge] = useState(0);
  const lastCase = useRef<string | null>(null);

  const load = useCallback(
    async (signal: AbortSignal) => {
      if (!caseId) return;
      try {
        const data = await fetchCase(world, caseId, signal);
        setState({ data, gone: false });
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        if (e instanceof ApiError && e.status === 404) setState({ data: null, gone: true });
        /* any other error: keep what is shown, the next seq change retries */
      }
    },
    [world, caseId],
  );

  useEffect(() => {
    if (lastCase.current !== caseId) {
      lastCase.current = caseId;
      setState({ data: null, gone: false });
    }
    if (!caseId) return;
    const ctl = new AbortController();
    load(ctl.signal);
    return () => ctl.abort();
  }, [caseId, seq, load, nudge]);

  const reload = useCallback(() => setNudge((n) => n + 1), []);
  return { ...state, reload };
}
