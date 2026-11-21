import { useEffect, useRef, useState } from "react";
import type { Place, Trip, Vehicle, WorldSnapshot } from "./api";
import { Crosshair, ExternalLink, IdCard, Smartphone, Tablet, Timer, TriangleAlert, Wrench, X } from "lucide-react";
import { fmtTime, humanize } from "./format";
import { VehicleTypeIcon } from "./icons";

type Send = (event: Record<string, unknown>) => Promise<void>;


/** Short place names for the chips ("UKC Ljubljana" -> "UKC", "Health centre Šiška" -> "ZD Šiška"). */
function shortPlace(p: Place | undefined): string {
  if (!p) return "?";
  return p.name
    .replace(/^UKC Ljubljana$/, "UKC")
    .replace(/^Oncology Institute Ljubljana$/, "Oncology")
    .replace(/^Dialysis centre.*$/, "Dialysis")
    .replace(/^General Hospital (\S+).*$/, "SB $1")
    .replace(/^Health centre (Ljubljana )?/, "ZD ")
    .replace(/^Ambulance base /, "Base ")
    .replace(/^Breakdown site of (.*)$/, "breakdown site")
    .replace(/^Call location$/, "call location");
}

const what = (t: Trip) => (t.kind === "equipment" ? (t.cargo ?? "equipment") : `${t.patient ?? t.label} (${t.needs})`);

interface Summary {
  tone: "idle" | "moving" | "loaded" | "returning" | "held" | "down" | "grounded";
  status: string; // one short word: pickup, patient, cargo, loading, return, idle, down, fog, held
  text: string; // where and why, short
  warnings: string[];
}

/** One vehicle in a few words: what it is doing, where, and why. */
function summarize(v: Vehicle, state: WorldSnapshot, places: Map<string, Place>, trips: Map<string, Trip>): Summary {
  const trip = v.current_trip_id ? trips.get(v.current_trip_id) : undefined;
  const own = state.trips.filter((t) => t.vehicle_id === v.id && t.status !== "completed" && t.status !== "cancelled");
  const late = own.filter((t) => (t.delay_min ?? 0) >= 5);
  const warnings: string[] = [];
  if (late.length) warnings.push(`${late.length} late trip${late.length > 1 ? "s" : ""} (up to +${Math.round(Math.max(...late.map((t) => t.delay_min ?? 0)))} min)`);
  if (state.alerts.some((a) => a.kind === "low_fuel" && a.vehicle_id === v.id)) warnings.push(`low fuel (${Math.round(v.fuel_pct)}%)`);
  const prio = (t: Trip) => (t.priority === "scheduled" ? "" : `${t.priority} `);

  if (v.status === "out_of_service") {
    // A load left inside: the trip now starts at this vehicle's breakdown site
    const stranded = state.trips.find(
      (t) =>
        t.status !== "completed" &&
        t.status !== "onboard" &&
        places.get(t.pickup_id)?.name === `Breakdown site of ${v.name}`,
    );
    warnings.unshift("out of service");
    return {
      tone: "down",
      status: "down",
      text: stranded ? `${stranded.kind === "equipment" ? stranded.cargo : `patient ${stranded.patient}`} on board · ${stranded.id}` : "out of service",
      warnings,
    };
  }
  const base = places.get(v.base_id);
  const groundedUntil = v.grounded_until ? fmtTime(v.grounded_until) : null;
  const held = v.busy_until && v.status !== "loading" && !(v.status === "returning" && !v.current_trip_id) ? fmtTime(v.busy_until) : null;

  let s: Summary;
  if (v.status === "to_pickup" && trip) {
    s = { tone: "moving", status: "pickup", text: `→ ${shortPlace(places.get(trip.pickup_id))} · ${prio(trip)}${trip.id} ${what(trip)}`, warnings };
  } else if (v.status === "loading" && trip) {
    s = { tone: "loaded", status: "loading", text: `${what(trip)} at ${shortPlace(places.get(trip.pickup_id))} · ${trip.id}`, warnings };
  } else if (v.status === "with_patient" && trip) {
    s = {
      tone: "loaded",
      status: trip.kind === "equipment" ? "cargo" : "patient",
      text: `→ ${shortPlace(places.get(trip.dropoff_id))} · ${prio(trip)}${trip.id} ${what(trip)}`,
      warnings,
    };
  } else if (v.status === "to_pickup" && v.queue.length) {
    // just re-planned (e.g. diverted): the simulator picks the next trip on its next tick
    s = { tone: "moving", status: "pickup", text: `→ next ${v.queue[0]}`, warnings };
  } else if (v.status === "returning" && v.queue.length) {
    // Just delivered (unloading) with the next job queued: it goes there, not back to base
    const next = trips.get(v.queue[0]);
    s = {
      tone: v.busy_until ? "loaded" : "moving",
      status: v.busy_until ? "unloading" : "pickup",
      text: next ? `next → ${shortPlace(places.get(next.pickup_id))} · ${prio(next)}${next.id}` : `next ${v.queue[0]}`,
      warnings,
    };
  } else if (v.status === "returning") {
    s = { tone: "returning", status: "return", text: `→ ${shortPlace(base)}`, warnings };
  } else {
    const atBase = base && Math.abs(base.lat - v.lat) < 0.0005 && Math.abs(base.lon - v.lon) < 0.0005;
    s = {
      tone: "idle",
      status: "idle",
      text: v.queue.length ? `next ${v.queue[0]}` : atBase ? `at ${shortPlace(base)}` : "waiting",
      warnings,
    };
  }
  if (groundedUntil) {
    s = { ...s, tone: "grounded", status: "fog", text: `grounded until ${groundedUntil}${s.tone === "idle" ? "" : ` · ${s.text}`}` };
  } else if (held) {
    s = { ...s, tone: "held", status: "held", text: `until ${held} · ${s.text}` };
  }
  return s;
}

export function VehicleStrip({
  state,
  selectedId,
  onSelect,
  onCenter,
  onOpenCard,
  send,
  busy,
}: {
  state: WorldSnapshot;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCenter: (id: string) => void;
  onOpenCard: (id: string) => void;
  send: Send;
  busy: boolean;
}) {
  const [open, setOpen] = useState<{ id: string; left: number } | null>(null);
  const strip = useRef<HTMLDivElement>(null);
  const places = new Map(state.places.map((p) => [p.id, p]));
  const trips = new Map(state.trips.map((t) => [t.id, t]));

  // Deselecting elsewhere (Esc, map click, card close) also closes the drop-down
  useEffect(() => {
    if (open && selectedId !== open.id) setOpen(null);
  }, [selectedId, open]);

  const toggle = (id: string, el: HTMLElement) => {
    if (open?.id === id) {
      setOpen(null);
      return;
    }
    const wrap = strip.current?.parentElement?.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    // Keep clear of the map's zoom buttons (top-left) and layer switcher (top-right): ~52 px each side
    const width = Math.min(340, (wrap?.width ?? 400) - 104);
    const left = Math.max(52, Math.min(r.left - (wrap?.left ?? 0), (wrap?.width ?? 400) - width - 56));
    onSelect(id);
    setOpen({ id, left });
  };

  const v = open ? state.vehicles.find((x) => x.id === open.id) : undefined;
  return (
    <>
      <div className="vstrip" ref={strip} onScroll={() => setOpen(null)} role="toolbar" aria-label="Vehicles">
        {state.vehicles.map((veh) => {
          const s = summarize(veh, state, places, trips);
          const title = `${veh.name} · ${s.status} · ${s.text}${s.warnings.length ? ` · warning: ${s.warnings.join(", ")}` : ""}`;
          return (
            <button
              key={veh.id}
              className={`vchip tone-${s.tone}${veh.id === selectedId ? " selected" : ""}${open?.id === veh.id ? " open" : ""}`}
              title={title}
              aria-expanded={open?.id === veh.id}
              onClick={(e) => toggle(veh.id, e.currentTarget)}
            >
              <span className="vchip-top">
                <span className="vchip-icon">
                  <VehicleTypeIcon type={veh.type} />
                </span>
                <strong>{veh.id}</strong>
                <span className="vchip-status">{s.status}</span>
                {s.warnings.length > 0 && (
                  <span className={`vchip-warn${s.tone === "down" ? " bad" : ""}`} aria-label="Warning">
                    <TriangleAlert />
                  </span>
                )}
              </span>
              <span className="vchip-text">{s.text}</span>
            </button>
          );
        })}
      </div>
      {open && v && (
        <VehiclePopover
          v={v}
          s={summarize(v, state, places, trips)}
          state={state}
          places={places}
          trips={trips}
          left={open.left}
          busy={busy}
          send={send}
          onClose={() => setOpen(null)}
          onCenter={() => onCenter(v.id)}
          onOpenCard={() => {
            setOpen(null);
            onOpenCard(v.id);
          }}
        />
      )}
    </>
  );
}

function VehiclePopover({
  v,
  s,
  state,
  places,
  trips,
  left,
  busy,
  send,
  onClose,
  onCenter,
  onOpenCard,
}: {
  v: Vehicle;
  s: Summary;
  state: WorldSnapshot;
  places: Map<string, Place>;
  trips: Map<string, Trip>;
  left: number;
  busy: boolean;
  send: Send;
  onClose: () => void;
  onCenter: () => void;
  onOpenCard: () => void;
}) {
  const trip = v.current_trip_id ? trips.get(v.current_trip_id) : undefined;
  const next = v.queue.map((id) => trips.get(id)).filter((t): t is Trip => Boolean(t));
  const down = v.status === "out_of_service";
  const name = (id: string) => places.get(id)?.name ?? id;
  return (
    <div className="vpop" style={{ left }} role="dialog" aria-label={`${v.name} details`}>
      <div className="vpop-head">
        <span className="vchip-icon">
          <VehicleTypeIcon type={v.type} />
        </span>
        <strong>
          {v.id} · {v.name}
        </strong>
        <button className="link vc-close" onClick={onClose} aria-label="Close">
          <X />
        </button>
      </div>
      <div className={`vpop-status tone-${s.tone}`}>
        {humanize(v.status)}
        {v.grounded_until ? ` · grounded by fog until ${fmtTime(v.grounded_until)}` : ""}
        {v.busy_until && v.status !== "loading" ? ` · held until ${fmtTime(v.busy_until)}` : ""} · fuel {Math.round(v.fuel_pct)}%{v.crew.length ? ` · crew of ${v.crew.length}` : ""}
      </div>
      {trip ? (
        <div className="vpop-trip">
          <div>
            <strong>{trip.id}</strong> {trip.label} <span className={`prio prio-${trip.priority}`}>{trip.priority}</span>
          </div>
          <div className="muted">
            {name(trip.pickup_id)} → {name(trip.dropoff_id)}
          </div>
          <div className="muted">
            {trip.status === "onboard" ? "on board" : `pickup ${fmtTime(trip.eta_pickup)}`} · drop-off {fmtTime(trip.eta_dropoff)}
            {(trip.delay_min ?? 0) >= 5 && <span className="late"> · +{Math.round(trip.delay_min ?? 0)} min late</span>}
          </div>
        </div>
      ) : (
        <div className="muted">{down ? `Out of service${s.text !== "out of service" ? `: ${s.text}` : ""}` : "No current trip"}</div>
      )}
      {next.length > 0 && (
        <div className="muted small">
          Then {next.length} more: {next.slice(0, 3).map((t) => t.id).join(", ")}
          {next.length > 3 ? "…" : ""}
        </div>
      )}
      {s.warnings.length > 0 && (
        <div className="vpop-warn">
          <TriangleAlert /> <span>{s.warnings.join(" · ")}</span>
        </div>
      )}
      <div className="vpop-actions">
        <button onClick={onCenter}>
          <Crosshair /> Centre
        </button>
        <button onClick={onOpenCard}>
          <IdCard /> Vehicle card
        </button>
        <button disabled={busy || down} onClick={() => send({ type: "delay", vehicle_id: v.id, minutes: 10, note: "reported from vehicle strip" })}>
          <Timer /> +10 min
        </button>
        <button disabled={busy || down} onClick={() => send({ type: "breakdown", vehicle_id: v.id, note: "reported from vehicle strip" })}>
          <Wrench /> Breakdown
        </button>
        <a className="button-link" href={`/crew/${encodeURIComponent(v.id)}?world=${state.world}`} target="_blank" rel="noopener">
          <Smartphone /> Crew view <ExternalLink />
        </a>
        <a className="button-link" href={`/vehicle/${encodeURIComponent(v.id)}?world=${state.world}`} target="_blank" rel="noopener">
          <Tablet /> Tablet view <ExternalLink />
        </a>
      </div>
    </div>
  );
}
