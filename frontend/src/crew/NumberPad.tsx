import { Delete } from "lucide-react";
import { useT } from "../i18n";
import { padKey } from "./padLogic";

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "back"];

/** Big keys for gloved hands: 0-9, a decimal point (when `allowDecimal`) and backspace. */
export function NumberPad({
  value,
  onChange,
  allowDecimal = false,
}: {
  value: string;
  onChange: (v: string) => void;
  allowDecimal?: boolean;
}) {
  const t = useT();
  return (
    <div className="pt-numpad" role="group" aria-label={t("pt.pad.keys")}>
      {KEYS.map((k) => (
        <button
          key={k}
          type="button"
          className="pt-numkey"
          disabled={k === "." && !allowDecimal}
          aria-label={k === "back" ? t("pt.pad.back") : undefined}
          onClick={() => onChange(padKey(value, k, allowDecimal))}
        >
          {k === "back" ? <Delete /> : k}
        </button>
      ))}
    </div>
  );
}
