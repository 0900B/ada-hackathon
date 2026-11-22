import { useEffect, useRef, useState } from "react";
import type { Place, Trip, Vehicle, WorldSnapshot } from "./api";
import { Crosshair, ExternalLink, IdCard, Smartphone, Tablet, Timer, TriangleAlert, Wrench, X } from "lucide-react";
import { fmtTime, nightText, vehicleStatusText } from "./format";
import { VehicleTypeIcon } from "./icons";
import { conditionText, LEVEL_LABEL, levelOf } from "./severity";
import { ResponseLine, SeverityBadge } from "./SeverityBadge";
import { doctorJob } from "./doctor";
import { DoctorTag, OriginTag } from "./DoctorTag";
import { RespondingTo } from "./RespondingTo";
import { UnitReason } from "./UnitReason";
import { tOr, useT, t as tx } from "./i18n";

type Send = (event: Record<string, unknown>) => Promise<void>;


/** Short place names for the chips ("UKC Ljubljana" -> "UKC", "Health centre Šiška" -> "ZD Šiška"). */
function shortPlace(p: Place | undefined): string {
  if (!p) return "?";
  return p.name
    .replace(/^UKC Ljubljana$/, "UKC")
    .replace(/^Oncology Institute Ljubljana$/, tx("ops.place.oncology"))
    .replace(/^Dialysis centre.*$/, tx("ops.place.dialysis"))
    .replace(/^General Hospital (\S+).*$/, "SB $1")
    .replace(/^Health centre (Ljubljana )?/, "ZD ")
    .replace(/^Ambulance base (.*)$/, (_m, name: string) => tx("ops.place.base", { name }))
    .replace(/^Breakdown site of (.*)$/, tx("ops.place.breakdownSite"))
    .replace(/^Call location$/, tx("ops.place.callLocation"));
}

/** A patient's transport need ("stretcher" / "nosila"); unknown codes as sent. */
const needsLabel = (needs: string) => tOr(`ops.needs.${needs}`, needs);

const what = (t: Trip) => (t.kind === "equipment" ? (t.cargo ?? tx("ops.equipment")) : `${t.patient ?? t.label} (${needsLabel(t.needs)})`);

interface Summary {
  tone: "idle" | "moving" | "loaded" | "returning" | "held" | "down" | "grounded";
  status: string; // one short word: pickup, patient, cargo, loading, return, idle, down, fog, held
  text: string; // where and why, short
  warnings: string[];
  job?: Trip; // the call it is serving (or goes to next): its severity shows in the chip
}

/** One vehicle in a few words: what it is doing, where, and why. */
function summarize(v: Vehicle, state: WorldSnapshot, places: Map<string, Place>, trips: Map<string, Trip>): Summary {
  const trip = v.current_trip_id ? trips.get(v.current_trip_id) : undefined;
  const own = state.trips.filter((t) => t.vehicle_id === v.id && t.status !== "completed" && t.status !== "cancelled");
  const late = own.filter((t) => (t.delay_min ?? 0) >= 5);
  const warnings: string[] = [];
  if (late.length) warnings.push(tx("ops.warnLate", { count: late.length, max: Math.round(Math.max(...late.map((t) => t.delay_min ?? 0))) }));
  if (state.alerts.some((a) => a.kind === "low_fuel" && a.vehicle_id === v.id)) warnings.push(tx("ops.warnFuel", { pct: Math.round(v.fuel_pct) }));

  if (v.status === "out_of_service") {
    // A load left inside: the trip now starts at this vehicle's breakdown site
    const stranded = state.trips.find(
      (t) =>
        t.status !== "completed" &&
        t.status !== "onboard" &&
        places.get(t.pickup_id)?.name === `Breakdown site of ${v.name}`,
    );
    warnings.unshift(tx("ops.outOfService"));
    return {
      tone: "down",
      status: tx("ops.st.down"),
      text: stranded
        ? tx("ops.strandedOnBoard", {
            what: stranded.kind === "equipment" ? (stranded.cargo ?? tx("ops.equipment")) : tx("ops.patientNamed", { name: stranded.patient }),
            id: stranded.id,
          })
        : tx("ops.outOfService"),
      warnings,
    };
  }
  const base = places.get(v.base_id);
  const groundedUntil = v.grounded_until ? fmtTime(v.grounded_until) : null;
  const busyAt = v.busy_until && v.status !== "loading" && !(v.status === "returning" && !v.current_trip_id) ? fmtTime(v.busy_until) : null;
  // A normal turnout (crew to the vehicle) is shown neutrally; anything else (a delay) as held
  const turnoutAt = busyAt && v.busy_reason === "turnout" ? busyAt : null;
  const held = turnoutAt ? null : busyAt;

  let s: Summary;
  if (v.type === "doctor") {
    // A doctor car never carries the patient: it joins the ambulance's crew and escorts it
    const unit = trip?.vehicle_id ?? tx("dr.theAmbulance");
    s =
      v.status === "to_pickup" && trip
        ? { tone: "moving", status: tx("ops.st.toScene"), text: tx("ops.drForTrip", { place: shortPlace(places.get(trip.pickup_id)), id: trip.id }), warnings, job: trip }
        : v.status === "loading" && trip
          ? { tone: "loaded", status: tx("ops.st.onScene"), text: tx("ops.onSceneWith", { unit, id: trip.id }), warnings, job: trip }
          : v.status === "with_patient" && trip
            ? { tone: "loaded", status: tx("ops.st.escort"), text: tx("ops.escortingTo", { place: shortPlace(places.get(trip.dropoff_id)), id: trip.id }), warnings, job: trip }
            : v.status === "returning"
              ? { tone: "returning", status: tx("ops.st.return"), text: `→ ${shortPlace(base)}`, warnings }
              : { tone: "idle", status: tx("ops.st.idle"), text: base ? tx("ops.atPlace", { place: shortPlace(base) }) : tx("ops.available"), warnings };
  } else if (v.status === "to_pickup" && trip) {
    s = { tone: "moving", status: tx("ops.st.pickup"), text: `→ ${shortPlace(places.get(trip.pickup_id))} · ${trip.id} ${what(trip)}`, warnings, job: trip };
  } else if (v.status === "loading" && trip) {
    s = { tone: "loaded", status: tx("ops.st.loading"), text: tx("ops.loadingAt", { what: what(trip), place: shortPlace(places.get(trip.pickup_id)), id: trip.id }), warnings, job: trip };
  } else if (v.status === "with_patient" && trip) {
    s = {
      tone: "loaded",
      status: tx(trip.kind === "equipment" ? "ops.st.cargo" : "ops.st.patient"),
      text: `→ ${shortPlace(places.get(trip.dropoff_id))} · ${trip.id} ${what(trip)}`,
      warnings,
      job: trip,
    };
  } else if (v.status === "to_pickup" && v.queue.length) {
    // just re-planned (e.g. diverted): the simulator picks the next trip on its next tick
    s = { tone: "moving", status: tx("ops.st.pickup"), text: tx("ops.toNext", { id: v.queue[0] }), warnings };
  } else if (v.status === "returning" && v.queue.length) {
    // Just delivered (unloading) with the next job queued: it goes there, not back to base
    const next = trips.get(v.queue[0]);
    s = {
      tone: v.busy_until ? "loaded" : "moving",
      status: tx(v.busy_until ? "ops.st.unloading" : "ops.st.pickup"),
      text: next ? tx("ops.nextTo", { place: shortPlace(places.get(next.pickup_id)), id: next.id }) : tx("ops.next", { id: v.queue[0] }),
      warnings,
      job: next,
    };
  } else if (v.status === "returning") {
    s = { tone: "returning", status: tx("ops.st.return"), text: `→ ${shortPlace(base)}`, warnings };
  } else {
    const atBase = base && Math.abs(base.lat - v.lat) < 0.0005 && Math.abs(base.lon - v.lon) < 0.0005;
    s = {
      tone: "idle",
      status: tx("ops.st.idle"),
      text: v.queue.length ? tx("ops.next", { id: v.queue[0] }) : atBase ? tx("ops.atPlace", { place: shortPlace(base) }) : tx("ops.waiting"),
      warnings,
    };
  }
  const night = nightText(v); // the helicopter flies by day only
  if (groundedUntil) {
    s = { ...s, tone: "grounded", status: tx("ops.st.fog"), text: `${tx("ops.groundedUntil", { time: groundedUntil })}${s.tone === "idle" ? "" : ` · ${s.text}`}` };
  } else if (night && s.tone === "idle") {
    s = { ...s, tone: "grounded", status: tx("heli.nightShort"), text: night };
  } else if (held) {
    s = { ...s, tone: "held", status: tx("ops.st.held"), text: tx("ops.heldUntil", { time: held, text: s.text }) };
  } else if (turnoutAt) {
    s = { ...s, status: tx("ops.st.turnout"), text: tx("ops.turnoutAt", { time: turnoutAt, text: s.text }) };
  }
  return s;
}

export function VehicleStrip({
  state,
  selectedId,
  onSelect,
  onCenter,
  onOpenCard,
  onOpenCall,
  onOverride,
  send,
  busy,
}: {
  state: WorldSnapshot;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCenter: (id: string) => void;
  onOpenCard: (id: string) => void;
  onOpenCall?: (tripId: string) => void;
  onOverride?: (tripId: string, vehicleId: string) => void;
  send: Send;
  busy: boolean;
}) {
  const t = useT();
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
      <div className="vstrip" ref={strip} onScroll={() => setOpen(null)} role="toolbar" aria-label={t("ops.stripAria")}>
        {state.vehicles.map((veh) => {
          const s = summarize(veh, state, places, trips);
          const level = s.job ? levelOf(s.job) : null;
          const cond = s.job ? conditionText(s.job) : null;
          const title = `${veh.name} · ${s.status} · ${s.text}${level ? ` · ${LEVEL_LABEL[level]}${cond ? `: ${cond}` : ""}` : ""}${
            s.warnings.length ? t("ops.chipWarning", { list: s.warnings.join(", ") }) : ""
          }`;
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
                  <span className={`vchip-warn${s.tone === "down" ? " bad" : ""}`} aria-label={t("ops.warningAria")}>
                    <TriangleAlert />
                  </span>
                )}
              </span>
              <span className="vchip-text">
                <OriginTag v={veh} />
                {s.job && level !== "routine" && <SeverityBadge trip={s.job} compact />}
                {s.text}
              </span>
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
          onOpenCall={
            onOpenCall &&
            ((tripId: string) => {
              setOpen(null);
              onOpenCall(tripId);
            })
          }
          onOverride={
            onOverride &&
            ((tripId: string, vehicleId: string) => {
              setOpen(null);
              onOverride(tripId, vehicleId);
            })
          }
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
  onOpenCall,
  onOverride,
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
  onOpenCall?: (tripId: string) => void;
  onOverride?: (tripId: string, vehicleId: string) => void;
}) {
  const t = useT();
  const trip = v.current_trip_id ? trips.get(v.current_trip_id) : undefined;
  const next = v.queue.map((id) => trips.get(id)).filter((t): t is Trip => Boolean(t));
  const down = v.status === "out_of_service";
  const name = (id: string) => places.get(id)?.name ?? id;
  return (
    <div className="vpop" style={{ left }} role="dialog" aria-label={t("ops.popAria", { name: v.name })}>
      <div className="vpop-head">
        <span className="vchip-icon">
          <VehicleTypeIcon type={v.type} />
        </span>
        <strong>
          {v.id} · {v.name}
        </strong>
        <OriginTag v={v} />
        <button className="link vc-close" onClick={onClose} aria-label={t("common.close")}>
          <X />
        </button>
      </div>
      <RespondingTo v={v} state={state} onOpenCall={onOpenCall} />
      <UnitReason v={v} state={state} onOverride={onOverride} />
      <div className={`vpop-status tone-${s.tone}`}>
        {vehicleStatusText(v, state.trips)}
        {v.grounded_until ? t("ops.popGrounded", { time: fmtTime(v.grounded_until) }) : nightText(v) ? ` · ${nightText(v)}` : ""}
        {v.busy_until && v.status !== "loading" ? t(v.busy_reason === "turnout" ? "ops.popTurnout" : "ops.popHeld", { time: fmtTime(v.busy_until) }) : ""}
        {t("ops.popFuel", { pct: Math.round(v.fuel_pct) })}
        {v.crew.length ? t("ops.popCrew", { n: v.crew.length }) : ""}
      </div>
      {trip ? (
        <div className="vpop-trip">
          {v.type === "doctor" && <div className="vpop-doctor">{doctorJob(v, trip, name)}</div>}
          <div>
            <strong>{trip.id}</strong> {trip.label}
          </div>
          <div className="sev-row">
            <SeverityBadge trip={trip} /> <DoctorTag trip={trip} vehicles={state.vehicles} now={state.sim_time} />
          </div>
          <div className="muted">
            {name(trip.pickup_id)} → {name(trip.dropoff_id)}
          </div>
          <div className="muted">
            {v.type === "doctor"
              ? `${t("ops.popDoctorAtScene", { time: fmtTime(trip.doctor_eta ?? null) })} · ${trip.vehicle_id ?? t("ops.popNoAmbulance")} ${
                  trip.status === "onboard" ? t("ops.popHasPatient") : t("ops.popAtTime", { time: fmtTime(trip.eta_pickup) })
                }`
              : `${trip.status === "onboard" ? t("ops.popOnBoard") : t("ops.popPickup", { time: fmtTime(trip.eta_pickup) })} · ${t("ops.popDropoff", {
                  time: fmtTime(trip.eta_dropoff),
                })}`}
            {(trip.delay_min ?? 0) >= 5 && <span className="late">{t("ops.popLate", { min: Math.round(trip.delay_min ?? 0) })}</span>}
          </div>
          <div className="small">
            <ResponseLine trip={trip} now={state.sim_time} />
          </div>
        </div>
      ) : (
        <div className="muted">
          {down ? `${t("ops.popOutOfService")}${s.text !== t("ops.outOfService") ? `: ${s.text}` : ""}` : t("ops.popNoTrip")}
        </div>
      )}
      {next.length > 0 && (
        <div className="muted small">
          {t("ops.popThen", { count: next.length, ids: next.slice(0, 3).map((x) => x.id).join(", ") })}
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
          <Crosshair /> {t("ops.centre")}
        </button>
        <button onClick={onOpenCard}>
          <IdCard /> {t("ops.vehicleCard")}
        </button>
        <button disabled={busy || down} onClick={() => send({ type: "delay", vehicle_id: v.id, minutes: 10, note: "reported from vehicle strip" })}>
          <Timer /> +10 min
        </button>
        <button disabled={busy || down} onClick={() => send({ type: "breakdown", vehicle_id: v.id, note: "reported from vehicle strip" })}>
          <Wrench /> {t("ops.breakdown")}
        </button>
        <a className="button-link" href={`/crew/${encodeURIComponent(v.id)}?world=${state.world}`} target="_blank" rel="noopener">
          <Smartphone /> {t("ops.crewView")} <ExternalLink />
        </a>
        <a className="button-link" href={`/vehicle/${encodeURIComponent(v.id)}?world=${state.world}`} target="_blank" rel="noopener">
          <Tablet /> {t("ops.tabletView")} <ExternalLink />
        </a>
      </div>
    </div>
  );
}
