import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, ChevronDown, ChevronRight, Mic, PhoneCall, PhoneIncoming, MapPin, X } from "lucide-react";
import { approveOption, postCall, setAiTriage, setAutopilot, type Trip, type WorldSnapshot } from "./api";
import { BY_LABEL, callsOf, STEP_LABEL, type CallView } from "./calls";
import { DoctorTag } from "./DoctorTag";
import { ErrorText } from "./ErrorText";
import { fmtTime } from "./format";
import { VehicleTypeIcon } from "./icons";
import { SeverityBadge } from "./SeverityBadge";
import { conditionText, LEVEL_LABEL, levelOf } from "./severity";
import { SPEECH_LANGS, useSpeechInput } from "./voice";

type Notify = (kind: "ok" | "error", text: string) => void;

const STATUS_CLASS: Record<string, string> = {
  waiting: "bad",
  dispatched: "",
  "en route": "moving",
  "on scene": "loaded",
  transporting: "loaded",
  "at hospital": "done",
  closed: "done",
  cancelled: "done",
};

/**
 * The right panel's first tab: every call from the 112 call (or hospital request) to the end.
 * Most severe first; a card opens into its timeline (who did what: caller, AI, rules, engine,
 * dispatcher, crew), the caller's words, the triage reason and any plan waiting for approval.
 */
export function CallsPanel({
  state,
  focus,
  onSelectVehicle,
  onPickOnMap,
  picked,
  notify,
  demo,
}: {
  state: WorldSnapshot;
  demo?: ReactNode; // Random call / Random failure (simulation)
  focus: { tripId: string; n: number } | null; // open this call (from a vehicle card)
  onSelectVehicle: (vehicleId: string, openCard: boolean) => void;
  onPickOnMap: () => void;
  picked: { lat: number; lon: number; n: number } | null; // a point chosen on the map for the new call
  notify: Notify;
}) {
  const [open, setOpen] = useState<string | null>(null); // trip id
  const [showClosed, setShowClosed] = useState(false);
  const [form, setForm] = useState(false);
  const { active, closed } = callsOf(state);
  const cardRefs = useRef(new Map<string, HTMLElement>());

  const expand = (c: CallView | undefined, toggle = true) => {
    if (!c) return;
    const next = toggle && open === c.trip.id ? null : c.trip.id;
    setOpen(next);
    const unit = c.units.find((u) => u.role === "unit") ?? c.units[0];
    if (next && unit) onSelectVehicle(unit.id, false); // highlight its route on the map
  };

  // Opened from a vehicle card ("Responding to ...") or a new/random call: apply once the call is in
  // the snapshot (a call just created may arrive with the next update)
  const appliedFocus = useRef(0);
  useEffect(() => {
    if (!focus || appliedFocus.current === focus.n) return;
    const c = [...active, ...closed].find((x) => x.trip.id === focus.tripId);
    if (!c) return;
    appliedFocus.current = focus.n;
    if (closed.includes(c)) setShowClosed(true);
    setOpen(c.trip.id);
    requestAnimationFrame(() => cardRefs.current.get(c.trip.id)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
  }, [focus, state.version]); // eslint-disable-line react-hooks/exhaustive-deps

  // A map point was picked for the new call: show the form again
  useEffect(() => {
    if (picked) setForm(true);
  }, [picked]);

  const switches = (
    <div className="calls-switches">
      {state.ai_triage !== undefined && (
        <Switch
          label="AI triage"
          title="New 112 calls are classified by the AI (otherwise by keyword rules)"
          on={state.ai_triage}
          onChange={(v) => setAiTriage(state.world, v).catch((e) => notify("error", String(e instanceof Error ? e.message : e)))}
        />
      )}
      {state.autopilot !== undefined && (
        <Switch
          label="Autopilot"
          title="The engine applies the recommended plans by itself (the dispatcher can still override)"
          on={state.autopilot}
          onChange={(v) => setAutopilot(state.world, v).catch((e) => notify("error", String(e instanceof Error ? e.message : e)))}
        />
      )}
    </div>
  );

  return (
    <section className="panel calls-panel">
      <div className="calls-head">
        <h2 className="panel-title">Calls</h2>
        {switches}
        <button className={`primary calls-new${form ? " on" : ""}`} onClick={() => setForm((f) => !f)} aria-expanded={form}>
          <PhoneIncoming /> New 112 call
        </button>
      </div>
      {demo}
      {form && (
        <NewCallForm
          state={state}
          picked={picked}
          onPickOnMap={onPickOnMap}
          onClose={() => setForm(false)}
          onCreated={(trip) => {
            setForm(false);
            const c = callsOf(state).active.find((x) => x.trip.id === trip.id);
            setOpen(trip.id);
            if (trip.vehicle_id) onSelectVehicle(trip.vehicle_id, false);
            notify("ok", `${trip.call?.call_id ?? trip.id}: ${LEVEL_LABEL[levelOf(trip)]}${conditionText(trip) ? ` · ${conditionText(trip)}` : ""}${trip.vehicle_id ? ` · ${trip.vehicle_id} dispatched` : ""}`);
            if (c) expand(c, false);
          }}
        />
      )}
      {active.length === 0 ? (
        <p className="muted">No active calls.</p>
      ) : (
        <ul className="calls-list">
          {active.map((c) => (
            <CallCard
              key={c.trip.id}
              c={c}
              state={state}
              open={open === c.trip.id}
              onToggle={() => expand(c)}
              onSelectVehicle={onSelectVehicle}
              notify={notify}
              refCb={(el) => (el ? cardRefs.current.set(c.trip.id, el) : cardRefs.current.delete(c.trip.id))}
            />
          ))}
        </ul>
      )}
      {closed.length > 0 && (
        <div className="calls-closed">
          <button className="link calls-closed-toggle" onClick={() => setShowClosed((s) => !s)} aria-expanded={showClosed}>
            {showClosed ? <ChevronDown /> : <ChevronRight />} Closed in the last 3 h ({closed.length})
          </button>
          {showClosed && (
            <ul className="calls-list">
              {closed.map((c) => (
                <CallCard
                  key={c.trip.id}
                  c={c}
                  state={state}
                  open={open === c.trip.id}
                  onToggle={() => expand(c)}
                  onSelectVehicle={onSelectVehicle}
                  notify={notify}
                  refCb={(el) => (el ? cardRefs.current.set(c.trip.id, el) : cardRefs.current.delete(c.trip.id))}
                />
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

function Switch({ label, title, on, onChange }: { label: string; title: string; on: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="switch calls-switch" title={title}>
      <input type="checkbox" role="switch" checked={on} onChange={(e) => onChange(e.target.checked)} />
      <span className="switch-track" aria-hidden />
      {label}
    </label>
  );
}

function CallCard({
  c,
  state,
  open,
  onToggle,
  onSelectVehicle,
  notify,
  refCb,
}: {
  c: CallView;
  state: WorldSnapshot;
  open: boolean;
  onToggle: () => void;
  onSelectVehicle: (vehicleId: string, openCard: boolean) => void;
  notify: Notify;
  refCb: (el: HTMLElement | null) => void;
}) {
  const t = c.trip;
  const [busy, setBusy] = useState(false);
  const approve = async () => {
    const run = c.proposal;
    if (!run?.recommendation) return;
    setBusy(true);
    try {
      await approveOption(state.world, run.id, run.recommendation.recommended_index);
      notify("ok", `Approved ${run.id}: ${run.recommendation.options[run.recommendation.recommended_index]?.title ?? ""}`);
    } catch (e) {
      notify("error", e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className={`call-card lvl-${levelOf(t)}${open ? " open" : ""}${c.status === "waiting" ? " waiting" : ""}`} ref={refCb}>
      <button className="call-summary" onClick={onToggle} aria-expanded={open}>
        <span className="call-line1">
          {open ? <ChevronDown /> : <ChevronRight />}
          <strong className="call-id">{c.id}</strong>
          <span className="muted">{fmtTime(c.received)}</span>
          {c.triageBy && <span className={`triage-tag ${c.triageBy}`} title={`Triaged by ${BY_LABEL[c.triageBy] ?? c.triageBy}`}>{c.triageBy === "ai" ? "AI" : c.triageBy === "rules" ? "Rules" : "Disp."}</span>}
          {c.kind === "hospital_request" && <span className="call-kind">Hospital request</span>}
          <span className={`call-status ${STATUS_CLASS[c.status] ?? ""}`}>{c.status}</span>
        </span>
        <span className="call-line2">
          <SeverityBadge trip={t} />
        </span>
        <span className="call-line3 muted">
          {c.address}
          {c.caller ? ` · ${c.caller}` : ""}
        </span>
      </button>
      {c.units.length > 0 && (
        <div className="call-units">
          {c.units.map((u) => (
            <button key={u.id} className={`unit-chip ${u.role}`} onClick={() => onSelectVehicle(u.id, true)} title={`Show ${u.id} (vehicle card)`}>
              {u.type && <VehicleTypeIcon type={u.type} />}
              <strong>{u.id}</strong>
              <span className="muted">{u.eta ? `${u.etaLabel} ${fmtTime(u.eta)}` : u.etaLabel}</span>
            </button>
          ))}
          <DoctorTag trip={t} vehicles={state.vehicles} now={state.sim_time} />
        </div>
      )}
      {c.units.length === 0 && c.status === "waiting" && <div className="call-units bad">No unit yet</div>}
      {c.proposal && !open && (
        <div className="call-proposal-hint">
          Plan {c.proposal.id} waiting for approval · <button className="link" onClick={onToggle}>open</button>
        </div>
      )}
      {open && (
        <div className="call-detail">
          {(c.textSl || c.textEn) && (
            <blockquote className="call-words">
              {c.textSl && (
                <div>
                  <span className="lang-tag">SL</span>
                  {c.textSl}
                </div>
              )}
              {c.textEn && c.textEn !== c.textSl && (
                <div className="muted">
                  <span className="lang-tag">EN</span>
                  {c.textEn}
                </div>
              )}
            </blockquote>
          )}
          {(c.reasonEn || c.reasonSl) && (
            <div className="call-reason">
              <span className={`triage-tag ${c.triageBy ?? ""}`}>{c.triageBy === "ai" ? "AI" : c.triageBy === "rules" ? "Rules" : "Triage"}</span>
              <span>{c.reasonEn ?? c.reasonSl}</span>
            </div>
          )}
          {c.proposal?.recommendation && (
            <div className="call-approve">
              <div>
                <strong>Proposal {c.proposal.id}:</strong>{" "}
                {c.proposal.recommendation.options[c.proposal.recommendation.recommended_index]?.title}
              </div>
              <button className="approve primary" disabled={busy} onClick={() => void approve()}>
                <Check /> Approve
              </button>
            </div>
          )}
          <ol className="timeline">
            {c.timeline.map((e, i) => (
              <li key={i} className={`tl-${e.kind}`}>
                <span className="tl-time">{fmtTime(e.at)}</span>
                <span className="tl-step">{STEP_LABEL[e.kind] ?? e.kind}</span>
                <span className={`tl-by by-${e.by}`}>{BY_LABEL[e.by] ?? e.by}</span>
                <span className="tl-text">
                  {e.text}
                  {e.vehicle_id && (
                    <button className="link tl-unit" onClick={() => onSelectVehicle(e.vehicle_id!, true)}>
                      {e.vehicle_id}
                    </button>
                  )}
                </span>
              </li>
            ))}
            {c.status !== "closed" && c.status !== "cancelled" && (
              <li className="tl-next muted">
                <span className="tl-time">…</span>
                <span className="tl-step">{c.status}</span>
              </li>
            )}
          </ol>
        </div>
      )}
    </li>
  );
}

// --- New 112 call ---------------------------------------------------------------------------

function NewCallForm({
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
      setTimeout(() => onCreated(trip), 2500); // show the triage, then open the call's card
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(/not found|405|method not allowed/i.test(msg) && !/address/i.test(msg) ? "This backend has no 112 intake yet: press E and click the map to place an emergency." : msg);
    } finally {
      setBusy(false);
    }
  };

  const ok = text.trim().length >= 3 && (point || address.trim().length >= 2);
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
            {result.call?.triage && <span className={`triage-tag ${result.call.triage.by}`}>{result.call.triage.by === "ai" ? "AI" : "Rules"}</span>}
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
