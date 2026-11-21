import { useEffect, useRef } from "react";
import { HOTKEYS, keyLabel, type HotkeyInfo } from "./hotkeys";
import "./voice.css";

/**
 * Keyboard shortcut overlay. Closes with Escape, `?`, the × button or a click outside.
 * While open it swallows those two keys (capture phase), so the dashboard's own `?` / Escape
 * bindings don't fire a second time.
 */
export function ShortcutsHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" || e.key === "?") {
        e.preventDefault();
        e.stopPropagation();
        closeRef.current();
      }
    };
    window.addEventListener("keydown", onKeyDown, true);
    panel.current?.focus();
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [open]);

  if (!open) return null;

  const groups = new Map<string, HotkeyInfo[]>();
  for (const h of HOTKEYS) groups.set(h.group, [...(groups.get(h.group) ?? []), h]);

  return (
    <div className="kbd-overlay" onClick={onClose}>
      <div
        ref={panel}
        className="kbd-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Keyboard shortcuts"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="kbd-head">
          <h2>Keyboard shortcuts</h2>
          <button className="link" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="kbd-groups">
          {[...groups].map(([group, keys]) => (
            <section key={group}>
              <h3>{group}</h3>
              <ul>
                {keys.map((h) => (
                  <li key={h.key}>
                    <span className="kbd-keys">
                      {h.key.split("+").map((k) => (
                        <kbd key={k}>{keyLabel(k)}</kbd>
                      ))}
                    </span>
                    <span>{h.label}</span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
        <p className="muted">Letter keys are ignored while typing in a field; press Esc to leave the field.</p>
      </div>
    </div>
  );
}
