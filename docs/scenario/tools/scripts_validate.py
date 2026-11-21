"""Check the input scripts: structure, order, and that no dispatch decision has leaked in. Run from the repository root."""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
D = REPO + "/docs/scenario/scripts"
FORBIDDEN_KEYS = {"unit", "units", "assignments", "assigned_to", "track", "path", "eta", "eta_min", "eta_t_s", "statuses", "status_chain", "carried_by", "vehicle", "vehicles", "arrives", "arrival_t_s", "runs"}
UNIT_ID = re.compile(r"(?<![\w-])(A\d{2}|D\d{2}|T\d{2}|PA\d{2}|PT\d{2})(?![\w-])")
STATUS = {"free", "busy_with_scheduled_transport", "cleaning", "not_available_low_fuel", "available", "not_available"}


def walk(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield path + "/" + k, k, v
            yield from walk(v, path + "/" + k)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from walk(v, path + f"[{i}]")


problems = 0
for f in sorted(os.listdir(D)):
    if not f.endswith(".json") or f == "index.json":
        continue
    d = json.load(open(os.path.join(D, f), encoding="utf-8"))
    sid = d["scenario"]
    msgs = []
    # no decisions outside the fleet (the resources are inputs)
    for name in ("timeline", "conditional_events", "patients", "world", "rules", "clock"):
        for pth, k, v in walk(d[name], name):
            if k in FORBIDDEN_KEYS:
                msgs.append(f"forbidden key {pth}")
        blob = json.dumps(d[name], ensure_ascii=False)
        m = UNIT_ID.search(blob)
        if m:
            msgs.append(f"unit id {m.group(0)} in {name}")
    tl = d["timeline"]
    if any(tl[i]["t_s"] > tl[i + 1]["t_s"] for i in range(len(tl) - 1)):
        msgs.append("timeline not sorted")
    calls = {e["data"]["call"]: e for e in tl if e["type"] == "call_received"}
    for e in tl:
        if e["type"] == "triage":
            c = e["data"]["call"]
            if c not in calls or calls[c]["t_s"] >= e["t_s"]:
                msgs.append(f"triage of {c} not after its call")
    for c, e in calls.items():
        if not any(x["type"] == "triage" and x["data"]["call"] == c for x in tl) and not any(x["type"] == "duplicate_call" and x["data"]["call"] == c for x in tl):
            msgs.append(f"{c} has no triage")
    ids = [u["id"] for u in d["fleet"]]
    if len(ids) != len(set(ids)):
        msgs.append("duplicate fleet ids")
    for u in d["fleet"]:
        if u["status"] not in STATUS:
            msgs.append(f"fleet status {u['status']}")
    pids = {p["id"] for p in d["patients"]}
    if len(pids) != len(d["patients"]):
        msgs.append("duplicate patient ids")
    call_ids = {c for c in calls if not any(x["type"] == "duplicate_call" and x["data"]["call"] == c and x["t_s"] == calls[c]["t_s"] for x in tl)}
    for p in d["patients"]:
        eids = [e["id"] for e in p["voice_entries"]]
        if len(eids) != len(set(eids)):
            msgs.append(f"{p['id']} duplicate entry ids")
        for e in p["voice_entries"]:
            if e["corrects"] and e["corrects"] not in eids:
                msgs.append(f"{e['id']} corrects unknown entry")
            if e["needs_correction"] and not any(o["corrects"] == e["id"] for o in p["voice_entries"]):
                msgs.append(f"{e['id']} needs a correction but none follows")
            if e["anchor"] not in ("at_patient", "left_scene", "at_hospital"):
                msgs.append(f"{e['id']} bad anchor")
        if p["call"] not in {e["data"]["call"] for e in tl if e["type"] == "call_received"}:
            msgs.append(f"{p['id']} unknown call")
        if isinstance(p["appears"], dict) and not any(c["type"] == "scene_report_sequence" for c in d["conditional_events"]):
            msgs.append(f"{p['id']} waits for a scene report that does not exist")
    for c in d["conditional_events"]:
        tr = c["trigger"]
        if "carrier_of_patient" in tr and tr["carrier_of_patient"] not in pids:
            msgs.append(f"{c['id']} unknown patient")
    starts = {e["data"]["id"]: e["t_s"] for e in tl if e["type"] == "road_event"}
    ends = {e["data"]["id"]: e["t_s"] for e in tl if e["type"] == "road_event_end"}
    for k, t in starts.items():
        if k not in ends or ends[k] <= t:
            msgs.append(f"road event {k} has no later end")
    s = d["summary"]
    print(f"{sid:5s} timeline {len(tl):3d} conditional {len(d['conditional_events'])} patients {len(d['patients']):2d} fleet {len(d['fleet']):2d} voice {s['voice_entries']:3d} -> {'OK' if not msgs else 'PROBLEMS'}")
    for m in msgs[:8]:
        print("    ", m)
    problems += len(msgs)
print("problems", problems)
