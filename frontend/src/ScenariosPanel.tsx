import { useState } from "react";
import { CalendarClock, PhoneIncoming, RotateCcw } from "lucide-react";
import { resetWorld, runScenario, SCENARIOS, setCalls, type WorldSnapshot } from "./api";
import { fmtTime } from "./format";

type Notify = (kind: "ok" | "error", text: string, sticky?: boolean) => void;

const PREP = "equipment_en_route";

/** Simulation only: operations mode and call stream, one-click demo scenarios, reset. */
export function ScenariosPanel({ state, notify }: { state: WorldSnapshot; notify: Notify }) {
  const world = state.world;
  const [running, setRunning] = useState<string | null>(null);
  const mode = state.mode ?? "live_calls";
  const calls = state.calls;

  const act = async (key: string, fn: () => Promise<string>, sticky = false) => {
    setRunning(key);
    try {
      notify("ok", await fn(), sticky);
    } catch (e) {
      notify("error", e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(null);
    }
  };

  const start = (name: string) =>
    act(
      name,
      async () => {
        const r = await runScenario(name);
        return r.note ?? `Scenario started: ${r.title}`;
      },
      name === PREP, // the prep note says which vehicle to open on the phone: keep it up until closed
    );

  const switchMode = (scheduledDay: boolean) =>
    act("mode", async () => {
      await resetWorld(world, scheduledDay);
      return scheduledDay
        ? "Simulation reset to a scheduled day: the vans have the day's pre-planned transports"
        : "Simulation reset to live calls: all units at base, calls come in and are dispatched at once";
    });

  const toggleCalls = () =>
    act("calls", async () => {
      const r = await setCalls(world, { enabled: !(calls?.enabled ?? true) });
      return r.enabled ? `Call stream on (${r.per_hour} calls per hour)` : "Call stream off";
    });

  const reset = () =>
    act("reset", async () => {
      await resetWorld(world);
      return "Simulation reset";
    });

  const callsLine = !calls
    ? null
    : mode === "scheduled_day"
      ? "No call stream in scheduled-day mode"
      : !calls.enabled
        ? "Call stream off"
        : calls.paused_until
          ? `Paused for the scenario until ${fmtTime(calls.paused_until)} · ${calls.generated} calls so far`
          : `${calls.per_hour} calls per hour${calls.next_at ? ` · next ${fmtTime(calls.next_at)}` : ""} · ${calls.generated} so far`;

  const prep = SCENARIOS.find((s) => s.name === PREP);
  return (
    <div className="scenarios">
      <div className="field-label">Operations</div>
      <div className="ops-mode">
        <span className="lang-toggle" role="group" aria-label="Operations mode">
          <button
            type="button"
            aria-pressed={mode === "live_calls"}
            disabled={running !== null}
            title="No pre-planned day: calls come in and are dispatched at once (resets the simulation)"
            onClick={() => mode !== "live_calls" && switchMode(false)}
          >
            <PhoneIncoming /> Live calls
          </button>
          <button
            type="button"
            aria-pressed={mode === "scheduled_day"}
            disabled={running !== null}
            title="The brief's initial plan: the vans start with the day's pre-planned transports (resets the simulation)"
            onClick={() => mode !== "scheduled_day" && switchMode(true)}
          >
            <CalendarClock /> Scheduled day
          </button>
        </span>
        {mode === "live_calls" && calls && (
          <label className="switch" title="Generate incoming calls in this world">
            <input type="checkbox" role="switch" checked={calls.enabled} disabled={running !== null} onChange={toggleCalls} />
            <span className="switch-track" aria-hidden />
            Call stream {calls.enabled ? "on" : "off"}
          </label>
        )}
      </div>
      {callsLine && <div className="muted ops-calls">{callsLine}</div>}

      {prep && (
        <button className="scenario scenario-prep" disabled={running !== null} onClick={() => start(prep.name)}>
          <span className="scenario-label">{running === prep.name ? "Preparing…" : prep.label}</span>
          <span className="scenario-desc">{prep.title}</span>
        </button>
      )}
      <div className="field-label">Demo scenarios · resets and stages the situation; press Analyse for the AI's options</div>
      <div className="scenario-grid">
        {SCENARIOS.filter((s) => s.name !== PREP).map((s) => (
          <button key={s.name} className="scenario" disabled={running !== null} onClick={() => start(s.name)}>
            <span className="scenario-label">{running === s.name ? "Starting…" : s.label}</span>
            <span className="scenario-desc">{s.title}</span>
          </button>
        ))}
      </div>
      <button className="ghost" disabled={running !== null} onClick={reset}>
        <RotateCcw /> Reset simulation
      </button>
    </div>
  );
}
