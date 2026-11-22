/** The Reports page's data: GET /{world}/reports?hours=N (backend/app/reports.py). */
import { useEffect, useState } from "react";
import { API_URL, type World } from "./api";
import { fmtNum, getLang, t } from "./i18n";
import type { Level } from "./severity";

export interface ResponseSample {
  min: number; // minutes from the call to the first unit at the patient
  target: number; // that call's own target (critical: 8 min in the city, 15 outside)
  met: boolean;
}

export interface SeverityStats {
  severity: Level;
  n: number; // calls closed in the window
  n_timed: number; // those with a response target (the figures below use these)
  target_min: number | null; // nominal target of the level
  median_response: number | null;
  p90_response: number | null;
  pct_within_target: number | null;
  responses: ResponseSample[];
}

export interface HourBucket {
  hour: string; // ISO start of the world-hour
  calls: number; // calls closed in that hour
  timed: number;
  within_target: number;
  pct_within_target: number | null;
  partial: boolean; // only part of the hour is in the window or has happened yet
}

export interface UnitUse {
  vehicle_id: string;
  type: "ambulance" | "transport" | "helicopter" | "doctor";
  busy_pct: number | null;
  samples: number;
}

export interface AiDecided {
  engine_only: number;
  claude_agreed: number;
  claude_changed: number;
  dispatcher_overrode: number;
}

export interface Report {
  world: World;
  window: { hours: number; from: string; to: string };
  totals: { calls: number; closed: number; open: number };
  by_severity: SeverityStats[];
  doctor: { n: number; target_min: number; pct_within_15: number | null; median: number | null; none_arrived: number };
  transports: { n: number; late: number; late_pct: number | null; late_after_min: number; avg_delay_min: number | null };
  utilisation: UnitUse[];
  ai: {
    calls: number;
    dispatched_by_engine: number;
    dispatched_by_claude: number;
    dispatched_by_dispatcher: number;
    reviewed_by_claude: number;
    changed_by_claude: number;
    dispatcher_overrides: number;
    decided: AiDecided;
    autonomous_share: number | null;
  };
  hourly: HourBucket[];
  method: Record<string, string>;
}

export const WINDOWS = [1, 3, 8] as const;
export const REFRESH_MS = 15_000;

/** The report of one world, refreshed every REFRESH_MS. The previous report stays while a new one loads. */
export function useReport(world: World, hours: number) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchedAt, setFetchedAt] = useState<number | null>(null);

  useEffect(() => {
    let stop = false;
    const ctl = new AbortController();
    const load = async () => {
      try {
        const res = await fetch(`${API_URL}/${world}/reports?hours=${hours}`, { signal: ctl.signal });
        if (res.status === 404) throw new Error(t("rep.noBackend"));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as Report;
        if (!stop) {
          setReport(data);
          setError(null);
          setFetchedAt(Date.now());
        }
      } catch (e) {
        if (!stop && !(e instanceof DOMException && e.name === "AbortError")) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!stop) setLoading(false);
      }
    };
    setLoading(true);
    void load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      stop = true;
      ctl.abort();
      clearInterval(timer);
    };
  }, [world, hours]);

  return { report, error, loading, fetchedAt };
}

/** "45%" in English, "45 %" (narrow no-break space) in Slovenian. */
export const fmtPct = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v)}${getLang() === "sl" ? " " : ""}%`);
/** "7.5 min" / "7,5 min" (decimal comma in Slovenian). */
export const fmtMin = (v: number | null | undefined) => (v == null ? "–" : `${v < 10 ? fmtNum(v, 1) : Math.round(v)} min`);
/** A raw table number with the language's decimal separator (English unchanged). */
export const fmtRaw = (v: number | null | undefined): string | number =>
  v == null ? "–" : getLang() === "sl" ? String(v).replace(".", ",") : v;
