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
