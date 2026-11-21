import { useState } from "react";
import { postEvent, type EventRecord, type WorldSnapshot } from "./api";

/** Part 1 of the brief: book a transport order; the engine places it into the live plan. */
export function BookingForm({ state }: { state: WorldSnapshot }) {
  const places = state.places.filter((p) => p.kind !== "incident_site" && p.kind !== "call_location");
  const hospitals = places.filter((p) => p.kind === "hospital" || p.kind === "health_centre");
  const [kind, setKind] = useState<"patient" | "equipment">("patient");
  const [pickup, setPickup] = useState(places.find((p) => p.kind === "residential")?.id ?? places[0]?.id ?? "");
  const [dropoff, setDropoff] = useState(hospitals[0]?.id ?? "");
  const [needs, setNeeds] = useState<"seated" | "wheelchair" | "stretcher">("seated");
  const [priority, setPriority] = useState<"scheduled" | "urgent">("scheduled");
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
        priority,
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
          <option value="patient">Patient</option>
          <option value="equipment">Equipment</option>
        </select>
        {kind === "patient" ? (
          <select value={needs} onChange={(e) => setNeeds(e.target.value as typeof needs)}>
            <option value="seated">seated</option>
            <option value="wheelchair">wheelchair</option>
            <option value="stretcher">stretcher</option>
          </select>
        ) : (
          <input placeholder="cargo, e.g. ventilator" value={label} onChange={(e) => setLabel(e.target.value)} />
        )}
        <select value={priority} onChange={(e) => setPriority(e.target.value as typeof priority)}>
          <option value="scheduled">scheduled</option>
          <option value="urgent">urgent</option>
        </select>
      </div>
      <div className="row">
        <select value={pickup} onChange={(e) => setPickup(e.target.value)} title="From">
          {places.map((p) => (
            <option key={p.id} value={p.id}>
              From: {p.name}
            </option>
          ))}
        </select>
      </div>
      <div className="row">
        <select value={dropoff} onChange={(e) => setDropoff(e.target.value)} title="To">
          {places.map((p) => (
            <option key={p.id} value={p.id}>
              To: {p.name}
            </option>
          ))}
        </select>
      </div>
      <div className="row booking-times">
        <label>
          ready in
          <input type="number" min={0} max={1440} value={readyIn} onChange={(e) => setReadyIn(Number(e.target.value))} /> min
        </label>
        <label>
          due within
          <input type="number" min={1} max={2880} placeholder="auto" value={deadline} onChange={(e) => setDeadline(e.target.value)} /> min
        </label>
      </div>
      {kind === "patient" && (
        <input placeholder="patient label (optional, pseudonymous)" value={label} onChange={(e) => setLabel(e.target.value)} />
      )}
      <button className="primary" disabled={busy || !pickup || !dropoff || pickup === dropoff} onClick={book}>
        {busy ? "Placing…" : "Book & place in plan"}
      </button>
      {result && <div className={`message ${result.ok ? "ok" : "error"}`}>{result.text}</div>}
    </div>
  );
}
