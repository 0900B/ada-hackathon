import { ClipboardCheck } from "lucide-react";
import { useT } from "../i18n";
import { handoverRemainingSec } from "./crewLogic";

/**
 * Shown instead of the idle screen after a patient trip ends, until the crew taps "Handover done":
 * the lines to read out at the hospital (oldest first) and the 15:00 handover countdown, red under
 * 3 minutes and "over" after 0. Elapsed time only; nothing here advises anything.
 */
export function HandoverScreen({
  lines,
  sinceIso,
  nowIso,
  onDone,
}: {
  lines: string[];
  sinceIso: string;
  nowIso: string;
  onDone: () => void;
}) {
  const t = useT();
  const left = handoverRemainingSec(sinceIso, nowIso);
  const over = left !== null && left < 0;
  const urgent = left !== null && left < 180;
  const abs = left === null ? null : Math.abs(left);
  const clock = abs === null ? "--:--" : `${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
  return (
    <section className="pt-log pt-ho" aria-label={t("pt.ho.title")}>
      <header className="pt-ho-head">
        <h2 className="pt-section-title">
          <ClipboardCheck /> {t("pt.ho.title")}
        </h2>
        <div className={`pt-ho-timer${urgent ? " urgent" : ""}`} role="timer" aria-label={t("pt.ho.timer")}>
          <span className="pt-ho-clock">{over ? t("pt.ho.over", { time: clock }) : clock}</span>
          <span className="pt-ho-sub">{t("pt.ho.timer")}</span>
        </div>
      </header>
      {lines.length === 0 ? (
        <p className="pt-log-empty">{t("pt.ho.empty")}</p>
      ) : (
        <ol className="pt-ho-lines">
          {lines.map((l, i) => (
            <li key={i} className={l.endsWith(" (check)") ? "check" : undefined}>
              {l.endsWith(" (check)") ? `${l.slice(0, -" (check)".length)} ${t("pt.ho.check")}` : l}
            </li>
          ))}
        </ol>
      )}
      <button type="button" className="pt-ho-done" onClick={onDone}>
        {t("pt.ho.done")}
      </button>
    </section>
  );
}
