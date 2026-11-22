import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import {
  API_URL,
  useWorldState,
  type Vehicle,
  type World,
  type WorldSnapshot,
} from "../api";
import { Mic, NotebookPen, Radio } from "lucide-react";
import { fmtTime, humanize } from "../format";
import { Callsign } from "../icons";
import { SeverityBadge } from "../SeverityBadge";
import { DoctorTag } from "../DoctorTag";
import { useHotkeys } from "../hotkeys";
import { DispatchPanel } from "../crew/DispatchPanel";
import { EtaPanel } from "../crew/EtaPanel";
import { crewStage } from "../crew/crewLogic";
import { QUICK, useDispatch } from "../crew/useDispatch";
import { useWakeLock } from "../crew/useWakeLock";
import { SPEECH_LANGS, speechSecureContext, usePushToTalk, useSpeechInput } from "../voice";
import "../voice.css";
import "../crew/crew.css";

/**
 * Crew view for one vehicle: /crew/:vehicleId?world=sim|live (default sim). Made for the tablet
 * in the patient compartment (two columns from 900 px) and collapses to one column on a phone.
 * The ETA comes first; the dispatch panel sends field messages from this vehicle, which the
 * backend turns into events and an AI replan that the dispatcher sees on the dashboard.
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
  const trip = vehicle.current_trip_id ? state.trips.find((t) => t.id === vehicle.current_trip_id) : undefined;
  const stage = crewStage(vehicle, trip);
  useWakeLock();

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

  return (
    <main className={`crew pt pt-stage-${stage}`}>
      <header className="pt-head">
        <h1 className="pt-title">
          <Callsign v={vehicle} /> <span>{vehicle.name}</span>
        </h1>
        {trip && (
          <div className="pt-who">
            <strong>{trip.kind === "equipment" ? (trip.cargo ?? "equipment") : trip.patient}</strong>{" "}
            <span className="muted">
              {trip.kind === "equipment" ? "equipment" : trip.needs} · {trip.id}
            </span>
          </div>
        )}
        {trip && (
          <div className="pt-sev">
            <SeverityBadge trip={trip} size="md" /> <DoctorTag trip={trip} vehicles={state.vehicles} now={state.sim_time} size="md" />
          </div>
        )}
        <div className="pt-head-chips">
          {vehicle.grounded_until && <span className="chip warn">Grounded by fog until {fmtTime(vehicle.grounded_until)}</span>}
          <span className={`chip ${connected ? "ok" : "bad"}`}>
            <i className="dot" /> {connected ? "Online" : "Reconnecting"}
          </span>
        </div>
      </header>

      <div className="pt-grid">
        <EtaPanel state={state} vehicle={vehicle} trip={trip} stage={stage} />

        <section className="pt-log" aria-label="Clinical log">
          <h2 className="pt-section-title">
            <NotebookPen /> Log
          </h2>
          <p className="pt-log-empty">Log: next task</p>
        </section>

        <section className="pt-dispatch" aria-label="Dispatch">
          <h2 className="pt-section-title">
            <Radio /> Dispatch
          </h2>
          <div className="crew-talk">
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
                  <span>{speech.listening ? "Listening… release to send" : "Hold to talk to dispatch"}</span>
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
          </div>

          <DispatchPanel dispatch={dispatch} draft={draft} setDraft={setDraft} />
        </section>
      </div>

      <footer className="pt-foot">
        <Link to={`/crew?world=${world}`}>Switch vehicle</Link>
        <Link to={`/${world}`}>Dispatcher dashboard</Link>
        <span className={`crew-world ${world}`}>{world === "sim" ? "SIM" : "LIVE"}</span>
      </footer>
    </main>
  );
}
