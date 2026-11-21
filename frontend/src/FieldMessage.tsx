import { useEffect, useState } from "react";
import { sendFieldMessage, type MessageResult, type WorldSnapshot } from "./api";
import { SPEECH_LANGS, speechSecureContext, usePushToTalk, useSpeechInput } from "./voice";
import "./voice.css";

/** Part 3 of the brief: a crew/dispatcher message in Slovenian (or English) -> events -> new plan. */
const EXAMPLES = [
  "Vozilo je obstalo. Oprema je še v njem.",
  "Zamujamo 20 minut, zastoj na obvoznici.",
  "Nujno: sum na možgansko kap v Polju, ležeči prevoz v UKC.",
  "Zaprta Zaloška cesta v Mostah zaradi nesreče.",
  "Megla na heliportu, helikopter ne more vzleteti.",
];

/**
 * Hotkey hook-up: pass `micToggleRef` (from `useRef<(() => void) | null>(null)`); while this box is
 * mounted, `micToggleRef.current()` toggles the microphone (the dashboard binds it to M).
 */
export function FieldMessage({
  state,
  micToggleRef,
}: {
  state: WorldSnapshot;
  micToggleRef?: { current: (() => void) | null };
}) {
  const [text, setText] = useState("");
  const [sender, setSender] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<MessageResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [autoSend, setAutoSend] = useState(true);

  const submit = async (body: string = text) => {
    const msg = body.trim();
    if (msg.length < 2) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await sendFieldMessage(state.world, msg, sender || null));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const speech = useSpeechInput({
    onFinal: (heard) => {
      setText(heard);
      if (autoSend && !busy) void submit(heard);
    },
  });
  const ptt = usePushToTalk(speech);

  useEffect(() => {
    if (!micToggleRef) return;
    const toggle = speech.toggle;
    micToggleRef.current = toggle;
    return () => {
      if (micToggleRef.current === toggle) micToggleRef.current = null;
    };
  }, [micToggleRef, speech.toggle]);

  return (
    <section className="panel panel-field">
      <div className="panel-head">
        <h2 className="panel-title">Message from the field</h2>
        <select className="sender" value={sender} onChange={(e) => setSender(e.target.value)} title="Who is sending the message" aria-label="Sender">
          <option value="">From: dispatcher</option>
          {state.vehicles.map((v) => (
            <option key={v.id} value={v.id}>
              From: {v.id} crew
            </option>
          ))}
        </select>
      </div>
      <div className="field-message">
        <textarea
          rows={2}
          placeholder="Sporočilo s terena (SL/EN), npr. »Vozilo je obstalo. Oprema je še v njem.« · Ctrl+Enter pošlje"
          aria-label="Field message"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && text.trim().length > 1) void submit();
          }}
        />
        {speech.listening && <div className="voice-interim">{speech.interim || "Listening… speak now"}</div>}
        <div className="fm-actions">
          {speech.supported && (
            <>
              <button
                type="button"
                className={`mic-btn${speech.listening ? " listening" : ""}`}
                title="Click to start/stop, or hold to talk and release (hotkey M)"
                aria-pressed={speech.listening}
                {...ptt}
              >
                🎤 {speech.listening ? "Listening…" : "Speak"}
              </button>
              <span className="lang-toggle" role="group" aria-label="Speech language">
                {SPEECH_LANGS.map((l) => (
                  <button
                    key={l.code}
                    type="button"
                    aria-pressed={speech.lang === l.code}
                    onClick={() => speech.setLang(l.code)}
                    title={`Recognise ${l.code}`}
                  >
                    {l.label}
                  </button>
                ))}
              </span>
            </>
          )}
          <select
            className="examples-pick"
            aria-label="Insert an example message"
            value=""
            onChange={(e) => e.target.value && setText(e.target.value)}
          >
            <option value="">Example…</option>
            {EXAMPLES.map((ex) => (
              <option key={ex} value={ex}>
                {ex}
              </option>
            ))}
          </select>
          <button className="primary send" disabled={busy || text.trim().length < 2} onClick={() => void submit()} title="Ctrl+Enter">
            {busy ? "Interpreting…" : "Send to AI"}
          </button>
        </div>
        {speech.supported ? (
          <label className="auto-send" title="Send to the AI as soon as you stop speaking">
            <input type="checkbox" checked={autoSend} onChange={(e) => setAutoSend(e.target.checked)} />
            send automatically after speaking
            {!speechSecureContext() && <span className="warn-text"> · voice needs HTTPS (or localhost)</span>}
          </label>
        ) : (
          <p className="muted small">🎤 Voice input needs Chrome or Edge.</p>
        )}
        {speech.error && <div className="message error">{speech.error}</div>}
        {error && <div className="message error">{error}</div>}
        {result && (
          <div className="parsed">
            <div>🇸🇮 {result.understood_sl}</div>
            <div className="muted">🇬🇧 {result.understood_en}</div>
            {result.needs_clarification && <div className="warn-box">❓ {result.needs_clarification}</div>}
            {result.applied.map((a) => (
              <div key={a.id} className="applied">
                ✓ {a.summary}
              </div>
            ))}
            {result.error && <div className="message error">{result.error}</div>}
            {result.run_id ? (
              <div className="muted">The AI dispatcher is replanning ({result.run_id})…</div>
            ) : (
              result.applied.length > 0 && !state.agent.auto && <div className="muted">Applied. Press A to analyse.</div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
