"""Replay a simulation script and print what each dashboard would receive.

Usage (from the repository root):
  python docs/scenario/tools/replay.py D12                      # everything, no waiting
  python docs/scenario/tools/replay.py D12 --dashboard er       # only what the ER dashboard sees
  python docs/scenario/tools/replay.py D12 --dashboard crew --unit A04
  python docs/scenario/tools/replay.py D12 --speed 30           # play in real time, 30 times faster
  python docs/scenario/tools/replay.py D12 --positions 60       # also print every unit's position each 60 s (from the track)
  python docs/scenario/tools/replay.py D12 --json               # raw event JSON lines, for piping into a dashboard
  python docs/scenario/tools/replay.py D12 --script             # the INPUT script (what the world and people do, no vehicle decisions)

By default this replays a reference run (a stand-in dispatcher's output). With --script it shows the input script instead.

Every dashboard reads the same ordered stream and filters by `visible_on`, which is what keeps them in sync.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
PLAY = os.path.join(HERE, "..", "reference_runs")
SCRIPTS = os.path.join(HERE, "..", "scripts")


def pos_at(track, t):
    if t < track[0][0] or t > track[-1][0]:
        return None
    for i in range(len(track) - 1):
        a, b = track[i], track[i + 1]
        if a[0] <= t <= b[0]:
            f = 0 if b[0] == a[0] else (t - a[0]) / (b[0] - a[0])
            return a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f
    return track[-1][1], track[-1][2]


def brief(e):
    d = e.get("data", {})
    for k in ("status", "text", "transcript_sl", "title_en", "message_sl", "caller_text_sl", "problem", "update", "reason"):
        if d.get(k):
            return str(d[k])[:110]
    return ""


def show_script(a):
    path = a.scenario if os.path.exists(a.scenario) else os.path.join(SCRIPTS, a.scenario + ".json")
    d = json.load(open(path, encoding="utf-8"))
    print(f'{d["scenario"]}: {d["name"]}  ({d["date"]} {d["start_local"]}, {d["shift"]} roster)')
    print(f'fleet at the start: {len(d["fleet"])} units, patients: {len(d["patients"])}, no vehicle is assigned in this file')
    t0 = time.time()
    for e in d["timeline"]:
        if a.speed:
            wait = e["t_s"] / a.speed - (time.time() - t0)
            if wait > 0:
                time.sleep(wait)
        x = e["data"]
        txt = x.get("caller_text_sl") or x.get("text") or x.get("title_en") or x.get("problem") or ""
        print(f'[{e["clock"]}] {e["type"]:28s} {x.get("call", ""):8s} {"HUMAN " if "human" in e["source"] else ""}{str(txt)[:100]}')
    for c in d["conditional_events"]:
        print(f'[when {json.dumps(c["trigger"], ensure_ascii=False)}] {c["type"]}')
        for st in c.get("steps", []):
            print(f'      +{st["after_s"]}s {st["type"]} {"HUMAN" if st.get("human") else ""}')
    for p in d["patients"][:3 if not a.json else None]:
        print(f'patient {p["id"]} ({p["severity"]}, {p["category"]}): {len(p["voice_entries"])} voice entries, anchored to the care episode')
        for v in p["voice_entries"]:
            print(f'      {v["anchor"]:11s} +{v["offset_s"]:>4}s  {v["transcript_sl"][:90]}')
    if len(d["patients"]) > 3 and not a.json:
        print(f'... {len(d["patients"]) - 3} more patients (use --json to print them all)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--dashboard", choices=["all", "dispatch", "er", "crew", "map"], default="all")
    ap.add_argument("--unit")
    ap.add_argument("--speed", type=float, default=0.0, help="0 = print at once; otherwise simulated seconds per real second")
    ap.add_argument("--positions", type=float, default=0.0, help="print unit positions every N simulated seconds")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--script", action="store_true", help="show the input script (timeline, conditional events, patient entries) instead of a reference run")
    a = ap.parse_args()
    if a.script:
        return show_script(a)
    path = a.scenario if os.path.exists(a.scenario) else os.path.join(PLAY, a.scenario + ".json")
    d = json.load(open(path, encoding="utf-8"))
    evs = [e for e in d["events"] if a.dashboard == "all" or a.dashboard in e["visible_on"]]
    if a.unit:
        evs = [e for e in evs if e.get("unit") in (None, a.unit)]
    stream = [(e["t_s"], 0, e) for e in evs]
    if a.positions:
        t = 0.0
        while t <= d["clock"]["end_t_s"]:
            for uid, v in d["vehicles"].items():
                if a.unit and uid != a.unit:
                    continue
                p = pos_at(v["track"], t)
                if p:
                    stream.append((t, 1, {"type": "unit_position", "unit": uid, "t_s": t, "clock": (datetime.fromisoformat(d["clock"]["origin_iso"]) + timedelta(seconds=t)).strftime("%H:%M:%S"), "data": {"lat": round(p[0], 5), "lon": round(p[1], 5)}, "visible_on": ["map", "dispatch"]}))
            t += a.positions
    stream.sort(key=lambda x: (x[0], x[1]))
    t0 = time.time()
    for t, _, e in stream:
        if a.speed:
            wait = t / a.speed - (time.time() - t0)
            if wait > 0:
                time.sleep(wait)
        if a.json:
            print(json.dumps(e, ensure_ascii=False))
        else:
            print(f'[{e.get("clock", "")}] {e["type"]:22s} {e.get("unit", ""):5s} {(e.get("patient") or "")[-6:]:7s} {"HUMAN " if e.get("human") else ""}{brief(e)}')


if __name__ == "__main__":
    main()
