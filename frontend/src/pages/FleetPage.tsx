import { Link } from "react-router";
import type { WorldSnapshot } from "../api";
import { fmtTime, humanize, nightText, vehicleStatusText, vehicleTypeLabel } from "../format";
import { Callsign } from "../icons";
import { ResponseLine, SeverityBadge } from "../SeverityBadge";
import { doctorJobLine } from "../doctor";
import { DoctorTag, OriginTag } from "../DoctorTag";
import { tOr, useT } from "../i18n";

/** Every vehicle with its current trip and projected queue (Live or Simulation: ?world=). */
export function FleetPage({ state }: { state: WorldSnapshot }) {
  const t = useT();
  const trips = new Map(state.trips.map((x) => [x.id, x]));
  const place = new Map(state.places.map((p) => [p.id, p.name]));

  return (
    <main className="page">
      <h2 className="page-title">
        {t("fleet.title", { world: t(state.hypothetical ? "rep.worldSim" : "rep.worldLive") })}
        <span className="page-switch">
          <Link to="/fleet?world=live" className={state.hypothetical ? "" : "on"}>
            {t("rep.worldLive")}
          </Link>
          <Link to="/fleet?world=sim" className={state.hypothetical ? "on" : ""}>
            {t("rep.worldSim")}
          </Link>
        </span>
      </h2>
      <div className="fleet-grid">
        {state.vehicles.map((v) => {
          const route = [v.current_trip_id, ...v.queue].filter((id): id is string => Boolean(id));
          return (
            <section key={v.id} className={`panel vehicle-card st-${v.status}`}>
              <h3>
                <Callsign v={v} /> {v.name}
                <OriginTag v={v} />
              </h3>
              {v.type === "doctor" && trips.get(v.current_trip_id ?? "") && (
                <p className="vc-doctor">{doctorJobLine(v, trips.get(v.current_trip_id ?? ""), (id) => place.get(id) ?? id)}</p>
              )}
              <p className="muted">
                {vehicleTypeLabel(v.type)} · {vehicleStatusText(v, state.trips)} · {t("fleet.base", { place: place.get(v.base_id) ?? v.base_id })}
                {v.busy_until ? t("fleet.busyUntil", { time: fmtTime(v.busy_until) }) : ""}
                {v.grounded_until ? t("fleet.groundedUntil", { time: fmtTime(v.grounded_until) }) : nightText(v) ? ` · ${nightText(v)}` : ""}
              </p>
              {route.length === 0 ? (
                <p className="muted">{t("fleet.noTrips")}</p>
              ) : (
                <ol className="schedule">
                  {route.map((id) => {
                    const trip = trips.get(id);
                    if (!trip) return null;
                    const late = (trip.delay_min ?? 0) >= 5;
                    return (
                      <li key={id} className={late ? "late" : ""}>
                        <strong>{trip.id}</strong> <SeverityBadge trip={trip} /> <DoctorTag trip={trip} vehicles={state.vehicles} now={state.sim_time} />{" "}
                        <span className="muted">{trip.kind === "equipment" ? trip.label : tOr(`fleet.needs.${trip.needs}`, humanize(trip.needs))}</span>
                        <br />
                        {place.get(trip.pickup_id)} → {place.get(trip.dropoff_id)}
                        <br />
                        <span className="muted">
                          {t("fleet.times", { pickup: fmtTime(trip.eta_pickup), dropoff: fmtTime(trip.eta_dropoff), due: fmtTime(trip.due_by) })}
                          {late ? t("fleet.late", { min: Math.round(trip.delay_min ?? 0) }) : ""}
                        </span>
                        {trip.status !== "onboard" && (
                          <>
                            <br />
                            <ResponseLine trip={trip} now={state.sim_time} />
                          </>
                        )}
                      </li>
                    );
                  })}
                </ol>
              )}
            </section>
          );
        })}
      </div>
    </main>
  );
}
