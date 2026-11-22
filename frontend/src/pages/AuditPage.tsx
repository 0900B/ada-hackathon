import { useEffect, useState } from "react";
import { API_URL } from "../api";
import {
  Bot,
  CircleCheck,
  CircleX,
  Clapperboard,
  Download,
  Lightbulb,
  Map,
  MessageSquare,
  PhoneIncoming,
  Power,
  RotateCcw,
  SlidersHorizontal,
  Truck,
  UserCheck,
  Zap,
  Dot,
  type LucideIcon,
} from "lucide-react";
import { fmtTime } from "../format";
import { tOr, useT } from "../i18n";

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
  "call",
  "event",
  "override",
  "field_message",
  "agent_run_started",
  "recommendation",
  "decision_approved",
  "decision_rejected",
  "plan_applied",
  "surge",
  "scenario",
  "reset",
  "setting",
  "startup",
];

const KIND_ICON: Record<string, LucideIcon> = {
  call: PhoneIncoming,
  event: Zap,
  override: UserCheck,
  surge: Truck,
  field_message: MessageSquare,
  agent_run_started: Bot,
  recommendation: Lightbulb,
  decision_approved: CircleCheck,
  decision_rejected: CircleX,
  plan_applied: Map,
  scenario: Clapperboard,
  reset: RotateCcw,
  setting: SlidersHorizontal,
  startup: Power,
};

function KindIcon({ kind }: { kind: string }) {
  const Icon = KIND_ICON[kind] ?? Dot;
  return <Icon aria-hidden />;
}

/** An entry type in the UI language ("decision approved" / "odločitev potrjena"); unknown types humanized. */
const kindLabel = (kind: string) => tOr(`audit.kind.${kind}`, kind.replace(/_/g, " "));

/**
 * Every event, AI recommendation and operator decision, newest first (auto-refreshes). The entries'
 * summaries come from the backend and stay as it writes them (English).
 */
export function AuditPage() {
  const t = useT();
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
      <h2>{t("audit.title")}</h2>
      <div className="audit-bar">
        <select value={world} onChange={(e) => setWorld(e.target.value)}>
          <option value="">{t("audit.allWorlds")}</option>
          <option value="live">{t("rep.worldLive")}</option>
          <option value="sim">{t("rep.worldSim")}</option>
        </select>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {k ? kindLabel(k) : t("audit.allKinds")}
            </option>
          ))}
        </select>
        <a className="button-link" href={`${API_URL}/audit/export${world ? `?world=${world}` : ""}`}>
          <Download /> {t("audit.export")}
        </a>
        {data && (
          <span className="muted">
            {t("audit.storage", { status: data.status.status, written: data.status.written_to_db, pending: data.status.pending })}
          </span>
        )}
      </div>
      {error && <div className="message error">{t("audit.loadError", { error })}</div>}
      <table className="audit">
        <thead>
          <tr>
            <th>{t("audit.colTime")}</th>
            <th>{t("audit.colWorld")}</th>
            <th>{t("audit.colType")}</th>
            <th>{t("audit.colRef")}</th>
            <th>{t("audit.colWhat")}</th>
          </tr>
        </thead>
        <tbody>
          {data?.entries.map((e) => (
            <tr key={`${e.id}-${e.at}`}>
              <td>
                {new Date(e.at).toLocaleDateString("sl-SI", { timeZone: "Europe/Ljubljana" })} {fmtTime(e.at)}
              </td>
              <td>
                <span className={`world-tag world-${e.world}`}>{tOr(`audit.worldTag.${e.world}`, e.world)}</span>
              </td>
              <td className="kind">
                <KindIcon kind={e.kind} />
                {kindLabel(e.kind)}
              </td>
              <td className="id">{e.ref ?? ""}</td>
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
      {data && data.entries.length === 0 && <p className="muted">{t("audit.empty")}</p>}
    </main>
  );
}
