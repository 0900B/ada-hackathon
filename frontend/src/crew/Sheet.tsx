import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";
import { useT } from "../i18n";

/**
 * A full-width sheet that rises from the bottom of the screen: the frame of the tap pads. It
 * closes with the Close button, a tap on the dim area or Escape; nothing is saved by closing.
 */
export function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const t = useT();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="pt-sheet-wrap"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section className="pt-sheet" role="dialog" aria-modal="true" aria-label={title}>
        <header className="pt-sheet-head">
          <h2>{title}</h2>
          <button type="button" className="pt-sheet-close" onClick={onClose}>
            <X /> {t("pt.pad.close")}
          </button>
        </header>
        <div className="pt-sheet-body">{children}</div>
      </section>
    </div>
  );
}
