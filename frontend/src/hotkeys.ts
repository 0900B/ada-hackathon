import { useEffect, useRef } from "react";
import { t, type TKey } from "./i18n";

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

/** A shortcut whose label and group follow the UI language. */
const hotkey = (key: string, label: TKey, group: TKey): HotkeyInfo => ({
  key,
  get label() {
    return t(label);
  },
  get group() {
    return t(group);
  },
});

/** Shown in the help overlay (`?`). The dashboard (App.tsx) binds the handlers with `useHotkeys`. */
export const HOTKEYS: HotkeyInfo[] = [
  hotkey("a", "dash.keys.a", "dash.keys.groupAi"),
  hotkey("y", "dash.keys.y", "dash.keys.groupAi"),
  hotkey("n", "dash.keys.n", "dash.keys.groupAi"),
  hotkey("m", "dash.keys.m", "dash.keys.groupMessage"),
  hotkey("Ctrl+Enter", "dash.keys.ctrlEnter", "dash.keys.groupMessage"),
  hotkey("b", "dash.keys.b", "dash.keys.groupEvents"),
  hotkey("d", "dash.keys.d", "dash.keys.groupEvents"),
  hotkey("f", "dash.keys.f", "dash.keys.groupEvents"),
  hotkey("e", "dash.keys.e", "dash.keys.groupEvents"),
  hotkey("c", "dash.keys.c", "dash.keys.groupEvents"),
  hotkey("r", "dash.keys.r", "dash.keys.groupDemo"),
  hotkey("x", "dash.keys.x", "dash.keys.groupDemo"),
  hotkey("Escape", "dash.keys.escape", "dash.keys.groupGeneral"),
  hotkey("?", "dash.keys.help", "dash.keys.groupGeneral"),
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
