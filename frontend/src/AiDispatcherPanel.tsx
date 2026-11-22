import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { Bot, ChevronDown, ChevronRight, MessageSquare, PhoneIncoming, ScanSearch } from "lucide-react";
import { apiCaps, setAiMode, setAiTriage, setAutopilot, type AiMode, type Trip, type WorldSnapshot } from "./api";
import { AgentPanel, type AgentKeys } from "./AgentPanel";
import { aiStatsOf, callsOf, type CallView } from "./calls";
import { CaseCard } from "./CaseCard";
import { FieldMessage } from "./FieldMessage";
import { fmtTime } from "./format";
import { NewCallForm } from "./NewCallForm";
import { conditionText, LEVEL_LABEL, levelOf } from "./severity";

type Notify = (kind: "ok" | "error", text: string) => void;

export interface CaseFocus {
  tripId: string;
  n: number;
  overrideVehicle?: string; // open this unit's override list (vehicle card "Override")
}

const EXPLAIN: Record<AiMode, string> = {
  autonomous: "Autonomous: the AI dispatcher handles each case; you can intervene anytime",
  assisted: "Assisted: the AI proposes, you approve",
};

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

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
  const [open, setOpen] = useState<string | null>(null); // trip id
  const [showClosed, setShowClosed] = useState(false);
  const [form, setForm] = useState(false);
  const [canOverride, setCanOverride] = useState(true);
  const [listening, setListening] = useState(false);
  const [overrideUnit, setOverrideUnit] = useState<{ tripId: string; id: string; n: number } | null>(null);
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
    requestAnimationFrame(() => cardRefs.current.get(c.trip.id)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
  }, [focus, state.version]); // eslint-disable-line react-hooks/exhaustive-deps

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
      key={c.trip.id}
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
      onMissingOverride={() => {
        setCanOverride(false);
        notify("error", "This backend cannot override units yet: use the vehicle card (breakdown, delay) or the Events tab.");
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
            <Bot /> AI dispatcher
          </h2>
          <ModeSwitch state={state} notify={notify} />
        </div>
        <AiStatus state={state} />
        <div className="ai-actions">
          <button className={`primary sm calls-new${form ? " on" : ""}`} onClick={() => setForm((f) => !f)} aria-expanded={form}>
            <PhoneIncoming /> New 112 call
          </button>
          {demo}
          {state.ai_triage !== undefined && (
            <label className="switch ai-triage" title="New 112 calls are classified by Claude (otherwise by keyword rules)">
              <input
                type="checkbox"
                role="switch"
                checked={state.ai_triage}
                onChange={(e) => setAiTriage(state.world, e.target.checked).catch((err) => notify("error", err instanceof Error ? err.message : String(err)))}
              />
              <span className="switch-track" aria-hidden />
              AI triage
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
                `${trip.call?.call_id ?? trip.id}: ${LEVEL_LABEL[levelOf(trip)]}${conditionText(trip) ? ` · ${conditionText(trip)}` : ""}${trip.vehicle_id ? ` · ${trip.vehicle_id} dispatched` : ""}`,
              );
              requestAnimationFrame(() => cardRefs.current.get(trip.id)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
            }}
          />
        )}
      </section>

      <div className="fold" ref={reviewRef}>
        <button className="fold-head" onClick={() => setReviewOpen(!reviewOpen)} aria-expanded={reviewOpen}>
          {reviewOpen ? <ChevronDown /> : <ChevronRight />}
          <ScanSearch />
          <strong>Situation review</strong>
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
          <strong>Message to the AI dispatcher</strong>
          <span className={`fold-sum${listening ? " live" : ""}`}>
            {listening ? "Listening…" : (
              <>
                speech or text · <kbd>M</kbd>
              </>
            )}
          </span>
        </button>
        <div className="fold-body" hidden={!messageOpen}>
          <FieldMessage state={state} micToggleRef={micToggleRef} bare onListening={setListening} />
        </div>
      </div>

      {active.length === 0 ? (
        <p className="muted cases-empty">No active cases. New 112 calls appear here as the AI classifies and dispatches them.</p>
      ) : (
        <ul className="cases" aria-label="Active cases">
          {active.map((c) => card(c, !known.current!.has(caseKey(c))))}
        </ul>
      )}
      {closed.length > 0 && (
        <div className="calls-closed">
          <button className="link calls-closed-toggle" onClick={() => setShowClosed((s) => !s)} aria-expanded={showClosed}>
            {showClosed ? <ChevronDown /> : <ChevronRight />} Closed in the last 3 h ({closed.length})
          </button>
          {showClosed && (
            <ul className="cases" aria-label="Closed cases">
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
    <div className="mode-switch" role="radiogroup" aria-label="AI dispatcher mode">
      {(["autonomous", "assisted"] as AiMode[]).map((m) => (
        <button key={m} role="radio" aria-checked={mode === m} className={mode === m ? "on" : ""} onClick={() => void choose(m)} title={EXPLAIN[m]}>
          {m === "autonomous" ? "Autonomous" : "Assisted"}
        </button>
      ))}
    </div>
  );
}

/** The mode's one-line explanation and what the AI dispatcher has done (ai_stats, else the timelines). */
function AiStatus({ state }: { state: WorldSnapshot }) {
  const mode: AiMode | null = state.ai_mode ?? (state.autopilot === undefined ? null : state.autopilot ? "autonomous" : "assisted");
  const s = aiStatsOf(state);
  const title = [
    `${plural(s.dispatched, "call")} dispatched by the AI`,
    `Claude changed ${plural(s.claude_changes, "decision")} of the rules engine`,
    s.last_decision_at ? `Last decision ${fmtTime(s.last_decision_at)}` : "",
    "Counted over the calls of the last 3 hours",
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <>
      {mode && <p className={`ai-explain mode-${mode}`}>{EXPLAIN[mode]}</p>}
      <p className="ai-stats" title={title}>
        Handling <strong>{plural(s.cases_active, "case")}</strong> · {plural(s.reroutes, "reroute")} · {plural(s.reassignments, "reassignment")} ·{" "}
        <span className={s.overrides ? "ai-stats-hi" : undefined}>{plural(s.overrides, "override")}</span> · {plural(s.claude_reviews, "Claude review")}
      </p>
    </>
  );
}

/** The general analysis in one line, for the folded "Situation review". */
function ReviewSummary({ state }: { state: WorldSnapshot }) {
  const run = state.agent.runs[0];
  const rec = run?.recommendation;
  let text: string;
  let tone = "";
  if (!run) text = "watching the fleet · A to analyse";
  else if (run.status === "running") {
    text = "Analysing…";
    tone = " live";
  } else if (run.status === "done" && rec && rec.options.length > 0) {
    text = `Waiting for your decision: ${rec.options[rec.recommended_index]?.title ?? "plan"}`;
    tone = " warn";
  } else if (run.status === "approved") text = `Approved: ${run.decision?.title ?? "plan"}`;
  else if (run.status === "rejected") text = "Rejected: the plan stays as it was";
  else if (run.status === "error") text = "The last analysis failed · A to retry";
  else text = "No action needed · A to analyse";
  return <span className={`fold-sum${tone}`}>{text}</span>;
}
