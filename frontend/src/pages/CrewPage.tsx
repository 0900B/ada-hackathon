import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import {
  API_URL,
  useWorldState,
  type Vehicle,
  type World,
  type WorldSnapshot,
} from "../api";
import { Mic, NotebookPen, Pill, Plus, Radio, Zap } from "lucide-react";
import { fmtTime, nightText, vehicleStatusLabel } from "../format";
import { tOr, useT } from "../i18n";
import { LangToggle } from "../LangToggle";
import { AdminLock } from "../AdminLock";
import { Callsign } from "../icons";
import { SeverityBadge } from "../SeverityBadge";
import { levelOf } from "../severity";
import { DoctorTag } from "../DoctorTag";
import { useHotkeys } from "../hotkeys";
import { DispatchPanel } from "../crew/DispatchPanel";
import { EtaPanel } from "../crew/EtaPanel";
import { QUICK, useDispatch } from "../crew/useDispatch";
import { useWakeLock } from "../crew/useWakeLock";
import { useClinicalLog } from "../crew/useClinicalLog";
import { useVoiceChannels } from "../crew/useVoiceChannels";
import { Timeline } from "../crew/Timeline";
import { VitalsPanel } from "../crew/VitalsPanel";
import { DrugPad } from "../crew/DrugPad";
import { VitalsPad } from "../crew/VitalsPad";
import { EventPad } from "../crew/EventPad";
import { observedAt } from "../crew/padLogic";
import { TimersPanel } from "../crew/TimersPanel";
import { crewStage, erEcho } from "../crew/crewLogic";
import { SPEECH_LANGS, speechSecureContext } from "../voice";
import "../voice.css";
import "../crew/crew.css";

/**
 * Crew view for one vehicle: /crew/:vehicleId?world=sim|live (default sim). Made for the tablet
 * in the patient compartment (two columns from 900 px) and collapses to one column on a phone.
 * The ETA comes first; the dispatch panel sends field messages from this vehicle, which the
 * backend turns into events and an AI replan that the dispatcher sees on the dashboard.
 *
 * Two voice channels share one recognizer: "Hold to log" puts what was said on the clinical
 * timeline (kept on the tablet, never sent to the dispatcher), "Hold to talk to dispatch" and the
 * quick buttons send field messages exactly as before.
 *
 * Text comes from the i18n dictionaries (the field surface defaults to Slovenian): the keys of the
 * older phone view are "tab." and "crew." (locales/field.ts), the tablet's own are "pt."
 * (locales/crewtablet.ts).
 */

export function CrewPage() {
  const { vehicleId = "" } = useParams();
  const [params] = useSearchParams();
  const world: World = params.get("world") === "live" ? "live" : "sim";
  const { state, connected } = useWorldState(world);
  const t = useT();

  if (!state) {
    return (
      <main className="crew">
        <p className="crew-loading">{t("common.connecting", { url: API_URL })}</p>
      </main>
    );
  }
  const vehicle = state.vehicles.find((v) => v.id.toLowerCase() === vehicleId.toLowerCase());
  if (!vehicle) return <VehiclePicker state={state} world={world} missing={vehicleId} />;
  return <CrewConsole key={vehicle.id} state={state} vehicle={vehicle} world={world} connected={connected} />;
}

function VehiclePicker({ state, world, missing }: { state: WorldSnapshot; world: World; missing: string }) {
  const t = useT();
  const here = missing ? `/crew/${encodeURIComponent(missing)}` : "/crew";
  return (
    <main className="crew">
      <section className="crew-card">
        <div className="crew-head-top">
          {missing ? (
            <h1 className="crew-title">{t("tab.notFound", { id: missing })}</h1>
          ) : (
            <h1 className="crew-title">{t("crew.title")}</h1>
          )}
          <LangToggle className="crew-uilang" />
        </div>
        <p className="muted">{t("crew.choose", { world: t(world === "sim" ? "tab.worldSim" : "tab.worldLive") })}</p>
      </section>
      <ul className="crew-pick">
        {state.vehicles.map((v) => (
          <li key={v.id}>
            <Link to={`/crew/${encodeURIComponent(v.id)}?world=${world}`}>
              <Callsign v={v} />
              <span className="crew-pick-name">{v.name}</span>
              <span className="muted">{vehicleStatusLabel(v.status)}</span>
            </Link>
          </li>
        ))}
      </ul>
      <p className="crew-foot muted">
        {t("tab.worldLabel")}{" "}
        <Link to={`${here}?world=sim`} className={world === "sim" ? "on" : ""}>
          {t("tab.worldSim")}
        </Link>{" "}
        ·{" "}
        <Link to={`${here}?world=live`} className={world === "live" ? "on" : ""}>
          {t("tab.worldLive")}
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
  const t = useT();
  const [draft, setDraft] = useState("");
  const dispatch = useDispatch(state, vehicle, world);
  const trip = vehicle.current_trip_id ? state.trips.find((x) => x.id === vehicle.current_trip_id) : undefined;
  const stage = crewStage(vehicle, trip);
  const needsText = (needs: string) => tOr(`tab.needs.${needs}`, needs);
  useWakeLock();

  // Logging is on while a patient is on board (loading counts); doctor cars log too
  const logOn = stage === "with_patient" && !!trip;
  const log = useClinicalLog(world, trip?.kind === "patient" ? trip.id : null, vehicle.id, state.sim_time);
  const [note, setNote] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  // The open tap pad. Closed when logging stops (the trip ended or changed), so a pad never
  // saves into another patient's log.
  const [pad, setPad] = useState<"drug" | "vitals" | "event" | null>(null);
  useEffect(() => {
    if (!logOn) setPad(null);
  }, [logOn]);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const { speech, channel, lastChannel, logMic, dispatchMic, toggle } = useVoiceChannels({
    onLog: (heard) => {
      if (!logOn) return setNotice(t("pt.notLogged"));
      const r = log.addSpoken(heard);
      setNotice(r === "nothing_to_confirm" ? t("pt.nothingToConfirm") : r === "confirmed" ? t("pt.confirmedNote") : null);
    },
    onDispatch: (heard) => {
      if (dispatch.isBusy()) setDraft(heard); // a message is still in flight: keep it for manual send
      else void dispatch.send(heard);
    },
  });
  const logListening = channel === "log";
  const dispatchListening = channel === "dispatch";

  // No shortcuts while a pad is open: a keyboard digit must not send a quick report from behind it
  useHotkeys(
    pad
      ? {}
      : {
          ...Object.fromEntries(QUICK.map((q) => [q.key, () => void dispatch.send(q.sl, q.key)])),
          m: () => {
            if (logOn) toggle("log");
          },
        },
  );

  const addNote = () => {
    const text = note.trim();
    if (!text || !logOn) return;
    log.add("note", {}, { source: "crew_tap", verbatim: text });
    setNote("");
  };

  const night = nightText(vehicle);

  return (
    <main className={`crew pt pt-stage-${stage}`}>
      <header className="pt-head">
        <h1 className="pt-title">
          <Callsign v={vehicle} /> <span>{vehicle.name}</span>
        </h1>
        {trip && (
          <div className="pt-who">
            <strong>{trip.kind === "equipment" ? (trip.cargo ?? t("tab.equipment")) : trip.patient}</strong>{" "}
            <span className="muted">
              {trip.kind === "equipment" ? t("tab.equipment") : needsText(trip.needs)} · {trip.id}
            </span>
          </div>
        )}
        {trip && (
          <div className="pt-sev">
            <SeverityBadge trip={trip} size="md" /> <DoctorTag trip={trip} vehicles={state.vehicles} now={state.sim_time} size="md" />
          </div>
        )}
        {trip?.call && (
          <div className="crew-call pt-call">
            <strong>{trip.call.call_id}</strong>
            {trip.call.address && <> · {trip.call.address}</>}
            {trip.call.text_sl && <div className="crew-words">»{trip.call.text_sl}«</div>}
            {trip.call.text_en && trip.call.text_en !== trip.call.text_sl && <div className="muted small">{trip.call.text_en}</div>}
          </div>
        )}
        <div className="pt-head-chips">
          {vehicle.grounded_until && <span className="chip warn">{t("tab.grounded", { time: fmtTime(vehicle.grounded_until) })}</span>}
          {night && <span className="chip warn">{night}</span>}
          <span className={`chip ${connected ? "ok" : "bad"}`}>
            <i className="dot" /> {connected ? t("tab.online") : t("tab.reconnecting")}
          </span>
          <AdminLock variant="crew" />
        </div>
      </header>

      <div className="pt-grid">
        <EtaPanel state={state} vehicle={vehicle} trip={trip} stage={stage} />

        <section className="pt-log" aria-label={t("pt.logAria")}>
          <h2 className="pt-section-title">
            <NotebookPen /> {t("pt.log")}
            {log.pending > 0 && <span className="pt-pending">{t("pt.notSent", { count: log.pending })}</span>}
          </h2>
          {!logOn ? (
            <p className="pt-log-empty">{t("pt.noPatientBoard")}</p>
          ) : (
            <>
              <div className="pt-log-bar">
                {speech.supported ? (
                  <button
                    type="button"
                    className={`ptt pt-logbtn${logListening ? " listening" : ""}`}
                    disabled={dispatchListening}
                    aria-pressed={logListening}
                    {...logMic}
                  >
                    <span className="pt-logbtn-main">
                      <NotebookPen /> {logListening ? t("pt.logListening") : t("pt.logHold")}
                    </span>
                    <span className="ptt-sub">
                      {logListening ? t("pt.logSubListening") : t("pt.logSubIdle")} <kbd>M</kbd>
                    </span>
                  </button>
                ) : (
                  <div className="warn-box">{t("pt.logNeedsChrome")}</div>
                )}
                <form
                  className="pt-note-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    addNote();
                  }}
                >
                  <input
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder={t("pt.notePlaceholder")}
                    enterKeyHint="done"
                    aria-label={t("pt.noteAria")}
                  />
                  <button type="submit" disabled={!note.trim()}>
                    <Plus /> {t("pt.addNote")}
                  </button>
                </form>
              </div>
              {logListening && <div className="voice-interim big">{speech.interim || "Govorite… / Speak now…"}</div>}
              {lastChannel === "log" && speech.error && <div className="message error">{speech.error}</div>}
              {notice && (
                <div className="pt-notice" role="status">
                  {notice}
                </div>
              )}
              <Timeline entries={log.entries} nowIso={state.sim_time} onConfirm={log.confirm} onDiscard={log.discard} />
            </>
          )}
        </section>

        {logOn && trip && (
          <section className="pt-rec" aria-label={t("pt.vp.title")}>
            <VitalsPanel entries={log.entries} nowIso={state.sim_time} level={levelOf(trip)} onEnter={() => setPad("vitals")} />
            <TimersPanel
              entries={log.entries}
              nowIso={state.sim_time}
              echo={erEcho((state as unknown as { clinical?: unknown }).clinical, trip.id)}
            />
            <div className="pt-pad-buttons">
              <button type="button" onClick={() => setPad("drug")}>
                <Pill /> {t("pt.pad.drug")}
              </button>
              <button type="button" onClick={() => setPad("event")}>
                <Zap /> {t("pt.pad.event")}
              </button>
            </div>
          </section>
        )}

        <section className="pt-dispatch" aria-label={t("pt.dispatch")}>
          <h2 className="pt-section-title">
            <Radio /> {t("pt.dispatch")}
          </h2>
          <div className="crew-talk">
            {speech.supported ? (
              <>
                <button
                  type="button"
                  className={`ptt${dispatchListening ? " listening" : ""}`}
                  disabled={(dispatch.busy && !dispatchListening) || logListening}
                  aria-pressed={dispatchListening}
                  {...dispatchMic}
                >
                  <span className="ptt-icon">
                    <Mic />
                  </span>
                  <span>{dispatchListening ? t("crew.pttListening") : t("pt.holdDispatch")}</span>
                  <span className="ptt-sub">{dispatchListening ? t("crew.pttTapStop") : t("crew.pttTapOnce")}</span>
                </button>
                <div className="crew-talk-bar">
                  <span className="lang-toggle big" role="group" aria-label={t("tab.speechLang")}>
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
                  <span className="muted">
                    {t("crew.speaks", { lang: t(speech.lang === "sl-SI" ? "crew.speaksSl" : "crew.speaksEn") })}
                  </span>
                </div>
                {!speechSecureContext() && <div className="warn-box">{t("crew.needsHttps")}</div>}
                {dispatchListening && <div className="voice-interim big">{speech.interim || "Govorite… / Speak now…"}</div>}
                {(lastChannel !== "log" || !logOn) && speech.error && <div className="message error">{speech.error}</div>}
              </>
            ) : (
              <div className="warn-box">{t("crew.needsChrome")}</div>
            )}
          </div>

          <DispatchPanel dispatch={dispatch} draft={draft} setDraft={setDraft} />
        </section>
      </div>

      {logOn && pad === "drug" && (
        <DrugPad
          onClose={() => setPad(null)}
          onSave={(c) => {
            log.add("drug_administered", c, { source: "crew_tap" });
            setPad(null);
          }}
        />
      )}
      {logOn && pad === "vitals" && (
        <VitalsPad
          onClose={() => setPad(null)}
          onSave={(c) => {
            log.add("vitals", c, { source: "crew_tap" });
            setPad(null);
          }}
        />
      )}
      {logOn && pad === "event" && (
        <EventPad
          onClose={() => setPad(null)}
          onSave={(key, label, minutesAgo) => {
            log.add("event", { key, label }, { source: "crew_tap", observed_t: minutesAgo > 0 ? observedAt(state.sim_time, minutesAgo) : null });
            setPad(null);
          }}
        />
      )}

      <footer className="pt-foot">
        <Link to={`/crew?world=${world}`}>{t("tab.switchVehicle")}</Link>
        <Link to={`/${world}`}>{t("crew.dashboard")}</Link>
        <LangToggle className="crew-uilang" />
        <span className={`crew-world ${world}`}>{world === "sim" ? t("tab.chipSim") : t("tab.chipLive")}</span>
      </footer>
    </main>
  );
}
