import { useEffect, useState } from 'react'
import Map from './Map'
import { API_URL, fetchState, runScenario, resetSimulation } from './api'
import { ambulances, hospitals, activeCalls } from './mockData'

// ── Data conversion ────────────────────────────────────────────────────────────

function liveToMapProps(state) {
  return {
    vehicles: state.vehicles,
    places:   state.places.filter(p => p.kind !== 'residential'),
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
      // stop polling as soon as SSE kicks in
      return () => clearInterval(poll)
    }, 8000)
    return () => clearTimeout(id)
  }, [state])

  const offline = state === null
  return { state, offline }
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

// ── Root component ────────────────────────────────────────────────────────────

export default function App() {
  const { state, offline } = useWorldState()
  const [busy, setBusy]       = useState(false)
  const [message, setMessage] = useState(null)
  const action = useAction(setMessage, setBusy)

  const mapProps = state ? liveToMapProps(state) : mockToMapProps()
  const run      = state?.agent?.runs?.[0] ?? null

  return (
    <div className="layout">
      <div className="map-container">
        <Map {...mapProps} />
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

          {/* Parts 2 and 3 will be added here */}
        </div>

        <Legend />
      </aside>
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
      <div className="scenario-grid">
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
        <button
          className="btn-scenario btn-reset"
          disabled={busy}
          onClick={() => action(() => resetSimulation())}
        >
          Reset
        </button>
      </div>
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
