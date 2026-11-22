import { ChevronRight, Info } from "lucide-react";
import type { Vehicle, VehicleDetail, WorldSnapshot } from "./api";
import { tOr, useLang, useT } from "./i18n";
import { conditionText, LEVEL_LABEL, levelOf } from "./severity";

/** A crew role from the backend's fixed set in the UI language ("Medical rescuer (driver)" / "Reševalec (voznik)"). */
const crewRoleLabel = (role: string) => tOr(`ops.role.${role}`, role);

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
  const t = useT();
  const lang = useLang();
  const place = (id: string) => state.places.find((p) => p.id === id)?.name ?? id;
  const tripId = v.current_trip_id ?? v.queue[0] ?? null;
  const trip = tripId ? state.trips.find((x) => x.id === tripId) : undefined;
  if (!trip) {
    const down = v.status === "out_of_service";
    return (
      <div className={`responding idle${down ? " down" : ""}`}>
        {down
          ? t("ops.popOutOfService")
          : t(v.status === "returning" ? "ops.resp.availableReturning" : "ops.resp.availableAt", { place: place(v.base_id) })}
      </div>
    );
  }
  const r = detail?.responding_to && detail.responding_to.trip_id === trip.id ? detail.responding_to : null;
  const callId = r?.call_id ?? trip.call?.call_id ?? trip.id;
  const level = LEVEL_LABEL[r?.severity ?? levelOf(trip)];
  const condSent = r?.condition_label ?? trip.condition_label ?? null;
  // Slovenian: the condition code's Slovenian label (the backend's label is English)
  const cond = lang === "sl" ? (conditionText(trip) ?? condSent) : condSent;
  const address = r?.address ?? trip.call?.address ?? place(trip.pickup_id);
  const to = (r?.dropoff_name ?? place(trip.dropoff_id)).replace(/ Ljubljana$/, "");
  const condPart = cond ? ` · ${cond}` : "";
  const text =
    v.type === "doctor"
      ? t("ops.resp.supporting", { unit: trip.vehicle_id ?? t("dr.theAmbulance"), address, call: callId, level, cond: condPart })
      : t(v.current_trip_id ? "ops.resp.responding" : "ops.resp.nextResponding", { call: callId, level, cond: condPart, address, to });
  return (
    <button className={`responding lvl-${levelOf(trip)}`} onClick={() => onOpenCall?.(trip.id)} disabled={!onOpenCall} title={t("ops.resp.openCall")}>
      <span>{text}</span>
      {onOpenCall && <ChevronRight />}
    </button>
  );
}

/** Crew as role chips (names in the tooltip) and the unit's capabilities behind an info icon. */
export function CrewRoles({ crew, capabilities }: { crew: Vehicle["crew"]; capabilities?: string[] }) {
  const t = useT();
  return (
    <div className="crew-roles">
      {crew.map((c) => (
        <span key={c.name + c.role} className="role-chip" title={c.name.replace(" (fictional)", "")}>
          {crewRoleLabel(c.role)}
        </span>
      ))}
      {capabilities && capabilities.length > 0 && (
        <span className="caps-info" title={capabilities.join(" · ")} aria-label={t("ops.capabilities", { list: capabilities.join(", ") })} tabIndex={0}>
          <Info />
        </span>
      )}
    </div>
  );
}
