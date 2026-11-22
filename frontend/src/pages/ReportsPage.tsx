import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import type { World } from "../api";
import { fmtTime } from "../format";
import {
  DecidedBar,
  Empty,
  HourlyChart,
  ResponseChart,
  TableView,
  UtilisationChart,
  WithinTargetChart,
  decidedTable,
  hourlyTable,
  responseTable,
  utilisationTable,
  withinTable,
} from "../ReportCharts";
import { fmtMin, fmtPct, useReport, WINDOWS, type Report } from "../reports";
import { LEVEL_LABEL, type Level } from "../severity";
import "../reports.css";

/** Operational statistics of one world over the last 1 / 3 / 8 world-hours, refreshed every 15 s. */
export function ReportsPage() {
  const [params] = useSearchParams();
  const world: World = params.get("world") === "sim" ? "sim" : "live";
  const asked = Number(params.get("hours"));
  const hours = (WINDOWS as readonly number[]).includes(asked) ? asked : 3;
  const { report, error, loading, fetchedAt } = useReport(world, hours);
  const shown = report && report.world === world ? report : null; // never show the other world's numbers

  const to = (w: World, h: number) => `/reports?world=${w}&hours=${h}`;
  return (
    <main className="page reports">
      <div className="rp-bar">
        <h2 className="page-title">
          Reports · {world === "sim" ? "Simulation" : "Live"}
          <span className="page-switch" role="group" aria-label="World">
            <Link to={to("live", hours)} className={world === "live" ? "on" : ""} aria-current={world === "live" ? "true" : undefined}>
              Live
            </Link>
            <Link to={to("sim", hours)} className={world === "sim" ? "on" : ""} aria-current={world === "sim" ? "true" : undefined}>
              Simulation
            </Link>
          </span>
          <span className="page-switch" role="group" aria-label="Time window">
            {WINDOWS.map((h) => (
              <Link key={h} to={to(world, h)} className={h === hours ? "on" : ""} aria-current={h === hours ? "true" : undefined}>
                {h} h
              </Link>
            ))}
          </span>
        </h2>
        <p className="rp-meta muted">
          {shown ? (
            <>
              World time {fmtTime(shown.window.to)} · window {fmtTime(shown.window.from)}–{fmtTime(shown.window.to)} · updated{" "}
              {fetchedAt ? new Date(fetchedAt).toLocaleTimeString("sl-SI") : ""} · refreshes every 15 s
            </>
          ) : (
            "Loading the report…"
          )}
        </p>
      </div>
      {error && <div className="message error">Could not load the report: {error}</div>}
      {shown && (
        <div className={`rp-body${loading ? " refreshing" : ""}`}>
          <Tiles r={shown} />
          <div className="rp-grid-a">
            <Card title="Response time by severity" sub="Each dot is one call" table={shown.by_severity.length ? responseTable(shown.by_severity) : null}>
              {shown.by_severity.length ? <ResponseChart stats={shown.by_severity} /> : <Empty />}
            </Card>
            <Card title="Within target by severity" sub="Reached the patient within the call's own target" table={shown.by_severity.length ? withinTable(shown.by_severity) : null}>
              {shown.by_severity.length ? <WithinTargetChart stats={shown.by_severity} /> : <Empty />}
            </Card>
          </div>
          <div className="rp-grid-b">
            <Card title="Calls closed per hour" sub="By world hour, Ljubljana time; the number under each column is the share within target" table={shown.hourly.length ? hourlyTable(shown.hourly) : null}>
              {shown.hourly.length ? <HourlyChart hourly={shown.hourly} /> : <Empty />}
            </Card>
            <Card title="Who decided" sub="The last word on each closed call" table={shown.ai.calls ? decidedTable(shown.ai.decided) : null}>
              {shown.ai.calls ? <Decided r={shown} /> : <Empty />}
            </Card>
            <Card title="Unit utilisation" sub="Share of time not idle" table={shown.utilisation.length ? utilisationTable(shown.utilisation) : null}>
              {shown.utilisation.length ? <UtilisationChart units={shown.utilisation} /> : <Empty>No fleet samples yet in this window.</Empty>}
            </Card>
          </div>
          <Footnote r={shown} />
        </div>
      )}
    </main>
  );
}

function Card({ title, sub, table, children }: { title: string; sub: string; table: { head: string[]; rows: (string | number)[][] } | null; children: ReactNode }) {
  return (
    <section className="panel rp-card">
      <h3 className="panel-title">{title}</h3>
      <p className="rp-sub muted">{sub}</p>
      <div className="rp-card-body">{children}</div>
      {table && <TableView head={table.head} rows={table.rows} />}
    </section>
  );
}

function Tile({ label, value, sub, title }: { label: string; value: string; sub: ReactNode; title?: string }) {
  return (
    <div className="rp-tile" title={title}>
      <span className="rp-tile-label">{label}</span>
      <span className="rp-tile-value">{value}</span>
      <span className="rp-tile-sub">{sub}</span>
    </div>
  );
}

function levelTile(r: Report, level: Level) {
  const s = r.by_severity.find((x) => x.severity === level);
  const met = s ? s.responses.filter((x) => x.met).length : 0;
  return (
    <Tile
      key={level}
      label={`${LEVEL_LABEL[level]} within target`}
      value={fmtPct(s?.pct_within_target)}
      sub={s && s.n_timed ? `${met} of ${s.n_timed} · median ${fmtMin(s.median_response)} · target ${s.target_min} min` : `No ${level} calls closed`}
      title={`Calls that reached the patient within their response target (${LEVEL_LABEL[level]}: ${s?.target_min ?? "–"} min${level === "critical" ? " in the city, 15 outside" : ""}).`}
    />
  );
}

function Tiles({ r }: { r: Report }) {
  const d = r.doctor;
  const t = r.transports;
  const ai = r.ai;
  const overrides = ai.decided.dispatcher_overrode;
  return (
    <div className="rp-tiles">
      <Tile label="Calls handled" value={String(r.totals.closed)} sub={`${r.totals.open} open now · last ${r.window.hours} h`} title="Calls closed in the window (the patient is at the hospital). Open calls are not counted." />
      {levelTile(r, "critical")}
      {levelTile(r, "serious")}
      <Tile
        label="Doctor on time"
        value={fmtPct(d.pct_within_15)}
        sub={d.n ? `${Math.round(((d.pct_within_15 ?? 0) * d.n) / 100)} of ${d.n} · within ${d.target_min} min${d.none_arrived ? ` · ${d.none_arrived} never arrived` : ""}` : "No call needed a doctor"}
        title="Calls that needed a doctor, with the doctor on scene within 15 minutes of the call."
      />
      <Tile
        label="Late transports"
        value={fmtPct(t.late_pct)}
        sub={t.n ? `${t.late} of ${t.n} · ${t.late_after_min} min or more after due${t.avg_delay_min != null ? ` · avg delay ${fmtMin(t.avg_delay_min)}` : ""}` : "No transport closed yet"}
        title="Patients who reached the hospital 5 minutes or more after their due time."
      />
      <Tile
        label="AI decisions vs overrides"
        value={fmtPct(ai.autonomous_share)}
        sub={ai.calls ? `${ai.calls - overrides} AI-led · ${overrides} ${overrides === 1 ? "override" : "overrides"}` : "No decisions yet"}
        title="Share of closed calls decided without a dispatcher override or manual assignment."
      />
    </div>
  );
}

function Decided({ r }: { r: Report }) {
  const ai = r.ai;
  return (
    <>
      <DecidedBar decided={ai.decided} />
      <p className="rp-assigned muted">
        Units assigned by: rules engine {ai.dispatched_by_engine} · Claude {ai.dispatched_by_claude} · dispatcher {ai.dispatched_by_dispatcher}
        {" · "}
        Claude reviewed {ai.reviewed_by_claude}, changed {ai.changed_by_claude}
      </p>
    </>
  );
}

function Footnote({ r }: { r: Report }) {
  return (
    <footer className="rp-foot muted">
      <p>
        {r.world === "sim"
          ? "Simulation: synthetic calls and fleet; times from the engine's travel model."
          : "Live: real clock, traffic and weather feeds; the calls and the fleet are synthetic and times come from the engine's travel model."}
      </p>
      <p>
        Response time runs from the call to the first unit at the patient. Targets: critical 8 min in the city (15 outside), serious 18 min, urgent 60 min; routine transports have none. Utilisation is
        sampled once per world-minute; a unit counts as busy whenever it is not idle.
      </p>
    </footer>
  );
}
