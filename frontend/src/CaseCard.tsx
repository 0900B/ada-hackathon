import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Crosshair,
  ExternalLink,
  MapPin,
  Plus,
  Repeat,
  Stethoscope,
  Tablet,
  X,
} from "lucide-react";
import {
  approveOption,
  assignUnit,
  fetchAlternatives,
  MissingEndpoint,
  type Alternative,
  type WorldSnapshot,
} from "./api";
import { badgesOf, BY_SHORT, isClaude, sourceText, STEP_LABEL, type Badge, type CallView, type CaseUnit } from "./calls";
import { DoctorTag } from "./DoctorTag";
import { fmtTime } from "./format";
import { VehicleTypeIcon } from "./icons";
import { TimeWeight } from "./SeverityBadge";
import { conditionText, LEVEL_LABEL, levelOf, modifierLabel, timeWeight } from "./severity";

type Notify = (kind: "ok" | "error", text: string) => void;

const STATUS_CLASS: Record<string, string> = {
  waiting: "bad",
  dispatched: "",
  "en route": "moving",
  "on scene": "loaded",
  transporting: "loaded",
  "at hospital": "done",
  closed: "done",
  cancelled: "done",
};

const minsUntil = (iso: string | null, now: string) => (iso ? Math.max(0, Math.round((Date.parse(iso) - Date.parse(now)) / 60_000)) : null);

/** What the dispatcher is overriding: one unit (replace) or a new one (add) of a role. */
interface OverrideTarget {
  mode: "replace" | "add";
  role: string;
  unit: CaseUnit | null;
}

const ADD_ROLES = [
  { role: "doctor", label: "Doctor car" },
  { role: "helicopter", label: "Helicopter (doctor on board)" },
  { role: "ambulance", label: "Second ambulance" },
];
// A case without a unit yet: the dispatcher assigns one (instead of waiting for the AI)
const ASSIGN_ROLES = [
  { role: "ambulance", label: "Ambulance" },
  { role: "transport", label: "Transport van" },
  { role: "helicopter", label: "Helicopter" },
];

/**
 * One case as an incident sheet: what it is and its status, where, what is happening (the caller's
 * words and the AI's triage), the units with the AI's reason for each, who did what (Claude, the rules
 * engine, the dispatcher) and the timeline. The dispatcher can override any unit or add one.
 */
export function CaseCard({
  c,
  state,
  open,
  selected,
  isNew,
  canOverride,
  overrideUnit,
  onToggle,
  onSelectVehicle,
  onCentreVehicle,
  onShowOnMap,
  onMissingOverride,
  notify,
  refCb,
}: {
  c: CallView;
  state: WorldSnapshot;
  open: boolean;
  selected: boolean;
  isNew: boolean;
  canOverride: boolean; // the backend has the alternatives/assign endpoints
  overrideUnit: { id: string; n: number } | null; // open the override list of this unit (from a vehicle card)
  onToggle: () => void;
  onSelectVehicle: (vehicleId: string, openCard: boolean) => void;
  onCentreVehicle: (vehicleId: string) => void;
  onShowOnMap: () => void;
  onMissingOverride: () => void;
  notify: Notify;
  refCb: (el: HTMLElement | null) => void;
}) {
  const t = c.trip;
  const level = levelOf(t);
  const cond = conditionText(t);
  const w = timeWeight(t);
  const [busy, setBusy] = useState(false);
  const [tlOpen, setTlOpen] = useState(false);
  const [override, setOverride] = useState<OverrideTarget | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const done = c.status === "closed" || c.status === "cancelled";

  // From a vehicle card's "Override": open that unit's list once the card is open
  const applied = useRef(0);
  useEffect(() => {
    if (!overrideUnit || applied.current === overrideUnit.n || !open) return;
    applied.current = overrideUnit.n;
    const unit = c.units.find((u) => u.id === overrideUnit.id);
    if (unit && canOverride && !done) setOverride({ mode: "replace", role: unit.role, unit });
  }, [overrideUnit, open]); // eslint-disable-line react-hooks/exhaustive-deps

  const approve = async () => {
    const run = c.proposal;
    if (!run?.recommendation) return;
    setBusy(true);
    try {
      await approveOption(state.world, run.id, run.recommendation.recommended_index);
      notify("ok", `Approved ${run.id}: ${run.recommendation.options[run.recommendation.recommended_index]?.title ?? ""}`);
    } catch (e) {
      notify("error", e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const first = c.units[0];
  const badges = badgesOf(c);
  const hasDoctor = c.units.some((u) => u.role === "doctor" || (u.role === "helicopter" && u.id === t.doctor_vehicle_id));
  const noUnit = c.units.length === 0;
  const addRoles = noUnit
    ? ASSIGN_ROLES
    : ADD_ROLES.filter((r) => !(r.role === "doctor" && hasDoctor) && !(r.role === "helicopter" && c.units.some((u) => u.type === "helicopter")));
  const proposal = c.proposal?.recommendation ? c.proposal : null;

  return (
    <li
      className={`case lvl-${level}${open ? " open" : ""}${selected ? " selected" : ""}${isNew ? " case-new" : ""}${c.status === "waiting" ? " waiting" : ""}${done ? " done" : ""}`}
      ref={refCb}
    >
      <button className="case-head" onClick={onToggle} aria-expanded={open} title={open ? "Collapse" : "Open the case and show its units on the map"}>
        <span className="case-title">
          <span className="case-level">{LEVEL_LABEL[level]}</span>
          {cond && <span className="case-cond">· {cond}</span>}
          {w != null && <TimeWeight w={w} />}
          <span className={`case-status ${STATUS_CLASS[c.status] ?? ""}`}>{c.status}</span>
        </span>
        <span className="case-meta">
          {open ? <ChevronDown /> : <ChevronRight />}
          <span className="case-id">{c.id}</span>
          <span>{fmtTime(c.received)}</span>
          {c.kind === "hospital_request" && <span className="call-kind">Hospital request</span>}
          {proposal && !open && <span className="case-flag">AI proposal waiting</span>}
        </span>
        {!open && (
          <span className="case-sum">
            <span className="case-sum-addr">{c.address}</span>
            {first ? (
              <span className="case-sum-unit">
                {first.id} {first.eta ? `${first.etaLabel} ${fmtTime(first.eta)}` : first.etaLabel}
                {c.units.length > 1 ? ` · +${c.units.length - 1} unit${c.units.length > 2 ? "s" : ""}` : ""}
              </span>
            ) : (
              !done && <span className="case-sum-unit bad">No unit yet</span>
            )}
          </span>
        )}
      </button>

      {!open && <Badges badges={badges} />}

      {open && (
        <div className="case-body">
          <section className="case-sec">
            <h4>Where</h4>
            <div className="case-where">
              <div>
                <div className="case-address">{c.address}</div>
                {c.caller && <div className="muted small">{c.kind === "hospital_request" ? "Requested by" : "Caller"}: {c.caller}</div>}
              </div>
              <button className="sm" onClick={onShowOnMap} title="Centre the map on the patient and blink the call marker">
                <MapPin /> On map
              </button>
            </div>
          </section>

          <section className="case-sec">
            <h4>What's happening</h4>
            {(c.textSl || c.textEn) && (
              <blockquote className="call-words">
                {c.textSl && (
                  <div>
                    <span className="lang-tag">SL</span>
                    {c.textSl}
                  </div>
                )}
                {c.textEn && c.textEn !== c.textSl && (
                  <div className="muted">
                    <span className="lang-tag">EN</span>
                    {c.textEn}
                  </div>
                )}
              </blockquote>
            )}
            <TriageLine c={c} />
          </section>

          <section className="case-sec">
            <h4>
              Units
              <DoctorTag trip={t} vehicles={state.vehicles} now={state.sim_time} />
            </h4>
            {c.units.length === 0 && !done && <div className="case-nounit">No unit yet: the AI dispatcher keeps looking for one</div>}
            {c.units.map((u) => (
              <UnitTile
                key={u.id}
                u={u}
                state={state}
                canOverride={canOverride && !done}
                overriding={override?.mode === "replace" && override.unit?.id === u.id}
                onOverride={() => setOverride((o) => (o?.unit?.id === u.id ? null : { mode: "replace", role: u.role, unit: u }))}
                onCentre={() => onCentreVehicle(u.id)}
                onSelect={() => onSelectVehicle(u.id, true)}
              >
                {override?.mode === "replace" && override.unit?.id === u.id && (
                  <OverridePanel
                    c={c}
                    state={state}
                    target={override}
                    onClose={() => setOverride(null)}
                    onMissing={() => {
                      setOverride(null);
                      onMissingOverride();
                    }}
                    onDone={(summary) => {
                      setOverride(null);
                      setResult(summary);
                      notify("ok", summary);
                    }}
                    notify={notify}
                  />
                )}
              </UnitTile>
            ))}
            {proposal?.recommendation && (
              <div className="case-proposal">
                <div>
                  <span className={`src-tag ${proposal.engine === "claude" ? "claude" : "rules"}`}>{proposal.engine === "claude" ? "Claude" : "Rules engine"}</span>{" "}
                  <strong>AI proposes:</strong> {proposal.recommendation.options[proposal.recommendation.recommended_index]?.title}
                </div>
                <button className="approve primary sm" disabled={busy} onClick={() => void approve()}>
                  <Check /> Approve
                </button>
              </div>
            )}
            {canOverride && !done && (
              <div className="case-add">
                <div className="split">
                  <button className="sm" onClick={() => setAddOpen((o) => !o)} aria-haspopup="menu" aria-expanded={addOpen}>
                    <Plus /> {noUnit ? "Assign a unit" : "Add unit"} <ChevronDown />
                  </button>
                  {addOpen && (
                    <AddMenu
                      roles={addRoles}
                      onClose={() => setAddOpen(false)}
                      onPick={(role) => {
                        setAddOpen(false);
                        // no unit yet: "replace" nothing, i.e. assign; otherwise the unit comes in addition
                        setOverride({ mode: noUnit ? "replace" : "add", role, unit: null });
                      }}
                    />
                  )}
                </div>
              </div>
            )}
            {override && !override.unit && (
              <OverridePanel
                c={c}
                state={state}
                target={override}
                onClose={() => setOverride(null)}
                onMissing={() => {
                  setOverride(null);
                  onMissingOverride();
                }}
                onDone={(summary) => {
                  setOverride(null);
                  setResult(summary);
                  notify("ok", summary);
                }}
                notify={notify}
              />
            )}
            {result && (
              <div className="case-result">
                <Check /> <span>{result}</span>
                <button className="link" onClick={() => setResult(null)} aria-label="Dismiss">
                  <X />
                </button>
              </div>
            )}
          </section>

          <Badges badges={badges} />

          <section className="case-sec case-tl-sec">
            <button className="link case-tl-toggle" onClick={() => setTlOpen((o) => !o)} aria-expanded={tlOpen}>
              {tlOpen ? <ChevronDown /> : <ChevronRight />} Timeline ({c.timeline.length} {c.timeline.length === 1 ? "step" : "steps"})
            </button>
            {tlOpen && (
              <ol className="case-tl">
                {c.timeline.map((e, i) => (
                  <li key={i} className={`tl-${e.kind}`} title={`${e.text}${e.detail || e.by ? `\n${sourceText(e.by, e.detail)}` : ""}`}>
                    <span className="tl-time">{fmtTime(e.at)}</span>
                    <span className="tl-step">{STEP_LABEL[e.kind] ?? e.kind}</span>
                    <span className={`tl-by by-${isClaude(e.by) ? "ai" : e.by}`}>{BY_SHORT[e.by] ?? e.by}</span>
                    <span className="tl-text">
                      {e.vehicle_id && (
                        <button className="link tl-unit" onClick={() => onSelectVehicle(e.vehicle_id!, true)} title={`Open ${e.vehicle_id}'s vehicle card`}>
                          {e.vehicle_id}
                        </button>
                      )}
                      {e.text}
                    </span>
                  </li>
                ))}
                {!done && (
                  <li className="tl-next muted">
                    <span className="tl-time">…</span>
                    <span className="tl-step">{c.status}</span>
                  </li>
                )}
              </ol>
            )}
          </section>
        </div>
      )}
    </li>
  );
}

/** The AI's triage: who classified it, level and condition, the reason, case modifiers. */
function TriageLine({ c }: { c: CallView }) {
  const t = c.trip;
  const by = c.triageBy;
  if (c.kind === "hospital_request" && !c.reasonEn) {
    return <div className="case-triage muted small">Hospital request: graded {LEVEL_LABEL[levelOf(t)].toLowerCase()} by the request, no triage needed</div>;
  }
  const label = by === "dispatcher" ? "Dispatcher" : isClaude(by) ? "AI triage · Claude" : by === "rules" ? "AI triage · rules" : "Triage";
  const src = by === "dispatcher" ? "dispatcher" : isClaude(by) ? "claude" : "rules";
  const mods = t.modifiers ?? [];
  // "Catastrophic bleeding: rapid loss of …" after "Critical · Catastrophic bleeding": drop the repeat
  const condLabel = conditionText(t);
  let why = c.reasonEn?.trim() ?? "";
  if (condLabel && why.toLowerCase().startsWith(`${condLabel.toLowerCase()}:`)) why = why.slice(condLabel.length + 1).trim();
  return (
    <div className="case-triage" title={`Classified by ${sourceText(by, c.triageDetail)}`}>
      <span className={`src-tag ${src}`}>{label}</span>
      <span className="case-triage-text">
        <strong>
          {LEVEL_LABEL[levelOf(t)]}
          {conditionText(t) ? ` · ${conditionText(t)}` : ""}
        </strong>
        {why ? <span className="case-triage-why">: {why}</span> : null}
      </span>
      {(mods.length > 0 || t.needs_doctor || c.trip.call?.triage?.needs_doctor) && (
        <span className="case-mods">
          {(t.needs_doctor || c.trip.call?.triage?.needs_doctor) && (
            <span className="mod-tag doctor">
              <Stethoscope /> Doctor needed
            </span>
          )}
          {mods.map((m) => (
            <span key={m} className="mod-tag">
              {modifierLabel(m)}
            </span>
          ))}
        </span>
      )}
    </div>
  );
}

export function Badges({ badges }: { badges: Badge[] }) {
  return (
    <div className="case-badges" aria-label="Who did what">
      {badges.map((b) => (
        <span key={b.key} className={`who-badge ${b.tone}`} title={b.title}>
          {b.check && <Check />}
          {b.label}
          {b.src && <span className="who-src">{b.src}</span>}
        </span>
      ))}
    </div>
  );
}

function UnitTile({
  u,
  state,
  canOverride,
  overriding,
  onOverride,
  onCentre,
  onSelect,
  children,
}: {
  u: CaseUnit;
  state: WorldSnapshot;
  canOverride: boolean;
  overriding: boolean;
  onOverride: () => void;
  onCentre: () => void;
  onSelect: () => void;
  children?: ReactNode;
}) {
  const left = minsUntil(u.eta, state.sim_time);
  const who = u.by === "dispatcher" ? "Dispatcher" : "AI";
  return (
    <div className={`unit-tile role-${u.role} ph-${u.phase}${overriding ? " overriding" : ""}`}>
      <div className="ut-head">
        <button className="link ut-id" onClick={onSelect} title={`${u.name}: open the vehicle card`}>
          {u.type && <VehicleTypeIcon type={u.type} />}
          {u.id}
        </button>
        <span className="ut-role">{u.roleLabel}</span>
        {u.eta ? (
          <span className="ut-eta">
            {u.etaLabel} <strong>{fmtTime(u.eta)}</strong>
            {left != null && u.phase !== "on_scene" ? ` · ${left} min` : ""}
          </span>
        ) : (
          <span className="ut-eta">{u.etaLabel}</span>
        )}
      </div>
      {u.progress != null && (
        <div className="ut-bar" aria-hidden>
          <i style={{ width: `${Math.round(u.progress * 100)}%` }} />
        </div>
      )}
      <div className="ut-step">{u.step}</div>
      {u.reason && (
        <div className={`ut-reason${u.by === "dispatcher" ? " by-dispatcher" : ""}`} title={`Decided by ${u.source}${u.assignedAt ? ` at ${fmtTime(u.assignedAt)}` : ""}\n${u.reason}`}>
          <span className={`ai-tag${u.by === "dispatcher" ? " dispatcher" : isClaude(u.by) ? " claude" : ""}`}>{who}</span>
          <span className="ut-reason-text">{u.reason}</span>
          {u.by !== "dispatcher" && <span className="ut-src">{u.by ? (BY_SHORT[u.by] ?? u.by) : "Engine"}</span>}
        </div>
      )}
      <div className="ut-actions">
        {canOverride && (
          <button className={`sm${overriding ? " on" : ""}`} onClick={onOverride} aria-expanded={overriding} title={`Choose another unit instead of ${u.id}`}>
            <Repeat /> Override <ChevronDown />
          </button>
        )}
        <button className="sm" onClick={onCentre} title={`Centre the map on ${u.id}`}>
          <Crosshair /> Centre
        </button>
        <a className="button-link sm" href={`/vehicle/${encodeURIComponent(u.id)}?world=${state.world}`} target="_blank" rel="noopener" title={`${u.id}'s tablet view`}>
          <Tablet /> Tablet <ExternalLink />
        </a>
      </div>
      {children}
    </div>
  );
}

function AddMenu({ roles, onPick, onClose }: { roles: { role: string; label: string }[]; onPick: (role: string) => void; onClose: () => void }) {
  const box = useRef<HTMLUListElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.parentElement?.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [onClose]);
  return (
    <ul className="split-menu" role="menu" ref={box}>
      {roles.map((r) => (
        <li key={r.role}>
          <button role="menuitem" onClick={() => onPick(r.role)}>
            {r.label}
          </button>
        </li>
      ))}
    </ul>
  );
}

/** The engine's ranked alternatives for one role; pick one, confirm, and the dispatcher's choice is applied. */
function OverridePanel({
  c,
  state,
  target,
  onClose,
  onDone,
  onMissing,
  notify,
}: {
  c: CallView;
  state: WorldSnapshot;
  target: OverrideTarget;
  onClose: () => void;
  onDone: (summary: string) => void;
  onMissing: () => void;
  notify: Notify;
}) {
  const [alts, setAlts] = useState<Alternative[] | null>(null);
  const [currentEta, setCurrentEta] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const tripId = c.trip.id;
  const role = target.role;
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = setTimeout(() => box.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }), 350);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    let stop = false;
    setAlts(null);
    setError(null);
    fetchAlternatives(state.world, tripId, role)
      .then((r) => {
        if (stop) return;
        setAlts(r.alternatives.filter((a) => a.vehicle_id !== target.unit?.id));
        setCurrentEta(r.current?.eta_scene ?? target.unit?.eta ?? null);
      })
      .catch((e) => {
        if (stop) return;
        if (e instanceof MissingEndpoint) onMissing();
        else setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      stop = true;
    };
  }, [state.world, tripId, role]); // eslint-disable-line react-hooks/exhaustive-deps

  const confirm = async () => {
    if (!picked) return;
    setBusy(true);
    try {
      const r = await assignUnit(state.world, tripId, {
        vehicle_id: picked,
        mode: target.mode,
        role,
        ...(target.unit ? { replaces: target.unit.id } : {}),
      });
      onDone(r.summary ?? (target.unit ? `${picked} replaces ${target.unit.id} on ${c.id}` : target.mode === "replace" ? `${picked} assigned to ${c.id}` : `${picked} added to ${c.id}`));
    } catch (e) {
      if (e instanceof MissingEndpoint) onMissing();
      else {
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
        notify("error", msg);
      }
    } finally {
      setBusy(false);
    }
  };

  const roleLabel = ([...ADD_ROLES, ...ASSIGN_ROLES].find((r) => r.role === role)?.label ?? role).toLowerCase();
  const title = target.unit ? `Replace ${target.unit.id} with…` : target.mode === "replace" ? `Assign ${roleLabel}…` : `Add ${roleLabel}…`;
  const pickedAlt = alts?.find((a) => a.vehicle_id === picked);
  return (
    <div className="override" role="group" aria-label={title} ref={box}>
      <div className="override-head">
        <strong>{title}</strong>
        <span className="muted small">ranked by the rules engine · at the patient{target.unit ? ` · vs ${target.unit.id}` : ""}</span>
        <button className="link vc-close" onClick={onClose} aria-label="Close">
          <X />
        </button>
      </div>
      {!alts && !error && <div className="muted small">Asking the engine for alternatives…</div>}
      {error && <div className="message error">{error}</div>}
      {alts && alts.length === 0 && <div className="muted small">No other unit can take this now.</div>}
      {alts && alts.length > 0 && (
        <ul className="override-list" role="listbox" aria-label="Alternatives">
          {alts.map((a, i) => {
            const eta = a.eta_scene ?? a.eta ?? null;
            const delta =
              a.delta_min ?? a.delta_vs_current_min ?? a.delta ?? (eta && currentEta ? (Date.parse(eta) - Date.parse(currentEta)) / 60_000 : null);
            const v = state.vehicles.find((x) => x.id === a.vehicle_id);
            const type = (v?.type ?? a.vehicle_type ?? null) as CaseUnit["type"];
            return (
              <li key={a.vehicle_id}>
                <button
                  role="option"
                  aria-selected={picked === a.vehicle_id}
                  className={`override-opt${picked === a.vehicle_id ? " on" : ""}`}
                  disabled={a.feasible === false}
                  onClick={() => setPicked(a.vehicle_id)}
                >
                  <span className="oo-line">
                    <span className="oo-rank">{i + 1}</span>
                    {type && <VehicleTypeIcon type={type} />}
                    <strong>{a.vehicle_id}</strong>
                    <span className="muted">{a.name && a.name !== a.vehicle_id ? a.name : ""}</span>
                    <span className="oo-eta" title="When it would reach the patient">
                      {eta ? fmtTime(eta) : "no estimate"}
                    </span>
                    {delta != null && target.unit && (
                      <span className={`oo-delta${delta > 0.5 ? " worse" : delta < -0.5 ? " better" : ""}`}>
                        {Math.abs(delta) < 0.5 ? "same" : `${delta > 0 ? "+" : "−"}${Math.round(Math.abs(delta))} min`}
                      </span>
                    )}
                  </span>
                  {a.cost_text && <span className="oo-cost">{a.cost_text}</span>}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <div className="override-actions">
        <button className="primary sm" disabled={!picked || busy} onClick={() => void confirm()}>
          <Check />{" "}
          {busy
            ? "Applying…"
            : picked
              ? target.unit
                ? `Confirm: ${picked} replaces ${target.unit.id}`
                : target.mode === "replace"
                  ? `Confirm: assign ${picked}`
                  : `Confirm: add ${picked}`
              : "Pick a unit"}
        </button>
        <button className="sm ghost" onClick={onClose}>
          Cancel
        </button>
      </div>
      {pickedAlt && target.unit && (
        <div className="muted small">
          {target.unit?.id} is released. Logged as the dispatcher's decision, not the AI's.
        </div>
      )}
    </div>
  );
}
