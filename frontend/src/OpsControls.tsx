import { useState } from "react";
import { Hospital, TriangleAlert } from "lucide-react";
import type { Priority, WorldSnapshot } from "./api";
import { compareTrips, conditionText, LEVEL_LABEL, LEVEL_PRIORITY, LEVELS, levelOf, severitySupported, type Level } from "./severity";
import { SeverityBadge } from "./SeverityBadge";

const PRIORITIES: Priority[] = ["emergency", "urgent", "scheduled"];

/**
 * Operator events: change a trip's priority (sprememba prioritete) and set how many more patients a
 * hospital can admit (zmanjšana kapaciteta bolnišnice). Both go through the parent's `send`.
 */
export function OpsControls({
  state,
  send,
  busy,
}: {
  state: WorldSnapshot;
  send: (event: Record<string, unknown>) => Promise<void>;
  busy: boolean;
}) {
  const open = state.trips.filter((t) => t.status !== "completed" && t.status !== "cancelled").sort(compareTrips);
  // Backends with severity levels take a level (and still the matching priority); older ones a priority
  const graded = severitySupported(state.trips);
  const hospitals = state.places.filter((p) => p.kind === "hospital");

  const [tripPick, setTripPick] = useState("");
  const [priority, setPriority] = useState<Priority>("emergency");
  const [level, setLevel] = useState<Level>("critical");
  const [hospitalPick, setHospitalPick] = useState("ukc");
  const [capacity, setCapacity] = useState(2);

  const trip = open.find((t) => t.id === tripPick) ?? open[0];
  const hospital = hospitals.find((p) => p.id === hospitalPick) ?? hospitals[0];
  const incoming = (placeId: string) => open.filter((t) => t.kind === "patient" && t.dropoff_id === placeId).length;
  const overCapacity = hospital ? state.alerts.find((a) => a.id === `hospital_over_capacity:${hospital.id}`) : undefined;

  return (
    <div className="controls ops-controls">
      <div className="scenario-label muted">{graded ? "Change a call's severity" : "Change a trip's priority"}</div>
      <div className="row">
        <select aria-label="Trip" value={trip?.id ?? ""} onChange={(e) => setTripPick(e.target.value)}>
          {open.map((t) => {
            const cond = conditionText(t);
            return (
              <option key={t.id} value={t.id}>
                {t.id} · {t.label} · {graded ? `${LEVEL_LABEL[levelOf(t)]}${cond ? `: ${cond}` : ""}` : t.priority}
              </option>
            );
          })}
        </select>
      </div>
      {graded ? (
        <div className="row">
          {trip && <SeverityBadge trip={trip} />}
          <select aria-label="New severity" value={level} onChange={(e) => setLevel(e.target.value as Level)}>
            {LEVELS.map((l) => (
              <option key={l} value={l}>
                {LEVEL_LABEL[l]}
              </option>
            ))}
          </select>
          <button
            disabled={busy || !trip || levelOf(trip) === level}
            title={trip && levelOf(trip) === level ? `${trip.id} is already ${LEVEL_LABEL[level].toLowerCase()}` : undefined}
            onClick={() => trip && send({ type: "priority_change", trip_id: trip.id, priority: LEVEL_PRIORITY[level], severity: level })}
          >
            Set severity
          </button>
        </div>
      ) : (
      <div className="row">
        <select aria-label="New priority" value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <button
          disabled={busy || !trip || trip.priority === priority}
          title={trip?.priority === priority ? `${trip.id} is already ${priority}` : undefined}
          onClick={() => trip && send({ type: "priority_change", trip_id: trip.id, priority })}
        >
          Set priority
        </button>
      </div>
      )}

      <div className="scenario-label muted">Hospital capacity (admissions it can still take)</div>
      <div className="row">
        <select aria-label="Hospital" value={hospital?.id ?? ""} onChange={(e) => setHospitalPick(e.target.value)}>
          {hospitals.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} · can admit {p.capacity ?? "∞"} · {incoming(p.id)} incoming
            </option>
          ))}
        </select>
      </div>
      <div className="row">
        <input
          type="number"
          aria-label="Admissions"
          min={0}
          max={1000}
          value={capacity}
          onChange={(e) => setCapacity(Math.max(0, Math.round(Number(e.target.value) || 0)))}
        />
        <button
          disabled={busy || !hospital}
          onClick={() => hospital && send({ type: "hospital_capacity", place_id: hospital.id, capacity })}
        >
          <Hospital /> Set capacity
        </button>
        <button
          className="ghost"
          disabled={busy || !hospital || hospital.capacity === null}
          onClick={() => hospital && send({ type: "hospital_capacity", place_id: hospital.id, capacity: null })}
        >
          No limit
        </button>
      </div>
      {overCapacity && (
        <p className="ops-warn">
          <TriangleAlert /> <span>{overCapacity.message}</span>
        </p>
      )}
    </div>
  );
}
