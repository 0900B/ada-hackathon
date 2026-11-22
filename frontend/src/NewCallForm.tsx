import { useEffect, useState } from "react";
import { MapPin, Mic, PhoneCall, PhoneIncoming, X } from "lucide-react";
import { postCall, type Trip, type WorldSnapshot } from "./api";
import { BY_LABEL } from "./calls";
import { ErrorText } from "./ErrorText";
import { t as tx, useLang, useT } from "./i18n";
import { SeverityBadge } from "./SeverityBadge";
import { SPEECH_LANGS, useSpeechInput } from "./voice";

/** A new 112 call: the caller's words and where. The AI classifies it and dispatches at once. */
export function NewCallForm({
  state,
  picked,
  onPickOnMap,
  onClose,
  onCreated,
}: {
  state: WorldSnapshot;
  picked: { lat: number; lon: number; n: number } | null;
  onPickOnMap: () => void;
  onClose: () => void;
  onCreated: (trip: Trip) => void;
}) {
  const t = useT();
  const lang = useLang();
  const [text, setText] = useState("");
  const [address, setAddress] = useState("");
  const [point, setPoint] = useState<{ lat: number; lon: number } | null>(null);
  const [caller, setCaller] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Trip | null>(null);
  const speech = useSpeechInput({ lang: "sl-SI", onFinal: (heard) => setText((prev) => (prev ? `${prev} ${heard}` : heard)) });
  const places = state.places.filter((p) => p.kind !== "call_location" && p.kind !== "incident_site");

  useEffect(() => {
    if (picked) {
      setPoint({ lat: picked.lat, lon: picked.lon });
      setAddress((a) => a || tx("ai.nc.mapPoint"));
    }
  }, [picked]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    const match = places.find((p) => p.name.toLowerCase() === address.trim().toLowerCase());
    // A picked point with the field still showing our own "Point on the map": send no address, so the
    // backend names it after the nearest place ("Map point near Šiška") rather than "Point on the map"
    const typed = point && address.trim() === tx("ai.nc.mapPoint") ? "" : address.trim();
    try {
      const trip = await postCall(state.world, {
        text: text.trim(),
        ...(point ? { lat: point.lat, lon: point.lon } : match ? { place_id: match.id } : {}),
        address: typed || undefined,
        caller_name: caller.trim() || undefined,
      });
      setResult(trip);
      setTimeout(() => onCreated(trip), 2500); // show the triage, then open the case card
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(/not found|405|method not allowed/i.test(msg) && !/address/i.test(msg) ? t("ai.nc.noIntake") : msg);
    } finally {
      setBusy(false);
    }
  };

  const ok = text.trim().length >= 3 && (point || address.trim().length >= 2);
  const triageBy = result?.call?.triage?.by;
  // The AI's clinical reason: Slovenian from the backend when the UI is Slovenian
  const reason = (lang === "sl" ? result?.call?.triage?.reason_sl : null) || result?.call?.triage?.reason_en;
  return (
    <div className="call-form">
      <div className="call-form-head">
        <PhoneCall /> <strong>{t("ai.newCall")}</strong>
        <button className="link vc-close" onClick={onClose} aria-label={t("common.close")}>
          <X />
        </button>
      </div>
      <label className="field-label" htmlFor="call-words">
        {t("ai.nc.words")}
      </label>
      <textarea
        id="call-words"
        rows={3}
        placeholder={t("ai.nc.placeholder")}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && ok && !busy) void submit();
        }}
      />
      {speech.listening && <div className="voice-interim">{speech.interim || t("ai.fm.speakNow")}</div>}
      {speech.supported && (
        <div className="row call-voice">
          <button type="button" className={`mic-btn${speech.listening ? " listening" : ""}`} onClick={speech.toggle} aria-pressed={speech.listening}>
            <Mic /> {speech.listening ? t("ai.listening") : t("ai.fm.speak")}
          </button>
          <span className="lang-toggle" role="group" aria-label={t("ai.fm.speechLang")}>
            {SPEECH_LANGS.map((l) => (
              <button key={l.code} type="button" aria-pressed={speech.lang === l.code} onClick={() => speech.setLang(l.code)}>
                {l.label}
              </button>
            ))}
          </span>
        </div>
      )}
      <label className="field-label" htmlFor="call-address">
        {t("ai.nc.where")}
      </label>
      <div className="row">
        <input
          id="call-address"
          list="call-places"
          placeholder={t("ai.nc.addressPh")}
          value={address}
          onChange={(e) => {
            setAddress(e.target.value);
            setPoint(null);
          }}
        />
        <datalist id="call-places">
          {places.map((p) => (
            <option key={p.id} value={p.name} />
          ))}
        </datalist>
        <button type="button" onClick={onPickOnMap} title={t("ai.nc.pickTitle")}>
          <MapPin /> {t("ai.nc.pick")}
        </button>
      </div>
      {point && <div className="muted small">{t("ai.nc.point", { lat: point.lat.toFixed(4), lon: point.lon.toFixed(4) })}</div>}
      <input placeholder={t("ai.nc.callerPh")} value={caller} onChange={(e) => setCaller(e.target.value)} aria-label={t("ai.nc.callerAria")} />
      <button className="primary" disabled={!ok || busy} onClick={() => void submit()}>
        <PhoneIncoming /> {busy ? t("ai.nc.classifying") : t("ai.nc.submit")}
      </button>
      {error && (
        <div className="message error">
          <ErrorText text={error} />
        </div>
      )}
      {result && (
        <div className="call-result">
          <div className="sev-row">
            <SeverityBadge trip={result} size="md" />
            {result.call?.triage?.needs_doctor && <span className="call-kind">{t("ai.doctorNeeded")}</span>}
            {triageBy && <span className={`src-tag ${triageBy === "ai" ? "claude" : "rules"}`}>{BY_LABEL[triageBy] ?? triageBy}</span>}
          </div>
          {reason && <div className="muted">{reason}</div>}
          <div>
            {result.timeline?.find((e) => e.kind === "dispatched")?.text ??
              (result.vehicle_id ? t("ai.nc.dispatched", { v: result.vehicle_id }) : t("ai.nc.noUnit"))}
          </div>
        </div>
      )}
    </div>
  );
}
