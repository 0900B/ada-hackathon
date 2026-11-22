import { useEffect, useRef, useState } from "react";
import { ChevronDown, PhoneIncoming, Zap, type LucideIcon } from "lucide-react";
import { CALL_LEVELS, FAILURES, type DemoApi } from "./demoInject";
import { useT } from "./i18n";

/** "Random call" and "Random failure" for the demo (Simulation only; hidden when the backend lacks them). */
export function DemoButtons({
  api,
  busy,
  onCall,
  onIncident,
}: {
  api: DemoApi;
  busy: boolean;
  onCall: (severity?: string) => void;
  onIncident: (kind?: string) => void;
}) {
  const t = useT();
  if (!api.call && !api.incident) return null;
  return (
    <div className="demo-buttons" role="group" aria-label={t("dash.demo.aria")}>
      {api.call && (
        <SplitMenu icon={PhoneIncoming} label={t("dash.demo.randomCall")} hotkey="R" options={CALL_LEVELS} busy={busy} onPick={onCall} />
      )}
      {api.incident && (
        <SplitMenu icon={Zap} label={t("dash.demo.randomFailure")} hotkey="X" options={FAILURES} busy={busy} onPick={onIncident} />
      )}
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
