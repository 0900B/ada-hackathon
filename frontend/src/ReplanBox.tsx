import { ArrowRight, Bot, Cpu, Loader2, PhoneIncoming, Radio, UserRound, X, Zap, type LucideIcon } from "lucide-react";
import type { TimelineEntry } from "./api";
import { isClaude, sourceText, STEP_LABEL } from "./calls";
import { fmtTime } from "./format";
import { useT } from "./i18n";

/**
 * The re-plan box on a case card: a disruption hit this call (breakdown, delay, closure, jam, fog, ...)
 * and what happened next, line by line, as it happens: the engine's re-dispatch or reroute with its real
 * time ("Rules engine · 0.1 s"), the unit before -> after, the arrival before -> after, then Claude's
 * review. The lines appear one after another for readability; the times shown are the real ones. Stays
 * until the dispatcher closes it or opens another case (AiDispatcherPanel).
 */
export function ReplanBox({
  mode = "disruption",
  timeline,
  since,
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
  const lines = rest.filter((e) => !(isNew ? SKIP_NEW : SKIP).has(e.kind)).slice(0, 10);
  const HeadIcon = isNew ? PhoneIncoming : Zap;
  return (
    <section className={`replan${isNew ? " new" : ""}`} aria-label={t("ai.replan.aria")} aria-live="polite">
      <div className="replan-head">
        <HeadIcon className="replan-icon" aria-hidden />
        <span className="replan-title">
          {t(isNew ? "ai.replan.newTitle" : "ai.replan.title")} {fmtTime(head.at)}
        </span>
        <span className="replan-what">{isNew ? t("ai.replan.newWhat") : head.text}</span>
        <button className="link replan-close" onClick={onClose} title={t("ai.replan.close")} aria-label={t("ai.replan.close")}>
          <X />
        </button>
      </div>
      <ol className="replan-lines">
        {lines.map((e, i) => (
          <ReplanLine key={`${e.at}|${e.kind}|${i}`} e={e} i={i} onSelectVehicle={onSelectVehicle} />
        ))}
        {reviewing && (
          <li className="replan-line pending by-ai" style={{ animationDelay: `${lines.length * STAGGER_S}s` }}>
            <Loader2 className="replan-who replan-spin" aria-hidden />
            <div className="replan-main">
              <div className="replan-text">{t("ai.replan.reviewing")}</div>
            </div>
          </li>
        )}
        {!reviewing && lines.length === 0 && (
          <li className="replan-line pending">
            <Loader2 className="replan-who replan-spin" aria-hidden />
            <div className="replan-main">
              <div className="replan-text">{t("ai.replan.waiting")}</div>
            </div>
          </li>
        )}
        {proposal && (
          <li className="replan-line proposal by-ai" style={{ animationDelay: `${(lines.length + 1) * STAGGER_S}s` }}>
            <Bot className="replan-who" aria-hidden />
            <div className="replan-main replan-proposal">
              <span className="replan-text">{t("ai.replan.proposal", { title: proposal })}</span>
              <button className="primary sm" onClick={onApprove} disabled={busy}>
                {t("ai.replan.approve")}
              </button>
            </div>
          </li>
        )}
      </ol>
    </section>
  );
}

const STAGGER_S = 0.35; // seconds between lines appearing (the real times are on each line)
const SKIP = new Set(["received", "triaged", "disruption"]);
// A new call's box shows the triage and dispatch, not the crew's progress (on scene, transporting, ...)
const SKIP_NEW = new Set(["received", "disruption", "on_scene", "doctor_on_scene", "transporting", "at_hospital", "handover_done", "closed"]);

function whoIcon(by: string): LucideIcon {
  if (isClaude(by)) return Bot;
  if (by === "dispatcher") return UserRound;
  if (by === "crew") return Radio;
  return Cpu;
}

function ReplanLine({ e, i, onSelectVehicle }: { e: TimelineEntry; i: number; onSelectVehicle: (id: string) => void }) {
  const t = useT();
  const Icon = whoIcon(e.by);
  const eta =
    e.eta_before && e.eta_after
      ? { before: e.eta_before, after: e.eta_after, delta: Math.round((Date.parse(e.eta_after) - Date.parse(e.eta_before)) / 60000) }
      : null;
  const where = e.eta_of === "hospital" ? t("ai.replan.atHospital") : e.eta_of === "pickup" ? t("ai.replan.atPickup") : t("ai.replan.atPatient");
  const swapped = e.unit_before && e.vehicle_id && e.unit_before !== e.vehicle_id;
  return (
    <li className={`replan-line by-${isClaude(e.by) ? "ai" : e.by}`} style={{ animationDelay: `${i * STAGGER_S}s` }}>
      <Icon className="replan-who" aria-hidden />
      <div className="replan-main">
        <div className="replan-row">
          {(e.by === "engine" || e.by === "rules" || isClaude(e.by)) && (
            <span className="replan-ai" title={t("ai.replan.aiChipTitle")}>
              {t("ai.replan.aiChip")}
            </span>
          )}
          <span className="replan-step">{STEP_LABEL[e.kind] ?? e.kind}</span>
          <span className="replan-src">{sourceText(e.by, e.detail)}</span>
          <span className="replan-time">{fmtTime(e.at)}</span>
        </div>
        <div className="replan-text">{e.text}</div>
        {(swapped || eta) && (
          <div className="replan-delta">
            {swapped && (
              <span className="replan-units">
                <s>{e.unit_before}</s>
                <ArrowRight aria-hidden />
                <button className="link" onClick={() => onSelectVehicle(e.vehicle_id!)}>
                  {e.vehicle_id}
                </button>
              </span>
            )}
            {eta && (
              <span className="replan-eta">
                {where}{" "}
                {eta.delta !== 0 && (
                  <>
                    <s>{fmtTime(eta.before)}</s>
                    <ArrowRight aria-hidden />
                  </>
                )}
                <b>{fmtTime(eta.after)}</b>
                <span className={`replan-d${eta.delta > 0 ? " worse" : eta.delta < 0 ? " better" : ""}`}>
                  {eta.delta > 0
                    ? t("ai.replan.later", { n: eta.delta })
                    : eta.delta < 0
                      ? t("ai.replan.earlier", { n: -eta.delta })
                      : t("ai.replan.same")}
                </span>
              </span>
            )}
          </div>
        )}
      </div>
    </li>
  );
}
