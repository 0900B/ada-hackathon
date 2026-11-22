import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import {
  API_URL,
  useWorldState,
  type Trip,
  type Vehicle,
  type World,
  type WorldSnapshot,
} from "../api";
import { ArrowRight, Mic } from "lucide-react";
import { fmtTime, humanize, vehicleStatusText } from "../format";
import { Callsign } from "../icons";
import { ResponseLine, SeverityBadge } from "../SeverityBadge";
import { doctorJobLine } from "../doctor";
import { DoctorTag } from "../DoctorTag";
import { useHotkeys } from "../hotkeys";
import { DispatchPanel } from "../crew/DispatchPanel";
import { QUICK, useDispatch } from "../crew/useDispatch";
import { SPEECH_LANGS, speechSecureContext, usePushToTalk, useSpeechInput } from "../voice";
import "../voice.css";

/**
 * Crew view for one vehicle, made for a phone: /crew/:vehicleId?world=sim|live (default sim).
 * Everything the crew says or taps is sent as a field message from this vehicle; the backend
 * turns it into events and starts an AI replan that the dispatcher sees on the dashboard.
 */

export function CrewPage() {
  const { vehicleId = "" } = useParams();
  const [params] = useSearchParams();
  const world: World = params.get("world") === "live" ? "live" : "sim";
  const { state, connected } = useWorldState(world);

  if (!state) {
    return (
      <main className="crew">
        <p className="crew-loading">Connecting to {API_URL} …</p>
      </main>
    );
  }
  const vehicle = state.vehicles.find((v) => v.id.toLowerCase() === vehicleId.toLowerCase());
  if (!vehicle) return <VehiclePicker state={state} world={world} missing={vehicleId} />;
  return <CrewConsole key={vehicle.id} state={state} vehicle={vehicle} world={world} connected={connected} />;
}

function VehiclePicker({ state, world, missing }: { state: WorldSnapshot; world: World; missing: string }) {
  const here = missing ? `/crew/${encodeURIComponent(missing)}` : "/crew";
  return (
    <main className="crew">
      <section className="crew-card">
        {missing ? (
          <h1 className="crew-title">Vehicle “{missing}” not found</h1>
        ) : (
          <h1 className="crew-title">Crew view</h1>
        )}
        <p className="muted">Choose your vehicle ({world === "sim" ? "simulation" : "live"}):</p>
      </section>
      <ul className="crew-pick">
        {state.vehicles.map((v) => (
          <li key={v.id}>
            <Link to={`/crew/${encodeURIComponent(v.id)}?world=${world}`}>
              <Callsign v={v} />
              <span className="crew-pick-name">{v.name}</span>
              <span className="muted">{humanize(v.status)}</span>
            </Link>
          </li>
        ))}
      </ul>
      <p className="crew-foot muted">
        World:{" "}
        <Link to={`${here}?world=sim`} className={world === "sim" ? "on" : ""}>
          simulation
        </Link>{" "}
        ·{" "}
        <Link to={`${here}?world=live`} className={world === "live" ? "on" : ""}>
          live
        </Link>
      </p>
    </main>
  );
}

/** Where the vehicle is heading next, from the current trip (or the first queued one). */
function nextStop(v: Vehicle, trip: Trip | undefined, queued: Trip | undefined, place: (id: string) => string) {
  if (trip) {
    return trip.status === "onboard"
      ? { label: `Drop-off: ${place(trip.dropoff_id)}`, eta: trip.eta_dropoff }
      : { label: `Pickup: ${place(trip.pickup_id)}`, eta: trip.eta_pickup };
  }
  if (queued) return { label: `Next trip ${queued.id}: pickup at ${place(queued.pickup_id)}`, eta: queued.eta_pickup };
  if (v.status === "returning") return { label: `Back to base: ${place(v.base_id)}`, eta: v.busy_until };
  return null;
}

function CrewConsole({
  state,
  vehicle,
  world,
  connected,
}: {
  state: WorldSnapshot;
  vehicle: Vehicle;
  world: World;
  connected: boolean;
}) {
  const [draft, setDraft] = useState("");
  const dispatch = useDispatch(state, vehicle, world);
  const tripById = (id: string | null | undefined) => (id ? state.trips.find((t) => t.id === id) : undefined);
  const trip = tripById(vehicle.current_trip_id);

  const speech = useSpeechInput({
    onFinal: (heard) => {
      if (dispatch.isBusy()) setDraft(heard); // a message is still in flight: keep it for manual send
      else void dispatch.send(heard);
    },
  });
  const ptt = usePushToTalk(speech);

  useHotkeys({
    ...Object.fromEntries(QUICK.map((q) => [q.key, () => void dispatch.send(q.sl, q.key)])),
    m: () => speech.toggle(),
  });

  const placeName = (id: string) => state.places.find((p) => p.id === id)?.name ?? id;
  const queued = tripById(vehicle.queue[0]);
  const stop = nextStop(vehicle, trip, queued, placeName);
  const late = (trip?.delay_min ?? 0) >= 5;

  return (
    <main className="crew">
      <header className="crew-card crew-head">
        <div className="crew-head-top">
          <h1 className="crew-title">
            <Callsign v={vehicle} /> {vehicle.name}
          </h1>
          <span className={`crew-world ${world}`}>{world === "sim" ? "SIM" : "LIVE"}</span>
        </div>
        <div className="crew-chips">
          <span className={`chip st-${vehicle.status}`}>{vehicleStatusText(vehicle, state.trips)}</span>
          <span className={`chip ${connected ? "ok" : "bad"}`}>
            <i className="dot" /> {connected ? "Online" : "Reconnecting"}
          </span>
          {vehicle.grounded_until && <span className="chip warn">Grounded by fog until {fmtTime(vehicle.grounded_until)}</span>}
        </div>

        {trip ? (
          <div className="crew-trip">
            <div className="crew-trip-who">
              <strong>{trip.kind === "equipment" ? (trip.cargo ?? "equipment") : trip.patient}</strong>{" "}
              <span className="muted">
                {trip.kind === "equipment" ? "equipment" : trip.needs} · {trip.id}
              </span>
            </div>
            {vehicle.type === "doctor" && <div className="crew-doctor">{doctorJobLine(vehicle, trip, placeName)}</div>}
            <div className="crew-sev">
              <SeverityBadge trip={trip} size="md" /> <DoctorTag trip={trip} vehicles={state.vehicles} now={state.sim_time} size="md" />
            </div>
            <div className="crew-route">
              {placeName(trip.pickup_id)} → {placeName(trip.dropoff_id)}
            </div>
            {vehicle.type === "doctor" ? (
              <div className="crew-eta">
                {vehicle.status === "to_pickup" ? (
                  <>
                    At the scene <strong>{fmtTime(trip.doctor_eta ?? null)}</strong> · {trip.vehicle_id ?? "no ambulance yet"}
                    {trip.vehicle_id && trip.status !== "onboard" && <> at {fmtTime(trip.eta_pickup)}</>}
                  </>
                ) : (
                  <>
                    Hospital <strong>{fmtTime(trip.eta_dropoff)}</strong> · with {trip.vehicle_id ?? "the ambulance"}
                  </>
                )}
              </div>
            ) : (
              <div className={`crew-eta${late ? " late" : ""}`}>
                {trip.status === "onboard" ? "Drop-off" : "Pickup"} ETA{" "}
                <strong>{fmtTime(trip.status === "onboard" ? trip.eta_dropoff : trip.eta_pickup)}</strong>
                {trip.status !== "onboard" && <> · drop-off {fmtTime(trip.eta_dropoff)}</>}
                {late && <> · +{Math.round(trip.delay_min ?? 0)} min late</>}
              </div>
            )}
            {trip.status !== "onboard" && vehicle.type !== "doctor" && (
              <div className="crew-resp">
                <ResponseLine trip={trip} now={state.sim_time} />
              </div>
            )}
          </div>
        ) : (
          <p className="muted crew-trip">No current trip.</p>
        )}
        {stop && (
          <div className="crew-next">
            <ArrowRight /> Next stop: <strong>{stop.label}</strong>
            {stop.eta && <> · {fmtTime(stop.eta)}</>}
            {vehicle.queue.length > (trip ? 0 : 1) && (
              <span className="muted"> · {vehicle.queue.length - (trip ? 0 : 1)} more queued</span>
            )}
            {!trip && queued && (
              <div className="crew-sev">
                <SeverityBadge trip={queued} size="md" />
              </div>
            )}
          </div>
        )}
      </header>

      <section className="crew-talk">
        {speech.supported ? (
          <>
            <button
              type="button"
              className={`ptt${speech.listening ? " listening" : ""}`}
              disabled={dispatch.busy && !speech.listening}
              aria-pressed={speech.listening}
              {...ptt}
            >
              <span className="ptt-icon">
                <Mic />
              </span>
              <span>{speech.listening ? "Listening… release to send" : "Hold to talk"}</span>
              <span className="ptt-sub">{speech.listening ? "or tap to stop" : "or tap once and speak"}</span>
            </button>
            <div className="crew-talk-bar">
              <span className="lang-toggle big" role="group" aria-label="Speech language">
                {SPEECH_LANGS.map((l) => (
                  <button
                    key={l.code}
                    type="button"
                    aria-pressed={speech.lang === l.code}
                    onClick={() => speech.setLang(l.code)}
                  >
                    {l.label}
                  </button>
                ))}
              </span>
              <span className="muted">Speaks: {speech.lang === "sl-SI" ? "slovenščina" : "English"}</span>
            </div>
            {!speechSecureContext() && <div className="warn-box">Voice input needs HTTPS (or localhost).</div>}
            {speech.listening && <div className="voice-interim big">{speech.interim || "Govorite… / Speak now…"}</div>}
            {speech.error && <div className="message error">{speech.error}</div>}
          </>
        ) : (
          <div className="warn-box">Voice input needs Chrome or Edge. Use the buttons or type below.</div>
        )}
      </section>

      <DispatchPanel dispatch={dispatch} draft={draft} setDraft={setDraft} />

      <p className="crew-foot muted">
        <Link to={`/crew?world=${world}`}>Switch vehicle</Link> · <Link to={`/${world}`}>Dispatcher dashboard</Link>
      </p>
    </main>
  );
}
