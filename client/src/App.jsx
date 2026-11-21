import { useEffect, useRef, useState } from 'react'
import MapView from './Map'
import { API_URL, fetchState, runScenario, resetSimulation, triggerAnalysis, approveOption, rejectRun } from './api'
import { ambulances, hospitals, activeCalls } from './mockData'

// ── Helpers ────────────────────────────────────────────────────────────────────

function nearestPlace(lat, lon, places) {
  let best = null, bestDist = Infinity
  for (const p of places) {
    if (!p.lat || !p.lon) continue
    const d = Math.hypot(p.lat - lat, p.lon - lon)
    if (d < bestDist) { bestDist = d; best = p }
  }
  return best
}

function incidentKindLabel(kind) {
  if (kind === 'road_closure') return 'Road closure'
  if (kind === 'accident')     return 'Accident'
  if (kind === 'congestion')   return 'Congestion'
  return kind.replace(/_/g, ' ')
}

// WMO weather code → short description
function wxDesc(code) {
  if (code == null) return ''
  if (code === 0)   return 'Clear'
  if (code <= 3)    return 'Cloudy'
  if (code <= 48)   return 'Fog'
  if (code <= 67)   return 'Rain'
  if (code <= 77)   return 'Snow'
  if (code <= 82)   return 'Showers'
  return 'Storm'
}

// Vehicles shown with a dark ring while run is active
function getAffectedVehicleIds(run, state) {
  if (!run || (run.status !== 'running' && run.status !== 'done')) return new Set()
  const ids = new Set()
  for (const v of (state?.vehicles ?? [])) {
    if (v.status === 'out_of_service') ids.add(v.id)
  }
  if (run.status === 'done') {
    for (const opt of (run.recommendation?.options ?? [])) {
      for (const step of (opt.steps ?? [])) {
        if (step.vehicle_id) ids.add(step.vehicle_id)
      }
    }
  }
  return ids
}

// ── Data conversion ────────────────────────────────────────────────────────────

function liveToMapProps(state) {
  return {
    vehicles:  state.vehicles,
    places:    state.places.filter(p => p.kind !== 'residential'),
    incidents: state.incidents.filter(i => i.active !== false),
  }
}

function mockToMapProps() {
  return {
    vehicles: ambulances.map(a => ({
      id: a.id, name: a.id, type: 'ambulance',
      lat: a.lat, lon: a.lng,
      status: a.status === 'free' ? 'idle' : 'to_pickup',
    })),
    places: hospitals.map(h => ({
      id: h.id, name: h.name, kind: 'hospital', lat: h.lat, lon: h.lng,
    })),
    incidents: activeCalls.map(c => ({
      id: c.id,
      kind: c.priority === 'high' ? 'road_closure' : 'congestion',
      lat: c.lat, lon: c.lng, radius_m: 300,
      description: c.description,
    })),
  }
}

// ── Live data via SSE (/stream), fallback to polling ──────────────────────────

function useWorldState() {
  const [state, setState] = useState(null)

  useEffect(() => {
    const es = new EventSource(`${API_URL}/stream`)
    es.onmessage = (msg) => {
      try { setState(JSON.parse(msg.data)) } catch {}
    }
    return () => es.close()
  }, [])

  useEffect(() => {
    if (state) return
    let pollId = null
    const timerId = setTimeout(() => {
      pollId = setInterval(async () => {
        try {
          const s = await fetchState()
          setState(s)
        } catch {}
      }, 3000)
    }, 8000)
    return () => {
      clearTimeout(timerId)
      if (pollId !== null) clearInterval(pollId)
    }
  }, [state])

  return { state, offline: state === null }
}

// ── Shared action helper ──────────────────────────────────────────────────────

function useAction(setMessage, setBusy) {
  return async (fn) => {
    setBusy(true)
    setMessage(null)
    try {
      await fn()
    } catch (e) {
      setMessage({ kind: 'error', text: e.message })
    } finally {
      setBusy(false)
    }
  }
}

function deltaClass(before, after) {
  if (after < before) return 'better'
  if (after > before) return 'worse'
  return 'same'
}

// ── Root component ────────────────────────────────────────────────────────────

export default function App() {
  const { state, offline } = useWorldState()
  const [busy, setBusy]               = useState(false)
  const [message, setMessage]         = useState(null)
  const [cardMinimised, setCardMinimised] = useState(false)
  const action = useAction(setMessage, setBusy)

  const mapProps    = state ? liveToMapProps(state) : mockToMapProps()
  const run         = state?.agent?.runs?.[0] ?? null
  const showCard    = run?.status === 'done' && !!run?.recommendation
  const affectedIds = getAffectedVehicleIds(run, state)

  // Reset minimised whenever a new decision arrives
  const prevRunId = useRef(null)
  useEffect(() => {
    if (showCard && run.id !== prevRunId.current) {
      setCardMinimised(false)
      prevRunId.current = run.id
    }
  }, [run?.id, showCard])

  // Esc minimises the card
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape' && showCard && !cardMinimised) setCardMinimised(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [showCard, cardMinimised])

  const cardOpen           = showCard && !cardMinimised
  const highlightIds       = [...affectedIds]
  const highlightIncidents = cardOpen

  const wx = state?.weather?.now ?? null

  return (
    <div className="layout">
      <div className="map-container">
        <MapView {...mapProps} highlightIds={highlightIds} highlightIncidents={highlightIncidents} />
        {showCard && !cardMinimised && (
          <DecisionCard
            run={run}
            busy={busy}
            action={action}
            onMinimise={() => setCardMinimised(true)}
          />
        )}
        {showCard && cardMinimised && (
          <DecisionBar onShow={() => setCardMinimised(false)} />
        )}
      </div>

      <aside className="side-panel">

        {/* ── Header: brand · sim time · weather ── */}
        <div className="panel-header">
          <div className="ph-row">
            <div className="brand">
              <svg className="brand-mark" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <rect x="0.75" y="0.75" width="14.5" height="14.5" stroke="currentColor" strokeWidth="1.5"/>
                <path d="M5.5 5.5L10.5 8L5.5 10.5" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/>
              </svg>
              <span className="brand-wordmark">DISPATCH</span>
            </div>
            {state?.sim_time && (
              <span className="ph-simtime">{fmtSimTime(state.sim_time)}</span>
            )}
          </div>
          <div className="ph-row ph-row--sub">
            <span className="panel-city">Ljubljana</span>
            {wx && (
              <span className="ph-weather">
                {Math.round(wx.temperature_c)}°C
                {wx.weather_code != null && ` · ${wxDesc(wx.weather_code)}`}
              </span>
            )}
          </div>
        </div>

        {/* ── Fleet overview: all vehicles, status at a glance ── */}
        <FleetSection vehicles={state?.vehicles ?? []} />

        {/* ── KPI strip: late, pending, delay ── */}
        <KpiBar kpis={state?.kpis} />

        {/* ── Events zone: fills remaining height; overflow hidden — no scroll ── */}
        <div className="events-zone">
          {offline && <p className="offline-notice">OFFLINE — demo data</p>}
          {message && <p className={`inline-msg ${message.kind}`}>{message.text}</p>}
          <EventSection
            incidents={state?.incidents?.filter(i => i.active !== false) ?? []}
            trips={state?.trips ?? []}
            places={state?.places ?? []}
            events={state?.events ?? []}
          />
          <AlertsSection alerts={state?.alerts} />
          {run?.recommendation && !cardOpen && <SituationSection rec={run.recommendation} />}
          <DecisionLogSection runs={state?.agent?.runs ?? []} />
        </div>

        {/* ── Scenarios: fixed at base of panel ── */}
        <ScenariosSection busy={busy || run?.status === 'running'} action={action} />

        {/* ── Status: current agent + run state ── */}
        <StatusSection run={run} busy={busy} action={action} />

        {/* ── Legend ── */}
        <Legend />
      </aside>
    </div>
  )
}

// ── Floating decision card ────────────────────────────────────────────────────

function DecisionCard({ run, busy, action, onMinimise }) {
  const rec = run.recommendation
  const [selectedIdx, setSelectedIdx] = useState(rec.recommended_index)
  const [detailsOpen, setDetailsOpen] = useState(false)

  useEffect(() => {
    setSelectedIdx(rec.recommended_index)
    setDetailsOpen(false)
  }, [run.id])

  const trigger     = run.trigger.startsWith('event:') ? run.trigger.slice(6) : run.trigger
  const dot         = rec.situation.indexOf('. ')
  const lead        = dot > -1 ? rec.situation.slice(0, dot + 1) : rec.situation
  const detail      = dot > -1 ? rec.situation.slice(dot + 2).trim() : ''
  const selectedOpt = rec.options[selectedIdx]
  const kpisBefore  = rec.kpis_before

  // Collect every vehicle ID mentioned across all options' steps
  const mentionedVehicles = [...new Set(
    (rec.options ?? []).flatMap(opt =>
      (opt.steps ?? []).map(s => s.vehicle_id).filter(Boolean)
    )
  )]

  // KPI delta for the currently selected option
  const recDiff = selectedOpt?.kpis_after
    ? Math.round((selectedOpt.kpis_after.total_delay_min ?? 0) - (kpisBefore?.total_delay_min ?? 0))
    : null
  const recDeltaCls = recDiff == null ? 'same' : deltaClass(kpisBefore?.total_delay_min ?? 0, selectedOpt.kpis_after.total_delay_min ?? 0)

  return (
    <div className="decision-card">

      {/* ── Compact header strip: event tag + name + minimise ── */}
      <div className="dc-header">
        <div className="dc-header-left">
          <span className="dc-event-tag">EVENT</span>
          <span className="dc-event-name">{trigger.replace(/_/g, ' ')}</span>
        </div>
        <button className="dc-minimise" onClick={onMinimise}>Minimise</button>
      </div>

      {/* ── Scrollable body ── */}
      <div className="dc-body">

        {/* 1 — Situation: opening statement, large and readable */}
        <div className="dc-section">
          <span className="dc-label">SITUATION</span>
          <p className="dc-situation-lead">{lead}</p>
          {detail && <p className="dc-situation-detail">{detail}</p>}
        </div>

        {/* 2 — Affected vehicles: Teal chips with monospace IDs */}
        {mentionedVehicles.length > 0 && (
          <div className="dc-section dc-vehicles-row">
            <span className="dc-label">AFFECTED VEHICLES</span>
            <div className="dc-vehicle-chips">
              {mentionedVehicles.map(id => (
                <span key={id} className="dc-vehicle-chip">{id}</span>
              ))}
            </div>
          </div>
        )}

        {/* 3 — Recommended action: visual centerpiece, Teal left border */}
        <div className="dc-section dc-rec-section">
          <span className="dc-label">RECOMMENDED — OPTION {selectedIdx + 1}</span>
          <p className="dc-rec-title">{selectedOpt?.title}</p>
          {selectedOpt?.summary && (
            <p className="dc-rec-summary">{selectedOpt.summary}</p>
          )}
          {recDiff !== null && (
            <p className="dc-rec-delta">
              Delay impact:{' '}
              <span className={`opt-delta ${recDeltaCls}`}>
                {recDiff > 0 ? `+${recDiff}` : recDiff} min
              </span>
            </p>
          )}
          <div className="dc-action-row">
            <button
              className="btn-approve"
              disabled={busy}
              onClick={() => action(() => approveOption(run.id, selectedIdx))}
            >
              Approve
            </button>
            <button
              className="btn-reject"
              disabled={busy}
              onClick={() => action(() => rejectRun(run.id))}
            >
              Reject
            </button>
          </div>
        </div>

        {/* 4 — Alternatives: visually subordinate; click to swap selection */}
        {rec.options.length > 1 && (
          <div className="dc-section">
            <span className="dc-label">ALTERNATIVES</span>
            <table className="dc-alt-table">
              <tbody>
                {rec.options.map((opt, i) => {
                  if (i === selectedIdx) return null
                  const before = kpisBefore?.total_delay_min ?? 0
                  const after  = opt.kpis_after?.total_delay_min ?? 0
                  const diff   = Math.round(after - before)
                  const cls    = deltaClass(before, after)
                  return (
                    <tr key={i} className="dc-alt-row" onClick={() => setSelectedIdx(i)}>
                      <td className="dc-alt-num">{i + 1}</td>
                      <td className="dc-alt-title">{opt.title}</td>
                      <td className="dc-alt-delta">
                        {opt.kpis_after
                          ? <span className={`opt-delta ${cls}`}>{diff > 0 ? `+${diff}` : diff} min</span>
                          : <span className="opt-delta same">—</span>
                        }
                      </td>
                      <td className="dc-alt-summary">{opt.summary}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* 5 — Details: escalation notes and reasoning, collapsed by default */}
        {(rec.escalation || rec.reasoning) && (
          <div className="dc-section dc-last-section">
            <button className="dc-details-toggle" onClick={() => setDetailsOpen(d => !d)}>
              {detailsOpen ? '▾' : '▸'} Details
            </button>
            {detailsOpen && (
              <div className="dc-details-body">
                {rec.escalation && <p className="situation-detail" style={{ marginTop: 6 }}>{rec.escalation}</p>}
                {rec.reasoning  && <p className="rec-reasoning"   style={{ marginTop: 6 }}>{rec.reasoning}</p>}
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  )
}

// ── Minimised decision bar ────────────────────────────────────────────────────

function DecisionBar({ onShow }) {
  return (
    <div className="decision-bar">
      <span className="decision-bar-text">Decision pending</span>
      <span className="decision-bar-sep">·</span>
      <button className="decision-bar-show" onClick={onShow}>Show</button>
    </div>
  )
}

// ── Fleet overview ────────────────────────────────────────────────────────────

function chipCategory(status) {
  if (status === 'idle') return 'free'
  if (status === 'out_of_service') return 'oos'
  return 'call'
}

function chipLabel(status) {
  const map = {
    idle:          'FREE',
    to_pickup:     'DISPATCH',
    loading:       'LOAD',
    with_patient:  'EN ROUTE',
    returning:     'RTB',
    out_of_service:'OOS',
  }
  return map[status] ?? status.replace(/_/g, ' ').toUpperCase()
}

function VehicleChip({ v }) {
  const cat = chipCategory(v.status)
  return (
    <div className={`fleet-chip fleet-chip--${cat}`}>
      <span className="chip-id">{v.id}</span>
      <span className="chip-status">{chipLabel(v.status)}</span>
    </div>
  )
}

function FleetSection({ vehicles }) {
  const free    = vehicles.filter(v => v.status === 'idle').length
  const onCall  = vehicles.filter(v => v.status !== 'idle' && v.status !== 'out_of_service').length
  const oos     = vehicles.filter(v => v.status === 'out_of_service').length

  return (
    <div className="panel-section fleet-section">
      <div className="fleet-header">
        <span className="section-label" style={{ marginBottom: 0 }}>FLEET</span>
        <span className="fleet-summary">
          {free > 0    && <span className="fs-free">{free} free</span>}
          {onCall > 0  && <span className="fs-call">{onCall} call</span>}
          {oos > 0     && <span className="fs-oos">{oos} oos</span>}
        </span>
      </div>
      <div className="fleet-grid">
        {vehicles.map(v => <VehicleChip key={v.id} v={v} />)}
      </div>
    </div>
  )
}

// ── KPI strip ─────────────────────────────────────────────────────────────────

function KpiBar({ kpis }) {
  if (!kpis) return null

  const late      = kpis.late_trips ?? 0
  const lateCrit  = kpis.late_non_scheduled ?? 0
  const unassEm   = (kpis.unassigned?.emergency ?? 0) + (kpis.unassigned?.urgent ?? 0)
  const unassAll  = unassEm + (kpis.unassigned?.scheduled ?? 0)
  const delay     = kpis.total_delay_min ?? 0
  const inService = kpis.vehicles_in_service ?? null

  return (
    <div className="kpi-bar">
      <div className="kpi-item">
        <span className={`kpi-value${lateCrit > 0 ? ' kpi-crit' : late > 0 ? ' kpi-warn' : ''}`}>
          {late}
        </span>
        <span className="kpi-label">LATE</span>
      </div>
      <div className="kpi-item">
        <span className={`kpi-value${unassEm > 0 ? ' kpi-crit' : unassAll > 0 ? ' kpi-warn' : ''}`}>
          {unassAll}
        </span>
        <span className="kpi-label">PENDING</span>
      </div>
      <div className="kpi-item">
        <span className="kpi-value">
          {Math.round(delay)}<span className="kpi-unit">m</span>
        </span>
        <span className="kpi-label">DELAY</span>
      </div>
      {inService !== null && (
        <div className="kpi-item">
          <span className="kpi-value">{inService}</span>
          <span className="kpi-label">UP</span>
        </div>
      )}
    </div>
  )
}

// ── Alerts ────────────────────────────────────────────────────────────────────

function AlertsSection({ alerts }) {
  // Show only high/critical alerts; cap at 3 to prevent overflow
  const active = (alerts ?? [])
    .filter(a => a.severity === 'critical' || a.severity === 'high')
    .slice(0, 3)
  if (active.length === 0) return null

  return (
    <div className="panel-section alerts-section">
      <span className="section-label">ALERTS</span>
      <div className="alerts-list">
        {active.map(a => (
          <div key={a.id} className={`alert-line alert-line--${a.severity}`}>
            <span className="alert-text">{a.message}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Scenarios ─────────────────────────────────────────────────────────────────

const SCENARIOS = [
  { name: 'stranded_patient', label: 'Stranded patient' },
  { name: 'stroke_rush_hour', label: 'Stroke + closure' },
  { name: 'snow_cascade',     label: 'Snow cascade'     },
]

function ScenariosSection({ busy, action }) {
  return (
    <div className="panel-section">
      <span className="section-label">SCENARIOS</span>
      <div className="scenario-list">
        {SCENARIOS.map(s => (
          <button
            key={s.name}
            className="btn-scenario"
            disabled={busy}
            onClick={() => action(() => runScenario(s.name))}
          >
            {s.label}
          </button>
        ))}
      </div>
      <button
        className="btn-reset-link"
        disabled={busy}
        onClick={() => action(() => resetSimulation())}
      >
        Reset simulation
      </button>
    </div>
  )
}

// ── Status ────────────────────────────────────────────────────────────────────

function StatusSection({ run, busy, action }) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (!run || run.status !== 'running') { setElapsed(0); return }
    const start = new Date(run.started_at).getTime()
    const id = setInterval(() => {
      setElapsed(Math.round((Date.now() - start) / 1000))
    }, 1000)
    return () => clearInterval(id)
  }, [run?.id, run?.status])

  let text = 'MONITORING'
  let awaiting = false
  if (run) {
    if      (run.status === 'running')  { text = `ANALYSING · ${elapsed}s` }
    else if (run.status === 'done')     { text = 'AWAITING DECISION'; awaiting = true }
    else if (run.status === 'approved') { text = 'APPROVED' }
    else if (run.status === 'rejected') { text = 'REJECTED' }
    else                                { text = run.status.toUpperCase() }
  }

  // Show Analyse button when no analysis is running or pending a decision
  const canAnalyse = run?.status !== 'running' && run?.status !== 'done'

  return (
    <div className="panel-section status-section">
      <span className="section-label">STATUS</span>
      <p className={`status-line${run?.status === 'running' ? ' analysing' : ''}${awaiting ? ' awaiting' : ''}`}>{text}</p>
      {canAnalyse && (
        <button
          className="btn-analyse"
          disabled={busy}
          onClick={() => action(() => triggerAnalysis())}
        >
          Analyse
        </button>
      )}
    </div>
  )
}

// ── Events ────────────────────────────────────────────────────────────────────

function EventSection({ incidents, trips, places, events }) {
  const placeById = new Map((places ?? []).map(p => [p.id, p]))

  const urgentTrips = (trips ?? []).filter(t =>
    (t.priority === 'emergency' || t.priority === 'urgent') &&
    t.status !== 'completed' && t.status !== 'cancelled'
  )

  if ((incidents ?? []).length === 0 && urgentTrips.length === 0) return null

  // Cap at 4 items combined to stay within events-zone height
  const incSlice  = (incidents ?? []).slice(0, 4)
  const tripSlice = urgentTrips.slice(0, Math.max(0, 4 - incSlice.length))

  return (
    <div className="panel-section">
      <span className="section-label">EVENTS</span>
      <div className="event-list">
        {incSlice.map(inc => {
          const nearest = nearestPlace(inc.lat, inc.lon, places ?? [])
          const time = fmtSimTime(inc.created_at)
          return (
            <div key={inc.id} className="event-line">
              <span className="event-time">{time}</span>
              <span className="event-text">
                {incidentKindLabel(inc.kind)}{nearest ? ` · ${nearest.name}` : ''}
              </span>
            </div>
          )
        })}
        {tripSlice.map(t => {
          const pickup  = placeById.get(t.pickup_id)
          const dropoff = placeById.get(t.dropoff_id)
          const label   = t.priority === 'emergency' ? 'Emergency patient' : 'Urgent patient'
          const ev   = (events ?? []).find(e => e.affected_trip_ids?.includes(t.id))
          const time = fmtSimTime(ev?.sim_time ?? t.pickup_after)
          const route = [pickup?.name, dropoff?.name].filter(Boolean).join(' → ')
          return (
            <div key={t.id} className="event-line">
              <span className="event-time">{time}</span>
              <span className="event-text">{label}{route ? ` · ${route}` : ''}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Situation ─────────────────────────────────────────────────────────────────

function SituationSection({ rec }) {
  const dot    = rec.situation.indexOf('. ')
  const lead   = dot > -1 ? rec.situation.slice(0, dot + 1) : rec.situation
  const detail = dot > -1 ? rec.situation.slice(dot + 2).trim() : ''

  return (
    <div className="panel-section">
      <span className="section-label">SITUATION</span>
      <p className="situation-lead">{lead}</p>
      {detail && <p className="situation-detail">{detail}</p>}
      {rec.escalation && (
        <>
          <span className="section-label" style={{ marginTop: 10 }}>ACTIONS FOR CREW</span>
          <p className="situation-detail">{rec.escalation}</p>
        </>
      )}
    </div>
  )
}

// ── Decision log ──────────────────────────────────────────────────────────────

function fmtSimTime(iso) {
  if (!iso) return '--:--'
  try {
    return new Date(iso).toLocaleTimeString('sl-SI', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso.slice(11, 16)
  }
}

function DecisionLogSection({ runs }) {
  const decided = runs.filter(r => r.status === 'approved' || r.status === 'rejected')
  if (decided.length === 0) return null

  return (
    <div className="panel-section">
      <span className="section-label">DECISION LOG</span>
      <div className="log-lines">
        {decided.map(r => {
          const time    = fmtSimTime(r.finished_at)
          const trigger = r.trigger.startsWith('event:') ? r.trigger.slice(6) : r.trigger
          const verdict = r.status.toUpperCase()
          const optPart = r.status === 'approved' && r.decision?.option_index != null
            ? `  Option ${r.decision.option_index + 1}`
            : ''
          return (
            <div key={r.id} className="log-line">
              {time}{'  '}{trigger}{optPart}{'  '}
              <span className={`log-verdict ${r.status}`}>{verdict}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Legend ────────────────────────────────────────────────────────────────────

function Legend() {
  return (
    <div className="legend">
      <span className="legend-title">LEGEND</span>
      <div className="legend-grid">
        <LegendItem shape="dot"    color="var(--op-free)"    label="Free" />
        <LegendItem shape="dot"    color="var(--op-high)"    label="High pri" />
        <LegendItem shape="dot"    color="var(--op-mission)" label="On call" />
        <LegendItem shape="dot"    color="var(--op-medium)"  label="Medium pri" />
        <LegendItem shape="dot"    color="#9e9e9e"           label="OOS" />
        <LegendItem shape="square" color="var(--op-hospital)"label="Hospital" />
        <LegendItem shape="ring"   color="#555"              label="Base" />
      </div>
    </div>
  )
}

function LegendItem({ shape, color, label }) {
  const char = shape === 'square' ? '■' : shape === 'ring' ? '○' : '●'
  return (
    <div className="legend-item">
      <span className="legend-shape" style={{ color }}>{char}</span>
      <span className="legend-label">{label}</span>
    </div>
  )
}
