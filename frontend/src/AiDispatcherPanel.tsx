import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { Bot, ChevronDown, ChevronRight, MessageSquare, PhoneIncoming, ScanSearch } from "lucide-react";
import { apiCaps, generalRun, setAiMode, setAiTriage, setAutopilot, type AiMode, type Trip, type WorldSnapshot } from "./api";
import { AgentPanel, type AgentKeys } from "./AgentPanel";
import { aiStatsOf, callsOf, type CallView } from "./calls";
import { CaseCard } from "./CaseCard";
import { FieldMessage } from "./FieldMessage";
import { fmtTime } from "./format";
import { NewCallForm } from "./NewCallForm";
import { conditionText, LEVEL_LABEL, levelOf } from "./severity";
import { liveRecord, t as tx, tr, useT } from "./i18n";

type Notify = (kind: "ok" | "error", text: string) => void;

export interface CaseFocus {
  tripId: string;
  n: number;
  overrideVehicle?: string; // open this unit's override list (vehicle card "Override")
}

/** The mode's one-line explanation (follows the UI language). */
const EXPLAIN: Record<AiMode, string> = liveRecord(["autonomous", "assisted"] as const, (m) => tx(`ai.explain.${m}`));

/**
 * The right panel's first tab: the AI dispatcher. It classifies every 112 call, dispatches, routes and
 * reroutes, unless the dispatcher intervenes. Header: the mode (Autonomous / Assisted), what the AI has
 * done, new and demo calls. Then the general situation review (Analyse, options, Approve), the message
 * box (speech or text) and every case as an incident sheet, most severe first.
 */
export function AiDispatcherPanel({
  state,
  focus,
  picked,
  onPickOnMap,
  selectedCase,
  onSelectCase,
  onSelectVehicle,
  onCentreVehicle,
  onShowCall,
  notify,
  demo,
  reviewOpen,
  setReviewOpen,
  messageOpen,
  setMessageOpen,
  micToggleRef,
  agentKeys,
}: {
  state: WorldSnapshot;
  focus: CaseFocus | null;
  picked: { lat: number; lon: number; n: number } | null; // a point chosen on the map for the new call
  onPickOnMap: () => void;
  selectedCase: string | null;
  onSelectCase: (tripId: string | null) => void;
  onSelectVehicle: (vehicleId: string, openCard: boolean) => void;
  onCentreVehicle: (vehicleId: string) => void;
  onShowCall: (tripId: string) => void;
  notify: Notify;
  demo?: ReactNode; // Random call / Random failure (simulation)
  reviewOpen: boolean;
  setReviewOpen: (open: boolean) => void;
  messageOpen: boolean;
  setMessageOpen: (open: boolean) => void;
  micToggleRef: { current: (() => void) | null };
  agentKeys: RefObject<AgentKeys | null>;
}) {
  const t = useT();
  const [open, setOpen] = useState<string | null>(null); // trip id
  const [showClosed, setShowClosed] = useState(false);
  const [form, setForm] = useState(false);
  const [canOverride, setCanOverride] = useState(true);
  const [listening, setListening] = useState(false);
  const [overrideUnit, setOverrideUnit] = useState<{ tripId: string; id: string; n: number } | null>(null);
  // A disruption hit a case: its card opens with the re-plan box, until closed or another case is opened
  const [replan, setReplan] = useState<{ tripId: string; since: string } | null>(null);
  const { active, closed } = callsOf(state);
  const cardRefs = useRef(new Map<string, HTMLElement>());
  const reviewRef = useRef<HTMLDivElement>(null);
  const messageRef = useRef<HTMLDivElement>(null);

  // Override and Add unit need the backend's alternatives/assign endpoints (known from its OpenAPI schema;
  // when that is unavailable the buttons show and hide themselves on the first 404)
  useEffect(() => {
    let stop = false;
    void apiCaps().then((caps) => !stop && caps && setCanOverride(caps.alternatives && caps.assign));
    return () => {
      stop = true;
    };
  }, []);

  // New cards slide in and pulse once; those already there when the page opened don't
  const known = useRef<Set<string> | null>(null);
  const caseKey = (c: CallView) => `${c.trip.id}@${c.trip.pickup_after}`;
  if (known.current === null) known.current = new Set(active.map(caseKey));

  const toggle = (c: CallView) => {
    const next = open === c.trip.id ? null : c.trip.id;
    setOpen(next);
    onSelectCase(next ?? (selectedCase === c.trip.id ? null : selectedCase));
  };

  // Opened from a vehicle card ("Responding to …", "Override") or a new/random call: apply once the call
  // is in the snapshot (a call just created may arrive with the next update)
  const appliedFocus = useRef(0);
  useEffect(() => {
    if (!focus || appliedFocus.current === focus.n) return;
    const c = [...active, ...closed].find((x) => x.trip.id === focus.tripId);
    if (!c) return;
    appliedFocus.current = focus.n;
    if (closed.includes(c)) setShowClosed(true);
    setOpen(c.trip.id);
    onSelectCase(c.trip.id);
    if (focus.overrideVehicle) setOverrideUnit({ tripId: c.trip.id, id: focus.overrideVehicle, n: focus.n });
    requestAnimationFrame(() => cardRefs.current.get(c.trip.id)?.scrollIntoView({ block: "start", behavior: "smooth" }));
  }, [focus, state.version]); // eslint-disable-line react-hooks/exhaustive-deps

  // The world was reset (a scenario, Reset): the open card belonged to the old world's call with that id
  const lastEpoch = useRef(state.epoch);
  useEffect(() => {
    if (state.epoch === undefined || state.epoch === lastEpoch.current) return;
    lastEpoch.current = state.epoch;
    setOpen(null);
    setOverrideUnit(null);
    setReplan(null);
    seenDisruption.current = 0; // a reset re-anchors the clock: later disruptions may carry earlier times
  }, [state.epoch]);

  // A new disruption on an open case (a breakdown, delay, closure, jam, ... from a button, a hotkey or the
  // crew): open that case and show its re-plan box. Those already there when the page opened don't pop up.
  const seenDisruption = useRef<number | null>(null);
  useEffect(() => {
    let newest: { tripId: string; at: string; ms: number } | null = null;
    for (const c of active) {
      for (const e of c.trip.timeline ?? []) {
        if (e.kind !== "disruption") continue;
        const ms = Date.parse(e.at);
        if (!newest || ms > newest.ms) newest = { tripId: c.trip.id, at: e.at, ms };
      }
    }
    if (seenDisruption.current === null) {
      seenDisruption.current = newest?.ms ?? 0;
      return;
    }
    if (!newest || newest.ms <= seenDisruption.current) return;
    seenDisruption.current = newest.ms;
    const hit = newest;
    setReplan({ tripId: hit.tripId, since: hit.at });
    setOpen(hit.tripId);
    onSelectCase(hit.tripId);
    requestAnimationFrame(() => cardRefs.current.get(hit.tripId)?.scrollIntoView({ block: "start", behavior: "smooth" }));
  }, [state.version]); // eslint-disable-line react-hooks/exhaustive-deps

  // Opening another case closes the re-plan box (collapsing the same case keeps it)
  useEffect(() => {
    if (replan && open && open !== replan.tripId) setReplan(null);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  // A map point was picked for the new call: show the form again
  useEffect(() => {
    if (picked) setForm(true);
  }, [picked]);

  // Opened by a hotkey (A, Y, N, M): bring the section into view
  useEffect(() => {
    if (reviewOpen) reviewRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [reviewOpen]);
  useEffect(() => {
    if (messageOpen) messageRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [messageOpen]);

  const card = (c: CallView, fresh: boolean) => (
    <CaseCard
      key={`${state.epoch ?? 0}:${c.trip.id}`} // a reset world reuses trip ids: fresh cards, no old card state
      c={c}
      state={state}
      open={open === c.trip.id}
      selected={selectedCase === c.trip.id}
      isNew={fresh}
      canOverride={canOverride}
      overrideUnit={overrideUnit && overrideUnit.tripId === c.trip.id ? overrideUnit : null}
      onToggle={() => toggle(c)}
      onSelectVehicle={onSelectVehicle}
      onCentreVehicle={onCentreVehicle}
      onShowOnMap={() => onShowCall(c.trip.id)}
      replan={replan && replan.tripId === c.trip.id ? replan.since : null}
      onCloseReplan={() => setReplan(null)}
      onMissingOverride={() => {
        setCanOverride(false);
        notify("error", t("ai.toast.noOverride"));
      }}
      notify={notify}
      refCb={(el) => (el ? cardRefs.current.set(c.trip.id, el) : cardRefs.current.delete(c.trip.id))}
    />
  );

  return (
    <>
      <section className="panel ai-top">
        <div className="ai-head">
          <h2 className="panel-title">
            <Bot /> {t("ai.title")}
          </h2>
          <ModeSwitch state={state} notify={notify} />
        </div>
        <AiStatus state={state} />
        <div className="ai-actions">
          <button className={`primary sm calls-new${form ? " on" : ""}`} onClick={() => setForm((f) => !f)} aria-expanded={form}>
            <PhoneIncoming /> {t("ai.newCall")}
          </button>
          {demo}
          {state.ai_triage !== undefined && (
            <label className="switch ai-triage" title={t("ai.triageSwitchTitle")}>
              <input
                type="checkbox"
                role="switch"
                checked={state.ai_triage}
                onChange={(e) => setAiTriage(state.world, e.target.checked).catch((err) => notify("error", err instanceof Error ? err.message : String(err)))}
              />
              <span className="switch-track" aria-hidden />
              {t("ai.triageSwitch")}
            </label>
          )}
        </div>
        {form && (
          <NewCallForm
            state={state}
            picked={picked}
            onPickOnMap={onPickOnMap}
            onClose={() => setForm(false)}
            onCreated={(trip: Trip) => {
              setForm(false);
              setOpen(trip.id);
              onSelectCase(trip.id);
              notify(
                "ok",
                `${trip.call?.call_id ?? trip.id}: ${LEVEL_LABEL[levelOf(trip)]}${conditionText(trip) ? ` · ${conditionText(trip)}` : ""}${trip.vehicle_id ? t("ai.toast.dispatched", { v: trip.vehicle_id }) : ""}`,
              );
              requestAnimationFrame(() => cardRefs.current.get(trip.id)?.scrollIntoView({ block: "start", behavior: "smooth" }));
            }}
          />
        )}
      </section>

      <div className={`folds${reviewOpen || messageOpen ? " has-open" : ""}`}>
      <div className="fold" ref={reviewRef}>
        <button className="fold-head" onClick={() => setReviewOpen(!reviewOpen)} aria-expanded={reviewOpen}>
          {reviewOpen ? <ChevronDown /> : <ChevronRight />}
          <ScanSearch />
          <strong>{t("ai.review")}</strong>
          <ReviewSummary state={state} />
        </button>
        <div className="fold-body" hidden={!reviewOpen}>
          <AgentPanel state={state} notify={notify} keysRef={agentKeys} bare />
        </div>
      </div>

      <div className="fold" ref={messageRef}>
        <button className="fold-head" onClick={() => setMessageOpen(!messageOpen)} aria-expanded={messageOpen}>
          {messageOpen ? <ChevronDown /> : <ChevronRight />}
          <MessageSquare />
          <strong>
            <span className="fold-long">{t("ai.message")}</span>
            <span className="fold-short">{t("ai.messageShort")}</span>
          </strong>
          {listening && <i className="fold-dot live" aria-hidden />}
          <span className={`fold-sum${listening ? " live" : ""}`}>
            {listening ? t("ai.listening") : tr("ai.speechOrText", { kbd: <kbd>M</kbd> })}
          </span>
        </button>
        <div className="fold-body" hidden={!messageOpen}>
          <FieldMessage state={state} micToggleRef={micToggleRef} bare onListening={setListening} />
        </div>
      </div>
      </div>

      {active.length === 0 ? (
        <p className="muted cases-empty">{t("ai.noCases")}</p>
      ) : (
        <ul className="cases" aria-label={t("ai.activeCases")}>
          {active.map((c) => card(c, !known.current!.has(caseKey(c))))}
        </ul>
      )}
      {closed.length > 0 && (
        <div className="calls-closed">
          <button className="link calls-closed-toggle" onClick={() => setShowClosed((s) => !s)} aria-expanded={showClosed}>
            {showClosed ? <ChevronDown /> : <ChevronRight />} {t("ai.closedToggle", { n: closed.length })}
          </button>
          {showClosed && (
            <ul className="cases" aria-label={t("ai.closedCases")}>
              {closed.map((c) => card(c, false))}
            </ul>
          )}
        </div>
      )}
    </>
  );
}

/** Autonomous / Assisted: snapshot ai_mode (POST /admin/ai-mode), or the older autopilot switch. */
function ModeSwitch({ state, notify }: { state: WorldSnapshot; notify: Notify }) {
  const t = useT();
  const [pending, setPending] = useState<AiMode | null>(null);
  const fromState: AiMode = state.ai_mode ?? (state.autopilot ? "autonomous" : "assisted");
  useEffect(() => {
    if (pending && pending === fromState) setPending(null);
  }, [pending, fromState]);
  if (state.ai_mode === undefined && state.autopilot === undefined) return null;
  const mode = pending ?? fromState;
  const choose = async (m: AiMode) => {
    if (m === mode) return;
    setPending(m);
    try {
      if (state.ai_mode !== undefined) {
        try {
          await setAiMode(state.world, m);
        } catch (e) {
          if (state.autopilot === undefined || !/not found/i.test(String(e))) throw e;
          await setAutopilot(state.world, m === "autonomous"); // ai_mode in the snapshot, endpoint not yet
        }
      } else await setAutopilot(state.world, m === "autonomous");
      notify("ok", EXPLAIN[m]);
    } catch (e) {
      setPending(null);
      notify("error", e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <div className="mode-switch" role="radiogroup" aria-label={t("ai.modeAria")}>
      {(["autonomous", "assisted"] as AiMode[]).map((m) => (
        <button key={m} role="radio" aria-checked={mode === m} className={mode === m ? "on" : ""} onClick={() => void choose(m)} title={EXPLAIN[m]}>
          {t(m === "autonomous" ? "ai.mode.autonomous" : "ai.mode.assisted")}
        </button>
      ))}
    </div>
  );
}

/** The mode's one-line explanation and what the AI dispatcher has done (ai_stats, else the timelines). */
function AiStatus({ state }: { state: WorldSnapshot }) {
  const t = useT();
  const mode: AiMode | null = state.ai_mode ?? (state.autopilot === undefined ? null : state.autopilot ? "autonomous" : "assisted");
  const s = aiStatsOf(state);
  const title = [
    t("ai.stats.dispatched", { count: s.dispatched }),
    t("ai.stats.changed", { count: s.claude_changes }),
    s.last_decision_at ? t("ai.stats.last", { time: fmtTime(s.last_decision_at) }) : "",
    t("ai.stats.window"),
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <>
      {mode && <p className={`ai-explain mode-${mode}`}>{EXPLAIN[mode]}</p>}
      <p className="ai-stats" title={title}>
        {tr("ai.stats.handling", { cases: <strong>{t("ai.stats.cases", { count: s.cases_active })}</strong> })} ·{" "}
        {t("ai.stats.reroutes", { count: s.reroutes })} · {t("ai.stats.reassignments", { count: s.reassignments })} ·{" "}
        <span className={s.overrides ? "ai-stats-hi" : undefined}>{t("ai.stats.overrides", { count: s.overrides })}</span> ·{" "}
        {t("ai.stats.reviews", { count: s.claude_reviews })}
      </p>
    </>
  );
}

/** The general analysis in one line, for the folded "Situation review". */
function ReviewSummary({ state }: { state: WorldSnapshot }) {
  const t = useT();
  const run = generalRun(state.agent.runs);
  const rec = run?.recommendation;
  let text: string;
  let tone = "";
  if (!run) text = t("ai.sum.watching");
  else if (run.status === "running") {
    text = t("ai.sum.analysing");
    tone = " live";
  } else if (run.status === "done" && rec && rec.options.length > 0) {
    text = t("ai.sum.waiting", { title: rec.options[rec.recommended_index]?.title ?? t("ai.sum.plan") });
    tone = " warn";
  } else if (run.status === "approved") text = t("ai.sum.approved", { title: run.decision?.title ?? t("ai.sum.plan") });
  else if (run.status === "rejected") text = t("ai.sum.rejected");
  else if (run.status === "error") text = t("ai.sum.failed");
  else text = t("ai.sum.noAction");
  return (
    <>
      {tone && <i className={`fold-dot${tone}`} title={text} aria-hidden />}
      <span className={`fold-sum${tone}`}>{text}</span>
    </>
  );
}
