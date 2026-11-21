/** Shared formatting helpers. */

export const fmtTime = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleTimeString("sl-SI", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Ljubljana" })
    : "–";

export const humanize = (s: string) => s.replace(/_/g, " ");
