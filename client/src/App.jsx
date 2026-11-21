import { useEffect, useState } from 'react'
import Map from './Map'
import { fetchState } from './api'
import { ambulances, hospitals, activeCalls } from './mockData'

// Convert live /state snapshot to the shape Map expects
function liveToMapProps(state) {
  return {
    vehicles: state.vehicles,
    places: state.places.filter(p => p.kind !== 'residential'),
    incidents: state.incidents.filter(i => i.active !== false),
  }
}

// Convert mockData to the same shape — used as fallback when backend is unreachable
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

export default function App() {
  const [mapProps, setMapProps] = useState(mockToMapProps())
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    async function load() {
      try {
        const state = await fetchState()
        setMapProps(liveToMapProps(state))
        setOffline(false)
      } catch {
        setMapProps(mockToMapProps())
        setOffline(true)
      }
    }

    load()
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [])

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
            <p className="offline-notice">OFFLINE — showing demo data</p>
          )}
          <p className="no-disruptions">
            {mapProps.incidents.length === 0
              ? 'No active disruptions'
              : `${mapProps.incidents.length} active incident${mapProps.incidents.length > 1 ? 's' : ''}`}
          </p>
        </div>

        <Legend />
      </aside>

    </div>
  )
}

function Legend() {
  return (
    <div className="legend">
      <span className="legend-title">LEGEND</span>
      <div className="legend-items">
        <LegendItem shape="dot"    color="#2f7d4f" label="Free" />
        <LegendItem shape="ring"   color="#b26b00" label="On mission" />
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
