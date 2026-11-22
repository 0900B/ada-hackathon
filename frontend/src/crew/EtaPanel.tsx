import type { Trip, Vehicle, WorldSnapshot } from "../api";
import { ArrowRight, Hospital, MapPin } from "lucide-react";
import { fmtTime, vehicleStatusText } from "../format";
import { ResponseLine, SeverityBadge } from "../SeverityBadge";
import { doctorJobLine } from "../doctor";
import { erEta, minutesUntil, type CrewStage } from "./crewLogic";

/**
 * The first thing the crew sees: the countdown to the hospital with a patient on board, the
 * countdown to the patient on the way there, or the vehicle's status and next stop otherwise.
 * Doctor cars keep their own lines (doctorJobLine and the doctor ETA block, unchanged).
 */
export function EtaPanel({
  state,
  vehicle,
  trip,
  stage,
}: {
  state: WorldSnapshot;
  vehicle: Vehicle;
  trip: Trip | undefined;
  stage: CrewStage;
}) {
  const place = (id: string) => state.places.find((p) => p.id === id);
  const placeName = (id: string) => place(id)?.name ?? id;

  if (vehicle.type === "doctor" && trip) {
    return (
      <section className="pt-eta pt-eta-doctor" aria-label="Doctor car">
        <div className="crew-doctor">{doctorJobLine(vehicle, trip, placeName)}</div>
        <div className="crew-route">
          {placeName(trip.pickup_id)} → {placeName(trip.dropoff_id)}
        </div>
        <div className="crew-eta">
          {vehicle.status === "to_pickup" ? (
            <>
              At the scene <strong>{fmtTime(trip.doctor_eta ?? null)}</strong> · {trip.vehicle_id ?? "no ambulance yet"}
              {trip.vehicle_id && trip.status !== "onboard" && <> at {fmtTime(trip.eta_pickup)}</>}
            </>
          ) : (
            <>
              Hospital <strong>{fmtTime(trip.eta_dropoff)}</strong> · with {trip.vehicle_id ?? "the ambulance"}
            </>
          )}
        </div>
      </section>
    );
  }

  if (trip && stage !== "no_patient") {
    const eta = erEta(trip, state.sim_time);
    const dropoff = place(trip.dropoff_id);
    const toEr = dropoff?.kind === "hospital";
    const dest = `${toEr ? "ER " : ""}${placeName(trip.dropoff_id)}`;
    const late = eta.late && <span className="pt-late">+{eta.lateMin} min late</span>;

    if (stage === "with_patient") {
      return (
        <section className={`pt-eta pt-eta-er${eta.late ? " late" : ""}`} aria-label="Arrival at the hospital">
          <div className="pt-eta-label">
            <Hospital /> {toEr ? "ER" : "Drop-off"}
          </div>
          <div className="pt-eta-place">{placeName(trip.dropoff_id)}</div>
          <BigMinutes minutes={eta.minutes} />
          <div className="pt-eta-sub">
            Arrive <strong>{fmtTime(eta.arriveAt)}</strong> {late}
          </div>
        </section>
      );
    }

    const toPatient = minutesUntil(trip.eta_pickup, state.sim_time);
    return (
      <section className={`pt-eta pt-eta-pickup${eta.late ? " late" : ""}`} aria-label="Arrival at the patient">
        <div className="pt-eta-label">
          <MapPin /> Patient in
        </div>
        <div className="pt-eta-place">{placeName(trip.pickup_id)}</div>
        <BigMinutes minutes={toPatient} />
        <div className="pt-eta-sub">
          Arrive <strong>{fmtTime(trip.eta_pickup)}</strong> <ResponseLine trip={trip} now={state.sim_time} />
        </div>
        <div className="pt-eta-then">
          <ArrowRight /> then {dest}
          {eta.arriveAt && <> · {fmtTime(eta.arriveAt)}</>} {late}
        </div>
      </section>
    );
  }

  const queued = vehicle.queue[0] ? state.trips.find((t) => t.id === vehicle.queue[0]) : undefined;
  const stop = nextStop(vehicle, trip, queued, placeName);
  return (
    <section className="pt-eta pt-eta-idle" aria-label="Vehicle status">
      <div className="pt-eta-label">No patient</div>
      <div className={`pt-status st-${vehicle.status}`}>{vehicleStatusText(vehicle, state.trips)}</div>
      {trip?.kind === "equipment" && (
        <div className="pt-eta-cargo">
          Equipment: <strong>{trip.cargo ?? "equipment"}</strong> <span className="muted">· {trip.id}</span>
        </div>
      )}
      {stop ? (
        <div className="crew-next">
          <ArrowRight /> Next stop: <strong>{stop.label}</strong>
          {stop.eta && <> · {fmtTime(stop.eta)}</>}
          {vehicle.queue.length > (trip ? 0 : 1) && (
            <span className="muted"> · {vehicle.queue.length - (trip ? 0 : 1)} more queued</span>
          )}
          {!trip && queued && (
            <div className="crew-sev">
              <SeverityBadge trip={queued} size="md" />
            </div>
          )}
        </div>
      ) : (
        !trip && <div className="pt-eta-none muted">No current trip.</div>
      )}
    </section>
  );
}

function BigMinutes({ minutes }: { minutes: number | null }) {
  return (
    <div className="pt-eta-big">
      <span className="pt-eta-min">{minutes ?? "–"}</span>
      {minutes !== null && <span className="pt-eta-unit">min</span>}
    </div>
  );
}

/** Where the vehicle is heading next, from the current trip (or the first queued one). */
function nextStop(v: Vehicle, trip: Trip | undefined, queued: Trip | undefined, place: (id: string) => string) {
  if (trip) {
    return trip.status === "onboard"
      ? { label: `Drop-off: ${place(trip.dropoff_id)}`, eta: trip.eta_dropoff }
      : { label: `Pickup: ${place(trip.pickup_id)}`, eta: trip.eta_pickup };
  }
  if (queued) return { label: `Next trip ${queued.id}: pickup at ${place(queued.pickup_id)}`, eta: queued.eta_pickup };
  if (v.status === "returning") return { label: `Back to base: ${place(v.base_id)}`, eta: v.busy_until };
  return null;
}
