import { Check, CircleHelp, Radio, Send } from "lucide-react";
import type { AgentRun, MessageResult } from "../api";
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
          placeholder="Sporočilo dispečerju…"
          enterKeyHint="send"
          aria-label="Message to the dispatcher"
        />
        <button type="submit" className="primary" disabled={busy || draft.trim().length < 2}>
          <Send /> Send
        </button>
      </form>

      {(busy || result || error || direct) && (
        <section className="crew-card crew-response" aria-live="polite">
          {sent && <div className="crew-sent">“{sent}”</div>}
          {busy && (
            <div>
              <span className="spinner" /> AI is interpreting the message…
            </div>
          )}
          {error && <div className="message error">Not delivered: {error}</div>}
          {direct && (
            <>
              <div className="applied">
                <Check /> {direct}
              </div>
              <div className="crew-notified">
                <Radio /> Sent to dispatch as a status report (AI message reading unavailable)
              </div>
            </>
          )}
          {result && <MessageOutcome result={result} run={run} />}
        </section>
      )}

      <section className="crew-quick" aria-label="Quick status">
        {QUICK.map((q) => (
          <button key={q.key} type="button" disabled={busy} onClick={() => void send(q.sl, q.key)} title={`${q.sl} (key ${q.key})`}>
            <span className="q-icon">
              <q.icon />
            </span>
            <span className="q-text">
              <span>{q.sl}</span>
              <span className="muted">{q.en}</span>
            </span>
            <kbd>{q.key}</kbd>
          </button>
        ))}
      </section>
    </>
  );
}

const RUN_STATUS: Record<AgentRun["status"], string> = {
  running: "AI is replanning…",
  done: "New plan proposed: waiting for the dispatcher's approval",
  approved: "Dispatcher approved the new plan",
  rejected: "Dispatcher rejected the proposal",
  superseded: "Replaced by a newer analysis",
  error: "AI analysis failed; the dispatcher decides manually",
};

function MessageOutcome({ result, run }: { result: MessageResult; run: AgentRun | undefined }) {
  return (
    <>
      <div>
        <span className="lang-tag">SL</span>
        {result.understood_sl}
      </div>
      <div className="muted">
        <span className="lang-tag">EN</span>
        {result.understood_en}
      </div>
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
          <Radio /> Dispatcher notified{result.run_id || run?.status === "running" ? ": AI is replanning" : ""}
          {run && (
            <div className={`crew-run run-${run.status}`}>
              {run.status === "running" && <span className="spinner" />} {RUN_STATUS[run.status]}
              {run.status === "approved" && run.decision?.title ? `: ${run.decision.title}` : ""}
            </div>
          )}
        </div>
      ) : result.applied.length > 0 ? (
        <div className="crew-notified">
          <Radio /> Dispatcher notified
        </div>
      ) : (
        !result.error && <div className="muted">Nothing changed in the plan.</div>
      )}
    </>
  );
}
