import type { VehicleDetail, WorldSnapshot } from "./api";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  CornerUpRight,
  Crosshair,
  ExternalLink,
  Fuel,
  House,
  Plane,
  Smartphone,
  Tablet,
  Timer,
  Wrench,
  X,
  CloudFog,
} from "lucide-react";
import { flightTarget, fmtTime, vehicleStatusText } from "./format";
import { Callsign } from "./icons";
import { levelOf } from "./severity";
import { ResponseLine, SeverityBadge } from "./SeverityBadge";
import { doctorJobLine } from "./doctor";
import { DoctorTag, OriginTag } from "./DoctorTag";
import { CrewRoles, RespondingTo } from "./RespondingTo";

type Send = (event: Record<string, unknown>) => Promise<void>;

const STOP_ICON = { pickup: ArrowUpFromLine, dropoff: ArrowDownToLine, base: House } as const;

/** Floating card for the selected vehicle: crew, fuel, current job, upcoming stops, quick actions. */
export function VehicleCard({
  detail,
  state,
  onClose,
  onCenter,
  onOpenCall,
  send,
  busy,
}: {
  detail: VehicleDetail;
  state: WorldSnapshot;
  onClose: () => void;
  onCenter: () => void;
  onOpenCall?: (tripId: string) => void; // open the call it responds to (Calls tab)
  send: Send;
  busy: boolean;
}) {
  const v = detail.vehicle;
  // the snapshot's copy of the current trip is newer than the detail's (refreshed every 3 s)
  const t = detail.current_trip ? (state.trips.find((x) => x.id === detail.current_trip!.id) ?? detail.current_trip) : null;
  const tripOf = (id: string | null) => (id ? state.trips.find((x) => x.id === id) : undefined);
  const fuelClass = detail.fuel.pct < 10 ? "bad" : detail.fuel.low ? "warn" : "ok";
  const down = v.status === "out_of_service";
  const heli = v.type === "helicopter";
  const flight = heli
    ? flightTarget(
        v,
        t ?? undefined,
        new Map(state.places.map((p) => [p.id, p])),
        state.trips.find((x) => x.id === v.queue[0]),
      )
    : null;

  return (
    <div className="vehicle-card-float">
      <div className="vc-head">
        <Callsign v={v} />
        <strong>{v.name}</strong>
        <OriginTag v={v} />
        <span className="muted">· {vehicleStatusText(v, state.trips)}</span>
        <button className="link vc-close" onClick={onClose} title="Close (Esc)">
          <X />
        </button>
      </div>
      <RespondingTo v={state.vehicles.find((x) => x.id === v.id) ?? v} state={state} detail={detail} onOpenCall={onOpenCall} />

      {heli && (
        <div className={`vc-flight${v.grounded_until ? " grounded" : ""}`}>
          {v.grounded_until ? <CloudFog /> : <Plane />}
          {v.grounded_until
            ? `Grounded by fog until ${fmtTime(v.grounded_until)}: no new flights${flight ? ` (finishing: ${flight.kind} ${flight.place.name})` : ""}`
            : flight
              ? `${v.busy_until ? "On the ground, next" : "Flying"} to ${flight.kind === "base" ? "base" : flight.kind}: ${flight.place.name} · straight line, 200 km/h`
              : "Parked at base, ready to fly (straight line, 200 km/h)"}
        </div>
      )}

      <div className="vc-fuel">
        <div className="vc-fuel-label">
          <Fuel /> Fuel {detail.fuel.pct.toFixed(0)}%{detail.fuel.range_km != null && <span className="muted"> · ~{detail.fuel.range_km} km range</span>}
        </div>
        <div className="vc-bar">
          <div className={`vc-bar-fill ${fuelClass}`} style={{ width: `${Math.max(2, detail.fuel.pct)}%` }} />
        </div>
        <div className="muted">
          {v.km_today.toFixed(1)} km today · base {detail.base}
          {v.shift_end ? ` · shift until ${fmtTime(v.shift_end)}` : ""}
        </div>
      </div>

      <div className="vc-section">
        <div className="vc-title">Crew</div>
        <CrewRoles crew={v.crew} capabilities={detail.capabilities} />
      </div>

      <div className="vc-section">
        <div className="vc-title">Now</div>
        {t ? (
          <>
            {v.type === "doctor" && (
              <div className="vc-doctor">{doctorJobLine(v, t, (id) => state.places.find((p) => p.id === id)?.name ?? id)}</div>
            )}
            <div>
              <strong className="id">{t.id}</strong> {t.label ?? t.patient}
            </div>
            <div className="sev-row">
              <SeverityBadge trip={t} />
              <DoctorTag trip={t} vehicles={state.vehicles} now={state.sim_time} />
            </div>
            {t.status !== "onboard" && v.type !== "doctor" && (
              <div className="small">
                <ResponseLine trip={t} now={state.sim_time} />
              </div>
            )}
          </>
        ) : (
          <div className="muted">{down ? "Out of service" : "No active job"}</div>
        )}
        {(detail.detour_legs?.length ?? 0) > 0 && (
          <div className="vc-detour">
            <CornerUpRight /> {detail.detour_legs?.includes(0) ? "Rerouted" : "Will be rerouted"} around a road closure (orange on the map)
          </div>
        )}
      </div>

      {detail.stops.length > 0 && (
        <div className="vc-section">
          <div className="vc-title">Next stops (highlighted on the map)</div>
          <ol className="vc-stops">
            {detail.stops.map((s, i) => {
              const StopIcon = STOP_ICON[s.kind];
              return (
              <li key={i} className={(s.delay_min ?? 0) >= 5 ? "late" : ""}>
                <span className="vc-num">{i + 1}</span> <StopIcon aria-label={s.kind} /> {s.eta ? fmtTime(s.eta) : "—"} · {s.place}
                {s.trip_id && <span className="muted"> · {s.trip_id}</span>}
                {s.kind === "pickup" && tripOf(s.trip_id) && levelOf(tripOf(s.trip_id)!) !== "routine" && (
                  <>
                    {" "}
                    <SeverityBadge trip={tripOf(s.trip_id)!} compact />
                  </>
                )}
                {(s.delay_min ?? 0) >= 5 && <span> · +{Math.round(s.delay_min ?? 0)} min</span>}
              </li>
              );
            })}
          </ol>
        </div>
      )}

      <div className="row vc-actions">
        <button onClick={onCenter}>
          <Crosshair /> Centre
        </button>
        <button
          disabled={busy || down}
          title="Delay this vehicle by 10 minutes (hotkey D)"
          onClick={() => send({ type: "delay", vehicle_id: v.id, minutes: 10, note: "reported from vehicle card" })}
        >
          <Timer /> +10 min
        </button>
        <button
          disabled={busy || down}
          title="Report a breakdown of this vehicle (hotkey B)"
          onClick={() => send({ type: "breakdown", vehicle_id: v.id, note: "reported from vehicle card" })}
        >
          <Wrench /> Breakdown
        </button>
      </div>
      <div className="vc-links">
        <a className="button-link" href={`/vehicle/${encodeURIComponent(v.id)}?world=${state.world}`} target="_blank" rel="noopener">
          <Tablet /> Tablet view <ExternalLink />
        </a>
        <a className="button-link" href={`/crew/${encodeURIComponent(v.id)}?world=${state.world}`} target="_blank" rel="noopener">
          <Smartphone /> Crew phone <ExternalLink />
        </a>
      </div>
    </div>
  );
}
