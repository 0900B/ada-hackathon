// Simulated Ljubljana dispatch data.
// Replace with live backend calls later — the shape of these objects
// is what the map components depend on.

export const ambulances = [
  { id: 'R1', status: 'free',       lat: 46.0620, lng: 14.5120 },
  { id: 'R2', status: 'on_mission', lat: 46.0580, lng: 14.4920 },
  { id: 'R3', status: 'free',       lat: 46.0490, lng: 14.5250 },
  { id: 'R4', status: 'on_mission', lat: 46.0700, lng: 14.5340 },
  { id: 'R5', status: 'free',       lat: 46.0530, lng: 14.4760 },
  { id: 'R6', status: 'on_mission', lat: 46.0750, lng: 14.5050 },
]

export const hospitals = [
  // Real Ljubljana hospital coordinates
  { id: 'ukc',       name: 'UKC Ljubljana',                   lat: 46.0640, lng: 14.4931 },
  { id: 'pediatric', name: 'Pediatrična klinika Ljubljana',   lat: 46.0618, lng: 14.4879 },
  { id: 'psych',     name: 'Psihiatrična klinika Ljubljana',  lat: 46.0765, lng: 14.4830 },
]

export const activeCalls = [
  { id: 'C1', priority: 'high',   description: 'Cardiac arrest – Metelkova',   lat: 46.0558, lng: 14.5135, assignedAmbulance: 'R2' },
  { id: 'C2', priority: 'medium', description: 'Traffic accident – Dunajska',  lat: 46.0712, lng: 14.5062, assignedAmbulance: 'R6' },
  { id: 'C3', priority: 'high',   description: 'Chest pain – Šiška',           lat: 46.0798, lng: 14.4876, assignedAmbulance: 'R4' },
  { id: 'C4', priority: 'medium', description: 'Fall, elderly – Fužine',       lat: 46.0501, lng: 14.5451, assignedAmbulance: null  },
]

// Demo recommendation — shown when backend is offline so the decision screen
// is always visible for presentation without a live connection.
export const MOCK_RUN = {
  id: 'MOCK-001',
  status: 'done',
  trigger: 'stranded_patient',
  started_at: new Date(Date.now() - 22000).toISOString(),
  finished_at: new Date(Date.now() - 4000).toISOString(),
  recommendation: {
    situation: 'R2 broke down on Tržaška cesta with a patient on board. 2 urgent and 4 scheduled trips are now unassigned.',
    options: [
      {
        title: 'Dispatch R4 to patient — R3 covers urgent trips',
        summary: 'R4 diverts to the breakdown site (ETA 8 min) and completes patient drop-off. R3 picks up 2 urgent trips. Covers all critical demand within the existing fleet.',
        steps: [{ vehicle_id: 'R4' }, { vehicle_id: 'R3' }],
        kpis_after: { total_delay_min: 12, late_trips: 1, unassigned: { emergency: 0, urgent: 0, scheduled: 2 } },
        feasible: true,
      },
      {
        title: 'Dispatch R3 only — lower disruption',
        summary: 'R3 reroutes to patient (ETA 11 min). R4 continues schedule. Urgent trips await R1 return in 20 min.',
        steps: [{ vehicle_id: 'R3' }],
        kpis_after: { total_delay_min: 24, late_trips: 2, unassigned: { emergency: 0, urgent: 2, scheduled: 4 } },
        feasible: true,
      },
      {
        title: 'Request mutual aid from Vič station',
        summary: 'External unit arrives in 18 min. Fleet schedule fully preserved; all trips eventually covered.',
        steps: [],
        kpis_after: { total_delay_min: 34, late_trips: 0, unassigned: { emergency: 0, urgent: 0, scheduled: 0 } },
        feasible: true,
      },
    ],
    recommended_index: 0,
    kpis_before: { total_delay_min: 0, late_trips: 0, unassigned: { emergency: 0, urgent: 2, scheduled: 4 } },
    reasoning: 'R4 is closest to the breakdown (ETA 8 min). R3 covering urgent trips resolves all critical demand without external resources.',
    escalation: 'Notify receiving facility of R2 breakdown. Contact patient family. Arrange R2 recovery from Tržaška cesta.',
  },
}

// Per-scenario mock scenes — applied as fallback when backend is offline or unresponsive.
// Incidents use lon (not lng) to match the live state shape.
export const MOCK_SCENARIO_DEFS = {
  stranded_patient: {
    incidents: [
      { id: 'demo-sp-1', kind: 'road_closure', lat: 46.0582, lon: 14.4985, radius_m: 280,
        description: 'Vehicle breakdown – Tržaška cesta', active: true },
    ],
    kpis: { total_delay_min: 18, late_trips: 2, vehicles_in_service: 5,
            unassigned: { emergency: 0, urgent: 2, scheduled: 4 } },
    recommendation: {
      situation: 'R2 broke down on Tržaška cesta with a patient on board. 2 urgent and 4 scheduled trips are now unassigned.',
      options: [
        {
          title: 'Dispatch R4 to patient — R3 covers urgent trips',
          summary: 'R4 reroutes to breakdown (ETA 8 min). R3 picks up 2 urgent trips. All critical demand covered within existing fleet.',
          steps: [{ vehicle_id: 'R4' }, { vehicle_id: 'R3' }],
          kpis_after: { total_delay_min: 12, late_trips: 1, unassigned: { emergency: 0, urgent: 0, scheduled: 2 } },
          feasible: true,
        },
        {
          title: 'Dispatch R3 only — lower disruption',
          summary: 'R3 goes to patient (ETA 11 min). R4 keeps schedule. Urgent trips await R1 return in 20 min.',
          steps: [{ vehicle_id: 'R3' }],
          kpis_after: { total_delay_min: 24, late_trips: 2, unassigned: { emergency: 0, urgent: 2, scheduled: 4 } },
          feasible: true,
        },
        {
          title: 'Request mutual aid from Vič station',
          summary: 'External unit arrives in 18 min. Fleet schedule preserved; all trips eventually covered.',
          steps: [],
          kpis_after: { total_delay_min: 34, late_trips: 0, unassigned: { emergency: 0, urgent: 0, scheduled: 0 } },
          feasible: true,
        },
      ],
      recommended_index: 0,
      kpis_before: { total_delay_min: 0, late_trips: 0, unassigned: { emergency: 0, urgent: 2, scheduled: 4 } },
      reasoning: 'R4 reaches the patient in 8 min. R3 covering urgent trips resolves all critical demand without external resources.',
      escalation: 'Notify receiving facility of R2 breakdown. Contact patient family. Arrange R2 recovery from Tržaška cesta.',
    },
  },

  stroke_rush_hour: {
    incidents: [
      { id: 'demo-srh-1', kind: 'road_closure', lat: 46.0712, lon: 14.5062, radius_m: 320,
        description: 'Road closure – Dunajska cesta', active: true },
      { id: 'demo-srh-2', kind: 'accident',     lat: 46.0640, lon: 14.5120, radius_m: 180,
        description: 'Stroke patient – Metelkova', active: true },
    ],
    kpis: { total_delay_min: 31, late_trips: 3, vehicles_in_service: 5,
            unassigned: { emergency: 1, urgent: 1, scheduled: 3 } },
    recommendation: {
      situation: 'Stroke patient on Metelkova. Dunajska cesta closed — primary route for R4 and R6 blocked. Rush hour adds 8–12 min to all east-side responses.',
      options: [
        {
          title: 'Dispatch R1 via Slovenska — avoids closure',
          summary: 'R1 routes via Slovenska cesta (ETA 9 min). R4 reroutes current trip via Tivolska. 2 trips delayed; no emergencies unassigned.',
          steps: [{ vehicle_id: 'R1' }, { vehicle_id: 'R4' }],
          kpis_after: { total_delay_min: 17, late_trips: 2, unassigned: { emergency: 0, urgent: 0, scheduled: 1 } },
          feasible: true,
        },
        {
          title: 'Dispatch R6 from Šiška — shorter distance',
          summary: 'R6 is closer but must cross partial closure (ETA 13 min). R4 delayed 15 min.',
          steps: [{ vehicle_id: 'R6' }, { vehicle_id: 'R4' }],
          kpis_after: { total_delay_min: 27, late_trips: 3, unassigned: { emergency: 0, urgent: 1, scheduled: 1 } },
          feasible: true,
        },
      ],
      recommended_index: 0,
      kpis_before: { total_delay_min: 8, late_trips: 1, unassigned: { emergency: 1, urgent: 1, scheduled: 3 } },
      reasoning: 'R1 via Slovenska avoids the closure entirely and arrives 4 min faster than R6 through partial congestion. Minimises total delay while guaranteeing stroke response time.',
      escalation: 'Alert stroke team at UKC — ETA 9 min. Coordinate with traffic control on Dunajska closure duration.',
    },
  },

  snow_cascade: {
    incidents: [
      { id: 'demo-sc-1', kind: 'congestion', lat: 46.0569, lon: 14.5058, radius_m: 420,
        description: 'Snow congestion – City centre', active: true },
      { id: 'demo-sc-2', kind: 'congestion', lat: 46.0750, lon: 14.5050, radius_m: 360,
        description: 'Snow congestion – Šiška', active: true },
      { id: 'demo-sc-3', kind: 'road_closure', lat: 46.0490, lon: 14.5250, radius_m: 260,
        description: 'Road blocked – Fužine', active: true },
    ],
    kpis: { total_delay_min: 48, late_trips: 4, vehicles_in_service: 4,
            unassigned: { emergency: 1, urgent: 2, scheduled: 5 } },
    recommendation: {
      situation: 'Heavy snowfall causing three simultaneous congestion points across the network. Response times up 40%. R5 delayed 22 min on current trip. 1 emergency unassigned.',
      options: [
        {
          title: 'Activate winter routing — reroute R2, R5, R6',
          summary: 'Switch to pre-planned winter routes. R2 covers R5 delay. All emergencies met within 15 min; scheduled trips accept 20–30 min delay.',
          steps: [{ vehicle_id: 'R2' }, { vehicle_id: 'R5' }, { vehicle_id: 'R6' }],
          kpis_after: { total_delay_min: 28, late_trips: 2, unassigned: { emergency: 0, urgent: 0, scheduled: 3 } },
          feasible: true,
        },
        {
          title: 'Prioritise emergencies — hold scheduled trips',
          summary: 'All available units redirected to emergency demand. 5 scheduled trips deferred until conditions improve.',
          steps: [{ vehicle_id: 'R1' }, { vehicle_id: 'R3' }, { vehicle_id: 'R5' }],
          kpis_after: { total_delay_min: 48, late_trips: 0, unassigned: { emergency: 0, urgent: 1, scheduled: 5 } },
          feasible: true,
        },
      ],
      recommended_index: 0,
      kpis_before: { total_delay_min: 12, late_trips: 2, unassigned: { emergency: 1, urgent: 2, scheduled: 5 } },
      reasoning: 'Winter routing resolves all critical demand within 15 min while limiting total disruption. Deferring scheduled trips prematurely increases backlog without improving emergency response.',
      escalation: 'Activate winter contingency protocol. Notify all crews of route changes. Alert dispatch — elevated ETAs until plows clear Šiška and Fužine.',
    },
  },
}
