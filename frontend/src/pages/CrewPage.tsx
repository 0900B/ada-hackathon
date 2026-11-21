import { useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import {
  API_URL,
  idSeq,
  sendFieldMessage,
  useWorldState,
  type AgentRun,
  type MessageResult,
  type Trip,
  type Vehicle,
  type World,
  type WorldSnapshot,
} from "../api";
import {
  ArrowRight,
  Check,
  CircleAlert,
  CircleHelp,
  Construction,
  Mic,
  Radio,
  Send,
  Siren,
  Timer,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { fmtTime, humanize, vehicleStatusText } from "../format";
import { Callsign } from "../icons";
import { useHotkeys } from "../hotkeys";
import { SPEECH_LANGS, speechSecureContext, usePushToTalk, useSpeechInput } from "../voice";
import "../voice.css";

/**
 * Crew view for one vehicle, made for a phone: /crew/:vehicleId?world=sim|live (default sim).
 * Everything the crew says or taps is sent as a field message from this vehicle; the backend
 * turns it into events and starts an AI replan that the dispatcher sees on the dashboard.
 */

const QUICK: { key: string; icon: LucideIcon; sl: string; en: string }[] = [
  { key: "1", icon: Wrench, sl: "Vozilo je obstalo.", en: "Vehicle broke down" },
  { key: "2", icon: Timer, sl: "Zamujamo 10 minut.", en: "10 min late" },
  { key: "3", icon: Siren, sl: "Stanje pacienta se je poslabšalo, potrebujemo nujni prevoz.", en: "Patient worse, urgent transport" },
  { key: "4", icon: Construction, sl: "Cesta pred nami je zaprta.", en: "Road ahead closed" },
  { key: "5", icon: CircleAlert, sl: "Potrebujemo pomoč na terenu.", en: "Need help on scene" },
];

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
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<string | null>(null);
  const [result, setResult] = useState<MessageResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busyRef = useRef(false);

  const send = async (raw: string): Promise<boolean> => {
    const text = raw.trim();
    if (text.length < 2 || busyRef.current) return false;
    busyRef.current = true;
    setBusy(true);
    setSent(text);
    setError(null);
    setResult(null);
    try {
      setResult(await sendFieldMessage(world, text, vehicle.id));
      navigator.vibrate?.(40);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  const speech = useSpeechInput({
    onFinal: (heard) => {
      if (busyRef.current) setDraft(heard); // a message is still in flight: keep it for manual send
      else void send(heard);
    },
  });
  const ptt = usePushToTalk(speech);

  useHotkeys({
    ...Object.fromEntries(QUICK.map((q) => [q.key, () => void send(q.sl)])),
    m: () => speech.toggle(),
  });

  const placeName = (id: string) => state.places.find((p) => p.id === id)?.name ?? id;
  const tripById = (id: string | null | undefined) => (id ? state.trips.find((t) => t.id === id) : undefined);
  const trip = tripById(vehicle.current_trip_id);
  const queued = tripById(vehicle.queue[0]);
  const stop = nextStop(vehicle, trip, queued, placeName);
  // The analysis that answers this message: the one it started, or (auto-analysis off) the first
  // one the dispatcher starts after it
  const sentSeq = Math.max(-1, ...(result?.applied ?? []).map((a) => idSeq(a.id)));
  const run = result?.run_id
    ? state.agent.runs.find((r) => r.id === result.run_id)
    : result?.applied.length
      ? [...state.agent.runs].reverse().find((r) => idSeq(r.id) > sentSeq)
      : undefined;
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
              <span className={`prio prio-${trip.priority}`}>{trip.priority}</span>{" "}
              <span className="muted">
                {trip.kind === "equipment" ? "equipment" : trip.needs} · {trip.id}
              </span>
            </div>
            <div className="crew-route">
              {placeName(trip.pickup_id)} → {placeName(trip.dropoff_id)}
            </div>
            <div className={`crew-eta${late ? " late" : ""}`}>
              {trip.status === "onboard" ? "Drop-off" : "Pickup"} ETA{" "}
              <strong>{fmtTime(trip.status === "onboard" ? trip.eta_dropoff : trip.eta_pickup)}</strong>
              {trip.status !== "onboard" && <> · drop-off {fmtTime(trip.eta_dropoff)}</>}
              {late && <> · +{Math.round(trip.delay_min ?? 0)} min late</>}
            </div>
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
          </div>
        )}
      </header>

      <section className="crew-talk">
        {speech.supported ? (
          <>
            <button
              type="button"
              className={`ptt${speech.listening ? " listening" : ""}`}
              disabled={busy && !speech.listening}
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

      <form
        className="crew-form"
        onSubmit={(e) => {
          e.preventDefault();
          void send(draft).then((ok) => ok && setDraft(""));
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Sporočilo dispečerju…"
          enterKeyHint="send"
          aria-label="Message to the dispatcher"
        />
        <button type="submit" className="primary" disabled={busy || draft.trim().length < 2}>
          <Send /> Send
        </button>
      </form>

      {(busy || result || error) && (
        <section className="crew-card crew-response" aria-live="polite">
          {sent && <div className="crew-sent">“{sent}”</div>}
          {busy && (
            <div>
              <span className="spinner" /> AI is interpreting the message…
            </div>
          )}
          {error && <div className="message error">Not delivered: {error}</div>}
          {result && <MessageOutcome result={result} run={run} />}
        </section>
      )}

      <section className="crew-quick" aria-label="Quick status">
        {QUICK.map((q) => (
          <button key={q.key} type="button" disabled={busy} onClick={() => void send(q.sl)} title={`${q.sl} (key ${q.key})`}>
            <span className="q-icon">
              <q.icon />
            </span>
            <span className="q-text">
              <span>{q.sl}</span>
              <span className="muted">{q.en}</span>
            </span>
            <kbd>{q.key}</kbd>
          </button>
        ))}
      </section>

      <p className="crew-foot muted">
        <Link to={`/crew?world=${world}`}>Switch vehicle</Link> · <Link to={`/${world}`}>Dispatcher dashboard</Link>
      </p>
    </main>
  );
}

const RUN_STATUS: Record<AgentRun["status"], string> = {
  running: "AI is replanning…",
  done: "New plan proposed: waiting for the dispatcher's approval",
  approved: "Dispatcher approved the new plan",
  rejected: "Dispatcher rejected the proposal",
  superseded: "Replaced by a newer analysis",
  error: "AI analysis failed; the dispatcher decides manually",
};

function MessageOutcome({ result, run }: { result: MessageResult; run: AgentRun | undefined }) {
  return (
    <>
      <div>
        <span className="lang-tag">SL</span>
        {result.understood_sl}
      </div>
      <div className="muted">
        <span className="lang-tag">EN</span>
        {result.understood_en}
      </div>
      {result.needs_clarification && (
        <div className="warn-box">
          <CircleHelp /> <span>{result.needs_clarification}</span>
        </div>
      )}
      {result.applied.map((a) => (
        <div key={a.id} className="applied">
          <Check /> {a.summary}
        </div>
      ))}
      {result.error && <div className="message error">{result.error}</div>}
      {result.run_id || run ? (
        <div className="crew-notified">
          <Radio /> Dispatcher notified{result.run_id || run?.status === "running" ? ": AI is replanning" : ""}
          {run && (
            <div className={`crew-run run-${run.status}`}>
              {run.status === "running" && <span className="spinner" />} {RUN_STATUS[run.status]}
              {run.status === "approved" && run.decision?.title ? `: ${run.decision.title}` : ""}
            </div>
          )}
        </div>
      ) : result.applied.length > 0 ? (
        <div className="crew-notified">
          <Radio /> Dispatcher notified
        </div>
      ) : (
        !result.error && <div className="muted">Nothing changed in the plan.</div>
      )}
    </>
  );
}
