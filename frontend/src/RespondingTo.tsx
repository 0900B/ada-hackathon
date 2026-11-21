import { ChevronRight, Info } from "lucide-react";
import type { Vehicle, VehicleDetail, WorldSnapshot } from "./api";
import { LEVEL_LABEL, levelOf } from "./severity";

/**
 * What a unit is doing, as the dispatcher thinks of it: the call it is responding to ("Responding to
 * 112-0042 · Critical · Cardiac arrest · Zaloška cesta 45 → UKC"), the ambulance a doctor car is
 * supporting, or where it is available. Clicking opens that call in the Calls tab.
 */
export function RespondingTo({
  v,
  state,
  detail,
  onOpenCall,
}: {
  v: Vehicle;
  state: WorldSnapshot;
  detail?: VehicleDetail | null;
  onOpenCall?: (tripId: string) => void;
}) {
  const place = (id: string) => state.places.find((p) => p.id === id)?.name ?? id;
  const tripId = v.current_trip_id ?? v.queue[0] ?? null;
  const trip = tripId ? state.trips.find((t) => t.id === tripId) : undefined;
  if (!trip) {
    const down = v.status === "out_of_service";
    return (
      <div className={`responding idle${down ? " down" : ""}`}>
        {down ? "Out of service" : `Available${v.status === "returning" ? ", returning to" : " at"} ${place(v.base_id)}`}
      </div>
    );
  }
  const r = detail?.responding_to && detail.responding_to.trip_id === trip.id ? detail.responding_to : null;
  const callId = r?.call_id ?? trip.call?.call_id ?? trip.id;
  const level = LEVEL_LABEL[r?.severity ?? levelOf(trip)];
  const cond = r?.condition_label ?? trip.condition_label ?? null;
  const address = r?.address ?? trip.call?.address ?? place(trip.pickup_id);
  const to = (r?.dropoff_name ?? place(trip.dropoff_id)).replace(/ Ljubljana$/, "");
  const next = v.current_trip_id ? "" : "Next: ";
  const text =
    v.type === "doctor"
      ? `Supporting ${trip.vehicle_id ?? "the ambulance"} at ${address} · ${callId} · ${level}${cond ? ` · ${cond}` : ""}`
      : `${next}Responding to ${callId} · ${level}${cond ? ` · ${cond}` : ""} · ${address} → ${to}`;
  return (
    <button className={`responding lvl-${levelOf(trip)}`} onClick={() => onOpenCall?.(trip.id)} disabled={!onOpenCall} title="Open this call">
      <span>{text}</span>
      {onOpenCall && <ChevronRight />}
    </button>
  );
}

/** Crew as role chips (names in the tooltip) and the unit's capabilities behind an info icon. */
export function CrewRoles({ crew, capabilities }: { crew: Vehicle["crew"]; capabilities?: string[] }) {
  return (
    <div className="crew-roles">
      {crew.map((c) => (
        <span key={c.name + c.role} className="role-chip" title={c.name.replace(" (fictional)", "")}>
          {c.role}
        </span>
      ))}
      {capabilities && capabilities.length > 0 && (
        <span className="caps-info" title={capabilities.join(" · ")} aria-label={`Capabilities: ${capabilities.join(", ")}`} tabIndex={0}>
          <Info />
        </span>
      )}
    </div>
  );
}
