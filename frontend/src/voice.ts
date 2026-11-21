import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type MouseEvent as ReactMouseEvent } from "react";

/**
 * Voice input over the browser's Web Speech API (Chrome / Edge; Safari partly).
 *
 * One recognition session = one phrase: the browser stops by itself when the speaker pauses
 * (or when `stop()` is called, e.g. on releasing a push-to-talk button). `onFinal` is then called
 * once with the whole transcript of that session.
 */

// --- Minimal Web Speech API types (own names, so they never clash with lib.dom) ---------------

interface SpeechAlternative {
  readonly transcript: string;
  readonly confidence: number;
}
interface SpeechResult {
  readonly isFinal: boolean;
  readonly length: number;
  readonly [index: number]: SpeechAlternative;
}
interface SpeechResultList {
  readonly length: number;
  readonly [index: number]: SpeechResult;
}
interface SpeechResultEvent extends Event {
  readonly resultIndex: number;
  readonly results: SpeechResultList;
}
interface SpeechErrorEvent extends Event {
  readonly error: string;
  readonly message?: string;
}
interface SpeechRecognizer {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onstart: ((e: Event) => void) | null;
  onresult: ((e: SpeechResultEvent) => void) | null;
  onerror: ((e: SpeechErrorEvent) => void) | null;
  onend: ((e: Event) => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type SpeechRecognizerCtor = new () => SpeechRecognizer;

function recognizerCtor(): SpeechRecognizerCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: SpeechRecognizerCtor; webkitSpeechRecognition?: SpeechRecognizerCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/** True when this browser has speech recognition at all. */
export const speechSupported = () => recognizerCtor() !== null;

/** Microphone access needs HTTPS or localhost; a phone on http://192.168.x.x gets "not-allowed". */
export const speechSecureContext = () => typeof window === "undefined" || window.isSecureContext !== false;

export type SpeechLang = "sl-SI" | "en-US";
export const SPEECH_LANGS: { code: SpeechLang; label: string }[] = [
  { code: "sl-SI", label: "SL" },
  { code: "en-US", label: "EN" },
];

const LANG_KEY = "planb.speechLang";

function savedLang(fallback: string): string {
  try {
    return localStorage.getItem(LANG_KEY) ?? fallback;
  } catch {
    return fallback;
  }
}

function errorText(code: string): string | null {
  switch (code) {
    case "aborted":
      return null; // we stopped it ourselves
    case "not-allowed":
    case "service-not-allowed":
      return speechSecureContext()
        ? "Microphone permission denied. Allow the mic for this site (icon in the address bar) and try again."
        : "Voice input needs HTTPS (or localhost). Open the https:// address of the app.";
    case "no-speech":
      return "No speech heard. Try again and speak right after pressing the mic.";
    case "audio-capture":
      return "No microphone found.";
    case "network":
      return "Speech service unreachable. The browser needs internet for voice input.";
    case "language-not-supported":
      return "This browser can't recognise this language. Switch SL/EN or type the message.";
    default:
      return `Voice input error: ${code}`;
  }
}

export interface SpeechInput {
  /** Browser has the Web Speech API (Chrome, Edge, Safari 14.5+). */
  supported: boolean;
  listening: boolean;
  /** Live transcript of the current session (final parts + the part still being recognised). */
  interim: string;
  start: () => void;
  stop: () => void;
  toggle: () => void;
  lang: string;
  setLang: (lang: string) => void;
  error: string | null;
}

export function useSpeechInput(opts?: { lang?: string; onFinal?: (text: string) => void }): SpeechInput {
  const [supported] = useState(speechSupported);
  const [lang, setLangState] = useState(() => savedLang(opts?.lang ?? "sl-SI"));
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);

  const recRef = useRef<SpeechRecognizer | null>(null);
  const onFinalRef = useRef(opts?.onFinal);
  useEffect(() => {
    onFinalRef.current = opts?.onFinal;
  });

  const setLang = useCallback((l: string) => {
    setLangState(l);
    try {
      localStorage.setItem(LANG_KEY, l);
    } catch {
      /* private mode etc.: not remembered, still works */
    }
  }, []);

  const stop = useCallback(() => {
    // stop() (not abort()) so the browser still delivers what it heard so far.
    try {
      recRef.current?.stop();
    } catch {
      /* already stopped */
    }
  }, []);

  const start = useCallback(() => {
    const Ctor = recognizerCtor();
    if (!Ctor) {
      setError("Voice input needs Chrome or Edge.");
      return;
    }
    if (recRef.current) return; // a session is already running

    const rec = new Ctor();
    rec.lang = lang;
    rec.continuous = false; // one phrase; ends on a pause (continuous mode is buggy on Android Chrome)
    rec.interimResults = true;
    rec.maxAlternatives = 1;

    let finalText = "";
    let liveText = "";
    let failed = false;

    rec.onresult = (e) => {
      // Rebuild from all results each time: robust against browsers that resend earlier results.
      let fin = "";
      let tmp = "";
      for (let i = 0; i < e.results.length; i++) {
        const r = e.results[i];
        const t = r[0]?.transcript ?? "";
        if (r.isFinal) fin += t;
        else tmp += t;
      }
      finalText = fin.trim();
      liveText = `${fin}${tmp}`.trim();
      if (recRef.current === rec) setInterim(liveText);
    };
    rec.onerror = (e) => {
      const msg = errorText(e.error);
      if (msg) {
        failed = e.error !== "no-speech";
        if (recRef.current === rec) setError(msg);
      }
    };
    rec.onend = () => {
      if (recRef.current !== rec) return; // unmounted or replaced
      recRef.current = null;
      setListening(false);
      setInterim("");
      // Some browsers end without marking the last words final: use what was shown.
      const text = (finalText || (failed ? "" : liveText)).trim();
      if (text) onFinalRef.current?.(text);
    };

    recRef.current = rec;
    setError(null);
    setInterim("");
    setListening(true);
    try {
      rec.start();
    } catch (e) {
      recRef.current = null;
      setListening(false);
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [lang]);

  const toggle = useCallback(() => {
    if (recRef.current) stop();
    else start();
  }, [start, stop]);

  // Stop cleanly on unmount: detach handlers first so nothing updates an unmounted component.
  useEffect(
    () => () => {
      const rec = recRef.current;
      recRef.current = null;
      if (rec) {
        rec.onresult = rec.onerror = rec.onend = null;
        try {
          rec.abort();
        } catch {
          /* ignore */
        }
      }
    },
    [],
  );

  return { supported, listening, interim, start, stop, toggle, lang, setLang, error };
}

/**
 * Pointer handlers for one mic button that does both:
 * - tap/click: toggle (starts; the session ends by itself after the phrase, or tap again to stop);
 * - press and hold (> 350 ms): push-to-talk, release to stop.
 * Keyboard (Enter/Space on the focused button) toggles.
 */
export function usePushToTalk(speech: Pick<SpeechInput, "listening" | "start" | "stop">, holdMs = 350) {
  const press = useRef<{ at: number; wasListening: boolean } | null>(null);

  const onPointerDown = (e: ReactPointerEvent<HTMLElement>) => {
    if (e.button !== 0) return;
    e.preventDefault(); // no focus steal / text selection on long press
    try {
      e.currentTarget.setPointerCapture(e.pointerId); // release counts even if the finger slides off
    } catch {
      /* ignore */
    }
    press.current = { at: Date.now(), wasListening: speech.listening };
    if (!speech.listening) {
      navigator.vibrate?.(20);
      speech.start();
    }
  };

  const onPointerUp = () => {
    const p = press.current;
    press.current = null;
    if (!p) return;
    const held = Date.now() - p.at >= holdMs;
    if (p.wasListening || held) speech.stop(); // tap while listening = stop; hold = push-to-talk
  };

  const onClick = (e: ReactMouseEvent<HTMLElement>) => {
    if (e.detail !== 0) return; // real pointer clicks are handled above; detail 0 = keyboard
    if (speech.listening) speech.stop();
    else speech.start();
  };

  return {
    onPointerDown,
    onPointerUp,
    onPointerCancel: onPointerUp,
    onClick,
    onContextMenu: (e: ReactMouseEvent) => e.preventDefault(),
  };
}
