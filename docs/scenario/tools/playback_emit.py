"""Turn built unit runs into the master event stream, patients, voice entries and the output file."""
import json
import math
import os
import random
import sys

from playback_gen import (OFFSET, D_ALL, build, h8, hhmmss, fmt_pt, hav_km, pos_at, path_len_m, SC, OUTDIR, _save_cache_hook)
from pb_templates import TEMPLATES, pick_template

CRIT = {"spo2": ("<", 90, "SpO2 below 90"), "sbp": ("<", 90, "Systolic pressure below 90")}
ER_STATUS_TEXT = {"NA POTI": "on the way to the scene", "NA KRAJU": "at the scene", "PRI PACIENTU": "with the patient", "S KRAJA": "on the way to hospital",
                  "NA CILJU": "at the hospital", "PREDAJA PACIENTA": "handover", "ZAKLJUČEK INT": "handed over"}


def assemble(scen):
    S, runs, heli, closures, accidents, others, fuel_km = build(scen)
    meta = json.load(open(SC, encoding="utf-8"))["meta"]
    hosp = json.load(open(SC, encoding="utf-8"))["hospitals"]
    calls = {c["id"]: c for c in scen["calls"]}
    log = {o["call"]: o for o in scen["dispatch_log"]}
    exp = scen["expected"]
    ev = S.emit
    unit_info = {}
    for o in scen["dispatch_log"]:
        for a in o["assignments"]:
            unit_info[a["unit"]] = a
    rng = random.Random(h8(scen["id"]))

    # ---- world and fleet context
    ev(0, "world_state", ["dispatch", "map"], data={"weather": scen["weather"], "weather_speed_factor": exp["weather_speed_factor"], "shift": scen["shift"],
                                                      "traffic_source": "time-of-day profile (live feeds are simulated)", "demand_trigger": "off",
                                                      "hospital_capacity_synthetic": {"ukc": {"resus_bays_free": 4, "icu_beds_free": 5, "accepts_now": {"red": 3, "yellow": 6, "green": 20}}}})
    for u in (scen["units_not_offered"].get("low_fuel") or []):
        ev(0, "agent_action", ["dispatch"], data={"text": f"{u} is not offered for dispatch: fuel too low for a full call", "reason": "fuel range filter"})
    for u, mins in (scen["units_not_offered"].get("cleaning") or {}).items():
        ev(0, "agent_action", ["dispatch"], data={"text": f"{u} is cleaning after a contaminated job and is offered again from minute {mins}", "reason": "readiness state"})

    # ---- road events (closures / accidents)
    for c in closures + accidents:
        ev(c["t0"], "road_event", ["dispatch", "map", "crew"], data={"id": c["id"], "kind": c["kind"], "lat": round(c["lat"], 5), "lon": round(c["lon"], 5), "radius_m": c["r"],
                                                                      "title_sl": c["title_sl"], "title_en": c["title_en"], "source": "simulated (stand-in for promet.si / NAP)",
                                                                      "delay_min": c["delay_s"] / 60 if c["kind"] == "accident" else None})
        ev(c["t1"], "road_event_end", ["dispatch", "map", "crew"], data={"id": c["id"]})

    # ---- calls: received, located, triaged, planned
    call_out = []
    for cid, c in calls.items():
        o = log[cid]
        t0 = o["t"] * 60 + OFFSET
        red = any(p["sev"] == "red" for p in c["patients"])
        lead = 70 if red else 95
        ev(t0 - lead, "call_received", ["dispatch"], call=cid, data={"caller_text_sl": c["caller_text_sl"], "channel": "112 via ReCO"})
        ev(t0 - lead + 2, "caller_location_pinned", ["dispatch", "map"], call=cid, data={"lat": c["lat"], "lon": c["lon"], "place": c["place_name"], "source": "112 call location (simulated)"})
        est = c["patients"]
        ev(t0 - 20, "triage_set", ["dispatch"], call=cid, actor="dispatcher", human=True,
           data={"priority": "red" if red else "yellow", "problem": c["problem"], "patients_estimated": est, "doctor_needed": c.get("doctors", 0) > 0,
                 "first_responders": bool(c.get("first_responders")), "fire": bool(c.get("fire")), "police": bool(c.get("police")), "helicopter_requested": bool(c.get("air")),
                 "note": "the one mandatory human step: triage with the national decision model"})
        acts = [a for a in o["assignments"] if not a.get("superseded") or True]
        ev(t0, "plan_made", ["dispatch"], call=cid, actor="agent",
           data={"units": [{"unit": a["unit"], "role": a["role"], "from": a["org"], "eta_min": a["eta_min"], "reason": a["note"], "other_region": a["area"] == "NG", "private": a["area"] == "PRIV"} for a in acts],
                 "procedure": "red: nearest suitable unit from any region; yellow: Ljubljana area first", "helicopter": o.get("helicopter")})
        if c.get("first_responders") or c.get("fire") or c.get("police"):
            ev(t0 + 3, "agent_action", ["dispatch"], call=cid, data={"text": "Alerted: " + ", ".join(n for n, f in (("first responders", "first_responders"), ("fire brigade", "fire"), ("police", "police")) if c.get(f))})
        call_out.append({"id": cid, "t_s": round(t0, 1), "lat": c["lat"], "lon": c["lon"], "place": c["place_name"], "problem": c["problem"], "caller_text_sl": c["caller_text_sl"],
                         "priority": "red" if red else "yellow", "patients_estimated": est})
    if exp["demand_trigger"]["on"]:
        ev(exp["demand_trigger"]["at_min"] * 60 + OFFSET, "demand_trigger_on", ["dispatch"], actor="agent", data={"reason": exp["demand_trigger"]["reason"], "effect": "other regions allowed for yellow calls; scheduled transports to private vans"})
    for b in scen["non_urgent_log"]:
        ev(b["t"] * 60 + OFFSET, "nonurgent_rebooked", ["dispatch"], actor="agent", data={"requested": b["n"], "to_private_vans": b["to_private_vans"], "kept_by_public_units": b["kept_by_public_units"], "trigger_on": b["trigger_on"]})

    # ---- unit runs: activation, statuses, ETA, road effects
    vehicles = {}
    run_by_call = {}
    for r in runs:
        run_by_call.setdefault(r["rec"]["call_id"], []).append(r)
    for r in runs:
        rec = r["rec"]
        u = r["unit"]
        cid = rec["call_id"]
        ev(r["t_act"], "unit_activated", ["dispatch", "crew", "map", "er"], call=cid, unit=u, actor="agent",
           data={"role": rec["role"], "org": rec["org"], "area": rec["area"], "private": rec["area"] == "PRIV", "other_region": rec["area"] == "NG", "reason": rec["note"],
                 "from": rec["from"], "scene": rec["scene"], "priority": rec["prio"], "eta_scene_min": rec["eta_min"], "speed_kmh": rec["speed_kmh"], "weather_factor": rec["weather_factor"], "traffic_factor": rec["traffic_factor"],
                 "diverted_from_scheduled_job": rec["diverted_from_other_job"]})
        if rec["diverted_from_other_job"] and not rec["note"].startswith("re-planned"):
            ev(r["t_act"] + 1, "agent_action", ["dispatch"], call=cid, data={"text": f"{u} was taken off a lower-priority job for this call; that job is re-planned and its patient told"})
        for (t, st) in r["statuses"]:
            ev(t, "unit_status", ["dispatch", "crew", "map"] + (["er"] if st in ER_STATUS_TEXT and rec["role"] != "van" else []), call=cid, unit=u,
               data={"status": st, "source": "GPS geofence" if st in ("NA KRAJU", "NA CILJU", "S KRAJA") else "crew or agent"})
        for e in r["events"]:
            if e["type"] == "reroute":
                ev(e["t"], "reroute", D_ALL, call=cid, unit=u, data={**{k: e[k] for k in ("closure", "from", "old_remaining_m", "new_remaining_m", "delta_s", "new_path", "path_source")},
                                                                      "message_sl": f"Zapora ceste. Nova pot je izračunana, približno {max(1, round(e['delta_s'] / 60))} min več.", "reason": "closure or accident ahead"})
            else:
                ev(e["t"], "traffic_delay", ["dispatch", "crew", "map", "er"], call=cid, unit=u, data={"accident": e["accident"], "delay_min": round(e["delay_s"] / 60, 1), "at": e["at"],
                                                                                                         "message_sl": f"Zastoj na poti, približno {round(e['delay_s'] / 60)} min zamude."})
        if r.get("cut") and r.get("cut_kind") == "diverted":
            ev(r["cut"], "unit_diverted", ["dispatch", "crew", "map"], call=cid, unit=u, actor="agent", data={"text": f"{u} is taken off {cid} (not yet at the patient) for a red call; position kept, new task follows",
                                                                                                           "position": fmt_pt(r["cut_pos"])})
        if r.get("cut") and r.get("cut_kind") == "stand_down":
            ev(r["cut"], "unit_stand_down", ["dispatch", "crew", "map"], call=cid, unit=u, actor="agent",
               data={"text": f"{u} stood down: the first team's triage needs fewer vehicles; unit is free at its current position", "position": fmt_pt(r["cut_pos"])})
            ev(r["cut"] + 5, "unit_status", ["dispatch", "crew", "map"], call=cid, unit=u, data={"status": "PROST", "source": "agent"})
        if r.get("breakdown"):
            b = r["breakdown"]
            ev(b["t"], "unit_breakdown", D_ALL, call=cid, unit=u, data={"at": b["at"], "title_sl": b["title_sl"], "title_en": b["title_en"], "patient_aboard": True})
            ev(b["t"] + 5, "agent_action", ["dispatch"], call=cid, data={"text": f"{u} broke down with the patient aboard: nearest free ambulance sent at once, tow requested"})
        if r.get("replacement_for"):
            ev(r["t_act"] + 2, "replacement_dispatched", ["dispatch", "crew", "map"], call=cid, unit=u, actor="agent", data={"for_unit": r["replacement_for"], "note": r["rec"]["note"]})
        # ETA stream
        carrier = rec["role"] in ("ambulance", "doctor") and r.get("t_hosp")
        if r.get("t_arr"):
            unc = None
            for fr, lab in ((0.0, "to scene"), (0.5, "to scene")):
                tt = r["t_dep"] + (r["t_arr"] - r["t_dep"]) * fr
                ev(tt, "eta_update", ["dispatch", "crew", "er"], call=cid, unit=u, data={"leg": "to scene", "eta_t_s": round(r["t_arr"], 1), "eta_clock": S.iso(r["t_arr"])[11:19]})
        if carrier:
            for fr in (0.0, 0.5, 0.85):
                tt = r["t_leave"] + (r["t_hosp"] - r["t_leave"]) * fr
                ev(tt, "eta_update", ["dispatch", "crew", "er"], call=cid, unit=u, data={"leg": "to hospital", "eta_t_s": round(r["t_hosp"], 1), "eta_clock": S.iso(r["t_hosp"])[11:19]})
        v = vehicles.setdefault(u, {"id": u, "kind": rec["kind"], "role": rec["role"], "org": rec["org"], "area": rec["area"], "base": rec["base"], "private": rec["area"] == "PRIV",
                                    "other_region": rec["area"] == "NG", "runs": [], "track": [], "statuses": [], "km": 0.0})
        v["runs"].append({"call": cid, "activated_t_s": round(r["t_act"], 1), "departure_t_s": round(r["t_dep"], 1), "arrival_t_s": round(r["t_arr"], 1) if r.get("t_arr") else None,
                          "left_scene_t_s": round(r["t_leave"], 1) if r.get("t_leave") else None, "hospital_arrival_t_s": round(r["t_hosp"], 1) if r.get("t_hosp") else None,
                          "free_t_s": round(r["t_prost"], 1) if r.get("t_prost") else None, "note": rec["note"], "replacement_for": r.get("replacement_for"),
                          "path_sources": sorted({e.get("path_source") for e in r["events"] if e.get("path_source")})})
        v["track"] += r["track"]
        v["statuses"] += [{"t_s": round(t, 1), "status": s} for t, s in r["statuses"]]
        v["km"] += r["km"]
    # fuel per vehicle
    for u, v in vehicles.items():
        start = 12 if u in (scen["units_not_offered"].get("low_fuel") or []) else 55 + h8(u, scen["id"]) % 38
        used_pct = v["km"] / 625.0 * 100  # 75 L tank at 12 L per 100 km
        v["fuel"] = {"start_pct": start, "km_driven": round(v["km"], 1), "end_pct": round(max(0, start - used_pct), 1), "tank_l": 75, "consumption_l_per_100km": 12, "source": "assumed (no fuel feed exists)"}
        v["km"] = round(v["km"], 1)
        v["track"].sort(key=lambda p: p[0])
        v["statuses"].sort(key=lambda s: s["t_s"])
        last = max((r_["t_prost"] or r_["t_end"]) for r_ in runs if r_["unit"] == u)
        if v["fuel"]["end_pct"] < 25 and v["role"] != "van":
            ev(last, "agent_action", ["dispatch"], unit=u, data={"text": f"{u} fuel at {v['fuel']['end_pct']:.0f} percent: refuelling scheduled before the next call", "reason": "fuel range filter"})
    if heli:
        v = {"id": "H1", "kind": "HNMP", "role": "helicopter", "org": "HNMP Brnik (army Bell 412)", "area": "LJ", "base": "brnik", "private": False, "other_region": False,
             "runs": [{"call": heli["call"], "activated_t_s": round(heli["t_act"], 1), "arrival_t_s": round(heli["t_land"], 1), "left_scene_t_s": round(heli["t_leave"], 1), "hospital_arrival_t_s": round(heli["t_hosp"], 1), "note": "straight line at 200 km/h"}],
             "track": heli["track"], "statuses": [{"t_s": round(t, 1), "status": s} for t, s in heli["statuses"]], "km": round(heli["km"], 1),
             "fuel": {"start_pct": 80, "km_driven": round(heli["km"], 1), "end_pct": None, "source": "not modelled (helicopter fuel range not found)"}}
        vehicles["H1"] = v
        ev(heli["t_act"], "unit_activated", ["dispatch", "crew", "map", "er"], call=heli["call"], unit="H1", actor="agent",
           data={"role": "helicopter", "org": v["org"], "reason": "red call, air option evaluated; flies if launch is allowed", "note": "pilot keeps the final go or no-go decision"})
        for t, st in heli["statuses"]:
            ev(t, "unit_status", ["dispatch", "crew", "map", "er"], call=heli["call"], unit="H1", data={"status": st, "source": "crew"})

    # ---- patients, voice entries, ER cards
    patients = {}
    pat_events(S, scen, calls, log, run_by_call, heli, patients, rng, ev, runs)

    # ---- other world events
    for w in others:
        if w["type"] == "duplicate_call":
            t = w["t_min"] * 60 + OFFSET
            ev(t, "call_received", ["dispatch"], call=w["call"], data={"caller_text_sl": w["caller_text_sl"], "channel": "112 via ReCO", "duplicate_of": w["call"]})
            ev(t + 20, "duplicate_call_merged", ["dispatch"], call=w["call"], actor="dispatcher", human=True, data={"text": "Second caller about the same incident, merged into the open call; no new units", "title_en": w["title_en"]})
        elif w["type"] == "capacity_drop":
            t = w["t_min"] * 60 + OFFSET
            ev(t, "capacity_update", ["dispatch", "er"], data={"hospital": w["hospital"], "resus_bays_free": w["resus_bays_free"], "title_en": w["title_en"], "source": "hospital report (simulated)"})
            ev(t + 5, "agent_action", ["dispatch"], actor="agent", data={"text": "Capacity down: destination for red patients stays with the crew or doctor; yellow and scheduled arrivals are offered another hospital"})
        elif w["type"] == "feed_stale":
            t = w["t_min"] * 60 + OFFSET
            ev(t, "feed_status", ["dispatch"], data={"feed": w["feed"], "state": "stale", "effect": "ETAs marked uncertain", "title_en": w["title_en"]})
            ev(t + w["duration_min"] * 60, "feed_status", ["dispatch"], data={"feed": w["feed"], "state": "fresh"})
        elif w["type"] == "priority_change":
            t = w["t_min"] * 60 + OFFSET
            ev(t, "priority_change", ["dispatch", "er", "crew"], call=w["call"], actor="crew report", data={"from": w["from"], "to": w["to"], "title_en": w["title_en"], "note": "the crew's report changes the priority; the agent extends the response"})
            for r in runs:
                if r["rec"]["note"].startswith("doctor vehicle added"):
                    ev(t + 20, "agent_action", ["dispatch"], call=w["call"], data={"text": f"Doctor vehicle {r['unit']} added to {w['call']}" + (" and will meet the patient at the hospital" if r.get("followed_to_hospital") else "")})

    # ---- mci scene report
    for cid, o in log.items():
        if o.get("scene_report"):
            sr = o["scene_report"]
            t = sr["t_min"] * 60 + OFFSET
            first = min(r["t_arr"] for r in run_by_call[cid] if r.get("t_arr"))
            ev(first, "first_team_on_scene", ["dispatch", "er", "map"], call=cid, data={"note": "first team arrives, writes the arrival time, starts primary triage"})
            ev(t - 60, "scene_report", ["dispatch", "er", "map"], call=cid, actor="first team leader", human=True,
               data={"method": "METHANE", "M": "major incident, mass-casualty plan needed", "E": "motorway, exact position from GPS", "T": "coach and car collision", "H": "possible trapped persons, fuel leak",
                     "A": "access via slip road, fire brigade on site", "N_estimate": sum(p["n"] for p in sr["estimate"]), "N_after_triage": sr["actual"], "E_services": "fire, police present"})
            ev(t - 50, "mci_declared", ["dispatch", "er", "map"], call=cid, actor="first team leader and dispatcher", human=True,
               data={"text": "Mass-casualty event declared; regional health coordination group (RKSZ) activated; hospitals alerted", "hospital_alarm": "yellow"})
            ev(t, "triage_complete", ["dispatch", "er", "map"], call=cid, actor="first team", data={"start_triage": sr["actual"], "estimate_was": sr["estimate"],
                                                                                                       "needs": o["needs"], "initial_wave": o["needs_initial"]})
            over = [r for r in run_by_call[cid] if r["rec"].get("dest_id") == "celje"]
            ev(t + 6, "hospital_distribution", ["dispatch", "er"], call=cid, actor="agent proposes, incident medical lead confirms", human=True,
               data={"ukc_accepts_now": {"red": 3, "yellow": 6, "green": 20}, "overflow_to": "SB Celje", "overflow_units": [r["unit"] for r in over],
                     "text": "UKC capacity is used first; the overflow (1 red, 2 yellow) goes to SB Celje. Destination of a red patient is confirmed by the incident medical lead.", "capacity": "synthetic"})
            ev(t + 3, "agent_action", ["dispatch"], call=cid, data={"text": "Initial wave was sent for the caller's estimate of about 30 injured. After triage the vehicles that are still on the way and not needed are stood down.",
                                                                    "stood_down": exp["stood_down_units"]})

    # ---- output
    S.events.sort(key=lambda e: (e["t_s"], e["seq"]))
    for i, e in enumerate(S.events, 1):
        e["seq"] = i
    idle = [{"id": u["id"], "kind": u["kind"], "area": u["area"], "lat": u["lat"], "lon": u["lon"], "state": u["state"]} for u in scen["fleet_initial"] if u["id"] not in vehicles]
    end_t = max(e["t_s"] for e in S.events)
    out = {
        "format": "adahack-playback/1", "scenario": scen["id"], "name": scen["name"], "intent": scen["intent"], "date": scen["date"], "start_local": scen["start_local"], "shift": scen["shift"],
        "clock": {"t_s": "seconds since the script origin; the first model minute is t_s = %d, ISO times are local (UTC+1)" % OFFSET, "origin_iso": S.iso(0), "end_t_s": end_t},
        "dashboards": {"dispatch": "all events", "er": "inbound ambulances, ETA, type, vitals, treatments, alerts, handover", "crew": "events for one unit (filter by unit)", "map": "positions from vehicles[].track, road events, reroutes"},
        "world": {"weather": scen["weather"], "road_events": [{"id": c["id"], "kind": c["kind"], "lat": round(c["lat"], 5), "lon": round(c["lon"], 5), "radius_m": c["r"], "from_t_s": round(c["t0"], 1), "to_t_s": round(c["t1"], 1),
                                                              "title_sl": c["title_sl"], "title_en": c["title_en"]} for c in closures + accidents],
                  "hospitals": hosp},
        "calls": call_out, "vehicles": vehicles, "patients": patients, "idle_fleet": idle, "events": S.events,
        "summary": {"vehicles": len(vehicles), "patients": len(patients), "events": len(S.events), "voice_entries": sum(1 for e in S.events if e["type"] == "voice_entry"),
                    "reroutes": sum(1 for e in S.events if e["type"] == "reroute"), "human_steps": sum(1 for e in S.events if e.get("human")),
                    "event_types": {t: sum(1 for e in S.events if e["type"] == t) for t in sorted({e["type"] for e in S.events})}},
    }
    return out


def pat_events(S, scen, calls, log, run_by_call, heli, patients, rng, ev, all_runs):
    exp = scen["expected"]
    for cid, c in calls.items():
        o = log[cid]
        rs = run_by_call.get(cid, [])
        amb = sorted([r for r in rs if r["rec"]["role"] == "ambulance" and not r.get("cut") and not r.get("replacement_for") and r.get("t_arr")], key=lambda r: r["t_arr"])
        repl = {r["replacement_for"]: r for r in all_runs if r.get("replacement_for") and r["rec"]["call_id"] == cid}
        docs = sorted([r for r in rs if r["rec"]["role"] == "doctor" and not r.get("cut") and r.get("t_arr")], key=lambda r: r["t_arr"])
        vans = sorted([r for r in rs if r["rec"]["role"] == "van" and not r.get("cut") and r.get("t_arr")], key=lambda r: r["t_arr"])
        sr = o.get("scene_report")
        counts = sr["actual"] if sr else {s: sum(p["n"] for p in c["patients"] if p["sev"] == s) for s in ("red", "yellow", "green")}
        t_pat = (sr["t_min"] * 60 + OFFSET) if sr else None
        plist = [("red", i) for i in range(counts["red"])] + [("yellow", i) for i in range(counts["yellow"])] + [("green", i) for i in range(counts["green"])]
        mci = bool(c.get("mci"))
        n_amb = 0
        van_idx = 0
        for k, (sev, _) in enumerate(plist, 1):
            pid = f"P-{cid}-{k}"
            tpl_name = pick_template(c["problem"], sev, mci)
            tpl = TEMPLATES[tpl_name]
            carrier, vcarrier = None, None
            if sev == "green":
                vcarrier = vans[van_idx // 4] if vans and van_idx // 4 < len(vans) else None
                van_idx += 1
            else:
                carrier = amb[n_amb] if n_amb < len(amb) else None
                n_amb += 1
            main = carrier or vcarrier
            if not main:
                continue
            age = rng.randint(*tpl["age"])
            sex = tpl["sex"] or rng.choice(["M", "F"])
            repl_run = repl.get(main["unit"])
            doctor = docs[0] if docs and sev == "red" and docs[0].get("t_contact") and docs[0]["t_contact"] < (main.get("t_leave") or 0) - 90 and not docs[0].get("followed_to_hospital") else None
            t_hosp_final = (repl_run["t_hosp"] if repl_run else main.get("t_hosp")) or (heli["t_hosp"] if heli and heli["call"] == cid else None) or main["t_end"]
            use_heli = heli and heli["call"] == cid and sev == "red"
            if use_heli:
                t_hosp_final = heli["t_hosp"]
            P = {"id": pid, "call": cid, "severity": sev, "label": f"Pacient {pid} (synthetic)", "age": age, "sex": sex, "category": tpl["category"], "template": tpl_name,
                 "carried_by": [main["unit"]] + ([repl_run["unit"]] if repl_run else []) + (["H1"] if use_heli else []), "doctor_unit": doctor["unit"] if doctor else None,
                 "destination": hosp_name(scen, main), "vitals_initial": tpl["vitals0"], "timeline": []}
            patients[pid] = P
            t_create = t_pat if t_pat else main["t_act"]
            ev(t_create, "patient_created", ["dispatch", "er"], call=cid, unit=main["unit"], patient=pid,
               data={"severity": sev, "category": tpl["category"], "age": age, "sex": sex, "source": "start triage on scene" if sr else "triage by the dispatcher"})
            card = {"card_id": pid, "call": cid, "priority": sev, "category": tpl["category"], "age": age, "sex": sex, "unit": main["unit"], "status": "en route to the scene",
                    "eta_hospital_t_s": round(t_hosp_final, 1), "latest_vitals": None, "treatments": [], "alerts": [], "destination": P["destination"], "problem_flags": flags_for(tpl_name)}
            ev(max(main["t_act"], t_create), "er_card_created", ["er"], call=cid, unit=main["unit"], patient=pid, data=dict(card))

            def push(t, kind, **extra):
                ev(t, "er_card_update", ["er"], call=cid, unit=main["unit"], patient=pid, data={"update": kind, **{k: v for k, v in extra.items()}, "card": json.loads(json.dumps(card))})
            for t, st in main["statuses"]:
                if st in ER_STATUS_TEXT:
                    card["status"] = ER_STATUS_TEXT[st]
                    push(t, "status", status=st)
            # entries
            scene_anchor = main["t_contact"] if main.get("t_contact") else main["t_arr"]
            trans_anchor = (heli["t_leave"] if use_heli else main.get("t_leave")) or scene_anchor
            arrive_anchor = t_hosp_final
            unit_ids = lambda t: ("H1" if use_heli and t >= heli["t_land"] else (repl_run["unit"] if repl_run and t >= repl_run["t_act"] + 40 else main["unit"]))  # noqa: E731
            entry_ids = {}
            windows = {"scene": max(60.0, ((main.get("t_leave") or scene_anchor + 900) if not use_heli else heli["t_leave"]) - scene_anchor - 20),
                       "transport": max(45.0, t_hosp_final - trans_anchor - 30), "arrival": 600.0}
            mx = {"scene": 1.0, "transport": 1.0, "arrival": 1.0}
            for e_ in tpl["entries"]:
                mx[e_[0]] = max(mx[e_[0]], e_[1])
            for m_ in tpl["monitor"]:
                mx[m_[0]] = max(mx[m_[0]], m_[1])
            scl = {a_: min(1.0, 0.9 * windows[a_] / mx[a_]) for a_ in mx}
            for idx, (anchor, off, mode, text, typ, content, conf, flags) in enumerate(tpl["entries"]):
                base = {"scene": scene_anchor, "transport": trans_anchor, "arrival": arrive_anchor}[anchor]
                off = off * scl[anchor]
                t = base + off + (h8(pid, idx) % 5 - 2)
                u = unit_ids(t)
                if "doctor" in flags and doctor:
                    t = doctor["t_contact"] + off
                    u = doctor["unit"]
                t = max(scene_anchor + 8, min(t, t_hosp_final - 25))
                eid = f"{pid}-V{idx + 1}"
                entry_ids[idx] = eid
                state = "check" if "check" in flags else "confirmed"
                conf_t = None if state == "check" else t + (5 if conf >= 0.9 else 9) + h8(eid) % 3
                corr = [f for f in flags if f.startswith("corrects:")]
                ev(t, "voice_entry", ["crew", "dispatch", "er"], call=cid, unit=u, patient=pid,
                   data={"entry_id": eid, "mode": "wake_phrase" if mode == "wake" else "push_to_talk", "wake_phrase": "Zapis" if mode == "wake" else None, "transcript_sl": text, "asr_confidence": conf,
                         "parsed": {"type": typ, "content": content}, "state": "heard", "readback_on_screen": True,
                         "corrects": entry_ids.get(int(corr[0].split(":")[1])) if corr else None})
                if state == "confirmed":
                    ev(conf_t, "voice_confirm", ["crew", "dispatch", "er"], call=cid, unit=u, patient=pid, data={"entry_id": eid, "state": "confirmed", "by": "crew tap" if conf < 0.9 else "crew tap or 'potrjeno'"})
                    apply_entry(card, typ, content)
                    push(conf_t, "entry", entry_id=eid, entry_type=typ)
                else:
                    ev(t + 4, "voice_check", ["crew"], call=cid, unit=u, patient=pid, data={"entry_id": eid, "text": "Low confidence: please repeat or correct the value", "asr_confidence": conf})
                P["timeline"].append({"t_s": round(t, 1), "entry_id": eid, "unit": u, "type": typ, "state": state})
                for fl in flags:
                    if fl.startswith("alert:"):
                        card["alerts"].append(fl[6:])
                        ev(t + 3, "er_alert", ["er", "dispatch"], call=cid, unit=u, patient=pid, actor="agent", data={"text": fl[6:], "source_entry": eid})
                        push(t + 3, "alert", text=fl[6:])
            for idx, (anchor, off, vit) in enumerate(tpl["monitor"]):
                base = {"scene": scene_anchor, "transport": trans_anchor, "arrival": arrive_anchor}[anchor]
                t = max(scene_anchor + 5, min(base + off * scl[anchor], t_hosp_final - 10))
                vv = {k: (v + (h8(pid, idx, k) % 5 - 2) if isinstance(v, int) and k in ("hr", "sbp", "dbp") and v > 0 else v) for k, v in vit.items()}
                ev(t, "monitor_vitals", ["crew", "er", "dispatch"], call=cid, unit=unit_ids(t), patient=pid, data={"source": "monitor feed (simulated)", **vv})
                card["latest_vitals"] = {**(card["latest_vitals"] or {}), **vv, "t_s": round(t, 1), "source": "monitor"}
                push(t, "vitals", vitals=vv)
                for key, (op, lim, text) in CRIT.items():
                    if key in vv and vv[key] and vv[key] < lim and text not in card["alerts"]:
                        card["alerts"].append(text)
                        ev(t + 2, "er_alert", ["er", "dispatch"], call=cid, unit=unit_ids(t), patient=pid, actor="agent", data={"text": text, "source": "monitor"})
                        push(t + 2, "alert", text=text)
            # arrival, handover, record
            carrier_final = repl_run if repl_run else main
            if use_heli:
                th = heli["t_hosp"]
            else:
                th = carrier_final.get("t_hosp")
            if th and sev != "green":
                bay = ("R" if sev == "red" else "Y") + str(1 + h8(pid) % 4)
                ev(th - 120, "er_bay_assigned", ["er", "crew"], call=cid, unit=unit_ids(th), patient=pid, actor="agent", data={"bay": bay})
                ev(th + 120, "handover_started", ["er", "crew", "dispatch"], call=cid, unit=unit_ids(th), patient=pid, data={"bay": bay, "limit_min": 15})
                summary = {"leading_problem": tpl["category"], "age": age, "sex": sex, "initial_vitals": tpl["vitals0"], "latest_vitals": card["latest_vitals"], "treatments": card["treatments"], "alerts": card["alerts"],
                           "times": {"call": S.iso(o["t"] * 60 + OFFSET - 70)[11:19], "at_patient": S.iso(scene_anchor)[11:19], "left_scene": S.iso(trans_anchor)[11:19], "at_hospital": S.iso(th)[11:19]}}
                ev(th + 125, "handover_summary", ["er", "crew"], call=cid, unit=unit_ids(th), patient=pid, actor="agent", data=summary)
                pending = [t["entry_id"] for t in P["timeline"] if t["state"] == "check"]
                ev(th + 540, "record_review_prompt", ["crew", "dispatch"], call=cid, unit=unit_ids(th), patient=pid, actor="agent",
                   data={"fields_to_review": [e["entry_id"] for e in P["timeline"] if e["type"] in ("drug_administered", "event", "procedure")] + pending, "unconfirmed": pending,
                         "note": "everything else is pre-filled from the event log; the paramedic reviews and signs"})
                ev(th + 600, "record_signed", ["crew", "dispatch", "er"], call=cid, unit=unit_ids(th), patient=pid, actor="paramedic", human=True,
                   data={"signed": True, "step": "last documentation step at drop-off", "signature": "stamp: name, time, hash (demo)", "hash": f"{h8(pid, 'sig'):08x}"})
                ev(th + 600, "handover_done", ["er", "crew", "dispatch"], call=cid, unit=unit_ids(th), patient=pid, data={"within_15_min": True})
                card["status"] = "handed over"
                push(th + 601, "status", status="handed over")
            elif vcarrier is not None and main.get("t_hosp"):
                ev(main["t_hosp"] + 120, "handover_done", ["er", "dispatch"], call=cid, unit=main["unit"], patient=pid, data={"area": "green area", "note": "walking wounded, no pre-alert needed"})


def hosp_name(scen, run):
    meta = json.load(open(SC, encoding="utf-8"))["hospitals"]
    return meta.get(run["rec"]["dest_id"], {}).get("name", "UKC Ljubljana")


def flags_for(name):
    return {"chest_pain": ["chest pain", "possible STEMI"], "stroke": ["suspected stroke"], "cardiac_arrest": ["resuscitation"], "breathing": ["dyspnoea"],
            "head_injury": ["severe head injury"], "pedestrian_trauma": ["polytrauma"], "crash": ["trauma"], "bleeding": ["trauma", "heavy bleeding"], "mci_red": ["mass casualty"]}.get(name, [])


def apply_entry(card, typ, content):
    if typ == "drug_administered":
        card["treatments"].append({"type": "drug", **content})
    elif typ == "procedure":
        card["treatments"].append({"type": "procedure", **content})
    elif typ == "vitals":
        card["latest_vitals"] = {**(card["latest_vitals"] or {}), **content, "source": "voice"}
    elif typ == "event":
        card["treatments"].append({"type": "event", **content})
