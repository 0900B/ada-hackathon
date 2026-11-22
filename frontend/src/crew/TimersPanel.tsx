import { Building2, Clock } from "lucide-react";
import { useT, type TKey } from "../i18n";
import { timers, type ClinicalEntry } from "./clinicalLog";
import type { EchoItem } from "./crewLogic";

/**
 * Elapsed time since the last drug, CPR started and stroke onset (only the ones that apply), and
 * what the ER has done about the case. Elapsed time only: this panel never advises anything.
 * Renders nothing when there is nothing to show.
 */
export function TimersPanel({ entries, nowIso, echo }: { entries: ClinicalEntry[]; nowIso: string; echo: EchoItem[] }) {
  const t = useT();
  const tm = timers(entries, nowIso);
  const lines: string[] = [];
  if (tm.lastDrugMin !== null) lines.push(t("pt.tm.lastDrug", { min: tm.lastDrugMin }));
  if (tm.cprMin !== null) lines.push(t("pt.tm.cpr", { min: tm.cprMin }));
  if (tm.strokeOnsetMin !== null) lines.push(t("pt.tm.stroke", { min: tm.strokeOnsetMin }));
  const er = echo.map((e) =>
    e.kind === "ack"
      ? t("pt.echo.ack")
      : e.kind === "bay"
        ? t("pt.echo.bay", { bay: e.value })
        : t("pt.echo.team", { team: teamName(t, e.value) }),
  );
  if (lines.length === 0 && er.length === 0) return null;
  return (
    <section className="pt-tm" aria-label={t("pt.tm.title")}>
      {lines.length > 0 && (
        <ul className="pt-tm-list">
          {lines.map((l) => (
            <li key={l}>
              <Clock /> {l}
            </li>
          ))}
        </ul>
      )}
      {er.length > 0 && (
        <ul className="pt-tm-list pt-tm-er">
          {er.map((l) => (
            <li key={l}>
              <Building2 /> {l}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** The team in the screen language when the dictionary knows it, else as the backend sent it. */
function teamName(t: ReturnType<typeof useT>, team: string): string {
  const key = `pt.team.${team}`;
  const known = ["stroke", "heart", "trauma", "resuscitation_room"].includes(team);
  return known ? t(key as TKey) : team;
}
