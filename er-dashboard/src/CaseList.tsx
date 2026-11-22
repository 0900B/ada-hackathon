import { AlertTriangle, BedDouble, CheckCheck, Truck } from "lucide-react";
import type { CaseCard, ErAlert } from "./api";
import { duration, minutesBetween } from "./format";
import { ARRIVED_STAGES, LEVEL_LABEL, TEAM_LABEL, caseTitle, stageGloss, titleIsNote } from "./labels";

export const isArrived = (c: CaseCard) => c.arrived_at !== null || ARRIVED_STAGES.has(c.stage ?? "");

function EtaBlock({ c, asOf }: { c: CaseCard; asOf: string }) {
  if (!isArrived(c)) {
    if (c.minutes_to_arrival === null) {
      return (
        <div className="eta">
          <span className="eta-num dim">–</span>
          <span className="eta-unit">no unit yet</span>
        </div>
      );
    }
    const m = Math.ceil(c.minutes_to_arrival);
    return (
      <div className="eta">
        <span className="eta-num">{m < 1 ? "<1" : m}</span>
        <span className="eta-unit">min to arrival</span>
      </div>
    );
  }
  const h = c.handover;
  const since = c.arrived_at ? duration(minutesBetween(c.arrived_at, asOf)) : null;
  let note = since ? `here for ${since}` : "at the ER";
  let cls = "";
  if (h && h.done_at === null) {
    if (h.overdue) {
      note = "handover overdue";
      cls = "bad";
    } else if (h.minutes_left !== null) {
      note = `handover: ${Math.ceil(h.minutes_left)} min left`;
    }
  } else if (h?.done_at) {
    note = "handed over";
    cls = "ok";
  }
  return (
    <div className="eta">
      <span className="eta-num here">Here</span>
      <span className={`eta-unit ${cls}`}>{note}</span>
    </div>
  );
}

export function CaseRow({
  c,
  asOf,
  alerts,
  selected,
  onSelect,
}: {
  c: CaseCard;
  asOf: string;
  alerts: ErAlert[];
  selected: boolean;
  onSelect: () => void;
}) {
  const top = alerts[0];
  const who = [c.age_years !== null ? `${c.age_years}` : null, c.sex === "f" ? "female" : c.sex === "m" ? "male" : null]
    .filter(Boolean)
    .join(", ");
  const problem = caseTitle(c.problem);
  return (
    <li>
      <button
        type="button"
        className={`row level-${c.level.value} ${c.level.inferred ? "assumed" : ""} ${selected ? "selected" : ""}`}
        aria-haspopup="dialog"
        onClick={onSelect}
      >
        <EtaBlock c={c} asOf={asOf} />
        <div className="row-main">
          <div className="row-title">
            <span className={`level-tag level-${c.level.value}`} title={c.level.inferred ? "Assumed from the dispatch priority: nobody has triaged this case" : `Triaged by ${c.level.source ?? "dispatch"}`}>
              {LEVEL_LABEL[c.level.value]}
              {c.level.inferred && <span className="assumed-mark"> (assumed)</span>}
            </span>
            <strong>{problem}</strong>
          </div>
          <div className="row-sub">
            <span>{who || c.patient_label}</span>
            {who && <span className="dim">{c.patient_label}</span>}
            {c.problem.note && !titleIsNote(c.problem) && <span className="dim note">“{c.problem.note}”</span>}
          </div>
          <div className="row-meta">
            <span className={`chip ${c.stage_inferred ? "estimated" : ""}`} title={c.stage_inferred ? "Estimated from the vehicle's movement" : "Reported"}>
              <Truck size={13} aria-hidden /> {stageGloss(c.stage)}
              {c.stage_inferred && " (estimated)"}
              {c.vehicle_id && <span className="dim"> {c.vehicle_id}</span>}
            </span>
            <span className={`chip ${c.bay ? "" : "todo"}`}>
              <BedDouble size={13} aria-hidden /> {c.bay ? `Bay ${c.bay}` : "No bay"}
            </span>
            <span className={`chip ${c.acknowledged ? "done" : "todo"}`}>
              <CheckCheck size={13} aria-hidden /> {c.acknowledged ? "Acknowledged" : "Not acknowledged"}
            </span>
            {c.teams_activated.map((t) => (
              <span key={t} className="chip team">
                {TEAM_LABEL[t]}
              </span>
            ))}
          </div>
          {top && (
            <div className={`row-alert sev-${top.severity}`}>
              <AlertTriangle size={14} aria-hidden /> {top.message}
              {alerts.length > 1 && <span className="more"> +{alerts.length - 1} more</span>}
            </div>
          )}
        </div>
      </button>
    </li>
  );
}
