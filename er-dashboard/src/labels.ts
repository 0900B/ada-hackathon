import type { AlertSeverity, Team, VitalKey } from "./api";

/** Plain-language names for the contract's enums. Slovenian stage names are the backend's own; English glosses are ours (to confirm with ER staff). */
export const PROBLEM_LABEL: Record<string, string> = {
  chest_pain: "Chest pain",
  stemi: "Heart attack (STEMI)",
  stroke: "Stroke",
  breathing_difficulty: "Breathing difficulty",
  severe_head_injury: "Severe head injury",
  resuscitation: "Resuscitation",
  polytrauma: "Multiple injuries",
  sepsis: "Sepsis",
  poisoning: "Poisoning",
  other: "Problem not specified",
};

/**
 * The headline of a case. Triage often names no specific problem ("other"): then the dispatcher's own
 * words from the call are more useful to staff than "problem not specified".
 */
export function caseTitle(problem: { type: string | null; note: string | null }): string {
  if (problem.type && problem.type !== "other") return PROBLEM_LABEL[problem.type] ?? problem.type;
  if (problem.note) return problem.note.charAt(0).toUpperCase() + problem.note.slice(1);
  return problem.type ? PROBLEM_LABEL.other : "Not triaged yet";
}
/** True when caseTitle already shows the note, so the note must not be repeated under it. */
export const titleIsNote = (problem: { type: string | null; note: string | null }) =>
  !(problem.type && problem.type !== "other") && !!problem.note;

export const STAGES:{ stage: string; gloss: string }[] = [
  { stage: "SPREJETO", gloss: "Accepted" },
  { stage: "NA POTI", gloss: "On the way" },
  { stage: "NA KRAJU", gloss: "At the scene" },
  { stage: "PRI PACIENTU", gloss: "With patient" },
  { stage: "S KRAJA", gloss: "Coming to ER" },
  { stage: "NA CILJU", gloss: "Arrived" },
  { stage: "PREDAJA PACIENTA", gloss: "Handover" },
  { stage: "PROST", gloss: "Unit free" },
];
export const stageIndex = (stage: string | null) => STAGES.findIndex((s) => s.stage === stage);
export const stageGloss = (stage: string | null) => STAGES.find((s) => s.stage === stage)?.gloss ?? "Not assigned yet";
/** A case is "here" once the unit has reached the ER, whatever the engine's arrival flag says. */
export const ARRIVED_STAGES = new Set(["NA CILJU", "PREDAJA PACIENTA", "PROST"]);

export const LEVEL_LABEL = { red: "Red", yellow: "Yellow", scheduled: "Scheduled" } as const;

export const TEAM_LABEL: Record<Team, string> = {
  stroke: "Stroke team",
  heart: "Heart team",
  trauma: "Trauma team",
  resuscitation_room: "Resuscitation room",
};
export const TEAMS: Team[] = ["stroke", "heart", "trauma", "resuscitation_room"];

export const SEVERITY_LABEL: Record<string, string> = {
  blue: "Blue",
  green: "Green",
  orange: "Orange",
  red: "Red",
  arrest: "Arrest",
};

export const EVENT_LABEL: Record<string, string> = {
  arrest: "Cardiac arrest",
  resuscitation_started: "Resuscitation started",
  rosc: "Pulse back (ROSC)",
  airway: "Airway secured",
  stroke_onset: "Stroke began",
  stemi: "STEMI on ECG",
  transfusion: "Transfusion",
};

export const ALERT_ORDER: AlertSeverity[] = ["critical", "high", "medium", "low"];
export const ALERT_LABEL: Record<AlertSeverity, string> = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };

export const VITAL_DEFS: { key: VitalKey; label: string; unit: string }[] = [
  { key: "hr", label: "Heart rate", unit: "bpm" },
  { key: "spo2", label: "Oxygen", unit: "%" },
  { key: "sbp", label: "Blood pressure", unit: "mmHg" }, // sbp and dbp are shown together
  { key: "rr", label: "Breathing", unit: "/min" },
  { key: "gcs", label: "Consciousness (GCS)", unit: "" },
  { key: "temp_c", label: "Temperature", unit: "°C" },
  { key: "glucose_mmol", label: "Glucose", unit: "mmol/L" },
];

export const ENTRY_LABEL: Record<string, string> = {
  triage: "Triage",
  patient_info: "Patient details",
  vitals: "Vitals",
  drug_administered: "Drug given",
  procedure: "Procedure",
  severity: "Severity",
  event: "Event",
  handover: "Handover",
  free: "Unit free",
  note: "Note",
  er_action: "ER action",
};
