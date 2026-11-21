"""Build the INPUT scripts (docs/scenario/scripts/Dxx.json): what the outside world and the people do, with no dispatch decisions.

A script has the starting fleet (resources), the calls, the dispatcher's simulated triage, road events, hospital reports, data-feed problems,
the patients with their monitor feed and the paramedic's voice entries (anchored to the care episode, not to a vehicle), and a few conditional events.
It does NOT say which vehicle takes a call, how long it needs, which path it drives or what its statuses are: the model decides that.
Run from the repository root: python docs/scenario/tools/make_input_scripts.py
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pb_templates import TEMPLATES  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SC = REPO + "/docs/scenario/dispatch_scenarios.json"
REF = REPO + "/docs/scenario/reference_runs"
OUT = REPO + "/docs/scenario/scripts"
OFFSET = 120
ANCHOR = {"scene": "at_patient", "transport": "left_scene", "arrival": "at_hospital"}
ROLE = {"NRV": "ambulance", "VUZ": "doctor_vehicle", "VAN": "sanitary_van", "PAMB": "private_ambulance", "PVAN": "private_van"}
AREA = {"LJ": "ljubljana_emergency_area", "NG": "other_region", "PRIV": "private_provider"}


def h8(*a):
    import hashlib
    return int(hashlib.sha1("|".join(map(str, a)).encode()).hexdigest()[:8], 16)


def clock(scen, t):
    from datetime import datetime, timedelta
    h, m = (int(x) for x in scen["start_local"].split(":"))
    dt = datetime.fromisoformat(f'{scen["date"]}T{h:02d}:{m:02d}:00') + timedelta(seconds=t - OFFSET)
    return dt.isoformat() + "+01:00"


def build(scen, ref):
    calls = {c["id"]: c for c in scen["calls"]}
    log = {o["call"]: o for o in scen["dispatch_log"]}
    tl = []

    def ev(t, typ, source, **data):
        tl.append({"t_s": round(t, 1), "clock": clock(scen, t)[11:19], "type": typ, "source": source, "data": data})

    # ---- calls and the dispatcher's simulated triage
    for cid, c in calls.items():
        t0 = log[cid]["t"] * 60 + OFFSET
        red = any(p["sev"] == "red" for p in c["patients"])
        lead = 70 if red else 95
        ev(t0 - lead, "call_received", "caller", call=cid, caller_text_sl=c["caller_text_sl"], channel="112 via ReCO", lat=c["lat"], lon=c["lon"], place=c["place_name"])
        ev(t0 - lead + (50 if red else 75), "triage", "dispatcher (human, simulated)", call=cid, priority="red" if red else "yellow", problem=c["problem"],
           patients_estimated=c["patients"], doctor_needed=c.get("doctors", 0) > 0, first_responders=bool(c.get("first_responders")), fire=bool(c.get("fire")), police=bool(c.get("police")),
           helicopter_requested=bool(c.get("air")), suspected_mass_casualty=bool(c.get("mci")),
           note="the one mandatory human step; the units are NOT part of this event")
    # ---- scheduled (non-urgent) transport requests
    for b in scen["non_urgent_batches"]:
        ev(b["t"] * 60 + OFFSET, "scheduled_transport_requests", "booking system", count=b["n"], note="the model decides who takes them (public units or private vans)")
    # ---- world events from the scenario spec and the resolved road events of the reference run
    cond = []
    for w in scen.get("world_events", []):
        t = w.get("t_min", 0) * 60 + OFFSET
        if w["type"] == "duplicate_call":
            ev(t, "duplicate_call", "caller", call=w["call"], caller_text_sl=w["caller_text_sl"], note="second caller about the same incident; the dispatcher merges it (human)")
        elif w["type"] == "capacity_drop":
            ev(t, "hospital_capacity_update", "hospital report", hospital=w["hospital"], resus_bays_free=w["resus_bays_free"], text=w["title_en"])
        elif w["type"] == "feed_stale":
            ev(t, "data_feed_status", "data feed", feed=w["feed"], state="stale", text=w["title_en"])
            ev(t + w["duration_min"] * 60, "data_feed_status", "data feed", feed=w["feed"], state="fresh")
        elif w["type"] == "priority_change":
            ev(t, "caller_callback", "caller", call=w["call"], text="The caller phones back: the pain has become severe, suspected heart attack.", retriage_from=w["from"], retriage_to=w["to"],
               note="the dispatcher re-triages (human); the model extends the response")
        elif w["type"] == "breakdown":
            cond.append({"id": w["id"], "type": "vehicle_breakdown", "source": "world",
                         "trigger": {"carrier_of_patient": f"P-{w['target']['call']}-1", "phase": "transport", "fraction_of_transport": w["target"]["when"]},
                         "data": {"title_sl": w["title_sl"], "title_en": w["title_en"], "patient_aboard": True,
                                  "note": "whichever vehicle carries the patient breaks down at that point; the model sends a replacement"}})
    for r in ref["world"]["road_events"]:
        delay = next((e["data"]["delay_min"] for e in ref["events"] if e["type"] == "road_event" and e["data"]["id"] == r["id"]), None)
        ev(r["from_t_s"], "road_event", "traffic feed (simulated)", id=r["id"], kind=r["kind"], lat=r["lat"], lon=r["lon"], radius_m=r["radius_m"], delay_min=delay,
           title_sl=r["title_sl"], title_en=r["title_en"], note="a closure blocks the road inside the circle; a jam delays vehicles that cross it")
        ev(r["to_t_s"], "road_event_end", "traffic feed (simulated)", id=r["id"])
    # ---- mass-casualty sequence, triggered by the first team reaching the scene
    patients_after = []
    for cid, o in log.items():
        if o.get("scene_report"):
            sr = o["scene_report"]
            ids = [p for p in ref["patients"] if ref["patients"][p]["call"] == cid]
            patients_after = ids
            cond.append({"id": "SR-" + cid, "type": "scene_report_sequence", "source": "first team on scene (human)", "trigger": {"first_unit_reaches_scene": cid},
                         "steps": [{"after_s": 240, "type": "scene_report", "human": True, "data": {"method": "METHANE", "N_estimate": sum(p["n"] for p in sr["estimate"]), "N_after_triage": sr["actual"],
                                                                                                    "text": "First team reports after start triage on the spot"}},
                                   {"after_s": 250, "type": "mci_declared", "human": True, "data": {"text": "Mass-casualty event declared, regional health coordination group activated, hospitals alerted"}},
                                   {"after_s": 300, "type": "start_triage_complete", "data": {"patients_appear": ids, "counts": sr["actual"]}}]})
    tl.sort(key=lambda e: e["t_s"])
    for i, e in enumerate(tl, 1):
        e["seq"] = i

    # ---- patients: condition, monitor feed, voice entries (anchored, unit-agnostic)
    pats = []
    for pid, p in ref["patients"].items():
        tpl = TEMPLATES[p["template"]]
        entries = []
        for idx, (anchor, off, mode, text, typ, content, conf, flags) in enumerate(tpl["entries"]):
            corr = [f for f in flags if f.startswith("corrects:")]
            al = [f[6:] for f in flags if f.startswith("alert:")]
            entries.append({"id": f"{pid}-V{idx + 1}", "anchor": ANCHOR[anchor], "offset_s": off, "by": "doctor_if_on_scene" if "doctor" in flags else "crew",
                            "mode": "wake_phrase" if mode == "wake" else "push_to_talk", "wake_phrase": "Zapis" if mode == "wake" else None, "transcript_sl": text, "asr_confidence": conf,
                            "parsed": {"type": typ, "content": content}, "needs_correction": "check" in flags, "corrects": f"{pid}-V{int(corr[0].split(':')[1]) + 1}" if corr else None,
                            "expected_er_alert": al[0] if al else None})
        mon = [{"anchor": ANCHOR[a], "offset_s": o, "source": "monitor (simulated)", "vitals": v} for (a, o, v) in tpl["monitor"]]
        pats.append({"id": pid, "call": p["call"], "severity": p["severity"], "label": p["label"], "age": p["age"], "sex": p["sex"], "category": tpl["category"], "template": p["template"],
                     "appears": ({"after": "start_triage_complete"} if pid in patients_after else "at_call"), "vitals_initial": tpl["vitals0"], "monitor_feed": mon, "voice_entries": entries,
                     "walking_wounded": p["severity"] == "green"})

    # ---- fleet: the resources at the start (no assignments)
    from_ids = {u["id"]: u for u in scen["fleet_initial"]}
    low = set(scen["units_not_offered"].get("low_fuel") or [])
    fleet = []
    for u in scen["fleet_initial"]:
        st = "free"
        busy = None
        if u["state"] == "non-urgent":
            st, busy = "busy_with_scheduled_transport", u["free_at_min"]
        elif u["state"] == "cleaning":
            st, busy = "cleaning", u["free_at_min"]
        elif not u["ok"]:
            st = "not_available_low_fuel"
        fuel = 12 if u["id"] in low else 55 + h8(u["id"], scen["id"]) % 38
        fleet.append({"id": u["id"], "role": ROLE[u["kind"]], "org": u["org"], "area": AREA[u["area"]], "base": u["base"], "home": u["home"], "lat": u["lat"], "lon": u["lon"], "status": st,
                      "busy_for_min": busy, "can_be_taken_off_scheduled_job": bool(u["divertable"]) if st == "busy_with_scheduled_transport" else None, "fuel_pct": fuel,
                      "assumed": u["area"] == "PRIV"})
    h, m = (int(x) for x in scen["start_local"].split(":"))
    in_window = 8 * 60 <= h * 60 + m < 16 * 60 + 30
    snow = bool((scen.get("weather") or {}).get("snow_cm"))
    heli_status = "available" if in_window and not scen.get("fog_at_brnik") else "not_available"
    heli_reason = None if heli_status == "available" else ("fog at Brnik" if scen.get("fog_at_brnik") and not snow else "snow and low cloud at Brnik (assumed)" if scen.get("fog_at_brnik") else "outside the daylight window (08:00 to 16:30)")
    fleet.append({"id": "H1", "role": "helicopter", "org": "HNMP Brnik (army Bell 412)", "area": AREA["LJ"], "base": "brnik", "lat": 46.2237, "lon": 14.4576, "status": heli_status, "reason": heli_reason,
                  "speed_kmh": 200, "call_to_takeoff_min": 13, "window_local": "08:00-16:30", "pilot_decides_go_no_go": True})

    world = {"weather": scen["weather"], "weather_speed_factor_hint": scen["expected"]["weather_speed_factor"], "shift": scen["shift"], "traffic": "time-of-day profile (live feeds simulated)",
             "hospitals": {"ukc": {"name": "UKC Ljubljana", "resus_bays_free": 4, "icu_beds_free": 5, "accepts_now": {"red": 3, "yellow": 6, "green": 20}, "synthetic": True}}}
    return {
        "format": "adahack-script/1", "scenario": scen["id"], "name": scen["name"], "intent": scen["intent"], "date": scen["date"], "start_local": scen["start_local"], "shift": scen["shift"],
        "what_this_is": "INPUT: what the world and the people do. No vehicle is assigned, no ETA, path or status is given: the model decides who goes, how long it takes and which way it drives. "
                        "A stand-in dispatcher's decisions for the same input are in scenario/reference_runs/ for comparison.",
        "clock": {"t_s": "seconds since the script origin; the first model minute is t_s = %d" % OFFSET, "origin_iso": clock(scen, 0), "tz": "Europe/Ljubljana (UTC+1 in winter)"},
        "rules": {
            "anchors": {"at_patient": "the first crew (ambulance or doctor) reaches the patient", "left_scene": "the patient leaves the scene", "at_hospital": "the patient arrives at the hospital"},
            "voice_entry_timing": "an entry happens offset_s seconds after its anchor. If the phase is shorter than the last offset, scale all offsets of that anchor so the last one falls inside 90 percent of the phase; keep their order.",
            "voice_entry_by": "crew = the ambulance crew with the patient; doctor_if_on_scene = the doctor vehicle's crew if a doctor reached the patient before transport, otherwise the crew",
            "voice_states": "an entry is 'heard' when said; confirmed by a crew tap or 'potrjeno' about 5 to 9 s later; an entry with needs_correction stays unconfirmed until the entry that 'corrects' it",
            "human_timings_assumed_s": {"dispatcher_triage_after_call": "50 (red) or 75 (yellow)", "crew_accepts_activation": "6 to 15", "paramedic_signs_after_arrival": 600, "handover_starts_after_arrival": 120},
            "durations_assumed_min": {"scene_red": 20, "scene_yellow": 15, "handover": 12, "turnaround": 8},
            "travel_hint": "backend/app/routing.py constants (road factor 1.35, 42 km/h, lights and sirens x1.3, weather and traffic factors); the model may use real routing",
            "noise": "monitor values may vary by a few units around the given numbers"},
        "world": world, "fleet": fleet, "timeline": tl, "conditional_events": cond, "patients": pats,
        "summary": {"calls": len(calls), "patients": len(pats), "timeline_events": len(tl), "conditional_events": len(cond), "fleet_units": len(fleet), "voice_entries": sum(len(p["voice_entries"]) for p in pats),
                    "human_events": sum(1 for e in tl if "human" in e["source"]) + sum(1 for c in cond for s in c.get("steps", []) if s.get("human")),
                    "road_events": sum(1 for e in tl if e["type"] == "road_event")},
    }


def pretty(out):
    c = lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
    lines = ["{"]
    keys = list(out)
    for i, k in enumerate(keys):
        v = out[k]
        comma = "," if i < len(keys) - 1 else ""
        if k in ("timeline", "fleet", "patients", "conditional_events"):
            lines.append(f'"{k}": [')
            lines += [c(e) + ("," if j < len(v) - 1 else "") for j, e in enumerate(v)]
            lines.append("]" + comma)
        else:
            lines.append(f'"{k}": {c(v)}{comma}')
    lines.append("}")
    return "\n".join(lines)


def main():
    data = json.load(open(SC, encoding="utf-8"))
    os.makedirs(OUT, exist_ok=True)
    idx = []
    for scen in data["scenarios"]:
        ref = json.load(open(f'{REF}/{scen["id"]}.json', encoding="utf-8"))
        out = build(scen, ref)
        open(f'{OUT}/{scen["id"]}.json', "w", encoding="utf-8").write(pretty(out))
        s = out["summary"]
        idx.append({"scenario": scen["id"], "name": scen["name"], "file": scen["id"] + ".json", **s})
        print(f'{scen["id"]:5s} timeline {s["timeline_events"]:3d} conditional {s["conditional_events"]} patients {s["patients"]:2d} voice {s["voice_entries"]:3d} fleet {s["fleet_units"]} human {s["human_events"]}')
    json.dump({"format": "adahack-script/1", "scenarios": idx}, open(f"{OUT}/index.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
