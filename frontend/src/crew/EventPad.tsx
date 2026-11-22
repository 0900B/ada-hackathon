import { useState } from "react";
import { useT, type TKey } from "../i18n";
import { EVENTS } from "./clinicalLog";
import { Sheet } from "./Sheet";

/** Stroke onset is the one event whose time matters: it asks how long ago it started. */
const ASKS_WHEN = "stroke_onset";
const MINUTES_AGO = [0, 5, 10, 15, 30, 60];

/**
 * One tap logs an event (cardiac arrest, ROSC, CPR started, ...). For stroke onset a second screen
 * asks how many minutes ago it started. `label` is the event's record name (English), whatever the
 * screen language is.
 */
export function EventPad({
  onSave,
  onClose,
}: {
  onSave: (key: string, label: string, minutesAgo: number) => void;
  onClose: () => void;
}) {
  const t = useT();
  const [asking, setAsking] = useState<{ key: string; label: string } | null>(null);

  if (asking) {
    return (
      <Sheet title={t(`pt.event.${asking.key}` as TKey)} onClose={onClose}>
        <h3 className="pt-pad-label">{t("pt.event.when")}</h3>
        <div className="pt-event-grid">
          {MINUTES_AGO.map((m) => (
            <button key={m} type="button" className="pt-event-btn" onClick={() => onSave(asking.key, asking.label, m)}>
              {m === 0 ? t("pt.tl.now") : t("pt.tl.ago", { min: m })}
            </button>
          ))}
        </div>
      </Sheet>
    );
  }

  return (
    <Sheet title={t("pt.event.title")} onClose={onClose}>
      <div className="pt-event-grid">
        {EVENTS.map((e) => (
          <button
            key={e.key}
            type="button"
            className="pt-event-btn"
            onClick={() => (e.key === ASKS_WHEN ? setAsking(e) : onSave(e.key, e.label, 0))}
          >
            {t(`pt.event.${e.key}` as TKey)}
          </button>
        ))}
      </div>
    </Sheet>
  );
}
