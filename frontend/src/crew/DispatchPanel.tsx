import { Check, CircleHelp, Radio, Send } from "lucide-react";
import type { AgentRun, MessageResult } from "../api";
import { ErrorText } from "../ErrorText";
import { useLang, useT } from "../i18n";
import { QUICK, type useDispatch } from "./useDispatch";

export function DispatchPanel({
  dispatch,
  draft,
  setDraft,
}: {
  dispatch: ReturnType<typeof useDispatch>;
  draft: string;
  setDraft: (s: string) => void;
}) {
  const t = useT();
  const lang = useLang();
  const { busy, sent, result, error, direct, run, send } = dispatch;
  return (
    <>
      <form
        className="crew-form"
        onSubmit={(e) => {
          e.preventDefault();
          void send(draft).then((ok) => ok && setDraft(""));
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t("tab.msgPlaceholder")}
          enterKeyHint="send"
          aria-label={t("crew.msgAria")}
        />
        <button type="submit" className="primary" disabled={busy || draft.trim().length < 2}>
          <Send /> {t("tab.send")}
        </button>
      </form>

      {(busy || result || error || direct) && (
        <section className="crew-card crew-response" aria-live="polite">
          {sent && <div className="crew-sent">{t("crew.quoted", { text: sent })}</div>}
          {busy && (
            <div>
              <span className="spinner" /> {t("crew.interpreting")}
            </div>
          )}
          {error && (
            <div className="message error">
              {t("crew.notDelivered")} <ErrorText text={error} />
            </div>
          )}
          {direct && (
            <>
              <div className="applied">
                <Check /> {direct}
              </div>
              <div className="crew-notified">
                <Radio /> {t("crew.sentDirect")}
              </div>
            </>
          )}
          {result && <MessageOutcome result={result} run={run} />}
        </section>
      )}

      {/* The quick reports are always SENT in Slovenian (what the AI message reader expects); the
          button shows the UI language first and the other one under it */}
      <section className="crew-quick" aria-label={t("crew.quickAria")}>
        {QUICK.map((q) => (
          <button
            key={q.key}
            type="button"
            disabled={busy}
            onClick={() => void send(q.sl, q.key)}
            title={t("crew.keyTitle", { text: q.sl, key: q.key })}
          >
            <span className="q-icon">
              <q.icon />
            </span>
            <span className="q-text">
              <span lang={lang === "sl" ? "sl" : "en"}>{lang === "sl" ? q.sl : q.en}</span>
              <span className="muted" lang={lang === "sl" ? "en" : "sl"}>
                {lang === "sl" ? q.en : q.sl}
              </span>
            </span>
            <kbd>{q.key}</kbd>
          </button>
        ))}
      </section>
    </>
  );
}

function MessageOutcome({ result, run }: { result: MessageResult; run: AgentRun | undefined }) {
  const t = useT();
  const lang = useLang();
  // What the AI understood, in both languages (the backend sends both): the UI language first
  const sl = (
    <div key="sl" className={lang === "sl" ? undefined : "muted"}>
      <span className="lang-tag">SL</span>
      {result.understood_sl}
    </div>
  );
  const en = (
    <div key="en" className={lang === "sl" ? "muted" : undefined}>
      <span className="lang-tag">EN</span>
      {result.understood_en}
    </div>
  );
  return (
    <>
      {lang === "sl" ? [sl, en] : [en, sl]}
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
      {result.run_id || run ? (
        <div className="crew-notified">
          <Radio /> {result.run_id || run?.status === "running" ? t("crew.notifiedReplanning") : t("crew.notified")}
          {run && (
            <div className={`crew-run run-${run.status}`}>
              {run.status === "running" && <span className="spinner" />} {t(`crew.run.${run.status}`)}
              {run.status === "approved" && run.decision?.title ? `: ${run.decision.title}` : ""}
            </div>
          )}
        </div>
      ) : result.applied.length > 0 ? (
        <div className="crew-notified">
          <Radio /> {t("crew.notified")}
        </div>
      ) : (
        !result.error && <div className="muted">{t("crew.nothingChanged")}</div>
      )}
    </>
  );
}
