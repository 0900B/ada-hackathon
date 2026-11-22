import { Check, CircleAlert, CloudCheck, CloudOff, Trash2, X } from "lucide-react";
import { fmtTime } from "../format";
import { tOr, useT } from "../i18n";
import { ageMinutes, entryLabel, type ClinicalEntry } from "./clinicalLog";

/** The row's text: events in the screen language (by key), everything else as logged. */
function rowLabel(e: ClinicalEntry): string {
  const key = e.type === "event" && e.content ? e.content.key : undefined;
  return typeof key === "string" ? tOr(`pt.event.${key}`, entryLabel(e)) : entryLabel(e);
}

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
  const t = useT();
  const syncText = (s: ClinicalEntry["sync"]) =>
    t(s === "pending" ? "pt.sync.pending" : s === "sent" ? "pt.sync.sent" : "pt.sync.rejected");
  if (entries.length === 0) {
    return <p className="pt-tl-empty">{t("pt.tl.empty")}</p>;
  }
  return (
    <ol className="pt-tl" aria-label={t("pt.tl.aria")}>
      {entries.map((e) => {
        const age = ageMinutes(e, nowIso);
        const spoken = e.source === "crew_voice" && e.type === "note";
        return (
          <li key={e.client_entry_id} className={`pt-tl-row pt-tl-${e.state}${e.needs_check ? " pt-tl-check" : ""}`}>
            <div className="pt-tl-when">
              <span className="pt-tl-time">{fmtTime(e.t)}</span>
              <span className="pt-tl-age">{age === null ? "–" : age === 0 ? t("pt.tl.now") : t("pt.tl.ago", { min: age })}</span>
            </div>
            <div className="pt-tl-what">
              <span className={`pt-tl-label${spoken ? " pt-tl-spoken" : ""}`}>
                {spoken ? `“${entryLabel(e)}”` : rowLabel(e)}
              </span>
              <span className="pt-tl-tags">
                <span className={`pt-tag pt-tag-${e.state}`}>{t(e.state === "heard" ? "pt.state.heard" : "pt.state.confirmed")}</span>
                {e.needs_check && (
                  <span className="pt-tag pt-tag-check">
                    <CircleAlert /> {t("pt.check")}
                  </span>
                )}
                <span className={`pt-sync pt-sync-${e.sync}`} title={t("pt.sync.title", { state: syncText(e.sync) })}>
                  {e.sync === "sent" ? <CloudCheck /> : e.sync === "rejected" ? <X /> : <CloudOff />}
                  {syncText(e.sync)}
                </span>
              </span>
            </div>
            {e.state === "heard" && (
              <div className="pt-tl-actions">
                <button type="button" className="pt-btn-confirm" onClick={() => onConfirm(e.client_entry_id)}>
                  <Check /> {t("pt.confirm")}
                </button>
                <button type="button" className="pt-btn-discard" onClick={() => onDiscard(e.client_entry_id)} aria-label={t("pt.discard")}>
                  <Trash2 /> {t("pt.discard")}
                </button>
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
