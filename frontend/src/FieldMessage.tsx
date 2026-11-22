import { useEffect, useState } from "react";
import { Check, Mic, Send, CircleHelp } from "lucide-react";
import { sendFieldMessage, type MessageResult, type WorldSnapshot } from "./api";
import { SPEECH_LANGS, speechSecureContext, usePushToTalk, useSpeechInput } from "./voice";
import "./voice.css";
import { ErrorText } from "./ErrorText";
import { useLang, useT } from "./i18n";

/** Part 3 of the brief: a crew/dispatcher message in Slovenian (or English) -> events -> new plan. */
const EXAMPLES = [
  "Vozilo je obstalo. Oprema je še v njem.",
  "Zamujamo 20 minut, zastoj na obvoznici.",
  "Nujno: sum na možgansko kap v Polju, ležeči prevoz v UKC.",
  "Zaprta Zaloška cesta v Mostah zaradi nesreče.",
  "Megla na heliportu, helikopter ne more vzleteti.",
  // From the field-message catalogue (docs/SURGE_EVENTS.md §4, Metelko): numbers as words, locatives
  "Zaradi kolone zamujamo približno petindvajset minut.",
  "Stojimo za zaledenelim tovornjakom, še dvajset minut.",
  "Cesta proti Vrhniki je zaprta, ne moremo mimo.",
  "Klic: padec na ledu v Šiški, sum na zlom kolka.",
  "Še en nujen klic: bolečina v prsih v Črnučah.",
  "Sneži, ceste so spolzke, vozimo počasneje.",
];

/**
 * Hotkey hook-up: pass `micToggleRef` (from `useRef<(() => void) | null>(null)`); while this box is
 * mounted, `micToggleRef.current()` toggles the microphone (the dashboard binds it to M).
 */
export function FieldMessage({
  state,
  micToggleRef,
  bare = false,
  onListening,
}: {
  state: WorldSnapshot;
  micToggleRef?: { current: (() => void) | null };
  bare?: boolean; // inside another section (the AI dispatcher tab): no panel frame or title of its own
  onListening?: (listening: boolean) => void;
}) {
  const t = useT();
  const lang = useLang();
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

  useEffect(() => {
    onListening?.(speech.listening);
  }, [speech.listening]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <section className={bare ? "panel-field bare" : "panel panel-field"}>
      <div className="panel-head">
        {bare ? (
          <span className="muted small fm-hint">{t("ai.fm.hint")}</span>
        ) : (
          <h2 className="panel-title">{t("ai.message")}</h2>
        )}
        <select className="sender" value={sender} onChange={(e) => setSender(e.target.value)} title={t("ai.fm.senderTitle")} aria-label={t("ai.fm.sender")}>
          <option value="">{t("ai.fm.fromDispatcher")}</option>
          {state.vehicles.map((v) => (
            <option key={v.id} value={v.id}>
              {t("ai.fm.fromCrew", { id: v.id })}
            </option>
          ))}
        </select>
      </div>
      <div className="field-message">
        <textarea
          rows={2}
          placeholder={t("ai.fm.placeholder")}
          aria-label={t("ai.fm.aria")}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && text.trim().length > 1) void submit();
          }}
        />
        {speech.listening && <div className="voice-interim">{speech.interim || t("ai.fm.speakNow")}</div>}
        <div className="fm-actions">
          {speech.supported && (
            <>
              <button
                type="button"
                className={`mic-btn${speech.listening ? " listening" : ""}`}
                title={t("ai.fm.micTitle")}
                aria-pressed={speech.listening}
                {...ptt}
              >
                <Mic /> {speech.listening ? t("ai.listening") : t("ai.fm.speak")}
              </button>
              <span className="lang-toggle" role="group" aria-label={t("ai.fm.speechLang")}>
                {SPEECH_LANGS.map((l) => (
                  <button
                    key={l.code}
                    type="button"
                    aria-pressed={speech.lang === l.code}
                    onClick={() => speech.setLang(l.code)}
                    title={t("ai.fm.recognise", { code: l.code })}
                  >
                    {l.label}
                  </button>
                ))}
              </span>
            </>
          )}
          <select
            className="examples-pick"
            aria-label={t("ai.fm.exampleAria")}
            value=""
            onChange={(e) => e.target.value && setText(e.target.value)}
          >
            <option value="">{t("ai.fm.example")}</option>
            {EXAMPLES.map((ex) => (
              <option key={ex} value={ex}>
                {ex}
              </option>
            ))}
          </select>
          <button className="primary send" disabled={busy || text.trim().length < 2} onClick={() => void submit()} title="Ctrl+Enter">
            <Send /> {busy ? t("ai.fm.interpreting") : t("ai.fm.send")}
          </button>
        </div>
        {speech.supported ? (
          <label className="auto-send" title={t("ai.fm.autoTitle")}>
            <input type="checkbox" checked={autoSend} onChange={(e) => setAutoSend(e.target.checked)} />
            {t("ai.fm.auto")}
            {!speechSecureContext() && <span className="warn-text">{t("ai.fm.https")}</span>}
          </label>
        ) : (
          <p className="muted small">{t("ai.fm.needsChrome")}</p>
        )}
        {speech.error && <div className="message error">{speech.error}</div>}
        {error && (
          <div className="message error">
            <ErrorText text={error} />
          </div>
        )}
        {result && (
          <div className="parsed">
            {/* What the AI understood, in both languages: the UI language first */}
            {(lang === "sl"
              ? [
                  ["SL", result.understood_sl],
                  ["EN", result.understood_en],
                ]
              : [
                  ["EN", result.understood_en],
                  ["SL", result.understood_sl],
                ]
            ).map(([tag, text], i) => (
              <div key={tag} className={i > 0 ? "muted" : undefined}>
                <span className="lang-tag">{tag}</span>
                {text}
              </div>
            ))}
            {result.needs_clarification && (
              <div className="warn-box">
                <CircleHelp /> <span>{result.needs_clarification}</span>
              </div>
            )}
            {result.applied.map((a) => (
              <div key={a.id} className="applied">
                <Check /> {a.summary}
              </div>
            ))}
            {result.error && <div className="message error">{result.error}</div>}
            {result.run_id ? (
              <div className="muted">{t("ai.fm.replanning", { id: result.run_id })}</div>
            ) : (
              result.applied.length > 0 && !state.agent.auto && <div className="muted">{t("ai.fm.applied")}</div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
