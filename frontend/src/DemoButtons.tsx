import { useEffect, useRef, useState } from "react";
import { ChevronDown, PhoneIncoming, X, Zap, type LucideIcon } from "lucide-react";
import type { Trip, Vehicle, WorldSnapshot } from "./api";
import { CALL_LEVELS, FAILURES, TARGET_ENTRY, TARGET_KINDS, type DemoApi } from "./demoInject";
import { vehicleStatusText } from "./format";
import { useT } from "./i18n";
import { conditionText } from "./severity";

/** "Random call" and "Random failure" for the demo (Simulation only; hidden when the backend lacks them).
 * The failure menu's first entry, "Choose unit…", opens the targeted failure: a unit on a job and what
 * happens to it. */
export function DemoButtons({
  api,
  busy,
  onCall,
  onIncident,
  state,
  preselect = null,
  onTarget,
}: {
  api: DemoApi;
  busy: boolean;
  onCall: (severity?: string) => void;
  onIncident: (kind?: string) => void;
  state?: WorldSnapshot; // with onTarget: offers "Choose unit…"
  preselect?: (string | null)[] | string | null; // the unit selected on the dashboard, else the selected case's unit
  onTarget?: TargetInject;
}) {
  const t = useT();
  const [targeting, setTargeting] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  if (!api.call && !api.incident) return null;
  const failures = state && onTarget ? [{ value: TARGET_ENTRY, label: t("dash.demo.target") }, ...FAILURES] : FAILURES;
  // Closing by Esc, Cancel or a successful inject gives the keyboard back to the Random failure button
  const closeTarget = (refocus = false) => {
    setTargeting(false);
    if (refocus) requestAnimationFrame(() => wrap.current?.querySelector<HTMLElement>('.split-caret[data-hotkey="X"]')?.focus());
  };
  return (
    <div className="demo-buttons" role="group" aria-label={t("dash.demo.aria")} ref={wrap}>
      {api.call && (
        <SplitMenu icon={PhoneIncoming} label={t("dash.demo.randomCall")} hotkey="R" options={CALL_LEVELS} busy={busy} onPick={onCall} />
      )}
      {api.incident && (
        <SplitMenu
          icon={Zap}
          label={t("dash.demo.randomFailure")}
          hotkey="X"
          options={failures}
          busy={busy}
          onPick={(k) => (k === TARGET_ENTRY ? setTargeting(true) : onIncident(k))}
        />
      )}
      {targeting && state && onTarget && (
        <TargetPopover state={state} preselect={preselect} busy={busy} onClose={closeTarget} onInject={onTarget} />
      )}
    </div>
  );
}

type Tr = ReturnType<typeof useT>;
/** Resolves to null when done (the popover closes), else the reason it did not fit (shown in it; "" = nothing to say). */
export type TargetInject = (vehicleId: string, kind: string) => Promise<string | null>;

interface JobUnit {
  v: Vehicle;
  trip: Trip;
  head: string; // "A2 · ambulance · to pickup"
  call: string; // "112-0004 Suspected stroke, Polje"
  equipment: boolean; // a van with equipment on board
  turnout: boolean; // just dispatched: the crew is still getting in, no route yet
}

/** Road units on a job (the helicopter is left to Fog): "A2 · ambulance · to pickup" over "112-0004 Suspected stroke, Šiška". */
function jobUnits(state: WorldSnapshot, t: Tr): JobUnit[] {
  const out: JobUnit[] = [];
  for (const v of state.vehicles) {
    if (v.type === "helicopter" || v.status === "out_of_service") continue;
    const tid = v.current_trip_id ?? v.queue[0];
    const trip = tid ? state.trips.find((x) => x.id === tid) : undefined;
    if (!trip || trip.status === "completed" || trip.status === "cancelled") continue;
    const what = conditionText(trip) ?? trip.label;
    const where = trip.call?.address ?? state.places.find((p) => p.id === trip.pickup_id)?.name ?? "";
    const turnout = v.busy_reason === "turnout" || (v.status === "idle" && !v.current_trip_id); // the second: sent, not yet moved
    out.push({
      v,
      trip,
      head: [v.id, t(`vtype.${v.type}`), vehicleStatusText(v, state.trips), ...(turnout ? [t("dash.target.turnout")] : [])].join(" · "),
      call: `${trip.call?.call_id ?? trip.id} ${what}${where ? `, ${where.split(",")[0]}` : ""}`,
      equipment: v.type === "transport" && trip.kind === "equipment" && trip.status === "onboard",
      turnout,
    });
  }
  return out;
}

/** Why a failure does not fit this unit right now (null: it fits). Only what the screen knows for sure:
 * the backend still answers 409 with its own reason for the rest (e.g. a leg too short for a closure). */
function whyNot(u: JobUnit, kind: (typeof TARGET_KINDS)[number], t: Tr): string | null {
  const { v } = u;
  if (kind.equipmentOnly) return u.equipment ? null : t("dash.target.whyEquip");
  const onScene = v.status === "loading";
  if (kind.value === "breakdown") return onScene ? t("dash.target.whyScene", { id: v.id }) : null;
  if (!kind.road) return null;
  if (u.turnout) return t("dash.target.whyTurnout", { id: v.id });
  if (onScene) return t("dash.target.whyScene", { id: v.id });
  if (v.status !== "to_pickup" && v.status !== "with_patient") return t("dash.target.whyRoad", { id: v.id });
  return null;
}

function TargetPopover({
  state,
  preselect,
  busy,
  onClose,
  onInject,
}: {
  state: WorldSnapshot;
  preselect: (string | null)[] | string | null;
  busy: boolean;
  onClose: (refocus?: boolean) => void;
  onInject: TargetInject;
}) {
  const t = useT();
  const units = jobUnits(state, t);
  const [picked, setPicked] = useState<string | null>(() => [preselect].flat().find((id) => id && units.some((u) => u.v.id === id)) ?? null);
  const [kind, setKind] = useState("breakdown");
  const [error, setError] = useState<string | null>(null); // why the last Inject did not fit (409), until another pick
  const box = useRef<HTMLDivElement>(null);
  // The unit on screen is always one on a job now (the picked one may have finished its job meanwhile)
  const cur = units.find((u) => u.v.id === picked) ?? units[0];
  const why = new Map(TARGET_KINDS.map((k) => [k.value, cur ? whyNot(cur, k, t) : null]));
  const chosen = why.get(kind) === null ? kind : (TARGET_KINDS.find((k) => why.get(k.value) === null)?.value ?? null);
  const reasons = [...new Set([...why.values()].filter((w): w is string => w !== null))];
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  // It must fit on screen (the right-hand panel is narrow and scrolls): as tall as the room below the buttons,
  // or above them when there is more room there; the units and kinds scroll inside, Cancel and Inject stay in view
  const [fit, setFit] = useState<{ up: boolean; max: number } | null>(null);
  useEffect(() => {
    const place = () => {
      const host = box.current?.parentElement;
      if (!host) return;
      const h = host.getBoundingClientRect();
      let top = 0;
      let bottom = window.innerHeight;
      for (let p = host.parentElement; p; p = p.parentElement) {
        const o = getComputedStyle(p).overflowY;
        if (o === "auto" || o === "scroll" || o === "hidden") {
          const r = p.getBoundingClientRect();
          top = Math.max(top, r.top);
          bottom = Math.min(bottom, r.bottom);
        }
      }
      const below = bottom - h.bottom - 8;
      const above = h.top - top - 8;
      const next = below < 300 && above > below ? { up: true, max: Math.max(160, Math.floor(above)) } : { up: false, max: Math.max(160, Math.floor(below)) };
      setFit((f) => (f && f.up === next.up && f.max === next.max ? f : next));
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, []);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation(); // not also "deselect everything" of the dashboard
        close.current(true);
      }
    };
    const outside = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) close.current();
    };
    window.addEventListener("keydown", esc, true);
    document.addEventListener("mousedown", outside);
    // Keyboard first: the focus goes to the picked unit (or the dialog), so the dashboard's single-key shortcuts stay quiet
    const first = box.current?.querySelector<HTMLElement>('[aria-checked="true"]') ?? box.current;
    first?.focus();
    return () => {
      window.removeEventListener("keydown", esc, true);
      document.removeEventListener("mousedown", outside);
    };
  }, []);
  // The dashboard's shortcuts (R, X, B, D, ...) must not fire while the focus is in here; arrows move within a radio group
  const keys = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") return;
    e.stopPropagation();
    const arrow = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e.key];
    const radio = (e.target as HTMLElement).closest<HTMLElement>('[role="radio"]');
    const group = radio?.closest('[role="radiogroup"]');
    if (!arrow || !radio || !group) return;
    const all = [...group.querySelectorAll<HTMLButtonElement>('[role="radio"]:not(:disabled)')];
    const next = all[(all.indexOf(radio as HTMLButtonElement) + arrow + all.length) % all.length];
    e.preventDefault();
    next?.focus();
    next?.click();
  };
  return (
    <div
      className={`target-pop${fit?.up ? " up" : ""}`}
      role="dialog"
      aria-label={t("dash.target.title")}
      ref={box}
      tabIndex={-1}
      onKeyDown={keys}
      style={fit ? { maxHeight: fit.max } : undefined}
    >
      <div className="target-head">
        <strong>{t("dash.target.title")}</strong>
        <button className="icon-btn" onClick={() => onClose(true)} aria-label={t("dash.target.cancel")}>
          <X />
        </button>
      </div>
      <div className="target-body">
      {units.length === 0 ? (
        <p className="target-empty">{t("dash.target.none")}</p>
      ) : (
        <>
          <div className="target-label">{t("dash.target.unit")}</div>
          <ul className="target-units" role="radiogroup" aria-label={t("dash.target.unit")}>
            {units.map((u) => (
              <li key={u.v.id}>
                <button
                  role="radio"
                  aria-checked={u.v.id === cur?.v.id}
                  className={u.v.id === cur?.v.id ? "on" : ""}
                  onClick={() => {
                    setPicked(u.v.id);
                    setError(null);
                  }}
                  title={`${u.head} · ${u.call}`}
                >
                  <b>{u.head}</b>
                  <span>{u.call}</span>
                </button>
              </li>
            ))}
          </ul>
          <div className="target-label">{t("dash.target.kind")}</div>
          <div className="target-kinds" role="radiogroup" aria-label={t("dash.target.kind")}>
            {TARGET_KINDS.map((k) => {
              const off = why.get(k.value) ?? null;
              return (
                <button
                  key={k.value}
                  role="radio"
                  aria-checked={k.value === chosen}
                  className={k.value === chosen ? "on" : ""}
                  disabled={off !== null}
                  title={off ?? undefined}
                  onClick={() => {
                    setKind(k.value);
                    setError(null);
                  }}
                >
                  {k.label()}
                </button>
              );
            })}
          </div>
          {reasons.length > 0 && (
            <ul className="target-why">
              {reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </>
      )}
      </div>
      {error && (
        <p className="target-err" role="alert">
          {error}
        </p>
      )}
      <div className="target-actions">
        <button onClick={() => onClose(true)}>{t("dash.target.cancel")}</button>
        <button
          className="primary"
          disabled={busy || !cur || !chosen}
          onClick={() => {
            if (!cur || !chosen) return;
            setError(null);
            void onInject(cur.v.id, chosen).then((err) => (err === null ? close.current(true) : setError(err || null)));
          }}
        >
          <Zap /> {t("dash.target.inject")}
        </button>
      </div>
    </div>
  );
}

function SplitMenu({
  icon: Icon,
  label,
  hotkey,
  options,
  busy,
  onPick,
}: {
  icon: LucideIcon;
  label: string;
  hotkey: string;
  options: readonly { value: string; label: string }[];
  busy: boolean;
  onPick: (value?: string) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc, true);
    return () => {
      document.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", esc, true);
    };
  }, [open]);
  return (
    <div className="split" ref={box}>
      <button className="split-main" disabled={busy} onClick={() => onPick()} title={`${label} (${hotkey})`}>
        <Icon /> {busy ? "…" : label} <kbd>{hotkey}</kbd>
      </button>
      <button className="split-caret" data-hotkey={hotkey} disabled={busy} onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open} aria-label={t("dash.demo.choose", { label })}>
        <ChevronDown />
      </button>
      {open && (
        <ul className="split-menu" role="menu">
          {options.map((o) => (
            <li key={o.value || "any"}>
              <button
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  onPick(o.value || undefined);
                }}
              >
                {o.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
