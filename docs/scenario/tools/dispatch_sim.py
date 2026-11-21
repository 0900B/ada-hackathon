"""Seeded dispatch scenarios for the Ljubljana emergency area: build the fleet, run a procedure-first assignment
model, validate engine payloads and write docs/scenario/dispatch_scenarios.json.

Run: python dispatch_sim.py <out.json>
Procedure first: red -> nearest suitable public unit from ANY area (private only if no public unit reaches in 15 min);
yellow -> Ljubljana-area units; other areas / private only when the demand trigger is on and the wait is long.
All numbers marked [A] in the notes are assumptions; the model is a stand-in for the real dispatcher.
"""
from __future__ import annotations

import copy
import json
import math
import random
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = sys.argv[1] if len(sys.argv) > 1 else None
SEED = 20261123

# ---- travel model: same constants as backend/app/routing.py -----------------------------------------------------
ROAD, SPEED, EMERG = 1.35, 42.0, 1.3


def hav(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(x))


def weather_factor(w):
    """Copy of backend/app/routing.py weather_factor (1.0 = no effect)."""
    if not w:
        return 1.0
    f = 1.0
    if w.get("snow_cm", 0) >= 1.0:
        f = min(f, 0.6)
    elif w.get("snow_cm", 0) > 0:
        f = min(f, 0.75)
    if w.get("precip_mm", 0) > 0 and w.get("temp_c", 10) <= 0.5:
        f = min(f, 0.7)
    elif w.get("precip_mm", 0) >= 2:
        f = min(f, 0.85)
    elif w.get("precip_mm", 0) > 0:
        f = min(f, 0.93)
    if w.get("wind_kmh", 0) >= 60:
        f = min(f, 0.85)
    return f


def traffic_factor(h, weekday):
    """Copy of backend/app/fetchers/traffic.py profile_factor."""
    if weekday and (6.5 <= h < 8.5 or 14.5 <= h < 17.5):
        return 0.65
    if h >= 22 or h < 5.5:
        return 1.1
    return 0.85 if weekday else 0.95


# ---- places ------------------------------------------------------------------------------------------------------
UKC = (46.0563, 14.5232)
HOSP = {"ukc": ("UKC Ljubljana", 46.0563, 14.5232), "jesenice": ("SB Jesenice", 46.443, 14.037),
        "celje": ("SB Celje", 46.234, 15.261), "novomesto": ("SB Novo mesto", 45.804, 15.169)}
BRNIK = (46.2237, 14.4576)

SCENES = {  # synthetic scene locations (town or district level, not real addresses)
    "vic": ("Vič (residential block)", 46.04, 14.482), "bezigrad": ("Bežigrad", 46.072, 14.511),
    "siska": ("Šiška", 46.0735, 14.479), "crnuce": ("Črnuče", 46.102, 14.532), "moste": ("Moste", 46.056, 14.542),
    "polje": ("Polje", 46.062, 14.59), "rudnik": ("Rudnik", 46.027, 14.53), "domzale": ("Domžale (outskirts)", 46.149, 14.612),
    "vrhnika": ("Vrhnika (outskirts)", 45.9735, 14.279), "grosuplje": ("Grosuplje (outskirts)", 45.964, 14.674),
    "medvode": ("Medvode (outskirts)", 46.150, 14.429), "skofljica": ("Škofljica", 45.984, 14.577),
    "kamnisko_bistrica": ("Kamniška Bistrica trailhead", 46.296, 14.602), "kocevje": ("Kočevje (outskirts)", 45.650, 14.875),
    "ring_east": ("East ring road (synthetic crash site)", 46.0545, 14.585),
    "a1_bus": ("A1 motorway near Šentjakob (synthetic crash site)", 46.1225, 14.575),
    "kamnik": ("Kamnik (outskirts)", 46.233, 14.626), "postojna": ("Postojna", 45.774, 14.215),
    "zaloska": ("Zaloška cesta", 46.0585, 14.538), "trzin": ("Trzin", 46.1305, 14.5575),
    "ig": ("Ivančna Gorica", 45.939, 14.804), "notranje_gorice": ("Notranje Gorice", 45.99, 14.4),
}

LJ_BASES = {"ukc": (46.058, 14.5265), "vrhnika": (45.966, 14.301), "ig": (45.939, 14.804), "medvode": (46.142, 14.413),
            "zd_center": (46.0573, 14.5155), "zd_siska": (46.0705, 14.493), "zd_vic": (46.0445, 14.4905),
            "domzale": (46.1377, 14.5937), "kamnik": (46.2259, 14.6121), "grosuplje": (45.9558, 14.6589),
            "kocevje": (45.6432, 14.8604), "ribnica": (45.7386, 14.7275), "logatec": (45.9168, 14.2265),
            "idrija": (46.0029, 14.0279), "postojna": (45.7743, 14.2153), "cerknica": (45.797, 14.3626)}
NG_BASES = {"kranj": (46.2389, 14.3556), "skofja_loka": (46.1655, 14.3063), "trzic": (46.3636, 14.3105),
            "litija": (46.0604, 14.8218), "zagorje": (46.1318, 14.9969), "trbovlje": (46.1541, 15.0518),
            "trebnje": (45.9042, 15.0224), "novomesto": (45.804, 15.1689)}
PRIV_BASES = [(46.076, 14.505), (46.045, 14.53), (46.10, 14.54), (46.06, 14.47), (46.07, 14.55), (46.035, 14.50)]


def roster(shift):
    """Crewed units at one moment. Day = 07:00-19:00. Fractional team counts in the decree (1.5) are 2 by day, 1 by night [A]."""
    day = shift == "day"
    units = []

    def add(kind, area, org, base, bases, n=1):
        for _ in range(n):
            units.append({"kind": kind, "area": area, "org": org, "base": base, "pos": bases[base]})
    # Ljubljana emergency area, ambulances (NRV): 12 at UKC station incl. outposts, 12 more at the other units
    add("NRV", "LJ", "UKC station", "ukc", LJ_BASES, 9)
    add("NRV", "LJ", "UKC outpost Vrhnika", "vrhnika", LJ_BASES)
    add("NRV", "LJ", "UKC outpost Ivančna Gorica", "ig", LJ_BASES)
    add("NRV", "LJ", "UKC outpost Medvode", "medvode", LJ_BASES)
    for base, org, d, n in (("domzale", "ZD Domžale", 2, 1), ("kamnik", "ZD Kamnik", 2, 1), ("logatec", "ZD Logatec", 1, 1),
                            ("ribnica", "ZD Ribnica", 2, 1), ("kocevje", "ZD Kočevje", 2, 2), ("idrija", "ZD Idrija", 2, 1),
                            ("postojna", "ZD Postojna", 2, 2), ("cerknica", "ZD Cerknica", 1, 1)):
        add("NRV", "LJ", org, base, LJ_BASES, d if day else n)
    # doctor vehicles (VUZ)
    for base, org, d, n in (("zd_center", "ZD Ljubljana", 1, 1), ("zd_siska", "ZD Ljubljana", 1, 1), ("zd_vic", "ZD Ljubljana", 1, 0),
                            ("domzale", "ZD Domžale", 1, 1), ("kamnik", "ZD Kamnik", 1, 1), ("grosuplje", "ZD Ivančna Gorica/Grosuplje", 1, 1),
                            ("vrhnika", "ZD Vrhnika", 1, 1), ("kocevje", "ZD Kočevje", 1, 1), ("idrija", "ZD Idrija", 1, 1),
                            ("postojna", "ZD Postojna", 1, 1)):
        add("VUZ", "LJ", org, base, LJ_BASES, d if day else n)
    # neighbouring areas (public)
    for base, org, d, n in (("kranj", "ZD Kranj", 3, 3), ("skofja_loka", "ZD Škofja Loka", 2, 2), ("trzic", "ZD Tržič", 2, 1),
                            ("litija", "ZD Litija", 2, 1), ("zagorje", "ZD Zagorje", 1, 1), ("trbovlje", "SB/ZD Trbovlje", 2, 2),
                            ("trebnje", "ZD Trebnje", 1, 1), ("novomesto", "SB/ZD Novo mesto", 3, 2)):
        add("NRV", "NG", org, base, NG_BASES, d if day else n)
    for base, org in (("kranj", "ZD Kranj"), ("skofja_loka", "ZD Škofja Loka"), ("litija", "ZD Litija"),
                      ("trbovlje", "SB/ZD Trbovlje"), ("novomesto", "SB/ZD Novo mesto")):
        add("VUZ", "NG", org, base, NG_BASES)
    # public sanitary vans at the UKC station (existing scenario has 2)
    add("VAN", "LJ", "UKC station (sanitary)", "ukc", LJ_BASES, 2)
    # private providers: bases are not published [A]
    for i in range(3):
        units.append({"kind": "PAMB", "area": "PRIV", "org": "Private ambulance (qualified crew) [A]", "base": f"priv{i+1}", "pos": PRIV_BASES[i]})
    for i in range(6):
        units.append({"kind": "PVAN", "area": "PRIV", "org": "Private non-urgent transport [A]", "base": f"priv{i+1}", "pos": PRIV_BASES[i]})
    cnt = {}
    for u in units:
        cnt[u["kind"]] = cnt.get(u["kind"], 0) + 1
        u["id"] = {"NRV": "A", "VUZ": "D", "VAN": "T", "PAMB": "PA", "PVAN": "PT"}[u["kind"]] + f"{cnt[u['kind']]:02d}"
        u["free_at"], u["divertable"], u["ok"], u["state"] = 0.0, False, True, "free"
        u["route"] = None
        u["home"] = u["pos"]
    return units


PRIV_LEAD = {"PAMB": 15.0, "PVAN": 30.0}  # mobilisation minutes [A]
EXIT = {"NRV": 1.0, "VAN": 1.0, "VUZ": 5.0}  # exit time: 1 min ambulance, 5 min doctor vehicle (2026 rulebook, reported) [SS]
RED_TARGET = 15.0
SCENE_MIN = {"red": 20.0, "yellow": 15.0, "green": 10.0}
HANDOVER, TURNAROUND = 12.0, 8.0  # [A] handover under the 15 min rule; routine cleaning and restock


def run(spec, idx):
    rnd = random.Random(SEED + sum(ord(ch) * (i + 1) for i, ch in enumerate(spec["id"])))
    h0, m0 = (int(x) for x in spec["start"].split(":"))
    start_h = h0 + m0 / 60
    fleet = roster(spec["shift"])
    lj_nrv = [u for u in fleet if u["kind"] == "NRV" and u["area"] == "LJ"]
    # background: units busy with non-urgent transports at start
    load = spec["background_load"]
    for u in fleet:
        if u["kind"] in ("NRV", "VUZ", "VAN") and u["area"] in ("LJ", "NG"):
            p = load if u["kind"] == "NRV" else load * 0.5
            if u["area"] == "NG":
                p *= spec.get("ng_factor", 0.6)
            if rnd.random() < p:
                u["free_at"] = rnd.uniform(spec.get("busy_min", 5), 45)
                u["divertable"] = rnd.random() < spec.get("divert_p", 0.4)
                u["state"] = "non-urgent"
                near = rnd.uniform(1, 6) / 111.0
                u["pos"] = (u["pos"][0] + rnd.uniform(-near, near), u["pos"][1] + rnd.uniform(-near, near))
            elif u["kind"] == "NRV" and u["area"] == "LJ" and u["base"] == "ukc" and rnd.random() < 0.3:
                u["pos"] = UKC  # just finished a handover
    for uid, mins in spec.get("cleaning", {}).items():
        u = next((x for x in fleet if x["id"] == uid), None)
        if u:
            u["free_at"], u["pos"], u["state"], u["divertable"] = mins, UKC, "cleaning", False
    for uid in spec.get("low_fuel", []):
        u = next((x for x in fleet if x["id"] == uid), None)
        if u:
            u["ok"], u["state"] = False, "low fuel (not eligible)"
    fleet_initial = [{"id": u["id"], "kind": u["kind"], "area": u["area"], "org": u["org"], "base": u["base"], "lat": round(u["pos"][0], 5), "lon": round(u["pos"][1], 5),
                      "home": [round(u["home"][0], 5), round(u["home"][1], 5)], "free_at_min": round(u["free_at"], 1), "divertable": u["divertable"], "state": u["state"], "ok": u["ok"]} for u in fleet]
    wf = weather_factor(spec.get("weather"))
    log, assigned, state = [], {}, {"trigger": None, "peak_busy": 0, "min_free": 99, "displaced": 0,
                                     "nonurgent_private": 0, "nonurgent_public": 0}
    calls = sorted(spec["calls"], key=lambda c: c["t"])
    needs = {}
    displaced_jobs = []
    out_by_call = {}

    def clock(t):
        return start_h + t / 60.0

    def tf(t):
        return traffic_factor(clock(t) % 24, spec["weekday"])

    def position(u, t):
        if u["route"] and t < u["route"][3]:
            (p0, p1, t0, t1) = u["route"]
            f = max(0.0, (t - t0) / max(1e-6, t1 - t0))
            return (p0[0] + (p1[0] - p0[0]) * f, p0[1] + (p1[1] - p0[1]) * f)
        return u["pos"]

    def is_div(u, t, red=True):
        """A unit can be taken off a job if it has not reached the patient. Only red may take a unit off a yellow job."""
        if not u["divertable"]:
            return False
        if u["route"] is not None and t >= u["route"][3]:
            return False
        return red or u.get("job") is None

    def eta(u, t, dest, red, extra=1.0):
        sp = SPEED * tf(t) * wf * extra * (EMERG if red else 1.0)
        if u["area"] == "PRIV":
            wait, pos = PRIV_LEAD[u["kind"]], u["pos"]
            if u["free_at"] > t:
                wait, pos = max(wait, u["free_at"] - t), UKC
        elif u["free_at"] <= t:
            wait, pos = EXIT[u["kind"]], position(u, t)
        elif is_div(u, t, red):
            wait, pos = 0.0, position(u, t)
        else:
            wait, pos = u["free_at"] - t + EXIT[u["kind"]], UKC
        return wait + hav(pos, dest) * ROAD / sp * 60.0

    def advance_background(t):
        """Units that finish a non-urgent transport start another one with the scenario's load probability."""
        for u in fleet:
            if u["state"] == "non-urgent" and u["free_at"] <= t:
                p = load if u["kind"] == "NRV" else load * 0.5
                if u["area"] == "NG":
                    p *= spec.get("ng_factor", 0.6)
                if rnd.random() < p:
                    near = rnd.uniform(1, 6) / 111.0
                    u["free_at"] = t + rnd.uniform(15, 45)
                    u["divertable"] = rnd.random() < spec.get("divert_p", 0.4)
                    u["pos"] = (u["home"][0] + rnd.uniform(-near, near), u["home"][1] + rnd.uniform(-near, near))
                    u["route"] = None
                else:
                    u["state"], u["pos"], u["route"] = "free", u["home"], None

    def free_lj(t):
        return sum(1 for u in lj_nrv if u["ok"] and u["free_at"] <= t)

    def update_trigger(t, why=None):
        crewed = sum(1 for u in lj_nrv)
        if state["trigger"] is None:
            if free_lj(t) / crewed <= 0.25:
                state["trigger"] = (round(t, 1), f"free ambulances in the Ljubljana area {free_lj(t)} of {crewed} (25 percent or less)")
            elif why:
                state["trigger"] = (round(t, 1), why)
        return state["trigger"] is not None

    def take(u, t, dest, scene, prio, call, kind_note=""):
        e = eta(u, t, scene, prio == "red", call.get("extra", 1.0))
        arr = t + e
        was_busy = u["free_at"] > t and is_div(u, t, prio == "red")
        _fa = u["free_at"]
        if u["area"] == "PRIV":
            leg_from, depart = (UKC if _fa > t else u["pos"]), t + max(PRIV_LEAD[u["kind"]], (_fa - t) if _fa > t else 0.0)
        elif _fa <= t:
            leg_from, depart = position(u, t), t + EXIT[u["kind"]]
        elif is_div(u, t, prio == "red"):
            leg_from, depart = position(u, t), t
        else:
            leg_from, depart = UKC, _fa + EXIT[u["kind"]]
        if was_busy:
            state["displaced"] += 1
            if u.get("job"):
                displaced_jobs.append((u["job"], u["id"]))
                if u.get("last_rec"):
                    u["last_rec"]["superseded"] = f"taken off for {call['id']}"
        u["job"] = None
        sp = SPEED * tf(t) * wf * (EMERG if prio == "red" else 1.0)
        trans = hav(scene, dest) * ROAD / sp * 60.0
        if u["kind"] == "VUZ" and prio != "red":
            done, pos = arr + SCENE_MIN[prio] + 5, scene
        else:
            done, pos = arr + SCENE_MIN[prio] + trans + HANDOVER + TURNAROUND, dest
        old = position(u, t)
        u["route"] = (old, scene, t, arr)
        u["free_at"], u["pos"] = done, pos
        u["divertable"] = prio == "yellow" and u["kind"] == "NRV"
        u["job"] = call if u["divertable"] else None
        u["state"] = f"call {call['id']}"
        role = {"NRV": "ambulance", "PAMB": "ambulance", "VUZ": "doctor", "VAN": "van", "PVAN": "van"}[u["kind"]]
        started_from_rest = (not was_busy) and u["area"] != "PRIV"
        rec = {"unit": u["id"], "kind": u["kind"], "role": role, "org": u["org"], "base": u["base"], "area": u["area"], "eta_min": round(e, 1),
               "arrives_min": round(arr, 1), "free_again_min": round(done, 1), "diverted_from_other_job": was_busy,
               "note": kind_note, "call_id": call["id"], "prio": prio, "activated_min": round(t, 2),
               "from": [round(leg_from[0], 5), round(leg_from[1], 5)], "position_at_activation": [round(old[0], 5), round(old[1], 5)], "depart_min": round(depart, 2), "scene": [round(scene[0], 5), round(scene[1], 5)], "dest": [round(dest[0], 5), round(dest[1], 5)],
               "dest_id": call.get("dest", "ukc"), "scene_min": SCENE_MIN[prio],
               "trans_min": 0.0 if (u["kind"] == "VUZ" and prio != "red") else round(trans, 2),
               "handover_min": 0.0 if (u["kind"] == "VUZ" and prio != "red") else HANDOVER,
               "turnaround_min": 0.0 if (u["kind"] == "VUZ" and prio != "red") else TURNAROUND,
               "exit_min": EXIT.get(u["kind"], 0.0) if _fa <= t and u["area"] != "PRIV" else 0.0,
               "private_lead_min": PRIV_LEAD.get(u["kind"], 0.0), "speed_kmh": round(sp, 1), "weather_factor": round(wf, 2),
               "traffic_factor": round(tf(t), 2), "fuel_note": "ok"}
        u["last_rec"] = rec
        return rec

    def assign_yellow(c, t, out, tag=""):
        sc, ds = (c["lat"], c["lon"]), (HOSP[c.get("dest", "ukc")][1], HOSP[c.get("dest", "ukc")][2])
        ex = c.get("extra", 1.0)
        cand = [u for u in fleet if u["kind"] == "NRV" and u["area"] == "LJ" and u["ok"]]
        best = min(cand, key=lambda u: eta(u, t, sc, False, ex))
        e = eta(best, t, sc, False, ex)
        note = "nearest unit in the Ljubljana area"
        if update_trigger(t) and e > 30:
            c2 = cand + [u for u in fleet if u["kind"] == "NRV" and u["area"] == "NG" and u["ok"]]
            b2 = min(c2, key=lambda u: eta(u, t, sc, False, ex))
            if eta(b2, t, sc, False, ex) < e:
                best, e, note = b2, eta(b2, t, sc, False, ex), "other area (trigger on, local wait over 30 min)"
            if e > 45:
                pc = [u for u in fleet if u["kind"] == "PAMB"]
                bp = min(pc, key=lambda u: eta(u, t, sc, False, ex))
                if eta(bp, t, sc, False, ex) < e:
                    best, note = bp, "private ambulance: wait over 45 min even with other areas [A]"
        out["assignments"].append(take(best, t, ds, sc, "yellow", c, tag + note))

    for call in calls:
        t = float(call["t"])
        advance_background(t)
        scene = (call["lat"], call["lon"])
        dest = (HOSP[call.get("dest", "ukc")][1], HOSP[call.get("dest", "ukc")][2])
        update_trigger(t)
        out = {"call": call["id"], "t": t, "assignments": [], "notes": []}
        out_by_call[call["id"]] = out
        reds = [p for p in call["patients"] if p["sev"] == "red"]
        yel = [p for p in call["patients"] if p["sev"] == "yellow"]
        grn = [p for p in call["patients"] if p["sev"] == "green"]
        n_red = sum(p["n"] for p in reds)
        n_yel = sum(p["n"] for p in yel)
        n_grn = sum(p["n"] for p in grn)
        mci = call.get("mci", False)
        want_yel_units = n_yel  # one patient per ambulance (capacity rule from the team)
        want_vans = math.ceil(n_grn / 4) if n_grn else 0
        needs[call["id"]] = {"NRV": n_red + want_yel_units, "VUZ": call.get("doctors", 0), "HNMP": 1 if call.get("air") else 0,
                             "VAN": want_vans}
        prio_call = "red" if n_red else "yellow"
        out["needs"] = needs[call["id"]]

        def pick(cands, t, red, extra):
            return min(cands, key=lambda u: eta(u, t, scene, red, extra))

        # ---- red ambulances: any public area; private only if no public unit reaches in time
        for _ in range(n_red):
            c = [u for u in fleet if u["kind"] == "NRV" and u["area"] in ("LJ", "NG") and u["ok"]]
            best = pick(c, t, True, call.get("extra", 1.0))
            e = eta(best, t, scene, True, call.get("extra", 1.0))
            note = "nearest suitable public unit"
            if e > RED_TARGET:
                update_trigger(t, f"predicted red arrival {e:.0f} min (over 15)")
                pc = [u for u in fleet if u["kind"] == "PAMB"]
                bp = pick(pc, t, True, call.get("extra", 1.0))
                if eta(bp, t, scene, True, call.get("extra", 1.0)) < e:
                    best, note = bp, "private ambulance: no public unit within 15 min"
            if best["area"] == "NG":
                note = "other area (red rule)"
            out["assignments"].append(take(best, t, dest, scene, "red", call, note))
        # ---- yellow ambulances: Ljubljana area; others only with the trigger and a long wait
        for _ in range(want_yel_units):
            assign_yellow(call, t, out)
        # ---- doctors
        for _ in range(call.get("doctors", 0)):
            c = [u for u in fleet if u["kind"] == "VUZ" and u["ok"] and (u["area"] == "LJ" or prio_call == "red")]
            best = pick(c, t, prio_call == "red", call.get("extra", 1.0))
            out["assignments"].append(take(best, t, dest, scene, prio_call, call, "doctor vehicle" + (" (other area)" if best["area"] == "NG" else "")))
        # ---- green patients: vans (public first, private if none free)
        for _ in range(want_vans):
            pub = [u for u in fleet if u["kind"] == "VAN"]
            bp = pick(pub, t, False, 1.0)
            priv = [u for u in fleet if u["kind"] == "PVAN" and u["free_at"] <= t]
            if eta(bp, t, scene, False, 1.0) > 20 and priv:
                bp = pick(priv, t, False, 1.0)
            note = "private transport van" if bp["area"] == "PRIV" else "public sanitary van"
            out["assignments"].append(take(bp, t, dest, scene, "green", call, note))
        # ---- helicopter
        if call.get("air"):
            ck = clock(t)
            flyable = 8.0 <= ck < 16.5 and not spec.get("fog_brnik")
            if flyable:
                d = hav(BRNIK, scene)
                hm = 13.0 + d / 200.0 * 60.0 + 3.0
                out["notes"].append(f"Helicopter H1 from Brnik: 13 min to take-off + {d / 200 * 60:.0f} min flight + landing = about {hm:.0f} min; "
                                    f"ground ETA of the first ambulance {min(a['eta_min'] for a in out['assignments'] if a['kind']=='NRV'):.0f} min")
                out["helicopter"] = {"launched": True, "eta_min": round(hm, 1)}
            else:
                why = spec.get("heli_reason") or ("fog at Brnik" if spec.get("fog_brnik") else None) or f"outside the daylight window (08:00 to 16:30), local time {int(ck):02d}:{int((ck % 1) * 60):02d}"
                out["notes"].append(f"Helicopter not available: {why}; ground units only")
                out["helicopter"] = {"launched": False, "reason": why}
        sr = call.get("scene_report")
        if sr:
            T = float(sr["t"])
            act = sr["actual"]
            out["needs_initial"] = dict(needs[call["id"]])
            need_n = {"NRV": act["red"] + act["yellow"], "VUZ": sr.get("doctors", 0), "VAN": math.ceil(act["green"] / 4)}
            for key, kinds in (("NRV", ("NRV", "PAMB")), ("VUZ", ("VUZ",)), ("VAN", ("VAN", "PVAN"))):
                recs = sorted([a for a in out["assignments"] if a["kind"] in kinds and not a.get("superseded")], key=lambda a: a["arrives_min"])
                for a in recs[need_n[key]:]:
                    uu = next(x for x in fleet if x["id"] == a["unit"])
                    pa = position(uu, T)
                    a["stood_down_at_min"] = T
                    a["position_at_stand_down"] = [round(pa[0], 5), round(pa[1], 5)]
                    a["free_again_min"] = T
                    uu["free_at"], uu["pos"], uu["route"], uu["divertable"], uu["state"] = T, pa, None, False, "stood down"
            needs[call["id"]] = {"NRV": need_n["NRV"], "VUZ": need_n["VUZ"], "HNMP": 1 if call.get("air") else 0, "VAN": need_n["VAN"]}
            out["needs"] = needs[call["id"]]
            out["scene_report"] = {"t_min": T, "estimate": call["patients"], "actual": act}
        while displaced_jobs:
            (jc, uid) = displaced_jobs.pop(0)
            out["notes"].append(f"{uid} was taken off {jc['id']} (yellow, not yet at the patient) for a red call; {jc['id']} is re-planned and its patient told")
            assign_yellow(jc, t, out_by_call[jc["id"]], f"re-planned at minute {t:g}: ")
        # ---- queue / capacity bookkeeping
        fl = free_lj(t)
        state["min_free"] = min(state["min_free"], fl)
        busy = len(lj_nrv) - fl
        state["peak_busy"] = max(state["peak_busy"], busy)
        out["free_lj_ambulances_after"] = fl
        log.append(out)
    # non-urgent batches
    nu = []
    for b in spec.get("non_urgent", []):
        t = float(b["t"])
        advance_background(t)
        on = update_trigger(t)
        if on:
            use = min(b["n"], sum(1 for u in fleet if u["kind"] == "PVAN" and u["free_at"] <= t))
            state["nonurgent_private"] += use
            state["nonurgent_public"] += b["n"] - use
            nu.append({"t": t, "n": b["n"], "to_private_vans": use, "kept_by_public_units": b["n"] - use, "trigger_on": True})
        else:
            state["nonurgent_public"] += b["n"]
            nu.append({"t": t, "n": b["n"], "to_private_vans": 0, "kept_by_public_units": b["n"], "trigger_on": False})
    # summary: DISTINCT units (a unit taken off one call and sent to another counts once)
    used_all = [a for o in log for a in o["assignments"]]
    used = [a for a in used_all if not a.get("stood_down_at_min")]
    sent = {}
    for a in used:
        sent[a["unit"]] = a
    sent_initial = {}
    for a in used_all:
        sent_initial[a["unit"]] = a
    stood_down = sorted(a["unit"] for a in used_all if a.get("stood_down_at_min"))
    kinds = {"NRV": "ambulances", "VUZ": "doctor_vehicles", "VAN": "sanitary_vans", "PAMB": "private_ambulances", "PVAN": "private_vans"}
    units_sent = {v: sorted(u for u, a in sent.items() if a["kind"] == k) for k, v in kinds.items()}
    heli = any(o.get("helicopter", {}).get("launched") for o in log)
    units_sent["helicopter"] = ["H1"] if heli else []
    by_kind = {k: len(v) for k, v in units_sent.items() if v}
    other_area = sorted(u for u, a in sent.items() if a["area"] == "NG")
    services = {}
    for c in calls:
        for flag, name in (("first_responders", "first responders"), ("fire", "fire brigade"), ("police", "police")):
            if c.get(flag):
                services.setdefault(name, []).append(c["id"])
        if c.get("mci"):
            for name in ("mass-casualty trailer", "incident commander and triage team"):
                services.setdefault(name, []).append(c["id"])
    red_first = {}
    for o in log:
        c = next(c for c in calls if c["id"] == o["call"])
        if any(p["sev"] == "red" for p in c["patients"]):
            red_first[o["call"]] = min(a["eta_min"] for a in o["assignments"] if a["kind"] in ("NRV", "PAMB") and not a.get("superseded"))
    total_pat = sum(p["n"] for c in calls for p in c["patients"]) if not any(c.get("scene_report") for c in calls) else sum(sum(c["scene_report"]["actual"].values()) if c.get("scene_report") else sum(p["n"] for p in c["patients"]) for c in calls)
    return {
        "log": log, "non_urgent": nu,
        "summary": {
            "calls": len(calls), "patients": total_pat,
            "units_needed_by_rule": {k: sum(n[k] for n in needs.values()) for k in ("NRV", "VUZ", "HNMP", "VAN")},
            "assignments_made": sum(1 for a in used if not a.get("superseded")),
            "units_reused_after_finishing": sum(1 for a in used if not a.get("superseded")) - len(sent),
            "initial_wave_vehicles": len(sent_initial) if stood_down else None,
            "stood_down_units": stood_down,
            "units_sent": units_sent,
            "units_dispatched": by_kind,
            "total_units_dispatched": sum(by_kind.values()),
            "other_area_units": other_area,
            "private_units": sorted(u for u, a in sent.items() if a["area"] == "PRIV"),
            "other_services_alerted": services,
            "diverted_other_jobs": state["displaced"],
            "demand_trigger": {"on": state["trigger"] is not None, "at_min": state["trigger"][0] if state["trigger"] else None,
                               "reason": state["trigger"][1] if state["trigger"] else None},
            "ljubljana_area_ambulances_crewed": len(lj_nrv),
            "ljubljana_area_ambulances_free_at_lowest": state["min_free"] if state["min_free"] != 99 else None,
            "ljubljana_area_peak_busy_percent": round(100 * state["peak_busy"] / len(lj_nrv)),
            "red_first_ambulance_arrival_min": red_first,
            "red_target_met": all(v <= RED_TARGET for v in red_first.values()) if red_first else None,
            "weather_speed_factor": round(wf, 2),
            "non_urgent_moved_to_private_vans": state["nonurgent_private"],
        },
        "ambulances_in_roster": len([u for u in fleet if u["kind"] == "NRV"]), "fleet_initial": fleet_initial,
    }


def call(i, t, place, problem, sl, patients, doctors=0, **kw):
    name, lat, lon = SCENES[place]
    return {"id": i, "t": t, "place_id": place, "place_name": name, "lat": lat, "lon": lon, "problem": problem,
            "caller_text_sl": sl, "patients": patients, "doctors": doctors, **kw}


R, Y, G = "red", "yellow", "green"
SCENARIOS = [
    {"id": "D01", "name": "Quiet morning: one yellow call", "start": "09:00", "weekday": True, "shift": "day", "background_load": 0.30,
     "weather": {}, "intent": "The smallest case: one patient, one ambulance. Shows procedure-first selection from live positions, local area only, no escalation.",
     "calls": [call("D01-C1", 0, "vic", "Fall at home, suspected hip fracture, conscious, in pain",
                    "Starejša gospa je padla doma in ne more vstati, boli jo kolk, pri zavesti je.", [{"sev": Y, "n": 1}])]},
    {"id": "D02", "name": "Chest pain: ambulance and doctor start from different places", "start": "10:30", "weekday": True, "shift": "day",
     "background_load": 0.35, "weather": {}, "intent": "One red call whose triage response includes a doctor. The doctor vehicle and the ambulance start at different bases; pre-alert to the ER.",
     "calls": [call("D02-C1", 0, "bezigrad", "Chest pain, sweating, suspected heart attack, 58 years",
                    "Mož, star 58 let, ima hude bolečine v prsih, poten je in bled.", [{"sev": R, "n": 1}], doctors=1, first_responders=True)]},
    {"id": "D03a", "name": "Cardiac arrest at a mountain trailhead, helicopter flies", "start": "11:15", "weekday": True, "shift": "day",
     "background_load": 0.35, "weather": {}, "intent": "Red call far from the base. Helicopter, doctor vehicle, ambulance and first responders. The agent races the helicopter against the ground ETA.",
     "calls": [call("D03a-C1", 0, "kamnisko_bistrica", "Cardiac arrest, bystander CPR in progress",
                    "Pohodnik se je zgrudil, ne diha, mimoidoči ga oživljajo.", [{"sev": R, "n": 1}], doctors=1, air=True, first_responders=True)]},
    {"id": "D03b", "name": "Same call with fog at Brnik: helicopter grounded", "start": "11:15", "weekday": True, "shift": "day",
     "background_load": 0.35, "weather": {"precip_mm": 0.0}, "fog_brnik": True,
     "intent": "The same call, but fog grounds the helicopter. The ground units already moved at the first minute; no replan needed.",
     "calls": [call("D03b-C1", 0, "kamnisko_bistrica", "Cardiac arrest, bystander CPR in progress",
                    "Pohodnik se je zgrudil, ne diha, mimoidoči ga oživljajo.", [{"sev": R, "n": 1}], doctors=1, air=True, first_responders=True)]},
    {"id": "D04", "world_events": [{"id": "W1", "type": "closure", "target": {"call": "D04-C1", "role": "ambulance", "phase": "to_scene", "when": 0.35, "where": 0.7}, "radius_m": 250, "duration_min": 40, "title_sl": "Cesta je zaprta zaradi prometne nesreče", "title_en": "Road closed after a collision"}], "name": "Two reds compete for the nearest unit", "start": "13:50", "weekday": True, "shift": "day", "background_load": 0.40,
     "weather": {}, "intent": "A yellow call is on its way when two red calls arrive three minutes apart. Shows diversion of a lower-priority unit and a dispatcher question when the clinical order is unclear.",
     "calls": [call("D04-C0", 0, "bezigrad", "Minor injuries after a fall from a bicycle", "Kolesar je padel, ima odrgnine in boli ga zapestje.", [{"sev": Y, "n": 1}]),
               call("D04-C1", 2, "siska", "Cardiac arrest at home, relative does CPR", "Žena ne diha, sin jo oživlja, Šiška.", [{"sev": R, "n": 1}], doctors=1, first_responders=True),
               call("D04-C2", 5, "crnuce", "Suspected stroke, face droop, arm weakness", "Moški ima povešen obraz in ne more dvigniti roke.", [{"sev": R, "n": 1}])]},
    {"id": "D05", "world_events": [{"id": "W1", "type": "duplicate_call", "call": "D05-C1", "t_min": 2, "caller_text_sl": "Drugi klicatelj: na obvoznici je več vozil, eno vozilo gori.", "title_en": "Second caller about the same crash (merged, no new units)"}, {"id": "W2", "type": "closure", "target": {"call": "D05-C1", "role": "ambulance", "phase": "to_scene", "when": 0.4, "where": 0.75}, "radius_m": 300, "duration_min": 45, "title_sl": "Zaprt pas ob kraju nesreče", "title_en": "Lane closed at the crash approach"}], "name": "Multi-vehicle crash on the ring road at dusk", "start": "17:20", "weekday": True, "shift": "day", "background_load": 0.45,
     "weather": {"precip_mm": 0.5, "temp_c": 4}, "intent": "One incident, six patients (2 red, 2 yellow, 2 green): seven units plus fire and police. Helicopter window has closed, rush hour and a closed lane slow every ETA.",
     "calls": [call("D05-C1", 0, "ring_east", "Crash of four vehicles, six injured, one trapped", "Trčenje štirih vozil na obvoznici, šest ranjenih, eden je ukleščen.",
                    [{"sev": R, "n": 2}, {"sev": Y, "n": 2}, {"sev": G, "n": 2}], doctors=2, air=True, fire=True, police=True, first_responders=True, extra=0.85)]},
    {"id": "D06", "world_events": [{"id": "W1", "type": "accident", "target": {"call": "D06-C4", "role": "ambulance", "phase": "to_scene", "when": 0.25, "where": 0.5}, "radius_m": 200, "duration_min": 25, "delay_min": 6, "title_sl": "Zastoj zaradi prometne nesreče", "title_en": "Jam after a minor collision"}], "name": "Rush hour mix: one red, five yellow, scheduled discharges", "start": "16:00", "weekday": True, "shift": "day", "background_load": 0.45,
     "weather": {}, "intent": "Steady pressure over an hour in rush hour: six calls, one red and five yellow. The agent keeps the area rule, uses the nearest free unit each time and leaves eight scheduled discharges with the public units because the demand trigger never fires.",
     "calls": [call("D06-C1", 0, "moste", "Abdominal pain with vomiting blood", "Moški bruha kri in mu je slabo.", [{"sev": Y, "n": 1}]),
               call("D06-C2", 8, "crnuce", "Fall from a ladder, head injury, drowsy", "Padel je z lestve, udaril se je v glavo, je zaspan.", [{"sev": R, "n": 1}], doctors=1),
               call("D06-C3", 22, "kocevje", "Breathing difficulty, known asthma", "Otrok težko diha, ima astmo.", [{"sev": Y, "n": 1}]),
               call("D06-C4", 31, "polje", "Severe pain in the leg after a fall", "Gospa se je zvila, noga je otekla in boli.", [{"sev": Y, "n": 1}]),
               call("D06-C5", 44, "rudnik", "Allergic reaction, hives and swollen lips", "Po piku čebele ima otekle ustnice in izpuščaj.", [{"sev": Y, "n": 1}]),
               call("D06-C6", 55, "trzin", "Diabetic, confused and sweating", "Sladkorni bolnik je zmeden in oblit z znojem.", [{"sev": Y, "n": 1}])],
     "non_urgent": [{"t": 30, "n": 8}]},
    {"id": "D07", "world_events": [{"id": "W1", "type": "breakdown", "target": {"call": "D07-C1", "role": "ambulance", "phase": "transport", "when": 0.5, "where": 0.7}, "title_sl": "Okvara vozila s pacientom na krovu", "title_en": "Ambulance breakdown with the patient aboard"}], "name": "Busy afternoon, teams near full capacity", "start": "15:00", "weekday": True, "shift": "day", "background_load": 0.75,
     "weather": {"precip_mm": 1.0, "temp_c": 6}, "intent": "Eleven calls in 75 minutes (3 red, 8 yellow) while most ambulances are already out. The demand trigger fires; non-urgent transports move to private vans; yellow calls and reds draw on other areas.",
     "calls": [call("D07-C1", 0, "siska", "Chest pain, 66 years", "Gospa ima stiskanje v prsih.", [{"sev": R, "n": 1}], doctors=1),
               call("D07-C2", 4, "moste", "Fall, wrist fracture", "Padec, zlomljeno zapestje.", [{"sev": Y, "n": 1}]),
               call("D07-C3", 9, "domzale", "Breathing difficulty, COPD", "Težko diha, ima KOPB.", [{"sev": R, "n": 1}], doctors=1),
               call("D07-C4", 14, "vrhnika", "Fall from a bicycle, hurt shoulder", "Kolesar je padel, boli ga rama.", [{"sev": Y, "n": 1}]),
               call("D07-C5", 20, "grosuplje", "Syncope, now awake", "Omedlel je, zdaj je buden.", [{"sev": Y, "n": 1}]),
               call("D07-C6", 27, "bezigrad", "High fever and confusion, elderly", "Starejši gospod ima vročino in je zmeden.", [{"sev": Y, "n": 1}]),
               call("D07-C7", 33, "crnuce", "Stroke symptoms", "Znaki možganske kapi, govor je moten.", [{"sev": R, "n": 1}]),
               call("D07-C8", 41, "vic", "Back pain after lifting", "Hud hrbtni bolečin po dvigovanju.", [{"sev": Y, "n": 1}]),
               call("D07-C9", 50, "medvode", "Kidney colic", "Ledvična kolika.", [{"sev": Y, "n": 1}]),
               call("D07-C10", 58, "skofljica", "Laceration, bleeding controlled", "Rana na roki, krvavitev ustavljena.", [{"sev": Y, "n": 1}]),
               call("D07-C11", 68, "polje", "Pregnant, bleeding", "Nosečnica ima krvavitev.", [{"sev": Y, "n": 1}])],
     "non_urgent": [{"t": 30, "n": 15}]},
    {"id": "D08", "date": "2026-11-28", "world_events": [{"id": "W1", "type": "duplicate_call", "call": "D08-C2", "t_min": 13, "caller_text_sl": "Drugi klicatelj: avto je v jarku, voznik se ne odziva.", "title_en": "Second caller about the same crash (merged)"}], "name": "Saturday night, thin staffing, three reds", "start": "03:20", "weekday": False, "shift": "night", "background_load": 0.50,
     "weather": {}, "intent": "Night roster (22 ambulances in the area against 26 by day), no helicopter, three reds in 21 minutes at different ends of the area. Shows other-area units for reds and the private option as last resort.",
     "calls": [call("D08-C1", 0, "domzale", "Cardiac arrest at a party", "Mladenič je padel in ne diha.", [{"sev": R, "n": 1}], doctors=1, first_responders=True),
               call("D08-C2", 12, "vrhnika", "Road crash, driver unconscious", "Prometna nesreča, voznik je nezavesten.", [{"sev": R, "n": 1}], doctors=1, fire=True, police=True),
               call("D08-C3", 21, "grosuplje", "Severe bleeding from a stab wound", "Zabodena rana, močna krvavitev.", [{"sev": R, "n": 1}], doctors=1, police=True)]},
    {"id": "D09", "date": "2026-12-01", "world_events": [{"id": "W1", "type": "closure", "target": {"call": "D09-C3", "role": "ambulance", "phase": "to_scene", "when": 0.3, "where": 0.65}, "radius_m": 300, "duration_min": 60, "title_sl": "Cesta zaprta zaradi snega in zdrsa", "title_en": "Road closed after a skid in the snow"}, {"id": "W2", "type": "feed_stale", "feed": "traffic", "t_min": 30, "duration_min": 15, "title_en": "Traffic feed stale for 15 minutes: ETAs marked uncertain"}], "name": "Snow and ice morning: many calls, slow roads", "start": "07:30", "weekday": True, "shift": "day", "background_load": 0.55,
     "weather": {"snow_cm": 3.0, "temp_c": -2.0, "precip_mm": 1.5, "wind_kmh": 20}, "fog_brnik": True, "heli_reason": "snow and low cloud at Brnik (assumed)", "cleaning": {"A03": 30}, "low_fuel": ["A05"],
     "intent": "Snow cuts road speed to 0.6 of normal on top of rush hour. Fourteen calls in two hours. One ambulance is cleaning, one is too low on fuel to be offered, the helicopter is grounded and non-urgent trips move to private vans.",
     "calls": [call("D09-C1", 0, "zaloska", "Crash on icy road, driver trapped", "Zdrsnilo je in trčilo, voznik je ukleščen.", [{"sev": R, "n": 1}], doctors=1, fire=True, police=True, air=True, extra=0.9),
               call("D09-C2", 6, "moste", "Fall on ice, wrist and hip pain", "Padec na ledu, boli zapestje in kolk.", [{"sev": Y, "n": 1}]),
               call("D09-C3", 12, "polje", "Fall on ice, head wound", "Padec na ledu, krvavi iz glave.", [{"sev": Y, "n": 1}]),
               call("D09-C4", 19, "siska", "Fall on ice, ankle", "Padec na ledu, gleženj.", [{"sev": Y, "n": 1}]),
               call("D09-C5", 25, "crnuce", "Two cars collided, one injured", "Trčenje dveh vozil, en ranjen.", [{"sev": Y, "n": 1}]),
               call("D09-C6", 31, "domzale", "Chest pain after shovelling snow", "Bolečine v prsih po metanju snega.", [{"sev": R, "n": 1}], doctors=1),
               call("D09-C7", 38, "rudnik", "Fall on ice, shoulder", "Padec na ledu, rama.", [{"sev": Y, "n": 1}]),
               call("D09-C8", 44, "vic", "Fall on ice, wrist", "Padec, zapestje.", [{"sev": Y, "n": 1}]),
               call("D09-C9", 52, "vrhnika", "Car off the road, passenger hurt", "Avto je zdrsnil s ceste, sopotnik je poškodovan.", [{"sev": Y, "n": 1}]),
               call("D09-C10", 61, "grosuplje", "Fall on ice, hip", "Padec na ledu, kolk.", [{"sev": Y, "n": 1}]),
               call("D09-C11", 70, "bezigrad", "Fall, neck pain", "Padec, boli vrat.", [{"sev": Y, "n": 1}]),
               call("D09-C12", 83, "kamnik", "Hypothermia, found outside", "Najden je podhlajen na prostem.", [{"sev": Y, "n": 1}]),
               call("D09-C13", 96, "medvode", "Fall on ice, leg", "Padec na ledu, noga.", [{"sev": Y, "n": 1}]),
               call("D09-C14", 110, "skofljica", "Fall on ice, wrist", "Padec na ledu, zapestje.", [{"sev": Y, "n": 1}])],
     "non_urgent": [{"t": 20, "n": 20}]},
    {"id": "D11", "world_events": [{"id": "W1", "type": "capacity_drop", "t_min": 8, "hospital": "ukc", "resus_bays_free": 0, "title_en": "UKC emergency department reports no free resuscitation bay; yellow and scheduled arrivals are redirected, red stays with UKC"}], "name": "Everything is out: no public unit is free within 15 minutes", "start": "16:00", "weekday": True, "shift": "day", "background_load": 1.0, "divert_p": 0.0, "ng_factor": 1.0, "busy_min": 18,
     "weather": {"wind_kmh": 70, "precip_mm": 3.0, "temp_c": 8},
     "intent": "Storm hour, an extreme case: every ambulance in the area and in the neighbouring areas is tied up for at least 18 minutes. Two reds and two yellows arrive. Shows the rule for private ambulances: used for a red call only when no public unit, from any area, reaches in 15 minutes and the private one is faster.",
     "calls": [call("D11-C1", 0, "bezigrad", "Collapse in the street, not breathing", "Moški se je zgrudil na ulici in ne diha.", [{"sev": R, "n": 1}], doctors=1, first_responders=True),
               call("D11-C2", 5, "polje", "Tree fell on a car, driver trapped", "Drevo je padlo na avto, voznik je ukleščen.", [{"sev": R, "n": 1}], doctors=1, fire=True, police=True),
               call("D11-C3", 10, "siska", "Roof tile injury, bleeding head", "Strešnik je padel na glavo, krvavi.", [{"sev": Y, "n": 1}]),
               call("D11-C4", 16, "vic", "Fall in the storm, hip pain", "Padec v vihari, boli kolk.", [{"sev": Y, "n": 1}])],
     "non_urgent": [{"t": 12, "n": 18}]},
    {"id": "D10", "name": "Mass-casualty: bus crash on the motorway, 22 patients", "start": "18:10", "weekday": True, "shift": "day", "background_load": 0.50,
     "weather": {"precip_mm": 0.5, "temp_c": 3}, "heli_reason": "outside the daylight window (08:00 to 16:30)",
     "world_events": [{"id": "W1", "type": "closure", "target": {"call": "D10-C1", "role": "ambulance", "phase": "to_scene", "when": 0.45, "where": 0.8}, "radius_m": 350, "duration_min": 90,
                       "title_sl": "Zaprt uvoz na avtocesto zaradi gasilcev", "title_en": "Slip road closed by the fire brigade"}],
     "intent": "The largest case: the caller says about 30 injured, so the agent sends everything it can within the 25-vehicle cap at once. The first team triages on scene (22 patients: 4 red, 8 yellow, 10 green) and reports; the vehicles that are still on their way and not needed are stood down. A human declares the mass-casualty event.",
     "calls": [call("D10-C1", 0, "a1_bus", "Coach and car crash on the motorway, caller estimates about 30 injured", "Avtobus je trčil na avtocesti, ranjenih je približno trideset.",
                    [{"sev": R, "n": 5}, {"sev": Y, "n": 10}, {"sev": G, "n": 15}], doctors=5, air=True, fire=True, police=True, mci=True, first_responders=True, extra=0.85,
                    scene_report={"t": 12, "actual": {"red": 4, "yellow": 8, "green": 10}, "doctors": 4})]},
    {"id": "D12", "name": "Everything at once: seven overlapping calls with a closure, a jam, a breakdown and a priority change", "start": "10:00", "weekday": True, "shift": "day",
     "background_load": 0.45, "weather": {}, "date": "2026-11-24",
     "world_events": [
        {"id": "W1", "type": "duplicate_call", "call": "D12-C3", "t_min": 4, "caller_text_sl": "Drugi klicatelj: pešec leži na cesti pri Zaloški, avto je odpeljal.", "title_en": "Second caller about the pedestrian crash (merged, no new units)"},
        {"id": "W2", "type": "closure", "target": {"call": "D12-C5", "role": "ambulance", "phase": "to_scene", "when": 0.3, "where": 0.6}, "radius_m": 300, "duration_min": 45,
         "title_sl": "Cesta proti Domžalam zaprta zaradi nesreče", "title_en": "Road towards Domžale closed after a collision"},
        {"id": "W3", "type": "accident", "target": {"call": "D12-C4", "role": "ambulance", "phase": "transport", "when": 0.2, "where": 0.5}, "radius_m": 200, "duration_min": 20, "delay_min": 4,
         "title_sl": "Zastoj zaradi trčenja", "title_en": "Jam after a minor collision"},
        {"id": "W4", "type": "feed_stale", "feed": "traffic", "t_min": 10, "duration_min": 5, "title_en": "Traffic feed stale for 5 minutes: ETAs marked uncertain"},
        {"id": "W5", "type": "breakdown", "target": {"call": "D12-C6", "role": "ambulance", "phase": "transport", "when": 0.5, "where": 0.7}, "title_sl": "Okvara vozila s pacientom na krovu", "title_en": "Ambulance breakdown with the patient aboard"},
        {"id": "W6", "type": "capacity_drop", "t_min": 16, "hospital": "ukc", "resus_bays_free": 1, "title_en": "UKC emergency department reports one free resuscitation bay"},
        {"id": "W7", "type": "priority_change", "call": "D12-C7", "t_min": 21, "from": "yellow", "to": "red", "add_doctor": True, "title_en": "Caller calls back: the pain has become severe, suspected heart attack. The dispatcher re-triages to red and a doctor vehicle is added"}],
     "intent": "A 25-minute demo script where events overlap: two calls in the same minute, a call that arrives while two others are on the road, a duplicate caller, a closure on a route, a jam, a feed that goes stale, an ambulance that breaks down with a patient aboard, a hospital that reports less capacity and a patient who gets worse.",
     "calls": [call("D12-C1", 0, "bezigrad", "Chest pain, sweating, suspected heart attack, 58 years", "Mož, star 58 let, ima hude bolečine v prsih, poten je in bled.", [{"sev": R, "n": 1}], doctors=1, first_responders=True),
               call("D12-C2", 0, "vic", "Fall at home, suspected hip fracture", "Starejša gospa je padla doma in ne more vstati, boli jo kolk.", [{"sev": Y, "n": 1}]),
               call("D12-C3", 3, "zaloska", "Pedestrian hit by a car, lying on the road", "Pešca je zadel avto, leži na cesti in je pri zavesti.", [{"sev": R, "n": 1}], doctors=1, police=True, first_responders=True),
               call("D12-C4", 6, "siska", "Allergic reaction after a wasp sting, swollen lips", "Po piku ose ima otekle ustnice in težko diha.", [{"sev": Y, "n": 1}]),
               call("D12-C5", 9, "domzale", "Cardiac arrest at home, relative does CPR", "Mož ne diha, žena ga oživlja.", [{"sev": R, "n": 1}], doctors=1, first_responders=True),
               call("D12-C6", 14, "crnuce", "Diabetic, confused and sweating", "Sladkorni bolnik je zmeden in oblit z znojem.", [{"sev": Y, "n": 1}]),
               call("D12-C7", 18, "polje", "Chest tightness, 62 years", "Gospod ima stiskanje v prsih, ne boli hudo.", [{"sev": Y, "n": 1}])]},
]


def main():
    out = {"meta": {
        "name": "Dispatch scenarios for the agentic flow", "synthetic": True, "seed": SEED,
        "colour_scheme": "red = life-threatening (engine priority emergency); yellow = possible danger or needs a doctor's assessment (engine priority urgent); "
                         "non-urgent = scheduled transport (engine priority scheduled). Green appears only as the on-scene severity of walking patients in multi-patient incidents.",
        "model": "Procedure-first assignment: red -> nearest suitable public unit from any area, private ambulance only if no public unit reaches in 15 min and the private one is faster; "
                 "yellow -> Ljubljana-area units, other areas only with the demand trigger on and a local wait over 30 min, private only over 45 min [A]; "
                 "non-urgent -> private vans once the trigger is on; doctor vehicles follow red calls with a doctor flag; one patient per ambulance, so red and yellow patients each need an ambulance.",
        "demand_trigger": "free ambulances in the Ljubljana area are 25 percent or less of those crewed, or a red arrival is predicted over 15 minutes [A threshold]",
        "travel": "Same constants as backend/app/routing.py: road factor 1.35, 42 km/h, lights and sirens x1.3 for red, weather factor and time-of-day traffic profile copied from the engine; positions interpolate while a unit drives",
        "service_times_min": {"scene_red": 20, "scene_yellow": 15, "handover": 12, "turnaround": 8, "tag": "[A]"},
        "assumptions": [
            "Roster by shift: 26 ambulances crewed in the Ljubljana emergency area by day, 22 by night (decree team counts of 1.5 become 2 by day, 1 by night)",
            "Doctor vehicles: 10 in the Ljubljana area by day, 9 by night; 5 in neighbouring areas",
            "Neighbouring areas used: Kranj, Škofja Loka, Tržič, Litija, Zagorje, Trbovlje, Trebnje, Novo mesto (unit counts rounded from the decree)",
            "Private providers: 3 ambulances with qualified crews (mobilisation 15 min) and 6 non-urgent vans (30 min); bases and crew qualification are not published",
            "Background load: share of units busy with non-urgent transports at the start, 30 percent is the all-day average from 134 interventions a day",
            "Which red calls get a doctor is set by the triage step; the flag is an input here (SloIn NMP text is not public)",
            "Slovenian caller texts are drafts to be read by a native speaker",
        ]},
        "scenes": {k: {"name": v[0], "lat": v[1], "lon": v[2]} for k, v in SCENES.items()},
        "hospitals": {k: {"name": v[0], "lat": v[1], "lon": v[2]} for k, v in HOSP.items()},
        "rosters": {s: {k: sum(1 for u in roster(s) if u["kind"] == k and u["area"] == a) for k, a in (("NRV", "LJ"), ("VUZ", "LJ"))} for s in ("day", "night")},
        "scenarios": []}
    out["meta"]["rosters_detail"] = {s: {"ljubljana_area_ambulances": sum(1 for u in roster(s) if u["kind"] == "NRV" and u["area"] == "LJ"),
                                         "ljubljana_area_doctor_vehicles": sum(1 for u in roster(s) if u["kind"] == "VUZ" and u["area"] == "LJ"),
                                         "other_area_ambulances": sum(1 for u in roster(s) if u["kind"] == "NRV" and u["area"] == "NG"),
                                         "other_area_doctor_vehicles": sum(1 for u in roster(s) if u["kind"] == "VUZ" and u["area"] == "NG"),
                                         "public_sanitary_vans": sum(1 for u in roster(s) if u["kind"] == "VAN"),
                                         "private_ambulances": sum(1 for u in roster(s) if u["kind"] == "PAMB"),
                                         "private_vans": sum(1 for u in roster(s) if u["kind"] == "PVAN")} for s in ("day", "night")}
    del out["rosters"]
    for i, spec in enumerate(sorted(SCENARIOS, key=lambda x: x["id"])):
        res = run(spec, i)
        engine = []
        for c in spec["calls"]:
            top = "emergency" if any(p["sev"] == "red" for p in c["patients"]) else "urgent"
            engine.append({"call": c["id"], "t_min": c["t"], "payload": {"type": "urgent_request", "lat": c["lat"], "lon": c["lon"], "dropoff_id": "ukc",
                                                                         "needs": "stretcher", "priority": top, "note": c["problem"]}})
        out["scenarios"].append({
            "id": spec["id"], "name": spec["name"], "intent": spec["intent"], "start_local": spec["start"],
            "weekday": spec["weekday"], "shift": spec["shift"], "weather": spec.get("weather", {}), "fog_at_brnik": spec.get("fog_brnik", False),
            "background_load": spec["background_load"], "units_not_offered": {"cleaning": spec.get("cleaning", {}), "low_fuel": spec.get("low_fuel", [])},
            "date": spec.get("date", "2026-11-24"), "world_events": spec.get("world_events", []), "fleet_initial": res["fleet_initial"],
            "calls": spec["calls"], "non_urgent_batches": spec.get("non_urgent", []),
            "engine_events": engine, "expected": res["summary"], "dispatch_log": res["log"], "non_urgent_log": res["non_urgent"]})
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for s in out["scenarios"]:
        e = s["expected"]
        print(f'{s["id"]:5s} calls {e["calls"]:2d} patients {e["patients"]:2d} needed {e["units_needed_by_rule"]} dispatched {e["total_units_dispatched"]:2d} '
              f'other-area {len(e["other_area_units"])} private {len(e["private_units"])} diverted {e["diverted_other_jobs"]} '
              f'trigger {e["demand_trigger"]["at_min"]} peak {e["ljubljana_area_peak_busy_percent"]}% red {e["red_first_ambulance_arrival_min"]} met {e["red_target_met"]}')


if __name__ == "__main__":
    main()
