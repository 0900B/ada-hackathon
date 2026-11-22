/**
 * Lightweight i18n (no dependency): typed dictionaries in English and Slovenian, `t(key, params)`
 * with `{name}` interpolation and plural forms (Slovenian has four: 1, 2, 3-4, 5+ and 0, picked by
 * Intl.PluralRules), a `useT()` hook, and the language remembered per surface in localStorage:
 * `planb.lang` for the dispatcher dashboard (default English, the presenter's choice) and
 * `planb.lang.field` for the crew phone (/crew) and the in-vehicle tablet (/vehicle), default
 * Slovenian. `?lang=sl` or `?lang=en` in the address sets it for that surface.
 *
 * Backend texts stay as the backend sends them (English), except its Slovenian fields (text_sl,
 * reason_sl, understood_sl, message_sl), which the UI picks when the language is Slovenian.
 */
import { createElement, Fragment, useEffect, useSyncExternalStore, type ReactNode } from "react";
import * as common from "./locales/common";
import * as dashboard from "./locales/dashboard";
import * as dispatch from "./locales/dispatch";
import * as pages from "./locales/pages";
import * as field from "./locales/field";
import * as ops from "./locales/ops";

export type Lang = "en" | "sl";
export const LANGS: Lang[] = ["sl", "en"];

/** Plural forms: English uses one/other; Slovenian one (1, 101), two (2, 102), few (3-4, 103-104), other (0, 5+). */
export type Plural = { one: string; two?: string; few?: string; other: string };
export type Msg = string | Plural;
/** The Slovenian side of a dictionary: every English key, nothing else. */
export type Translation<T> = { [K in keyof T]: Msg };

const EN = { ...common.en, ...dashboard.en, ...ops.en, ...dispatch.en, ...pages.en, ...field.en };
export type TKey = keyof typeof EN;
const SL: Record<TKey, Msg> = { ...common.sl, ...dashboard.sl, ...ops.sl, ...dispatch.sl, ...pages.sl, ...field.sl };
const DICT: Record<Lang, Record<TKey, Msg>> = { en: EN, sl: SL };

export type Params = Record<string, string | number | null | undefined>;

// ---- the language store -------------------------------------------------------------------------

type Surface = "dashboard" | "field";
const STORAGE: Record<Surface, string> = { dashboard: "planb.lang", field: "planb.lang.field" };
const DEFAULT: Record<Surface, Lang> = { dashboard: "en", field: "sl" };

const surfaceOf = (path: string): Surface => (/^\/(crew|vehicle)(\/|$)/.test(path) ? "field" : "dashboard");
const currentSurface = (): Surface => (typeof window === "undefined" ? "dashboard" : surfaceOf(window.location.pathname));
const isLang = (v: unknown): v is Lang => v === "en" || v === "sl";

function readStored(s: Surface): Lang | null {
  try {
    const v = localStorage.getItem(STORAGE[s]);
    return isLang(v) ? v : null;
  } catch {
    return null;
  }
}
function writeStored(s: Surface, l: Lang) {
  try {
    localStorage.setItem(STORAGE[s], l);
  } catch {
    /* private mode: the choice lasts for this page only */
  }
}

const chosen: Partial<Record<Surface, Lang>> = {};
for (const s of ["dashboard", "field"] as Surface[]) {
  const v = readStored(s);
  if (v) chosen[s] = v;
}
// ?lang=sl / ?lang=en: set the language of the surface the page opens on (e.g. a link to the crew phone)
try {
  const q = new URLSearchParams(window.location.search).get("lang");
  if (isLang(q)) {
    chosen[currentSurface()] = q;
    writeStored(currentSurface(), q);
  }
} catch {
  /* no window */
}

/** The language of the surface shown now (dashboard pages or the crew/tablet views). */
export const getLang = (): Lang => {
  const s = currentSurface();
  return chosen[s] ?? DEFAULT[s];
};

const listeners = new Set<() => void>();
const subscribe = (fn: () => void) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};

/** Switch the language of the current surface and remember it on this device. */
export function setLang(l: Lang) {
  const s = currentSurface();
  chosen[s] = l;
  writeStored(s, l);
  listeners.forEach((fn) => fn());
}

// ---- translation --------------------------------------------------------------------------------

const rules: Partial<Record<Lang, Intl.PluralRules>> = {};
function pluralForm(lang: Lang, p: Plural, count: number): string {
  const r = (rules[lang] ??= new Intl.PluralRules(lang === "sl" ? "sl-SI" : "en-GB"));
  const cat = r.select(count) as keyof Plural;
  return p[cat] ?? p.other;
}

const interpolate = (s: string, params?: Params) =>
  params ? s.replace(/\{(\w+)\}/g, (m, k: string) => (params[k] == null ? m : String(params[k]))) : s;

export function translate(lang: Lang, key: TKey, params?: Params): string {
  const msg = DICT[lang][key] ?? EN[key] ?? key;
  const text = typeof msg === "string" ? msg : pluralForm(lang, msg, Number(params?.count ?? 0));
  return interpolate(text, params);
}

/** Translate in the current language (for helpers outside components; components use `useT()`). */
export const t = (key: TKey, params?: Params): string => translate(getLang(), key, params);

/** Whether a dynamic key exists, e.g. `cond.${code}` for a condition code from the backend. */
export const hasKey = (key: string): key is TKey => key in EN;

/** Translate a dynamic key (`vstatus.${status}`), or fall back when the dictionary lacks it. */
export const tOr = (key: string, fallback: string, params?: Params): string => (hasKey(key) ? t(key, params) : fallback);

/**
 * A record whose values follow the language: `LEVEL_LABEL.critical` reads "Critical" or "Kritično"
 * at the time of reading (so existing `LEVEL_LABEL[level]` lookups translate without changes).
 */
export function liveRecord<K extends string>(keys: readonly K[], get: (k: K) => string): Record<K, string> {
  const o = {} as Record<K, string>;
  for (const k of keys) Object.defineProperty(o, k, { get: () => get(k), enumerable: true });
  return o;
}

/** A number with the decimal separator of the language ("2.5" / "2,5"). */
export const fmtNum = (n: number, digits = 1, lang: Lang = getLang()): string => {
  const s = n.toFixed(digits);
  return lang === "sl" ? s.replace(".", ",") : s;
};

/** A number as it is (no rounding), with the decimal separator of the language ("0.25" / "0,25"). */
export const fmtDec = (n: number, lang: Lang = getLang()): string => (lang === "sl" ? String(n).replace(".", ",") : String(n));

/**
 * Rich text: `{name}` placeholders replaced by React nodes, e.g.
 * `tr("header.help", { key: <kbd>?</kbd> })` for "Press {key} for shortcuts".
 */
export function tr(key: TKey, nodes: Record<string, ReactNode>, params?: Params, lang: Lang = getLang()): ReactNode {
  const text = translate(lang, key, params);
  const parts = text.split(/(\{\w+\})/g).map((part) => {
    const m = /^\{(\w+)\}$/.exec(part);
    return m && m[1] in nodes ? nodes[m[1]] : part;
  });
  return createElement(Fragment, null, ...parts);
}

export type TFn = (key: TKey, params?: Params) => string;

/** The current language; the component re-renders when it changes. */
export function useLang(): Lang {
  return useSyncExternalStore(subscribe, getLang, getLang);
}

/** `const t = useT()`: translate in the current language, re-rendering when it changes. */
export function useT(): TFn {
  const lang = useLang();
  return (key, params) => translate(lang, key, params);
}

/** For the app root: keeps <html lang> in step and re-renders the whole tree on a switch. */
export function useLangRoot(): Lang {
  const lang = useLang();
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  return lang;
}
