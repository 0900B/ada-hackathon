import { AlertTriangle, Bot, Check, Loader2, PencilLine, PhoneIncoming, UserRound, X, Zap, type LucideIcon } from "lucide-react";
import type { TimelineEntry } from "./api";
import { isClaude, sourceText, type CaseUnit } from "./calls";
import { fmtTime } from "./format";
import { useT } from "./i18n";

/**
 * The compact AI box on a case card: a new call the AI dispatcher is handling, or a disruption that hit
 * the call. One small step chain (each step ticks when it is done: who did it and how long it took),
 * then the decision in one block: who goes and when, why, and Claude's verdict. The full step-by-step log
 * stays in the case timeline. Stays until the dispatcher closes it or opens another case (AiDispatcherPanel).
 */
export function ReplanBox({
  mode = "disruption",
  timeline,
  since,
  units,
  autonomous = false,
  reviewing,
  proposal,
  busy,
  onApprove,
  onClose,
  onSelectVehicle,
}: {
  mode?: "disruption" | "new"; // a disruption hit the call, or a new call the AI dispatcher is handling
  timeline: TimelineEntry[];
  since: string; // the disruption entry's time (new: the "received" entry's time)
  units: CaseUnit[]; // who serves the call now (the decision)
  autonomous?: boolean; // Autonomous mode: Claude checks cases by itself
  reviewing: boolean; // Claude is reviewing this case right now
  proposal: string | null; // a pending proposal's title (Assisted mode)
  busy: boolean;
  onApprove: () => void;
  onClose: () => void;
  onSelectVehicle: (vehicleId: string) => void;
}) {
  const t = useT();
  const isNew = mode === "new";
  const headKind = isNew ? "received" : "disruption";
  let start = -1;
  for (let i = timeline.length - 1; i >= 0; i--) {
    if (timeline[i].kind === headKind && timeline[i].at === since) {
      start = i;
      break;
    }
  }
  if (start < 0) return null;
  const head = timeline[start];
  // A new call: what the AI dispatcher did with it, until the next disruption (that gets its own box)
  let rest = timeline.slice(start + 1);
  if (isNew) {
    const stop = rest.findIndex((e) => e.kind === "disruption");
    if (stop >= 0) rest = rest.slice(0, stop);
  }
  const verdict = claudeVerdict(rest, reviewing, proposal);
  const steps = isNew ? newCallSteps(rest, units, t) : disruptionSteps(rest, t);
  steps.push(claudeStep(verdict, rest, autonomous, t));
  const decision = rest.find((e) => DECIDES.has(e.kind) && e.by !== "crew");
  const why = isNew ? unitReasons(units) : engineWhy(decision);
  const swap = !isNew && decision?.unit_before && decision.vehicle_id && decision.unit_before !== decision.vehicle_id ? decision : null;
  const moved = rest.filter((e) => e.eta_before && e.eta_after).pop();
  const delta = !isNew && moved ? minutes(moved.eta_before!, moved.eta_after!) : null;
  const HeadIcon = isNew ? PhoneIncoming : Zap;
  return (
    <section className={`replan rp${isNew ? " new" : ""}`} aria-label={t("ai.replan.aria")} aria-live="polite">
      <div className="replan-head">
        <HeadIcon className="replan-icon" aria-hidden />
        <span className="replan-title">
          {t(isNew ? "ai.replan.newTitle" : "ai.replan.title")} {fmtTime(head.at)}
        </span>
        <span className="replan-what">{isNew ? t("ai.rp.newWhat") : head.text}</span>
        <button className="link replan-close" onClick={onClose} title={t("ai.replan.close")} aria-label={t("ai.replan.close")}>
          <X />
        </button>
      </div>

      <ol className="rp-steps">
        {steps.map((s) => (
          <li key={s.key} className={`rp-step ${s.state}`} title={s.title}>
            {s.state === "active" ? <Loader2 className="replan-spin" aria-hidden /> : s.state === "warn" ? <AlertTriangle aria-hidden /> : s.state === "off" ? null : <Check aria-hidden />}
            <span className="rp-step-label">{s.label}</span>
            {s.src && <span className="rp-step-src">{s.src}</span>}
          </li>
        ))}
      </ol>

      <div className="rp-decision">
        {units.length === 0 ? (
          <div className="decision-none">{t("ai.decision.noUnit")}</div>
        ) : (
          <ul className="rp-units">
            {units.map((u, i) => (
              <li key={u.id}>
                <button className="link rp-unit" onClick={() => onSelectVehicle(u.id)}>
                  {u.id}
                </button>
                {i === 0 && swap && (
                  <span className="rp-was">
                    {t("ai.rp.was", { id: swap.unit_before! })}
                  </span>
                )}
                <span className="rp-role">{u.roleLabel}</span>
                <span className="rp-eta">
                  {u.etaLabel} <b>{u.eta ? fmtTime(u.eta) : "–"}</b>
                </span>
                {i === 0 && delta != null && delta !== 0 && (
                  <span className={`replan-d ${delta > 0 ? "worse" : "better"}`}>
                    {delta > 0 ? t("ai.replan.later", { n: delta }) : t("ai.replan.earlier", { n: -delta })}
                  </span>
                )}
                {u.by === "dispatcher" && <span className="decision-by by-dispatcher">{t("ai.decision.byDispatcher")}</span>}
              </li>
            ))}
          </ul>
        )}
        {why && (
          <div className="rp-why">
            <span className="rp-why-label">{t("ai.rp.why")}</span> {why}
          </div>
        )}
        <ClaudeLine verdict={verdict} autonomous={autonomous} busy={busy} onApprove={onApprove} />
      </div>
    </section>
  );
}

type StepState = "done" | "active" | "warn" | "off";
type Step = { key: string; label: string; src: string; state: StepState; title: string };
type T = ReturnType<typeof useT>;

const DECIDES = new Set(["reassigned", "unit_replaced", "recalculated", "rerouted", "dispatched", "override"]);

function step(key: string, label: string, e: TimelineEntry | undefined, state: StepState = "done"): Step {
  return { key, label, src: e ? sourceText(e.by, e.detail) : "", state, title: e?.text ?? "" };
}

/** A new call: classified (Claude or the keyword rules), dispatched (the rules engine). */
function newCallSteps(rest: TimelineEntry[], units: CaseUnit[], t: T): Step[] {
  const triaged = rest.find((e) => e.kind === "triaged");
  const sent = rest.find((e) => e.kind === "dispatched");
  return [
    triaged ? step("triaged", t("ai.rp.classified"), triaged) : step("triaged", t("ai.rp.classified"), undefined, "active"),
    sent || units.length ? step("dispatched", t("ai.rp.dispatched"), sent) : step("dispatched", t("ai.rp.finding"), undefined, "active"),
  ];
}

/** A disruption: its impact on the call (+N min), then the engine's recalculation (switched or kept). */
function disruptionSteps(rest: TimelineEntry[], t: T): Step[] {
  const out: Step[] = [];
  const impact = rest.find((e) => (e.kind === "delayed" || e.kind === "rerouted") && e.eta_before && e.eta_after);
  if (impact) {
    const d = minutes(impact.eta_before!, impact.eta_after!);
    out.push(step("impact", d ? t("ai.rp.impact", { d: d > 0 ? `+${d}` : `${d}` }) : t("ai.rp.impactNone"), impact, d > 0 ? "warn" : "done"));
  }
  const engine = rest.find((e) => ["reassigned", "unit_replaced", "recalculated"].includes(e.kind) && !isClaude(e.by));
  if (engine) {
    const switched = engine.kind !== "recalculated" && engine.vehicle_id;
    out.push(step("engine", switched ? t("ai.rp.switched", { id: engine.vehicle_id! }) : t("ai.rp.kept"), engine));
  } else {
    out.push(step("engine", t("ai.rp.recalculating"), undefined, "active"));
  }
  return out;
}

function claudeStep(v: Verdict, rest: TimelineEntry[], autonomous: boolean, t: T): Step {
  const e = [...rest].reverse().find((x) => isClaude(x.by) && (x.kind === "reviewed" || x.kind === "note" || x.kind === "proposal"));
  if (v.kind === "reviewing") return step("claude", t("ai.rp.claudeCheck"), undefined, "active");
  if (v.kind === "agreed" || v.kind === "changed" || v.kind === "proposed") return step("claude", t("ai.rp.claudeCheck"), e);
  if (v.kind === "refused" || v.kind === "unavailable") return step("claude", t("ai.rp.claudeCheck"), e, "warn");
  return { key: "claude", label: t("ai.rp.claudeCheck"), src: autonomous ? t("ai.rp.notAsked") : t("ai.rp.assisted"), state: "off", title: "" };
}

function minutes(a: string, b: string): number {
  return Math.round((Date.parse(b) - Date.parse(a)) / 60000);
}

/** Why these units: each unit's reason, as the engine (or the dispatcher) wrote it. */
function unitReasons(units: CaseUnit[]): string {
  return units
    .filter((u) => u.reason)
    .map((u) => `${u.id}: ${u.reason}`)
    .join(" · ");
}

/** Why the engine decided what it did after the disruption, in one short clause. */
function engineWhy(e: TimelineEntry | undefined): string {
  if (!e) return "";
  let s = e.text.replace(/^Recalculated:\s*/i, "");
  s = s.split(/: switched|; compared|; [A-Z]\d+ released/)[0];
  return s.length > 160 ? `${s.slice(0, 157)}…` : s;
}

type VerdictKind = "reviewing" | "agreed" | "changed" | "refused" | "unavailable" | "proposed" | "override" | "none";
type Verdict = { kind: VerdictKind; text: string };

/** Claude's reason, short: the part in brackets when there is one ("keep A1 ... (A1 and A2 tie)" -> "A1 and A2 tie"). */
function shortReason(text: string): string {
  const m = /\(([^()]*(?:\([^()]*\)[^()]*)*)\)\s*$/.exec(text);
  const s = (m ? m[1] : text).trim();
  return s.length > 180 ? `${s.slice(0, 177)}…` : s;
}

/** What Claude made of the decision, from the timeline after the box's start. */
function claudeVerdict(after: TimelineEntry[], reviewing: boolean, proposal: string | null): Verdict {
  if (reviewing) return { kind: "reviewing", text: "" };
  for (let i = after.length - 1; i >= 0; i--) {
    const e = after[i];
    if (e.kind === "override" && e.by === "dispatcher") return { kind: "override", text: e.text };
    if (e.kind === "reviewed" && isClaude(e.by)) {
      const changed = /\bchanged:\s*/i.exec(e.text);
      if (changed) return { kind: "changed", text: e.text.slice(changed.index + changed[0].length) };
      return { kind: "agreed", text: shortReason(e.text) };
    }
    if (e.kind === "note" && isClaude(e.by) && /decision stands/.test(e.text)) {
      return { kind: "refused", text: e.text.replace(/^AI dispatcher \(Claude\)\s*/i, "") };
    }
    if (e.kind === "note" && /review not available/i.test(e.text)) return { kind: "unavailable", text: "" };
  }
  if (proposal) return { kind: "proposed", text: proposal };
  return { kind: "none", text: "" };
}

const VERDICT_ICON: Record<VerdictKind, LucideIcon> = {
  reviewing: Loader2,
  agreed: Check,
  changed: PencilLine,
  refused: AlertTriangle,
  unavailable: AlertTriangle,
  proposed: Bot,
  override: UserRound,
  none: Bot,
};

/** Claude's verdict on the decision, one line. */
function ClaudeLine({ verdict: v, autonomous, busy, onApprove }: { verdict: Verdict; autonomous: boolean; busy: boolean; onApprove: () => void }) {
  const t = useT();
  const VIcon = VERDICT_ICON[v.kind];
  const label = v.kind === "none" && autonomous ? t("ai.decision.claude.noneAuto") : t(`ai.decision.claude.${v.kind}`);
  return (
    <div className={`decision-claude rp-claude v-${v.kind}`}>
      <VIcon className={v.kind === "reviewing" ? "replan-spin" : undefined} aria-hidden />
      <div className="decision-claude-main">
        <span className="decision-claude-label">{label}</span>
        {v.text && <span className="decision-claude-text">{v.text}</span>}
      </div>
      {v.kind === "proposed" && (
        <button className="primary sm" onClick={onApprove} disabled={busy}>
          {t("ai.replan.approve")}
        </button>
      )}
    </div>
  );
}
