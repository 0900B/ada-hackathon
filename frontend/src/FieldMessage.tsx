import { useState } from "react";
import { sendFieldMessage, type MessageResult, type WorldSnapshot } from "./api";

/** Part 3 of the brief: a crew/dispatcher message in Slovenian (or English) -> events -> new plan. */
const EXAMPLES = [
  "Vozilo je obstalo. Oprema je še v njem.",
  "Zamujamo 20 minut, zastoj na obvoznici.",
  "Nujno: sum na možgansko kap v Polju, ležeči prevoz v UKC.",
  "Zaprta Zaloška cesta pri UKC zaradi nesreče.",
  "Megla na heliportu, helikopter ne more vzleteti.",
];

export function FieldMessage({ state }: { state: WorldSnapshot }) {
  const [text, setText] = useState("");
  const [sender, setSender] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<MessageResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await sendFieldMessage(state.world, text.trim(), sender || null));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="field-message">
      <div className="row">
        <select value={sender} onChange={(e) => setSender(e.target.value)} title="Who is sending the message">
          <option value="">From: dispatcher</option>
          {state.vehicles.map((v) => (
            <option key={v.id} value={v.id}>
              From: {v.id} crew
            </option>
          ))}
        </select>
      </div>
      <textarea
        rows={2}
        placeholder="Sporočilo s terena (SL/EN), npr. »Vozilo je obstalo. Oprema je še v njem.«"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && text.trim().length > 1) void submit();
        }}
      />
      <div className="examples">
        {EXAMPLES.map((ex) => (
          <button key={ex} className="example" onClick={() => setText(ex)} title="Use this example">
            {ex}
          </button>
        ))}
      </div>
      <button className="primary" disabled={busy || text.trim().length < 2} onClick={submit}>
        {busy ? "Interpreting…" : "Send to AI (Ctrl+Enter)"}
      </button>
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
          {result.run_id && <div className="muted">The AI dispatcher is replanning ({result.run_id})…</div>}
        </div>
      )}
    </div>
  );
}
