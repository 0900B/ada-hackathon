"""Live-calls mode: a stream of synthetic calls, each dispatched by the engine the moment it comes in.

The mix is close to a city EMS evening: emergencies at addresses around Ljubljana (to UKC), now and
then a remote one where the helicopter is clearly faster, urgent field calls, urgent patient
transports (health centre -> UKC, GP referrals, urgent discharges, inter-hospital transfers) and
urgent equipment runs (blood products, lab samples, a ventilator). Every call is emergency or urgent.

Calls go through the normal event path (apply_event): emergencies and field calls are dispatched to
the nearest suitable free unit (dispatch_call); transports and equipment are booked onto a van (an
ambulance only if no van can take it), and when nothing fits on time they go to the vehicle that can
collect them soonest. A generated call never starts an AI analysis by itself: step() only reports
"problems" (a call no unit can take, or one that will be late) and the caller decides.

Each world has its own generator with its own seeded RNG (the trips and the scenarios stay
reproducible); arrivals are exponential with CALLS_PER_HOUR in world time.
"""
from __future__ import annotations

import random
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable

from .. import config

if TYPE_CHECKING:
    from ..models import EventRecord
    from ..state import WorldState

MIN_GAP_MIN, MAX_GAP_MIN = 2.0, 25.0  # clamp the random gaps between calls (world minutes)
MAX_CALLS_PER_STEP = 3  # catch up after a long pause, but never flood
PROBLEM_RUN_GAP_MIN = 15.0  # at most one automatic analysis for call problems per this many minutes
SCENARIO_QUIET_MIN = 30.0  # after a demo scenario starts, no new calls for this long (world time)

# Where calls come from. City areas get most calls; the suburbs some.
CITY = ["home_siska", "home_vic", "home_moste", "home_bezigrad", "home_rudnik", "home_crnuce", "home_polje"]
SUBURBS = ["home_domzale", "home_medvode", "home_grosuplje", "home_skofljica", "home_vrhnika"]
HEALTH_CENTRES = ["zd_center", "zd_siska", "zd_vic"]
# Remote spots where the helicopter is clearly faster than any ambulance by road (approximate).
REMOTE = [
    ("Kamniška Bistrica (hiking trail)", 46.3085, 14.5910, "hiker fell, suspected spinal injury"),
    ("Krvavec (ski area)", 46.2960, 14.5330, "skier collision, head injury"),
    ("Sava valley near Litija", 46.0560, 14.8300, "farm accident, crushed leg"),
]
# Emergencies: about 10% critical (life-threatening now), the rest serious (docs/DISPATCH_PRIORITIES.md).
CRITICAL_SHARE = 0.10
CRITICAL_CONDITIONS = [("cardiac_arrest", 4), ("choking", 2), ("catastrophic_bleeding", 2), ("anaphylaxis", 2)]
# Serious calls: most do not need a doctor on scene, so that about 25 % of all red calls get a doctor
# car (critical ones always do), in line with Slovenian dispatch, where a doctor is really needed in
# 10 to 30 % of top-priority interventions (engine.severity.DOCTOR_CONDITIONS).
SERIOUS_CONDITIONS = [("stroke", 4), ("seizure", 3), ("sepsis", 3), ("stemi", 0.75), ("breathing_difficulty", 0.25), ("major_trauma", 0.25)]
EMERGENCY_NOTES = {
    "cardiac_arrest": "unconscious, not breathing; caller instructed in CPR",
    "choking": "choking, cannot speak",
    "catastrophic_bleeding": "heavy bleeding from a leg wound",
    "anaphylaxis": "bee sting, swelling of the throat",
    "stroke": "face drooping, slurred speech",
    "stemi": "crushing chest pain, sweating",
    "breathing_difficulty": "severe breathing difficulty",
    "major_trauma": "traffic accident, injured driver",
    "seizure": "seizure still going on",
    "sepsis": "high fever, confused, low blood pressure",
}
FIELD_NOTES = ["fall at home, cannot get up", "suspected wrist fracture", "fall on the stairs, hip pain"]
FIELD_NOTE_FOR = {"fall": "fall, cannot get up", "fracture": "suspected fracture"}  # the note matching the caller's words

# --- What the callers say (Slovenian, with English) ------------------------------------------------
# Every text grades to its condition with the keyword rules (agent/messages.grade_text), and names a
# child only in CHILD_WORDS: tests/test_calls.py checks each one, with every modifier sentence added.
CALLER_WORDS: dict[str, list[tuple[str, str]]] = {
    "cardiac_arrest": [
        ("Moj mož se je zgrudil v kuhinji, ne diha in se ne odziva!", "My husband collapsed in the kitchen, he is not breathing and not responding!"),
        ("Soseda leži na stopnišču, ne diha, ustnice ima modre.", "My neighbour is lying on the stairs, not breathing, her lips are blue."),
        ("Oče je med večerjo izgubil zavest in ne diha več.", "My father lost consciousness at dinner and is no longer breathing."),
    ],
    "choking": [
        ("Mama se je zadušila s hrano, ne more govoriti in se drži za vrat.", "My mother is choking on food, she can't speak and is holding her throat."),
        ("Gost v restavraciji se duši, obraz mu postaja moder.", "A guest in the restaurant is choking, his face is turning blue."),
    ],
    "catastrophic_bleeding": [
        ("Sodelavec si je z motorno žago prerezal nogo, močno krvavi.", "A co-worker cut his leg with a chainsaw, he is bleeding heavily."),
        ("Sosed je padel skozi steklena vrata in močno krvavi iz roke, kri brizga.",
         "My neighbour fell through a glass door and is bleeding heavily from his arm, blood is spurting."),
    ],
    "anaphylaxis": [
        ("Po piku čebele ji je otekel jezik, mislim, da je alergijski šok, komaj diha.",
         "After a bee sting her tongue swelled up, I think it's anaphylactic shock, she can barely breathe."),
        ("Partner je alergičen na oreščke, pojedel je piškot in ima anafilaktično reakcijo, ves je otekel.",
         "My partner is allergic to nuts, he ate a biscuit and is having an anaphylactic reaction, he is all swollen."),
    ],
    "stroke": [
        ("Babica ima povešen ustni kot in govori nerazločno, sum na kap.", "Grandma's mouth droops on one side and her speech is slurred, suspected stroke."),
        ("Mož nenadoma ne more govoriti, desna roka mu ne deluje, mislim, da ima možgansko kap.",
         "My husband suddenly can't speak and his right arm doesn't work, I think he's having a stroke."),
        ("Mama ima povešen kot ust, je zmedena in šibka na desni strani.", "My mother's mouth droops at the corner, she is confused and weak on the right side."),
    ],
    "stemi": [
        ("Sosed ima hudo bolečino v prsih, ki se širi v levo roko, ves je poten.",
         "My neighbour has severe chest pain spreading to his left arm, he is sweating heavily."),
        ("Mož ima tiščanje v prsih in slabost, pred leti je že imel infarkt.", "My husband has chest pressure and nausea, he had a heart attack years ago."),
    ],
    "breathing_difficulty": [
        ("Dedek s KOPB zelo težko diha in ne more izgovoriti cele povedi.", "Grandpa with COPD is struggling to breathe and can't finish a sentence."),
        ("Partnerica ima napad astme, pršilo ne pomaga, težko diha in je bleda.",
         "My partner is having an asthma attack, the inhaler doesn't help, she is struggling to breathe and pale."),
    ],
    "major_trauma": [
        ("Prometna nesreča na križišču, voznik je ukleščen v avtu in krvavi iz glave.",
         "Traffic accident at the junction, the driver is trapped in the car and bleeding from the head."),
        ("Delavec je padel z gradbenega odra, z višine kakih šest metrov, ne more premikati nog.",
         "A worker fell from scaffolding, about six metres, he can't move his legs."),
        ("Kolesarja je zbil avto, leži na cesti in je zmeden.", "A car hit a cyclist, he is lying on the road and confused."),
    ],
    "seizure": [
        ("Sin ima epileptični napad že več kot pet minut in ne preneha.", "My son has been having an epileptic seizure for over five minutes and it won't stop."),
        ("Sodelavka je padla na tla in ima krče po celem telesu.", "A colleague fell to the floor and is convulsing all over."),
    ],
    "sepsis": [
        ("Mama ima visoko vročino, je zmedena in zelo slabotna, zdravnik sumi na sepso.",
         "My mother has a high fever, is confused and very weak, the doctor suspects sepsis."),
        ("Oče ima po operaciji mrzlico, 40 stopinj vročine in nizek pritisk, sum na sepso.",
         "My father has chills after his operation, a 40-degree fever and low blood pressure, suspected sepsis."),
    ],
    "fracture": [
        ("Gospa je padla na poledenelem pločniku in si verjetno zlomila zapestje.", "A lady fell on the icy pavement and has probably broken her wrist."),
        ("Starejši gospod ima po padcu na stopnicah sum na zlom kolka.", "An elderly man has a suspected hip fracture after a fall on the stairs."),
    ],
    "fall": [
        ("Babica je padla doma in ne more vstati, boli jo kolk.", "Grandma fell at home and can't get up, her hip hurts."),
        ("Sosed je padel na stopnicah, ima udarnino na glavi, a je pri zavesti.", "My neighbour fell on the stairs, he has a bump on the head but is conscious."),
        ("Mama je zjutraj padla v kopalnici in ne more vstati, a je pri zavesti.", "My mother fell in the bathroom this morning and can't get up, but she is conscious."),
    ],
}
CHILD_WORDS: dict[str, list[tuple[str, str]]] = {  # the "child" modifier comes from the words themselves
    "cardiac_arrest": [("Dojenček v posteljici ne diha!", "The baby in the cot is not breathing!")],
    "choking": [("Otrok je pogoltnil kocko in se duši!", "A child swallowed a toy block and is choking!")],
    "catastrophic_bleeding": [("Deček si je z nožem prerezal roko in močno krvavi.", "A boy cut his arm with a knife and is bleeding heavily.")],
    "anaphylaxis": [("Deklica ima anafilaktični šok po arašidih, ves obraz ji je otekel.", "A girl is in anaphylactic shock after peanuts, her whole face is swollen.")],
    "stroke": [("Deklica ima nenadoma povešen ustni kot in ne more govoriti.", "A girl suddenly has a drooping mouth and can't speak.")],
    "stemi": [("Deček ima nenadno hudo bolečino v prsih in je bled.", "A boy has sudden severe chest pain and is pale.")],
    "breathing_difficulty": [("Deček ima hud napad astme in težko diha.", "A boy is having a severe asthma attack and is struggling to breathe.")],
    "major_trauma": [("Otroka je zbil avto na prehodu za pešce.", "A car hit a child on the zebra crossing.")],
    "seizure": [("Deklica ima vročinske krče in se ne odziva.", "A girl is having febrile convulsions and is not responding.")],
    "sepsis": [("Otrok ima visoko vročino, je zaspan in zmeden, zdravnica sumi na sepso.",
                "A child has a high fever, is drowsy and confused, the doctor suspects sepsis.")],
    "fracture": [("Deček je padel s trampolina, sum na zlom roke.", "A boy fell off a trampoline, suspected broken arm.")],
    "fall": [("Otrok je padel s stola in se udaril v glavo, joka.", "A child fell off a chair and hit his head, he is crying.")],
}
# Sentences that carry a case modifier (added when the generator picks it).
MODIFIER_WORDS: dict[str, tuple[str, str]] = {
    "no_bystander_cpr": ("Nihče ne oživlja.", "Nobody is doing CPR."),
    "deteriorating": ("Stanje se slabša.", "It's getting worse."),
    "multiple_patients": ("Poškodovanih je več oseb.", "Several people are injured."),
    "late_stroke_window": ("Simptomi so se začeli pred več kot tremi urami.", "The symptoms started more than three hours ago."),
}
CPR_GIVEN = ("Oživljamo.", "We are doing CPR.")  # a cardiac arrest with bystander CPR
REMOTE_WORDS: dict[str, tuple[str, str]] = {  # by REMOTE name (the generator's remote calls)
    "Kamniška Bistrica (hiking trail)": ("Planinec je na poti v Kamniški Bistrici padel z višine kakih deset metrov, ne čuti nog.",
                                         "A hiker on the Kamniška Bistrica trail fell about ten metres and can't feel his legs."),
    "Krvavec (ski area)": ("Na Krvavcu sta trčila smučarja, eden ima hudo poškodbo glave in je zmeden.",
                           "Two skiers collided on Krvavec, one has a serious head injury and is confused."),
    "Sava valley near Litija": ("Kmeta pri Litiji je stisnil traktor, huda poškodba noge, zelo krvavi.",
                                "A farmer near Litija was crushed by a tractor, serious leg injury, bleeding a lot."),
}
# More remote spots for the demo's random calls only (the generator keeps REMOTE, so its stream is unchanged).
REMOTE_EXTRA = [
    ("Velika planina (mountain pasture)", 46.2930, 14.6420,
     "Na Veliki planini je pastir padel z višine s skale in ima hudo poškodbo hrbta.",
     "A herdsman on Velika planina fell from a rock and has a serious back injury."),
    ("Kum (hiking trail)", 46.0890, 15.0750,
     "Planinka je na Kumu padla z višine in ne more vstati, huda poškodba hrbta.",
     "A hiker on Mount Kum fell from a height and can't get up, serious back injury."),
]
# Streets per area (real street names; the coordinates are the area's, see _address).
STREETS: dict[str, list[str]] = {
    "Šiška": ["Celovška cesta", "Derčeva ulica", "Vodnikova cesta", "Drenikova ulica"],
    "Vič": ["Tržaška cesta", "Jamova cesta", "Viška cesta", "Cesta v Mestni log"],
    "Moste": ["Zaloška cesta", "Pokopališka ulica", "Proletarska cesta", "Kavčičeva ulica"],
    "Bežigrad": ["Dunajska cesta", "Linhartova cesta", "Vojkova cesta", "Topniška ulica"],
    "Rudnik": ["Ižanska cesta", "Peruzzijeva ulica", "Jurčkova cesta"],
    "Črnuče": ["Primožičeva ulica", "Cesta 24. junija", "Pot k sejmišču"],
    "Polje": ["Zadobrovška cesta", "Chengdujska cesta", "Cesta v Zgornji Kašelj"],
    "Domžale": ["Ljubljanska cesta", "Kolodvorska cesta", "Savska cesta"],
    "Medvode": ["Cesta komandanta Staneta", "Ostrovrharjeva ulica", "Zbiljska cesta"],
    "Grosuplje": ["Adamičeva cesta", "Taborska cesta", "Cesta na Krko"],
    "Škofljica": ["Šmarska cesta", "Klanec", "Pot na Drenik"],
    "Vrhnika": ["Stara cesta", "Cankarjev trg", "Robova cesta"],
}
FIRST_NAMES = ["Ana", "Marko", "Petra", "Luka", "Nina", "Jure", "Maja", "Tine", "Katja", "Miha", "Barbara", "Andrej",
               "Mojca", "Tomaž", "Špela", "Gregor", "Irena", "Boštjan", "Alenka", "Primož"]
LAST_NAMES = ["Novak", "Kovač", "Horvat", "Zupan", "Krajnc", "Potočnik", "Kos", "Vidmar", "Mlakar", "Kovačič", "Bizjak",
              "Hribar", "Kastelic", "Oblak", "Žagar", "Rozman"]
NEEDS_WORDS = {
    "seated": ("pacient sedi", "the patient can sit"),
    "wheelchair": ("pacient je na invalidskem vozičku", "the patient uses a wheelchair"),
    "stretcher": ("pacient leži, potrebna so nosila", "the patient is lying down, a stretcher is needed"),
    "equipment": ("", ""),
}


def _modifiers(rng: random.Random, condition: str) -> list[str]:
    """Occasional case modifiers that raise a call's weight within its level."""
    mods = []
    if condition == "cardiac_arrest" and rng.random() < 0.5:
        mods.append("no_bystander_cpr")
    if condition == "stroke" and rng.random() < 0.2:
        mods.append("late_stroke_window")
    if condition == "major_trauma" and rng.random() < 0.1:
        mods.append("multiple_patients")
    if rng.random() < 0.05:
        mods.append("child")
    if rng.random() < 0.05:
        mods.append("deteriorating")
    return mods

# (kind, weight). Tuned so that ambulances and vans are typically 50-70 % busy at 8 calls/hour.
MIX = [
    ("emergency", 0.38),
    ("field_urgent", 0.08),
    ("remote", 0.03),
    ("hc_to_ukc", 0.14),
    ("gp_referral", 0.08),
    ("discharge", 0.07),
    ("transfer", 0.02),  # long runs (Trbovlje, Novo mesto): rare, they tie a van up for 2 to 3 hours
    ("blood", 0.09),
    ("lab", 0.08),
    ("ventilator", 0.01),
]


@dataclass
class CallGenerator:
    """Per-world call stream state (no engine imports here: state.py holds one of these)."""

    enabled: bool = field(default_factory=lambda: config.CALLS_ENABLED)
    per_hour: float = field(default_factory=lambda: config.CALLS_PER_HOUR)
    rng: random.Random = field(default_factory=random.Random)
    # Caller names, addresses and words: a separate stream, so the calls themselves (and the dispatch
    # benchmark, tools/benchmark.py) are exactly what they were before the calls had words.
    text_rng: random.Random = field(default_factory=random.Random)
    next_at: datetime | None = None
    paused_until: datetime | None = None
    last_problem_run_at: datetime | None = None
    generated: int = 0

    def reset(self, seed: int, world: str, now: datetime) -> None:
        self.rng = random.Random(seed * 7919 + zlib.crc32(world.encode()))
        self.text_rng = random.Random(seed * 104729 + zlib.crc32(world.encode()) + 1)
        self.paused_until = self.last_problem_run_at = None
        self.generated = 0
        self.next_at = now + self._gap()

    def _gap(self) -> timedelta:
        mean = 60.0 / max(self.per_hour, 0.1)
        return timedelta(minutes=min(MAX_GAP_MIN, max(MIN_GAP_MIN, self.rng.expovariate(1 / mean))))

    def pause(self, until: datetime) -> None:
        self.paused_until = until
        if self.next_at is None or self.next_at < until:
            self.next_at = until + self._gap()

    def status(self, state: WorldState) -> dict[str, Any]:
        active = self.enabled and not state.scheduled_day
        return {
            "enabled": self.enabled,
            "active": active,  # calls are generated now (live-calls mode, switched on)
            "per_hour": self.per_hour,
            "next_at": self.next_at.isoformat() if active and self.next_at else None,
            "paused_until": self.paused_until.isoformat() if self.paused_until and self.paused_until > state.sim_time else None,
            "generated": self.generated,
        }


def _address(state: WorldState, rng: random.Random, suburbs_share: float = 0.25) -> tuple[str, float, float]:
    """A random street address: near a city area (or a suburb), up to ~600 m away from its centre."""
    pid = rng.choice(SUBURBS if rng.random() < suburbs_share else CITY)
    p = state.places[pid]
    lat = p.lat + rng.uniform(-0.0054, 0.0054)
    lon = p.lon + rng.uniform(-0.0078, 0.0078)
    return p.name, round(lat, 5), round(lon, 5)


def new_call_id(state: WorldState, kind: str = "112") -> str:
    """'112-0042' for a 112 call, 'REQ-0007' for a hospital's request (per-world counters)."""
    prefix = "112" if kind == "112" else "REQ"
    state.call_seq[prefix] = n = state.call_seq.get(prefix, 0) + 1
    return f"{prefix}-{n:04d}"


def caller_name(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def street_address(rng: random.Random, area: str) -> str:
    """A plausible street address in an area, e.g. 'Zaloška cesta 45, Moste'."""
    streets = STREETS.get(area)
    if not streets:
        return area
    return f"{rng.choice(streets)} {rng.randint(1, 160)}, {area}"


def caller_words(rng: random.Random, condition: str, modifiers: list[str]) -> tuple[str, str]:
    """What the caller says for this condition and these case modifiers (Slovenian, English)."""
    pool = CHILD_WORDS.get(condition) if "child" in modifiers else None
    sl, en = rng.choice(pool or CALLER_WORDS.get(condition) or [("Potrebujemo reševalce.", "We need an ambulance.")])
    for m in modifiers:
        if m in MODIFIER_WORDS:
            sl, en = f"{sl} {MODIFIER_WORDS[m][0]}", f"{en} {MODIFIER_WORDS[m][1]}"
    if condition == "cardiac_arrest" and "no_bystander_cpr" not in modifiers:
        sl, en = f"{sl} {CPR_GIVEN[0]}", f"{en} {CPR_GIVEN[1]}"
    return sl, en


def call_record_112(state: WorldState, rng: random.Random, address: str, sl: str, en: str, triage: bool = True):
    """A 112 call record (triaged by the keyword rules unless triage=False: the caller triages later)."""
    from ..agent.triage import triage_rules
    from ..models import CallRecord

    return CallRecord(
        call_id=new_call_id(state, "112"), kind="112", received_at=state.sim_time, caller_name=caller_name(rng),
        address=address, text_sl=sl, text_en=en, triage=triage_rules(sl, state.sim_time) if triage else None,
    )


def _hospital_request(state: WorldState, rng: random.Random, kind: str, ev):
    """The record behind a generated booking: who asks for it and in what words."""
    from ..agent.triage import reasons
    from ..models import CallRecord, CallTriage

    a, b = state.places[ev.pickup_id], state.places[ev.dropoff_id]
    need_sl, need_en = NEEDS_WORDS.get(ev.needs, ("", ""))
    name = caller_name(rng)
    address = street_address(rng, a.name) if a.kind == "residential" else a.name
    if kind == "hc_to_ukc":
        who = f"{name}, nurse ({a.name})"
        sl, en = f"Prosimo za nujen prevoz pacienta na urgenco UKC; {need_sl}.", f"Please send an urgent transport to the UKC emergency department; {need_en}."
    elif kind == "gp_referral":
        who = f"Dr. {name}, GP"
        sl = f"Napotujem pacienta na pregled v UKC še danes, prosim za prevoz z doma; {need_sl}."
        en = f"I'm referring a patient to UKC for assessment today, please collect them at home; {need_en}."
    elif kind == "discharge":
        who = f"{name}, ward nurse ({a.name})"
        sl = f"Nujen odpust: potrebujemo posteljo, prosimo za prevoz pacienta domov ({b.name}); {need_sl}."
        en = f"Urgent discharge: we need the bed, please take the patient home ({b.name}); {need_en}."
    elif kind == "transfer":
        who = f"Dr. {name} ({a.name})"
        sl, en = f"Premestitev pacienta v {b.name}; {need_sl}.", f"Inter-hospital transfer to {b.name}; {need_en}."
    elif kind == "blood":
        who = f"{name}, transfusion service ({a.name})"
        sl, en = f"Nujno pošljite krvne pripravke za transfuzijo v {b.name}.", f"Please rush blood products for a transfusion to {b.name}."
    elif kind == "lab":
        who = f"{name}, laboratory ({a.name})"
        sl, en = "Prosimo za nujen odvoz vzorcev v centralni laboratorij UKC.", "Please collect samples urgently for the UKC central lab."
    else:
        who = f"{name}, intensive care ({a.name})"
        sl, en = f"Posojamo ventilator intenzivni enoti v {b.name}, prosimo za prevoz.", f"We are lending a ventilator to the ICU in {b.name}, please transport it."
    condition = "equipment" if ev.needs == "equipment" else "transfer"
    reason_en, reason_sl = reasons("urgent", condition, [])
    triage = CallTriage(by="rules", at=state.sim_time, severity="urgent", condition=condition,
                        condition_label=CONDITION_LABELS[condition], reason_en=reason_en, reason_sl=reason_sl)
    return CallRecord(call_id=new_call_id(state, "hospital_request"), kind="hospital_request", received_at=state.sim_time,
                      caller_name=who, address=address, text_sl=sl, text_en=en, triage=triage)


CONDITION_LABELS = {"transfer": "Urgent transfer", "equipment": "Equipment"}


def build_call(state: WorldState, rng: random.Random, kind: str | None = None):
    """One synthetic call as an operator event (UrgentRequestEvent or TaskRequestEvent)."""
    return build_call_with_record(state, rng, random.Random(0), kind)[0]


def build_call_with_record(state: WorldState, rng: random.Random, text_rng: random.Random, kind: str | None = None):
    """One synthetic call: (operator event, call record). rng decides the call exactly as before (the
    stream does not depend on the words); text_rng only picks the caller, the address and the words."""
    from ..models import UrgentRequestEvent

    kind = kind or rng.choices([k for k, _ in MIX], weights=[w for _, w in MIX])[0]
    if kind == "emergency":
        area, lat, lon = _address(state, rng)
        critical = rng.random() < CRITICAL_SHARE
        pool = CRITICAL_CONDITIONS if critical else SERIOUS_CONDITIONS
        condition = rng.choices([c for c, _ in pool], weights=[w for _, w in pool])[0]
        mods = _modifiers(rng, condition)
        address = street_address(text_rng, area)
        sl, en = caller_words(text_rng, condition, mods)
        ev = UrgentRequestEvent(
            type="urgent_request", lat=lat, lon=lon, place_name=address[:80], dropoff_id="ukc", needs="stretcher",
            priority="emergency", severity="critical" if critical else "serious", condition=condition,
            modifiers=mods, note=EMERGENCY_NOTES.get(condition),
        )
        return ev, call_record_112(state, text_rng, address, sl, en)
    if kind == "field_urgent":
        area, lat, lon = _address(state, rng)
        condition = rng.choice(["fall", "fall", "fracture"])
        needs = "stretcher" if rng.random() < 0.6 else "seated"
        mods = ["child"] if rng.random() < 0.05 else []
        rng.choice(FIELD_NOTES)  # drawn as before (keeps the stream); the note now matches the words
        address = street_address(text_rng, area)
        sl, en = caller_words(text_rng, condition, mods)
        ev = UrgentRequestEvent(
            type="urgent_request", lat=lat, lon=lon, place_name=address[:80], dropoff_id="ukc",
            needs=needs, priority="urgent", severity="urgent",  # type: ignore[arg-type]
            condition=condition, modifiers=mods, note=FIELD_NOTE_FOR[condition],
        )
        return ev, call_record_112(state, text_rng, address, sl, en)
    if kind == "remote":
        name, lat, lon, note = rng.choice(REMOTE)
        sl, en = REMOTE_WORDS[name]
        ev = UrgentRequestEvent(
            type="urgent_request", lat=lat, lon=lon, place_name=name, dropoff_id="ukc",
            needs="stretcher", priority="emergency", severity="serious", condition="major_trauma", note=note,
        )
        return ev, call_record_112(state, text_rng, name, sl, en)
    ev = _booking(state, rng, kind)
    return ev, _hospital_request(state, text_rng, kind, ev)


def _booking(state: WorldState, rng: random.Random, kind: str):
    """A generated urgent transport or equipment run (a hospital's request)."""
    from ..models import TaskRequestEvent

    def booking(pickup: str, dropoff: str, needs: str, note: str, label: str | None = None, ready=(0, 15)):
        return TaskRequestEvent(
            type="task_request", kind="equipment" if needs == "equipment" else "patient",
            pickup_id=pickup, dropoff_id=dropoff, needs=needs, priority="urgent",  # type: ignore[arg-type]
            ready_in_min=rng.randint(*ready), label=label, note=note, if_late="soonest",
            severity="urgent", condition="equipment" if needs == "equipment" else "transfer",
        )

    needs = rng.choices(["seated", "wheelchair", "stretcher"], weights=[4, 3, 3])[0]
    if kind == "hc_to_ukc":
        return booking(rng.choice(HEALTH_CENTRES), "ukc", needs, "referred to the UKC emergency department")
    if kind == "gp_referral":
        return booking(rng.choice(CITY + SUBURBS), "ukc", needs, "GP referral: needs hospital assessment today")
    if kind == "discharge":
        return booking(rng.choice(["ukc", "ukc", "onko"]), rng.choice(CITY + SUBURBS), needs, "urgent discharge: bed needed", ready=(5, 20))
    if kind == "transfer":
        far = rng.choice(["sb_trbovlje", "sb_novo_mesto"])
        a, b = ("ukc", far) if rng.random() < 0.5 else (far, "ukc")
        return booking(a, b, "stretcher", "inter-hospital transfer", ready=(10, 30))
    if kind == "blood":
        return booking("ukc", rng.choice(["onko", "zd_center", "zd_vic"]), "equipment", "for a transfusion", "blood products", (0, 10))
    if kind == "lab":
        return booking(rng.choice(HEALTH_CENTRES), "ukc", "equipment", "to the central lab", "lab samples", (0, 10))
    return booking("ukc", rng.choice(["sb_trbovlje", "sb_novo_mesto"]), "equipment", "ICU loan to a regional hospital", "ventilator", (10, 30))


def problem_of(state: WorldState, record: EventRecord) -> str | None:
    """Why a dispatched call needs a dispatcher's attention (None = handled)."""
    from ..engine.projection import LATE_ALERT_MIN

    trip = state.trips.get(record.affected_trip_ids[0]) if record.affected_trip_ids else None
    if trip is None:
        return None
    if trip.status == "unassigned":
        return f"no unit can take {trip.id} ({trip.label}, {trip.priority})"
    if (trip.delay_min or 0) >= LATE_ALERT_MIN:
        return f"{trip.id} ({trip.label}, {trip.priority}) will be {trip.delay_min:.0f} min late with {trip.vehicle_id}"
    return None


def step(state: WorldState, intake: Callable[..., bool] | None = None) -> list[tuple[EventRecord, str | None]]:
    """Generate the calls that are due. Returns (event record, problem or None) per call.

    Every call comes with its record (caller, address, words, the rules' triage). intake(state, event,
    call), when given, may take a 112 call over (return True) to triage it with Claude first and apply
    it later (app/intake.py); such a call is not in the result."""
    from ..engine.events import apply_event

    gen: CallGenerator = state.calls
    if not gen.enabled or state.scheduled_day or gen.next_at is None:
        return []
    now = state.sim_time
    if gen.paused_until and now < gen.paused_until:
        return []
    out: list[tuple[EventRecord, str | None]] = []
    taken = 0
    while now >= gen.next_at and len(out) + taken < MAX_CALLS_PER_STEP:
        ev, call = build_call_with_record(state, gen.rng, gen.text_rng)
        gen.generated += 1
        gen.next_at += gen._gap()
        if intake is not None and call.kind == "112" and intake(state, ev, call):
            taken += 1
            continue
        record = apply_event(state, ev, call)
        record.generated = True
        out.append((record, problem_of(state, record)))
    if now >= gen.next_at:  # still behind after a long pause: skip ahead instead of a burst
        gen.next_at = now + gen._gap()
    return out


def may_analyse(state: WorldState) -> bool:
    """A call problem may start an analysis: auto-analyse on, none running, not too often."""
    gen: CallGenerator = state.calls
    if not state.auto_analyze or any(r.status == "running" for r in state.agent_runs):
        return False
    last = gen.last_problem_run_at
    if last is not None and state.sim_time - last < timedelta(minutes=PROBLEM_RUN_GAP_MIN):
        return False
    gen.last_problem_run_at = state.sim_time
    return True
