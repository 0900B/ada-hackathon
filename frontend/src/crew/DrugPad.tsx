import { useState } from "react";
import { Check } from "lucide-react";
import { useT } from "../i18n";
import { DRUGS, ROUTES, UNITS } from "./clinicalLog";
import { NumberPad } from "./NumberPad";
import { Sheet } from "./Sheet";
import { canSaveDrug } from "./padLogic";

/**
 * Record a drug that was given: tap the drug (or "Other" and type its name), type the dose, tap the
 * unit and the route. Save stays off until all four are set. The dose is saved as typed.
 */
export function DrugPad({
  onSave,
  onClose,
}: {
  onSave: (c: { drug: string; dose: number; unit: string; route: string }) => void;
  onClose: () => void;
}) {
  const t = useT();
  const [drug, setDrug] = useState("");
  const [other, setOther] = useState(false);
  const [dose, setDose] = useState("");
  const [unit, setUnit] = useState("");
  const [route, setRoute] = useState("");
  const ready = canSaveDrug({ drug, dose, unit, route });

  const save = () => {
    if (!ready) return;
    onSave({ drug: drug.trim(), dose: Number(dose), unit, route });
  };

  return (
    <Sheet title={t("pt.drug.title")} onClose={onClose}>
      <div className="pt-pad-cols">
        <div className="pt-pad-left">
          <h3 className="pt-pad-label">{t("pt.drug.drug")}</h3>
          <div className="pt-chips">
            {DRUGS.map((d) => (
              <button
                key={d}
                type="button"
                className="pt-chip"
                aria-pressed={!other && drug === d}
                onClick={() => {
                  setOther(false);
                  setDrug(d);
                }}
              >
                {d}
              </button>
            ))}
            <button
              type="button"
              className="pt-chip"
              aria-pressed={other}
              onClick={() => {
                setOther(true);
                setDrug("");
              }}
            >
              {t("pt.drug.other")}
            </button>
          </div>
          {other && (
            <input
              className="pt-pad-text"
              value={drug}
              onChange={(e) => setDrug(e.target.value)}
              placeholder={t("pt.drug.otherPlaceholder")}
              aria-label={t("pt.drug.otherPlaceholder")}
              autoFocus
            />
          )}
          <h3 className="pt-pad-label">{t("pt.drug.unit")}</h3>
          <div className="pt-chips">
            {UNITS.map((u) => (
              <button key={u} type="button" className="pt-chip" aria-pressed={unit === u} onClick={() => setUnit(u)}>
                {u}
              </button>
            ))}
          </div>
          <h3 className="pt-pad-label">{t("pt.drug.route")}</h3>
          <div className="pt-chips">
            {ROUTES.map((r) => (
              <button key={r} type="button" className="pt-chip" aria-pressed={route === r} onClick={() => setRoute(r)}>
                {r}
              </button>
            ))}
          </div>
        </div>
        <div className="pt-pad-right">
          <h3 className="pt-pad-label">{t("pt.drug.dose")}</h3>
          <div className="pt-pad-display" aria-live="polite">
            <strong>{dose || "–"}</strong> <span>{unit}</span>
          </div>
          <NumberPad value={dose} onChange={setDose} allowDecimal />
          <button type="button" className="pt-pad-save" disabled={!ready} onClick={save}>
            <Check /> {t("pt.pad.save")}
          </button>
        </div>
      </div>
    </Sheet>
  );
}
