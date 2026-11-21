import { useEffect, useRef, useState } from 'react'
import Map from './Map'
import { API_URL, fetchState, runScenario, resetSimulation, approveOption, rejectRun } from './api'
import { ambulances, hospitals, activeCalls } from './mockData'

// ── Helpers ────────────────────────────────────────────────────────────────────

// Find the closest place to a lat/lon — used for incident location labels
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

// Vehicles that need a "pending decision" ring: active while run.status === 'done'
function getAffectedVehicleIds(run, state) {
  if (!run || run.status !== 'done') return new Set()
  const ids = new Set()
  for (const opt of (run.recommendation?.options ?? [])) {
    for (const step of (opt.steps ?? [])) {
      if (step.vehicle_id) ids.add(step.vehicle_id)
    }
  }
  // Always include broken-down vehicles
  for (const v of (state?.vehicles ?? [])) {
    if (v.status === 'out_of_service') ids.add(v.id)
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

  // If SSE delivers nothing within 8s, start polling /state as a fallback.
  // Once SSE delivers a message, polling stops.
  useEffect(() => {
    if (state) return
    const id = setTimeout(() => {
      if (state) return
      const poll = setInterval(async () => {
        try {
          const s = await fetchState()
          setState(s)
        } catch {}
      }, 3000)
      return () => clearInterval(poll)
    }, 8000)
    return () => clearTimeout(id)
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

// ── Extract vehicle IDs mentioned in recommendation text ──────────────────────

function extractHighlightIds(rec, vehicles) {
  if (!rec || !vehicles?.length) return []
  const text = [
    rec.situation ?? '',
    ...(rec.options?.map(o => `${o.title} ${o.summary}`) ?? []),
    rec.reasoning ?? '',
  ].join(' ')
  return vehicles.filter(v => text.includes(v.id)).map(v => v.id)
}

// ── Shared delta helper ───────────────────────────────────────────────────────

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

  const mapProps = state ? liveToMapProps(state) : mockToMapProps()
  const run      = state?.agent?.runs?.[0] ?? null
  const showCard = run?.status === 'done' && !!run?.recommendation

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
  // Ring shown on affected vehicles while a run is active (running or awaiting decision)
  const highlightIds       = [...affectedIds]
  const highlightIncidents = cardOpen

  return (
    <div className="layout">
      <div className="map-container">
        <Map {...mapProps} highlightIds={highlightIds} highlightIncidents={highlightIncidents} />
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
        <div className="panel-header">
          <span className="panel-title">DISPATCH</span>
          <span className="panel-city">Ljubljana</span>
        </div>

        <div className="panel-body">
          {offline && (
            <p className="offline-notice" style={{ padding: '8px 20px' }}>
              OFFLINE — showing demo data
            </p>
          )}
          {message && (
            <p className={`inline-msg ${message.kind}`}>{message.text}</p>
          )}

          <ScenariosSection busy={busy} action={action} />
          <StatusSection run={run} />
          <EventSection
            incidents={state?.incidents?.filter(i => i.active !== false) ?? []}
            trips={state?.trips ?? []}
            places={state?.places ?? []}
            events={state?.events ?? []}
          />
          {run?.recommendation && <SituationSection rec={run.recommendation} />}
          <DecisionLogSection runs={state?.agent?.runs ?? []} />
        </div>

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

  return (
    <div className="decision-card">
      <div className="dc-header">
        <span className="dc-event-tag">EVENT</span>
        <span className="dc-event-name">{trigger.replace(/_/g, ' ')}</span>
        <span className="dc-event-sep">·</span>
        <span className="dc-event-lead">{lead}</span>
        <button className="dc-minimise" onClick={onMinimise}>Minimise</button>
      </div>

      <div className="dc-section">
        <span className="dc-label">RECOMMENDED</span>
        <p className="dc-rec-title">Option {selectedIdx + 1} — {selectedOpt?.title}</p>
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

      {(detail || rec.escalation || rec.reasoning) && (
        <div className="dc-section dc-last-section">
          <button className="dc-details-toggle" onClick={() => setDetailsOpen(d => !d)}>
            {detailsOpen ? '▾' : '▸'} Details
          </button>
          {detailsOpen && (
            <div className="dc-details-body">
              {detail         && <p className="situation-detail">{detail}</p>}
              {rec.escalation && <p className="situation-detail" style={{ marginTop: 6 }}>{rec.escalation}</p>}
              {rec.reasoning  && <p className="rec-reasoning"   style={{ marginTop: 6 }}>{rec.reasoning}</p>}
            </div>
          )}
        </div>
      )}
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

function StatusSection({ run }) {
  const [elapsed, setElapsed] = useState(0)

  // Count up locally while agent is running so the counter is smooth
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

  return (
    <div className="panel-section">
      <span className="section-label">STATUS</span>
      <p className={`status-line${awaiting ? ' awaiting' : ''}`}>{text}</p>
    </div>
  )
}

// ── Event section — raw incident facts from state, shown before AI finishes ───

function EventSection({ incidents, trips, places, events }) {
  const placeById = new Map((places ?? []).map(p => [p.id, p]))

  const urgentTrips = (trips ?? []).filter(t =>
    (t.priority === 'emergency' || t.priority === 'urgent') &&
    t.status !== 'completed' && t.status !== 'cancelled'
  )

  if ((incidents ?? []).length === 0 && urgentTrips.length === 0) return null

  return (
    <div className="panel-section">
      <span className="section-label">EVENTS</span>
      <div className="event-list">
        {(incidents ?? []).map(inc => {
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
        {urgentTrips.map(t => {
          const pickup  = placeById.get(t.pickup_id)
          const dropoff = placeById.get(t.dropoff_id)
          const label   = t.priority === 'emergency' ? 'Emergency patient' : 'Urgent patient'
          // prefer the event timestamp when available
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

// ── Situation (panel: AI analysis, shown once recommendation is ready) ─────────

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
      <div className="legend-items">
        <LegendItem shape="dot"    color="#2f7d4f" label="Free" />
        <LegendItem shape="dot"    color="#b26b00" label="On mission" />
        <LegendItem shape="dot"    color="#9e9e9e" label="Out of service" />
        <LegendItem shape="square" color="#1f3a5f" label="Hospital" />
        <LegendItem shape="ring"   color="#555"    label="Base" />
        <LegendItem shape="dot"    color="#b3261e" label="High priority" />
        <LegendItem shape="dot"    color="#8a7a00" label="Medium" />
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
