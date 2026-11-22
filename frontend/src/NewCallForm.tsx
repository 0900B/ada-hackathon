import { useEffect, useState } from "react";
import { MapPin, Mic, PhoneCall, PhoneIncoming, X } from "lucide-react";
import { postCall, type Trip, type WorldSnapshot } from "./api";
import { BY_LABEL } from "./calls";
import { ErrorText } from "./ErrorText";
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
  const [text, setText] = useState("");
  const [address, setAddress] = useState("");
  const [point, setPoint] = useState<{ lat: number; lon: number } | null>(null);
  const [caller, setCaller] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Trip | null>(null);
  const speech = useSpeechInput({ lang: "sl-SI", onFinal: (heard) => setText((t) => (t ? `${t} ${heard}` : heard)) });
  const places = state.places.filter((p) => p.kind !== "call_location" && p.kind !== "incident_site");

  useEffect(() => {
    if (picked) {
      setPoint({ lat: picked.lat, lon: picked.lon });
      setAddress((a) => a || "Point on the map");
    }
  }, [picked]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    const match = places.find((p) => p.name.toLowerCase() === address.trim().toLowerCase());
    try {
      const trip = await postCall(state.world, {
        text: text.trim(),
        ...(point ? { lat: point.lat, lon: point.lon } : match ? { place_id: match.id } : {}),
        address: address.trim() || undefined,
        caller_name: caller.trim() || undefined,
      });
      setResult(trip);
      setTimeout(() => onCreated(trip), 2500); // show the triage, then open the case card
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(/not found|405|method not allowed/i.test(msg) && !/address/i.test(msg) ? "This backend has no 112 intake yet: press E and click the map to place an emergency." : msg);
    } finally {
      setBusy(false);
    }
  };

  const ok = text.trim().length >= 3 && (point || address.trim().length >= 2);
  const triageBy = result?.call?.triage?.by;
  return (
    <div className="call-form">
      <div className="call-form-head">
        <PhoneCall /> <strong>New 112 call</strong>
        <button className="link vc-close" onClick={onClose} aria-label="Close">
          <X />
        </button>
      </div>
      <label className="field-label" htmlFor="call-words">
        What the caller says
      </label>
      <textarea
        id="call-words"
        rows={3}
        placeholder="»Moj mož se je zgrudil in ne diha!« · Ctrl+Enter sends"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && ok && !busy) void submit();
        }}
      />
      {speech.listening && <div className="voice-interim">{speech.interim || "Listening… speak now"}</div>}
      {speech.supported && (
        <div className="row call-voice">
          <button type="button" className={`mic-btn${speech.listening ? " listening" : ""}`} onClick={speech.toggle} aria-pressed={speech.listening}>
            <Mic /> {speech.listening ? "Listening…" : "Speak"}
          </button>
          <span className="lang-toggle" role="group" aria-label="Speech language">
            {SPEECH_LANGS.map((l) => (
              <button key={l.code} type="button" aria-pressed={speech.lang === l.code} onClick={() => speech.setLang(l.code)}>
                {l.label}
              </button>
            ))}
          </span>
        </div>
      )}
      <label className="field-label" htmlFor="call-address">
        Where
      </label>
      <div className="row">
        <input
          id="call-address"
          list="call-places"
          placeholder="Address or place (e.g. Bežigrad)"
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
        <button type="button" onClick={onPickOnMap} title="Click the map where the patient is">
          <MapPin /> Pick on map
        </button>
      </div>
      {point && (
        <div className="muted small">
          Map point {point.lat.toFixed(4)}, {point.lon.toFixed(4)}
        </div>
      )}
      <input placeholder="Caller's name (optional)" value={caller} onChange={(e) => setCaller(e.target.value)} aria-label="Caller's name" />
      <button className="primary" disabled={!ok || busy} onClick={() => void submit()}>
        <PhoneIncoming /> {busy ? "Classifying…" : "Classify and dispatch"}
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
            {result.call?.triage?.needs_doctor && <span className="call-kind">Doctor needed</span>}
            {triageBy && <span className={`src-tag ${triageBy === "ai" ? "claude" : "rules"}`}>{BY_LABEL[triageBy] ?? triageBy}</span>}
          </div>
          {result.call?.triage?.reason_en && <div className="muted">{result.call.triage.reason_en}</div>}
          <div>
            {result.timeline?.find((e) => e.kind === "dispatched")?.text ?? (result.vehicle_id ? `${result.vehicle_id} dispatched` : "No unit yet: dispatch is looking for one")}
          </div>
        </div>
      )}
    </div>
  );
}
