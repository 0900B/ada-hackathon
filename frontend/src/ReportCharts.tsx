/**
 * The charts of the Reports page, drawn as plain SVG (no chart library).
 *
 * Colour carries meaning only: a call within its target is neutral, one that missed it is red; severity
 * levels keep their badge colours (and every row is also named in text); utilisation is a single hue.
 * Every chart has the same text equivalent in a table (TableView), and every mark answers hover and
 * keyboard focus with the same tooltip.
 */
import {
  createContext,
  useContext,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FocusEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import type { Vehicle } from "./api";
import { vehicleTypeLabel } from "./format";
import { t as tx, useT } from "./i18n";
import { Callsign } from "./icons";
import { fmtMin, fmtPct, fmtRaw, type AiDecided, type HourBucket, type SeverityStats, type UnitUse } from "./reports";
import { LEVEL_LABEL, LEVEL_TARGET_MIN, type Level } from "./severity";

const TZ = "Europe/Ljubljana";
export const hourLabel = (iso: string) =>
  new Date(iso).toLocaleTimeString("sl-SI", { hour: "2-digit", minute: "2-digit", timeZone: TZ });

// --- Shared pieces ----------------------------------------------------------------------------------

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setWidth(Math.floor(el.clientWidth));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

interface Tip {
  x: number;
  y: number;
  body: ReactNode;
}
interface TipApi {
  show: (at: { clientX: number; clientY: number }, body: ReactNode) => void;
  hide: () => void;
}
const TipContext = createContext<TipApi | null>(null);

/** A chart's frame: the tooltip floats above the pointer (or the focused mark), inside the frame. */
export function ChartBox({ children, className = "" }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const api = useMemo<TipApi>(
    () => ({
      show: (at, body) => {
        const r = ref.current?.getBoundingClientRect();
        if (r) setTip({ x: at.clientX - r.left, y: at.clientY - r.top, body });
      },
      hide: () => setTip(null),
    }),
    [],
  );
  return (
    <TipContext.Provider value={api}>
      <div className={`rp-chart ${className}`.trim()} ref={ref} onPointerLeave={api.hide}>
        {children}
        {tip && (
          <div className="rp-tip" role="tooltip" style={{ left: `clamp(84px, ${tip.x}px, calc(100% - 84px))`, top: tip.y }}>
            {tip.body}
          </div>
        )}
      </div>
    </TipContext.Provider>
  );
}

/** Hover and focus handlers that show `body` in the nearest ChartBox. */
function useTip() {
  const api = useContext(TipContext);
  return (body: ReactNode) => ({
    onPointerMove: (e: PointerEvent) => api?.show(e, body),
    onPointerLeave: () => api?.hide(),
    onFocus: (e: FocusEvent<Element>) => {
      const r = e.currentTarget.getBoundingClientRect();
      api?.show({ clientX: r.left + r.width / 2, clientY: r.top }, body);
    },
    onBlur: () => api?.hide(),
  });
}

function TipRows({ title, rows }: { title: ReactNode; rows: [string, ReactNode][] }) {
  return (
    <>
      <strong>{title}</strong>
      {rows.map(([k, v]) => (
        <span key={k} className="rp-tip-row">
          <span>{k}</span>
          <span>{v}</span>
        </span>
      ))}
    </>
  );
}

export function LevelChip({ level }: { level: Level }) {
  return (
    <span className={`sev sev-${level}`}>
      <span className="sev-level">{LEVEL_LABEL[level]}</span>
    </span>
  );
}

/** The chart's text twin: the same numbers as a table (collapsed; opens with a click or the keyboard). */
export function TableView({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  const t = useT();
  return (
    <details className="rp-table">
      <summary>{t("rep.tableView")}</summary>
      <table>
        <thead>
          <tr>
            {head.map((h) => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

/** A label column next to an SVG that fills the rest of the row (its width is measured). */
function PlotRow({ label, height, children, className = "" }: { label: ReactNode; height: number; className?: string; children: (width: number) => ReactNode }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  return (
    <div className={`rp-row ${className}`.trim()}>
      <div className="rp-row-label">{label}</div>
      <div className="rp-row-plot" ref={ref} style={{ height }}>
        {width > 0 && children(width)}
      </div>
    </div>
  );
}

export function Empty({ children }: { children?: ReactNode }) {
  const t = useT();
  return <p className="rp-empty">{children ?? t("rep.emptyCalls")}</p>;
}

/** Rounded at the data end (right), square at the baseline (left). */
function barH(x: number, y: number, w: number, h: number, r = 4): string {
  const rr = Math.min(r, w / 2, h / 2);
  return `M${x},${y} H${x + w - rr} a${rr},${rr} 0 0 1 ${rr},${rr} V${y + h - rr} a${rr},${rr} 0 0 1 ${-rr},${rr} H${x} Z`;
}
/** Rounded at the top, square at the bottom. */
function barV(x: number, y: number, w: number, h: number, r = 4): string {
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h} V${y + rr} a${rr},${rr} 0 0 1 ${rr},${-rr} H${x + w - rr} a${rr},${rr} 0 0 1 ${rr},${rr} V${y + h} Z`;
}

function niceStep(range: number, count = 5): number {
  const raw = Math.max(range, 1e-9) / count;
  const p = 10 ** Math.floor(Math.log10(raw));
  const f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}
/** Clean tick values from 0 up to a nice maximum that covers `max`. */
function niceScale(max: number, count = 5): { ticks: number[]; max: number } {
  const step = niceStep(max, count);
  const top = Math.ceil(max / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let v = 0; v <= top + 1e-9; v += step) ticks.push(Math.round(v * 100) / 100);
  return { ticks, max: top };
}

// --- 1. Response-time distribution per severity, with the target line --------------------------------

const DOT_R = 4;
const LANES = [0, -1, 1, -2, 2];
const LANE_GAP = 9;
const PLOT_PAD = 10;

/** Spread dots that would overlap over a few lanes above and below the centre line. */
function swarm(xs: number[]): number[] {
  const placed: { x: number; lane: number }[] = [];
  return xs.map((x, i) => {
    const free = LANES.find((lane) => !placed.some((p) => p.lane === lane && Math.abs(p.x - x) < 2 * DOT_R + 2));
    const lane = free ?? LANES[i % LANES.length];
    placed.push({ x, lane });
    return lane;
  });
}

const ROW_LEVELS: Level[] = ["critical", "serious", "urgent"];

export function ResponseChart({ stats }: { stats: SeverityStats[] }) {
  const t = useT();
  return (
    <ChartBox>
      <div className="rp-legend" aria-hidden>
        <span><i className="rp-dot met" /> {t("rep.withinTarget")}</span>
        <span><i className="rp-dot missed" /> {t("rep.missed")}</span>
        <span><i className="rp-line" /> {t("rep.target")}</span>
        <span><i className="rp-tri" /> {t("rep.median")}</span>
      </div>
      {ROW_LEVELS.map((level) => (
        <ResponseRow key={level} level={level} s={stats.find((x) => x.severity === level)} />
      ))}
      <p className="rp-axis-title">{t("rep.respAxis")}</p>
    </ChartBox>
  );
}

function ResponseRow({ level, s }: { level: Level; s: SeverityStats | undefined }) {
  const tl = useT();
  const tip = useTip();
  const timed = s?.responses ?? [];
  const label = (
    <>
      <LevelChip level={level} />
      <span className="rp-row-sub">
        {s ? (
          <>
            {tl("rep.nCalls", { count: s.n })}
            {s.median_response != null && (
              <>
                <br />
                {tl("rep.medianLine", { m: fmtMin(s.median_response) })}
                <br />
                p90 {fmtMin(s.p90_response)}
              </>
            )}
          </>
        ) : (
          tl("rep.noCalls")
        )}
      </span>
    </>
  );
  return (
    <PlotRow label={label} height={80}>
      {(w) => {
        const targets = [...new Set([s?.target_min ?? LEVEL_TARGET_MIN[level], ...timed.map((r) => r.target)].filter((t): t is number => t != null))].sort((a, b) => a - b);
        const maxResp = Math.max(0, ...timed.map((r) => r.min));
        const scale = niceScale(Math.max((targets[targets.length - 1] ?? 5) * 1.2, maxResp * 1.06, 5), 5);
        const x0 = PLOT_PAD;
        const x1 = w - PLOT_PAD;
        const sx = (v: number) => x0 + (v / scale.max) * (x1 - x0);
        const midY = 35;
        const axisY = 61;
        const sorted = [...timed].sort((a, b) => a.min - b.min);
        const lanes = swarm(sorted.map((r) => sx(r.min)));
        return (
          <svg
            width={w}
            height={80}
            role="img"
            aria-label={
              s
                ? tl("rep.respAria", { level: LEVEL_LABEL[level], n: s.n_timed, median: fmtMin(s.median_response) })
                : tl("rep.respAriaNone", { level: LEVEL_LABEL[level] })
            }
          >
            <line className="rp-axis" x1={x0} x2={x1} y1={axisY} y2={axisY} />
            {scale.ticks.map((t, i) => (
              <g key={t}>
                <line className="rp-axis" x1={sx(t)} x2={sx(t)} y1={axisY} y2={axisY + 4} />
                <text className="rp-tick" x={sx(t)} y={axisY + 16} textAnchor={i === 0 ? "start" : i === scale.ticks.length - 1 ? "end" : "middle"}>
                  {t}
                  {i === scale.ticks.length - 1 ? " min" : ""}
                </text>
              </g>
            ))}
            {!timed.length && (
              <text className="rp-tick" x={x0} y={midY + 4}>
                {tl("rep.noClosedInWindow")}
              </text>
            )}
            {targets.map((t, i) => {
              const nearEdge = sx(t) > x1 - 120;
              return (
                <g key={t}>
                  <line className="rp-target" x1={sx(t)} x2={sx(t)} y1={14} y2={axisY} />
                  <text className="rp-target-label" x={sx(t) + (nearEdge ? -5 : 5)} y={11} textAnchor={nearEdge ? "end" : "start"}>
                    {i === 0 ? tl("rep.targetMin", { t }) : tl("rep.outsideMin", { t })}
                  </text>
                </g>
              );
            })}
            {sorted.map((r, i) => {
              const cx = sx(r.min);
              const cy = midY + lanes[i] * LANE_GAP;
              const body = (
                <TipRows
                  title={tl("rep.toPatient", { m: fmtMin(r.min) })}
                  rows={[
                    [tl("rep.colLevel"), LEVEL_LABEL[level]],
                    [tl("rep.colTarget"), `${r.target} min`],
                    [tl("rep.colResult"), r.met ? tl("rep.withinTarget") : tl("rep.missedBy", { m: fmtMin(r.min - r.target) })],
                  ]}
                />
              );
              return (
                <g key={i}>
                  <circle className={`rp-mark ${r.met ? "met" : "missed"}`} cx={cx} cy={cy} r={DOT_R} />
                  <circle className="rp-hit" cx={cx} cy={cy} r={9} {...tip(body)} />
                </g>
              );
            })}
            {s?.median_response != null && (
              <path className="rp-median" d={`M${sx(s.median_response) - 5},${axisY - 9} h10 l-5,8 z`}>
                <title>{tl("rep.medianTitle", { m: fmtMin(s.median_response) })}</title>
              </path>
            )}
          </svg>
        );
      }}
    </PlotRow>
  );
}

export const withinTable = (stats: SeverityStats[]) => ({
  head: [tx("rep.colLevel"), tx("rep.colWithin"), tx("rep.withinHead2"), tx("rep.colShare")],
  rows: stats.map((s) => [LEVEL_LABEL[s.severity], s.responses.filter((r) => r.met).length, s.n_timed, fmtPct(s.pct_within_target)]),
});

export const responseTable = (stats: SeverityStats[]) => ({
  head: [
    tx("rep.colLevel"),
    tx("rep.respHeadCalls"),
    tx("rep.respHeadTimed"),
    tx("rep.respHeadTarget"),
    tx("rep.respHeadMedian"),
    tx("rep.respHeadP90"),
    tx("rep.colWithin"),
  ],
  rows: stats.map((s) => [
    LEVEL_LABEL[s.severity],
    s.n,
    s.n_timed,
    s.target_min ?? "–",
    fmtRaw(s.median_response),
    fmtRaw(s.p90_response),
    fmtPct(s.pct_within_target),
  ]),
});

// --- 2. Share within target per severity ---------------------------------------------------------------

const LEVEL_FILL: Record<Level, string> = {
  critical: "var(--rp-crit)",
  serious: "var(--rp-ser)",
  urgent: "var(--rp-urg)",
  routine: "var(--rp-rtn)",
};

export function WithinTargetChart({ stats }: { stats: SeverityStats[] }) {
  const t = useT();
  return (
    <ChartBox>
      <WithinTargetRows stats={stats} />
      <p className="rp-axis-title">{t("rep.withinAxis")}</p>
    </ChartBox>
  );
}

function WithinTargetRows({ stats }: { stats: SeverityStats[] }) {
  const tl = useT();
  const tip = useTip();
  return (
    <>
      {ROW_LEVELS.map((level) => {
        const s = stats.find((x) => x.severity === level);
        const met = s ? s.responses.filter((r) => r.met).length : 0;
        const pct = s?.pct_within_target ?? null;
        return (
          <PlotRow
            key={level}
            label={
              <>
                <LevelChip level={level} />
                <span className="rp-row-sub">{tl("rep.targetMin", { t: s?.target_min ?? LEVEL_TARGET_MIN[level] ?? "–" })}</span>
              </>
            }
            height={44}
          >
            {(w) => {
              const valueW = 92;
              const trackW = Math.max(40, w - valueW);
              const fill = pct == null ? 0 : (pct / 100) * trackW;
              const body = (
                <TipRows
                  title={tl("rep.withinTip", { level: LEVEL_LABEL[level], pct: fmtPct(pct) })}
                  rows={[
                    [tl("rep.colWithin"), s ? tl("rep.ofN", { a: met, b: s.n_timed }) : "–"],
                    [tl("rep.colMedian"), fmtMin(s?.median_response)],
                    ["p90", fmtMin(s?.p90_response)],
                  ]}
                />
              );
              return (
                <svg
                  width={w}
                  height={44}
                  role="img"
                  aria-label={
                    pct == null
                      ? tl("rep.withinAriaNone", { level: LEVEL_LABEL[level] })
                      : tl("rep.withinAria", { level: LEVEL_LABEL[level], pct: fmtPct(pct) })
                  }
                >
                  <rect className="rp-track" x={0} y={15} width={trackW} height={14} rx={4} />
                  {fill > 0 && <path d={barH(0, 15, fill, 14)} style={{ fill: LEVEL_FILL[level] }} />}
                  <rect className="rp-hit" x={0} y={6} width={trackW} height={32} tabIndex={0} aria-label={`${LEVEL_LABEL[level]} ${fmtPct(pct)}`} {...tip(body)} />
                  <text className="rp-value" x={trackW + 10} y={24}>
                    {fmtPct(pct)}
                  </text>
                  {s && s.n_timed > 0 && (
                    <text className="rp-value-sub" x={trackW + 10} y={38}>
                      {met}/{s.n_timed}
                    </text>
                  )}
                </svg>
              );
            }}
          </PlotRow>
        );
      })}
      <PlotRow label="" height={22} className="rp-axis-row">
        {(w) => {
          const trackW = Math.max(40, w - 92);
          return (
            <svg width={w} height={22} aria-hidden>
              <line className="rp-axis" x1={0} x2={trackW} y1={2} y2={2} />
              {[0, 50, 100].map((t) => (
                <g key={t}>
                  <line className="rp-axis" x1={(t / 100) * trackW} x2={(t / 100) * trackW} y1={2} y2={6} />
                  <text className="rp-tick" x={(t / 100) * trackW} y={18} textAnchor={t === 0 ? "start" : t === 100 ? "end" : "middle"}>
                    {t}%
                  </text>
                </g>
              ))}
            </svg>
          );
        }}
      </PlotRow>
    </>
  );
}

// --- 3. Calls closed per hour, with the share within target ---------------------------------------------

export function HourlyChart({ hourly }: { hourly: HourBucket[] }) {
  return (
    <ChartBox>
      <HourlyColumns hourly={hourly} />
    </ChartBox>
  );
}

function HourlyColumns({ hourly }: { hourly: HourBucket[] }) {
  const tl = useT();
  const [ref, w] = useWidth<HTMLDivElement>();
  const tip = useTip();
  const H = 190;
  const padL = 58;
  const padR = 8;
  const top = 18;
  const baseY = 130;
  const peak = Math.max(1, ...hourly.map((h) => h.calls));
  const scale = niceScale(peak, 4);
  return (
    <div ref={ref} className="rp-fill">
      <div className="rp-legend" aria-hidden>
        <span><i className="rp-sw met" /> {tl("rep.withinTarget")}</span>
        <span><i className="rp-sw missed" /> {tl("rep.missed")}</span>
        <span><i className="rp-sw other" /> {tl("rep.noTarget")}</span>
        <span><i className="rp-sw met faded" /> {tl("rep.hourIncomplete")}</span>
      </div>
      {w > 0 && (
        <svg width={w} height={H} role="img" aria-label={tl("rep.hourlyAria", { n: hourly.length })}>
          <text className="rp-tick" x={0} y={10}>
            {tl("rep.callsClosedAxis")}
          </text>
          {scale.ticks.map((t) => {
            const y = baseY - (t / scale.max) * (baseY - top);
            return (
              <g key={t}>
                <line className="rp-grid" x1={padL} x2={w - padR} y1={y} y2={y} />
                <text className="rp-tick" x={padL - 8} y={y + 4} textAnchor="end">
                  {t}
                </text>
              </g>
            );
          })}
          <line className="rp-axis" x1={padL} x2={w - padR} y1={baseY} y2={baseY} />
          <text className="rp-tick" x={padL - 8} y={baseY + 36} textAnchor="end">
            {tl("rep.inTargetAxis")}
          </text>
          {hourly.map((h, i) => {
            const slot = (w - padL - padR) / hourly.length;
            const bw = Math.min(24, slot * 0.6);
            const x = padL + slot * i + (slot - bw) / 2;
            const missed = h.timed - h.within_target;
            const other = h.calls - h.timed;
            const unit = (baseY - top) / scale.max;
            const segs = [
              { n: h.within_target, cls: "met" },
              { n: missed, cls: "missed" },
              { n: other, cls: "other" },
            ].filter((s) => s.n > 0);
            let y = baseY;
            const lastIndex = segs.length - 1;
            const body = (
              <TipRows
                title={tl("rep.hourTip", { hour: hourLabel(h.hour), count: h.calls })}
                rows={[
                  [tl("rep.colWithin"), tl("rep.ofN", { a: h.within_target, b: h.timed })],
                  [tl("rep.colShare"), fmtPct(h.pct_within_target)],
                  ...(h.partial ? ([[tl("rep.note"), tl("rep.hourIncomplete")]] as [string, string][]) : []),
                ]}
              />
            );
            return (
              <g key={h.hour} className={h.partial ? "rp-partial" : undefined}>
                {segs.map((s, k) => {
                  const hh = s.n * unit - (k < lastIndex ? 2 : 0); // 2px surface gap between stacked segments
                  y -= s.n * unit;
                  return <path key={s.cls} className={`rp-seg ${s.cls}`} d={k === lastIndex ? barV(x, y, bw, hh) : `M${x},${y + s.n * unit} v${-hh} h${bw} v${hh} Z`} />;
                })}
                <rect className="rp-hit" x={padL + slot * i} y={top} width={slot} height={baseY - top} tabIndex={0} aria-label={tl("rep.hourAria", { hour: hourLabel(h.hour), n: h.calls, pct: fmtPct(h.pct_within_target) })} {...tip(body)} />
                <text className="rp-tick" x={x + bw / 2} y={baseY + 16} textAnchor="middle">
                  {hourLabel(h.hour)}
                </text>
                <text className="rp-pct" x={x + bw / 2} y={baseY + 36} textAnchor="middle">
                  {fmtPct(h.pct_within_target)}
                </text>
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

export const hourlyTable = (hourly: HourBucket[]) => ({
  head: [tx("rep.hourHead"), tx("rep.hourHeadClosed"), tx("rep.hourHeadTimed"), tx("rep.colWithin"), tx("rep.colShare"), tx("rep.hourHeadComplete")],
  rows: hourly.map((h) => [hourLabel(h.hour), h.calls, h.timed, h.within_target, fmtPct(h.pct_within_target), tx(h.partial ? "rep.no" : "rep.yes")]),
});

// --- 4. Unit utilisation ---------------------------------------------------------------------------------

export function UtilisationChart({ units }: { units: UnitUse[] }) {
  return (
    <ChartBox className="util">
      <UtilisationRows units={units} />
    </ChartBox>
  );
}

function UtilisationRows({ units }: { units: UnitUse[] }) {
  const tl = useT();
  const tip = useTip();
  return (
    <>
      {units.map((u) => {
        const v: Pick<Vehicle, "id" | "type"> = { id: u.vehicle_id, type: u.type };
        return (
          <PlotRow key={u.vehicle_id} label={<Callsign v={v} />} height={22}>
            {(w) => {
              const valueW = 44;
              const trackW = Math.max(40, w - valueW);
              const pct = u.busy_pct ?? 0;
              const body = (
                <TipRows
                  title={tl("rep.utilTip", { id: u.vehicle_id, pct: fmtPct(u.busy_pct) })}
                  rows={[
                    [tl("rep.samples"), tl("rep.samplesValue", { n: u.samples })],
                    [tl("rep.busy"), tl("rep.busyNote")],
                  ]}
                />
              );
              return (
                <svg width={w} height={22} role="img" aria-label={tl("rep.utilAria", { id: u.vehicle_id, pct: fmtPct(u.busy_pct) })}>
                  <rect className="rp-track" x={0} y={6} width={trackW} height={10} rx={4} />
                  {pct > 0 && <path className="rp-use" d={barH(0, 6, (pct / 100) * trackW, 10)} />}
                  <rect className="rp-hit" x={0} y={1} width={trackW} height={20} tabIndex={0} aria-label={`${u.vehicle_id} ${fmtPct(u.busy_pct)}`} {...tip(body)} />
                  <text className="rp-value-sm" x={trackW + 8} y={15}>
                    {fmtPct(u.busy_pct)}
                  </text>
                </svg>
              );
            }}
          </PlotRow>
        );
      })}
      <PlotRow label="" height={22} className="rp-axis-row">
        {(w) => {
          const trackW = Math.max(40, w - 44);
          return (
            <svg width={w} height={22} aria-hidden>
              <line className="rp-axis" x1={0} x2={trackW} y1={2} y2={2} />
              {[0, 50, 100].map((t) => (
                <g key={t}>
                  <line className="rp-axis" x1={(t / 100) * trackW} x2={(t / 100) * trackW} y1={2} y2={6} />
                  <text className="rp-tick" x={(t / 100) * trackW} y={18} textAnchor={t === 0 ? "start" : t === 100 ? "end" : "middle"}>
                    {t}%
                  </text>
                </g>
              ))}
            </svg>
          );
        }}
      </PlotRow>
    </>
  );
}

export const utilisationTable = (units: UnitUse[]) => ({
  head: [tx("rep.utilHeadUnit"), tx("rep.utilHeadType"), tx("rep.busy"), tx("rep.samples")],
  rows: units.map((u) => [u.vehicle_id, vehicleTypeLabel(u.type), fmtPct(u.busy_pct), u.samples]),
});

// --- 5. Who decided -----------------------------------------------------------------------------------------

/** Who had the last word on a call; name and note follow the UI language at the time of reading. */
const decider = (key: keyof AiDecided, name: "rep.decEngine" | "rep.decAgreed" | "rep.decChanged" | "rep.decOverrode") => ({
  key,
  get name() {
    return tx(name);
  },
  get note() {
    return tx(`${name}Note`);
  },
});

export const DECIDED: { key: keyof AiDecided; name: string; note: string }[] = [
  decider("engine_only", "rep.decEngine"),
  decider("claude_agreed", "rep.decAgreed"),
  decider("claude_changed", "rep.decChanged"),
  decider("dispatcher_overrode", "rep.decOverrode"),
];

export function DecidedBar({ decided }: { decided: AiDecided }) {
  return (
    <ChartBox>
      <DecidedParts decided={decided} />
    </ChartBox>
  );
}

function DecidedParts({ decided }: { decided: AiDecided }) {
  const tl = useT();
  const tip = useTip();
  const [ref, w] = useWidth<HTMLDivElement>();
  const total = DECIDED.reduce((a, d) => a + decided[d.key], 0);
  const H = 30;
  let x = 0;
  return (
    <>
      <div ref={ref} className="rp-fill">
        {w > 0 && (
          <svg width={w} height={H} role="img" aria-label={tl("rep.decAria", { total, list: DECIDED.map((d) => `${d.name} ${decided[d.key]}`).join(", ") })}>
            {DECIDED.map((d) => {
              const n = decided[d.key];
              if (!n) return null;
              const segW = (n / total) * w;
              const sx = x;
              x += segW;
              const drawW = Math.max(1, segW - 2); // 2px surface gap between parts
              const share = Math.round((100 * n) / total);
              const body = <TipRows title={tl("rep.decTip", { name: d.name, n, count: total })} rows={[[tl("rep.colShare"), fmtPct(share)], [d.note, ""]]} />;
              return (
                <g key={d.key}>
                  <rect className={`rp-part ${d.key}`} x={sx} y={0} width={drawW} height={H} rx={4} />
                  {drawW >= 46 && (
                    <text className={`rp-part-text ${d.key}`} x={sx + 8} y={20}>
                      {fmtPct(share)}
                    </text>
                  )}
                  <rect className="rp-hit" x={sx} y={0} width={segW} height={H} tabIndex={0} aria-label={tl("rep.decPartAria", { name: d.name, n })} {...tip(body)} />
                </g>
              );
            })}
          </svg>
        )}
      </div>
      <ul className="rp-decided">
        {DECIDED.map((d) => (
          <li key={d.key}>
            <i className={`rp-sw part ${d.key}`} />
            <span className="rp-decided-name">
              {d.name} <span className="muted">{d.note}</span>
            </span>
            <span className="rp-decided-n">{decided[d.key]}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

export const decidedTable = (decided: AiDecided) => ({
  head: [tx("rep.decHead"), tx("rep.decHeadCalls")],
  rows: DECIDED.map((d) => [`${d.name} ${d.note}`, decided[d.key]]),
});
