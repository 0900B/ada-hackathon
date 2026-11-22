/**
 * Some server messages come in both languages, "Slovenian text. / English text." (e.g. the AI usage
 * limit, HTTP 429). Show them as two lines, Slovenian first; any other text as it is.
 */
export function splitBilingual(text: string): [string, string] | null {
  const i = text.indexOf(" / ");
  if (i < 0) return null;
  const sl = text.slice(0, i).trim();
  const en = text.slice(i + 3).trim();
  return sl.length > 20 && en.length > 20 ? [sl, en] : null;
}

/** Plain text with the two languages on separate lines (for toasts with white-space: pre-line). */
export const bilingualLines = (text: string) => splitBilingual(text)?.join("\n") ?? text;

export function ErrorText({ text }: { text: string }) {
  const parts = splitBilingual(text);
  if (!parts) return <>{text}</>;
  return (
    <span className="bilingual">
      <span>
        <span className="lang-tag">SL</span>
        {parts[0]}
      </span>
      <span className="muted">
        <span className="lang-tag">EN</span>
        {parts[1]}
      </span>
    </span>
  );
}
