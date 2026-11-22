import { useRef, useState } from "react";
import {
  idSeq,
  postEvent,
  sendFieldMessage,
  type MessageResult,
  type Trip,
  type Vehicle,
  type World,
  type WorldSnapshot,
} from "../api";
import { CircleAlert, Construction, Siren, Timer, Wrench, type LucideIcon } from "lucide-react";
import { LEVEL_PRIORITY, levelOf, levelUp, severitySupported } from "../severity";

/**
 * Everything the crew says or taps is sent as a field message from this vehicle; the backend
 * turns it into events and starts an AI replan that the dispatcher sees on the dashboard.
 */

export const QUICK: { key: string; icon: LucideIcon; sl: string; en: string }[] = [
  { key: "1", icon: Wrench, sl: "Vozilo je obstalo.", en: "Vehicle broke down" },
  { key: "2", icon: Timer, sl: "Zamujamo 10 minut.", en: "10 min late" },
  { key: "3", icon: Siren, sl: "Stanje pacienta se je poslabšalo, potrebujemo nujni prevoz.", en: "Patient worse, urgent transport" },
  { key: "4", icon: Construction, sl: "Cesta pred nami je zaprta.", en: "Road ahead closed" },
  { key: "5", icon: CircleAlert, sl: "Potrebujemo pomoč na terenu.", en: "Need help on scene" },
];

/** A point about `ahead` metres along the vehicle's current road path (else where it is). */
function pointAhead(v: Vehicle, ahead = 250): [number, number] {
  const line = v.path ?? [];
  let left = ahead;
  for (let i = 1; i < line.length; i++) {
    const [alat, alon] = line[i - 1];
    const [blat, blon] = line[i];
    const d = Math.hypot((blat - alat) * 111_320, (blon - alon) * 111_320 * Math.cos((alat * Math.PI) / 180));
    if (d >= left) return [alat + ((blat - alat) * left) / d, alon + ((blon - alon) * left) / d];
    left -= d;
  }
  return line.length ? line[line.length - 1] : [v.lat, v.lon];
}

/**
 * The same quick report as a plain event, for when the AI message parser is unavailable (no API key,
 * or the AI can't be reached): the crew can still reach dispatch. null = no direct equivalent.
 */
function directReport(key: string, v: Vehicle, trip: Trip | undefined, graded: boolean): Record<string, unknown> | null {
  const note = `reported by the crew of ${v.id}`;
  if (key === "1") return { type: "breakdown", vehicle_id: v.id, note };
  if (key === "2") return { type: "delay", vehicle_id: v.id, minutes: 10, note };
  if (key === "3" && trip && trip.kind === "patient") {
    // one severity level up (routine > urgent > serious > critical); older backends: urgent, then emergency
    const up = levelUp(levelOf(trip));
    if (graded && up) return { type: "priority_change", trip_id: trip.id, priority: LEVEL_PRIORITY[up], severity: up, note };
    if (!graded && trip.priority !== "emergency")
      return { type: "priority_change", trip_id: trip.id, priority: trip.priority === "scheduled" ? "urgent" : "emergency", note };
  }
  if (key === "4" && v.type !== "helicopter") {
    const [lat, lon] = pointAhead(v);
    return { type: "road_closure", lat, lon, radius_m: 150, description: `Road closed (${note})` };
  }
  return null;
}

export function useDispatch(state: WorldSnapshot, vehicle: Vehicle, world: World) {
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<string | null>(null);
  const [result, setResult] = useState<MessageResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [direct, setDirect] = useState<string | null>(null); // sent as a plain event (AI unavailable)
  const busyRef = useRef(false);
  const tripById = (id: string | null | undefined) => (id ? state.trips.find((t) => t.id === id) : undefined);
  const trip = tripById(vehicle.current_trip_id);

  const send = async (raw: string, quickKey?: string): Promise<boolean> => {
    const text = raw.trim();
    if (text.length < 2 || busyRef.current) return false;
    busyRef.current = true;
    setBusy(true);
    setSent(text);
    setError(null);
    setResult(null);
    setDirect(null);
    try {
      setResult(await sendFieldMessage(world, text, vehicle.id));
      navigator.vibrate?.(40);
      return true;
    } catch (e) {
      const fallback = quickKey ? directReport(quickKey, vehicle, trip, severitySupported(state.trips)) : null;
      if (fallback) {
        try {
          const rec = await postEvent(world, fallback);
          setDirect(rec.summary);
          navigator.vibrate?.(40);
          return true;
        } catch (e2) {
          setError(e2 instanceof Error ? e2.message : String(e2));
          return false;
        }
      }
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  // The analysis that answers this message: the one it started, or (auto-analysis off) the first
  // one the dispatcher starts after it
  const sentSeq = Math.max(-1, ...(result?.applied ?? []).map((a) => idSeq(a.id)));
  const run = result?.run_id
    ? state.agent.runs.find((r) => r.id === result.run_id)
    : result?.applied.length
      ? [...state.agent.runs].reverse().find((r) => idSeq(r.id) > sentSeq)
      : undefined;

  return { busy, sent, result, error, direct, run, send };
}
