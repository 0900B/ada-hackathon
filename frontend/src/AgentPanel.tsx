import { useState } from "react";
import {
  analyzeNow,
  approveOption,
  rejectRun,
  type AgentRun,
  type AgentStep,
  type Kpis,
  type PlanStep,
  type RecommendationOption,
  type WorldSnapshot,
} from "./api";

type Notify = (m: { kind: "ok" | "error"; text: string }) => void;

const STEP_ICON: Record<AgentStep["kind"], string> = {
  info: "ℹ",
  reasoning: "💭",
  tool_call: "🔎",
  tool_result: "📊",
  error: "⚠",
};

const unassigned = (k: Kpis) => k.unassigned.emergency + k.unassigned.urgent + k.unassigned.scheduled;

function Delta({ label, before, after, unit = "" }: { label: string; before: number; after: number; unit?: string }) {
  const cls = after < before ? "better" : after > before ? "worse" : "same";
  return (
    <span className={`delta ${cls}`}>
      {label} {Math.round(before)}→{Math.round(after)}
      {unit}
    </span>
  );
}

function stepText(s: PlanStep) {
  const where = s.interrupt_current ? "divert now" : s.position === null ? "end of queue" : s.position === 0 ? "next" : `#${s.position + 1}`;
  return `${s.trip_id} → ${s.vehicle_id} (${where})`;
}

function OptionCard({
  run,
  option,
  index,
  before,
  onApprove,
  busy,
}: {
  run: AgentRun;
  option: RecommendationOption;
  index: number;
  before: Kpis | null;
  onApprove: (i: number) => void;
  busy: boolean;
}) {
  const rec = run.recommendation!;
  const recommended = index === rec.recommended_index;
  const approved = run.status === "approved" && run.decision?.option_index === index;
  const after = option.kpis_after;
  return (
    <div className={`option${recommended ? " recommended" : ""}${option.feasible === false ? " infeasible" : ""}`}>
      <div className="option-head">
        <strong>
          {index + 1}. {option.title}
        </strong>
        {recommended && <span className="badge">Recommended</span>}
        {approved && <span className="badge ok">✓ Approved</span>}
      </div>
      <p className="option-summary">{option.summary}</p>
      {before && after && (
        <div className="deltas">
          <Delta label="Late" before={before.late_trips} after={after.late_trips} />
          <Delta label="Delay" before={before.total_delay_min} after={after.total_delay_min} unit=" min" />
          <Delta label="Unassigned" before={unassigned(before)} after={unassigned(after)} />
        </div>
      )}
      {option.steps.length > 0 && (
        <ul className="plan-steps">
          {option.steps.map((s, i) => (
            <li key={i}>{stepText(s)}</li>
          ))}
        </ul>
      )}
      {option.feasible === false && <div className="warn-box">Not feasible: {option.errors.join("; ")}</div>}
      {(option.pros.length > 0 || option.cons.length > 0) && (
        <div className="proscons">
          {option.pros.map((p, i) => (
            <div key={`p${i}`} className="pro">
              + {p}
            </div>
          ))}
          {option.cons.map((c, i) => (
            <div key={`c${i}`} className="con">
              − {c}
            </div>
          ))}
        </div>
      )}
      {run.status === "done" && option.feasible !== false && (
        <button className={recommended ? "primary" : ""} disabled={busy} onClick={() => onApprove(index)}>
          Approve option {index + 1}
        </button>
      )}
    </div>
  );
}

export function AgentPanel({ state, notify }: { state: WorldSnapshot; notify: Notify }) {
  const [busy, setBusy] = useState(false);
  const { enabled, model, runs } = state.agent;
  const run = runs[0];

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try {
      await fn();
      notify({ kind: "ok", text: ok });
    } catch (e) {
      notify({ kind: "error", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  const rec = run?.recommendation;
  const elapsed = run ? Math.round((Date.now() - new Date(run.started_at).getTime()) / 1000) : 0;

  return (
    <div className="agent">
      <div className="agent-head">
        <span className={`chip ${enabled ? "ok" : "warn"}`}>{enabled ? `Claude · ${model}` : "Engine only (no API key)"}</span>
        <button disabled={busy} onClick={() => act(() => analyzeNow(state.world), "Analysis started")}>
          ✨ Analyze now
        </button>
      </div>

      {!run && <p className="muted">Inject an event or click “Analyze now”: recommendations appear here.</p>}

      {run && (
        <>
          <div className="run-status">
            {run.status === "running" ? (
              <span>
                <span className="spinner" /> Analysing {run.event_id ?? "situation"}… {elapsed}s
              </span>
            ) : (
              <span className="muted">
                {run.id} · {run.event_id ?? run.trigger} · {run.status}
                {run.engine === "engine_fallback" ? " · engine fallback" : ""}
              </span>
            )}
          </div>

          {(run.status === "running" || !rec) && (
            <ul className="trace">
              {run.steps.slice(-8).map((s, i) => (
                <li key={i} className={`trace-${s.kind}`}>
                  {STEP_ICON[s.kind]} {s.kind === "reasoning" ? s.text.slice(0, 180) + (s.text.length > 180 ? "…" : "") : s.text}
                </li>
              ))}
            </ul>
          )}

          {rec && (
            <div className="rec">
              {run.engine === "engine_fallback" && <div className="warn-box">⚠ {run.error ?? "Claude unavailable"}: showing the engine's own plan.</div>}
              <p className="situation">{rec.situation}</p>
              {rec.escalation && <div className="escalation">🚨 {rec.escalation}</div>}
              {rec.options.length === 0 && <p className="muted">No action needed.</p>}
              {rec.options.map((o, i) => (
                <OptionCard
                  key={i}
                  run={run}
                  option={o}
                  index={i}
                  before={rec.kpis_before}
                  busy={busy}
                  onApprove={(idx) => act(() => approveOption(state.world, run.id, idx), `Option ${idx + 1} applied`)}
                />
              ))}
              {rec.reasoning && <p className="reasoning">💡 {rec.reasoning}</p>}
              {rec.notifications.length > 0 && (
                <details className="notifications">
                  <summary>Notification drafts ({rec.notifications.length})</summary>
                  {rec.notifications.map((n, i) => (
                    <div key={i} className="notification">
                      <strong>{n.recipient}</strong>
                      <div>🇸🇮 {n.message_sl}</div>
                      <div className="muted">🇬🇧 {n.message_en}</div>
                    </div>
                  ))}
                </details>
              )}
              <details className="notifications">
                <summary>How the agent got here ({run.steps.length} steps)</summary>
                <ul className="trace">
                  {run.steps.map((s, i) => (
                    <li key={i} className={`trace-${s.kind}`}>
                      {STEP_ICON[s.kind]} {s.text}
                    </li>
                  ))}
                </ul>
              </details>
              {run.status === "done" && (
                <button className="ghost" disabled={busy} onClick={() => act(() => rejectRun(state.world, run.id), "Recommendation rejected")}>
                  Reject all
                </button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
