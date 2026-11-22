import { useEffect, useRef, useState, type RefObject } from "react";
import {
  analyzeNow,
  approveOption,
  generalRun,
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
  type StepDetail,
  type WorldSnapshot,
} from "./api";
import {
  Ban,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Clapperboard,
  Clock,
  Eye,
  Info,
  Lightbulb,
  MessageSquare,
  RefreshCw,
  Search,
  Siren,
  Sparkles,
  Table2,
  TriangleAlert,
  User,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { fmtTime } from "./format";
import { tOr, useLang, useT } from "./i18n";
import { SeverityBadge } from "./SeverityBadge";

type Notify = (kind: "ok" | "error", text: string) => void;

/** What the dashboard's hotkeys (A, Y, N) call; the panel owns the rules (e.g. no approving stale plans). */
export interface AgentKeys {
  analyse: () => void;
  approveRecommended: () => void;
  reject: () => void;
}

const COLLAPSE_AFTER_MS = 20_000; // a decided run shows its outcome this long, then moves to history
const STALE_AFTER_MIN = 10; // an undecided plan older than this (world clock) is not offered for approval

const STEP_ICON: Record<AgentStep["kind"], LucideIcon> = {
  info: Info,
  reasoning: Lightbulb,
  tool_call: Search,
  tool_result: Table2,
  error: TriangleAlert,
};

function TraceLine({ step, clip }: { step: AgentStep; clip?: number }) {
  const Icon = STEP_ICON[step.kind];
  const text = clip && step.kind === "reasoning" && step.text.length > clip ? step.text.slice(0, clip) + "…" : step.text;
  return (
    <li className={`trace-${step.kind}`}>
      <Icon /> <span>{text}</span>
    </li>
  );
}

const unassigned = (k: Kpis) => k.unassigned.emergency + k.unassigned.urgent + k.unassigned.scheduled;

/** Events that call for a new analysis (not the operator's own decisions or all-clears). A call
 * from the live-calls stream only counts while it is a problem: still without a unit, or late. */
function needsAnalysis(e: EventRecord, state: WorldSnapshot): boolean {
  if (e.generated) {
    return e.affected_trip_ids.some((id) => {
      const t = state.trips.find((x) => x.id === id);
      return t !== undefined && (t.status === "unassigned" || (t.delay_min ?? 0) >= 5);
    });
  }
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

/** The recommendation's situation summary: long texts start clamped to three lines, click to expand. */
function Situation({ text }: { text: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const long = text.length > 220;
  return (
    <p
      className={`situation${long && !open ? " clamp-3" : ""}${long ? " expandable" : ""}`}
      title={long && !open ? t("ai.rev.fullText") : undefined}
      onClick={long ? () => setOpen((o) => !o) : undefined}
    >
      {text}
    </p>
  );
}

/** What started this analysis, in one line: a field message, a scenario, an event or the operator. */
function RunContext({ run, state }: { run: AgentRun; state: WorldSnapshot }) {
  const t = useT();
  if (run.trigger === "message" && run.question) {
    const m = /^Field message: "([\s\S]*)"\. Understood as: ([\s\S]*)$/.exec(run.question);
    return (
      <div className="run-context">
        <MessageSquare />
        <div>
          <q>{m ? m[1] : run.question}</q>
          {m && <div className="muted">{t("ai.rev.understood", { text: m[2] })}</div>}
        </div>
      </div>
    );
  }
  if (run.trigger.startsWith("scenario:")) {
    const name = run.trigger.slice("scenario:".length);
    return (
      <div className="run-context">
        <Clapperboard />{" "}
        <span>{t("ai.rev.scenario", { title: tOr(`dash.scn.${name}.title`, SCENARIOS.find((s) => s.name === name)?.title ?? name) })}</span>
      </div>
    );
  }
  const event = run.event_id ? state.events.find((e) => e.id === run.event_id) : undefined;
  if (event)
    return (
      <div className="run-context">
        <Zap /> <span>{event.summary}</span>
      </div>
    );
  // An analysis right after a scenario carries the scenario's description: show just its title
  const scenario = run.question ? /^Demo scenario: (.+?)\. These events/.exec(run.question) : null;
  if (scenario)
    return (
      <div className="run-context" title={run.question ?? undefined}>
        <Clapperboard /> <span>{t("ai.rev.scenario", { title: scenario[1] })}</span>
      </div>
    );
  return (
    <div className="run-context" title={run.question ?? undefined}>
      <User /> <span className="clamp-2">{run.question ? t("ai.rev.operatorQ", { q: run.question }) : t("ai.rev.operator")}</span>
    </div>
  );
}

function StepLine({ step, state, detail }: { step: PlanStep; state: WorldSnapshot; detail?: StepDetail }) {
  const t = useT();
  const trip = state.trips.find((x) => x.id === step.trip_id);
  const place = (id: string) => state.places.find((p) => p.id === id)?.name ?? id;
  if (detail) {
    // The engine's own sentence for what this step does once the whole option is applied
    const late = (detail.delay_min ?? 0) > 0;
    return (
      <li className={late ? "step-late" : undefined}>
        <span className="step-trip">{step.trip_id}</span>{" "}
        {trip && (
          <>
            <SeverityBadge trip={trip} weight={false} modifiers={false} /> <span className="muted">·</span>{" "}
          </>
        )}
        {detail.text}
        {step.dropoff_id && !detail.text.includes(place(step.dropoff_id)) && (
          <span className="step-redirect">{t("ai.rev.to", { place: place(step.dropoff_id) })}</span>
        )}
      </li>
    );
  }
  const where = step.interrupt_current
    ? t("ai.rev.divert")
    : step.position === null
      ? t("ai.rev.endQueue")
      : step.position === 0
        ? t("ai.rev.next")
        : t("ai.rev.queuePos", { n: step.position + 1 });
  return (
    <li>
      <span className="step-trip">{step.trip_id}</span> {trip && <SeverityBadge trip={trip} weight={false} modifiers={false} />}
      {trip && <span className="muted"> {trip.label}</span>} → <span className="step-veh">{step.vehicle_id}</span>{" "}
      <span className="muted">({where})</span>
      {step.dropoff_id && <span className="step-redirect">{t("ai.rev.to", { place: place(step.dropoff_id) })}</span>}
    </li>
  );
}

function Notifications({ rec, open }: { rec: Recommendation; open?: boolean }) {
  const t = useT();
  const lang = useLang();
  if (rec.notifications.length === 0) return null;
  return (
    <details className="more" open={open}>
      <summary>{t("ai.rev.messages", { n: rec.notifications.length })}</summary>
      {rec.notifications.map((n, i) => {
        // Both languages, the UI language first
        const lines = [
          { lang: "sl", text: n.message_sl },
          { lang: "en", text: n.message_en },
        ].filter((x) => x.text);
        if (lang === "en") lines.reverse();
        return (
          <div key={i} className="notification">
            <strong>{n.recipient}</strong>
            {lines.map((x, j) => (
              <div key={x.lang} className={j > 0 ? "muted" : undefined}>
                <span className="lang-tag">{x.lang.toUpperCase()}</span>
                {x.text}
              </div>
            ))}
          </div>
        );
      })}
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
  const t = useT();
  const rec = run.recommendation!;
  const recommended = index === rec.recommended_index;
  const approved = run.status === "approved" && run.decision?.option_index === index;
  const after = option.kpis_after;
  return (
    <div className={`option${recommended ? " recommended" : ""}${approved ? " approved" : ""}${option.feasible === false ? " infeasible" : ""}`}>
      <div className="option-head">
        <span className="option-num">{index + 1}</span>
        <strong className="option-title">{option.title}</strong>
        {recommended && <span className="badge">{t("ai.rev.recommended")}</span>}
        {approved && (
          <span className="badge ok">
            <Check /> {t("ai.rev.approved")}
          </span>
        )}
      </div>
      {option.summary && <p className="option-summary">{option.summary}</p>}
      {before && after && (
        <div className="deltas">
          <Delta label={t("ai.rev.dLate")} before={before.late_trips} after={after.late_trips} />
          <Delta label={t("ai.rev.dDelay")} before={before.total_delay_min} after={after.total_delay_min} unit=" min" />
          <Delta label={t("ai.rev.dUnassigned")} before={unassigned(before)} after={unassigned(after)} />
          {(before.over_capacity > 0 || after.over_capacity > 0) && (
            <Delta label={t("ai.rev.dOverCapacity")} before={before.over_capacity} after={after.over_capacity} />
          )}
        </div>
      )}
      {option.steps.length > 0 && (
        <ul className="plan-steps">
          {option.steps.map((s, i) => (
            <StepLine
              key={i}
              step={s}
              state={state}
              detail={option.step_details?.find((d) => d.trip_id === s.trip_id && d.vehicle_id === s.vehicle_id)}
            />
          ))}
        </ul>
      )}
      {option.feasible === false && <div className="warn-box">{t("ai.rev.notFeasible", { errors: option.errors.join("; ") })}</div>}
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
          <Check /> {t("ai.rev.approveOption", { n: index + 1 })}
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
  const t = useT();
  const rec = run.recommendation!;
  return (
    <div className="rec">
      {run.engine === "engine_fallback" && (
        <div className="warn-box">
          <TriangleAlert /> <span>{t("ai.rev.fallback", { error: run.error ?? t("ai.rev.claudeUnavailable") })}</span>
        </div>
      )}
      <Situation text={rec.situation} />
      {rec.escalation && (
        <div className="escalation">
          <Siren /> <span>{rec.escalation}</span>
        </div>
      )}
      {rec.options.length === 0 && <p className="muted">{t("ai.rev.noActionDot")}</p>}
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
      {rec.reasoning && (
        <p className="reasoning">
          <Lightbulb /> <span>{rec.reasoning}</span>
        </p>
      )}
      <Notifications rec={rec} />
      <details className="more">
        <summary>{t("ai.rev.trace", { count: run.steps.length })}</summary>
        <ul className="trace">
          {run.steps.map((s, i) => (
            <TraceLine key={i} step={s} />
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
  bare = false,
}: {
  state: WorldSnapshot;
  notify: Notify;
  keysRef?: RefObject<AgentKeys | null>;
  bare?: boolean; // inside the AI dispatcher tab's "Situation review": no panel frame or title of its own
}) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [staleRuns, setStaleRuns] = useState<ReadonlySet<string>>(() => new Set());
  const [showLast, setShowLast] = useState(false);
  const [autoSupported, setAutoSupported] = useState(true);
  const [autoPending, setAutoPending] = useState<boolean | null>(null);
  const [, rerender] = useState(0);
  // Per run: when this client saw it finish (world clock) and get decided (wall clock)
  const seen = useRef(new Map<string, { sawRunning?: boolean; sawUndecided?: boolean; doneSim?: number; decidedAt?: number }>());

  const { enabled, model, runs } = state.agent;
  const run = generalRun(runs); // case reviews (review_of set) stay on their case cards
  const rec = run?.recommendation ?? null;
  const simNow = Date.parse(state.sim_time);
  const now = Date.now();

  // --- lifecycle bookkeeping (idempotent, so it is safe during render) ---
  let info: { sawRunning?: boolean; sawUndecided?: boolean; doneSim?: number; decidedAt?: number } | undefined;
  if (run) {
    // run ids restart when the backend restarts (the page survives that): key by id + start time
    const runKey = `${run.id}@${run.started_at}`;
    info = seen.current.get(runKey);
    if (!info) seen.current.set(runKey, (info = {}));
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
  const newEvents = state.events.filter((e) => idSeq(e.id) > lastRunSeq && needsAnalysis(e, state));
  const showCta = !auto && newEvents.length > 0 && run?.status !== "running";

  const act = async (fn: () => Promise<unknown>, ok: string, runId?: string) => {
    setBusy(true);
    try {
      await fn();
      notify("ok", ok);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      // 409 from the backend: "Plan no longer valid ..." or "Plan is out of date ..."
      if (runId && /no longer valid|out of date/i.test(msg)) setStaleRuns((s) => new Set(s).add(runId));
      notify("error", msg);
    } finally {
      setBusy(false);
    }
  };
  const analyse = () => act(() => analyzeNow(state.world), t("ai.rev.started"));
  // A second Y (or click) before the snapshot shows the run as approved would get "Run … is approved;
  // nothing to approve" and replace the success toast with an error: approve each run once (keyed by id +
  // start time: run ids restart when the backend restarts)
  const approving = useRef(new Set<string>());
  const approve = (i: number) => {
    if (!run || !rec) return;
    const id = run.id;
    const key = `${id}@${run.started_at}`;
    if (approving.current.has(key)) return;
    approving.current.add(key);
    void act(
      () => approveOption(state.world, id, i).catch((e) => {
        approving.current.delete(key); // refused (e.g. out of date): it may be tried again
        throw e;
      }),
      t("ai.rev.optionApplied", { n: i + 1, title: rec.options[i].title }),
      id,
    );
  };
  const reject = () => run && act(() => rejectRun(state.world, run.id), t("ai.rev.rejectedToast"));

  const toggleAuto = async () => {
    const want = !auto;
    setAutoPending(want);
    try {
      const r = await setAgentAuto(state.world, want);
      if (r === "unsupported") {
        setAutoSupported(false);
        setAutoPending(null);
        notify("ok", t("ai.rev.noAutoSwitch"));
      } else {
        setAutoPending(r.auto);
        notify("ok", t(r.auto ? "ai.rev.autoOnToast" : "ai.rev.autoOffToast"));
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
        if (!run || run.status === "running") return notify("error", t(run ? "ai.rev.stillAnalysing" : "ai.rev.nothingYet"));
        if (!undecided || !rec) return notify("error", t("ai.rev.noRecApproval"));
        if (stale) return notify("error", t("ai.rev.outdated"));
        const i = rec.recommended_index;
        if (!rec.options[i] || rec.options[i].feasible === false) return notify("error", t("ai.rev.notFeasibleRec"));
        approve(i);
      },
      reject: () => {
        if (!undecided) return notify("error", t("ai.rev.noRecDecision"));
        void reject();
      },
    };
  });

  const inService = state.vehicles.filter((v) => v.status !== "out_of_service").length;
  const k = state.kpis;
  const issues = [
    unassigned(k) > 0 && t("ai.rev.unassigned", { n: unassigned(k) }),
    k.late_trips > 0 && t("ai.rev.late", { n: k.late_trips }),
    k.over_capacity > 0 && t("ai.rev.overCapacity", { n: k.over_capacity }),
  ].filter(Boolean) as string[];
  // When it was decided, on the world's clock (the applied plan's event), else the wall clock
  const decisionEvent = run?.decision?.event_id ? state.events.find((e) => e.id === run.decision?.event_id) : undefined;
  const decisionTime = decisionEvent ? fmtTime(decisionEvent.sim_time) : run?.decision?.at ? fmtTime(run.decision.at) : "";
  const approvedOption = run?.status === "approved" && rec ? rec.options[run.decision?.option_index ?? -1] : undefined;

  return (
    <section className={bare ? "panel-ai bare" : "panel panel-ai"}>
      <div className="panel-head">
        {bare ? (
          <span className="muted small review-hint">{t("ai.rev.hint")}</span>
        ) : (
          <h2 className="panel-title">{t("ai.review")}</h2>
        )}
        <button className={`analyze${showCta ? " primary" : ""}`} disabled={busy} onClick={() => void analyse()} title={t("ai.rev.hotkeyA")}>
          <Sparkles /> {t("ai.rev.analyse")} <kbd>A</kbd>
        </button>
      </div>
      <div className="agent-meta">
        <span className={`chip ${enabled ? "ok" : "warn"}`} title={enabled ? model : t("ai.rev.noKey")}>
          {enabled ? `Claude · ${model}` : t("ai.rev.engineOnly")}
        </span>
        {autoSupported && (
          <label className="switch" title={t("ai.rev.autoTitle")}>
            <input type="checkbox" role="switch" checked={auto} onChange={() => void toggleAuto()} />
            <span className="switch-track" aria-hidden />
            {t(auto ? "ai.rev.autoOn" : "ai.rev.autoOff")}
          </label>
        )}
      </div>

      {showCta && (
        <button className="cta" onClick={() => void analyse()} disabled={busy}>
          <span className="cta-title">
            <Zap /> {t("ai.rev.newEvents", { count: newEvents.length })} · {t("ai.rev.analyse")} <kbd>A</kbd>
          </span>
          <span className="cta-text">{newEvents[newEvents.length - 1].summary}</span>
        </button>
      )}

      {(!run || collapsed) && (
        <div className="agent-idle">
          <div className="idle-line">
            <Eye /> {t("ai.rev.watching", { count: inService })} ·{" "}
            {issues.length ? `${issues.join(" · ")}${t("ai.rev.pressA")}` : t("ai.rev.noIssues")}
          </div>
          {run && (
            <button className="link last-run" onClick={() => setShowLast((s) => !s)} aria-expanded={showLast}>
              {showLast ? <ChevronDown /> : <ChevronRight />}
              {run.status === "approved"
                ? t("ai.rev.lastApproved", { time: decisionTime, title: run.decision?.title ?? t("ai.sum.plan") })
                : run.status === "rejected"
                  ? t("ai.rev.lastRejected", { time: decisionTime })
                  : t("ai.rev.lastAnalysis", {
                      id: run.id,
                      status: rec?.options.length ? tOr(`ai.run.${run.status}`, run.status) : t("ai.rev.noActionLower"),
                    })}
            </button>
          )}
          {run && showLast && rec && <RecommendationView run={run} state={state} busy={busy} canApprove={false} onApprove={approve} />}
          {!run && <p className="muted">{t("ai.rev.empty")}</p>}
        </div>
      )}

      {run && !collapsed && (
        <div className="agent">
          <RunContext run={run} state={state} />

          {run.status === "running" && (
            <>
              <div className="run-status st-running">
                <span className="spinner" />
                <strong>{t("ai.sum.analysing")}</strong> {Math.max(0, Math.round((now - Date.parse(run.started_at)) / 1000))} s
                <span className="muted run-meta">{run.id}</span>
              </div>
              <ul className="trace">
                {run.steps.slice(-6).map((s, i) => (
                  <TraceLine key={i} step={s} clip={160} />
                ))}
              </ul>
            </>
          )}

          {undecided && rec && (
            <>
              <div className="run-status st-done">
                <strong>{t("ai.rev.waiting")}</strong>
                <span className="muted">
                  {ageMin < 1 ? t("ai.rev.proposedNow") : t("ai.rev.proposedAgo", { n: Math.round(ageMin) })}
                  {state.hypothetical && ageMin >= 1 ? t("ai.rev.simTime") : ""}
                </span>
                <span className="muted run-meta">
                  {run.id}
                  {run.engine === "engine_fallback" ? t("ai.rev.byEngine") : " · Claude"}
                </span>
              </div>
              {stale && (
                <div className="stale-box">
                  <Clock /> {staleRuns.has(run.id) ? t("ai.rev.staleGone") : t("ai.rev.staleOld", { n: Math.round(ageMin) })}{" "}
                  {t("ai.rev.reanalyseHint")}
                  <button className="primary" disabled={busy} onClick={() => void analyse()}>
                    <RefreshCw /> {t("ai.rev.reanalyse")} <kbd>A</kbd>
                  </button>
                </div>
              )}
              <RecommendationView run={run} state={state} busy={busy} canApprove={!stale} onApprove={approve} />
              <button className="ghost reject" disabled={busy} onClick={() => void reject()}>
                <X /> {t(stale ? "ai.rev.dismiss" : "ai.rev.rejectAll")} <kbd>N</kbd>
              </button>
            </>
          )}

          {finished && (
            <div className={`decision st-${run.status}`}>
              <div className="decision-head">
                {run.status === "approved" ? (
                  <>
                    <Check /> {t("ai.rev.approvedOption", { n: (run.decision?.option_index ?? 0) + 1, title: run.decision?.title ?? "" })}
                  </>
                ) : run.status === "rejected" ? (
                  <>
                    <Ban /> {t("ai.sum.rejected")}
                  </>
                ) : run.status === "error" ? (
                  <>
                    <CircleAlert /> {t("ai.rev.failed", { error: run.error ?? "" })}
                  </>
                ) : (
                  <>
                    <Check /> {t("ai.rev.noAction")}
                  </>
                )}
              </div>
              {run.status === "done" &&
                rec?.situation &&
                rec.situation !== state.events.find((e) => e.id === run.event_id)?.summary && (
                  <p className="muted small">{rec.situation}</p>
                )}
              {run.decision?.executed && run.decision.executed.length > 0 ? (
                // what each step did as it was applied (the engine's own wording)
                <ul className="plan-steps">
                  {run.decision.executed.map((text, i) => (
                    <li key={i}>{text}</li>
                  ))}
                </ul>
              ) : (
                approvedOption &&
                approvedOption.steps.length > 0 && (
                  <ul className="plan-steps">
                    {approvedOption.steps.map((s, i) => (
                      <StepLine
                        key={i}
                        step={s}
                        state={state}
                        detail={approvedOption.step_details?.find((d) => d.trip_id === s.trip_id && d.vehicle_id === s.vehicle_id)}
                      />
                    ))}
                  </ul>
                )
              )}
              {run.status === "approved" && rec && <Notifications rec={rec} open />}
              <div className="muted small">
                {t("ai.rev.history", { n: Math.max(0, Math.ceil((COLLAPSE_AFTER_MS - shownFor) / 1000)) })}{" "}
                <button
                  className="link"
                  onClick={() => {
                    if (info) info.decidedAt = 0;
                    rerender((n) => n + 1);
                  }}
                >
                  {t("ai.rev.hideNow")}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
