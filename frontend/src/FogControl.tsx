/** Fog (megla) report: grounds every helicopter for an hour; its pending trips need road vehicles. */
import { CloudFog } from "lucide-react";
import { useT } from "./i18n";

const FOG_EVENT = { type: "fog", duration_min: 60 } as const;

export function FogControl({
  send,
  busy,
}: {
  send: (event: Record<string, unknown>) => Promise<void>;
  busy: boolean;
}) {
  const t = useT();
  return (
    <button disabled={busy} title={t("ops.fogTitle")} onClick={() => void send({ ...FOG_EVENT })}>
      <CloudFog /> {t("ops.fog")}
    </button>
  );
}
