"""Synthetic patient and voice-entry templates for the playback scripts.

Every entry: (anchor, offset_s, mode, transcript_sl, type, content, asr_confidence, flags)
anchor: "scene" = seconds after the crew reaches the patient, "transport" = seconds after leaving the scene, "arrival" = seconds after reaching the hospital.
mode: "wake" = started with the wake phrase, "ptt" = push-to-talk. Flag "alert:<text>" raises an ER alert, "check" = low confidence, stays unconfirmed until corrected,
"doctor" = said by the doctor vehicle's crew when a doctor is on scene, "corrects:<n>" = corrects the n-th entry of the template (0-based).
The Slovenian transcripts are drafts to be read by a native speaker. All clinical content is synthetic and not guidance.
"""

W, P = "wake", "ptt"


def E(anchor, off, mode, text, typ, content, conf=0.94, *flags):
    return (anchor, off, mode, text, typ, content, conf, list(flags))


def M(anchor, off, **vit):
    return (anchor, off, vit)


TEMPLATES = {
    "chest_pain": {
        "category": "Chest pain, suspected heart attack", "age": (52, 72), "sex": "M",
        "vitals0": {"hr": 98, "sbp": 150, "dbp": 90, "spo2": 94, "rr": 20, "gcs": 15},
        "monitor": [M("scene", 40, hr=98, sbp=150, dbp=90, spo2=94, rr=20), M("transport", 240, hr=90, sbp=138, dbp=86, spo2=96, rr=18), M("transport", 600, hr=84, sbp=132, dbp=82, spo2=97, rr=16)],
        "entries": [
            E("scene", 60, W, "Zapis, bolečina v prsih od pol ure, jakost osem od deset.", "assessment", {"pain_nrs": 8, "onset": "30 min before the call"}, 0.95),
            E("scene", 150, P, "Dvanajstkanalni EKG narejen, dvig ST v spodnjih odvodih.", "procedure", {"name": "12-lead ECG", "result": "ST elevation, inferior leads"}, 0.9, "alert:Suspected STEMI (inferior leads)"),
            E("scene", 240, W, "Zapis, aspirin tristo miligramov per os.", "drug_administered", {"drug": "aspirin", "dose": "300 mg", "route": "PO"}, 0.96),
            E("scene", 330, W, "Zapis, nitroglicerin sprej, dva vpiha pod jezik.", "drug_administered", {"drug": "nitroglycerin spray", "dose": "2 doses", "route": "SL"}, 0.9),
            E("transport", 60, W, "Zapis, morfin pet miligramov intravenozno.", "drug_administered", {"drug": "morphine", "dose": "5 mg", "route": "IV"}, 0.93),
            E("transport", 260, P, "Krvni tlak sto dvajset na osemnajst, saturacija devetdeset sedem.", "vitals", {"sbp": 120, "dbp": 18, "spo2": 97}, 0.55, "check"),
            E("transport", 285, P, "Popravek, osemdeset, ne osemnajst.", "vitals", {"sbp": 120, "dbp": 80, "spo2": 97}, 0.92, "corrects:5"),
        ]},
    "cardiac_arrest": {
        "category": "Cardiac arrest, resuscitation", "age": (50, 78), "sex": None,
        "vitals0": {"hr": 0, "sbp": 0, "dbp": 0, "spo2": 0, "rr": 0, "gcs": 3},
        "monitor": [M("scene", 25, hr=0, sbp=0, dbp=0, spo2=0, rr=0, rhythm="VF"), M("scene", 460, hr=112, sbp=88, dbp=58, spo2=90, rr=10, rhythm="sinus tachycardia"), M("transport", 300, hr=104, sbp=96, dbp=62, spo2=98, rr=12)],
        "entries": [
            E("scene", 20, P, "Pacient ne diha in nima pulza, začenjam masažo srca.", "event", {"event": "cardiac_arrest", "cpr": "started"}, 0.95, "alert:Cardiac arrest, CPR started"),
            E("scene", 70, W, "Zapis, defibrilacija ena, dvesto joulov.", "procedure", {"name": "defibrillation", "energy": "200 J", "number": 1}, 0.95),
            E("scene", 140, W, "Zapis, adrenalin en miligram intravenozno.", "drug_administered", {"drug": "adrenaline", "dose": "1 mg", "route": "IV"}, 0.94, "doctor"),
            E("scene", 260, W, "Zapis, intubacija opravljena, tubus sedem in pol.", "procedure", {"name": "intubation", "tube": "7.5"}, 0.9, "doctor", "alert:Intubated"),
            E("scene", 450, P, "Povrnitev spontanega krvnega obtoka.", "event", {"event": "ROSC"}, 0.93, "alert:Return of spontaneous circulation"),
            E("transport", 70, W, "Zapis, krvni tlak devetdeset na šestdeset, srčni utrip sto deset.", "vitals", {"sbp": 90, "dbp": 60, "hr": 110}, 0.92),
            E("transport", 320, P, "Pacient je prezračevan, saturacija osemindevetdeset.", "vitals", {"spo2": 98}, 0.9),
        ]},
    "stroke": {
        "category": "Suspected stroke", "age": (62, 84), "sex": None,
        "vitals0": {"hr": 84, "sbp": 168, "dbp": 100, "spo2": 96, "rr": 16, "gcs": 14},
        "monitor": [M("scene", 40, hr=84, sbp=168, dbp=100, spo2=96, rr=16), M("transport", 300, hr=80, sbp=160, dbp=96, spo2=97, rr=16)],
        "entries": [
            E("scene", 45, W, "Zapis, FAST pozitiven, povešen obraz levo, šibkost leve roke.", "assessment", {"FAST": "positive", "face": "left droop", "arm": "left weakness"}, 0.94),
            E("scene", 90, P, "Začetek simptomov ob devetih petintrideset.", "onset_time", {"onset": "09:35"}, 0.9, "alert:Suspected stroke, onset time logged"),
            E("scene", 150, W, "Zapis, krvni sladkor šest celih dve.", "vitals", {"glucose_mmol_l": 6.2}, 0.93),
            E("transport", 60, P, "Pacient pri zavesti, GCS štirinajst, krvni tlak sto osemdeset na sto.", "vitals", {"gcs": 14, "sbp": 180, "dbp": 100}, 0.88),
        ]},
    "fall_hip": {
        "category": "Fall, suspected hip fracture", "age": (72, 92), "sex": "F",
        "vitals0": {"hr": 92, "sbp": 142, "dbp": 82, "spo2": 96, "rr": 18, "gcs": 15},
        "monitor": [M("scene", 40, hr=92, sbp=142, dbp=82, spo2=96, rr=18), M("transport", 240, hr=86, sbp=138, dbp=80, spo2=97, rr=16)],
        "entries": [
            E("scene", 60, W, "Zapis, padec doma, boleče desno stegno, noga skrajšana in zasukana navzven.", "assessment", {"finding": "suspected hip fracture, right leg shortened and externally rotated", "pain_nrs": 7}, 0.92),
            E("scene", 180, W, "Zapis, morfin tri miligrame intravenozno.", "drug_administered", {"drug": "morphine", "dose": "3 mg", "route": "IV"}, 0.93),
            E("transport", 90, P, "Imobilizacija opravljena, bolečina štiri od deset.", "procedure", {"name": "immobilisation", "pain_nrs": 4}, 0.9),
        ]},
    "pedestrian_trauma": {
        "category": "Pedestrian hit by a car, major trauma", "age": (24, 62), "sex": None,
        "vitals0": {"hr": 112, "sbp": 108, "dbp": 70, "spo2": 95, "rr": 24, "gcs": 14},
        "monitor": [M("scene", 40, hr=112, sbp=108, dbp=70, spo2=95, rr=24), M("transport", 120, hr=118, sbp=100, dbp=64, spo2=94, rr=24)],
        "entries": [
            E("scene", 50, W, "Zapis, pešec, povožen, pri zavesti, boli medenica in leva noga.", "assessment", {"mechanism": "pedestrian vs car", "pain_site": "pelvis, left leg"}, 0.92, "alert:Major trauma, pedestrian"),
            E("scene", 120, W, "Zapis, vratna opornica in zajemalna nosila.", "procedure", {"name": "cervical collar and scoop stretcher"}, 0.94),
            E("scene", 210, W, "Zapis, žilni pristop, fiziološka raztopina petsto mililitrov.", "procedure", {"name": "IV access", "fluid": "saline 500 ml"}, 0.93),
            E("transport", 60, P, "Medenica stabilizirana s pasom, krvni tlak sto na šestdeset štiri.", "vitals", {"sbp": 100, "dbp": 64}, 0.9),
        ]},
    "allergic": {
        "category": "Allergic reaction", "age": (18, 55), "sex": None,
        "vitals0": {"hr": 118, "sbp": 105, "dbp": 66, "spo2": 93, "rr": 24, "gcs": 15},
        "monitor": [M("scene", 40, hr=118, sbp=105, dbp=66, spo2=93, rr=24), M("transport", 240, hr=96, sbp=118, dbp=72, spo2=97, rr=18)],
        "entries": [
            E("scene", 50, W, "Zapis, alergijska reakcija po piku, otekle ustnice, koprivnica po telesu.", "assessment", {"finding": "swollen lips, hives after a sting"}, 0.92),
            E("scene", 120, W, "Zapis, adrenalin nič celih pet miligrama intramuskularno.", "drug_administered", {"drug": "adrenaline", "dose": "0.5 mg", "route": "IM"}, 0.93),
            E("transport", 120, P, "Dihanje se je izboljšalo, saturacija devetinsedemdeset.", "vitals", {"spo2": 79}, 0.58, "check"),
            E("transport", 140, P, "Popravek, saturacija sedemindevetdeset.", "vitals", {"spo2": 97}, 0.92, "corrects:2"),
        ]},
    "diabetic": {
        "category": "Low blood sugar, confusion", "age": (35, 75), "sex": None,
        "vitals0": {"hr": 104, "sbp": 128, "dbp": 78, "spo2": 97, "rr": 18, "gcs": 13},
        "monitor": [M("scene", 40, hr=104, sbp=128, dbp=78, spo2=97, rr=18), M("transport", 240, hr=88, sbp=126, dbp=78, spo2=98, rr=16)],
        "entries": [
            E("scene", 50, W, "Zapis, krvni sladkor dve cele ena.", "vitals", {"glucose_mmol_l": 2.1}, 0.94),
            E("scene", 120, W, "Zapis, glukoza štirideset odstotna petdeset mililitrov intravenozno.", "drug_administered", {"drug": "glucose 40%", "dose": "50 ml", "route": "IV"}, 0.92),
            E("transport", 90, P, "Pacient je bolj bister, sladkor pet cele osem.", "vitals", {"glucose_mmol_l": 5.8, "gcs": 15}, 0.9),
        ]},
    "head_injury": {
        "category": "Head injury, drowsy", "age": (30, 70), "sex": "M",
        "vitals0": {"hr": 78, "sbp": 150, "dbp": 88, "spo2": 96, "rr": 16, "gcs": 12},
        "monitor": [M("scene", 40, hr=78, sbp=150, dbp=88, spo2=96, rr=16), M("transport", 200, hr=70, sbp=160, dbp=92, spo2=96, rr=14)],
        "entries": [
            E("scene", 50, W, "Zapis, padec z lestve, udarec v glavo, GCS dvanajst.", "assessment", {"mechanism": "fall from a ladder", "gcs": 12}, 0.93, "alert:Head injury, GCS 12"),
            E("scene", 150, W, "Zapis, vratna opornica, kisik deset litrov na minuto.", "procedure", {"name": "cervical collar", "oxygen": "10 L/min"}, 0.93),
            E("transport", 150, P, "Zenice neenake, GCS deset.", "assessment", {"pupils": "unequal", "gcs": 10}, 0.88, "alert:GCS dropped to 10, pupils unequal"),
        ]},
    "breathing": {
        "category": "Breathing difficulty", "age": (6, 80), "sex": None,
        "vitals0": {"hr": 116, "sbp": 138, "dbp": 84, "spo2": 86, "rr": 30, "gcs": 15},
        "monitor": [M("scene", 40, hr=116, sbp=138, dbp=84, spo2=86, rr=30), M("transport", 240, hr=100, sbp=134, dbp=82, spo2=94, rr=22)],
        "entries": [
            E("scene", 45, W, "Zapis, hudo težko dihanje, saturacija šestinosemdeset.", "vitals", {"spo2": 86, "rr": 30}, 0.93, "alert:SpO2 86, severe breathing difficulty"),
            E("scene", 110, W, "Zapis, kisik petnajst litrov in salbutamol inhalacija.", "drug_administered", {"drug": "oxygen 15 L/min and salbutamol", "route": "inhalation"}, 0.9),
            E("transport", 120, P, "Saturacija štiriindevetdeset, dihanje lažje.", "vitals", {"spo2": 94}, 0.9),
        ]},
    "bleeding": {
        "category": "Severe bleeding", "age": (20, 60), "sex": "M",
        "vitals0": {"hr": 124, "sbp": 88, "dbp": 52, "spo2": 94, "rr": 26, "gcs": 14},
        "monitor": [M("scene", 40, hr=124, sbp=88, dbp=52, spo2=94, rr=26), M("transport", 160, hr=118, sbp=94, dbp=56, spo2=95, rr=24)],
        "entries": [
            E("scene", 40, W, "Zapis, vbodna rana na trebuhu, močna krvavitev.", "assessment", {"finding": "stab wound, heavy bleeding"}, 0.92, "alert:Heavy bleeding, hypotension"),
            E("scene", 100, W, "Zapis, kompresijski povoj in dva žilna pristopa.", "procedure", {"name": "compression dressing, two IV lines"}, 0.92),
            E("transport", 80, P, "Tlak devetdeset na petdeset šest, nadaljujem z infuzijo.", "vitals", {"sbp": 90, "dbp": 56}, 0.88),
        ]},
    "crash": {
        "category": "Road crash injury", "age": (20, 65), "sex": None,
        "vitals0": {"hr": 108, "sbp": 118, "dbp": 74, "spo2": 96, "rr": 22, "gcs": 14},
        "monitor": [M("scene", 40, hr=108, sbp=118, dbp=74, spo2=96, rr=22), M("transport", 200, hr=102, sbp=122, dbp=76, spo2=97, rr=20)],
        "entries": [
            E("scene", 50, W, "Zapis, voznik je bil ukleščen, bolečina v prsnem košu in desni nogi.", "assessment", {"mechanism": "trapped driver", "pain_site": "chest, right leg"}, 0.91),
            E("scene", 140, W, "Zapis, vratna opornica, žilni pristop, fiziološka raztopina.", "procedure", {"name": "cervical collar, IV access, saline"}, 0.92),
            E("transport", 80, P, "Zapis, analgezija, fentanil petdeset mikrogramov.", "drug_administered", {"drug": "fentanyl", "dose": "50 mcg", "route": "IV"}, 0.9),
        ]},
    "generic_yellow": {
        "category": "Injury or illness, stable", "age": (20, 80), "sex": None,
        "vitals0": {"hr": 88, "sbp": 136, "dbp": 82, "spo2": 97, "rr": 17, "gcs": 15},
        "monitor": [M("scene", 40, hr=88, sbp=136, dbp=82, spo2=97, rr=17), M("transport", 240, hr=84, sbp=132, dbp=80, spo2=98, rr=16)],
        "entries": [
            E("scene", 60, W, "Zapis, pacient pri zavesti, bolečina pet od deset.", "assessment", {"pain_nrs": 5, "conscious": True}, 0.94),
            E("transport", 90, P, "Stanje stabilno, brez poslabšanja.", "assessment", {"condition": "stable"}, 0.9),
        ]},
    "mci_red": {
        "category": "Mass casualty, red (immediate)", "age": (20, 70), "sex": None,
        "vitals0": {"hr": 126, "sbp": 92, "dbp": 56, "spo2": 90, "rr": 28, "gcs": 11},
        "monitor": [M("scene", 40, hr=126, sbp=92, dbp=56, spo2=90, rr=28), M("transport", 200, hr=118, sbp=100, dbp=62, spo2=94, rr=24)],
        "entries": [
            E("scene", 40, W, "Zapis, primarna triaža rdeča, hudo poškodovan.", "triage", {"start_category": "red"}, 0.94, "alert:Red patient from the mass-casualty site"),
            E("scene", 120, W, "Zapis, žilni pristop in kisik petnajst litrov.", "procedure", {"name": "IV access, oxygen 15 L/min"}, 0.92),
            E("transport", 90, P, "Tlak sto na dvainšestdeset, saturacija štiriindevetdeset.", "vitals", {"sbp": 100, "dbp": 62, "spo2": 94}, 0.88),
        ]},
    "mci_yellow": {
        "category": "Mass casualty, yellow (delayed)", "age": (18, 80), "sex": None,
        "vitals0": {"hr": 98, "sbp": 130, "dbp": 80, "spo2": 96, "rr": 20, "gcs": 15},
        "monitor": [M("scene", 40, hr=98, sbp=130, dbp=80, spo2=96, rr=20), M("transport", 300, hr=92, sbp=128, dbp=78, spo2=97, rr=18)],
        "entries": [
            E("scene", 40, W, "Zapis, primarna triaža rumena, zlom podlaket.", "triage", {"start_category": "yellow", "finding": "forearm fracture"}, 0.93),
            E("transport", 120, P, "Imobilizacija opravljena, stanje stabilno.", "procedure", {"name": "immobilisation", "condition": "stable"}, 0.9),
        ]},
    "mci_green": {
        "category": "Mass casualty, green (minor)", "age": (18, 80), "sex": None,
        "vitals0": {"hr": 84, "sbp": 128, "dbp": 78, "spo2": 98, "rr": 16, "gcs": 15},
        "monitor": [],
        "entries": [E("scene", 30, P, "Primarna triaža zelena, hodeči ranjenec, lažje poškodbe.", "triage", {"start_category": "green"}, 0.92)]},
}

KEYWORDS = [
    ("cardiac arrest", "cardiac_arrest"), ("not breathing", "cardiac_arrest"), ("collapse", "cardiac_arrest"),
    ("stroke", "stroke"), ("chest pain", "chest_pain"), ("chest tightness", "chest_pain"),
    ("pedestrian", "pedestrian_trauma"), ("allergic", "allergic"), ("diabetic", "diabetic"),
    ("head injury", "head_injury"), ("ladder", "head_injury"), ("roof tile", "head_injury"),
    ("breathing", "breathing"), ("asthma", "breathing"), ("copd", "breathing"),
    ("stab", "bleeding"), ("bleeding", "bleeding"), ("trapped", "crash"), ("crash", "crash"), ("collided", "crash"), ("car off", "crash"),
    ("hip", "fall_hip"),
]


def pick_template(problem, sev, mci=False):
    if mci:
        return {"red": "mci_red", "yellow": "mci_yellow", "green": "mci_green"}[sev]
    low = problem.lower()
    for kw, name in KEYWORDS:
        if kw in low:
            return name
    return "generic_yellow"
