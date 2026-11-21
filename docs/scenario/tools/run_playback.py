import json, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playback_gen as G
from playback_emit import assemble

ids = sys.argv[1:]
data = json.load(open(G.SC, encoding="utf-8"))
os.makedirs(G.OUTDIR, exist_ok=True)


def pretty(out):
    lines = ["{"]
    keys = list(out.keys())
    for i, k in enumerate(keys):
        v = out[k]
        comma = "," if i < len(keys) - 1 else ""
        c = lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":"))
        if k == "events":
            lines.append(f'"{k}": [')
            lines += [c(e) + ("," if j < len(v) - 1 else "") for j, e in enumerate(v)]
            lines.append("]" + comma)
        elif k in ("vehicles", "patients") and isinstance(v, dict):
            lines.append(f'"{k}": {{')
            items = list(v.items())
            lines += [f'{c(kk)}: {c(vv)}' + ("," if j < len(items) - 1 else "") for j, (kk, vv) in enumerate(items)]
            lines.append("}" + comma)
        else:
            lines.append(f'"{k}": {c(v)}{comma}')
    lines.append("}")
    return "\n".join(lines)


summary = []
for scen in data["scenarios"]:
    if ids and scen["id"] not in ids:
        continue
    print("building", scen["id"], flush=True)
    out = assemble(scen)
    path = os.path.join(G.OUTDIR, scen["id"] + ".json")
    open(path, "w", encoding="utf-8").write(pretty(out))
    G._save_cache_hook()
    s = out["summary"]
    print(f'  {scen["id"]}: vehicles {s["vehicles"]} patients {s["patients"]} events {s["events"]} voice {s["voice_entries"]} reroutes {s["reroutes"]} human steps {s["human_steps"]} size {os.path.getsize(path)//1024} KB', flush=True)
    summary.append({"scenario": scen["id"], "name": scen["name"], "file": scen["id"] + ".json", **s})
print("osrm stats:", G._stats)
if not ids:
    json.dump({"format": "adahack-reference-run/1", "scenarios": summary}, open(os.path.join(G.OUTDIR, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
