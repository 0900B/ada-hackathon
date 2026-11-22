import type { ReactNode } from "react";
import { useState } from "react";
import { CalendarClock, PhoneIncoming, RotateCcw } from "lucide-react";
import { resetWorld, runScenario, SCENARIOS, setCalls, type WorldSnapshot } from "./api";
import { fmtTime } from "./format";
import { tOr, useT } from "./i18n";

type Notify = (kind: "ok" | "error", text: string, sticky?: boolean) => void;

const PREP = "equipment_en_route";

/** A demo scenario's button label and description in the UI language (api.ts SCENARIOS are English). */
const scenarioLabel = (s: { name: string; label: string }) => tOr(`dash.scn.${s.name}`, s.label);
const scenarioTitle = (s: { name: string; title: string }) => tOr(`dash.scn.${s.name}.title`, s.title);

/** Simulation only: operations mode and call stream, one-click demo scenarios, reset. */
export function ScenariosPanel({ state, notify, extra }: { state: WorldSnapshot; notify: Notify; extra?: ReactNode }) {
  const t = useT();
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
        return r.note ?? t("dash.sc.started", { title: r.title }); // the note and the title come from the backend
      },
      name === PREP, // the prep note says which vehicle to open on the phone: keep it up until closed
    );

  const switchMode = (scheduledDay: boolean) =>
    act("mode", async () => {
      await resetWorld(world, scheduledDay);
      return scheduledDay ? t("dash.sc.resetScheduled") : t("dash.sc.resetLive");
    });

  const toggleCalls = () =>
    act("calls", async () => {
      const r = await setCalls(world, { enabled: !(calls?.enabled ?? true) });
      return r.enabled ? t("dash.sc.streamOnToast", { count: r.per_hour }) : t("dash.calls.off");
    });

  const reset = () =>
    act("reset", async () => {
      await resetWorld(world);
      return t("dash.sc.reset");
    });

  const callsLine = !calls
    ? null
    : mode === "scheduled_day"
      ? t("dash.sc.noStream")
      : !calls.enabled
        ? null // the switch right above already says "Call stream off"
        : calls.paused_until
          ? t("dash.sc.paused", { time: fmtTime(calls.paused_until), count: calls.generated })
          : `${t("dash.sc.perHour", { count: calls.per_hour })}${calls.next_at ? t("dash.sc.next", { time: fmtTime(calls.next_at) }) : ""}${t("dash.sc.soFar", { count: calls.generated })}`;

  const prep = SCENARIOS.find((s) => s.name === PREP);
  return (
    <div className="scenarios">
      <div className="field-label">{t("dash.sc.operations")}</div>
      <div className="ops-mode">
        <span className="lang-toggle" role="group" aria-label={t("dash.sc.modeAria")}>
          <button
            type="button"
            aria-pressed={mode === "live_calls"}
            disabled={running !== null}
            title={t("dash.sc.liveTitle")}
            onClick={() => mode !== "live_calls" && switchMode(false)}
          >
            <PhoneIncoming /> {t("dash.sc.liveCalls")}
          </button>
          <button
            type="button"
            aria-pressed={mode === "scheduled_day"}
            disabled={running !== null}
            title={t("dash.sc.scheduledTitle")}
            onClick={() => mode !== "scheduled_day" && switchMode(true)}
          >
            <CalendarClock /> {t("dash.sc.scheduledDay")}
          </button>
        </span>
        {mode === "live_calls" && calls && (
          <label className="switch" title={t("dash.sc.streamTitle")}>
            <input type="checkbox" role="switch" checked={calls.enabled} disabled={running !== null} onChange={toggleCalls} />
            <span className="switch-track" aria-hidden />
            {calls.enabled ? t("dash.sc.streamOn") : t("dash.sc.streamOff")}
          </label>
        )}
      </div>
      {callsLine && <div className="muted ops-calls">{callsLine}</div>}
      {extra}

      {prep && (
        <button className="scenario scenario-prep" disabled={running !== null} onClick={() => start(prep.name)}>
          <span className="scenario-label">{running === prep.name ? t("dash.sc.preparing") : scenarioLabel(prep)}</span>
          <span className="scenario-desc">{scenarioTitle(prep)}</span>
        </button>
      )}
      <div className="field-label">{t("dash.sc.demoHeader")}</div>
      <div className="scenario-grid">
        {SCENARIOS.filter((s) => s.name !== PREP).map((s) => (
          <button key={s.name} className="scenario" disabled={running !== null} onClick={() => start(s.name)}>
            <span className="scenario-label">{running === s.name ? t("dash.sc.starting") : scenarioLabel(s)}</span>
            <span className="scenario-desc">{scenarioTitle(s)}</span>
          </button>
        ))}
      </div>
      <button className="ghost" disabled={running !== null} onClick={reset}>
        <RotateCcw /> {t("dash.sc.resetButton")}
      </button>
    </div>
  );
}
