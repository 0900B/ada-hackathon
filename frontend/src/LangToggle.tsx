import { LANGS, setLang, useLang, useT } from "./i18n";

/** The compact "SL | EN" language switch (dashboard header, tablet, crew phone). */
export function LangToggle({ className = "" }: { className?: string }) {
  const lang = useLang();
  const t = useT();
  return (
    <div className={`lang-toggle ${className}`} role="group" aria-label={t("lang.label")}>
      {LANGS.map((l, i) => (
        <span key={l} className="lang-toggle-item">
          {i > 0 && (
            <span className="lang-toggle-sep" aria-hidden>
              |
            </span>
          )}
          <button
            type="button"
            className={lang === l ? "on" : ""}
            aria-pressed={lang === l}
            lang={l}
            title={t(l === "sl" ? "lang.sl" : "lang.en")}
            onClick={() => setLang(l)}
          >
            {l.toUpperCase()}
          </button>
        </span>
      ))}
    </div>
  );
}
