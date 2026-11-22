import { useState } from "react";
import { AlertTriangle, Check } from "lucide-react";
import { postAction } from "./api";
import type { ActionBody, CaseCard, CaseDetailData, ErAlert, LogEntry, Team, Vital, World } from "./api";
import { ago, clock, minutesBetween, sexLabel } from "./format";
import {
  ENTRY_LABEL,
  EVENT_LABEL,
  LEVEL_LABEL,
  PROBLEM_LABEL,
  SEVERITY_LABEL,
  STAGES,
  TEAMS,
  TEAM_LABEL,
  VITAL_DEFS,
  caseTitle,
  stageIndex,
  titleIsNote,
} from "./labels";

const STALE_MIN = 10;

function StageRail({ c }: { c: CaseCard }) {
  const at = stageIndex(c.stage);
  return (
    <ol className="stages" aria-label="Where the patient is">
      {STAGES.map((s, i) => (
        <li key={s.stage} className={i < at ? "past" : i === at ? `now ${c.stage_inferred ? "estimated" : ""}` : ""} aria-current={i === at ? "step" : undefined}>
          <span>{s.gloss}</span>
        </li>
      ))}
      {at >= 0 && c.stage_inferred && <li className="stage-note">The current step is estimated from the vehicle's movement.</li>}
    </ol>
  );
}

function VitalTile({ label, unit, value, v }: { label: string; unit: string; value: string; v: Vital }) {
  const stale = v.age_min > STALE_MIN;
  return (
    <div className={`vital ${stale ? "stale" : ""} ${v.needs_check ? "check" : ""}`}>
      <div className="vital-label">{label}</div>
      <div className="vital-value">
        {value}
        {unit && <span className="vital-unit"> {unit}</span>}
      </div>
      <div className="vital-age">
        {ago(v.age_min)}
        {stale && " (old reading)"}
      </div>
      {v.needs_check && <div className="vital-flag">Check this value: outside what is possible</div>}
      {!v.needs_check && v.state !== "confirmed" && <div className="vital-state">{v.state === "heard" ? "Heard, not confirmed" : "Inferred"}</div>}
    </div>
  );
}

function Vitals({ c }: { c: CaseCard }) {
  const tiles = VITAL_DEFS.flatMap((d) => {
    if (d.key === "sbp") {
      const s = c.vitals.sbp;
      const dbp = c.vitals.dbp;
      if (!s && !dbp) return [];
      const ref = (s && dbp ? (s.age_min >= dbp.age_min ? s : dbp) : (s ?? dbp)) as Vital;
      const merged: Vital = { ...ref, needs_check: !!(s?.needs_check || dbp?.needs_check) };
      return [<VitalTile key="bp" label={d.label} unit={d.unit} value={`${s?.value ?? "–"}/${dbp?.value ?? "–"}`} v={merged} />];
    }
    const v = c.vitals[d.key];
    return v ? [<VitalTile key={d.key} label={d.label} unit={d.unit} value={String(v.value)} v={v} />] : [];
  });
  if (!tiles.length) return <p className="empty">No vitals reported yet. The crew sends them once the patient is on board.</p>;
  return <div className="vitals">{tiles}</div>;
}

function describeEntry(e: LogEntry): string {
  const k = e.content;
  switch (e.type) {
    case "triage":
      return `${String(k.level)}, ${PROBLEM_LABEL[String(k.problem_type)] ?? k.problem_type}`;
    case "patient_info":
      return [k.age_years != null ? `age ${k.age_years}` : "", k.sex ? sexLabel(String(k.sex)) : ""].filter(Boolean).join(", ");
    case "vitals":
      return Object.entries(k)
        .filter(([, v]) => v !== null)
        .map(([m, v]) => `${m} ${v}`)
        .join(", ");
    case "drug_administered":
      return `${k.drug} ${k.dose} ${k.route}`;
    case "procedure":
      return String(k.name);
    case "severity":
      return SEVERITY_LABEL[String(k.value)] ?? String(k.value);
    case "event":
      return EVENT_LABEL[String(k.kind)] ?? String(k.kind);
    case "handover":
    case "free":
      return String(k.note ?? "");
    case "note":
      return String(k.text ?? "");
    case "er_action": {
      const a = String(k.action);
      const what = a === "bay_assigned" ? `Bay ${k.bay} assigned` : a === "team_activated" ? `${TEAM_LABEL[k.team as Team] ?? k.team} called` : "Acknowledged";
      // the note says why, for example "Called automatically: problem type: stroke"
      return e.verbatim ? `${what}. ${e.verbatim}` : what;
    }
    default:
      return "";
  }
}

function Timeline({ entries, supersededIds }: { entries: LogEntry[]; supersededIds: Set<string> }) {
  if (!entries.length) return <p className="empty">Nothing recorded yet.</p>;
  return (
    <ol className="timeline">
      {[...entries].reverse().map((e) => (
        <li key={e.seq} className={supersededIds.has(e.entry_id) ? "replaced" : ""}>
          <time>{clock(e.observed_t)}</time>
          <span className="tl-type">{ENTRY_LABEL[e.type] ?? e.type}</span>
          <span className="tl-text">{describeEntry(e)}</span>
          <span className="tl-src dim">
            {e.unit}
            {e.state !== "confirmed" && `, ${e.state}`}
            {supersededIds.has(e.entry_id) && ", replaced by a correction"}
            {e.needs_check && ", check this entry"}
          </span>
        </li>
      ))}
    </ol>
  );
}

function Actions({ world, c, onDone }: { world: World; c: CaseCard; onDone: () => void }) {
  const [bay, setBay] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const run = async (body: ActionBody, okText: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await postAction(world, c.case_id, body);
      setMsg({ ok: true, text: okText });
      if (body.action === "bay_assigned") setBay("");
      onDone();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const suggested = new Set(c.suggested_actions.filter((s) => s.action === "team_activated").map((s) => s.team));
  const reasonFor = (action: string, team?: Team) => c.suggested_actions.find((s) => s.action === action && (!team || s.team === team))?.reason;

  return (
    <section className="panel" aria-labelledby="act-h">
      <h3 id="act-h">What reception can do</h3>
      <div className="act-grid">
        <div className="act">
          <button type="button" className={`btn ${!c.acknowledged ? "primary" : ""}`} disabled={busy || c.acknowledged} onClick={() => run({ action: "acknowledge" }, "Acknowledged")}>
            {c.acknowledged ? (
              <>
                <Check size={16} aria-hidden /> Acknowledged
              </>
            ) : (
              "Acknowledge this case"
            )}
          </button>
          {reasonFor("acknowledge") && <p className="why">{reasonFor("acknowledge")}</p>}
        </div>

        <form
          className="act"
          onSubmit={(e) => {
            e.preventDefault();
            if (bay.trim()) run({ action: "bay_assigned", bay: bay.trim() }, `Bay ${bay.trim()} assigned`);
          }}
        >
          <label htmlFor={`bay-${c.case_id}`}>{c.bay ? `Bay ${c.bay}. Change to:` : "Assign a bay"}</label>
          <div className="inline">
            <input id={`bay-${c.case_id}`} value={bay} onChange={(e) => setBay(e.target.value)} placeholder="e.g. R2" maxLength={40} autoComplete="off" />
            <button type="submit" className={`btn ${!c.bay ? "primary" : ""}`} disabled={busy || !bay.trim()}>
              Assign bay
            </button>
          </div>
        </form>

        <div className="act wide">
          <div className="act-label">Call a team</div>
          <div className="teams">
            {TEAMS.map((t) => {
              const on = c.teams_activated.includes(t);
              return (
                <button
                  key={t}
                  type="button"
                  className={`btn ${suggested.has(t) && !on ? "primary" : ""}`}
                  disabled={busy || on}
                  title={reasonFor("team_activated", t)}
                  onClick={() => run({ action: "team_activated", team: t }, `${TEAM_LABEL[t]} called`)}
                >
                  {on ? (
                    <>
                      <Check size={16} aria-hidden /> {TEAM_LABEL[t]} called
                    </>
                  ) : (
                    TEAM_LABEL[t]
                  )}
                </button>
              );
            })}
          </div>
          {[...suggested].map((t) => {
            const r = reasonFor("team_activated", t as Team);
            return r ? (
              <p className="why" key={String(t)}>
                Suggested: {TEAM_LABEL[t as Team]}. {r}
              </p>
            ) : null;
          })}
        </div>
      </div>
      <p className="hint">Suggestions only. Nothing is sent until someone presses a button.</p>
      <div role="status" aria-live="polite" className={msg ? `msg ${msg.ok ? "ok" : "bad"}` : "msg"}>
        {msg?.text}
      </div>
    </section>
  );
}

export function CaseDetail({
  world,
  c,
  data,
  alerts,
  asOf,
  onChanged,
}: {
  world: World;
  c: CaseCard;
  data: CaseDetailData | null;
  alerts: ErAlert[];
  asOf: string;
  onChanged: () => void;
}) {
  const problem = caseTitle(c.problem);
  const who = [c.age_years !== null ? `${c.age_years} years` : null, sexLabel(c.sex) || null].filter(Boolean).join(", ");
  const superseded = new Set((data?.timeline ?? []).map((e) => e.supersedes).filter((s): s is string => !!s));
  const arrived = c.arrived_at !== null;

  return (
    <article className="detail" aria-label={`Case ${c.case_id}`}>
      <header className={`d-head level-${c.level.value}`}>
        <div>
          <h2>{problem}</h2>
          <p className="d-sub">
            {who || c.patient_label}
            {who && <span className="dim"> {c.patient_label}</span>}
            {c.vehicle_id && <span className="dim"> unit {c.vehicle_id}</span>}
          </p>
          {c.problem.note && !titleIsNote(c.problem) && <p className="d-note">“{c.problem.note}”</p>}
        </div>
        <div className="d-facts">
          <span className={`level-tag level-${c.level.value}`}>
            {LEVEL_LABEL[c.level.value]}
            {c.level.inferred && " (assumed)"}
          </span>
          {c.severity && <span className="chip">On-scene severity: {SEVERITY_LABEL[c.severity] ?? c.severity}</span>}
          <span className="chip">
            {arrived
              ? `Arrived ${clock(c.arrived_at)} (${ago(minutesBetween(c.arrived_at as string, asOf))})`
              : c.eta_dropoff
                ? `Expected ${clock(c.eta_dropoff)}`
                : "No arrival time yet"}
          </span>
        </div>
      </header>

      {c.level.inferred && <p className="banner">Nobody has triaged this case. The colour comes from the dispatch priority.</p>}

      {alerts.length > 0 && (
        <section className="panel" aria-labelledby="al-h">
          <h3 id="al-h">Needs attention</h3>
          <ul className="alert-list">
            {alerts.map((a) => (
              <li key={a.id} className={`sev-${a.severity}`}>
                <AlertTriangle size={15} aria-hidden /> {a.message}
                {a.since && <span className="dim"> since {clock(a.since)}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="panel" aria-labelledby="st-h">
        <h3 id="st-h">Where the patient is</h3>
        <StageRail c={c} />
      </section>

      <Actions key={c.case_id} world={world} c={c} onDone={onChanged} />

      <section className="panel" aria-labelledby="vi-h">
        <h3 id="vi-h">Vitals</h3>
        <Vitals c={c} />
      </section>

      <div className="two">
        <section className="panel" aria-labelledby="tr-h">
          <h3 id="tr-h">Treatment so far</h3>
          {c.treatments.length === 0 && c.events.length === 0 ? (
            <p className="empty">No drugs, procedures or key events recorded.</p>
          ) : (
            <ul className="plain">
              {c.treatments.map((t) => (
                <li key={t.seq}>
                  <time>{clock(t.observed_t)}</time>{" "}
                  {t.type === "drug_administered" ? `${t.content.drug}, ${t.content.dose}, ${t.content.route}` : t.content.name}
                </li>
              ))}
              {c.events.map((e, i) => (
                <li key={`e${i}`}>
                  <time>{clock(e.observed_t)}</time> {EVENT_LABEL[e.kind] ?? e.kind}
                  {e.onset_t && <span className="dim"> began {clock(e.onset_t)}</span>}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="panel" aria-labelledby="hi-h">
          <h3 id="hi-h">Everything recorded</h3>
          <Timeline entries={data?.timeline ?? []} supersededIds={superseded} />
        </section>
      </div>
    </article>
  );
}
