"""Build replayable simulation scripts (one JSON per scenario) from docs/scenario/dispatch_scenarios.json.

Each script holds: calls, vehicles (timeline, road path with timestamps, statuses, fuel), patients (vitals, voice entries), road events with reroutes,
and ONE master event stream that every dashboard (dispatch, ER, crew screen, map) filters by `visible_on`.
Road paths come from the public OSRM demo server (light use, cached); if it fails a synthetic path is used and marked.
Run: python playback_gen.py [scenario ids...]
"""
import hashlib
import json
import math
import os
import random
import sys
import time
import urllib.request
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pb_templates import TEMPLATES, pick_template  # noqa: E402

SC = REPO + "/docs/scenario/dispatch_scenarios.json"
OUTDIR = REPO + "/docs/scenario/reference_runs"
import tempfile
CACHE = os.environ.get("OSRM_CACHE", os.path.join(tempfile.gettempdir(), "adahack_osrm_cache.json"))
OFFSET = 120  # seconds before the first model minute, so call_received and triage come before the plan
ROAD = 1.35

# ---------------------------------------------------------------- geometry
def hav_km(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(x))


def xy(p, lat0):
    return math.radians(p[1]) * 6371000.0 * math.cos(math.radians(lat0)), math.radians(p[0]) * 6371000.0


def seg_dist_m(p, a, b):
    lat0 = (a[0] + b[0]) / 2
    px, py = xy(p, lat0)
    ax, ay = xy(a, lat0)
    bx, by = xy(b, lat0)
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def path_len_m(path):
    return sum(hav_km(path[i], path[i + 1]) * 1000 for i in range(len(path) - 1))


def hits(path, c):
    ctr = (c["lat"], c["lon"])
    return any(seg_dist_m(ctr, path[i], path[i + 1]) <= c["r"] for i in range(len(path) - 1))


def point_at_dist(path, d):
    acc = 0.0
    for i in range(len(path) - 1):
        seg = hav_km(path[i], path[i + 1]) * 1000
        if acc + seg >= d or i == len(path) - 2:
            f = 0 if seg == 0 else max(0.0, min(1.0, (d - acc) / seg))
            return (path[i][0] + (path[i + 1][0] - path[i][0]) * f, path[i][1] + (path[i + 1][1] - path[i][1]) * f)
        acc += seg
    return path[-1]


def track_from_path(path, t0, dur):
    total = max(path_len_m(path), 1.0)
    out, acc = [[round(t0, 1), round(path[0][0], 5), round(path[0][1], 5)]], 0.0
    for i in range(1, len(path)):
        acc += hav_km(path[i - 1], path[i]) * 1000
        out.append([round(t0 + dur * acc / total, 1), round(path[i][0], 5), round(path[i][1], 5)])
    return out


def pos_at(track, t):
    if t <= track[0][0]:
        return (track[0][1], track[0][2])
    for i in range(len(track) - 1):
        if track[i][0] <= t <= track[i + 1][0]:
            span = track[i + 1][0] - track[i][0]
            f = 0 if span == 0 else (t - track[i][0]) / span
            return (track[i][1] + (track[i + 1][1] - track[i][1]) * f, track[i][2] + (track[i + 1][2] - track[i][2]) * f)
    return (track[-1][1], track[-1][2])


# ---------------------------------------------------------------- OSRM with cache
_cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
_last = [0.0]
_stats = {"osrm": 0, "cached": 0, "synthetic": 0}


def synthetic(a, b, via=None):
    pts = [a] + ([via] if via else []) + [b]
    if not via:
        mid = ((a[0] + b[0]) / 2 + (b[1] - a[1]) * 0.03, (a[1] + b[1]) / 2 - (b[0] - a[0]) * 0.03)
        pts = [a, mid, b]
    return {"path": [list(p) for p in pts], "dist_m": path_len_m(pts) * 1.2, "src": "synthetic"}


def osrm_routes(a, b, via=None, alternatives=False):
    key = f"{a[0]:.4f},{a[1]:.4f};{b[0]:.4f},{b[1]:.4f};{via and (round(via[0], 4), round(via[1], 4))};{alternatives}"
    if key in _cache:
        _stats["cached"] += 1
        return _cache[key]
    coords = [a] + ([via] if via else []) + [b]
    cs = ";".join(f"{lon:.5f},{lat:.5f}" for lat, lon in coords)
    url = f"https://router.project-osrm.org/route/v1/driving/{cs}?overview=simplified&geometries=geojson&alternatives={'true' if alternatives else 'false'}"
    wait = 0.4 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "adahack-prototype-research/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.load(r)
        routes = [{"path": [[la, lo] for lo, la in rt["geometry"]["coordinates"]], "dist_m": rt["distance"], "src": "osrm"} for rt in d["routes"]]
        _stats["osrm"] += 1
    except Exception as ex:  # noqa: BLE001
        print("   OSRM failed:", str(ex)[:80])
        routes = [synthetic(a, b, via)]
        _stats["synthetic"] += 1
    _last[0] = time.time()
    _cache[key] = routes
    return routes


def route(a, b, avoid=()):
    if hav_km(a, b) < 0.03:
        return {"path": [list(a), list(b)], "dist_m": hav_km(a, b) * 1000, "src": "direct"}
    base_route = osrm_routes(a, b, alternatives=False)[0]
    if not avoid or not any(hits(base_route["path"], c) for c in avoid):
        return base_route
    alts = osrm_routes(a, b, alternatives=True)
    ok = [r for r in alts if not any(hits(r["path"], c) for c in avoid)]
    if ok:
        return min(ok, key=lambda r: r["dist_m"])
    c = avoid[0]
    base = alts[0]["path"]
    # direction of travel near the closure, then a via point to one side of it
    k = min(range(len(base) - 1), key=lambda i: seg_dist_m((c["lat"], c["lon"]), base[i], base[i + 1]))
    dy, dx = base[k + 1][0] - base[k][0], base[k + 1][1] - base[k][1]
    n = math.hypot(dx * math.cos(math.radians(c["lat"])), dy) or 1.0
    off = max(1500.0, 5 * c["r"]) / 111000.0
    cands = []
    for sgn in (1, -1):
        via = (c["lat"] + sgn * (dx * math.cos(math.radians(c["lat"])) / n) * off, c["lon"] - sgn * (dy / n) * off / math.cos(math.radians(c["lat"])))
        r2 = osrm_routes(a, b, via=via)[0]
        if not any(hits(r2["path"], cc) for cc in avoid):
            cands.append(r2)
    if cands:
        return min(cands, key=lambda r: r["dist_m"])
    return {**synthetic(a, b, via), "src": "synthetic_detour"}


# ---------------------------------------------------------------- legs with closures and accidents
def make_leg(p_from, p_to, t0, dur, closures, accidents):
    active = [c for c in closures if c["t0"] <= t0 < c["t1"]]
    r = route(p_from, p_to, active)
    track = track_from_path(r["path"], t0, dur)
    events, src = [], r["src"]
    pend = sorted([("c", c) for c in closures if c["t0"] > t0] + [("a", a) for a in accidents if a["t1"] > t0], key=lambda x: x[1]["t0"])
    for kind, ev in pend:
        tend = track[-1][0]
        te = ev["t0"]
        if te >= tend:
            continue
        pos = pos_at(track, max(te, t0))
        rem = [pos] + [(p[1], p[2]) for p in track if p[0] > max(te, t0)]
        if kind == "c":
            if not hits(rem, ev):
                continue
            others = [c for c in closures if c["t0"] <= te < c["t1"]]
            r2 = route(pos, p_to, others)
            old_len, new_len = path_len_m(rem), path_len_m(r2["path"])
            eff_new = max(new_len, old_len * 1.08)  # a detour is never faster than the original fastest route
            new_dur = (tend - te) * (eff_new / max(old_len, 1.0)) + 30.0
            track = [p for p in track if p[0] < te] + track_from_path(r2["path"], te, new_dur)
            src = r2["src"]
            events.append({"type": "reroute", "t": te, "closure": ev["id"], "from": [round(pos[0], 5), round(pos[1], 5)], "old_remaining_m": round(old_len), "new_remaining_m": round(new_len),
                           "delta_s": round(new_dur - (tend - te), 1), "new_path": [[round(p[1], 5), round(p[2], 5)] for p in track if p[0] >= te], "path_source": r2["src"]})
        else:
            dsts = 0.0
            hitp = None
            L = path_len_m(rem)
            while dsts <= L:
                pt = point_at_dist(rem, dsts)
                if math.hypot(*[(pt[0] - ev["lat"]) * 111000, (pt[1] - ev["lon"]) * 111000 * math.cos(math.radians(ev["lat"]))]) <= ev["r"]:
                    hitp = (dsts, pt)
                    break
                dsts += 25.0
            if not hitp:
                continue
            tc = max(te, pos_at_time_of_dist(track, pos, rem, hitp[0], max(te, t0)))
            if tc > ev["t1"] or tc >= track[-1][0]:
                continue
            d_s = ev["delay_s"]
            new = []
            for p in track:
                new.append([round(p[0] + (d_s if p[0] > tc else 0), 1), p[1], p[2]])
            i = next(i for i, p in enumerate(new) if p[0] > tc + d_s - 1e-6) if any(p[0] > tc + d_s - 1e-6 for p in new) else len(new)
            new[i:i] = [[round(tc, 1), round(hitp[1][0], 5), round(hitp[1][1], 5)], [round(tc + d_s, 1), round(hitp[1][0], 5), round(hitp[1][1], 5)]]
            track = new
            events.append({"type": "traffic_delay", "t": tc, "accident": ev["id"], "delay_s": d_s, "at": [round(hitp[1][0], 5), round(hitp[1][1], 5)]})
    return {"track": track, "events": events, "t_end": track[-1][0], "src": src}


def pos_at_time_of_dist(track, pos, rem, d, tmin):
    """Time at which the vehicle has covered distance d along the remaining path (uniform speed on the remaining track)."""
    t_start = max(tmin, track[0][0])
    t_end = track[-1][0]
    L = max(path_len_m(rem), 1.0)
    return t_start + (t_end - t_start) * min(1.0, d / L)


# ---------------------------------------------------------------- helpers
def h8(*a):
    return int(hashlib.sha1("|".join(map(str, a)).encode()).hexdigest()[:8], 16)


def hhmmss(t):
    t = int(round(t))
    return f"{(t // 3600) % 24:02d}:{(t % 3600) // 60:02d}:{t % 60:02d}"


class Script:
    def __init__(self, scen):
        self.s = scen
        self.events = []
        self.seq = 0
        h, m = (int(x) for x in scen["start_local"].split(":"))
        self.start_dt = datetime.fromisoformat(f'{scen["date"]}T{h:02d}:{m:02d}:00')
        self.hosp = {k: v for k, v in json.load(open(SC, encoding="utf-8"))["hospitals"].items()}

    def iso(self, t):
        return (self.start_dt + timedelta(seconds=t - OFFSET)).isoformat() + "+01:00"

    def emit(self, t, typ, vis, **kw):
        self.seq += 1
        self.events.append({"seq": self.seq, "t_s": round(t, 1), "clock": self.iso(t)[11:19], "iso": self.iso(t), "type": typ, "visible_on": vis, **kw})


D_ALL = ["dispatch", "er", "crew", "map"]


def fmt_pt(p):
    return [round(p[0], 5), round(p[1], 5)]


# ---------------------------------------------------------------- build one scenario
def build(scen):
    S = Script(scen)
    calls = {c["id"]: c for c in scen["calls"]}
    log = {o["call"]: o for o in scen["dispatch_log"]}
    meta = json.load(open(SC, encoding="utf-8"))["meta"]
    hosp = json.load(open(SC, encoding="utf-8"))["hospitals"]
    fleet0 = {u["id"]: u for u in scen["fleet_initial"]}
    wev = scen.get("world_events", [])
    closures, accidents, others = [], [], []

    # ---- all assignment records in chronological order, per unit
    recs = []
    for o in scen["dispatch_log"]:
        for a in o["assignments"]:
            recs.append(a)
    recs.sort(key=lambda a: (a["activated_min"], a["unit"]))
    by_unit = {}
    for a in recs:
        by_unit.setdefault(a["unit"], []).append(a)

    # ---- resolve world events that need routes (closure / accident location from a target vehicle's base path)
    def base_leg(rec, phase):
        if phase == "to_scene":
            t0 = rec["depart_min"] * 60 + OFFSET
            return t0, (rec["arrives_min"] - rec["depart_min"]) * 60, rec["from"], rec["scene"]
        t_leave = (rec["arrives_min"] + rec["scene_min"]) * 60 + OFFSET
        return t_leave, rec["trans_min"] * 60, rec["scene"], rec["dest"]

    def target_rec(tg):
        for a in log[tg["call"]]["assignments"]:
            if a["role"] == tg["role"] and not a.get("superseded") and not a.get("stood_down_at_min"):
                return a
        return None

    for w in wev:
        if w["type"] in ("closure", "accident"):
            rec = target_rec(w["target"])
            t0, dur, pf, pt = base_leg(rec, w["target"]["phase"])
            r = route(pf, pt)
            when = t0 + dur * w["target"]["when"]
            ctr = point_at_dist(r["path"], path_len_m(r["path"]) * w["target"]["where"])
            obj = {"id": w["id"], "lat": ctr[0], "lon": ctr[1], "r": w["radius_m"], "t0": when, "t1": when + w["duration_min"] * 60,
                   "title_sl": w.get("title_sl", ""), "title_en": w.get("title_en", ""), "kind": w["type"], "delay_s": w.get("delay_min", 0) * 60, "target_unit": rec["unit"]}
            (closures if w["type"] == "closure" else accidents).append(obj)
        else:
            others.append(w)

    # ---- hospital distribution after the scene report: UKC takes what its capacity allows, the rest goes to SB Celje (synthetic capacity)
    for cid_, o_ in log.items():
        sr_ = o_.get("scene_report")
        if not sr_:
            continue
        cap = {"red": 3, "yellow": 6}
        nrv = sorted([a for a in o_["assignments"] if a["kind"] in ("NRV", "PAMB") and not a.get("superseded") and not a.get("stood_down_at_min")], key=lambda a: a["arrives_min"])
        act = sr_["actual"]
        reds, yels = nrv[:act["red"]], nrv[act["red"]:act["red"] + act["yellow"]]
        over = reds[cap["red"]:] + yels[cap["yellow"]:]
        cel = hosp["celje"]
        for a in over:
            a["dest"] = [cel["lat"], cel["lon"]]
            a["dest_id"] = "celje"
            a["trans_min"] = round(hav_km(a["scene"], a["dest"]) * ROAD / (a["speed_kmh"]) * 60, 2)
            a["note"] += " | overflow: patient goes to SB Celje (UKC capacity)"
    # ---- unit runs
    runs = []
    last_track = {}
    fuel_km = {}
    for unit, lst in by_unit.items():
        prev_end_track = None
        for i, rec in enumerate(lst):
            nxt = lst[i + 1] if i + 1 < len(lst) else None
            run = build_run(S, scen, rec, nxt, prev_end_track, closures, accidents, hosp, meta)
            runs.append(run)
            prev_end_track = run["track"]
            fuel_km[unit] = fuel_km.get(unit, 0) + run["km"]
    # ---- helicopter
    heli = None
    for o in scen["dispatch_log"]:
        if o.get("helicopter", {}).get("launched"):
            heli = build_heli(S, scen, calls[o["call"]], o, [r for r in runs if r["rec"]["call_id"] == o["call"]], hosp)
    # ---- breakdowns, priority changes (need free-unit search over built runs)
    extra_runs = []
    for w in others:
        if w["type"] == "breakdown":
            extra_runs += do_breakdown(S, scen, w, runs, fleet0, closures, accidents, hosp)
        elif w["type"] == "priority_change":
            extra_runs += do_priority_change(S, scen, w, runs, fleet0, calls, closures, accidents, hosp)
    all_runs = runs + extra_runs
    return S, all_runs, heli, closures, accidents, others, fuel_km


def build_run(S, scen, rec, nxt, prev_track, closures, accidents, hosp, meta, replacement_for=None, scene_s_override=None, t_force=None):
    u = rec["unit"]
    t_act = rec["activated_min"] * 60 + OFFSET
    acc = 6 + h8(u, rec["call_id"]) % 10
    t_dep = max(rec["depart_min"] * 60 + OFFSET, t_act + acc)
    start = tuple(rec["from"])
    if prev_track and rec.get("diverted_from_other_job") and prev_track[-1][0] >= t_act - 1:
        start = pos_at(prev_track, t_act)
    dur1 = max(60.0, (rec["arrives_min"] - rec["depart_min"]) * 60)
    scene = tuple(rec["scene"])
    # cut-off times: taken off for a red call, or stood down
    cut = None
    if rec.get("superseded"):
        cut = nxt["activated_min"] * 60 + OFFSET if nxt else None
        # find the superseding assignment time: first later assignment of this unit
    if rec.get("stood_down_at_min") is not None:
        cut = rec["stood_down_at_min"] * 60 + OFFSET
    leg1 = make_leg(start, scene, t_dep, dur1, closures, accidents) if (cut is None or cut > t_dep) else {"track": [[round(t_dep, 1), round(start[0], 5), round(start[1], 5)]], "events": [], "t_end": t_dep, "src": "none"}
    track = leg1["track"]
    events = list(leg1["events"])
    run = {"rec": rec, "unit": u, "role": rec["role"], "t_act": t_act, "t_acc": t_act + acc, "t_dep": t_dep, "events": events, "replacement_for": replacement_for, "statuses": []}
    run["statuses"].append((t_act + acc, "SPREJETO"))
    if cut is not None and cut <= leg1["t_end"]:
        pos = pos_at(track, cut)
        track = [p for p in track if p[0] < cut] + [[round(cut, 1), round(pos[0], 5), round(pos[1], 5)]]
        run.update({"track": track, "t_end": cut, "cut": cut, "cut_kind": "stand_down" if rec.get("stood_down_at_min") is not None else "diverted", "cut_pos": pos,
                    "km": path_len_m([(p[1], p[2]) for p in track]) / 1000})
        if t_dep < cut:
            run["statuses"].append((t_dep, "NA POTI"))
        run["t_arr"] = None
        run["t_prost"] = cut if rec.get("stood_down_at_min") is not None else None
        return run
    run["statuses"].append((t_dep, "NA POTI"))
    t_arr = leg1["t_end"]
    run["statuses"].append((t_arr, "NA KRAJU"))
    contact = t_arr + (90 if rec["role"] != "doctor" else 60)
    run["statuses"].append((contact, "PRI PACIENTU" if rec["role"] != "van" else "PRI PACIENTU"))
    scene_s = (scene_s_override if scene_s_override is not None else rec["scene_min"] * 60)
    t_leave = t_arr + scene_s
    run.update({"t_arr": t_arr, "t_contact": contact, "t_leave": t_leave, "scene": scene})
    if rec["trans_min"] == 0:  # doctor on a yellow call: done at the scene
        t_prost = t_leave + 5 * 60
        run["statuses"] += [(t_leave, "ZAKLJUČEK INT"), (t_prost, "PROST")]
        track.append([round(t_prost, 1), round(scene[0], 5), round(scene[1], 5)])
        run.update({"track": track, "t_end": t_prost, "t_prost": t_prost, "t_hosp": None, "dest": None, "events": events + [], "km": path_len_m([(p[1], p[2]) for p in track]) / 1000})
        return run
    dest = tuple(rec["dest"])
    trans = rec["trans_min"] * 60
    track.append([round(t_leave, 1), round(scene[0], 5), round(scene[1], 5)])
    leg2 = make_leg(scene, dest, t_leave, trans, closures, accidents)
    track += leg2["track"][1:] if leg2["track"] and track[-1][0] == leg2["track"][0][0] else leg2["track"]
    events += leg2["events"]
    t_hosp = leg2["t_end"]
    run["statuses"] += [(t_leave, "S KRAJA"), (t_hosp, "NA CILJU"), (t_hosp + 120, "PREDAJA PACIENTA"), (t_hosp + rec["handover_min"] * 60, "ZAKLJUČEK INT"),
                        (t_hosp + rec["handover_min"] * 60, "ČIŠČENJE")]
    t_prost = t_hosp + (rec["handover_min"] + rec["turnaround_min"]) * 60
    run["statuses"].append((t_prost, "PROST"))
    track.append([round(t_prost, 1), round(dest[0], 5), round(dest[1], 5)])
    run.update({"track": track, "t_end": t_prost, "t_prost": t_prost, "t_hosp": t_hosp, "dest": dest, "km": path_len_m([(p[1], p[2]) for p in track]) / 1000, "leg2_t0": t_leave})
    return run


def build_heli(S, scen, call, o, ground_runs, hosp):
    brnik = (46.2237, 14.4576)
    scene = (call["lat"], call["lon"])
    ukc = (hosp["ukc"]["lat"], hosp["ukc"]["lon"])
    t0 = o["t"] * 60 + OFFSET
    d1 = hav_km(brnik, scene)
    fly1 = d1 / 200.0 * 3600
    t_takeoff = t0 + 13 * 60
    t_land = t_takeoff + fly1 + 120
    t_contact = t_land + 120
    t_leave = t_contact + 8 * 60
    d2 = hav_km(scene, ukc)
    fly2 = d2 / 200.0 * 3600
    t_hosp = t_leave + fly2 + 120
    t_back = t_hosp + 12 * 60 + d2 * 0 + hav_km(ukc, brnik) / 200.0 * 3600
    track = [[round(t0, 1), brnik[0], brnik[1]], [round(t_takeoff, 1), brnik[0], brnik[1]], [round(t_takeoff + fly1, 1), scene[0], scene[1]], [round(t_leave, 1), scene[0], scene[1]],
             [round(t_leave + fly2, 1), ukc[0], ukc[1]], [round(t_hosp + 12 * 60, 1), ukc[0], ukc[1]], [round(t_back, 1), brnik[0], brnik[1]]]
    st = [(t0 + 10, "SPREJETO"), (t0 + 9 * 60, "PRIHOD DO HELIKOPTERJA"), (t_takeoff, "VZLET"), (t_land, "NA KRAJU"), (t_contact, "PRI PACIENTU"), (t_leave, "S KRAJA"),
          (t_hosp, "NA CILJU"), (t_hosp + 120, "PREDAJA PACIENTA"), (t_hosp + 12 * 60, "ZAKLJUČEK INT"), (t_back, "VRNITEV V BAZO")]
    heli = {"unit": "H1", "t_act": t0, "statuses": st, "track": track, "t_land": t_land, "t_contact": t_contact, "t_leave": t_leave, "t_hosp": t_hosp, "scene": scene, "dest": ukc, "call": call["id"],
            "km": (d1 + d2 + hav_km(ukc, brnik))}
    # ground units hand over to the helicopter crew: they stay at the scene until take-off, then are free
    for r in ground_runs:
        if r.get("t_leave") and r["t_leave"] > t_land and r["rec"]["role"] in ("ambulance", "doctor"):
            sc = r["scene"]
            r["statuses"] = [s for s in r["statuses"] if s[1] in ("SPREJETO", "NA POTI", "NA KRAJU", "PRI PACIENTU")] + [(t_leave, "ZAKLJUČEK INT"), (t_leave + 60, "PROST")]
            r["track"] = [p for p in r["track"] if p[0] <= r["t_arr"]] + [[round(t_leave + 60, 1), round(sc[0], 5), round(sc[1], 5)]]
            r["t_leave"], r["t_hosp"], r["t_prost"], r["t_end"], r["dest"] = t_leave, None, t_leave + 60, t_leave + 60, None
            r["handed_to_heli"] = True
            r["events"] = [e for e in r["events"] if e["t"] < r["t_arr"]]
    return heli


def find_free(kind_set, area_set, pos, tb, runs, fleet0, exclude=()):
    best = None
    for uid, u in fleet0.items():
        if u["kind"] not in kind_set or u["area"] not in area_set or not u["ok"] or uid in exclude:
            continue
        busy_until = u["free_at_min"] * 60 + OFFSET if u["state"] in ("non-urgent", "cleaning") else 0
        p = (u["lat"], u["lon"])
        ur = [r for r in runs if r["unit"] == uid]
        conflict = False
        for r in ur:
            end = r.get("t_prost") or r["t_end"]
            if r["t_act"] - 60 <= tb <= end + 1:
                conflict = True
            elif end <= tb:
                busy_until = max(busy_until, end)
                p = tuple(r["dest"]) if r.get("dest") else (r["scene"] if r.get("scene") else p)
            elif tb < r["t_act"] < tb + 2400:
                conflict = True  # the unit is booked for a later call that the replacement job would overlap
        if conflict or busy_until > tb:
            continue
        d = hav_km(p, pos)
        if best is None or d < best[0]:
            best = (d, uid, p, u)
    return best


def do_breakdown(S, scen, w, runs, fleet0, closures, accidents, hosp):
    tg = w["target"]
    cand = [r for r in runs if r["rec"]["call_id"] == tg["call"] and r["rec"]["role"] == tg["role"] and r.get("t_hosp") and not r.get("cut")]
    if not cand:
        return []
    r = cand[0]
    t0, t1 = r["t_leave"], r["t_hosp"]
    tb = t0 + (t1 - t0) * tg["when"]
    P = pos_at(r["track"], tb)
    broken = r["unit"]
    r["track"] = [p for p in r["track"] if p[0] < tb] + [[round(tb, 1), round(P[0], 5), round(P[1], 5)]]
    r["statuses"] = [s for s in r["statuses"] if s[0] <= tb] + [(tb, "OKVARA")]
    r["breakdown"] = {"t": tb, "at": fmt_pt(P), "title_sl": w.get("title_sl"), "title_en": w.get("title_en")}
    r["t_hosp"], r["t_prost"], r["t_end"], r["dest"] = None, None, tb, None
    r["events"] = [e for e in r["events"] if e["t"] < tb]
    fb = find_free({"NRV"}, {"LJ", "NG"}, P, tb + 30, runs, fleet0, exclude={broken})
    if not fb:
        return []
    d, uid, p0, u = fb
    rec0 = r["rec"]
    prio = rec0["prio"]
    sp = rec0["speed_kmh"]
    drive = hav_km(p0, P) * ROAD / sp * 3600
    t_act = tb + 20
    rec = {"unit": uid, "kind": "NRV", "role": "ambulance", "org": u["org"], "base": u["base"], "area": u["area"], "eta_min": round((drive + 60) / 60, 1), "arrives_min": round((t_act - OFFSET + 60 + drive) / 60, 2),
           "free_again_min": 0, "diverted_from_other_job": False, "note": f"replacement for {broken} (breakdown with patient aboard)", "call_id": rec0["call_id"], "prio": prio,
           "activated_min": round((t_act - OFFSET) / 60, 2), "from": [round(p0[0], 5), round(p0[1], 5)], "position_at_activation": [round(p0[0], 5), round(p0[1], 5)],
           "depart_min": round((t_act - OFFSET + 60) / 60, 2), "scene": [round(P[0], 5), round(P[1], 5)], "dest": rec0["dest"], "dest_id": rec0["dest_id"], "scene_min": 3.0,
           "trans_min": round(hav_km(P, rec0["dest"]) * ROAD / sp * 60, 2), "handover_min": rec0["handover_min"], "turnaround_min": rec0["turnaround_min"], "exit_min": 1.0,
           "private_lead_min": 0.0, "speed_kmh": sp, "weather_factor": rec0["weather_factor"], "traffic_factor": rec0["traffic_factor"], "fuel_note": "ok"}
    nr = build_run(S, scen, rec, None, None, closures, accidents, hosp, None, replacement_for=broken, scene_s_override=180)
    nr["rec"]["scene"] = rec["scene"]
    return [nr]


def do_priority_change(S, scen, w, runs, fleet0, calls, closures, accidents, hosp):
    c = calls[w["call"]]
    tchg = w["t_min"] * 60 + OFFSET
    scene = (c["lat"], c["lon"])
    fb = find_free({"VUZ"}, {"LJ", "NG"}, scene, tchg + 30, runs, fleet0)
    amb = [r for r in runs if r["rec"]["call_id"] == w["call"] and r["rec"]["role"] == "ambulance"]
    if not fb or not amb:
        return []
    d, uid, p0, u = fb
    sp = amb[0]["rec"]["speed_kmh"] * 1.3
    drive = hav_km(p0, scene) * ROAD / sp * 3600
    t_act = tchg + 20
    dest = amb[0]["rec"]["dest"]
    follow = amb[0].get("t_leave") and (t_act + 300 + drive) > amb[0]["t_leave"]
    tgt = dest if follow else [round(scene[0], 5), round(scene[1], 5)]
    rec = {"unit": uid, "kind": "VUZ", "role": "doctor", "org": u["org"], "base": u["base"], "area": u["area"], "eta_min": round((drive + 300) / 60, 1), "arrives_min": round((t_act - OFFSET + 300 + drive) / 60, 2),
           "free_again_min": 0, "diverted_from_other_job": False, "note": "doctor vehicle added after the priority change", "call_id": w["call"], "prio": "red", "activated_min": round((t_act - OFFSET) / 60, 2),
           "from": [round(p0[0], 5), round(p0[1], 5)], "position_at_activation": [round(p0[0], 5), round(p0[1], 5)], "depart_min": round((t_act - OFFSET + 300) / 60, 2),
           "scene": tgt, "dest": dest, "dest_id": amb[0]["rec"]["dest_id"], "scene_min": 6.0, "trans_min": 0.0, "handover_min": 0.0, "turnaround_min": 0.0, "exit_min": 5.0,
           "private_lead_min": 0.0, "speed_kmh": round(sp, 1), "weather_factor": 1.0, "traffic_factor": 1.0, "fuel_note": "ok"}
    nr = build_run(S, scen, rec, None, None, closures, accidents, hosp, None)
    nr["followed_to_hospital"] = bool(follow)
    return [nr]


def _save_cache_hook():
    json.dump(_cache, open(CACHE, "w", encoding="utf-8"))
