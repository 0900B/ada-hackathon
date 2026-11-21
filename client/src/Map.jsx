import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { Circle, CircleMarker, LayersControl, MapContainer, Marker, Popup, TileLayer, Tooltip } from 'react-leaflet'

// Meaning-only colours from CLAUDE.md
const COLOR = {
  free:     '#2f7d4f',
  mission:  '#b26b00',
  hospital: '#1f3a5f',
  base:     '#555555',
  high:     '#b3261e',
  medium:   '#8a7a00',
  disabled: '#9e9e9e',
}

// Navy square for hospitals — no Leaflet built-in square shape
const hospitalIcon = L.divIcon({
  className: '',
  html: `<div style="width:10px;height:10px;background:${COLOR.hospital};border:1.5px solid #0a1f38;"></div>`,
  iconSize: [10, 10],
  iconAnchor: [5, 5],
  popupAnchor: [0, -8],
})

// Small outlined circle for ambulance bases
const baseIcon = L.divIcon({
  className: '',
  html: `<div style="width:8px;height:8px;border-radius:50%;border:1.5px solid ${COLOR.base};background:transparent;"></div>`,
  iconSize: [8, 8],
  iconAnchor: [4, 4],
  popupAnchor: [0, -6],
})

// Vehicle status → circle fill style
function vehicleStyle(v) {
  if (v.status === 'out_of_service') {
    return { color: COLOR.disabled, weight: 1, fillColor: COLOR.disabled, fillOpacity: 0.25 }
  }
  if (v.status === 'idle') {
    return { color: COLOR.free, weight: 1.5, fillColor: COLOR.free, fillOpacity: 0.85 }
  }
  // to_pickup, loading, with_patient, returning → on mission (solid amber)
  return { color: COLOR.mission, weight: 1.5, fillColor: COLOR.mission, fillOpacity: 0.85 }
}

// Incident kind → circle border colour
function incidentColor(kind) {
  if (kind === 'congestion') return COLOR.medium
  return COLOR.high  // road_closure, accident
}

export default function Map({ vehicles = [], places = [], incidents = [], highlightIds = [], highlightIncidents = false }) {
  const hospitals = places.filter(p => p.kind === 'hospital')
  const bases     = places.filter(p => p.kind === 'base')
  const callSites = places.filter(p => p.kind === 'call_location' || p.kind === 'incident_site')

  return (
    <MapContainer
      center={[46.0569, 14.5058]}
      zoom={14}
      style={{ width: '100%', height: '100%' }}
    >
      <LayersControl position="topright" collapsed={false}>
        <LayersControl.BaseLayer checked name="Light">
          <TileLayer
            className="tiles-light"
            url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            maxZoom={19}
          />
        </LayersControl.BaseLayer>
        <LayersControl.BaseLayer name="Standard">
          <TileLayer
            url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            maxZoom={19}
          />
        </LayersControl.BaseLayer>
        <LayersControl.BaseLayer name="Satellite">
          <TileLayer
            url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            attribution='Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community'
            maxZoom={19}
          />
        </LayersControl.BaseLayer>
      </LayersControl>

      {/* ── Hospitals: navy square ── */}
      {hospitals.map(h => (
        <Marker key={h.id} position={[h.lat, h.lon]} icon={hospitalIcon}>
          <Popup>
            <strong>{h.name}</strong>
          </Popup>
        </Marker>
      ))}

      {/* ── Ambulance bases: small grey ring ── */}
      {bases.map(b => (
        <Marker key={b.id} position={[b.lat, b.lon]} icon={baseIcon}>
          <Popup>{b.name}</Popup>
        </Marker>
      ))}

      {/* ── Active incidents: translucent circle sized to actual radius_m ── */}
      {incidents.map(inc => {
        const c = incidentColor(inc.kind)
        return (
          <Circle
            key={inc.id}
            center={[inc.lat, inc.lon]}
            radius={inc.radius_m}
            pathOptions={{ color: c, weight: 1.5, fillColor: c, fillOpacity: 0.15 }}
          >
            <Tooltip>{inc.description || inc.kind}</Tooltip>
          </Circle>
        )
      })}

      {/* ── Call/incident sites from places (urgent_request etc.) ── */}
      {callSites.map(p => (
        <CircleMarker
          key={p.id}
          center={[p.lat, p.lon]}
          radius={6}
          pathOptions={{ color: COLOR.high, weight: 1.5, fillColor: COLOR.high, fillOpacity: 0.8 }}
        >
          <Tooltip>{p.name}</Tooltip>
        </CircleMarker>
      ))}

      {/* ── Vehicles: colour by status, monospace ID label ── */}
      {vehicles.map(v => (
        <CircleMarker
          key={v.id}
          center={[v.lat, v.lon]}
          radius={v.type === 'ambulance' ? 7 : 6}
          pathOptions={vehicleStyle(v)}
        >
          <Tooltip
            permanent
            direction="right"
            offset={[12, 0]}
            className="amb-label"
          >
            {v.id}
          </Tooltip>
          <Popup>
            <span className="popup-id">{v.id}</span> — {v.name}<br />
            Status: {v.status.replace(/_/g, ' ')}<br />
            Type: {v.type}
          </Popup>
        </CircleMarker>
      ))}

      {/* ── Decision highlight: thin dark ring on vehicles and incidents referenced by the card ── */}
      {highlightIds.map(id => {
        const v = vehicles.find(v => v.id === id)
        if (!v) return null
        return (
          <CircleMarker
            key={`hl-${id}`}
            center={[v.lat, v.lon]}
            radius={(v.type === 'ambulance' ? 7 : 6) + 5}
            pathOptions={{ color: '#111', weight: 1.5, fill: false, opacity: 0.55 }}
          />
        )
      })}
      {highlightIncidents && incidents.map(inc => (
        <Circle
          key={`hl-inc-${inc.id}`}
          center={[inc.lat, inc.lon]}
          radius={inc.radius_m}
          pathOptions={{ color: '#111', weight: 2, fill: false, opacity: 0.45 }}
        />
      ))}
    </MapContainer>
  )
}
