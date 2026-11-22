import { useState } from "react";
import { postEvent, type EventRecord, type WorldSnapshot } from "./api";
import { useT } from "./i18n";
import { LEVEL_LABEL } from "./severity";

/** Part 1 of the brief: book a transport order; the engine places it into the live plan. */
export function BookingForm({ state }: { state: WorldSnapshot }) {
  const t = useT();
  const places = state.places.filter((p) => p.kind !== "incident_site" && p.kind !== "call_location");
  const hospitals = places.filter((p) => p.kind === "hospital" || p.kind === "health_centre");
  const [kind, setKind] = useState<"patient" | "equipment">("patient");
  const [pickup, setPickup] = useState(places.find((p) => p.kind === "residential")?.id ?? places[0]?.id ?? "");
  const [dropoff, setDropoff] = useState(hospitals[0]?.id ?? "");
  const [needs, setNeeds] = useState<"seated" | "wheelchair" | "stretcher">("seated");
  // Bookings are urgent or routine (critical and serious calls go through a new emergency, E)
  const [severity, setSeverity] = useState<"routine" | "urgent">("routine");
  const [readyIn, setReadyIn] = useState(20);
  const [deadline, setDeadline] = useState<string>("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  const book = async () => {
    setBusy(true);
    setResult(null);
    try {
      const rec: EventRecord = await postEvent(state.world, {
        type: "task_request",
        kind,
        pickup_id: pickup,
        dropoff_id: dropoff,
        needs: kind === "equipment" ? "equipment" : needs,
        priority: severity === "urgent" ? "urgent" : "scheduled",
        severity,
        ready_in_min: readyIn,
        due_in_min: deadline ? Number(deadline) : null,
        label: label.trim() || null,
      });
      setResult({ ok: true, text: rec.summary });
    } catch (e) {
      setResult({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="booking">
      <div className="row">
        <select value={kind} onChange={(e) => setKind(e.target.value as "patient" | "equipment")}>
          <option value="patient">{t("ops.bk.patient")}</option>
          <option value="equipment">{t("ops.bk.equipment")}</option>
        </select>
        {kind === "patient" ? (
          <select value={needs} onChange={(e) => setNeeds(e.target.value as typeof needs)}>
            <option value="seated">{t("ops.needs.seated")}</option>
            <option value="wheelchair">{t("ops.needs.wheelchair")}</option>
            <option value="stretcher">{t("ops.needs.stretcher")}</option>
          </select>
        ) : (
          <input placeholder={t("ops.bk.cargoPlaceholder")} value={label} onChange={(e) => setLabel(e.target.value)} />
        )}
        <select
          aria-label={t("ops.bk.severity")}
          value={severity}
          onChange={(e) => setSeverity(e.target.value as typeof severity)}
          title={t("ops.bk.severityTitle")}
        >
          <option value="routine">{LEVEL_LABEL.routine}</option>
          <option value="urgent">{LEVEL_LABEL.urgent}</option>
        </select>
      </div>
      <div className="row">
        <select value={pickup} onChange={(e) => setPickup(e.target.value)} title={t("ops.bk.from")}>
          {places.map((p) => (
            <option key={p.id} value={p.id}>
              {t("ops.bk.fromPlace", { name: p.name })}
            </option>
          ))}
        </select>
      </div>
      <div className="row">
        <select value={dropoff} onChange={(e) => setDropoff(e.target.value)} title={t("ops.bk.to")}>
          {places.map((p) => (
            <option key={p.id} value={p.id}>
              {t("ops.bk.toPlace", { name: p.name })}
            </option>
          ))}
        </select>
      </div>
      <div className="row booking-times">
        <label>
          {t("ops.bk.readyIn")}
          <input type="number" min={0} max={1440} value={readyIn} onChange={(e) => setReadyIn(Number(e.target.value))} /> min
        </label>
        <label>
          {t("ops.bk.dueWithin")}
          <input type="number" min={1} max={2880} placeholder={t("ops.bk.auto")} value={deadline} onChange={(e) => setDeadline(e.target.value)} /> min
        </label>
      </div>
      {kind === "patient" && (
        <input placeholder={t("ops.bk.labelPlaceholder")} value={label} onChange={(e) => setLabel(e.target.value)} />
      )}
      <button className="primary" disabled={busy || !pickup || !dropoff || pickup === dropoff} onClick={book}>
        {busy ? t("ops.bk.placing") : t("ops.bk.book")}
      </button>
      {result && <div className={`message ${result.ok ? "ok" : "error"}`}>{result.text}</div>}
    </div>
  );
}
