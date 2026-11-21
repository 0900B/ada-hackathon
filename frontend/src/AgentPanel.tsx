import { useEffect, useRef, useState, type RefObject } from "react";
import {
  analyzeNow,
  approveOption,
  idSeq,
  rejectRun,
  SCENARIOS,
  setAgentAuto,
  type AgentRun,
  type AgentStep,
  type EventRecord,
  type Kpis,
  type PlanStep,
  type Recommendation,
  type RecommendationOption,
  type WorldSnapshot,
} from "./api";
import { fmtTime } from "./format";

type Notify = (kind: "ok" | "error", text: string) => void;

/** What the dashboard's hotkeys (A, Y, N) call; the panel owns the rules (e.g. no approving stale plans). */
export interface AgentKeys {
  analyse: () => void;
  approveRecommended: () => void;
  reject: () => void;
}

const COLLAPSE_AFTER_MS = 20_000; // a decided run shows its outcome this long, then moves to history
const STALE_AFTER_MIN = 10; // an undecided plan older than this (world clock) is not offered for approval

const STEP_ICON: Record<AgentStep["kind"], string> = {
  info: "ℹ",
  reasoning: "💭",
  tool_call: "🔎",
  tool_result: "📊",
  error: "⚠",
};

const unassigned = (k: Kpis) => k.unassigned.emergency + k.unassigned.urgent + k.unassigned.scheduled;

/** Events that call for a new analysis (not the operator's own decisions or all-clears). */
function needsAnalysis(e: EventRecord): boolean {
  if (e.type === "plan_applied" || e.type === "clear_incident") return false;
  if (e.type === "weather_override" && /cleared/i.test(e.summary)) return false;
  if (e.type === "hospital_capacity" && /limit lifted/i.test(e.summary)) return false;
  if (e.type === "task_request") return /left for the AI/i.test(e.summary); // placed bookings need nothing
  return true;
}

function Delta({ label, before, after, unit = "" }: { label: string; before: number; after: number; unit?: string }) {
  const cls = after < before ? "better" : after > before ? "worse" : "same";
  return (
    <span className={`delta ${cls}`}>
      {label} <strong>{Math.round(before)}</strong> → <strong>{Math.round(after)}</strong>
      {unit}
    </span>
  );
}

/** What started this analysis, in one line: a field message, a scenario, an event or the operator. */
function RunContext({ run, state }: { run: AgentRun; state: WorldSnapshot }) {
  if (run.trigger === "message" && run.question) {
    const m = /^Field message: "([\s\S]*)"\. Understood as: ([\s\S]*)$/.exec(run.question);
    return (
      <div className="run-context">
        💬 <q>{m ? m[1] : run.question}</q>
        {m && <div className="muted">Understood: {m[2]}</div>}
      </div>
    );
  }
  if (run.trigger.startsWith("scenario:")) {
    const name = run.trigger.slice("scenario:".length);
    return <div className="run-context">🎬 Scenario: {SCENARIOS.find((s) => s.name === name)?.title ?? name}</div>;
  }
  const event = run.event_id ? state.events.find((e) => e.id === run.event_id) : undefined;
  if (event) return <div className="run-context">⚡ {event.summary}</div>;
  return <div className="run-context">👤 Operator review{run.question ? `: ${run.question}` : ""}</div>;
}

function StepLine({ step, state }: { step: PlanStep; state: WorldSnapshot }) {
  const trip = state.trips.find((t) => t.id === step.trip_id);
  const place = (id: string) => state.places.find((p) => p.id === id)?.name ?? id;
  const where = step.interrupt_current
    ? "divert now"
    : step.position === null
      ? "end of its queue"
      : step.position === 0
        ? "next"
        : `#${step.position + 1} in queue`;
  return (
    <li>
      <span className="step-trip">{step.trip_id}</span>
      {trip && <span className="muted"> {trip.label}</span>} → <span className="step-veh">{step.vehicle_id}</span>{" "}
      <span className="muted">({where})</span>
      {step.dropoff_id && <span className="step-redirect"> · to {place(step.dropoff_id)}</span>}
    </li>
  );
}

function Notifications({ rec, open }: { rec: Recommendation; open?: boolean }) {
  if (rec.notifications.length === 0) return null;
  return (
    <details className="more" open={open}>
      <summary>📨 Messages to crews and hospitals ({rec.notifications.length})</summary>
      {rec.notifications.map((n, i) => (
        <div key={i} className="notification">
          <strong>{n.recipient}</strong>
          <div>🇸🇮 {n.message_sl}</div>
          <div className="muted">🇬🇧 {n.message_en}</div>
        </div>
      ))}
    </details>
  );
}

function OptionCard({
  run,
  option,
  index,
  before,
  state,
  canApprove,
  onApprove,
  busy,
}: {
  run: AgentRun;
  option: RecommendationOption;
  index: number;
  before: Kpis | null;
  state: WorldSnapshot;
  canApprove: boolean;
  onApprove: (i: number) => void;
  busy: boolean;
}) {
  const rec = run.recommendation!;
  const recommended = index === rec.recommended_index;
  const approved = run.status === "approved" && run.decision?.option_index === index;
  const after = option.kpis_after;
  return (
    <div className={`option${recommended ? " recommended" : ""}${approved ? " approved" : ""}${option.feasible === false ? " infeasible" : ""}`}>
      <div className="option-head">
        <span className="option-num">{index + 1}</span>
        <strong className="option-title">{option.title}</strong>
        {recommended && <span className="badge">Recommended</span>}
        {approved && <span className="badge ok">✓ Approved</span>}
      </div>
      {option.summary && <p className="option-summary">{option.summary}</p>}
      {before && after && (
        <div className="deltas">
          <Delta label="Late" before={before.late_trips} after={after.late_trips} />
          <Delta label="Delay" before={before.total_delay_min} after={after.total_delay_min} unit=" min" />
          <Delta label="Unassigned" before={unassigned(before)} after={unassigned(after)} />
          {(before.over_capacity > 0 || after.over_capacity > 0) && (
            <Delta label="Over capacity" before={before.over_capacity} after={after.over_capacity} />
          )}
        </div>
      )}
      {option.steps.length > 0 && (
        <ul className="plan-steps">
          {option.steps.map((s, i) => (
            <StepLine key={i} step={s} state={state} />
          ))}
        </ul>
      )}
      {option.feasible === false && <div className="warn-box">Not feasible now: {option.errors.join("; ")}</div>}
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
      {canApprove && option.feasible !== false && (
        <button className={`approve${recommended ? " primary" : ""}`} disabled={busy} onClick={() => onApprove(index)}>
          ✓ Approve option {index + 1}
          {recommended && <kbd>Y</kbd>}
        </button>
      )}
    </div>
  );
}

/** Situation, options and the agent's notes of a finished run (read-only when canApprove is false). */
function RecommendationView({
  run,
  state,
  busy,
  canApprove,
  onApprove,
}: {
  run: AgentRun;
  state: WorldSnapshot;
  busy: boolean;
  canApprove: boolean;
  onApprove: (i: number) => void;
}) {
  const rec = run.recommendation!;
  return (
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
          state={state}
          busy={busy}
          canApprove={canApprove}
          onApprove={onApprove}
        />
      ))}
      {rec.reasoning && <p className="reasoning">💡 {rec.reasoning}</p>}
      <Notifications rec={rec} />
      <details className="more">
        <summary>How the agent got here ({run.steps.length} steps)</summary>
        <ul className="trace">
          {run.steps.map((s, i) => (
            <li key={i} className={`trace-${s.kind}`}>
              {STEP_ICON[s.kind]} {s.text}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

export function AgentPanel({
  state,
  notify,
  keysRef,
}: {
  state: WorldSnapshot;
  notify: Notify;
  keysRef?: RefObject<AgentKeys | null>;
}) {
  const [busy, setBusy] = useState(false);
  const [staleRuns, setStaleRuns] = useState<ReadonlySet<string>>(() => new Set());
  const [showLast, setShowLast] = useState(false);
  const [autoSupported, setAutoSupported] = useState(true);
  const [autoPending, setAutoPending] = useState<boolean | null>(null);
  const [, rerender] = useState(0);
  // Per run: when this client saw it finish (world clock) and get decided (wall clock)
  const seen = useRef(new Map<string, { sawRunning?: boolean; sawUndecided?: boolean; doneSim?: number; decidedAt?: number }>());

  const { enabled, model, runs } = state.agent;
  const run = runs[0];
  const rec = run?.recommendation ?? null;
  const simNow = Date.parse(state.sim_time);
  const now = Date.now();

  // --- lifecycle bookkeeping (idempotent, so it is safe during render) ---
  let info: { sawRunning?: boolean; sawUndecided?: boolean; doneSim?: number; decidedAt?: number } | undefined;
  if (run) {
    info = seen.current.get(run.id);
    if (!info) seen.current.set(run.id, (info = {}));
    if (run.status === "running") info.sawRunning = true;
    if (run.status === "done" && info.doneSim === undefined) {
      // Watched it finish: now. Loaded the page later: estimate from the wall-clock finish time.
      const finished = Date.parse(run.finished_at ?? "");
      const lateBy = info.sawRunning || Number.isNaN(finished) ? 0 : Math.max(0, now - finished) * state.speedup;
      info.doneSim = simNow - lateBy;
    }
  }
  const hasOptions = (rec?.options.length ?? 0) > 0;
  const undecided = run?.status === "done" && hasOptions;
  const finished = run !== undefined && run.status !== "running" && !undecided; // decided, failed or nothing to do
  if (run && info) {
    if (undecided || run.status === "running") info.sawUndecided = true;
    if (finished && info.decidedAt === undefined) {
      const at = Date.parse(run.decision?.at ?? run.finished_at ?? "");
      info.decidedAt = info.sawUndecided ? now : Number.isNaN(at) ? now - COLLAPSE_AFTER_MS : Math.min(now, at);
    }
  }
  const shownFor = finished && info?.decidedAt !== undefined ? now - info.decidedAt : 0;
  const collapsed = finished && shownFor >= COLLAPSE_AFTER_MS;
  const ageMin = undecided && info?.doneSim !== undefined ? Math.max(0, (simNow - info.doneSim) / 60000) : 0;
  const stale = undecided && run !== undefined && (ageMin > STALE_AFTER_MIN || staleRuns.has(run.id));

  // Re-render when the outcome should collapse (snapshots usually arrive anyway; this makes it exact)
  useEffect(() => {
    if (!finished || collapsed) return;
    const timer = setTimeout(() => rerender((n) => n + 1), COLLAPSE_AFTER_MS - shownFor + 50);
    return () => clearTimeout(timer);
  }, [finished, collapsed, shownFor, run?.id]);
  useEffect(() => setShowLast(false), [run?.id]);

  // Something happened since the last analysis (only matters while auto-analysis is off)
  const auto = autoPending ?? state.agent.auto;
  useEffect(() => {
    if (autoPending !== null && state.agent.auto === autoPending) setAutoPending(null);
  }, [autoPending, state.agent.auto]);
  const lastRunSeq = idSeq(run?.id);
  const newEvents = state.events.filter((e) => idSeq(e.id) > lastRunSeq && needsAnalysis(e));
  const showCta = !auto && newEvents.length > 0 && run?.status !== "running";

  const act = async (fn: () => Promise<unknown>, ok: string, runId?: string) => {
    setBusy(true);
    try {
      await fn();
      notify("ok", ok);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (runId && /no longer valid/i.test(msg)) setStaleRuns((s) => new Set(s).add(runId));
      notify("error", msg);
    } finally {
      setBusy(false);
    }
  };
  const analyse = () => act(() => analyzeNow(state.world), "Analysis started");
  const approve = (i: number) => {
    if (!run || !rec) return;
    void act(() => approveOption(state.world, run.id, i), `Option ${i + 1} approved and applied: ${rec.options[i].title}`, run.id);
  };
  const reject = () => run && act(() => rejectRun(state.world, run.id), "Recommendation rejected");

  const toggleAuto = async () => {
    const want = !auto;
    setAutoPending(want);
    try {
      const r = await setAgentAuto(state.world, want);
      if (r === "unsupported") {
        setAutoSupported(false);
        setAutoPending(null);
        notify("ok", "This backend has no auto-analyse switch yet; analyses follow its default.");
      } else {
        setAutoPending(r.auto);
        notify("ok", r.auto ? "Auto-analyse on: every disruptive event starts an analysis" : "Auto-analyse off: press A to analyse");
      }
    } catch (e) {
      setAutoPending(null);
      notify("error", e instanceof Error ? e.message : String(e));
    }
  };

  // Hotkeys A / Y / N (bound in App.tsx) go through the same rules as the buttons
  useEffect(() => {
    if (!keysRef) return;
    keysRef.current = {
      analyse: () => void analyse(),
      approveRecommended: () => {
        if (!run || run.status === "running") return notify("error", run ? "The AI is still analysing." : "Nothing to approve yet.");
        if (!undecided || !rec) return notify("error", "No recommendation waiting for approval.");
        if (stale) return notify("error", "This plan is outdated: press A to re-analyse.");
        const i = rec.recommended_index;
        if (!rec.options[i] || rec.options[i].feasible === false) return notify("error", "The recommended option is not feasible.");
        approve(i);
      },
      reject: () => {
        if (!undecided) return notify("error", "No recommendation waiting for a decision.");
        void reject();
      },
    };
  });

  const inService = state.vehicles.filter((v) => v.status !== "out_of_service").length;
  const k = state.kpis;
  const issues = [
    unassigned(k) > 0 && `${unassigned(k)} unassigned`,
    k.late_trips > 0 && `${k.late_trips} late`,
    k.over_capacity > 0 && `${k.over_capacity} over hospital capacity`,
  ].filter(Boolean) as string[];
  // When it was decided, on the world's clock (the applied plan's event), else the wall clock
  const decisionEvent = run?.decision?.event_id ? state.events.find((e) => e.id === run.decision?.event_id) : undefined;
  const decisionTime = decisionEvent ? fmtTime(decisionEvent.sim_time) : run?.decision?.at ? fmtTime(run.decision.at) : "";
  const approvedOption = run?.status === "approved" && rec ? rec.options[run.decision?.option_index ?? -1] : undefined;

  return (
    <section className="panel panel-ai">
      <div className="panel-head">
        <h2 className="panel-title">AI dispatcher</h2>
        <button className={`analyze${showCta ? " primary" : ""}`} disabled={busy} onClick={() => void analyse()} title="Hotkey A">
          ✨ Analyse <kbd>A</kbd>
        </button>
      </div>
      <div className="agent-meta">
        <span className={`chip ${enabled ? "ok" : "warn"}`} title={enabled ? model : "No ANTHROPIC_API_KEY: the engine's own plan is shown"}>
          {enabled ? `Claude · ${model}` : "Engine only"}
        </span>
        {autoSupported && (
          <label className="switch" title="Start an AI analysis automatically after every disruptive event">
            <input type="checkbox" role="switch" checked={auto} onChange={() => void toggleAuto()} />
            <span className="switch-track" aria-hidden />
            Auto-analyse {auto ? "on" : "off"}
          </label>
        )}
      </div>

      {showCta && (
        <button className="cta" onClick={() => void analyse()} disabled={busy}>
          <span className="cta-title">
            ⚡ {newEvents.length === 1 ? "New event" : `${newEvents.length} new events`} · Analyse <kbd>A</kbd>
          </span>
          <span className="cta-text">{newEvents[newEvents.length - 1].summary}</span>
        </button>
      )}

      {(!run || collapsed) && (
        <div className="agent-idle">
          <div className="idle-line">
            👁 Watching {inService} vehicles · {issues.length ? `${issues.join(" · ")} · press A to analyse` : "no open issues"}
          </div>
          {run && (
            <button className="link last-run" onClick={() => setShowLast((s) => !s)} aria-expanded={showLast}>
              {showLast ? "▾" : "▸"}{" "}
              {run.status === "approved"
                ? `✓ Approved ${decisionTime}: ${run.decision?.title ?? "plan"}`
                : run.status === "rejected"
                  ? `✕ Rejected ${decisionTime}`
                  : `Last analysis ${run.id}: ${rec?.options.length ? `${run.status}` : "no action needed"}`}
            </button>
          )}
          {run && showLast && rec && <RecommendationView run={run} state={state} busy={busy} canApprove={false} onApprove={approve} />}
          {!run && <p className="muted">Report an event or send a field message; the AI's options appear here.</p>}
        </div>
      )}

      {run && !collapsed && (
        <div className="agent">
          <RunContext run={run} state={state} />

          {run.status === "running" && (
            <>
              <div className="run-status st-running">
                <span className="spinner" />
                <strong>Analysing…</strong> {Math.max(0, Math.round((now - Date.parse(run.started_at)) / 1000))} s
                <span className="muted run-meta">{run.id}</span>
              </div>
              <ul className="trace">
                {run.steps.slice(-6).map((s, i) => (
                  <li key={i} className={`trace-${s.kind}`}>
                    {STEP_ICON[s.kind]} {s.kind === "reasoning" ? s.text.slice(0, 160) + (s.text.length > 160 ? "…" : "") : s.text}
                  </li>
                ))}
              </ul>
            </>
          )}

          {undecided && rec && (
            <>
              <div className="run-status st-done">
                <strong>Waiting for your decision</strong>
                <span className="muted">
                  {" "}
                  · proposed {ageMin < 1 ? "just now" : `${Math.round(ageMin)} min ago`}
                  {state.hypothetical && ageMin >= 1 ? " (sim time)" : ""}
                </span>
                <span className="muted run-meta">
                  {run.id}
                  {run.engine === "engine_fallback" ? " · engine" : " · Claude"}
                </span>
              </div>
              {stale && (
                <div className="stale-box">
                  ⏳ {staleRuns.has(run.id) ? "The fleet has moved on and this plan no longer fits." : `This plan is ${Math.round(ageMin)} min old; the fleet has moved on.`}{" "}
                  Re-analyse for a fresh plan.
                  <button className="primary" disabled={busy} onClick={() => void analyse()}>
                    ✨ Re-analyse <kbd>A</kbd>
                  </button>
                </div>
              )}
              <RecommendationView run={run} state={state} busy={busy} canApprove={!stale} onApprove={approve} />
              <button className="ghost reject" disabled={busy} onClick={() => void reject()}>
                ✕ {stale ? "Dismiss" : "Reject all"} <kbd>N</kbd>
              </button>
            </>
          )}

          {finished && (
            <div className={`decision st-${run.status}`}>
              <div className="decision-head">
                {run.status === "approved" ? (
                  <>
                    ✓ Approved: option {(run.decision?.option_index ?? 0) + 1} · {run.decision?.title}
                  </>
                ) : run.status === "rejected" ? (
                  <>✕ Rejected: the plan stays as it was</>
                ) : run.status === "error" ? (
                  <>⚠ The analysis failed: {run.error}</>
                ) : (
                  <>✓ {rec?.situation ?? "Analysis finished"}: no action needed</>
                )}
              </div>
              {approvedOption && approvedOption.steps.length > 0 && (
                <ul className="plan-steps">
                  {approvedOption.steps.map((s, i) => (
                    <StepLine key={i} step={s} state={state} />
                  ))}
                </ul>
              )}
              {run.status === "approved" && rec && <Notifications rec={rec} open />}
              <div className="muted small">
                Moves to the history in {Math.max(0, Math.ceil((COLLAPSE_AFTER_MS - shownFor) / 1000))} s ·{" "}
                <button
                  className="link"
                  onClick={() => {
                    if (info) info.decidedAt = 0;
                    rerender((n) => n + 1);
                  }}
                >
                  hide now
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
