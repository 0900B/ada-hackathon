import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, Bot, Truck, Volume2, VolumeX, WifiOff } from "lucide-react";
import type { ErAlert, World } from "./api";
import { useAlertSound, useAutoTeams, usePersistentFlag } from "./automation";
import { CaseModal } from "./CaseModal";
import { CaseRow, isArrived } from "./CaseList";
import { clock } from "./format";
import { ALERT_LABEL } from "./labels";
import { enableSound, playTest } from "./sound";
import { useBoard, useCaseDetail } from "./useBoard";

function initialWorld(): World {
  const w = new URLSearchParams(window.location.search).get("world");
  return w === "live" ? "live" : "sim";
}

function useNow(ms: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(id);
  }, [ms]);
  return now;
}

export default function App() {
  const [world, setWorld] = useState<World>(initialWorld);
  const [selected, setSelected] = useState<string | null>(() => window.location.hash.slice(1) || null);
  const { board, lastOk, error, featureOff, refresh } = useBoard(world);
  const detail = useCaseDetail(world, selected, board?.seq ?? null);
  const now = useNow(1000);

  // sound is off until someone turns it on (browsers need a click); auto-calling teams is on by default
  const [sound, setSound] = usePersistentFlag("er.sound", false);
  const [auto, setAuto] = usePersistentFlag("er.autoTeams", true);
  const [soundBlocked, setSoundBlocked] = useState(false);
  useEffect(() => {
    // a remembered "on" still needs one click this session before the browser lets it play
    if (sound && !enableSound()) setSoundBlocked(true);
  }, [sound]);
  useAlertSound(world, board, sound);
  const afterAuto = useCallback(() => {
    refresh();
    detail.reload();
  }, [refresh, detail.reload]);
  const autoState = useAutoTeams(world, board, auto, afterAuto);

  const toggleSound = () => {
    if (sound) {
      setSound(false);
      return;
    }
    if (enableSound()) {
      setSoundBlocked(false);
      setSound(true);
      playTest();
    } else setSoundBlocked(true);
  };

  const switchWorld = (w: World) => {
    setWorld(w);
    setSelected(null);
    const url = new URL(window.location.href);
    url.searchParams.set("world", w);
    url.hash = "";
    window.history.replaceState(null, "", url.toString());
  };
  const select = useCallback((id: string | null) => {
    setSelected(id);
    window.history.replaceState(null, "", id ? `#${id}` : window.location.pathname + window.location.search);
  }, []);
  const closeModal = useCallback(() => select(null), [select]);

  const alertsByCase = useMemo(() => {
    const m = new Map<string, ErAlert[]>();
    for (const a of board?.alerts ?? []) m.set(a.case_id, [...(m.get(a.case_id) ?? []), a]);
    return m;
  }, [board]);

  const cases = board?.cases ?? [];
  const coming = cases.filter((c) => !isArrived(c));
  const here = cases.filter(isArrived);
  const red = coming.filter((c) => c.level.value === "red").length;
  const next = coming.find((c) => c.minutes_to_arrival !== null);
  const urgentAlerts = (board?.alerts ?? []).filter((a) => a.severity === "critical" || a.severity === "high");
  const staleSec = lastOk ? Math.round((now - lastOk) / 1000) : null;
  const offline = error !== null && !featureOff;
  const current = cases.find((c) => c.case_id === selected) ?? null;

  return (
    <div className="app">
      <header className="top">
        <div className="top-brand">
          <Activity size={20} aria-hidden />
          <h1>ER inbound board</h1>
        </div>
        <p className="summary" aria-live="polite">
          {board ? (
            coming.length === 0 ? (
              <strong>No one is on the way</strong>
            ) : (
              <>
                <strong>{coming.length} on the way</strong>
                {red > 0 && <span className="pill red">{red} red</span>}
                {next && next.minutes_to_arrival !== null && (
                  <span>
                    next in <strong>{Math.max(1, Math.ceil(next.minutes_to_arrival))} min</strong>
                  </span>
                )}
              </>
            )
          ) : (
            <span className="dim">Loading…</span>
          )}
          {urgentAlerts.length > 0 && <span className="pill alert">{urgentAlerts.length} need attention</span>}
        </p>
        <div className="top-right">
          {import.meta.env.BASE_URL !== "/" && (
            <a className="switch" href="/" title="Back to the dispatch dashboard">
              <Truck size={16} aria-hidden /> Dispatch dashboard
            </a>
          )}
          <button type="button" className={`switch ${sound ? "on" : ""}`} aria-pressed={sound} onClick={toggleSound} title="Play a sound when a new critical alert appears">
            {sound ? <Volume2 size={16} aria-hidden /> : <VolumeX size={16} aria-hidden />} Alert sound {sound ? "on" : "off"}
          </button>
          <button type="button" className={`switch ${auto ? "on" : ""}`} aria-pressed={auto} onClick={() => setAuto(!auto)} title="Call the ER teams that the case calls for, without waiting for a click">
            <Bot size={16} aria-hidden /> Auto-call teams {auto ? "on" : "off"}
          </button>
          <div className="seg" role="group" aria-label="Which world to show">
            <button type="button" aria-pressed={world === "sim"} onClick={() => switchWorld("sim")} title="The demo world (runs faster than real time)">
              Simulation
            </button>
            <button type="button" aria-pressed={world === "live"} onClick={() => switchWorld("live")} title="The real-time world">
              Live
            </button>
          </div>
          <span className={`conn ${offline ? "bad" : ""}`} role="status">
            {offline ? (
              <>
                <WifiOff size={14} aria-hidden /> Connection lost{staleSec !== null ? `, data is ${staleSec} s old` : ""}
              </>
            ) : board ? (
              <>
                <span className="dot" aria-hidden /> {world === "sim" ? "Simulated time" : "Time"} {clock(board.as_of)}
              </>
            ) : null}
          </span>
        </div>
      </header>

      {soundBlocked && <p className="banner">Your browser blocked sound. Press “Alert sound” to allow it.</p>}
      {sound && !soundBlocked && <p className="visually-hidden" role="status">Alert sound is on</p>}
      {auto && autoState.error && <p className="banner bad-banner">Automatic team call failed: {autoState.error}</p>}
      {offline && board && <p className="banner bad-banner">{error}. Showing the last board received.</p>}
      {featureOff && <p className="banner bad-banner">{error}. Ask the team to start the server with the clinical module enabled.</p>}
      {offline && !board && <p className="banner bad-banner">{error}. Retrying every few seconds.</p>}

      {urgentAlerts.length > 0 && (
        <nav className="ribbon" aria-label="Alerts that need attention">
          {urgentAlerts.slice(0, 6).map((a) => (
            <button key={a.id} type="button" className={`ribbon-item sev-${a.severity}`} onClick={() => select(a.case_id)}>
              <AlertTriangle size={14} aria-hidden />
              <span className="ribbon-sev">{ALERT_LABEL[a.severity]}</span>
              <span>{a.message}</span>
              <span className="dim">{a.case_id}</span>
            </button>
          ))}
          {urgentAlerts.length > 6 && <span className="dim ribbon-more">+{urgentAlerts.length - 6} more</span>}
        </nav>
      )}

      <main className="list" aria-label="Cases">
        {board && cases.length === 0 && (
          <div className="empty-board">
            <h2>No ambulances are heading to the ER</h2>
            <p>A case appears here as soon as dispatch assigns a unit to a patient bound for the ER. This page updates by itself.</p>
          </div>
        )}
        {coming.length > 0 && board && (
          <section aria-labelledby="coming-h">
            <h2 className="list-h" id="coming-h">
              On the way
            </h2>
            <ul className="rows">
              {coming.map((c) => (
                <CaseRow key={c.case_id} c={c} asOf={board.as_of} alerts={alertsByCase.get(c.case_id) ?? []} selected={c.case_id === selected} onSelect={() => select(c.case_id)} />
              ))}
            </ul>
          </section>
        )}
        {here.length > 0 && board && (
          <section aria-labelledby="here-h">
            <h2 className="list-h" id="here-h">
              At the ER
            </h2>
            <ul className="rows">
              {here.map((c) => (
                <CaseRow key={c.case_id} c={c} asOf={board.as_of} alerts={alertsByCase.get(c.case_id) ?? []} selected={c.case_id === selected} onSelect={() => select(c.case_id)} />
              ))}
            </ul>
          </section>
        )}
      </main>

      {selected && board && current && (
        <CaseModal
          world={world}
          c={current}
          data={detail.data}
          alerts={alertsByCase.get(current.case_id) ?? []}
          asOf={board.as_of}
          onClose={closeModal}
          onChanged={afterAuto}
        />
      )}
      {selected && board && !current && (
        <div className="backdrop" onMouseDown={closeModal}>
          <div className="modal small" role="dialog" aria-modal="true" aria-label="Case not on the board" onMouseDown={(e) => e.stopPropagation()}>
            <p>
              <strong>{selected}</strong> is no longer on the board. A case leaves three hours after arrival.
            </p>
            <button type="button" className="btn primary" onClick={closeModal}>
              Back to the cases
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
