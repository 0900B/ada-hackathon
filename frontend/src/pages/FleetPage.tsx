import type { WorldSnapshot } from "../api";
import { fmtTime, humanize } from "../format";

/** Example subpage: every vehicle with its current trip and projected queue. */
export function FleetPage({ state }: { state: WorldSnapshot }) {
  const trips = new Map(state.trips.map((t) => [t.id, t]));
  const place = new Map(state.places.map((p) => [p.id, p.name]));

  return (
    <main className="page">
      <h2>Fleet</h2>
      <div className="fleet-grid">
        {state.vehicles.map((v) => {
          const route = [v.current_trip_id, ...v.queue].filter((id): id is string => Boolean(id));
          return (
            <section key={v.id} className={`panel vehicle-card st-${v.status}`}>
              <h3>
                <span className={`veh veh-${v.type}`}>{v.id}</span> {v.name}
              </h3>
              <p className="muted">
                {v.type} · {humanize(v.status)} · base {place.get(v.base_id) ?? v.base_id}
                {v.busy_until ? ` · busy until ${fmtTime(v.busy_until)}` : ""}
                {v.grounded_until ? ` · 🌫 grounded by fog until ${fmtTime(v.grounded_until)}` : ""}
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
                        <strong>{t.id}</strong> <span className={`prio prio-${t.priority}`}>{t.priority}</span> {t.needs}
                        <br />
                        {place.get(t.pickup_id)} → {place.get(t.dropoff_id)}
                        <br />
                        <span className="muted">
                          pickup {fmtTime(t.eta_pickup)} · drop-off {fmtTime(t.eta_dropoff)} · due {fmtTime(t.due_by)}
                          {late ? ` · +${Math.round(t.delay_min ?? 0)} min late` : ""}
                        </span>
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
