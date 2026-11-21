import { Ambulance, Helicopter, Van, type LucideProps } from "lucide-react";
import type { Vehicle } from "./api";

/** The glyph for a vehicle type (same shapes as the map markers in glyphs.ts). */
export function VehicleTypeIcon({ type, ...props }: { type: Vehicle["type"] } & LucideProps) {
  const Icon = type === "ambulance" ? Ambulance : type === "helicopter" ? Helicopter : Van;
  return <Icon aria-hidden {...props} />;
}

/** Callsign badge: type glyph + id, e.g. [ambulance] A1. */
export function Callsign({ v, className = "" }: { v: Pick<Vehicle, "id" | "type">; className?: string }) {
  return (
    <span className={`veh ${className}`.trim()}>
      <VehicleTypeIcon type={v.type} />
      {v.id}
    </span>
  );
}
