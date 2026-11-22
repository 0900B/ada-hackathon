import { useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, WifiOff } from "lucide-react";
import type { ErAlert, World } from "./api";
import { CaseDetail } from "./CaseDetail";
import { CaseRow, isArrived } from "./CaseList";
import { clock } from "./format";
import { ALERT_LABEL } from "./labels";
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

  const switchWorld = (w: World) => {
    setWorld(w);
    setSelected(null);
    const url = new URL(window.location.href);
    url.searchParams.set("world", w);
    url.hash = "";
    window.history.replaceState(null, "", url.toString());
  };
  const select = (id: string | null) => {
    setSelected(id);
    window.history.replaceState(null, "", id ? `#${id}` : window.location.pathname + window.location.search);
  };

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
    <div className={`app ${selected ? "has-selection" : ""}`}>
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

      <main className="split">
        <section className="list" aria-label="Cases">
          {board && cases.length === 0 && (
            <div className="empty-board">
              <h2>No ambulances are heading to the ER</h2>
              <p>A case appears here as soon as dispatch assigns a unit to a patient bound for the ER. This page updates by itself.</p>
            </div>
          )}
          {coming.length > 0 && board && (
            <>
              <h2 className="list-h">On the way</h2>
              <ul className="rows">
                {coming.map((c) => (
                  <CaseRow key={c.case_id} c={c} asOf={board.as_of} alerts={alertsByCase.get(c.case_id) ?? []} selected={c.case_id === selected} onSelect={() => select(c.case_id)} />
                ))}
              </ul>
            </>
          )}
          {here.length > 0 && board && (
            <>
              <h2 className="list-h">At the ER</h2>
              <ul className="rows">
                {here.map((c) => (
                  <CaseRow key={c.case_id} c={c} asOf={board.as_of} alerts={alertsByCase.get(c.case_id) ?? []} selected={c.case_id === selected} onSelect={() => select(c.case_id)} />
                ))}
              </ul>
            </>
          )}
        </section>

        <aside className="pane" aria-label="Case details">
          {current && board ? (
            <CaseDetail
              world={world}
              c={current}
              data={detail.data}
              alerts={alertsByCase.get(current.case_id) ?? []}
              asOf={board.as_of}
              onBack={() => select(null)}
              onChanged={() => {
                refresh(); // show the action now instead of waiting for the next poll
                detail.reload();
              }}
            />
          ) : selected && board ? (
            <div className="pane-empty">
              <p>
                <strong>{selected}</strong> is no longer on the board. A case leaves three hours after arrival.
              </p>
              <button type="button" className="btn" onClick={() => select(null)}>
                Back to the list
              </button>
            </div>
          ) : (
            <div className="pane-empty">
              <p>Select a case to see vitals, treatment and what reception can do.</p>
            </div>
          )}
        </aside>
      </main>
    </div>
  );
}
