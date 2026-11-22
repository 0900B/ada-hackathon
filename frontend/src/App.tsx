import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useMatch, useSearchParams } from "react-router";
import {
  API_URL,
  activateSurge,
  generalRun,
  postEvent,
  standDownSurge,
  useWorldState,
  type Alert,
  type EventRecord,
  type Kpis,
  fetchVehicle,
  type Trip,
  type VehicleDetail,
  type World,
  type WorldSnapshot,
} from "./api";
import { AdminLock } from "./AdminLock";
import { fmtDec, fmtNum, t as tx, tOr, tr, useLang, useLangRoot, useT } from "./i18n";
import { tripStatusLabel } from "./format";
import { LangToggle } from "./LangToggle";
import type { AgentKeys } from "./AgentPanel";
import { BookingForm } from "./BookingForm";
import {
  Car,
  CircleAlert,
  CircleCheck,
  CloudRain,
  CloudSnow,
  Construction,
  Database,
  Octagon,
  PhoneIncoming,
  Sun,
  TrafficCone,
  Users,
  X,
} from "lucide-react";
import { BRAND } from "./brand";
import { EventsPanel } from "./EventsPanel";
import { useHotkeys } from "./hotkeys";
import { ShortcutsHelp } from "./ShortcutsHelp";
import { CrewPage } from "./pages/CrewPage";
import { ScenariosPanel } from "./ScenariosPanel";
import { EmergencyPicker } from "./EmergencyPicker";
import { AiDispatcherPanel, type CaseFocus } from "./AiDispatcherPanel";
import { DemoButtons } from "./DemoButtons";
import { MissingEndpoint, randomCall, randomIncident, targetErrorText, useDemoApi } from "./demoInject";
import { bilingualLines } from "./ErrorText";
import { VehicleCard } from "./VehicleCard";
import { VehicleStrip } from "./VehicleStrip";
import { OpsControls } from "./OpsControls";
import { fmtTime } from "./format";
import { compareTrips, LEVEL_RANK, levelOf, targetMisses, type ResponseInfo } from "./severity";
import { ResponseLine, SeverityBadge } from "./SeverityBadge";
import { doctorMisses, type DoctorInfo } from "./doctor";
import { DoctorTag, OriginTag } from "./DoctorTag";
import { MapView, type ClickMode } from "./MapView";
import { AuditPage } from "./pages/AuditPage";
import { FleetPage } from "./pages/FleetPage";
import { ReportsPage } from "./pages/ReportsPage";

// The tablet view loads separately: its navigation map patches Leaflet for rotation (leaflet-rotate)
const TabletPage = lazy(() => import("./pages/TabletPage").then((m) => ({ default: m.TabletPage })));

type Send = (event: Record<string, unknown>) => Promise<void>;
type Toast = { kind: "ok" | "error"; text: string; sticky: boolean; n: number };
type Notify = (kind: "ok" | "error", text: string, sticky?: boolean) => void;
type Tab = "ai" | "scenarios" | "events" | "book" | "alerts";

const unassignedTotal = (k: Kpis) => k.unassigned.emergency + k.unassigned.urgent + k.unassigned.scheduled;

function describe(rec: EventRecord): string {
  const b = rec.kpis_before;
  const a = rec.kpis_after;
  return tx("dash.describe", {
    summary: rec.summary, // the backend's own words (English)
    count: rec.affected_trip_ids.length,
    lateBefore: b.late_trips,
    lateAfter: a.late_trips,
    unBefore: unassignedTotal(b),
    unAfter: unassignedTotal(a),
  });
}

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Layout: header with navigation, then the routed page. Each page opens its own live connection. */
export default function App() {
  useLangRoot(); // a language switch re-renders the whole tree (no remount: forms and selections stay)
  const t = useT();
  const crew = useMatch("/crew/*");
  const tablet = useMatch("/vehicle/*");
  const { pathname } = useLocation();
  // Fleet and Crew view follow the world of the dashboard you came from
  const [lastWorld, setLastWorld] = useState<World>("live");
  useEffect(() => {
    if (pathname === "/sim" || pathname === "/live") setLastWorld(pathname === "/sim" ? "sim" : "live");
  }, [pathname]);

  if (crew || tablet) {
    // Crew view (phone) and in-vehicle tablet: full screen, without the dispatcher header
    return (
      <Routes>
        <Route path="/crew/:vehicleId?" element={<CrewPage />} />
        <Route
          path="/vehicle/:vehicleId?"
          element={
            <Suspense fallback={<div className="loading">{t("dash.loadingTablet")}</div>}>
              <TabletPage />
            </Suspense>
          }
        />
      </Routes>
    );
  }
  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <h1 className="wordmark">{BRAND.product}</h1>
          <span className="brand-sub" title={`${BRAND.tagline} · ${BRAND.operator}`}>
            {BRAND.tagline} · <strong>{BRAND.operator}</strong>
          </span>
        </div>
        <nav className="nav">
          <NavLink to="/live">{t("dash.nav.live")}</NavLink>
          <NavLink to="/sim">{t("dash.nav.sim")}</NavLink>
          <NavLink to={`/fleet?world=${lastWorld}`}>{t("dash.nav.fleet")}</NavLink>
          <NavLink to={`/reports?world=${lastWorld}`}>{t("dash.nav.reports")}</NavLink>
          <NavLink to="/audit">{t("dash.nav.audit")}</NavLink>
          <NavLink to={`/crew?world=${lastWorld === "live" ? "live" : "sim"}`}>{t("dash.nav.crew")}</NavLink>
        </nav>
        <span className="header-help muted">{tr("dash.header.help", { key: <kbd>?</kbd> })}</span>
        <AdminLock />
        <LangToggle />
      </header>
      <Routes>
        <Route path="/" element={<Navigate to="/live" replace />} />
        <Route path="/live" element={<WorldPage key="live" world="live" />} />
        <Route path="/sim" element={<WorldPage key="sim" world="sim" />} />
        <Route path="/fleet" element={<FleetRoute />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </div>
  );
}

function WorldPage({ world }: { world: World }) {
  const t = useT();
  const { state, connected } = useWorldState(world);
  if (!state) return <div className="loading">{t("common.connecting", { url: API_URL })}</div>;
  return (
    <>
      <StatusBar state={state} connected={connected} />
      <Dashboard state={state} />
    </>
  );
}

function FleetRoute() {
  const [params] = useSearchParams();
  const world: World = params.get("world") === "sim" ? "sim" : "live";
  return <FleetWorld key={world} world={world} />;
}

function FleetWorld({ world }: { world: World }) {
  const t = useT();
  const { state, connected } = useWorldState(world);
  if (!state) return <div className="loading">{t("common.connecting", { url: API_URL })}</div>;
  return (
    <>
      <StatusBar state={state} connected={connected} />
      <FleetPage state={state} />
    </>
  );
}

function NotFound() {
  const t = useT();
  return (
    <main className="page">
      <h2>{t("dash.notFound")}</h2>
      <Link to="/">{t("dash.backToDashboard")}</Link>
    </main>
  );
}

function Dashboard({ state }: { state: WorldSnapshot }) {
  const t = useT();
  const world = state.world;
  const sim = state.hypothetical;
  const [mode, setMode] = useState<ClickMode>(null);
  const [pendingCall, setPendingCall] = useState<{ lat: number; lon: number } | null>(null); // where the next emergency goes
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [cardOpen, setCardOpen] = useState(false); // full vehicle card (marker / trip row) vs the strip's drop-down
  const [detail, setDetail] = useState<VehicleDetail | null>(null);
  const [centerOn, setCenterOn] = useState<{ lat: number; lon: number; n: number } | null>(null);
  const [picked, setPicked] = useState(""); // vehicle chosen in the Events tab dropdown
  const [help, setHelp] = useState(false);
  const [tab, setTab] = useState<Tab>("ai"); // the panel starts from the AI dispatcher and its cases
  const [callFocus, setCallFocus] = useState<CaseFocus | null>(null); // open this case's card
  const [callPoint, setCallPoint] = useState<{ lat: number; lon: number; n: number } | null>(null); // new call: map point
  const [caseSel, setCaseSel] = useState<string | null>(null); // the case whose units are highlighted on the map
  const [flashCall, setFlashCall] = useState<{ tripId: string; n: number } | null>(null); // "On map": centre + blink
  const [reviewOpen, setReviewOpen] = useState(false); // "Situation review" (the general analysis)
  const [messageOpen, setMessageOpen] = useState(false); // "Message to the AI dispatcher"
  const openCall = (tripId: string) => {
    setTab("ai");
    setCallFocus({ tripId, n: Date.now() });
  };
  const overrideUnit = (tripId: string, vehicleId: string) => {
    setTab("ai");
    setCallFocus({ tripId, n: Date.now(), overrideVehicle: vehicleId });
  };
  // The units of a case: the ambulance (or van, helicopter), the doctor and any added unit
  const unitsOf = (tripId: string | null): string[] => {
    const t = tripId ? state.trips.find((x) => x.id === tripId) : undefined;
    if (!t) return [];
    const ids = [t.vehicle_id, t.doctor_vehicle_id, ...(t.units ?? []).map((u) => u.vehicle_id)].filter((x): x is string => Boolean(x));
    return [...new Set(ids)];
  };
  // Selecting a case selects all its units: the first one's whole route, the others' current legs
  const selectCase = (tripId: string | null) => {
    setCaseSel(tripId);
    const first = unitsOf(tripId)[0] ?? null;
    setSelectedId(first);
    setCardOpen(false);
  };
  const caseUnits = unitsOf(caseSel);
  // Demo injections (Simulation only; hidden until the backend has the endpoints)
  const [demo, demoMissing] = useDemoApi(sim);
  const [demoBusy, setDemoBusy] = useState(false);
  const injectCall = async (severity?: string) => {
    if (!demo.call || demoBusy) return;
    setDemoBusy(true);
    try {
      const { trip, summary } = await randomCall(severity);
      notify("ok", summary);
      if (trip) openCall(trip.id); // the case card opens and selects its units
    } catch (e) {
      if (e instanceof MissingEndpoint) {
        demoMissing("call");
        notify("error", t("dash.err.randomCallsBackend"));
      } else notify("error", bilingualLines(errorText(e)));
    } finally {
      setTimeout(() => setDemoBusy(false), 600);
    }
  };
  // E + a click on the map + a condition: in the Simulation a real 112 call from the call library at that
  // point (caller, Slovenian words, triage, case card); in Live, or with an older backend, the plain event.
  const sendPicked = async (event: Record<string, unknown>) => {
    const { lat, lon, condition, modifiers } = event as { lat: number; lon: number; condition: string; modifiers?: string[] };
    if (!sim || !demo.call) return void send(event);
    try {
      const { trip, summary } = await randomCall(undefined, { condition, lat, lon, modifiers });
      notify("ok", summary);
      if (trip) openCall(trip.id);
    } catch (e) {
      if (e instanceof MissingEndpoint) void send(event);
      else notify("error", bilingualLines(errorText(e)));
    }
  };
  const injectIncident = async (kind?: string) => {
    if (!demo.incident || demoBusy) return;
    setDemoBusy(true);
    try {
      const { event, summary } = await randomIncident(kind);
      notify("ok", summary);
      const tripId = event?.affected_trip_ids?.[0];
      const vehicleId = (event as { payload?: { vehicle_id?: string } } | null)?.payload?.vehicle_id;
      if (tripId) openCall(tripId); // the case card opens and selects its units
      else if (vehicleId) select(vehicleId, false);
    } catch (e) {
      if (e instanceof MissingEndpoint) {
        demoMissing("incident");
        notify("error", t("dash.err.randomFailuresBackend"));
      } else notify("error", bilingualLines(errorText(e)));
    } finally {
      setTimeout(() => setDemoBusy(false), 600);
    }
  };
  // "Choose unit…": a failure aimed at one unit. null: done (the popover closes); text: why it did not fit,
  // shown in the popover, which stays open ("": busy, nothing to say)
  const injectTargeted = async (vehicleId: string, kind: string): Promise<string | null> => {
    if (!demo.incident || demoBusy) return "";
    setDemoBusy(true);
    try {
      const { event, summary } = await randomIncident(kind, vehicleId);
      notify("ok", summary);
      const tripId = event?.affected_trip_ids?.[0];
      if (tripId) openCall(tripId);
      else select(vehicleId, false);
      return null;
    } catch (e) {
      if (e instanceof MissingEndpoint) {
        demoMissing("incident");
        return t("dash.err.randomFailuresBackend");
      }
      return targetErrorText(errorText(e));
    } finally {
      setTimeout(() => setDemoBusy(false), 600);
    }
  };
  const caseUnit = caseSel ? (state.trips.find((x) => x.id === caseSel)?.vehicle_id ?? null) : null;
  const demoButtons = (
    <DemoButtons
      api={demo}
      busy={demoBusy}
      onCall={(s) => void injectCall(s)}
      onIncident={(k) => void injectIncident(k)}
      state={state}
      preselect={[selectedId, caseUnit]}
      onTarget={injectTargeted}
    />
  );
  const [unseenRun, setUnseenRun] = useState(false);
  const micToggle = useRef<(() => void) | null>(null);
  const agentKeys = useRef<AgentKeys | null>(null);

  // One selection for markers, trip rows and the vehicle strip; markers and rows open the full card.
  // Selecting a single vehicle ends the case selection (its other units fade again).
  const select = (id: string | null, card = true) => {
    setSelectedId(id);
    setCardOpen(id !== null && card);
    if (id === null || !caseUnits.includes(id)) setCaseSel(null);
  };
  const centerVehicle = (id: string) => {
    const v = state.vehicles.find((x) => x.id === id);
    if (v) setCenterOn({ lat: v.lat, lon: v.lon, n: Date.now() });
  };

  const notify: Notify = (kind, text, sticky = false) => setToast({ kind, text, sticky: sticky || kind === "error", n: Date.now() });

  // Toasts fade after a while; errors and notes marked sticky stay until closed or replaced
  useEffect(() => {
    if (!toast || toast.sticky) return;
    const timer = setTimeout(() => setToast((t) => (t?.n === toast.n ? null : t)), 9000);
    return () => clearTimeout(timer);
  }, [toast]);

  // A new AI analysis (scenario, field message, event, hotkey): bring the AI dispatcher into view with
  // its situation review open, except while booking, where switching would hide the booking result (a
  // badge marks the tab instead). In Autonomous mode the review stays folded: its one-line summary says
  // what the AI is doing, and the autopilot applies the plan.
  const latestRun = generalRun(state.agent.runs); // a case review shows on its case card, not here
  const lastRunId = useRef(latestRun?.id);
  const autonomous = (state.ai_mode ?? (state.autopilot ? "autonomous" : "assisted")) === "autonomous";
  useEffect(() => {
    if (!latestRun || latestRun.id === lastRunId.current) return;
    lastRunId.current = latestRun.id;
    if (tab === "book") {
      setUnseenRun(true);
      return;
    }
    setTab("ai");
    if (!autonomous) setReviewOpen(true);
  }, [latestRun, tab, autonomous]);
  useEffect(() => {
    if (tab === "ai") setUnseenRun(false);
  }, [tab]);

  // The selected case got another unit (reassigned, overridden): follow it on the map
  const caseUnitsKey = caseUnits.join(",");
  useEffect(() => {
    if (caseSel && caseUnits.length && (!selectedId || !caseUnits.includes(selectedId))) {
      setSelectedId(caseUnits[0]);
      setCardOpen(false);
    }
  }, [caseSel, caseUnitsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // The world was reset (a scenario, Reset): the selected case and vehicle belonged to the old world (its
  // trip ids start again at TR-001), so drop them rather than highlight an unrelated new call. (Declared
  // after the effect above, so in the same render this one's clearing wins.)
  const lastEpoch = useRef(state.epoch);
  useEffect(() => {
    if (state.epoch === undefined || state.epoch === lastEpoch.current) return;
    lastEpoch.current = state.epoch;
    setCaseSel(null);
    setSelectedId(null);
    setCardOpen(false);
    setCallFocus(null);
  }, [state.epoch]);

  // Selected vehicle: refresh its card and highlighted route every 3 s
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let stop = false;
    const load = () =>
      fetchVehicle(world, selectedId)
        .then((d) => !stop && setDetail(d))
        .catch(() => !stop && setDetail(null));
    void load();
    const timer = setInterval(load, 3000);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [world, selectedId]);

  const send: Send = async (event) => {
    setBusy(true);
    try {
      notify("ok", describe(await postEvent(world, event)));
    } catch (e) {
      notify("error", errorText(e));
    } finally {
      setBusy(false);
    }
  };

  // B/D act on the vehicle selected on the map (marker or trip row), never on some other vehicle
  const selectedVehicle = selectedId ? state.vehicles.find((v) => v.id === selectedId) : undefined;
  const onSelected = (what: string, fn: (id: string) => void) => {
    if (!selectedVehicle) notify("error", t("dash.err.selectVehicleFirst", { what }));
    else if (selectedVehicle.status === "out_of_service") notify("error", t("dash.err.alreadyOut", { name: selectedVehicle.name }));
    else fn(selectedVehicle.id);
  };

  // A/Y/N act on the situation review, M on the message box: both live in the AI dispatcher tab
  const showReview = () => {
    setTab("ai");
    setReviewOpen(true);
  };
  useHotkeys({
    m: () => {
      setTab("ai");
      setMessageOpen(true);
      micToggle.current?.();
    },
    a: () => {
      showReview();
      agentKeys.current?.analyse();
    },
    y: () => {
      showReview();
      agentKeys.current?.approveRecommended();
    },
    n: () => {
      showReview();
      agentKeys.current?.reject();
    },
    b: () =>
      onSelected(t("dash.err.whatBreakdown"), (id) => void send({ type: "breakdown", vehicle_id: id, note: "reported by the operator, hotkey" })),
    d: () =>
      onSelected(t("dash.err.whatDelay"), (id) => void send({ type: "delay", vehicle_id: id, minutes: 10, note: "reported by the operator, hotkey" })),
    f: () => void send({ type: "fog", duration_min: 60 }),
    e: () => setMode((m) => (m === "emergency" ? null : "emergency")),
    c: () => setMode((m) => (m === "closure" ? null : "closure")),
    r: () => void injectCall(),
    x: () => void injectIncident(),
    Escape: () => {
      setMode(null);
      select(null);
      setToast(null);
    },
    "?": () => setHelp((h) => !h),
  });

  const onMapClick = (lat: number, lon: number) => {
    if (mode === "closure") {
      void send({ type: "road_closure", lat, lon, radius_m: 400, description: "Road closed (operator report)" });
    } else if (mode === "emergency") {
      setPendingCall({ lat, lon }); // what kind of emergency: the picker sends it
    } else if (mode === "call") {
      setCallPoint({ lat, lon, n: Date.now() }); // the new 112 call's location (the form in the AI dispatcher tab)
      setTab("ai");
    }
    setMode(null);
  };

  const misses = responseAlerts(state);
  const drMisses = doctorAlerts(state);
  const alertCount = misses.length + drMisses.length + state.alerts.length + state.incidents.filter((i) => i.active).length;
  const critical = misses.length > 0 || drMisses.length > 0 || state.alerts.some((a) => a.severity === "critical");
  const activeCalls = state.trips.filter((t) => t.status !== "completed" && t.status !== "cancelled").length;
  const waitingCalls = state.trips.filter((t) => t.status === "unassigned" && (t.severity === "critical" || t.severity === "serious")).length;
  const tabs: { id: Tab; label: string; badge?: string; hot?: boolean; title?: string }[] = [
    {
      id: "ai",
      label: t("dash.tab.ai"),
      badge: unseenRun ? t("dash.tab.new") : activeCalls ? String(activeCalls) : undefined,
      hot: unseenRun || waitingCalls > 0,
      title: `${t("dash.tab.aiTitle", { count: activeCalls })}${waitingCalls ? t("dash.tab.aiTitleRed", { count: waitingCalls }) : ""}${unseenRun ? t("dash.tab.aiTitleNew") : ""}`,
    },
    ...(sim ? [{ id: "scenarios" as Tab, label: t("dash.tab.scenarios") }] : []),
    { id: "events", label: sim ? t("dash.tab.events") : t("dash.tab.report") },
    { id: "book", label: t("dash.tab.book") },
    { id: "alerts", label: t("dash.tab.alerts"), badge: alertCount ? String(alertCount) : undefined, hot: critical },
  ];

  return (
    <main className="main">
      <ShortcutsHelp open={help} onClose={() => setHelp(false)} />
      <section className="map-col">
        <VehicleStrip
          state={state}
          selectedId={selectedId}
          onSelect={(id) => select(id, false)}
          onCenter={centerVehicle}
          onOpenCard={(id) => select(id, true)}
          onOpenCall={openCall}
          onOverride={overrideUnit}
          send={send}
          busy={busy}
        />
        <div className="map-wrap">
        {mode && (
          <div className="map-hint">
            {mode === "closure" ? <Construction /> : <CircleAlert />}
            {t(mode === "closure" ? "dash.hint.closure" : mode === "call" ? "dash.hint.call" : "dash.hint.emergency")} ·{" "}
            <button className="link" onClick={() => setMode(null)}>
              {t("dash.hint.cancel")}
            </button>
          </div>
        )}
        {pendingCall && (
          <EmergencyPicker
            at={pendingCall}
            onCancel={() => setPendingCall(null)}
            onSend={(event) => {
              setPendingCall(null);
              void sendPicked(event);
            }}
          />
        )}
        <MapView
          state={state}
          mode={mode}
          pin={pendingCall}
          onMapClick={onMapClick}
          selectedId={selectedId}
          onSelect={(id) => select(id)}
          detail={detail}
          centerOn={centerOn}
          group={caseUnits}
          flash={flashCall}
        />
        <MapLegend />
        {detail && selectedId && cardOpen && (
          <VehicleCard
            detail={detail}
            state={state}
            busy={busy}
            send={send}
            onClose={() => select(null)}
            onOpenCall={openCall}
            onOverride={overrideUnit}
            onCenter={() => setCenterOn({ lat: detail.vehicle.lat, lon: detail.vehicle.lon, n: Date.now() })}
          />
        )}
        {toast && (
          <div className={`toast ${toast.kind}`} role="status" aria-live="polite">
            {toast.kind === "ok" ? <CircleCheck /> : <CircleAlert />}
            <span>{toast.text}</span>
            <button className="link toast-close" onClick={() => setToast(null)} aria-label={t("common.dismiss")}>
              <X />
            </button>
          </div>
        )}
        </div>
      </section>
      <aside className="side">
        <KpiRow kpis={state.kpis} />
        <div className="side-tabs" role="tablist" aria-label={t("dash.tabs.aria")}>
          {tabs.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              className={`side-tab${tab === t.id ? " on" : ""}${t.id === "ai" ? " side-tab-ai" : ""}`}
              onClick={() => setTab(t.id)}
              title={t.title}
            >
              {t.label}
              {t.badge && <span className={`tab-badge${t.hot ? " hot" : ""}`}>{t.badge}</span>}
            </button>
          ))}
        </div>
        {/* Every tab stays mounted (hidden), so forms, results and the mic hotkey survive switching */}
        <div className="side-body side-body-ai" hidden={tab !== "ai"}>
          <AiDispatcherPanel
            state={state}
            focus={callFocus}
            picked={callPoint}
            onPickOnMap={() => setMode("call")}
            selectedCase={caseSel}
            onSelectCase={selectCase}
            onSelectVehicle={(id, card) => select(id, card)}
            onCentreVehicle={centerVehicle}
            onShowCall={(tripId) => setFlashCall({ tripId, n: Date.now() })}
            notify={notify}
            demo={demoButtons}
            reviewOpen={reviewOpen}
            setReviewOpen={setReviewOpen}
            messageOpen={messageOpen}
            setMessageOpen={setMessageOpen}
            micToggleRef={micToggle}
            agentKeys={agentKeys}
          />
        </div>
        {sim && (
          <div className="side-body" hidden={tab !== "scenarios"}>
            <Panel title={t("dash.panel.scenarios")}>
              <ScenariosPanel state={state} notify={notify} extra={demoButtons} />
            </Panel>
          </div>
        )}
        <div className="side-body" hidden={tab !== "events"}>
          <Panel title={sim ? t("dash.panel.whatIf") : t("dash.panel.reportEvent")}>
            <EventsPanel state={state} busy={busy} mode={mode} setMode={setMode} send={send} picked={picked} setPicked={setPicked} />
          </Panel>
          <Panel title={t("dash.panel.priority")}>
            <OpsControls state={state} send={send} busy={busy} />
          </Panel>
        </div>
        <div className="side-body" hidden={tab !== "book"}>
          <Panel title={t("dash.panel.book")}>
            <BookingForm state={state} />
          </Panel>
        </div>
        <div className="side-body" hidden={tab !== "alerts"}>
          {!sim && (
            <Panel title={t("dash.panel.conditions")}>
              <Conditions state={state} />
            </Panel>
          )}
          <Panel title={t("dash.panel.alerts", { count: alertCount })}>
            <Alerts state={state} send={send} />
          </Panel>
          <Panel title={t("dash.panel.eventLog")}>
            <EventLog events={state.events} trips={state.trips} />
          </Panel>
        </div>
      </aside>
      <section className="trips">
        <TripTable state={state} selectedId={selectedId} onSelect={(id) => select(id)} />
      </section>
    </main>
  );
}

/** Where the calls come from: the demo's synthetic call stream (both worlds), or the scheduled day. */
function CallsChip({ state }: { state: WorldSnapshot }) {
  const t = useT();
  const c = state.calls;
  if (!c) return null;
  const text =
    state.mode === "scheduled_day"
      ? t("dash.calls.scheduledDay")
      : !c.enabled
        ? t("dash.calls.off")
        : c.paused_until
          ? t("dash.calls.pausedUntil", { time: fmtTime(c.paused_until) })
          : t("dash.calls.perHour", { count: c.per_hour });
  const title =
    t("dash.calls.title") +
    (c.next_at ? `\n${t("dash.calls.titleNext", { time: fmtTime(c.next_at) })}` : "") +
    `\n${t("dash.calls.titleSoFar", { count: c.generated })}`;
  return (
    <span className="chip" title={title}>
      <PhoneIncoming /> {text}
    </span>
  );
}

/** Contracted surge capacity in the fleet: until when, and a stand-down action (the dispatcher's decision). */
function SurgeChip({ state }: { state: WorldSnapshot }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const s = state.surge;
  if (!s?.active || !s.until) return null;
  const standDown = async () => {
    if (!window.confirm(t("dash.surge.confirmStandDown"))) return;
    setBusy(true);
    try {
      await standDownSurge(state.world);
    } catch (e) {
      window.alert(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="chip warn surge-chip" title={t("dash.surge.unitsTitle", { units: s.units.join(", ") })}>
      <Users /> {t("dash.surge.activeUntil", { time: fmtTime(s.until) })}
      <button className="link" disabled={busy} onClick={() => void standDown()} title={t("dash.surge.endTitle")}>
        {t("dash.surge.standDown")}
      </button>
    </span>
  );
}

/** The demand trigger's alert, with the one-click offer of contracted surge capacity. */
function HighDemandAlert({ alert, state }: { alert: Alert; state: WorldSnapshot }) {
  const t = useT();
  const lang = useLang();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const s = state.surge;
  const amb = s?.available.ambulances.length ?? 0;
  const vans = s?.available.vans.length ?? 0;
  const hours = s?.default.hours ?? 2;
  const canActivate = Boolean(s && !s.active && amb + vans > 0);
  const label = t("dash.surge.activate", {
    ambulances: t("dash.surge.ambulances", { count: amb }),
    vans: t("dash.surge.vans", { count: vans }),
    hours,
  });
  const activate = async () => {
    const offer = (lang === "en" ? s?.offer : null) ?? label; // the backend's offer is English
    if (!window.confirm(t("dash.surge.confirmActivate", { offer }))) return;
    setBusy(true);
    try {
      const r = await activateSurge(state.world, { hours });
      setNote(r.event?.summary ?? t("dash.surge.active"));
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className={`alert sev-${alert.severity} high-demand`}>
      <div>{alert.message}</div>
      {canActivate && (
        <button className="primary surge-button" disabled={busy} onClick={() => void activate()}>
          <Users /> {busy ? t("dash.surge.activating") : label}
        </button>
      )}
      {note && <div className="muted surge-note">{note}</div>}
    </li>
  );
}

function MapLegend() {
  const t = useT();
  return (
    <div className="map-legend" aria-label={t("dash.legend.aria")}>
      <span title={t("dash.legend.criticalTitle")}>
        <i className="lg lg-crit" /> {t("dash.legend.critical")}
      </span>
      <span title={t("dash.legend.seriousTitle")}>
        <i className="lg lg-ser" /> {t("dash.legend.serious")}
      </span>
      <span title={t("dash.legend.doctorTitle")}>
        <i className="lg lg-doctor" /> {t("dash.legend.doctor")}
      </span>
      <span>
        <i className="lg lg-idle" /> {t("dash.legend.available")}
      </span>
      <span>
        <i className="lg lg-moving" /> {t("dash.legend.toPickup")}
      </span>
      <span>
        <i className="lg lg-loaded" /> {t("dash.legend.onBoard")}
      </span>
      <span>
        <i className="lg lg-down" /> {t("dash.legend.out")}
      </span>
      <span>
        <i className="lg lg-detour" /> {t("dash.legend.detour")}
      </span>
      <span title={t("dash.legend.closureTitle")}>
        <i className="lg lg-road lg-closure" /> {t("dash.legend.closure")}
      </span>
      <span title={t("dash.legend.crashTitle")}>
        <i className="lg lg-road lg-crash" /> {t("dash.legend.crash")}
      </span>
      <span title={t("dash.legend.jamTitle")}>
        <i className="lg lg-road lg-jam" /> {t("dash.legend.jam")}
      </span>
    </div>
  );
}

function StatusBar({ state, connected }: { state: WorldSnapshot; connected: boolean }) {
  const t = useT();
  const w = state.weather.now;
  const sources = Object.values(state.sources);
  const unhealthy = sources.filter((s) => s.health !== "fresh");
  const health = (h: string) => tOr(`dash.health.${h}`, h);
  const sourcesTitle =
    sources
      .map(
        (s) =>
          `${s.name}: ${health(s.health)}${s.last_error ? ` (${s.last_error})` : t("dash.status.sourceAge", { kind: s.kind, age: s.age_s ?? "–" })}`,
      )
      .join("\n") + `\n${t("dash.status.routesCached", { count: state.roads.routes_cached })}`;
  return (
    <div className={`statusbar ${state.hypothetical ? "is-sim" : "is-live"}`}>
      <span className="mode-badge">
        {state.hypothetical ? t("dash.status.sim", { speed: state.speedup }) : t("dash.status.live")}
      </span>
      <div className="chips">
        <span className={`chip ${connected ? "ok" : "bad"}`}>
          <i className="dot" /> {connected ? t("dash.status.connected") : t("dash.status.reconnecting")}
        </span>
        <span className="chip chip-strong">
          {state.hypothetical ? t("dash.status.simTime") : t("dash.status.time")} {fmtTime(state.sim_time)}
        </span>
        {w && (
          <span className={`chip ${state.weather.overridden ? "warn" : ""}`}>
            <WeatherIcon w={w} /> {fmtNum(w.temperature_c, 1)} °C ·{" "}
            {fmtDec(w.precipitation_mm)} mm · {state.weather.overridden ? t("dash.status.demoOverride") : w.source}
          </span>
        )}
        <span
          className="chip"
          title={
            state.traffic.samples.map((s) => `${s.road}: ${s.current_kmh}/${s.free_flow_kmh} km/h`).join("\n") ||
            state.traffic.source
          }
        >
          <Car /> {t("dash.status.traffic")} ×{fmtNum(state.traffic.factor, 2)} ·{" "}
          {state.traffic.source === "tomtom" ? t("dash.status.tomtomLive") : t("dash.status.profile")}
        </span>
        <CallsChip state={state} />
        <SurgeChip state={state} />
        <span
          className={`chip ${unhealthy.some((s) => s.health === "down") ? "bad" : unhealthy.length ? "warn" : "ok"}`}
          title={sourcesTitle}
        >
          <Database />
          {unhealthy.length
            ? unhealthy.map((s) => `${s.name}: ${health(s.health)}`).join(" · ")
            : t("dash.status.feedsFresh")}
        </span>
        <TilesChip />
      </div>
    </div>
  );
}

/** The TomTom traffic layer's daily tile cap (from /health, once a minute): a quiet note when it's reached. */
function TilesChip() {
  const t = useT();
  const [tiles, setTiles] = useState<{ capped?: boolean; used?: string } | null>(null);
  useEffect(() => {
    let stop = false;
    const load = () =>
      fetch(`${API_URL}/health`)
        .then((r) => (r.ok ? r.json() : null))
        .then((h) => !stop && setTiles(h?.traffic_tiles ?? null))
        .catch(() => undefined);
    void load();
    const timer = setInterval(load, 60_000);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, []);
  if (!tiles?.capped) return null;
  return (
    <span className="chip warn" title={t("dash.tiles.title", { used: tiles.used ?? "?" })}>
      <Car /> {t("dash.tiles.paused")}
    </span>
  );
}

function WeatherIcon({ w }: { w: { snowfall_cm: number; precipitation_mm: number } }) {
  return w.snowfall_cm > 0 ? <CloudSnow /> : w.precipitation_mm > 0 ? <CloudRain /> : <Sun />;
}

function IncidentIcon({ kind }: { kind: string }) {
  return kind === "road_closure" ? <Octagon /> : kind === "accident" ? <CircleAlert /> : <TrafficCone />;
}

/** Live page: what the real world looks like right now. */
function Conditions({ state }: { state: WorldSnapshot }) {
  const t = useT();
  const w = state.weather.now;
  const nextHours = state.weather.forecast.filter((h) => new Date(h.time).getTime() > Date.now()).slice(0, 4);
  const live = state.incidents.filter((i) => i.source === "live");
  return (
    <div className="conditions">
      {w && (
        <div>
          <strong>
            <WeatherIcon w={w} /> {fmtNum(w.temperature_c, 1)} °C
          </strong>{" "}
          · {fmtDec(w.precipitation_mm)} mm · {t("dash.cond.wind", { speed: Math.round(w.wind_speed_kmh) })}{" "}
          <span className="muted">({w.source})</span>
          {nextHours.length > 0 && (
            <div className="muted">
              {t("dash.cond.nextHours")}{" "}
              {nextHours
                .map(
                  (h) =>
                    `${fmtTime(h.time)} ${Math.round(h.temperature_c)}°${h.snowfall_cm > 0 ? t("dash.cond.snow") : h.precipitation_mm > 0 ? t("dash.cond.rain") : ""}`,
                )
                .join(" · ")}
            </div>
          )}
        </div>
      )}
      <div>
        <strong>
          {t("dash.status.traffic")} ×{fmtNum(state.traffic.factor, 2)}
        </strong>{" "}
        <span className="muted">({state.traffic.source === "tomtom" ? t("dash.status.tomtomLive") : state.traffic.source})</span>
        {state.traffic.samples.length > 0 && (
          <ul className="roads">
            {state.traffic.samples.map((s) => (
              <li key={s.road} className={s.ratio < 0.7 ? "slow" : ""}>
                {s.road}: {s.current_kmh}/{s.free_flow_kmh} km/h
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <strong>{t("dash.cond.liveIncidents", { count: live.length })}</strong>
        {live.slice(0, 5).map((i) => (
          <div key={i.id} className="muted">
            <IncidentIcon kind={i.kind} /> {i.description}
          </div>
        ))}
      </div>
    </div>
  );
}

function KpiRow({ kpis }: { kpis: Kpis }) {
  const t = useT();
  const items: [string, string | number, boolean][] = [
    [t("dash.kpi.open"), kpis.open_trips, false],
    [t("dash.kpi.late"), kpis.late_trips, kpis.late_trips > 0],
    [t("dash.kpi.delay"), Math.round(kpis.total_delay_min), kpis.total_delay_min >= 15],
    [t("dash.kpi.unassigned"), unassignedTotal(kpis), unassignedTotal(kpis) > 0],
    [t("dash.kpi.inService"), kpis.vehicles_in_service, false],
  ];
  return (
    <div className="kpis">
      {items.map(([label, value, bad]) => (
        <div key={label} className={`kpi${bad ? " bad" : ""}`}>
          <div className="kpi-value">{value}</div>
          <div className="kpi-label">{label}</div>
        </div>
      ))}
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel">
      <h2 className="panel-title">{title}</h2>
      {children}
    </section>
  );
}

/** Critical and serious calls that will miss their response target (unless the backend already alerts on them). */
function responseAlerts(state: WorldSnapshot): { trip: Trip; r: ResponseInfo }[] {
  const covered = new Set(state.alerts.filter((a) => a.trip_id && /target|response/i.test(a.kind)).map((a) => a.trip_id));
  return targetMisses(state.trips, state.sim_time).filter((m) => !covered.has(m.trip.id));
}

/** Critical calls whose doctor (car or helicopter) will reach the scene after the target. */
function doctorAlerts(state: WorldSnapshot): { trip: Trip; d: DoctorInfo }[] {
  const covered = new Set(state.alerts.filter((a) => a.trip_id && /doctor/i.test(a.kind)).map((a) => a.trip_id));
  return doctorMisses(state.trips, state.vehicles, state.sim_time).filter((m) => !covered.has(m.trip.id));
}

function Alerts({ state, send }: { state: WorldSnapshot; send: Send }) {
  useLang(); // texts below use tx(): `t` is the trip here
  const incidents = state.incidents.filter((i) => i.active);
  const misses = responseAlerts(state);
  const drMisses = doctorAlerts(state);
  if (misses.length === 0 && drMisses.length === 0 && state.alerts.length === 0 && incidents.length === 0)
    return <p className="muted">{tx("dash.alerts.allClear")}</p>;
  return (
    <ul className="alerts">
      {misses.map(({ trip: t, r }) => (
        <li key={`target:${t.id}`} className={`alert target-miss lvl-${levelOf(t)}`}>
          <div className="target-miss-head">
            <SeverityBadge trip={t} modifiers={false} />
            <strong className="id">{t.id}</strong>
          </div>
          <div>
            {r.minutes == null
              ? tx("dash.alerts.noUnit", { waited: Math.round(r.waited), target: r.target })
              : tx("dash.alerts.late", {
                  unit: t.vehicle_id ?? tx("dash.alerts.theUnit"),
                  m: r.minutes,
                  target: r.target,
                  over: r.minutes - r.target,
                })}
          </div>
        </li>
      ))}
      {drMisses.map(({ trip: t, d }) => (
        <li key={`doctor:${t.id}`} className={`alert target-miss lvl-${levelOf(t)}`}>
          <div className="target-miss-head">
            <SeverityBadge trip={t} weight={false} modifiers={false} />
            <strong className="id">{t.id}</strong>
            <DoctorTag trip={t} vehicles={state.vehicles} now={state.sim_time} />
          </div>
          <div>
            {d.minutes == null
              ? tx("dash.alerts.drNone", { waited: Math.round(d.waited), target: d.target })
              : tx("dash.alerts.drLate", { v: d.vehicle, m: d.minutes, target: d.target, over: d.minutes - d.target })}
          </div>
        </li>
      ))}
      {incidents.map((inc) => (
        <li key={inc.id} className={`alert ${inc.kind === "congestion" ? "sev-medium" : "sev-high"}`}>
          <span>
            <IncidentIcon kind={inc.kind} /> {inc.description}
          </span>
          {inc.source === "injected" && (
            <button className="link" onClick={() => send({ type: "clear_incident", incident_id: inc.id })}>
              {tx("dash.alerts.clear")}
            </button>
          )}
        </li>
      ))}
      {state.alerts.map((a) =>
        a.kind === "high_demand" ? (
          <HighDemandAlert key={a.id} alert={a} state={state} />
        ) : (
          <li key={a.id} className={`alert sev-${a.severity}`}>
            {a.message}
          </li>
        ),
      )}
    </ul>
  );
}

function EventLog({ events, trips }: { events: EventRecord[]; trips: Trip[] }) {
  useLang(); // describe() and the texts here use tx(): `t` is a trip here
  if (events.length === 0) return <p className="muted">{tx("dash.events.none")}</p>;
  const byId = new Map(trips.map((t) => [t.id, t]));
  // The most severe call an event touches (a new call, a priority change, a breakdown's patients…)
  const worst = (e: EventRecord) =>
    e.affected_trip_ids
      .map((id) => byId.get(id))
      .filter((t): t is Trip => Boolean(t))
      .sort((a, b) => LEVEL_RANK[levelOf(a)] - LEVEL_RANK[levelOf(b)])[0];
  return (
    <ul className="events">
      {[...events].reverse().map((e) => {
        const t = worst(e);
        return (
          <li key={e.id}>
            <span className="muted">{fmtTime(e.sim_time)}</span> {t && <SeverityBadge trip={t} compact />} {describe(e)}
          </li>
        );
      })}
    </ul>
  );
}

function TripTable({
  state,
  selectedId,
  onSelect,
}: {
  state: WorldSnapshot;
  selectedId: string | null;
  onSelect: (vehicleId: string | null) => void;
}) {
  useLang(); // texts below use tx(): `t` is the trip here
  const place = new Map(state.places.map((p) => [p.id, p.name]));
  const vehicleById = new Map(state.vehicles.map((v) => [v.id, v]));
  // Most severe first, then the most time-critical condition, then the earliest due
  const open = state.trips.filter((t) => t.status !== "completed" && t.status !== "cancelled").sort(compareTrips);
  const done = state.trips.length - open.length;
  const needs = (n: string) => tOr(`dash.needs.${n}`, n);

  return (
    <table className="trip-table">
      <thead>
        <tr>
          <th>{tx("dash.trips.trip")}</th>
          <th>{tx("dash.trips.patient")}</th>
          <th>{tx("dash.trips.severity")}</th>
          <th title={tx("dash.trips.respTitle")}>{tx("dash.trips.resp")}</th>
          <th>{tx("dash.trips.route")}</th>
          <th>{tx("dash.trips.vehicle")}</th>
          <th>{tx("dash.trips.status")}</th>
          <th>{tx("dash.trips.due")}</th>
          <th>{tx("dash.trips.eta")}</th>
          <th>{tx("dash.trips.delay")}</th>
        </tr>
      </thead>
      <tbody>
        {open.map((t) => {
          const late = (t.delay_min ?? 0) >= 5;
          const route = `${place.get(t.pickup_id) ?? t.pickup_id} → ${place.get(t.dropoff_id) ?? t.dropoff_id}`;
          return (
            <tr
              key={t.id}
              className={`${t.status === "unassigned" ? "row-unassigned" : late ? "row-late" : ""}${
                t.vehicle_id && t.vehicle_id === selectedId ? " row-selected" : ""
              }${t.vehicle_id ? " clickable" : ""}`}
              onClick={() => t.vehicle_id && onSelect(t.vehicle_id)}
              title={t.vehicle_id ? tx("dash.trips.showOnMap", { v: t.vehicle_id }) : undefined}
            >
              <td className="id">{t.id}</td>
              <td className="cell-clip" title={`${t.label ?? t.patient ?? ""}${t.kind === "patient" ? ` · ${needs(t.needs)}` : ""}`}>
                {t.label ?? t.patient}
                {t.kind === "patient" && <span className="muted"> · {needs(t.needs)}</span>}
              </td>
              <td className="cell-sev">
                <SeverityBadge trip={t} />
              </td>
              <td className="cell-resp">
                <ResponseLine trip={t} now={state.sim_time} compact />
                <DoctorTag trip={t} vehicles={state.vehicles} now={state.sim_time} compact />
              </td>
              <td className="cell-clip cell-route" title={route}>
                {route}
              </td>
              <td className={t.vehicle_id ? "id" : "muted"}>
                {t.vehicle_id ?? "—"}
                <OriginTag v={vehicleById.get(t.vehicle_id ?? "")} compact />
              </td>
              <td>{tripStatusLabel(t.status)}</td>
              <td>{fmtTime(t.due_by)}</td>
              <td>{fmtTime(t.eta_dropoff)}</td>
              <td className={late ? "late" : ""}>
                {t.delay_min == null ? "—" : late ? `+${Math.round(t.delay_min)} min` : tx("dash.trips.onTime")}
              </td>
            </tr>
          );
        })}
      </tbody>
      <tfoot>
        <tr>
          <td colSpan={10} className="muted">
            {tx("dash.trips.footer", {
              open: tx("dash.trips.open", { count: open.length }),
              done: tx("dash.trips.done", { count: done }),
            })}
          </td>
        </tr>
      </tfoot>
    </table>
  );
}
