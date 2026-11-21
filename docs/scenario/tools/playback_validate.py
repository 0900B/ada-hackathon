import json
import os, math, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
D = REPO + "/docs/scenario/reference_runs"
CHAIN = ["SPREJETO", "NA POTI", "NA KRAJU", "PRI PACIENTU", "S KRAJA", "NA CILJU", "PREDAJA PACIENTA", "ZAKLJUČEK INT", "ČIŠČENJE", "PROST"]
VIS = {"dispatch", "er", "crew", "map"}


def hav_km(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(x))


problems = 0
tot = {"events": 0, "vehicles": 0, "patients": 0}
for f in sorted(os.listdir(D)):
    if not f.endswith(".json") or f == "index.json":
        continue
    d = json.load(open(os.path.join(D, f), encoding="utf-8"))
    sid = d["scenario"]
    msgs = []
    ev = d["events"]
    tot["events"] += len(ev)
    tot["vehicles"] += len(d["vehicles"])
    tot["patients"] += len(d["patients"])
    if any(ev[i]["t_s"] > ev[i + 1]["t_s"] for i in range(len(ev) - 1)):
        msgs.append("events not sorted")
    if [e["seq"] for e in ev] != list(range(1, len(ev) + 1)):
        msgs.append("seq not 1..n")
    if any(e["t_s"] < 0 for e in ev):
        msgs.append("negative t_s")
    for e in ev:
        if not set(e["visible_on"]) <= VIS or not e["visible_on"]:
            msgs.append("bad visible_on " + e["type"])
            break
    # vehicles
    for uid, v in d["vehicles"].items():
        tr = v["track"]
        if any(tr[i][0] > tr[i + 1][0] + 1e-6 for i in range(len(tr) - 1)):
            msgs.append(f"{uid} track times go backwards")
        speeds = []
        teleports = 0
        for i in range(len(tr) - 1):
            dt = tr[i + 1][0] - tr[i][0]
            dist = hav_km(tr[i][1:], tr[i + 1][1:]) * 1000
            if dt <= 0.5 and dist > 150:
                teleports += 1
            elif dt > 5:
                speeds.append(dist / dt * 3.6)
        if v["role"] != "helicopter" and speeds and max(speeds) > 160:
            msgs.append(f"{uid} speed {max(speeds):.0f} km/h")
        if teleports:
            msgs.append(f"{uid} teleports {teleports}")
        st = [s["status"] for s in v["statuses"]]
        # each run's statuses must follow the chain order
        idx = [CHAIN.index(s) for s in st if s in CHAIN]
        # statuses of several runs concatenate; check monotonic inside a run: split at SPREJETO
        runs, cur = [], []
        for s in st:
            if s == "SPREJETO" and cur:
                runs.append(cur)
                cur = []
            cur.append(s)
        runs.append(cur)
        for r in runs:
            ids = [CHAIN.index(s) for s in r if s in CHAIN]
            if ids != sorted(ids):
                msgs.append(f"{uid} status order {r}")
        if v["fuel"]["end_pct"] is not None and v["fuel"]["end_pct"] < 0:
            msgs.append(f"{uid} negative fuel")
    # patients
    types = d["summary"]["event_types"]
    for pid, p in d["patients"].items():
        for u in p["carried_by"]:
            if u not in d["vehicles"]:
                msgs.append(f"{pid} carrier {u} missing")
        if p["severity"] != "green":
            if not any(e["type"] == "voice_entry" and e.get("patient") == pid for e in ev):
                msgs.append(f"{pid} no voice entries")
            if not any(e["type"] == "record_signed" and e.get("patient") == pid for e in ev):
                msgs.append(f"{pid} not signed")
    n_tri = sum(1 for e in ev if e["type"] == "triage_set")
    if n_tri != len(d["calls"]):
        msgs.append(f"triage_set {n_tri} != calls {len(d['calls'])}")
    ids = {r["id"] for r in d["world"]["road_events"]}
    for e in ev:
        if e["type"] == "reroute":
            if e["data"]["closure"] not in ids:
                msgs.append("reroute unknown closure")
            if e["data"]["delta_s"] <= 0:
                msgs.append("reroute with no extra time")
    # unit_status for every vehicle appears in events
    n_status = sum(1 for e in ev if e["type"] == "unit_status")
    n_status_v = sum(len(v["statuses"]) for v in d["vehicles"].values())
    if n_status < n_status_v:
        msgs.append(f"status events {n_status} < vehicle statuses {n_status_v}")
    print(f"{sid:5s} events {len(ev):4d} vehicles {len(d['vehicles']):2d} patients {len(d['patients']):2d} reroutes {types.get('reroute', 0):2d} breakdown {types.get('unit_breakdown', 0)} stand_down {types.get('unit_stand_down', 0)} "
          f"human {d['summary']['human_steps']:2d} -> {'OK' if not msgs else 'PROBLEMS'}")
    for m in msgs[:8]:
        print("    ", m)
    problems += len(msgs)
print("TOTAL", tot, "problems", problems)
