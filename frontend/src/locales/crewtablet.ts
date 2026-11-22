/**
 * Patient-compartment tablet (/crew/:id): the strings of the redesigned crew view that the older
 * phone view did not have (the ETA panel, the clinical log, the timeline, the tap pads). Keys start
 * with "pt.". Strings the phone view already had keep their "tab." and "crew." keys (field.ts).
 *
 * The Slovenian side was written by the developer and has not been checked by a paramedic.
 */
import type { Translation } from "../i18n";

export const en = {
  // ETA panel
  "pt.region.doctor": "Doctor car",
  "pt.region.er": "Arrival at the hospital",
  "pt.region.patient": "Arrival at the patient",
  "pt.region.status": "Vehicle status",
  "pt.er": "ER",
  "pt.dropoff": "Drop-off",
  "pt.min": "min",
  "pt.arrive": "Arrive",
  "pt.late": "+{min} min late",
  "pt.patientIn": "Patient in",
  "pt.then": "then {dest}",
  "pt.noPatient": "No patient",
  "pt.equipmentLabel": "Equipment:",

  // Log area
  "pt.log": "Log",
  "pt.logAria": "Clinical log",
  "pt.notSent": "{count} not sent yet",
  "pt.noPatientBoard": "No patient on board",
  "pt.notLogged": "No patient on board: not logged",
  "pt.nothingToConfirm": "Nothing to confirm",
  "pt.confirmedNote": "Confirmed",
  "pt.logHold": "Hold to log",
  "pt.logListening": "Logging… release to keep",
  "pt.logSubIdle": "say “potrjeno” to confirm the last note",
  "pt.logSubListening": "stays on the tablet, not sent to dispatch",
  "pt.logNeedsChrome": "Voice logging needs Chrome or Edge. Type a note instead.",
  "pt.notePlaceholder": "Type a note…",
  "pt.noteAria": "Typed note for the log",
  "pt.addNote": "Add note",

  // Dispatch area
  "pt.dispatch": "Dispatch",
  "pt.holdDispatch": "Hold to talk to dispatch",

  // Timeline
  "pt.tl.empty": "Nothing logged yet. Hold the log button and speak, or type a note.",
  "pt.tl.aria": "Timeline, newest first",
  "pt.tl.now": "now",
  "pt.tl.ago": "{min} min ago",
  "pt.state.heard": "heard",
  "pt.state.confirmed": "confirmed",
  "pt.check": "check this",
  "pt.sync.pending": "pending",
  "pt.sync.sent": "sent",
  "pt.sync.rejected": "not accepted",
  "pt.sync.title": "Sync: {state}",
  "pt.confirm": "Confirm",
  "pt.discard": "Discard",
};

export const sl: Translation<typeof en> = {
  "pt.region.doctor": "Zdravniško vozilo",
  "pt.region.er": "Prihod v bolnišnico",
  "pt.region.patient": "Prihod k pacientu",
  "pt.region.status": "Stanje vozila",
  "pt.er": "UC",
  "pt.dropoff": "Predaja",
  "pt.min": "min",
  "pt.arrive": "Prihod",
  "pt.late": "+{min} min zamude",
  "pt.patientIn": "Pacient čez",
  "pt.then": "nato {dest}",
  "pt.noPatient": "Ni pacienta",
  "pt.equipmentLabel": "Oprema:",

  "pt.log": "Zapis",
  "pt.logAria": "Klinični zapis",
  "pt.notSent": "Neposlano: {count}",
  "pt.noPatientBoard": "Ni pacienta v vozilu",
  "pt.notLogged": "Ni pacienta v vozilu: ni zapisano",
  "pt.nothingToConfirm": "Ni česa potrditi",
  "pt.confirmedNote": "Potrjeno",
  "pt.logHold": "Držite za zapis",
  "pt.logListening": "Zapisujem … spustite za shranitev",
  "pt.logSubIdle": "recite »potrjeno«, da potrdite zadnji zapis",
  "pt.logSubListening": "ostane na tablici, ni poslano dispečerju",
  "pt.logNeedsChrome": "Glasovni zapis deluje v Chromu ali Edgu. Vpišite opombo.",
  "pt.notePlaceholder": "Vpišite opombo …",
  "pt.noteAria": "Vpisana opomba za zapis",
  "pt.addNote": "Dodaj opombo",

  "pt.dispatch": "Dispečer",
  "pt.holdDispatch": "Držite za govor dispečerju",

  "pt.tl.empty": "Še ni zapisov. Držite gumb za zapis in govorite ali vpišite opombo.",
  "pt.tl.aria": "Časovnica, najnovejše zgoraj",
  "pt.tl.now": "zdaj",
  "pt.tl.ago": "pred {min} min",
  "pt.state.heard": "slišano",
  "pt.state.confirmed": "potrjeno",
  "pt.check": "preverite",
  "pt.sync.pending": "čaka",
  "pt.sync.sent": "poslano",
  "pt.sync.rejected": "ni sprejeto",
  "pt.sync.title": "Sinhronizacija: {state}",
  "pt.confirm": "Potrdi",
  "pt.discard": "Zavrzi",
};
