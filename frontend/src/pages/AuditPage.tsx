import { useEffect, useState } from "react";
import { API_URL } from "../api";
import { fmtTime } from "../format";

interface AuditEntry {
  id: string;
  at: string;
  world: string;
  kind: string;
  ref: string | null;
  summary: string;
  payload: unknown;
}

interface AuditResponse {
  status: { status: string; written_to_db: number; in_memory: number; pending: number };
  entries: AuditEntry[];
}

const KINDS = [
  "",
  "event",
  "field_message",
  "agent_run_started",
  "recommendation",
  "decision_approved",
  "decision_rejected",
  "plan_applied",
  "scenario",
  "reset",
];

const KIND_ICON: Record<string, string> = {
  event: "⚡",
  field_message: "💬",
  agent_run_started: "🤖",
  recommendation: "💡",
  decision_approved: "✅",
  decision_rejected: "✖",
  plan_applied: "🗺",
  scenario: "🎬",
  reset: "↺",
  startup: "⏻",
};

/** Every event, AI recommendation and operator decision, newest first (auto-refreshes). */
export function AuditPage() {
  const [world, setWorld] = useState("");
  const [kind, setKind] = useState("");
  const [data, setData] = useState<AuditResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stop = false;
    const load = async () => {
      try {
        const qs = new URLSearchParams({ limit: "300", ...(world && { world }), ...(kind && { kind }) });
        const res = await fetch(`${API_URL}/audit?${qs}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        if (!stop) {
          setData((await res.json()) as AuditResponse);
          setError(null);
        }
      } catch (e) {
        if (!stop) setError(e instanceof Error ? e.message : String(e));
      }
    };
    void load();
    const timer = setInterval(load, 5000);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [world, kind]);

  return (
    <main className="page">
      <h2>Audit log</h2>
      <div className="audit-bar">
        <select value={world} onChange={(e) => setWorld(e.target.value)}>
          <option value="">All worlds</option>
          <option value="live">Live</option>
          <option value="sim">Simulation</option>
        </select>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {k ? k.replace(/_/g, " ") : "All entry types"}
            </option>
          ))}
        </select>
        <a className="button-link" href={`${API_URL}/audit/export${world ? `?world=${world}` : ""}`}>
          ⬇ Export (JSON lines)
        </a>
        {data && (
          <span className="muted">
            Storage: {data.status.status} · {data.status.written_to_db} written to database · {data.status.pending} pending
          </span>
        )}
      </div>
      {error && <div className="message error">Could not load the audit log: {error}</div>}
      <table className="audit">
        <thead>
          <tr>
            <th>Time</th>
            <th>World</th>
            <th>Type</th>
            <th>Ref</th>
            <th>What happened</th>
          </tr>
        </thead>
        <tbody>
          {data?.entries.map((e) => (
            <tr key={`${e.id}-${e.at}`}>
              <td>
                {new Date(e.at).toLocaleDateString("sl-SI", { timeZone: "Europe/Ljubljana" })} {fmtTime(e.at)}
              </td>
              <td>
                <span className={`world-tag world-${e.world}`}>{e.world}</span>
              </td>
              <td>
                {KIND_ICON[e.kind] ?? "•"} {e.kind.replace(/_/g, " ")}
              </td>
              <td className="mono">{e.ref ?? ""}</td>
              <td>
                {e.payload ? (
                  <details>
                    <summary>{e.summary}</summary>
                    <pre>{JSON.stringify(e.payload, null, 2)}</pre>
                  </details>
                ) : (
                  e.summary
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {data && data.entries.length === 0 && <p className="muted">No entries yet.</p>}
    </main>
  );
}
