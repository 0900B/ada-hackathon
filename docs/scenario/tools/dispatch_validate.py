import json
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, REPO + "/backend")
from pydantic import TypeAdapter
from app.models import OperatorEvent
ta = TypeAdapter(OperatorEvent)
d = json.load(open(REPO + "/docs/scenario/dispatch_scenarios.json", encoding="utf-8"))
n = bad = 0
for s in d["scenarios"]:
    for e in s["engine_events"]:
        n += 1
        try:
            ta.validate_python(e["payload"])
        except Exception as ex:
            bad += 1
            print("INVALID", s["id"], e["call"], str(ex)[:200])
print("engine payloads checked:", n, "invalid:", bad)
# consistency checks
for s in d["scenarios"]:
    exp = s["expected"]
    need = exp["units_needed_by_rule"]
    disp = exp["units_dispatched"]
    sum_need = need["NRV"] + need["VUZ"] + need["VAN"]
    us = exp["units_sent"]
    sum_sent = sum(len(v) for k, v in us.items() if k != "helicopter")
    assert exp["assignments_made"] == sum_need, (s["id"], exp["assignments_made"], sum_need)
    assert sum_sent == exp["assignments_made"] - exp["units_reused_after_finishing"], s["id"]
    ids = [u for k, v in us.items() for u in v]
    assert len(ids) == len(set(ids)), s["id"]
    assert all(c["id"].startswith(s["id"]) for c in s["calls"]), s["id"]
    for o in s["dispatch_log"]:
        ids = [a["unit"] for a in o["assignments"]]
        assert len(ids) == len(set(ids)) or any("re-planned" in a["note"] for a in o["assignments"]), (s["id"], o["call"], ids)
print("consistency ok")
