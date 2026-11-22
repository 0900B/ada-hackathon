import { useEffect, useRef, useState } from "react";
import { Baby, Stethoscope, TrendingDown, Users, X } from "lucide-react";
import { DOCTOR_CONDITIONS } from "./doctor";
import { hasKey, t as tx, tr, translate, useT } from "./i18n";
import { CONDITIONS, LEVEL_HELP, LEVEL_LABEL, LEVEL_PRIORITY, LEVEL_TARGET_MIN, modifierLabel, type Condition, type Level } from "./severity";

type PickLevel = Exclude<Level, "routine">;

const LEVEL_KEYS: { level: PickLevel; key: string }[] = [
  { level: "critical", key: "c" },
  { level: "serious", key: "s" },
  { level: "urgent", key: "u" },
];
const MOD_KEYS = [
  { code: "child", key: "k", icon: Baby },
  { code: "deteriorating", key: "w", icon: TrendingDown },
  { code: "multiple_patients", key: "p", icon: Users },
];

/** The English label of a condition or modifier (the note sent to the backend stays English). */
const english = (key: string, fallback: string) => (hasKey(key) ? translate("en", key) : fallback);
const QUICK: { level: PickLevel; code: string }[] = [
  { level: "critical", code: "cardiac_arrest" },
  { level: "serious", code: "stroke" },
];

/** What the picker sends: an urgent_request with the severity fields (older backends use priority and the note). */
export function emergencyEvent(lat: number, lon: number, c: Condition, modifiers: string[]): Record<string, unknown> {
  const mods = MOD_KEYS.filter((m) => modifiers.includes(m.code)).map((m) => english(`mod.${m.code}`, m.code).toLowerCase());
  return {
    type: "urgent_request",
    lat,
    lon,
    priority: LEVEL_PRIORITY[c.level],
    needs: "stretcher",
    dropoff_id: "ukc",
    severity: c.level,
    condition: c.code,
    modifiers,
    note: [english(`cond.${c.code}`, c.label), ...mods].join(", "),
  };
}

/**
 * Before a new emergency call is sent (E, then a click on the map): what it is. One click for the
 * common cases, or by keyboard: C / S / U pick the level, 1-6 send that condition, K / W / P toggle
 * a child, getting worse or several patients, Enter sends the first condition, Esc cancels.
 */
export function EmergencyPicker({
  at,
  onSend,
  onCancel,
}: {
  at: { lat: number; lon: number };
  onSend: (event: Record<string, unknown>) => void;
  onCancel: () => void;
}) {
  const t = useT();
  const [level, setLevel] = useState<PickLevel>("critical");
  const [mods, setMods] = useState<string[]>([]);
  const list = CONDITIONS.filter((c) => c.level === level);
  const box = useRef<HTMLDivElement>(null);

  const send = (c: Condition) => onSend(emergencyEvent(at.lat, at.lon, c, mods));
  const toggle = (code: string) => setMods((m) => (m.includes(code) ? m.filter((x) => x !== code) : [...m, code]));

  // Keys go to the picker while it is open (captured before the dashboard's own shortcuts)
  const keys = useRef({ list, send, toggle, setLevel, onCancel });
  keys.current = { list, send, toggle, setLevel, onCancel };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
      const k = keys.current;
      const key = e.key.toLowerCase();
      let handled = true;
      if (key === "escape") k.onCancel();
      else if (key === "enter" && k.list[0]) k.send(k.list[0]);
      else if (/^[1-9]$/.test(key) && k.list[Number(key) - 1]) k.send(k.list[Number(key) - 1]);
      else if (LEVEL_KEYS.some((l) => l.key === key)) k.setLevel(LEVEL_KEYS.find((l) => l.key === key)!.level);
      else if (MOD_KEYS.some((m) => m.key === key)) k.toggle(MOD_KEYS.find((m) => m.key === key)!.code);
      else handled = false;
      if (handled) {
        e.preventDefault(); // the dashboard's hotkeys ignore handled events
        e.stopPropagation();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);

  useEffect(() => box.current?.focus(), []);

  return (
    <div className="epick" ref={box} tabIndex={-1} role="dialog" aria-label={t("dash.pick.title")}>
      <div className="epick-head">
        <strong>{t("dash.pick.title")}</strong>
        <span className="muted small">
          {at.lat.toFixed(4)}, {at.lon.toFixed(4)} · {t("dash.pick.toUkc")}
        </span>
        <button className="link epick-close" onClick={onCancel} aria-label={t("dash.pick.cancel")} title={t("dash.pick.cancel")}>
          <X />
        </button>
      </div>
      <div className="epick-quick">
        {QUICK.map((q) => {
          const c = CONDITIONS.find((x) => x.code === q.code)!;
          return (
            <button
              key={q.code}
              className={`epick-q sev-${q.level}`}
              onClick={() => send(c)}
              title={t("dash.pick.sendNow", { level: LEVEL_LABEL[q.level], cond: c.label })}
            >
              <span className="sev-level">{LEVEL_LABEL[q.level]}</span> {c.label}
              {DOCTOR_CONDITIONS.has(c.code) && <DoctorNeeded short />}
            </button>
          );
        })}
      </div>
      <div className="epick-levels" role="tablist" aria-label={t("dash.pick.severity")}>
        {LEVEL_KEYS.map(({ level: l, key }) => (
          <button
            key={l}
            role="tab"
            aria-selected={level === l}
            className={`epick-level sev-${l}${level === l ? " on" : ""}`}
            onClick={() => setLevel(l)}
            title={t("dash.pick.levelTitle", { help: LEVEL_HELP[l], key: key.toUpperCase() })}
          >
            <span className="sev-level">{LEVEL_LABEL[l]}</span>
            <kbd>{key.toUpperCase()}</kbd>
          </button>
        ))}
      </div>
      <ol className="epick-conds">
        {list.map((c, i) => (
          <li key={c.code}>
            <button onClick={() => send(c)} title={t("dash.pick.send", { level: LEVEL_LABEL[c.level], cond: c.label, w: c.weight })}>
              <kbd>{i + 1}</kbd>
              <span className="epick-cond">{c.label}</span>
              {DOCTOR_CONDITIONS.has(c.code) && <DoctorNeeded short />}
              <span className={`sev-tw${c.weight >= 8 ? " hi" : c.weight >= 5 ? " mid" : ""}`}>T{c.weight}</span>
            </button>
          </li>
        ))}
      </ol>
      <div className="epick-mods" aria-label={t("dash.pick.case")}>
        {MOD_KEYS.map(({ code, key, icon: Icon }) => (
          <button key={code} className={`epick-mod${mods.includes(code) ? " on" : ""}`} aria-pressed={mods.includes(code)} onClick={() => toggle(code)}>
            <Icon /> {modifierLabel(code)} <kbd>{key.toUpperCase()}</kbd>
          </button>
        ))}
      </div>
      <div className="epick-foot muted small">
        {t("dash.pick.target", { min: LEVEL_TARGET_MIN[level] })}
        {list.some((c) => DOCTOR_CONDITIONS.has(c.code)) && t("dash.pick.doctorGoes")} ·{" "}
        {tr("dash.pick.keysSend", { first: <kbd>1</kbd>, last: <kbd>{list.length}</kbd> })} ·{" "}
        {tr("dash.pick.enterSends", { enter: <kbd>Enter</kbd> }, { cond: list[0]?.label })} · {tr("dash.pick.escCancels", { esc: <kbd>Esc</kbd> })}
      </div>
    </div>
  );
}

/** This condition brings a doctor: a doctor car (VUZ) joins the ambulance crew on scene. */
function DoctorNeeded({ short = false }: { short?: boolean }) {
  return (
    <span className="epick-dr" title={tx("dash.pick.drTitle")}>
      <Stethoscope aria-hidden />
      {short ? tx("dash.pick.drShort") : tx("dash.pick.drLong")}
    </span>
  );
}
