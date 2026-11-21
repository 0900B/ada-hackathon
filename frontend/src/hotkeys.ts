import { useEffect, useRef } from "react";

/**
 * Global keyboard shortcuts.
 *
 * Binding keys are `KeyboardEvent.key` values, case-insensitive: "m", "?", "Escape", "1".
 * A "ctrl+" prefix (also matches Cmd on macOS) is supported, e.g. "ctrl+k". Plain bindings never
 * fire while Ctrl/Cmd/Alt is held, so browser shortcuts (Ctrl+C, …) keep working.
 *
 * Ignored while typing in an input, textarea, select or contenteditable, except Escape, which
 * runs its binding and also leaves the field (blur), so the letter shortcuts work again.
 * Ctrl+Enter in the field-message box is handled by that box itself, not here.
 */
export type HotkeyBindings = Record<string, (e: KeyboardEvent) => void>;

export interface HotkeyInfo {
  key: string;
  label: string;
  group: string;
}

/** Shown in the help overlay (`?`). The dashboard (App.tsx) binds the handlers with `useHotkeys`. */
export const HOTKEYS: HotkeyInfo[] = [
  { key: "a", label: "Analyse now", group: "AI dispatcher" },
  { key: "y", label: "Approve the recommended option", group: "AI dispatcher" },
  { key: "n", label: "Reject the recommendation", group: "AI dispatcher" },
  { key: "m", label: "Voice input on / off", group: "Message from the field" },
  { key: "Ctrl+Enter", label: "Send the message (in the message box)", group: "Message from the field" },
  { key: "b", label: "Breakdown of the selected vehicle (click its marker, chip or trip row first)", group: "Events" },
  { key: "d", label: "Delay the selected vehicle 10 min", group: "Events" },
  { key: "f", label: "Fog: ground helicopters 1 h", group: "Events" },
  { key: "e", label: "Emergency call: click the map, then pick what it is (1 sends Critical · Cardiac arrest; C / S / U level, 1-6 condition, K / W / P case)", group: "Events" },
  { key: "c", label: "Road closure (then click the map)", group: "Events" },
  { key: "r", label: "Random 112 call (simulation)", group: "Demo" },
  { key: "x", label: "Random failure: crash, closure, fog, breakdown, delay… (simulation)", group: "Demo" },
  { key: "Escape", label: "Cancel / deselect / close", group: "General" },
  { key: "?", label: "Show / hide this help", group: "General" },
];

export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

function matches(combo: string, e: KeyboardEvent): boolean {
  const parts = combo.toLowerCase().split("+");
  // "+" itself as a key: "ctrl++" -> ["ctrl", "", ""]
  const key = parts[parts.length - 1] === "" && parts.length > 1 ? "+" : parts[parts.length - 1];
  const wantCtrl = parts.includes("ctrl") || parts.includes("meta") || parts.includes("cmd");
  const wantAlt = parts.includes("alt");
  const hasCtrl = e.ctrlKey || e.metaKey;
  if (wantCtrl !== hasCtrl || wantAlt !== e.altKey) return false;
  return e.key.toLowerCase() === key;
}

/**
 * Bind global shortcuts while the calling component is mounted.
 * `bindings` may be a fresh object on every render (the latest one is always used).
 */
export function useHotkeys(bindings: HotkeyBindings, enabled = true) {
  const ref = useRef(bindings);
  useEffect(() => {
    ref.current = bindings;
  });

  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.repeat || e.isComposing) return;
      const typing = isTypingTarget(e.target);
      if (typing && e.key !== "Escape") return;
      for (const [combo, fn] of Object.entries(ref.current)) {
        if (!matches(combo, e)) continue;
        if (typing) (e.target as HTMLElement).blur();
        else e.preventDefault();
        fn(e);
        return;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled]);
}

/** Pretty label for a key in the help overlay. */
export function keyLabel(key: string): string {
  if (key === "Escape") return "Esc";
  if (key.length === 1) return key.toUpperCase();
  return key;
}
