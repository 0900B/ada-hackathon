import { Check, CircleAlert, CloudCheck, CloudOff, Trash2, X } from "lucide-react";
import { fmtTime } from "../format";
import { ageMinutes, entryLabel, type ClinicalEntry } from "./clinicalLog";

const SYNC_TEXT: Record<ClinicalEntry["sync"], string> = {
  pending: "pending",
  sent: "sent",
  rejected: "not accepted",
};

/**
 * The trip's log, newest first. Each row: world time and age, what was said or tapped (speech in
 * quotes, word for word), its state, whether it has reached the backend, and on a heard row the
 * Confirm and Discard buttons.
 */
export function Timeline({
  entries,
  nowIso,
  onConfirm,
  onDiscard,
}: {
  entries: ClinicalEntry[];
  nowIso: string;
  onConfirm: (id: string) => void;
  onDiscard: (id: string) => void;
}) {
  if (entries.length === 0) {
    return <p className="pt-tl-empty">Nothing logged yet. Hold the log button and speak, or type a note.</p>;
  }
  return (
    <ol className="pt-tl" aria-label="Timeline, newest first">
      {entries.map((e) => {
        const age = ageMinutes(e, nowIso);
        const spoken = e.source === "crew_voice" && e.type === "note";
        return (
          <li key={e.client_entry_id} className={`pt-tl-row pt-tl-${e.state}${e.needs_check ? " pt-tl-check" : ""}`}>
            <div className="pt-tl-when">
              <span className="pt-tl-time">{fmtTime(e.t)}</span>
              <span className="pt-tl-age">{age === null ? "–" : age === 0 ? "now" : `${age} min ago`}</span>
            </div>
            <div className="pt-tl-what">
              <span className={`pt-tl-label${spoken ? " pt-tl-spoken" : ""}`}>
                {spoken ? `“${entryLabel(e)}”` : entryLabel(e)}
              </span>
              <span className="pt-tl-tags">
                <span className={`pt-tag pt-tag-${e.state}`}>{e.state}</span>
                {e.needs_check && (
                  <span className="pt-tag pt-tag-check">
                    <CircleAlert /> check this
                  </span>
                )}
                <span className={`pt-sync pt-sync-${e.sync}`} title={`Sync: ${SYNC_TEXT[e.sync]}`}>
                  {e.sync === "sent" ? <CloudCheck /> : e.sync === "rejected" ? <X /> : <CloudOff />}
                  {SYNC_TEXT[e.sync]}
                </span>
              </span>
            </div>
            {e.state === "heard" && (
              <div className="pt-tl-actions">
                <button type="button" className="pt-btn-confirm" onClick={() => onConfirm(e.client_entry_id)}>
                  <Check /> Confirm
                </button>
                <button type="button" className="pt-btn-discard" onClick={() => onDiscard(e.client_entry_id)} aria-label="Discard">
                  <Trash2 /> Discard
                </button>
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
