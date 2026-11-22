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
import { fmtTime, nightText, tripStatusLabel, vehicleStatusLabel, vehicleStatusText } from "../format";
import { fmtNum, t as tx, tOr, useLang, useT, type Lang } from "../i18n";
import { LangToggle } from "../LangToggle";
import { VehicleTypeIcon } from "../icons";
import { NavMap } from "../NavMap";
import { conditionText, LEVEL_LABEL, LEVEL_PRIORITY, LEVEL_RANK, LEVELS, levelOf, severitySupported, type Level } from "../severity";
import { ResponseLine, SeverityBadge } from "../SeverityBadge";
import { doctorJobLine } from "../doctor";
import { DoctorTag, OriginTag } from "../DoctorTag";
import { bilingualLines } from "../ErrorText";
import { AdminLock } from "../AdminLock";
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
  const t = useT();
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
        <p className="mdt-loading">{t("common.connecting", { url: API_URL })}</p>
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
  const t = useT();
  return (
    <main className={`mdt mdt-picker ${night ? "night" : "day"}`}>
      <div className="mdt-picker-lang">
        <LangToggle className="mdt-uilang" />
      </div>
      <h1>{missing ? t("tab.notFound", { id: missing }) : t("tab.pickerTitle")}</h1>
      <p className="mdt-muted">{t("tab.pickerChoose", { world: t(world === "sim" ? "tab.worldSim" : "tab.worldLive") })}</p>
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
        {t("tab.worldLabel")} <Link to={`/vehicle?world=sim`}>{t("tab.worldSim")}</Link> · <Link to={`/vehicle?world=live`}>{t("tab.worldLive")}</Link>
      </p>
    </main>
  );
}

// --- navigation banner -------------------------------------------------------------------------

/** "300 m", "1.2 km" ("1,2 km" in Slovenian). */
const fmtDist = (m: number) => (m < 1000 ? `${Math.max(10, Math.round(m / 10) * 10)} m` : `${fmtNum(m / 1000, m < 10_000 ? 1 : 0)} km`);

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

/** Feminine head nouns of Slovenian street names ("Zaloška cesta", "Ulica Janeza Pavla II."). */
const FEMININE_HEADS = new Set(["cesta", "ulica", "steza", "pot", "obvoznica", "avtocesta", "vpadnica", "magistrala", "promenada", "pešpot", "obala", "vas"]);

/**
 * A Slovenian street name in the accusative, for "zavijte desno na Zaloško cesto": the feminine
 * head noun and the adjectives before it change -a to -o ("Zaloška cesta" -> "Zaloško cesto",
 * "Ulica bratov Učakar" -> "Ulico bratov Učakar"). Masculine and neuter names ("Trg OF",
 * "Prešernov trg") are the same in the accusative, so anything else stays exactly as given.
 */
function slAccusative(name: string): string {
  const words = name.split(" ");
  const head = words.findIndex((w) => FEMININE_HEADS.has(w.toLowerCase()));
  if (head < 0 || head > 3) return name;
  return words.map((w, i) => (i <= head && /[a-zčšž]a$/i.test(w) ? `${w.slice(0, -1)}${w.endsWith("A") ? "O" : "o"}` : w)).join(" ");
}

/** The manoeuvre as one instruction ("Turn right onto Zaloška cesta" / "Zavijte desno na Zaloško cesto"). */
function instruction(s: NavStep, lang: Lang): string {
  const ref = s.ref ? (/^\d/.test(s.ref) ? tx("tab.nav.roadRef", { ref: s.ref }) : s.ref) : "";
  const named = s.name ? (lang === "sl" ? slAccusative(s.name) : s.name) : "";
  const road = named || ref;
  const onto = road ? tx("tab.nav.onto", { road }) : "";
  const ontoThen = road ? tx("tab.nav.ontoThen", { road }) : "";
  const mod = s.modifier ?? "";
  const side = mod.includes("left") ? "left" : mod.includes("right") ? "right" : "";
  const dir = (m: string) => tOr(`tab.dir.${m}`, m);
  const p = (extra: Record<string, string | number>) => ({ onto, ontoThen, ...extra });
  const sideWord = side ? tx(side === "left" ? "tab.nav.sideWord.left" : "tab.nav.sideWord.right") : "";
  const onSide = side ? tx(side === "left" ? "tab.nav.onSide.left" : "tab.nav.onSide.right") : "";
  switch (s.type) {
    case "arrive":
      return side ? tx("tab.nav.arriveSide", { side: tx(side === "left" ? "tab.nav.side.left" : "tab.nav.side.right") }) : tx("tab.nav.arrive");
    case "depart":
      return tx("tab.nav.depart", p({}));
    case "roundabout":
    case "rotary":
      return s.exit ? tx("tab.nav.roundaboutExit", p({ exit: s.exit })) : tx("tab.nav.roundaboutEnter", p({}));
    case "exit roundabout":
    case "exit rotary":
      return tx("tab.nav.roundaboutLeave", p({}));
    case "roundabout turn":
      return tx("tab.nav.roundaboutTurn", p({ dir: dir(mod) }));
    case "merge":
      return tx("tab.nav.merge", p({ side: sideWord }));
    case "on ramp":
      return tx("tab.nav.onRamp", p({ onSide }));
    case "off ramp":
      return tx("tab.nav.offRamp", p({ onSide }));
    case "fork":
      return tx("tab.nav.fork", p({ dir: dir(side || "straight") }));
    case "end of road":
      return tx("tab.nav.endOfRoad", p({ dir: dir(side || mod) }));
    case "continue":
    case "new name":
      return mod && mod !== "straight" ? tx("tab.nav.keep", p({ dir: dir(mod) })) : tx("tab.nav.continue", p({}));
    default:
      if (mod === "uturn") return tx("tab.nav.uturn", p({}));
      if (mod === "straight" || !mod) return tx("tab.nav.straight", p({}));
      if (mod.startsWith("slight")) return tx("tab.nav.bear", p({ dir: dir(side) }));
      return tx("tab.nav.turn", p({ dir: dir(mod) }));
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

const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"] as const;

function NavBanner({ nav, vehicle, trip, state }: { nav: Navigation | null; vehicle: Vehicle; trip: Trip | undefined; state: WorldSnapshot }) {
  const t = useT();
  const lang = useLang();
  const kindText = (kind: "pickup" | "dropoff" | "base") => t(`tab.kind.${kind}`);
  if (vehicle.status === "out_of_service")
    return (
      <div className="mdt-banner down">
        <TriangleAlert /> {t("tab.outOfService")}
      </div>
    );
  if (vehicle.waiting_until && Date.parse(vehicle.waiting_until) > Date.parse(state.sim_time) && trip) {
    return (
      <div className="mdt-banner">
        <span className="mdt-turn-icon">
          <Clock />
        </span>
        <div>
          <div className="mdt-instr">{t("tab.waitingPatient", { time: fmtTime(vehicle.waiting_until) })}</div>
          <div className="mdt-next-stop">{t("tab.atPickup", { place: state.places.find((p) => p.id === trip.pickup_id)?.name })}</div>
        </div>
      </div>
    );
  }
  if (!nav || !nav.target) {
    const busy =
      vehicle.status === "loading" ? t("tab.loadingDots") : vehicle.status === "idle" ? t("tab.standingBy") : vehicleStatusLabel(vehicle.status);
    return <div className="mdt-banner idle">{busy}</div>;
  }
  const eta = nav.eta ? fmtTime(nav.eta) : "–";
  // Standing still for a while: loading, unloading or held by an operator delay
  const busyUntil = vehicle.busy_until && Date.parse(vehicle.busy_until) > Date.parse(state.sim_time) ? vehicle.busy_until : null;
  const busyText =
    vehicle.status === "loading"
      ? trip?.kind === "equipment"
        ? t("tab.busy.equipment")
        : t("tab.busy.patient")
      : vehicle.status === "returning"
        ? t("tab.busy.unloading")
        : vehicle.busy_reason === "turnout"
          ? t("tab.busy.turnout")
          : t("tab.busy.held");
  const stopLine = (
    <div className="mdt-next-stop">
      {kindText(nav.target.kind)}: <strong>{nav.target.name}</strong>
      {nav.remaining_m != null && <> · {fmtDist(nav.remaining_m)}</>} · {t("tab.eta")} <strong>{eta}</strong>
      {nav.detour && (
        <span className="mdt-detour">
          {" "}
          <CornerUpRight /> {t("tab.detour")}
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
          <div className="mdt-instr">{t("tab.busyUntil", { what: busyText, time: fmtTime(busyUntil) })}</div>
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
          <div className="mdt-instr">{t("tab.arrived", { kind: kindText(nav.target.kind) })}</div>
          <div className="mdt-next-stop">
            <strong>{nav.target.name}</strong>
            {vehicle.status === "loading" ? t("tab.arrivedLoading") : ""}
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
            {t("tab.fly", { deg: String(b).padStart(3, "0"), compass: t(`tab.compass.${COMPASS[Math.round(b / 45) % 8]}`) })}
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
          <div className="mdt-instr">{t("tab.driveTo", { place: nav.target.name })}</div>
          {stopLine}
          {nav.status === "pending" && <div className="mdt-muted small">{t("tab.loadingDirections")}</div>}
        </div>
      </div>
    );
  }
  return (
    <div className="mdt-banner">
      <ManeuverIcon step={next} />
      <div>
        <div className="mdt-dist">{next.distance_m < 30 ? t("tab.now") : t("tab.inDist", { dist: fmtDist(next.distance_m) })}</div>
        <div className="mdt-instr">{instruction(next, lang)}</div>
        {stopLine}
        {then && then.type !== "arrive" && (
          <div className="mdt-then">
            {t("tab.then", { instr: instruction(then, lang).replace(/^./, (c) => c.toLowerCase()), dist: fmtDist(then.distance_m) })}
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

    // (written in the language of the moment; a later switch leaves earlier notes as they were)
    const lines = [
      ...added.map((id) => {
        const t = trip(id)!;
        const cond = conditionText(t);
        return tx("tab.note.newJob", {
          id: t.id,
          level: LEVEL_LABEL[levelOf(t)],
          cond: cond ? ` · ${cond}` : "",
          label: t.label,
          from: place(t.pickup_id),
          to: place(t.dropoff_id),
        });
      }),
      ...removed.map((id) => {
        const t = trip(id);
        return t?.vehicle_id ? tx("tab.note.movedTo", { id, vehicle: t.vehicle_id }) : tx("tab.note.handedBack", { id });
      }),
      ...redirected.map((id) => tx("tab.note.nowGoesTo", { id, place: place(mine.get(id)!) })),
    ];
    // Why: the newest event since the last snapshot (an approved plan, a booking, a breakdown…)
    const fresh = state.events.filter((e) => idSeq(e.id) > before.lastEvent);
    const cause = fresh[fresh.length - 1];
    let reason = cause ? cause.summary : tx("tab.note.updated");
    const crew: { sl: string; en: string }[] = [];
    const planEvent = [...fresh].reverse().find((e) => e.type === "plan_applied");
    if (planEvent) {
      const run = state.agent.runs.find((r) => r.decision?.event_id === planEvent.id);
      reason = run?.decision?.title ? tx("tab.note.approvedTitle", { title: run.decision.title }) : tx("tab.note.approved");
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
  const t = useT();
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
    const timer = setTimeout(() => setConfirm(null), 10_000);
    return () => clearTimeout(timer);
  }, [confirm]);

  const send = async (event: Record<string, unknown>) => {
    setSending(true);
    try {
      const rec = await postEvent(state.world, event);
      notify(true, t("tab.quick.sent", { summary: rec.summary }));
    } catch (e) {
      notify(false, e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
      setConfirm(null);
    }
  };

  const items: { id: QuickId; icon: LucideIcon; label: string; disabled: boolean }[] = [
    { id: "breakdown", icon: Wrench, label: t("tab.quick.breakdown"), disabled: down },
    { id: "delay", icon: Timer, label: t("tab.quick.delay"), disabled: down },
    { id: "closure", icon: Construction, label: t("tab.quick.closure"), disabled: vehicle.type === "helicopter" },
    { id: "worse", icon: Siren, label: t("tab.quick.worse"), disabled: !patientTrip },
  ];

  if (confirm) {
    const question: Record<QuickId, string> = {
      breakdown: t("tab.quick.qBreakdown", { id: vehicle.id }),
      delay: t("tab.quick.qDelay", { id: vehicle.id }),
      closure: t("tab.quick.qClosure"),
      worse: t("tab.quick.qWorse", { id: patientTrip?.id ?? t("tab.quick.thisTrip") }),
    };
    const [lat, lon] = pointAhead(vehicle, detail?.legs[0]);
    return (
      <div className="mdt-confirm" role="alertdialog" aria-label={t("tab.quick.confirm")}>
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
                  {graded || l !== "serious" ? LEVEL_LABEL[l] : t("tab.quick.emergency")}
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
              <Check /> {t("tab.quick.yesSend")}
            </button>
          )}
          <button className="mdt-btn" disabled={sending} onClick={() => setConfirm(null)}>
            <X /> {t("common.cancel")}
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
  const t = useT();
  const lang = useLang();
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
      // what the AI understood, in the UI language (the backend sends both)
      const understood = lang === "sl" ? r.understood_sl || r.understood_en : r.understood_en;
      notify(true, r.needs_clarification ? t("tab.msg.asks", { q: r.needs_clarification }) : t("tab.msg.understood", { text: understood }));
    } catch (e) {
      notify(false, t("tab.msg.notDelivered", { error: bilingualLines(e instanceof Error ? e.message : String(e)) }));
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
        {t("tab.msgToDispatch")}
        {speech.supported && (
          <span className="lang-toggle" role="group" aria-label={t("tab.speechLang")} title={t("tab.speechLang")}>
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
            title={t("tab.msg.pttTitle")}
            disabled={busy && !speech.listening}
            {...ptt}
          >
            <Mic /> {speech.listening ? t("tab.msg.listening") : t("tab.msg.talk")}
          </button>
        )}
        <input
          className="mdt-input"
          value={speech.listening ? speech.interim : draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t("tab.msgPlaceholder")}
          aria-label={t("tab.msgToDispatch")}
          enterKeyHint="send"
        />
        <button type="submit" className="mdt-btn primary" disabled={busy || draft.trim().length < 2}>
          <Send /> {busy ? "…" : t("tab.send")}
        </button>
      </form>
      {speech.supported && !speechSecureContext() && <div className="mdt-muted small">{t("tab.msg.needsHttps")}</div>}
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
  const t = useT();
  const lang = useLang();
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
    const timer = setInterval(load, 3000);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [world, vehicle.id]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast((x) => (x?.n === toast.n ? null : x)), toast.ok ? 7000 : 12000);
    return () => clearTimeout(timer);
  }, [toast]);
  const notify = (ok: boolean, text: string) => setToast({ ok, text, n: Date.now() });
  const needsText = (needs: string) => tOr(`tab.needs.${needs}`, needs);
  const roleText = (role: string) => tOr(`tab.role.${role}`, role);

  const trips = new Map(state.trips.map((x) => [x.id, x]));
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
        <OriginTag v={vehicle} />
        <span className={`mdt-chip st-${vehicle.status}`}>{vehicleStatusText(vehicle, state.trips)}</span>
        {vehicle.grounded_until && <span className="mdt-chip warn">{t("tab.grounded", { time: fmtTime(vehicle.grounded_until) })}</span>}
        {nightText(vehicle) && <span className="mdt-chip warn">{nightText(vehicle)}</span>}
        <span className="mdt-spacer" />
        <span className={`mdt-chip ${world}`}>{world === "sim" ? t("tab.chipSim") : t("tab.chipLive")}</span>
        <span className={`mdt-chip ${connected ? "ok" : "bad"}`}>
          <i className="dot" /> {connected ? t("tab.online") : t("tab.reconnecting")}
        </span>
        <span className="mdt-clock">{fmtTime(state.sim_time)}</span>
        <AdminLock variant="tablet" />
        <LangToggle className="mdt-uilang" />
        <button
          className="mdt-btn icon"
          onClick={toggleTheme}
          aria-label={night ? t("tab.dayMode") : t("tab.nightMode")}
          title={night ? t("tab.dayMode") : t("tab.nightMode")}
        >
          {night ? <Sun /> : <Moon />}
        </button>
        <Link className="mdt-btn icon" to={`/vehicle?world=${world}`} aria-label={t("tab.switchVehicle")} title={t("tab.switchVehicle")}>
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
            <div className="mdt-section-title">{trip ? t("tab.currentJob") : nextTrip ? t("tab.nextJob") : t("tab.job")}</div>
            {job ? (
              <div className="mdt-job">
                <div className="mdt-job-head">
                  <span className="mdt-trip-id">{job.id}</span>
                  <span className="mdt-muted">
                    {vehicle.type === "doctor"
                      ? `${job.vehicle_id ?? t("tab.noAmbulanceYet")}${
                          job.vehicle_id ? (job.status === "onboard" ? `: ${t("tab.patientOnBoard")}` : `: ${tripStatusLabel(job.status)}`) : ""
                        }`
                      : job.status === "onboard"
                        ? job.kind === "equipment"
                          ? t("tab.loadOnBoard")
                          : t("tab.patientOnBoard")
                        : tripStatusLabel(job.status)}
                  </span>
                </div>
                {vehicle.type === "doctor" && <div className="mdt-job-doctor">{doctorJobLine(vehicle, job, place)}</div>}
                {job.call && (
                  <div className="mdt-call">
                    <div className="mdt-call-id">
                      {job.call.call_id}
                      {job.call.address && <span> · {job.call.address}</span>}
                    </div>
                    {(job.call.text_sl || job.call.text_en) && (
                      <blockquote className="mdt-words">
                        {/* the caller's own words, then the translation (both kept in either language) */}
                        {job.call.text_sl && <div>»{job.call.text_sl}«</div>}
                        {job.call.text_en && job.call.text_en !== job.call.text_sl && <div className="mdt-muted">{job.call.text_en}</div>}
                      </blockquote>
                    )}
                  </div>
                )}
                <div className="mdt-job-sev">
                  <SeverityBadge trip={job} size="lg" />
                  <DoctorTag trip={job} vehicles={state.vehicles} now={state.sim_time} size="lg" />
                </div>
                {job.status !== "onboard" && vehicle.type !== "doctor" && (
                  <div className="mdt-job-resp">
                    <ResponseLine trip={job} now={state.sim_time} />
                  </div>
                )}
                <div className="mdt-job-who">
                  {job.kind === "equipment"
                    ? t("tab.equipmentLine", { cargo: job.cargo ?? t("tab.equipment") })
                    : t("tab.patientLine", { name: job.patient ?? job.label })}
                  {job.kind === "patient" && <span className="mdt-needs">{needsText(job.needs)}</span>}
                </div>
                <div className="mdt-job-route">
                  <span>{place(job.pickup_id)}</span>
                  <span className="mdt-arrow">→</span>
                  <span>{place(job.dropoff_id)}</span>
                </div>
                <div className="mdt-job-times">
                  <span>
                    {t("tab.ready")} <strong>{fmtTime(job.pickup_after)}</strong>
                  </span>
                  <span>
                    {t("tab.due")} <strong>{fmtTime(job.due_by)}</strong>
                  </span>
                  <span>
                    {t("tab.eta")} <strong className={(job.delay_min ?? 0) >= 5 ? "late" : ""}>{fmtTime(job.eta_dropoff)}</strong>
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
              <div className="mdt-muted">{vehicle.status === "out_of_service" ? t("tab.outOfServiceShort") : t("tab.noJob")}</div>
            )}
          </section>

          {detail && detail.stops.length > 0 && (
            <section className="mdt-card">
              <div className="mdt-section-title">{t("tab.nextStops")}</div>
              <ol className="mdt-stops">
                {detail.stops.slice(0, 6).map((s, i) => (
                  <li key={i} className={(s.delay_min ?? 0) >= 5 ? "late" : ""}>
                    <span className={`mdt-stop-num stop-${s.kind}`}>{s.kind === "base" ? <House /> : i + 1}</span>
                    <span className="mdt-stop-place">
                      {s.kind === "pickup" ? t("tab.stop.pickup") : s.kind === "dropoff" ? t("tab.stop.dropoff") : t("tab.stop.base")} · {s.place}
                      {s.trip_id && <span className="mdt-muted"> · {s.trip_id}</span>}
                      {s.kind === "pickup" && trips.get(s.trip_id ?? "") && levelOf(trips.get(s.trip_id ?? "")!) !== "routine" && (
                        <>
                          {" "}
                          <SeverityBadge trip={trips.get(s.trip_id ?? "")!} compact />
                        </>
                      )}
                      {s.kind === "pickup" && s.ready_at && <span className="mdt-muted">{t("tab.stop.ready", { time: fmtTime(s.ready_at) })}</span>}
                    </span>
                    <span className="mdt-stop-eta">{s.eta ? fmtTime(s.eta) : "—"}</span>
                  </li>
                ))}
              </ol>
            </section>
          )}

          <section className="mdt-card">
            <div className="mdt-section-title">{t("tab.vehicle")}</div>
            <div className="mdt-fuel">
              <Fuel /> {Math.round(vehicle.fuel_pct)}%
              <div className="mdt-bar">
                <div className={`mdt-bar-fill ${vehicle.fuel_pct < 10 ? "bad" : vehicle.fuel_pct < 20 ? "warn" : "ok"}`} style={{ width: `${Math.max(2, vehicle.fuel_pct)}%` }} />
              </div>
              <span className="mdt-muted">{t("tab.kmToday", { km: fmtNum(vehicle.km_today, 1, lang) })}</span>
            </div>
            <div className="mdt-crew">
              {vehicle.crew.map((c) => (
                <span key={c.name}>
                  {c.name.replace(" (fictional)", "")} <span className="mdt-muted">· {roleText(c.role)}</span>
                </span>
              ))}
            </div>
            {vehicle.shift_end && <div className="mdt-muted">{t("tab.shiftUntil", { time: fmtTime(vehicle.shift_end) })}</div>}
          </section>
        </div>

        <div className="mdt-input-area">
          <CrewMessage world={world} vehicle={vehicle} notify={notify} />
          <QuickStatus state={state} vehicle={vehicle} trip={trip} detail={detail} notify={notify} />
        </div>
      </aside>

      {note && (
        <div className="mdt-note-overlay" role="alertdialog" aria-label={t("tab.note.dialog")}>
          <div className="mdt-dispatch">
            <div className="mdt-dispatch-head">
              <Mail /> {t("tab.note.dialog")} <span className="mdt-muted">· {fmtTime(note.at)}</span>
              {notes.length > 1 && <span className="mdt-chip">{t("tab.note.more", { count: notes.length - 1 })}</span>}
            </div>
            <div className="mdt-dispatch-reason">{note.reason}</div>
            <ul className="mdt-dispatch-lines">
              {note.lines.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
            {/* the crew message in both languages, the UI language first */}
            {note.crew.map((c, i) => {
              const sl = (
                <div key="sl" className={lang === "sl" ? undefined : "mdt-muted"}>
                  <span className="lang-tag">SL</span>
                  {c.sl}
                </div>
              );
              const en = (
                <div key="en" className={lang === "sl" ? "mdt-muted" : undefined}>
                  <span className="lang-tag">EN</span>
                  {c.en}
                </div>
              );
              return (
                <div key={i} className="mdt-dispatch-crew">
                  {lang === "sl" ? [sl, en] : [en, sl]}
                </div>
              );
            })}
            <button className="mdt-btn primary big" onClick={ack}>
              <Check /> {t("tab.note.ack")}
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
