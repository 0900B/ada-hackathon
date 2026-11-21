import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { MapContainer, TileLayer, CircleMarker, Marker, Popup, Tooltip } from 'react-leaflet'
import { ambulances, hospitals, activeCalls } from './mockData'

// Semantic colours — match the design rules in CLAUDE.md
const COLOR = {
  free:       '#2f7d4f',
  on_mission: '#b26b00',
  hospital:   '#1f3a5f',
  high:       '#b3261e',
  medium:     '#8a7a00',
}

// Square marker for hospitals (Leaflet doesn't have a built-in square shape)
const hospitalIcon = L.divIcon({
  className: '',   // suppress leaflet's default white box
  html: `<div style="
    width: 10px;
    height: 10px;
    background: ${COLOR.hospital};
    border: 1.5px solid #0a1f38;
  "></div>`,
  iconSize: [10, 10],
  iconAnchor: [5, 5],
  popupAnchor: [0, -8],
})

export default function Map() {
  return (
    <MapContainer
      center={[46.0569, 14.5058]}   // Ljubljana city centre
      zoom={13}
      style={{ width: '100%', height: '100%' }}
    >
      {/* CARTO Positron — clean light tiles */}
      <TileLayer
        url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
        subdomains="abcd"
        maxZoom={20}
      />

      {/* ── Hospitals: small square ── */}
      {hospitals.map(h => (
        <Marker key={h.id} position={[h.lat, h.lng]} icon={hospitalIcon}>
          <Popup>
            <strong>{h.name}</strong>
          </Popup>
        </Marker>
      ))}

      {/* ── Active calls: filled circle, coloured by priority ── */}
      {activeCalls.map(c => (
        <CircleMarker
          key={c.id}
          center={[c.lat, c.lng]}
          radius={6}
          pathOptions={{
            color: '#1a1a1a',           // dark outline
            weight: 1.5,
            fillColor: COLOR[c.priority],
            fillOpacity: 0.9,
          }}
        >
          <Popup>
            <span className="popup-id">{c.id}</span> {c.priority.toUpperCase()}<br />
            {c.description}<br />
            {c.assignedAmbulance
              ? <span>Assigned: {c.assignedAmbulance}</span>
              : <span className="popup-warn">Unassigned</span>
            }
          </Popup>
        </CircleMarker>
      ))}

      {/* ── Ambulances: filled circle (free) or ring (on_mission) ── */}
      {ambulances.map(a => (
        <CircleMarker
          key={a.id}
          center={[a.lat, a.lng]}
          radius={7}
          pathOptions={
            a.status === 'free'
              ? { color: COLOR.free, weight: 1.5, fillColor: COLOR.free, fillOpacity: 0.9 }
              : { color: COLOR.on_mission, weight: 2.5, fillColor: COLOR.on_mission, fillOpacity: 0 }
          }
        >
          {/* Small monospace ID next to the circle */}
          <Tooltip
            permanent
            direction="right"
            offset={[9, 0]}
            className="amb-label"
          >
            {a.id}
          </Tooltip>
          <Popup>
            <span className="popup-id">{a.id}</span><br />
            Status: {a.status === 'free' ? 'Free' : 'On mission'}
          </Popup>
        </CircleMarker>
      ))}
    </MapContainer>
  )
}
