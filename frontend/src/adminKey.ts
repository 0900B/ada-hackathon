/**
 * The demo lock, client side. With ADMIN_KEY set on the backend, every POST/PUT/PATCH/DELETE must
 * carry `X-Plan-B-Key: <key>` (backend/app/admin_key.py); reading stays open. The key lives only on
 * our own devices: open the page once with `?key=…` (captureKeyFromUrl, called from main.tsx before
 * anything renders) and it is kept in localStorage (`planb.adminKey`) and removed from the address bar.
 *
 * Every control request goes through `controlFetch`: it adds the header and, on a 401, asks the lock
 * indicator (AdminLock.tsx) to open its key prompt and throws a ViewOnlyError whose message the
 * caller's own error toast shows ("View only: enter the admin key to control the demo").
 * No dependency on api.ts: api.ts and demoInject.ts import from here.
 */
import { useSyncExternalStore } from "react";
import { t } from "./i18n";

const STORAGE_KEY = "planb.adminKey";
export const KEY_HEADER = "X-Plan-B-Key";
/** "View only: enter the admin key to control the demo" (in the UI language). */
export const viewOnlyMessage = () => t("dash.lock.viewOnlyMsg");
/** "Admin key not accepted: enter it again to control the demo" (in the UI language). */
export const keyRejectedMessage = () => t("dash.lock.rejectedMsg");
/** Header values are Latin-1 and a key never has spaces or control characters. */
export const validKey = (k: string) => /^[\x21-\x7e]+$/.test(k);

function readStored(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) ?? "";
  } catch {
    return ""; // storage blocked (private window): the key then lasts until the page closes
  }
}

let key = readStored();
let promptSeq = 0;
let promptNote = "";
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => void listeners.delete(l);
};

export const getAdminKey = () => key;

export function setAdminKey(next: string): void {
  key = next.trim();
  try {
    if (key) localStorage.setItem(STORAGE_KEY, key);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* kept in memory only */
  }
  emit();
}

export const clearAdminKey = () => setAdminKey("");

/** A `?key=…` in the page URL: store it, and take it out of the address bar (and the history entry). */
export function captureKeyFromUrl(): void {
  try {
    const url = new URL(window.location.href);
    if (!url.searchParams.has("key")) return;
    const fromUrl = (url.searchParams.get("key") ?? "").trim();
    if (fromUrl && validKey(fromUrl)) setAdminKey(fromUrl);
    url.searchParams.delete("key");
    window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
  } catch {
    /* no URL or history API: nothing to capture */
  }
}

/** The stored key (re-renders when it changes). */
export const useAdminKey = (): string => useSyncExternalStore(subscribe, getAdminKey, getAdminKey);

/** Counts up whenever something asks for the key prompt (a 401, a rejected key). */
export const usePromptRequest = (): number => useSyncExternalStore(subscribe, () => promptSeq, () => promptSeq);
export const getPromptNote = () => promptNote;

export function requestKeyPrompt(note: string): void {
  promptNote = note;
  promptSeq += 1;
  emit();
}

/** Thrown for a 401 on a control action; the message is what an error toast shows. */
export class ViewOnlyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ViewOnlyError";
  }
}

/** The headers of a control request: the caller's, plus the admin key when this device has one. */
export function controlHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  if (key) headers.set(KEY_HEADER, key);
  return headers;
}

/** fetch for POST/PUT/PATCH/DELETE: sends the admin key; a 401 opens the key prompt and throws ViewOnlyError. */
export async function controlFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(input, { ...init, headers: controlHeaders(init.headers) });
  if (res.status === 401) {
    const message = key ? keyRejectedMessage() : viewOnlyMessage();
    requestKeyPrompt(message);
    throw new ViewOnlyError(message);
  }
  return res;
}
