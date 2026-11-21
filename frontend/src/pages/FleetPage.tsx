import { Link } from "react-router";
import type { WorldSnapshot } from "../api";
import { fmtTime, vehicleStatusText } from "../format";
import { Callsign } from "../icons";
import { ResponseLine, SeverityBadge } from "../SeverityBadge";
import { doctorJobLine } from "../doctor";
import { DoctorTag, OriginTag } from "../DoctorTag";

/** Every vehicle with its current trip and projected queue (Live or Simulation: ?world=). */
export function FleetPage({ state }: { state: WorldSnapshot }) {
  const trips = new Map(state.trips.map((t) => [t.id, t]));
  const place = new Map(state.places.map((p) => [p.id, p.name]));

  return (
    <main className="page">
      <h2 className="page-title">
        Fleet · {state.hypothetical ? "Simulation" : "Live"}
        <span className="page-switch">
          <Link to="/fleet?world=live" className={state.hypothetical ? "" : "on"}>
            Live
          </Link>
          <Link to="/fleet?world=sim" className={state.hypothetical ? "on" : ""}>
            Simulation
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
                {v.type} · {vehicleStatusText(v, state.trips)} · base {place.get(v.base_id) ?? v.base_id}
                {v.busy_until ? ` · busy until ${fmtTime(v.busy_until)}` : ""}
                {v.grounded_until ? ` · grounded by fog until ${fmtTime(v.grounded_until)}` : ""}
              </p>
              {route.length === 0 ? (
                <p className="muted">No trips.</p>
              ) : (
                <ol className="schedule">
                  {route.map((id) => {
                    const t = trips.get(id);
                    if (!t) return null;
                    const late = (t.delay_min ?? 0) >= 5;
                    return (
                      <li key={id} className={late ? "late" : ""}>
                        <strong>{t.id}</strong> <SeverityBadge trip={t} /> <DoctorTag trip={t} vehicles={state.vehicles} now={state.sim_time} />{" "}
                        <span className="muted">{t.kind === "equipment" ? t.label : t.needs}</span>
                        <br />
                        {place.get(t.pickup_id)} → {place.get(t.dropoff_id)}
                        <br />
                        <span className="muted">
                          pickup {fmtTime(t.eta_pickup)} · drop-off {fmtTime(t.eta_dropoff)} · due {fmtTime(t.due_by)}
                          {late ? ` · +${Math.round(t.delay_min ?? 0)} min late` : ""}
                        </span>
                        {t.status !== "onboard" && (
                          <>
                            <br />
                            <ResponseLine trip={t} now={state.sim_time} />
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
