import { useState } from "react";
import { RotateCcw } from "lucide-react";
import { resetWorld, runScenario, SCENARIOS, type World } from "./api";

type Notify = (kind: "ok" | "error", text: string, sticky?: boolean) => void;

const PREP = "equipment_en_route";

/** Simulation only: one-click demo scenarios (reset + events + one AI analysis) and reset. */
export function ScenariosPanel({ world, notify }: { world: World; notify: Notify }) {
  const [running, setRunning] = useState<string | null>(null);

  const start = async (name: string) => {
    setRunning(name);
    try {
      const r = await runScenario(name);
      // The prep note says which vehicle to open on the phone: keep it up until closed
      notify("ok", r.note ?? `Scenario started: ${r.title}`, Boolean(r.note));
    } catch (e) {
      notify("error", e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(null);
    }
  };

  const reset = async () => {
    setRunning("reset");
    try {
      await resetWorld(world);
      notify("ok", "Simulation reset");
    } catch (e) {
      notify("error", e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(null);
    }
  };

  const prep = SCENARIOS.find((s) => s.name === PREP);
  return (
    <div className="scenarios">
      {prep && (
        <button className="scenario scenario-prep" disabled={running !== null} onClick={() => start(prep.name)}>
          <span className="scenario-label">{running === prep.name ? "Preparing…" : prep.label}</span>
          <span className="scenario-desc">{prep.title}</span>
        </button>
      )}
      <div className="field-label">Demo scenarios · reset, several events at once, one AI analysis</div>
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
