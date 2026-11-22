import { useEffect, useRef, useState } from "react";
import { Lock, LockOpen } from "lucide-react";
import { checkAdminKey, fetchAdminLock } from "./api";
import { useT } from "./i18n";
import {
  keyRejectedMessage,
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
  const t = useT();
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
      openPrompt(keyRejectedMessage());
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
      setError(t("dash.lock.noSpaces"));
      return;
    }
    setBusy(true);
    setError("");
    const verdict = await checkAdminKey(k);
    setBusy(false);
    if (verdict === "rejected") {
      setError(t("dash.lock.notAccepted"));
      return;
    }
    setRejected(false);
    setAdminKey(k); // "unknown" (backend unreachable) is kept too: the check repeats on the next load
    setOpen(false);
  };

  const noLock = backendLock === false;
  const state = noLock ? "nolock" : !key ? "view" : rejected ? "rejected" : "ok";
  const label = { nolock: t("dash.lock.nolock"), view: t("dash.lock.view"), rejected: t("dash.lock.rejected"), ok: t("dash.lock.ok") }[state];
  const Icon = state === "ok" || state === "nolock" ? LockOpen : Lock;
  const title = {
    nolock: t("dash.lock.titleNolock"),
    view: t("dash.lock.titleView"),
    rejected: t("dash.lock.titleRejected"),
    ok: t("dash.lock.titleOk"),
  }[state];

  // No lock on the backend (ADMIN_KEY not set): everything is open, so there is nothing to show
  if (noLock) return null;

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
          aria-label={t("dash.lock.adminKey")}
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          {noLock ? (
            <>
              <p>{t("dash.lock.noLockText")}</p>
              <div className="adminlock-row">
                <button type="button" className="adminlock-act" onClick={() => setOpen(false)}>
                  {t("common.close")}
                </button>
              </div>
            </>
          ) : (
            <>
              <strong>{key ? t("dash.lock.onDevice") : t("dash.lock.adminKey")}</strong>
              {note ? (
                <p className="adminlock-note">{note}</p>
              ) : (
                <p className="adminlock-help">{key ? t("dash.lock.helpReplace") : t("dash.lock.helpView")}</p>
              )}
              <input
                type="password"
                className="adminlock-input"
                value={draft}
                onChange={(e) => {
                  setDraft(e.target.value);
                  setError("");
                }}
                placeholder={t("dash.lock.adminKey")}
                aria-label={t("dash.lock.adminKey")}
                autoComplete="off"
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
                autoFocus
              />
              {error && <p className="adminlock-error">{error}</p>}
              <div className="adminlock-row">
                <button type="submit" className="adminlock-act primary" disabled={busy || !draft.trim()}>
                  {busy ? t("dash.lock.checking") : t("dash.lock.unlock")}
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
                    {t("dash.lock.clear")}
                  </button>
                )}
                <button type="button" className="adminlock-act" onClick={() => setOpen(false)}>
                  {t("common.close")}
                </button>
              </div>
            </>
          )}
        </form>
      )}
    </div>
  );
}
