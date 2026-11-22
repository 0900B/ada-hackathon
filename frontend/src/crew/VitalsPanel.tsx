import { CircleAlert, HeartPulse, Plus } from "lucide-react";
import { useT } from "../i18n";
import { ageMinutes, entryLabel, latestOf, vitalsStatus, type ClinicalEntry } from "./clinicalLog";
import type { Level } from "../severity";

/**
 * The newest vitals with their age, always together: a vital is never shown without how old it is.
 * Amber and "overdue" once a new set is due for the case's severity; "No vitals yet" before any.
 * The Enter vitals button opens the vitals pad.
 */
export function VitalsPanel({
  entries,
  nowIso,
  level,
  onEnter,
}: {
  entries: ClinicalEntry[];
  nowIso: string;
  level: Level;
  onEnter: () => void;
}) {
  const t = useT();
  const latest = latestOf(entries, "vitals");
  const status = vitalsStatus(entries, nowIso, level);
  const age = latest ? ageMinutes(latest, nowIso) : null;

  return (
    <section className="pt-vp" aria-label={t("pt.vp.title")}>
      <h2 className="pt-section-title">
        <HeartPulse /> {t("pt.vp.title")}
      </h2>
      {latest ? (
        <>
          <div className="pt-vp-values">{entryLabel(latest)}</div>
          <div className={`pt-vp-age${status.overdue ? " pt-vp-overdue" : ""}`}>
            {age === null ? t("pt.vp.lastUnknown") : t("pt.vp.last", { min: age })}
            {status.overdue && (
              <span className="pt-tag pt-tag-check">
                <CircleAlert /> {t("pt.vp.overdue")}
              </span>
            )}
            {latest.needs_check && (
              <span className="pt-tag pt-tag-check">
                <CircleAlert /> {t("pt.check")}
              </span>
            )}
          </div>
        </>
      ) : (
        <div className="pt-vp-age pt-vp-overdue">{t("pt.vp.none")}</div>
      )}
      <button type="button" className="pt-vp-enter" onClick={onEnter}>
        <Plus /> {t("pt.vp.enter")}
      </button>
    </section>
  );
}
