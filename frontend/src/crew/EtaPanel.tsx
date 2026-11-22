import type { Trip, Vehicle, WorldSnapshot } from "../api";
import { ArrowRight, Hospital, MapPin } from "lucide-react";
import { fmtTime, vehicleStatusText } from "../format";
import { t as tx, useT } from "../i18n";
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
  const t = useT();
  const place = (id: string) => state.places.find((p) => p.id === id);
  const placeName = (id: string) => place(id)?.name ?? id;

  if (vehicle.type === "doctor" && trip) {
    return (
      <section className="pt-eta pt-eta-doctor" aria-label={t("pt.region.doctor")}>
        <div className="crew-doctor">{doctorJobLine(vehicle, trip, placeName)}</div>
        <div className="crew-route">
          {placeName(trip.pickup_id)} → {placeName(trip.dropoff_id)}
        </div>
        <div className="crew-eta">
          {vehicle.status === "to_pickup" ? (
            <>
              {t("crew.atScene")} <strong>{fmtTime(trip.doctor_eta ?? null)}</strong> · {trip.vehicle_id ?? t("tab.noAmbulanceYet")}
              {trip.vehicle_id && trip.status !== "onboard" && t("crew.atTime", { time: fmtTime(trip.eta_pickup) })}
            </>
          ) : (
            <>
              {t("crew.hospital")} <strong>{fmtTime(trip.eta_dropoff)}</strong> ·{" "}
              {trip.vehicle_id ? t("crew.withUnit", { unit: trip.vehicle_id }) : t("crew.withAmbulance")}
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
    const dest = `${toEr ? `${t("pt.er")} ` : ""}${placeName(trip.dropoff_id)}`;
    const late = eta.late && <span className="pt-late">{t("pt.late", { min: eta.lateMin })}</span>;

    if (stage === "with_patient") {
      return (
        <section className={`pt-eta pt-eta-er${eta.late ? " late" : ""}`} aria-label={t("pt.region.er")}>
          <div className="pt-eta-label">
            <Hospital /> {toEr ? t("pt.er") : t("pt.dropoff")}
          </div>
          <div className="pt-eta-place">{placeName(trip.dropoff_id)}</div>
          <BigMinutes minutes={eta.minutes} />
          <div className="pt-eta-sub">
            {t("pt.arrive")} <strong>{fmtTime(eta.arriveAt)}</strong> {late}
          </div>
        </section>
      );
    }

    const toPatient = minutesUntil(trip.eta_pickup, state.sim_time);
    return (
      <section className={`pt-eta pt-eta-pickup${eta.late ? " late" : ""}`} aria-label={t("pt.region.patient")}>
        <div className="pt-eta-label">
          <MapPin /> {t("pt.patientIn")}
        </div>
        <div className="pt-eta-place">{placeName(trip.pickup_id)}</div>
        <BigMinutes minutes={toPatient} />
        <div className="pt-eta-sub">
          {t("pt.arrive")} <strong>{fmtTime(trip.eta_pickup)}</strong> <ResponseLine trip={trip} now={state.sim_time} />
        </div>
        <div className="pt-eta-then">
          <ArrowRight /> {t("pt.then", { dest })}
          {eta.arriveAt && <> · {fmtTime(eta.arriveAt)}</>} {late}
        </div>
      </section>
    );
  }

  const queued = vehicle.queue[0] ? state.trips.find((x) => x.id === vehicle.queue[0]) : undefined;
  const stop = nextStop(vehicle, trip, queued, placeName);
  return (
    <section className="pt-eta pt-eta-idle" aria-label={t("pt.region.status")}>
      <div className="pt-eta-label">{t("pt.noPatient")}</div>
      <div className={`pt-status st-${vehicle.status}`}>{vehicleStatusText(vehicle, state.trips)}</div>
      {trip?.kind === "equipment" && (
        <div className="pt-eta-cargo">
          {t("pt.equipmentLabel")} <strong>{trip.cargo ?? t("tab.equipment")}</strong> <span className="muted">· {trip.id}</span>
        </div>
      )}
      {stop ? (
        <div className="crew-next">
          <ArrowRight /> {t("crew.nextStop")} <strong>{stop.label}</strong>
          {stop.eta && <> · {fmtTime(stop.eta)}</>}
          {vehicle.queue.length > (trip ? 0 : 1) && (
            <span className="muted">{t("crew.moreQueued", { count: vehicle.queue.length - (trip ? 0 : 1) })}</span>
          )}
          {!trip && queued && (
            <div className="crew-sev">
              <SeverityBadge trip={queued} size="md" />
            </div>
          )}
        </div>
      ) : (
        !trip && <div className="pt-eta-none muted">{t("crew.noTrip")}</div>
      )}
    </section>
  );
}

function BigMinutes({ minutes }: { minutes: number | null }) {
  const t = useT();
  return (
    <div className="pt-eta-big">
      <span className="pt-eta-min">{minutes ?? "–"}</span>
      {minutes !== null && <span className="pt-eta-unit">{t("pt.min")}</span>}
    </div>
  );
}

/** Where the vehicle is heading next, from the current trip (or the first queued one). */
function nextStop(v: Vehicle, trip: Trip | undefined, queued: Trip | undefined, place: (id: string) => string) {
  if (trip) {
    return trip.status === "onboard"
      ? { label: tx("crew.dropoffAt", { place: place(trip.dropoff_id) }), eta: trip.eta_dropoff }
      : { label: tx("crew.pickupAt", { place: place(trip.pickup_id) }), eta: trip.eta_pickup };
  }
  if (queued) return { label: tx("crew.nextTrip", { id: queued.id, place: place(queued.pickup_id) }), eta: queued.eta_pickup };
  if (v.status === "returning") return { label: tx("crew.backToBase", { place: place(v.base_id) }), eta: v.busy_until };
  return null;
}
