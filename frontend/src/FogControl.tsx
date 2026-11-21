/** Fog (megla) report: grounds every helicopter for an hour; its pending trips need road vehicles. */

const FOG_EVENT = { type: "fog", duration_min: 60 } as const;

export function FogControl({
  send,
  busy,
}: {
  send: (event: Record<string, unknown>) => Promise<void>;
  busy: boolean;
}) {
  return (
    <div className="row">
      <button
        disabled={busy}
        title="Fog at the helicopter base: no take-offs for 1 h. Trips not yet picked up go back to dispatch."
        onClick={() => void send({ ...FOG_EVENT })}
      >
        🌫 Fog: ground helicopters 1 h
      </button>
    </div>
  );
}
