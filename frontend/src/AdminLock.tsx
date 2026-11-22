import { useEffect, useRef, useState } from "react";
import { Lock, LockOpen } from "lucide-react";
import { checkAdminKey, fetchAdminLock } from "./api";
import {
  KEY_REJECTED_MESSAGE,
  clearAdminKey,
  getPromptNote,
  setAdminKey,
  useAdminKey,
  usePromptRequest,
  validKey,
} from "./adminKey";
import "./adminlock.css";

type Variant = "header" | "tablet" | "crew";

/**
 * The demo lock's indicator: "Control unlocked" (this device holds the admin key) or "View only", with
 * a click to enter or clear the key in a small inline prompt. The prompt also opens by itself when a
 * control action gets a 401 (adminKey.ts: controlFetch). When the backend has no ADMIN_KEY at all, the
 * chip says "No lock set" so a forgotten Railway variable shows before the pitch, not during it.
 * Same component on the dashboard header, the in-vehicle tablet and the crew phone.
 */
export function AdminLock({ variant = "header" }: { variant?: Variant }) {
  const key = useAdminKey();
  const promptSeq = usePromptRequest();
  const [backendLock, setBackendLock] = useState<boolean | null>(null); // does the backend have an ADMIN_KEY? null: unknown
  const [rejected, setRejected] = useState(false); // the stored key failed the backend's check
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [top, setTop] = useState(52);
  const button = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLFormElement>(null);
  const seen = useRef(promptSeq);

  const openPrompt = (why: string) => {
    const r = button.current?.getBoundingClientRect();
    if (r) setTop(Math.round(r.bottom + 6));
    setNote(why);
    setDraft("");
    setError("");
    setOpen(true);
  };

  useEffect(() => {
    let stop = false;
    void fetchAdminLock().then((v) => !stop && setBackendLock(v));
    return () => {
      stop = true;
    };
  }, []);

  // The stored key (from ?key= or typed earlier) is checked once against the backend: a typo must show
  // here, on our device, not on stage.
  useEffect(() => {
    setRejected(false);
    if (!key) return;
    let stop = false;
    void checkAdminKey(key).then((v) => {
      if (stop || v !== "rejected") return;
      setRejected(true);
      openPrompt(KEY_REJECTED_MESSAGE);
    });
    return () => {
      stop = true;
    };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  // A 401 somewhere (adminKey.ts: controlFetch) asks for the prompt
  useEffect(() => {
    if (promptSeq === seen.current) return;
    seen.current = promptSeq;
    setBackendLock(true);
    if (key) setRejected(true);
    openPrompt(getPromptNote());
  }, [promptSeq]); // eslint-disable-line react-hooks/exhaustive-deps

  // Click outside or Escape closes the prompt
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!pop.current?.contains(t) && !button.current?.contains(t)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const submit = async () => {
    const k = draft.trim();
    if (!k || busy) return;
    if (!validKey(k)) {
      setError("A key has no spaces or special characters.");
      return;
    }
    setBusy(true);
    setError("");
    const verdict = await checkAdminKey(k);
    setBusy(false);
    if (verdict === "rejected") {
      setError("That key was not accepted.");
      return;
    }
    setRejected(false);
    setAdminKey(k); // "unknown" (backend unreachable) is kept too: the check repeats on the next load
    setOpen(false);
  };

  const noLock = backendLock === false;
  const state = noLock ? "nolock" : !key ? "view" : rejected ? "rejected" : "ok";
  const label = { nolock: "No lock set", view: "View only", rejected: "Key rejected", ok: "Control unlocked" }[state];
  const Icon = state === "ok" || state === "nolock" ? LockOpen : Lock;
  const title = {
    nolock: "The backend has no ADMIN_KEY: anyone with the link can control the demo.",
    view: "View only: control actions need the admin key. Click to enter it.",
    rejected: "The stored admin key was not accepted. Click to enter it again.",
    ok: "This device holds the admin key and can control the demo. Click to change or clear it.",
  }[state];

  return (
    <div className="adminlock" data-variant={variant}>
      <button
        ref={button}
        type="button"
        className={`adminlock-btn ${state}`}
        title={title}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => (open ? setOpen(false) : openPrompt(""))}
      >
        <Icon aria-hidden="true" />
        <span>{label}</span>
      </button>
      {open && (
        <form
          ref={pop}
          className="adminlock-pop"
          style={{ top }}
          role="dialog"
          aria-label="Admin key"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          {noLock ? (
            <>
              <p>The backend has no admin key set (ADMIN_KEY), so the controls are open to anyone with the link.</p>
              <div className="adminlock-row">
                <button type="button" className="adminlock-act" onClick={() => setOpen(false)}>
                  Close
                </button>
              </div>
            </>
          ) : (
            <>
              <strong>{key ? "Admin key on this device" : "Admin key"}</strong>
              {note ? (
                <p className="adminlock-note">{note}</p>
              ) : (
                <p className="adminlock-help">
                  {key
                    ? "Enter another key to replace it, or clear it to go back to view only."
                    : "View only. Enter the admin key to reset, inject failures, approve plans and run the AI."}
                </p>
              )}
              <input
                type="password"
                className="adminlock-input"
                value={draft}
                onChange={(e) => {
                  setDraft(e.target.value);
                  setError("");
                }}
                placeholder="Admin key"
                aria-label="Admin key"
                autoComplete="off"
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
                autoFocus
              />
              {error && <p className="adminlock-error">{error}</p>}
              <div className="adminlock-row">
                <button type="submit" className="adminlock-act primary" disabled={busy || !draft.trim()}>
                  {busy ? "Checking…" : "Unlock"}
                </button>
                {key && (
                  <button
                    type="button"
                    className="adminlock-act"
                    onClick={() => {
                      clearAdminKey();
                      setOpen(false);
                    }}
                  >
                    Clear key
                  </button>
                )}
                <button type="button" className="adminlock-act" onClick={() => setOpen(false)}>
                  Close
                </button>
              </div>
            </>
          )}
        </form>
      )}
    </div>
  );
}
