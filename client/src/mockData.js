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
    situation: 'Transport T2 broke down on Tržaška cesta with a patient on board. 6 trips are now unassigned: 2 urgent, 4 scheduled.',
    options: [
      {
        title: 'Dispatch T4 to patient, reassign urgent trips',
        summary: 'T4 diverts to the breakdown site (ETA 8 min) and completes patient drop-off. T3 picks up urgent TR-007. Covers all critical demand within the existing fleet.',
        steps: [{ vehicle_id: 'T4', trip_id: 'TR-005' }, { vehicle_id: 'T3', trip_id: 'TR-009' }],
        kpis_after: { total_delay_min: 12, late_trips: 1, unassigned: { emergency: 0, urgent: 0, scheduled: 2 } },
        pros: ['Patient retrieved in 8 min', 'Both urgent trips covered'],
        cons: ['T4 misses next scheduled run by 22 min'],
        feasible: true,
      },
      {
        title: 'Dispatch T3 only — lower disruption',
        summary: 'T3 reroutes to patient (ETA 11 min). T4 continues current schedule. Urgent trips await T1 return in 20 min.',
        steps: [{ vehicle_id: 'T3', trip_id: 'TR-005' }],
        kpis_after: { total_delay_min: 24, late_trips: 2, unassigned: { emergency: 0, urgent: 2, scheduled: 4 } },
        pros: ['T4 schedule preserved'],
        cons: ['Urgent trips unresolved for 20+ min'],
        feasible: true,
      },
      {
        title: 'Request mutual aid from Vič station',
        summary: 'Call 1 vehicle from neighboring station (ETA 18 min). Fleet schedule fully preserved; all trips eventually covered.',
        steps: [],
        kpis_after: { total_delay_min: 34, late_trips: 0, unassigned: { emergency: 0, urgent: 0, scheduled: 0 } },
        pros: ['All trips covered', 'Fleet schedule preserved'],
        cons: ['18 min wait for stranded patient', 'External resource required'],
        feasible: true,
      },
    ],
    recommended_index: 0,
    kpis_before: { total_delay_min: 0, late_trips: 0, unassigned: { emergency: 0, urgent: 2, scheduled: 4 } },
    reasoning: "Option 1 is fastest for the stranded patient and resolves both urgent trips within the existing fleet. T4's 22-minute delay to its next scheduled run is acceptable given patient urgency.",
    escalation: 'Notify receiving facility of T2 breakdown. Contact patient family. Arrange T2 recovery from Tržaška cesta.',
  },
}
