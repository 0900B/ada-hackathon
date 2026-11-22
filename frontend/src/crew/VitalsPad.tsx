import { useState } from "react";
import { Check, ChevronRight } from "lucide-react";
import { useT, type TKey } from "../i18n";
import type { VitalKey } from "./clinicalLog";
import { NumberPad } from "./NumberPad";
import { Sheet } from "./Sheet";
import { VITAL_KEYS, vitalsContent } from "./padLogic";

/** What each vital is measured in (shown next to the value; not translated). */
const UNIT: Record<VitalKey, string> = { sbp: "mmHg", dbp: "mmHg", spo2: "%", hr: "/min", rr: "/min", temp: "°C", glucose: "mmol/l", gcs: "" };
const DECIMAL: Record<VitalKey, boolean> = { sbp: false, dbp: false, spo2: false, hr: false, rr: false, temp: true, glucose: true, gcs: false };

/**
 * Enter vitals one at a time: tap a field, type the number. Every field is optional; Save needs at
 * least one. A value is saved exactly as typed (an implausible one is marked in the log, not changed).
 */
export function VitalsPad({ onSave, onClose }: { onSave: (c: Record<string, number>) => void; onClose: () => void }) {
  const t = useT();
  const [fields, setFields] = useState<Partial<Record<VitalKey, string>>>({});
  const [current, setCurrent] = useState<VitalKey>("sbp");
  const content = vitalsContent(fields);
  const ready = Object.keys(content).length > 0;
  const next = VITAL_KEYS[(VITAL_KEYS.indexOf(current) + 1) % VITAL_KEYS.length];

  return (
    <Sheet title={t("pt.vitals.title")} onClose={onClose}>
      <div className="pt-pad-cols">
        <div className="pt-pad-left">
          <p className="pt-pad-hint">{t("pt.vitals.hint")}</p>
          <div className="pt-vfields">
            {VITAL_KEYS.map((k) => (
              <button key={k} type="button" className="pt-vfield" aria-pressed={current === k} onClick={() => setCurrent(k)}>
                <span className="pt-vfield-name">{t(`pt.vital.${k}` as TKey)}</span>
                <span className="pt-vfield-val">
                  <strong>{fields[k] || "–"}</strong> {UNIT[k] && <span>{UNIT[k]}</span>}
                </span>
              </button>
            ))}
          </div>
        </div>
        <div className="pt-pad-right">
          <h3 className="pt-pad-label">{t(`pt.vital.${current}` as TKey)}</h3>
          <div className="pt-pad-display" aria-live="polite">
            <strong>{fields[current] || "–"}</strong> <span>{UNIT[current]}</span>
          </div>
          <NumberPad
            value={fields[current] ?? ""}
            onChange={(v) => setFields((f) => ({ ...f, [current]: v }))}
            allowDecimal={DECIMAL[current]}
          />
          <div className="pt-pad-actions">
            <button type="button" className="pt-pad-next" onClick={() => setCurrent(next)}>
              {t("pt.pad.next")} <ChevronRight />
            </button>
            <button type="button" className="pt-pad-save" disabled={!ready} onClick={() => onSave(content)}>
              <Check /> {t("pt.pad.save")}
            </button>
          </div>
        </div>
      </div>
    </Sheet>
  );
}
