/** Fog (megla) report: grounds every helicopter for an hour; its pending trips need road vehicles. */
import { CloudFog } from "lucide-react";

const FOG_EVENT = { type: "fog", duration_min: 60 } as const;

export function FogControl({
  send,
  busy,
}: {
  send: (event: Record<string, unknown>) => Promise<void>;
  busy: boolean;
}) {
  return (
    <button
      disabled={busy}
      title="Fog at the helicopter base: no take-offs for 1 h. Trips not yet picked up go back to dispatch. (hotkey F)"
      onClick={() => void send({ ...FOG_EVENT })}
    >
      <CloudFog /> Fog: ground helicopters 1 h
    </button>
  );
}
