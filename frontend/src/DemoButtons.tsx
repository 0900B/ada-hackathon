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
  preselect?: string | null; // the unit selected on the dashboard (or the selected case's unit)
  onTarget?: (vehicleId: string, kind: string) => Promise<boolean>;
}) {
  const t = useT();
  const [targeting, setTargeting] = useState(false);
  if (!api.call && !api.incident) return null;
  const failures = state && onTarget ? [{ value: TARGET_ENTRY, label: t("dash.demo.target") }, ...FAILURES] : FAILURES;
  return (
    <div className="demo-buttons" role="group" aria-label={t("dash.demo.aria")}>
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
        <TargetPopover state={state} preselect={preselect} busy={busy} onClose={() => setTargeting(false)} onInject={onTarget} />
      )}
    </div>
  );
}

interface JobUnit {
  v: Vehicle;
  trip: Trip;
  text: string;
  equipment: boolean;
}

/** Road units on a job (the helicopter is left to Fog): "A2 · ambulance · to patient · 112-0004 Stroke, Šiška". */
function jobUnits(state: WorldSnapshot, t: ReturnType<typeof useT>): JobUnit[] {
  const out: JobUnit[] = [];
  for (const v of state.vehicles) {
    if (v.type === "helicopter" || v.status === "out_of_service") continue;
    const tid = v.current_trip_id ?? v.queue[0];
    const trip = tid ? state.trips.find((x) => x.id === tid) : undefined;
    if (!trip) continue;
    const what = conditionText(trip) ?? trip.label;
    const where = trip.call?.address ?? state.places.find((p) => p.id === trip.pickup_id)?.name ?? "";
    const call = `${trip.call?.call_id ?? trip.id} ${what}${where ? `, ${where.split(",")[0]}` : ""}`;
    out.push({
      v,
      trip,
      text: `${v.id} · ${t(`vtype.${v.type}`)} · ${vehicleStatusText(v, state.trips)} · ${call}`,
      equipment: v.type === "transport" && trip.kind === "equipment" && trip.status === "onboard",
    });
  }
  return out;
}

function TargetPopover({
  state,
  preselect,
  busy,
  onClose,
  onInject,
}: {
  state: WorldSnapshot;
  preselect: string | null;
  busy: boolean;
  onClose: () => void;
  onInject: (vehicleId: string, kind: string) => Promise<boolean>;
}) {
  const t = useT();
  const units = jobUnits(state, t);
  const [vid, setVid] = useState<string | null>(() =>
    preselect && units.some((u) => u.v.id === preselect) ? preselect : (units[0]?.v.id ?? null),
  );
  const [kind, setKind] = useState("breakdown");
  const box = useRef<HTMLDivElement>(null);
  const cur = units.find((u) => u.v.id === vid);
  const kinds = TARGET_KINDS.filter((k) => !k.equipmentOnly || cur?.equipment);
  const chosen = kinds.some((k) => k.value === kind) ? kind : "breakdown";
  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    const outside = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) onClose();
    };
    window.addEventListener("keydown", esc, true);
    document.addEventListener("mousedown", outside);
    return () => {
      window.removeEventListener("keydown", esc, true);
      document.removeEventListener("mousedown", outside);
    };
  }, [onClose]);
  return (
    <div className="target-pop" role="dialog" aria-label={t("dash.target.title")} ref={box}>
      <div className="target-head">
        <strong>{t("dash.target.title")}</strong>
        <button className="icon-btn" onClick={onClose} aria-label={t("dash.target.cancel")}>
          <X />
        </button>
      </div>
      {units.length === 0 ? (
        <p className="target-empty">{t("dash.target.none")}</p>
      ) : (
        <>
          <div className="target-label">{t("dash.target.unit")}</div>
          <ul className="target-units" role="radiogroup" aria-label={t("dash.target.unit")}>
            {units.map((u) => (
              <li key={u.v.id}>
                <button role="radio" aria-checked={u.v.id === vid} className={u.v.id === vid ? "on" : ""} onClick={() => setVid(u.v.id)} title={u.text}>
                  {u.text}
                </button>
              </li>
            ))}
          </ul>
          <div className="target-label">{t("dash.target.kind")}</div>
          <div className="target-kinds" role="radiogroup" aria-label={t("dash.target.kind")}>
            {kinds.map((k) => (
              <button key={k.value} role="radio" aria-checked={k.value === chosen} className={k.value === chosen ? "on" : ""} onClick={() => setKind(k.value)}>
                {k.label()}
              </button>
            ))}
          </div>
        </>
      )}
      <div className="target-actions">
        <button onClick={onClose}>{t("dash.target.cancel")}</button>
        <button
          className="primary"
          disabled={busy || !vid || units.length === 0}
          onClick={() => {
            if (vid) void onInject(vid, chosen).then((ok) => ok && onClose());
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
      <button className="split-caret" disabled={busy} onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open} aria-label={t("dash.demo.choose", { label })}>
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
