import { Baby, TrendingDown, Users } from "lucide-react";
import type { Trip } from "./api";
import {
  conditionText,
  LEVEL_HELP,
  LEVEL_LABEL,
  LEVEL_SHORT,
  levelOf,
  modifierLabel,
  responseOf,
  responseText,
  targetMin,
  timeWeight,
  type Graded,
} from "./severity";

const MOD_ICON: Record<string, typeof Baby> = { child: Baby, deteriorating: TrendingDown, multiple_patients: Users };

/** Tooltip: level and what it means, the condition, time sensitivity, case modifiers and the target. */
export function severityTitle(t: Graded): string {
  const level = levelOf(t);
  const cond = conditionText(t);
  const w = timeWeight(t);
  const target = targetMin(t);
  return [
    `${LEVEL_LABEL[level]}${cond ? ` · ${cond}` : ""}`,
    LEVEL_HELP[level],
    w != null ? `Time sensitivity ${w}/10: how much waiting costs for this condition within its level (10 = cardiac arrest).` : "",
    t.modifiers?.length ? `Case: ${t.modifiers.map(modifierLabel).join(", ")}` : "",
    target != null ? `Response target: ${target} min to reach the patient.` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

/** Time sensitivity within the level as "T10"; stronger colour for the most time-critical conditions. */
export function TimeWeight({ w }: { w: number }) {
  return (
    <span className={`sev-tw${w >= 8 ? " hi" : w >= 5 ? " mid" : ""}`} aria-label={`time sensitivity ${w} of 10`}>
      T{w}
    </span>
  );
}

/**
 * The one badge for a call's severity everywhere: Critical (solid red), Serious (red outline),
 * Urgent (amber), Routine (neutral). Optionally the condition next to it ("Critical · Cardiac
 * arrest"), the time sensitivity (T1-T10) and the case modifiers as small icons.
 */
export function SeverityBadge({
  trip,
  size = "sm",
  compact = false,
  condition = true,
  weight = true,
  modifiers = true,
}: {
  trip: Graded;
  size?: "sm" | "md" | "lg";
  compact?: boolean; // level abbreviated (CRIT, SER, URG, RTN), nothing else: strips and dense lists
  condition?: boolean;
  weight?: boolean;
  modifiers?: boolean;
}) {
  const level = levelOf(trip);
  const cond = condition && !compact ? conditionText(trip) : null;
  const w = weight && !compact ? timeWeight(trip) : null;
  const mods = modifiers && !compact ? (trip.modifiers ?? []) : [];
  return (
    <span className={`sev sev-${level} sev-${size}${compact ? " sev-compact" : ""}`} title={severityTitle(trip)}>
      <span className="sev-level">{compact ? LEVEL_SHORT[level] : LEVEL_LABEL[level]}</span>
      {cond && <span className="sev-cond">{cond}</span>}
      {w != null && <TimeWeight w={w} />}
      {mods.map((m) => {
        const Icon = MOD_ICON[m];
        return Icon ? (
          <Icon key={m} className="sev-mod" aria-label={modifierLabel(m)} />
        ) : (
          <span key={m} className="sev-mod-text">
            {modifierLabel(m)}
          </span>
        );
      })}
    </span>
  );
}

/** Whether the call reaches its patient within the response target ("reaches in 11 min · target 8"). */
export function ResponseLine({ trip, now, compact = false }: { trip: Trip; now: string; compact?: boolean }) {
  const r = responseOf(trip, now);
  if (!r) return null;
  const title =
    r.minutes == null
      ? `No unit assigned yet: waiting ${Math.round(r.waited)} min, target ${r.target} min to reach the patient.`
      : `From the call (or the ready time) to reaching the patient: ${r.minutes} min. Target ${r.target} min${
          r.missed ? `: ${r.minutes - r.target} min over.` : "."
        }`;
  if (compact)
    return (
      <span className={`resp${r.missed ? " missed" : " met"}`} title={title}>
        {r.minutes ?? "—"}
        <span className="resp-target">/{r.target}</span>
      </span>
    );
  return (
    <span className={`resp${r.missed ? " missed" : " met"}`} title={title}>
      {responseText(r)}
    </span>
  );
}
