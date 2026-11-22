import { useState } from "react";
import { Hospital, TriangleAlert } from "lucide-react";
import type { Priority, WorldSnapshot } from "./api";
import { compareTrips, conditionText, LEVEL_LABEL, LEVEL_PRIORITY, LEVELS, levelOf, severitySupported, type Level } from "./severity";
import { SeverityBadge } from "./SeverityBadge";
import { tOr, useLang, useT } from "./i18n";

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
  const t = useT();
  const lang = useLang();
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

  const prioLabel = (p: string) => tOr(`ops.prio.${p}`, p);
  // English keeps "is already critical" in lower case; Slovenian names the level as it is
  const levelWord = (l: Level) => (lang === "en" ? LEVEL_LABEL[l].toLowerCase() : LEVEL_LABEL[l]);

  return (
    <div className="controls ops-controls">
      <div className="scenario-label muted">{t(graded ? "ops.pc.changeSeverity" : "ops.pc.changePriority")}</div>
      <div className="row">
        <select aria-label={t("ops.pc.trip")} value={trip?.id ?? ""} onChange={(e) => setTripPick(e.target.value)}>
          {open.map((x) => {
            const cond = conditionText(x);
            return (
              <option key={x.id} value={x.id}>
                {x.id} · {x.label} · {graded ? `${LEVEL_LABEL[levelOf(x)]}${cond ? `: ${cond}` : ""}` : prioLabel(x.priority)}
              </option>
            );
          })}
        </select>
      </div>
      {graded ? (
        <div className="row">
          {trip && <SeverityBadge trip={trip} />}
          <select aria-label={t("ops.pc.newSeverity")} value={level} onChange={(e) => setLevel(e.target.value as Level)}>
            {LEVELS.map((l) => (
              <option key={l} value={l}>
                {LEVEL_LABEL[l]}
              </option>
            ))}
          </select>
          <button
            disabled={busy || !trip || levelOf(trip) === level}
            title={trip && levelOf(trip) === level ? t("ops.pc.alreadyLevel", { id: trip.id, level: levelWord(level) }) : undefined}
            onClick={() => trip && send({ type: "priority_change", trip_id: trip.id, priority: LEVEL_PRIORITY[level], severity: level })}
          >
            {t("ops.pc.setSeverity")}
          </button>
        </div>
      ) : (
      <div className="row">
        <select aria-label={t("ops.pc.newPriority")} value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {prioLabel(p)}
            </option>
          ))}
        </select>
        <button
          disabled={busy || !trip || trip.priority === priority}
          title={trip?.priority === priority ? t("ops.pc.alreadyPriority", { id: trip.id, priority: prioLabel(priority) }) : undefined}
          onClick={() => trip && send({ type: "priority_change", trip_id: trip.id, priority })}
        >
          {t("ops.pc.setPriority")}
        </button>
      </div>
      )}

      <div className="scenario-label muted">{t("ops.pc.capacityLabel")}</div>
      <div className="row">
        <select aria-label={t("ops.pc.hospital")} value={hospital?.id ?? ""} onChange={(e) => setHospitalPick(e.target.value)}>
          {hospitals.map((p) => (
            <option key={p.id} value={p.id}>
              {t("ops.pc.hospitalOption", { name: p.name, cap: p.capacity ?? "∞", n: incoming(p.id) })}
            </option>
          ))}
        </select>
      </div>
      <div className="row">
        <input
          type="number"
          aria-label={t("ops.pc.admissions")}
          min={0}
          max={1000}
          value={capacity}
          onChange={(e) => setCapacity(Math.max(0, Math.round(Number(e.target.value) || 0)))}
        />
        <button
          disabled={busy || !hospital}
          onClick={() => hospital && send({ type: "hospital_capacity", place_id: hospital.id, capacity })}
        >
          <Hospital /> {t("ops.pc.setCapacity")}
        </button>
        <button
          className="ghost"
          disabled={busy || !hospital || hospital.capacity === null}
          onClick={() => hospital && send({ type: "hospital_capacity", place_id: hospital.id, capacity: null })}
        >
          {t("ops.pc.noLimit")}
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
