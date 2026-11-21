import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import {
  API_URL,
  fetchNavigation,
  fetchVehicle,
  idSeq,
  postEvent,
  sendFieldMessage,
  useWorldState,
  type Alert,
  type MessageResult,
  type Navigation,
  type NavStep,
  type Trip,
  type Vehicle,
  type VehicleDetail,
  type World,
  type WorldSnapshot,
} from "../api";
import {
  ArrowLeftRight,
  Check,
  Clock,
  Construction,
  Flag,
  Fuel,
  House,
  Mail,
  Mic,
  Moon,
  NotebookText,
  RotateCw,
  Send,
  Siren,
  Sun,
  Timer,
  TriangleAlert,
  Wrench,
  X,
  CornerUpRight,
  type LucideIcon,
} from "lucide-react";
import { fmtTime, humanize, vehicleStatusText } from "../format";
import { VehicleTypeIcon } from "../icons";
import { NavMap } from "../NavMap";
import { conditionText, LEVEL_LABEL, LEVEL_PRIORITY, LEVEL_RANK, LEVELS, levelOf, severitySupported, type Level } from "../severity";
import { ResponseLine, SeverityBadge } from "../SeverityBadge";
import { SPEECH_LANGS, speechSecureContext, usePushToTalk, useSpeechInput } from "../voice";
import "../voice.css";
import "../tablet.css";

/**
 * In-vehicle tablet (mobile data terminal), landscape iPad first: /vehicle/:vehicleId?world=sim|live.
 * Navigation map with the next manoeuvre, the current job, next stops, crew messages to dispatch,
 * one-tap status reports (no AI involved) and messages from dispatch when the plan changes.
 */

const THEME_KEY = "planb.mdtTheme";
const DONE = ["completed", "cancelled"];

function savedNight(): boolean {
  try {
    return localStorage.getItem(THEME_KEY) !== "day";
  } catch {
    return true;
  }
}

export function TabletPage() {
  const { vehicleId = "" } = useParams();
  const [params] = useSearchParams();
  const world: World = params.get("world") === "live" ? "live" : "sim";
  const { state, connected } = useWorldState(world);
  const [night, setNight] = useState(savedNight);
  const toggleTheme = () =>
    setNight((n) => {
      try {
        localStorage.setItem(THEME_KEY, n ? "day" : "night");
      } catch {
        /* not remembered */
      }
      return !n;
    });

  if (!state) {
    return (
      <main className={`mdt ${night ? "night" : "day"}`}>
        <p className="mdt-loading">Connecting to {API_URL} …</p>
      </main>
    );
  }
  const vehicle = state.vehicles.find((v) => v.id.toLowerCase() === vehicleId.toLowerCase());
  if (!vehicle) return <TabletPicker state={state} world={world} missing={vehicleId} night={night} />;
  return (
    <TabletConsole
      key={`${world}:${vehicle.id}`}
      state={state}
      vehicle={vehicle}
      world={world}
      connected={connected}
      night={night}
      toggleTheme={toggleTheme}
    />
  );
}

function TabletPicker({ state, world, missing, night }: { state: WorldSnapshot; world: World; missing: string; night: boolean }) {
  return (
    <main className={`mdt mdt-picker ${night ? "night" : "day"}`}>
      <h1>{missing ? `Vehicle “${missing}” not found` : "In-vehicle tablet"}</h1>
      <p className="mdt-muted">Choose this vehicle ({world === "sim" ? "simulation" : "live"}):</p>
      <ul>
        {state.vehicles.map((v) => (
          <li key={v.id}>
            <Link to={`/vehicle/${encodeURIComponent(v.id)}?world=${world}`}>
              <span className="mdt-badge">
                <VehicleTypeIcon type={v.type} /> {v.id}
              </span>
              <span className="mdt-pick-name">{v.name}</span>
              <span className="mdt-muted">{vehicleStatusText(v, state.trips)}</span>
            </Link>
          </li>
        ))}
      </ul>
      <p className="mdt-muted">
        World: <Link to={`/vehicle?world=sim`}>simulation</Link> · <Link to={`/vehicle?world=live`}>live</Link>
      </p>
    </main>
  );
}

// --- navigation banner -------------------------------------------------------------------------

const fmtDist = (m: number) => (m < 1000 ? `${Math.max(10, Math.round(m / 10) * 10)} m` : `${(m / 1000).toFixed(m < 10_000 ? 1 : 0)} km`);

const TURN_ANGLE: Record<string, number> = {
  straight: 0,
  "slight right": 40,
  right: 90,
  "sharp right": 135,
  uturn: 180,
  "slight left": -40,
  left: -90,
  "sharp left": -135,
};

function instruction(s: NavStep): string {
  const road = s.name || (s.ref ? (/^\d/.test(s.ref) ? `road ${s.ref}` : s.ref) : "");
  const onto = road ? ` onto ${road}` : "";
  const mod = s.modifier ?? "";
  const side = mod.includes("left") ? "left" : mod.includes("right") ? "right" : "";
  switch (s.type) {
    case "arrive":
      return `Arrive${side ? `, on the ${side}` : ""}`;
    case "depart":
      return `Head off${onto}`;
    case "roundabout":
    case "rotary":
      return s.exit ? `At the roundabout take exit ${s.exit}${onto}` : `Enter the roundabout${onto}`;
    case "exit roundabout":
    case "exit rotary":
      return `Leave the roundabout${onto}`;
    case "roundabout turn":
      return `At the roundabout turn ${mod}${onto}`;
    case "merge":
      return `Merge${side ? ` ${side}` : ""}${onto}`;
    case "on ramp":
      return `Take the ramp${side ? ` on the ${side}` : ""}${onto}`;
    case "off ramp":
      return `Take the exit${side ? ` on the ${side}` : ""}${onto}`;
    case "fork":
      return `Keep ${side || "straight"}${onto}`;
    case "end of road":
      return `At the end of the road turn ${side || mod}${onto}`;
    case "continue":
    case "new name":
      return mod && mod !== "straight" ? `Keep ${mod}${onto}` : `Continue${onto}`;
    default:
      if (mod === "uturn") return `Make a U-turn${onto}`;
      if (mod === "straight" || !mod) return `Go straight${onto}`;
      if (mod.startsWith("slight")) return `Bear ${side}${onto}`;
      return `Turn ${mod}${onto}`;
  }
}

function ManeuverIcon({ step, bearing }: { step?: NavStep; bearing?: number }) {
  if (step?.type === "arrive")
    return (
      <span className="mdt-turn-icon">
        <Flag />
      </span>
    );
  if (step && (step.type === "roundabout" || step.type === "rotary"))
    return (
      <span className="mdt-turn-icon">
        <RotateCw />
      </span>
    );
  const angle = bearing ?? TURN_ANGLE[step?.modifier ?? "straight"] ?? 0;
  return (
    <svg className="mdt-turn-icon" viewBox="0 0 48 48" style={{ transform: `rotate(${angle}deg)` }} aria-hidden>
      <path d="M24 4 L39 22 H29.5 V44 H18.5 V22 H9 Z" />
    </svg>
  );
}

const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

function NavBanner({ nav, vehicle, trip, state }: { nav: Navigation | null; vehicle: Vehicle; trip: Trip | undefined; state: WorldSnapshot }) {
  const kindText = { pickup: "Pickup", dropoff: "Drop-off", base: "Back to base" } as const;
  if (vehicle.status === "out_of_service")
    return (
      <div className="mdt-banner down">
        <TriangleAlert /> Out of service · dispatch is re-planning your trips
      </div>
    );
  if (vehicle.waiting_until && Date.parse(vehicle.waiting_until) > Date.parse(state.sim_time) && trip) {
    return (
      <div className="mdt-banner">
        <span className="mdt-turn-icon">
          <Clock />
        </span>
        <div>
          <div className="mdt-instr">Waiting for the patient until {fmtTime(vehicle.waiting_until)}</div>
          <div className="mdt-next-stop">At pickup: {state.places.find((p) => p.id === trip.pickup_id)?.name}</div>
        </div>
      </div>
    );
  }
  if (!nav || !nav.target) {
    const busy = vehicle.status === "loading" ? "Loading…" : vehicle.status === "idle" ? "No active job · standing by" : humanize(vehicle.status);
    return <div className="mdt-banner idle">{busy}</div>;
  }
  const eta = nav.eta ? fmtTime(nav.eta) : "–";
  // Standing still for a while: loading, unloading or held by an operator delay
  const busyUntil = vehicle.busy_until && Date.parse(vehicle.busy_until) > Date.parse(state.sim_time) ? vehicle.busy_until : null;
  const busyText =
    vehicle.status === "loading"
      ? trip?.kind === "equipment"
        ? "Loading the equipment"
        : "Loading the patient"
      : vehicle.status === "returning"
        ? "Unloading"
        : "Held";
  const stopLine = (
    <div className="mdt-next-stop">
      {kindText[nav.target.kind]}: <strong>{nav.target.name}</strong>
      {nav.remaining_m != null && <> · {fmtDist(nav.remaining_m)}</>} · ETA <strong>{eta}</strong>
      {nav.detour && (
        <span className="mdt-detour">
          {" "}
          <CornerUpRight /> detour around a closure
        </span>
      )}
    </div>
  );
  if (busyUntil) {
    return (
      <div className="mdt-banner">
        <span className="mdt-turn-icon">
          <Clock />
        </span>
        <div>
          <div className="mdt-instr">
            {busyText} · until {fmtTime(busyUntil)}
          </div>
          {stopLine}
        </div>
      </div>
    );
  }
  if (nav.status === "arrived") {
    return (
      <div className="mdt-banner">
        <ManeuverIcon step={{ type: "arrive" } as NavStep} />
        <div>
          <div className="mdt-instr">Arrived · {kindText[nav.target.kind]}</div>
          <div className="mdt-next-stop">
            <strong>{nav.target.name}</strong>
            {vehicle.status === "loading" ? " · loading" : ""}
          </div>
        </div>
      </div>
    );
  }
  if (nav.mode === "flight") {
    const b = nav.bearing_deg ?? 0;
    return (
      <div className="mdt-banner">
        <ManeuverIcon bearing={b} />
        <div>
          <div className="mdt-dist">{nav.remaining_m != null ? fmtDist(nav.remaining_m) : ""}</div>
          <div className="mdt-instr">
            Fly {String(b).padStart(3, "0")}° {COMPASS[Math.round(b / 45) % 8]} · straight line
          </div>
          {stopLine}
        </div>
      </div>
    );
  }
  const [next, then] = nav.steps;
  if (!next) {
    return (
      <div className="mdt-banner">
        <ManeuverIcon />
        <div>
          <div className="mdt-instr">Drive to {nav.target.name}</div>
          {stopLine}
          {nav.status === "pending" && <div className="mdt-muted small">Loading turn-by-turn directions…</div>}
        </div>
      </div>
    );
  }
  return (
    <div className="mdt-banner">
      <ManeuverIcon step={next} />
      <div>
        <div className="mdt-dist">{next.distance_m < 30 ? "Now" : `In ${fmtDist(next.distance_m)}`}</div>
        <div className="mdt-instr">{instruction(next)}</div>
        {stopLine}
        {then && then.type !== "arrive" && (
          <div className="mdt-then">
            Then: {instruction(then).replace(/^./, (c) => c.toLowerCase())} ({fmtDist(then.distance_m)})
          </div>
        )}
      </div>
    </div>
  );
}

// --- messages from dispatch --------------------------------------------------------------------

interface DispatchNote {
  id: string;
  at: string;
  reason: string;
  lines: string[];
  crew: { sl: string; en: string }[];
}

function useChime() {
  const ctx = useRef<AudioContext | null>(null);
  useEffect(() => {
    // Browsers only allow sound after a tap: unlock the audio context on the first touch
    const unlock = () => {
      try {
        const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
        if (!ctx.current && Ctor) ctx.current = new Ctor();
        void ctx.current?.resume();
      } catch {
        /* no audio */
      }
    };
    window.addEventListener("pointerdown", unlock);
    return () => window.removeEventListener("pointerdown", unlock);
  }, []);
  return () => {
    const c = ctx.current;
    if (!c || c.state !== "running") return;
    try {
      [880, 1320].forEach((f, i) => {
        const o = c.createOscillator();
        const g = c.createGain();
        o.frequency.value = f;
        o.type = "sine";
        const t = c.currentTime + i * 0.18;
        g.gain.setValueAtTime(0.0001, t);
        g.gain.exponentialRampToValueAtTime(0.18, t + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);
        o.connect(g).connect(c.destination);
        o.start(t);
        o.stop(t + 0.4);
      });
    } catch {
      /* no audio */
    }
  };
}

const mentions = (text: string, v: Vehicle) =>
  new RegExp(`\\b${v.id}\\b`, "i").test(text) || text.toLowerCase().includes(v.name.toLowerCase());

/** Watches the snapshot for plan changes that touch this vehicle and turns them into messages. */
function useDispatchNotes(state: WorldSnapshot, vehicle: Vehicle, chime: () => void) {
  const [notes, setNotes] = useState<DispatchNote[]>([]);
  const prev = useRef<{ trips: Map<string, string>; lastEvent: number; sim: number } | null>(null);

  useEffect(() => {
    const mine = new Map(
      state.trips.filter((t) => t.vehicle_id === vehicle.id && !DONE.includes(t.status)).map((t) => [t.id, t.dropoff_id]),
    );
    const lastEvent = Math.max(-1, ...state.events.map((e) => idSeq(e.id)));
    const sim = Date.parse(state.sim_time);
    const before = prev.current;
    prev.current = { trips: mine, lastEvent, sim };
    // First snapshot, a reset (clock or event ids went back) or a reconnect gap: just take it as is
    if (!before || sim < before.sim - 1000 || lastEvent < before.lastEvent) return;

    const trip = (id: string) => state.trips.find((t) => t.id === id);
    const place = (id: string) => state.places.find((p) => p.id === id)?.name ?? id;
    const added = [...mine.keys()].filter((id) => !before.trips.has(id));
    const removed = [...before.trips.keys()].filter((id) => !mine.has(id) && !DONE.includes(trip(id)?.status ?? "completed"));
    const redirected = [...mine.keys()].filter((id) => before.trips.has(id) && before.trips.get(id) !== mine.get(id));
    if (!added.length && !removed.length && !redirected.length) return;

    const lines = [
      ...added.map((id) => {
        const t = trip(id)!;
        const cond = conditionText(t);
        return `New job: ${t.id} ${LEVEL_LABEL[levelOf(t)]}${cond ? ` · ${cond}` : ""} · ${t.label} · ${place(t.pickup_id)} → ${place(t.dropoff_id)}`;
      }),
      ...removed.map((id) => {
        const t = trip(id);
        return t?.vehicle_id ? `${id} moved to ${t.vehicle_id}` : `${id} handed back to dispatch`;
      }),
      ...redirected.map((id) => `${id} now goes to ${place(mine.get(id)!)}`),
    ];
    // Why: the newest event since the last snapshot (an approved plan, a booking, a breakdown…)
    const fresh = state.events.filter((e) => idSeq(e.id) > before.lastEvent);
    const cause = fresh[fresh.length - 1];
    let reason = cause ? cause.summary : "Dispatch updated your plan";
    const crew: { sl: string; en: string }[] = [];
    const planEvent = [...fresh].reverse().find((e) => e.type === "plan_applied");
    if (planEvent) {
      const run = state.agent.runs.find((r) => r.decision?.event_id === planEvent.id);
      reason = `Dispatcher approved a new plan${run?.decision?.title ? `: ${run.decision.title}` : ""}`;
      const executed = run?.decision?.executed ?? [];
      lines.push(...executed.filter((x) => mentions(x, vehicle)).map((x) => `· ${x}`));
      for (const n of run?.recommendation?.notifications ?? []) {
        if (mentions(n.recipient, vehicle)) crew.push({ sl: n.message_sl, en: n.message_en });
      }
    }
    setNotes((ns) => [...ns, { id: `${state.sim_time}-${lastEvent}`, at: state.sim_time, reason, lines, crew }]);
    chime();
  }, [state]); // eslint-disable-line react-hooks/exhaustive-deps -- runs once per snapshot

  return { notes, ack: () => setNotes((ns) => ns.slice(1)) };
}

// --- quick status (no AI: straight to events) --------------------------------------------------

/** A point about `ahead` metres along the route being driven (else the vehicle's own position). */
function pointAhead(v: Vehicle, leg: [number, number][] | undefined, ahead = 250): [number, number] {
  if (!leg || leg.length < 2) return [v.lat, v.lon];
  let left = ahead;
  for (let i = 1; i < leg.length; i++) {
    const [alat, alon] = leg[i - 1];
    const [blat, blon] = leg[i];
    const dy = (blat - alat) * 111_320;
    const dx = (blon - alon) * 111_320 * Math.cos((alat * Math.PI) / 180);
    const d = Math.hypot(dx, dy);
    if (d >= left) {
      const f = left / d;
      return [alat + (blat - alat) * f, alon + (blon - alon) * f];
    }
    left -= d;
  }
  return leg[leg.length - 1];
}

type QuickId = "breakdown" | "delay" | "closure" | "worse";

function QuickStatus({
  state,
  vehicle,
  trip,
  detail,
  notify,
}: {
  state: WorldSnapshot;
  vehicle: Vehicle;
  trip: Trip | undefined;
  detail: VehicleDetail | null;
  notify: (ok: boolean, text: string) => void;
}) {
  const [confirm, setConfirm] = useState<QuickId | null>(null);
  const [sending, setSending] = useState(false);
  const down = vehicle.status === "out_of_service";
  // "Patient worse" raises the level to any higher one. Without severity support the backend only
  // knows urgent and emergency (sent as "serious"), so an emergency cannot go higher there.
  const graded = severitySupported(state.trips);
  const higher: Level[] =
    trip && trip.kind === "patient"
      ? (graded ? LEVELS : (["serious", "urgent"] as Level[])).filter((l) => LEVEL_RANK[l] < LEVEL_RANK[levelOf(trip)])
      : [];
  const patientTrip = higher.length ? trip : undefined;

  // An unanswered "are you sure?" goes away by itself
  useEffect(() => {
    if (!confirm) return;
    const t = setTimeout(() => setConfirm(null), 10_000);
    return () => clearTimeout(t);
  }, [confirm]);

  const send = async (event: Record<string, unknown>) => {
    setSending(true);
    try {
      const rec = await postEvent(state.world, event);
      notify(true, `Sent to dispatch: ${rec.summary}`);
    } catch (e) {
      notify(false, e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
      setConfirm(null);
    }
  };

  const items: { id: QuickId; icon: LucideIcon; label: string; disabled: boolean }[] = [
    { id: "breakdown", icon: Wrench, label: "Breakdown", disabled: down },
    { id: "delay", icon: Timer, label: "Delay +10 min", disabled: down },
    { id: "closure", icon: Construction, label: "Road ahead closed", disabled: vehicle.type === "helicopter" },
    { id: "worse", icon: Siren, label: "Patient worse", disabled: !patientTrip },
  ];

  if (confirm) {
    const question: Record<QuickId, string> = {
      breakdown: `Report a breakdown of ${vehicle.id}? Your trips go back to dispatch.`,
      delay: `Tell dispatch ${vehicle.id} is delayed by 10 minutes?`,
      closure: "Report the road ahead as closed? Other vehicles will be routed around it.",
      worse: `Patient of ${patientTrip?.id ?? "this trip"} is worse: raise the severity to…`,
    };
    const [lat, lon] = pointAhead(vehicle, detail?.legs[0]);
    return (
      <div className="mdt-confirm" role="alertdialog" aria-label="Confirm">
        <div className="mdt-confirm-q">{question[confirm]}</div>
        <div className="mdt-confirm-actions">
          {confirm === "worse" && patientTrip ? (
            <>
              {[...higher].reverse().map((l) => (
                <button
                  key={l}
                  className={`mdt-btn ${l === "urgent" ? "warn" : "danger"}`}
                  disabled={sending}
                  onClick={() =>
                    send({
                      type: "priority_change",
                      trip_id: patientTrip.id,
                      priority: LEVEL_PRIORITY[l],
                      severity: l,
                      note: `crew of ${vehicle.id}: patient worse`,
                    })
                  }
                >
                  {/* without severity support the backend knows only "emergency" above urgent */}
                  {graded || l !== "serious" ? LEVEL_LABEL[l] : "Emergency"}
                </button>
              ))}
            </>
          ) : (
            <button
              className="mdt-btn danger"
              disabled={sending}
              onClick={() =>
                send(
                  confirm === "breakdown"
                    ? { type: "breakdown", vehicle_id: vehicle.id, note: `reported by the crew of ${vehicle.id}` }
                    : confirm === "delay"
                      ? { type: "delay", vehicle_id: vehicle.id, minutes: 10, note: `reported by the crew of ${vehicle.id}` }
                      : { type: "road_closure", lat, lon, radius_m: 150, description: `Road closed (reported by the crew of ${vehicle.id})` },
                )
              }
            >
              <Check /> Yes, send
            </button>
          )}
          <button className="mdt-btn" disabled={sending} onClick={() => setConfirm(null)}>
            <X /> Cancel
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="mdt-quick">
      {items.map((q) => (
        <button key={q.id} className="mdt-btn" disabled={q.disabled || sending} onClick={() => setConfirm(q.id)}>
          <q.icon className="mdt-quick-icon" /> {q.label}
        </button>
      ))}
    </div>
  );
}

// --- crew message (voice or text, through the AI message parser) -------------------------------

function CrewMessage({ world, vehicle, notify }: { world: World; vehicle: Vehicle; notify: (ok: boolean, text: string) => void }) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<MessageResult | null>(null);
  const busyRef = useRef(false);

  const send = async (raw: string) => {
    const text = raw.trim();
    if (text.length < 2 || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setResult(null);
    try {
      const r = await sendFieldMessage(world, text, vehicle.id);
      setResult(r);
      setDraft("");
      notify(true, r.needs_clarification ? `Dispatch asks: ${r.needs_clarification}` : `Dispatch understood: ${r.understood_en}`);
    } catch (e) {
      notify(false, `Not delivered: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };
  const speech = useSpeechInput({ onFinal: (heard) => (busyRef.current ? setDraft(heard) : void send(heard)) });
  const ptt = usePushToTalk(speech);

  return (
    <div className="mdt-talk">
      <div className="mdt-section-title">
        Message to dispatch
        {speech.supported && (
          <span className="lang-toggle" role="group" aria-label="Speech language">
            {SPEECH_LANGS.map((l) => (
              <button key={l.code} type="button" aria-pressed={speech.lang === l.code} onClick={() => speech.setLang(l.code)}>
                {l.label}
              </button>
            ))}
          </span>
        )}
      </div>
      <form
        className="mdt-talk-row"
        onSubmit={(e) => {
          e.preventDefault();
          void send(draft);
        }}
      >
        {speech.supported && (
          <button
            type="button"
            className={`mdt-btn mdt-ptt${speech.listening ? " listening" : ""}`}
            aria-pressed={speech.listening}
            title="Hold to talk and release to send, or tap once and speak"
            disabled={busy && !speech.listening}
            {...ptt}
          >
            <Mic /> {speech.listening ? "Listening…" : "Talk"}
          </button>
        )}
        <input
          className="mdt-input"
          value={speech.listening ? speech.interim : draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Sporočilo dispečerju…"
          aria-label="Message to dispatch"
          enterKeyHint="send"
        />
        <button type="submit" className="mdt-btn primary" disabled={busy || draft.trim().length < 2}>
          <Send /> {busy ? "…" : "Send"}
        </button>
      </form>
      {speech.supported && !speechSecureContext() && <div className="mdt-muted small">Voice needs HTTPS (or localhost).</div>}
      {speech.error && <div className="mdt-muted small warn">{speech.error}</div>}
      {result?.applied.map((a) => (
        <div key={a.id} className="mdt-muted small ok">
          <Check /> {a.summary}
        </div>
      ))}
    </div>
  );
}

// --- the console -------------------------------------------------------------------------------

function TabletConsole({
  state,
  vehicle,
  world,
  connected,
  night,
  toggleTheme,
}: {
  state: WorldSnapshot;
  vehicle: Vehicle;
  world: World;
  connected: boolean;
  night: boolean;
  toggleTheme: () => void;
}) {
  const [detail, setDetail] = useState<VehicleDetail | null>(null);
  const [nav, setNav] = useState<Navigation | null>(null);
  const [toast, setToast] = useState<{ ok: boolean; text: string; n: number } | null>(null);
  const chime = useChime();
  const { notes, ack } = useDispatchNotes(state, vehicle, chime);

  // Vehicle detail (route geometry, stops) and navigation: polled; both survive reconnects
  useEffect(() => {
    let stop = false;
    const load = () => {
      fetchVehicle(world, vehicle.id).then((d) => !stop && setDetail(d), () => undefined);
      fetchNavigation(world, vehicle.id).then((n) => !stop && setNav(n), () => !stop && setNav(null));
    };
    load();
    const t = setInterval(load, 3000);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, [world, vehicle.id]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast((x) => (x?.n === toast.n ? null : x)), toast.ok ? 7000 : 12000);
    return () => clearTimeout(t);
  }, [toast]);
  const notify = (ok: boolean, text: string) => setToast({ ok, text, n: Date.now() });

  const trips = new Map(state.trips.map((t) => [t.id, t]));
  const place = (id: string) => state.places.find((p) => p.id === id)?.name ?? id;
  const trip = vehicle.current_trip_id ? trips.get(vehicle.current_trip_id) : undefined;
  const nextTrip = !trip && vehicle.queue[0] ? trips.get(vehicle.queue[0]) : undefined;
  const job = trip ?? nextTrip;
  const myTrips = new Set([vehicle.current_trip_id, ...vehicle.queue].filter(Boolean) as string[]);
  const alerts: Alert[] = state.alerts.filter((a) => a.vehicle_id === vehicle.id || (a.trip_id && myTrips.has(a.trip_id)));
  const note = notes[0];

  return (
    <main className={`mdt ${night ? "night" : "day"}`}>
      <header className="mdt-top">
        <span className={`mdt-badge type-${vehicle.type}`}>
          <VehicleTypeIcon type={vehicle.type} /> {vehicle.id}
        </span>
        <strong className="mdt-name">{vehicle.name}</strong>
        <span className={`mdt-chip st-${vehicle.status}`}>{vehicleStatusText(vehicle, state.trips)}</span>
        {vehicle.grounded_until && <span className="mdt-chip warn">Grounded by fog until {fmtTime(vehicle.grounded_until)}</span>}
        <span className="mdt-spacer" />
        <span className={`mdt-chip ${world}`}>{world === "sim" ? "SIM" : "LIVE"}</span>
        <span className={`mdt-chip ${connected ? "ok" : "bad"}`}>
          <i className="dot" /> {connected ? "Online" : "Reconnecting"}
        </span>
        <span className="mdt-clock">{fmtTime(state.sim_time)}</span>
        <button className="mdt-btn icon" onClick={toggleTheme} aria-label={night ? "Day mode" : "Night mode"} title={night ? "Day mode" : "Night mode"}>
          {night ? <Sun /> : <Moon />}
        </button>
        <Link className="mdt-btn icon" to={`/vehicle?world=${world}`} aria-label="Switch vehicle" title="Switch vehicle">
          <ArrowLeftRight />
        </Link>
      </header>

      <section className="mdt-mapcol">
        <NavBanner nav={nav} vehicle={vehicle} trip={trip} state={state} />
        <div className="mdt-mapbox">
          <NavMap vehicle={vehicle} detail={detail} nav={nav} incidents={state.incidents} />
          {toast &&<div className={`mdt-toast ${toast.ok ? "ok" : "bad"}`}>{toast.text}</div>}
        </div>
      </section>

      <aside className="mdt-side">
        <div className="mdt-scroll">
          {alerts.length > 0 && (
            <div className="mdt-alerts">
              {alerts.map((a) => (
                <div key={a.id} className={`mdt-alert sev-${a.severity}`}>
                  <TriangleAlert /> <span>{a.message}</span>
                </div>
              ))}
            </div>
          )}

          <section className="mdt-card">
            <div className="mdt-section-title">{trip ? "Current job" : nextTrip ? "Next job" : "Job"}</div>
            {job ? (
              <div className="mdt-job">
                <div className="mdt-job-head">
                  <span className="mdt-trip-id">{job.id}</span>
                  <span className="mdt-muted">{job.status === "onboard" ? (job.kind === "equipment" ? "load on board" : "patient on board") : humanize(job.status)}</span>
                </div>
                <div className="mdt-job-sev">
                  <SeverityBadge trip={job} size="lg" />
                </div>
                {job.status !== "onboard" && (
                  <div className="mdt-job-resp">
                    <ResponseLine trip={job} now={state.sim_time} />
                  </div>
                )}
                <div className="mdt-job-who">
                  {job.kind === "equipment" ? `Equipment: ${job.cargo ?? "equipment"}` : `Patient ${job.patient ?? job.label}`}
                  {job.kind === "patient" && <span className="mdt-needs">{job.needs}</span>}
                </div>
                <div className="mdt-job-route">
                  <span>{place(job.pickup_id)}</span>
                  <span className="mdt-arrow">→</span>
                  <span>{place(job.dropoff_id)}</span>
                </div>
                <div className="mdt-job-times">
                  <span>
                    Ready <strong>{fmtTime(job.pickup_after)}</strong>
                  </span>
                  <span>
                    Due <strong>{fmtTime(job.due_by)}</strong>
                  </span>
                  <span>
                    ETA <strong className={(job.delay_min ?? 0) >= 5 ? "late" : ""}>{fmtTime(job.eta_dropoff)}</strong>
                    {(job.delay_min ?? 0) >= 5 && <span className="late"> +{Math.round(job.delay_min ?? 0)}′</span>}
                  </span>
                </div>
                {job.note && (
                  <div className="mdt-note">
                    <NotebookText /> <span>{job.note}</span>
                  </div>
                )}
              </div>
            ) : (
              <div className="mdt-muted">{vehicle.status === "out_of_service" ? "Out of service." : "No job. Standing by for dispatch."}</div>
            )}
          </section>

          {detail && detail.stops.length > 0 && (
            <section className="mdt-card">
              <div className="mdt-section-title">Next stops</div>
              <ol className="mdt-stops">
                {detail.stops.slice(0, 6).map((s, i) => (
                  <li key={i} className={(s.delay_min ?? 0) >= 5 ? "late" : ""}>
                    <span className={`mdt-stop-num stop-${s.kind}`}>{s.kind === "base" ? <House /> : i + 1}</span>
                    <span className="mdt-stop-place">
                      {s.kind === "pickup" ? "Pick up" : s.kind === "dropoff" ? "Drop off" : "Base"} · {s.place}
                      {s.trip_id && <span className="mdt-muted"> · {s.trip_id}</span>}
                      {s.kind === "pickup" && trips.get(s.trip_id ?? "") && levelOf(trips.get(s.trip_id ?? "")!) !== "routine" && (
                        <>
                          {" "}
                          <SeverityBadge trip={trips.get(s.trip_id ?? "")!} compact />
                        </>
                      )}
                      {s.kind === "pickup" && s.ready_at && <span className="mdt-muted"> · ready {fmtTime(s.ready_at)}</span>}
                    </span>
                    <span className="mdt-stop-eta">{s.eta ? fmtTime(s.eta) : "—"}</span>
                  </li>
                ))}
              </ol>
            </section>
          )}

          <section className="mdt-card">
            <div className="mdt-section-title">Vehicle</div>
            <div className="mdt-fuel">
              <Fuel /> {Math.round(vehicle.fuel_pct)}%
              <div className="mdt-bar">
                <div className={`mdt-bar-fill ${vehicle.fuel_pct < 10 ? "bad" : vehicle.fuel_pct < 20 ? "warn" : "ok"}`} style={{ width: `${Math.max(2, vehicle.fuel_pct)}%` }} />
              </div>
              <span className="mdt-muted">{vehicle.km_today.toFixed(1)} km today</span>
            </div>
            <div className="mdt-crew">
              {vehicle.crew.map((c) => (
                <span key={c.name}>
                  {c.name.replace(" (fictional)", "")} <span className="mdt-muted">· {c.role}</span>
                </span>
              ))}
            </div>
            {vehicle.shift_end && <div className="mdt-muted">Shift until {fmtTime(vehicle.shift_end)}</div>}
          </section>
        </div>

        <div className="mdt-input-area">
          <CrewMessage world={world} vehicle={vehicle} notify={notify} />
          <QuickStatus state={state} vehicle={vehicle} trip={trip} detail={detail} notify={notify} />
        </div>
      </aside>

      {note && (
        <div className="mdt-note-overlay" role="alertdialog" aria-label="Message from dispatch">
          <div className="mdt-dispatch">
            <div className="mdt-dispatch-head">
              <Mail /> Message from dispatch <span className="mdt-muted">· {fmtTime(note.at)}</span>
              {notes.length > 1 && <span className="mdt-chip">+{notes.length - 1} more</span>}
            </div>
            <div className="mdt-dispatch-reason">{note.reason}</div>
            <ul className="mdt-dispatch-lines">
              {note.lines.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
            {note.crew.map((c, i) => (
              <div key={i} className="mdt-dispatch-crew">
                <div>
                  <span className="lang-tag">SL</span>
                  {c.sl}
                </div>
                <div className="mdt-muted">
                  <span className="lang-tag">EN</span>
                  {c.en}
                </div>
              </div>
            ))}
            <button className="mdt-btn primary big" onClick={ack}>
              <Check /> Acknowledge
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
