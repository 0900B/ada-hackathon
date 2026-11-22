import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import type { World } from "../api";
import { fmtTime } from "../format";
import { useT, type TFn } from "../i18n";
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
  const t = useT();
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
          {t("rep.title", { world: t(world === "sim" ? "rep.worldSim" : "rep.worldLive") })}
          <span className="page-switch" role="group" aria-label={t("rep.ariaWorld")}>
            <Link to={to("live", hours)} className={world === "live" ? "on" : ""} aria-current={world === "live" ? "true" : undefined}>
              {t("rep.worldLive")}
            </Link>
            <Link to={to("sim", hours)} className={world === "sim" ? "on" : ""} aria-current={world === "sim" ? "true" : undefined}>
              {t("rep.worldSim")}
            </Link>
          </span>
          <span className="page-switch" role="group" aria-label={t("rep.ariaWindow")}>
            {WINDOWS.map((h) => (
              <Link key={h} to={to(world, h)} className={h === hours ? "on" : ""} aria-current={h === hours ? "true" : undefined}>
                {h} h
              </Link>
            ))}
          </span>
        </h2>
        <p className="rp-meta muted">
          {shown
            ? t("rep.meta", {
                now: fmtTime(shown.window.to),
                from: fmtTime(shown.window.from),
                to: fmtTime(shown.window.to),
                updated: fetchedAt ? new Date(fetchedAt).toLocaleTimeString("sl-SI") : "",
              })
            : t("rep.loading")}
        </p>
      </div>
      {error && <div className="message error">{t("rep.loadError", { error })}</div>}
      {shown && (
        <div className={`rp-body${loading ? " refreshing" : ""}`}>
          <Tiles r={shown} />
          <div className="rp-grid-a">
            <Card title={t("rep.cardResponse")} sub={t("rep.cardResponseSub")} table={shown.by_severity.length ? responseTable(shown.by_severity) : null}>
              {shown.by_severity.length ? <ResponseChart stats={shown.by_severity} /> : <Empty />}
            </Card>
            <Card title={t("rep.cardWithin")} sub={t("rep.cardWithinSub")} table={shown.by_severity.length ? withinTable(shown.by_severity) : null}>
              {shown.by_severity.length ? <WithinTargetChart stats={shown.by_severity} /> : <Empty />}
            </Card>
          </div>
          <div className="rp-grid-b">
            <Card title={t("rep.cardHourly")} sub={t("rep.cardHourlySub")} table={shown.hourly.length ? hourlyTable(shown.hourly) : null}>
              {shown.hourly.length ? <HourlyChart hourly={shown.hourly} /> : <Empty />}
            </Card>
            <Card title={t("rep.cardDecided")} sub={t("rep.cardDecidedSub")} table={shown.ai.calls ? decidedTable(shown.ai.decided) : null}>
              {shown.ai.calls ? <Decided r={shown} /> : <Empty />}
            </Card>
            <Card title={t("rep.cardUtil")} sub={t("rep.cardUtilSub")} table={shown.utilisation.length ? utilisationTable(shown.utilisation) : null}>
              {shown.utilisation.length ? <UtilisationChart units={shown.utilisation} /> : <Empty>{t("rep.noFleetSamples")}</Empty>}
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

function levelTile(t: TFn, r: Report, level: Level) {
  const s = r.by_severity.find((x) => x.severity === level);
  const met = s ? s.responses.filter((x) => x.met).length : 0;
  return (
    <Tile
      key={level}
      label={t("rep.levelWithin", { level: LEVEL_LABEL[level] })}
      value={fmtPct(s?.pct_within_target)}
      sub={
        s && s.n_timed
          ? t("rep.levelSub", { met, n: s.n_timed, median: fmtMin(s.median_response), target: s.target_min })
          : t(`rep.noLevelCalls.${level}`)
      }
      title={t(level === "critical" ? "rep.levelTitleCity" : "rep.levelTitle", { level: LEVEL_LABEL[level], target: s?.target_min ?? "–" })}
    />
  );
}

function Tiles({ r }: { r: Report }) {
  const t = useT();
  const d = r.doctor;
  const tr = r.transports;
  const ai = r.ai;
  const overrides = ai.decided.dispatcher_overrode;
  return (
    <div className="rp-tiles">
      <Tile
        label={t("rep.tileHandled")}
        value={String(r.totals.closed)}
        sub={`${t("rep.openNow", { count: r.totals.open })} · ${t("rep.lastHours", { h: r.window.hours })}`}
        title={t("rep.tileHandledTitle")}
      />
      {levelTile(t, r, "critical")}
      {levelTile(t, r, "serious")}
      <Tile
        label={t("rep.tileDoctor")}
        value={fmtPct(d.pct_within_15)}
        sub={
          d.n
            ? t("rep.doctorSub", { ok: Math.round(((d.pct_within_15 ?? 0) * d.n) / 100), n: d.n, target: d.target_min }) +
              (d.none_arrived ? t("rep.doctorNever", { count: d.none_arrived }) : "")
            : t("rep.doctorNone")
        }
        title={t("rep.tileDoctorTitle")}
      />
      <Tile
        label={t("rep.tileLate")}
        value={fmtPct(tr.late_pct)}
        sub={
          tr.n
            ? t("rep.lateSub", { late: tr.late, n: tr.n, after: tr.late_after_min }) +
              (tr.avg_delay_min != null ? t("rep.lateAvg", { delay: fmtMin(tr.avg_delay_min) }) : "")
            : t("rep.lateNone")
        }
        title={t("rep.tileLateTitle")}
      />
      <Tile
        label={t("rep.tileAi")}
        value={fmtPct(ai.autonomous_share)}
        sub={ai.calls ? t("rep.aiSub", { led: ai.calls - overrides, count: overrides }) : t("rep.aiNone")}
        title={t("rep.tileAiTitle")}
      />
    </div>
  );
}

function Decided({ r }: { r: Report }) {
  const t = useT();
  const ai = r.ai;
  return (
    <>
      <DecidedBar decided={ai.decided} />
      <p className="rp-assigned muted">
        {t("rep.assigned", { engine: ai.dispatched_by_engine, claude: ai.dispatched_by_claude, dispatcher: ai.dispatched_by_dispatcher })}
        {" · "}
        {t("rep.reviewed", { reviewed: ai.reviewed_by_claude, changed: ai.changed_by_claude })}
      </p>
    </>
  );
}

function Footnote({ r }: { r: Report }) {
  const t = useT();
  return (
    <footer className="rp-foot muted">
      <p>{t(r.world === "sim" ? "rep.footSim" : "rep.footLive")}</p>
      <p>{t("rep.footMethod")}</p>
    </footer>
  );
}
