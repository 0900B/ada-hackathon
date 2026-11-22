import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import type { CaseCard, CaseDetailData, ErAlert, World } from "./api";
import { CaseDetail } from "./CaseDetail";
import { MapPanel } from "./MapPanel";

/**
 * The popup for one case: live map on one side, every piece of data on the other. Closes with the button,
 * Escape or a click on the dark background; focus moves into it on open and back to the tile on close.
 */
export function CaseModal({
  world,
  c,
  data,
  alerts,
  asOf,
  onClose,
  onChanged,
}: {
  world: World;
  c: CaseCard;
  data: CaseDetailData | null;
  alerts: ErAlert[];
  asOf: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const closeBtn = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    closeBtn.current?.focus();
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden"; // the page behind must not scroll
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      opener?.focus?.();
    };
  }, [onClose]);

  return (
    <div
      className="backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-label={`Case ${c.case_id}`}>
        <button ref={closeBtn} type="button" className="modal-close" onClick={onClose} aria-label="Close">
          <X size={20} aria-hidden />
        </button>
        <div className="modal-body">
          <MapPanel world={world} c={c} />
          <CaseDetail world={world} c={c} data={data} alerts={alerts} asOf={asOf} onChanged={onChanged} />
        </div>
      </div>
    </div>
  );
}
