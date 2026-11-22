const TZ = "Europe/Ljubljana";

/** Backend times are UTC with an offset; staff read Ljubljana local time (contract section 7, item 4). */
export function clock(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: TZ });
}

export function minutesBetween(fromIso: string, toIso: string): number {
  return (new Date(toIso).getTime() - new Date(fromIso).getTime()) / 60000;
}

/** "just now", "6 min", "1 h 5 min": world minutes, whole numbers. */
export function duration(min: number): string {
  const m = Math.max(0, Math.round(min));
  if (m < 1) return "under 1 min";
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h} h ${r} min` : `${h} h`;
}

export function ago(min: number): string {
  return Math.round(min) < 1 ? "just now" : `${duration(min)} ago`;
}

export function sexLabel(sex: string | null): string {
  return sex === "f" ? "female" : sex === "m" ? "male" : "";
}
