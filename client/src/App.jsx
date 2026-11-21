import Map from './Map'

// Root layout: map on the left (~70%), dispatch panel on the right (~30%).
export default function App() {
  return (
    <div className="layout">

      <div className="map-container">
        <Map />
      </div>

      <aside className="side-panel">
        <div className="panel-header">
          <span className="panel-title">DISPATCH CO-PILOT</span>
          <span className="panel-city">Ljubljana</span>
        </div>
        <div className="panel-body">
          <p className="no-disruptions">No active disruptions</p>
        </div>
      </aside>

    </div>
  )
}
