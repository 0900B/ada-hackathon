"""Build docs/DISPATCH_SCENARIOS.md from docs/scenario/dispatch_scenarios.json (numbers come from the seeded model)."""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
J = REPO + "/docs/scenario/dispatch_scenarios.json"
D = json.load(open(J, encoding="utf-8"))
S = {s["id"]: s for s in D["scenarios"]}
PB12 = json.load(open(J.replace("dispatch_scenarios.json", "playback/D12.json"), encoding="utf-8"))
IDX = {x["scenario"]: x for x in json.load(open(J.replace("dispatch_scenarios.json", "playback/index.json"), encoding="utf-8"))["scenarios"]}
META = D["meta"]
ROS = META["rosters_detail"]
NAMES = {"ambulances": "Ambulances", "doctor_vehicles": "Doctor vehicles", "helicopter": "Helicopter", "sanitary_vans": "Public sanitary vans",
         "private_ambulances": "Private ambulances", "private_vans": "Private vans"}


def clock(start, t):
    h, m = (int(x) for x in start.split(":"))
    tot = h * 60 + m + int(round(t))
    return f"{(tot // 60) % 24:02d}:{tot % 60:02d}"


def org_of(s):
    m = {}
    for o in s["dispatch_log"]:
        for a in o["assignments"]:
            m[a["unit"]] = a["org"].replace(" [A]", "").replace("Private ambulance (qualified crew)", "private").replace("Private non-urgent transport", "private")
    return m


def who(a):
    tag = " (other region)" if a["area"] == "NG" else ""
    rp = ""
    if a["note"].startswith("re-planned"):
        rp = " [re-planned " + a["note"].split(":")[0].replace("re-planned ", "") + "]"
    org = a["org"].replace(" [A]", "").replace("Private ambulance (qualified crew)", "private ambulance").replace("Private non-urgent transport", "private van")
    sd = f' [stood down at minute {a["stood_down_at_min"]:g}]' if a.get("stood_down_at_min") is not None else ""
    return f'{a["unit"]} {org}{tag}, {a["eta_min"]:.0f} min{rp}{sd}'


def pat(c):
    n = {"red": 0, "yellow": 0, "green": 0}
    for p in c["patients"]:
        n[p["sev"]] += p["n"]
    return n


def pstr(n):
    return ", ".join(f"{n[k]} {k}" for k in ("red", "yellow", "green") if n[k]) or "none"


def plural(n, one, many=None):
    return f"{n} {one if n == 1 else (many or one + 's')}"


def need(nd):
    parts = []
    if nd["NRV"]:
        parts.append(plural(nd["NRV"], "ambulance"))
    if nd["VUZ"]:
        parts.append(plural(nd["VUZ"], "doctor vehicle"))
    if nd["HNMP"]:
        parts.append("helicopter")
    if nd["VAN"]:
        parts.append(plural(nd["VAN"], "van"))
    return ", ".join(parts)


def calls_table(s):
    rows = ["| Call | Time | Place | Level | Patients | Needs (by rule) | Sent (unit, minutes to arrive) |", "|---|---|---|---|---|---|---|"]
    logs = {o["call"]: o for o in s["dispatch_log"]}
    for c in s["calls"]:
        o = logs[c["id"]]
        lvl = "red" if any(p["sev"] == "red" for p in c["patients"]) else "yellow"
        extra = [n for n, f in (("first responders", "first_responders"), ("fire", "fire"), ("police", "police"), ("mass-casualty trailer and incident command", "mci")) if c.get(f)]
        needs = need(o["needs"]) + (" + " + ", ".join(extra) if extra else "")
        if o.get("needs_initial"):
            needs = f'initial wave {need(o["needs_initial"])} -> after triage {need(o["needs"])}' + (" + " + ", ".join(extra) if extra else "")
        final = [a for a in o["assignments"] if not a.get("superseded")]
        sup = [a["unit"] for a in o["assignments"] if a.get("superseded")]
        sent = "; ".join(who(a) for a in final)
        pcell = pstr(pat(c))
        if o.get("scene_report"):
            a_ = o["scene_report"]["actual"]
            pcell = f'{sum(p["n"] for p in c["patients"])} estimated ({pstr(pat(c))}) -> {sum(a_.values())} triaged on scene ({a_["red"]} red, {a_["yellow"]} yellow, {a_["green"]} green)'
        if sup:
            sent += f" (earlier choices {', '.join(sup)} were taken off this call for red calls)"
        rows.append(f'| {c["id"]} | {clock(s["start_local"], c["t"])} | {c["place_name"]} | {lvl} | {pcell} | {needs} | {sent} |')
    return "\n".join(rows)


def units_block(s):
    e = s["expected"]
    org = org_of(s)
    us = e["units_sent"]
    out = []
    for k in ("ambulances", "doctor_vehicles", "sanitary_vans", "private_ambulances", "private_vans", "helicopter"):
        ids = us.get(k, [])
        if not ids:
            continue
        label = NAMES[k]
        if k == "helicopter":
            out.append(f"- **{label}:** H1 from Brnik")
            continue
        extra = ""
        other = [u for u in ids if u in e["other_area_units"]]
        if other:
            extra = " (other regions: " + ", ".join(f"{u} {org[u]}" for u in other) + ")"
        out.append(f"- **{label} ({len(ids)}):** {', '.join(ids)}{extra}")
    if not us.get("helicopter") and any(o.get("helicopter") for o in s["dispatch_log"]):
        why = next(o["helicopter"]["reason"] for o in s["dispatch_log"] if o.get("helicopter"))
        out.append(f"- **Helicopter:** not sent ({why})")
    out.append(f'- **From other regions:** {", ".join(f"{u} ({org[u]})" for u in e["other_area_units"]) if e["other_area_units"] else "none"}')
    out.append(f'- **Private units:** {", ".join(e["private_units"]) if e["private_units"] else "none"}')
    sv = e["other_services_alerted"]
    out.append("- **Other services alerted by dispatch (not part of the ambulance fleet):** " + (", ".join(sv) if sv else "none"))
    if e.get("stood_down_units"):
        out.append(f'- **Stood down after triage ({len(e["stood_down_units"])}):** {", ".join(e["stood_down_units"])} (the initial wave was {e["initial_wave_vehicles"]} vehicles)')
    if e["units_reused_after_finishing"]:
        out.append(f'- **Reuse:** {e["assignments_made"]} assignments were served by {e["assignments_made"] - e["units_reused_after_finishing"]} different vehicles, because {e["units_reused_after_finishing"]} vehicle(s) finished one job and took the next.')
    return "\n".join(out)


def ctx(s):
    w = s.get("weather") or {}
    bits = [f'{s["start_local"]} start, {"weekday" if s["weekday"] else "weekend"}, {s["shift"]} roster']
    if w.get("snow_cm"):
        bits.append(f'snow {w["snow_cm"]:g} cm, {w.get("temp_c")} °C')
    elif w.get("wind_kmh", 0) >= 60:
        bits.append(f'storm wind {w["wind_kmh"]} km/h, rain')
    elif w.get("precip_mm"):
        bits.append(f'light rain, {w.get("temp_c", "")} °C')
    else:
        bits.append("dry")
    bits.append(f'speed factor from weather {s["expected"]["weather_speed_factor"]}')
    bits.append(f'{round(s["background_load"] * 100)} percent of units busy with scheduled transports at the start')
    return "; ".join(bits)


def section(sid, title, shows, points):
    s = S[sid]
    e = s["expected"]
    nu = s["non_urgent_log"]
    npat = e["patients"]
    lines = [f"### {sid}. {title}", "", f'**Shows:** {shows}', "", "**Setup:** " + ctx(s) + f". {e['calls']} call{'s' if e['calls'] != 1 else ''}, {npat} patient{'s' if npat != 1 else ''}.", "",
             calls_table(s), "", "**All units sent:**", "", units_block(s), ""]
    tr = e["demand_trigger"]
    nums = [f'**Vehicles needed by the rules:** {need(e["units_needed_by_rule"]) or "none"}. **Different vehicles sent:** {e["total_units_dispatched"]} (helicopter included where it flew).']
    nums.append(f'**Demand trigger:** on at minute {tr["at_min"]:g} ({tr["reason"]}).' if tr["on"] else "**Demand trigger:** not reached.")
    if e["diverted_other_jobs"]:
        nums.append(f'**Units taken off another job:** {e["diverted_other_jobs"]}.')
    if nu:
        b = nu[0]
        nums.append(f'**Scheduled transports:** {b["n"]} requested at minute {b["t"]:g}; {b["to_private_vans"]} to private vans, {b["kept_by_public_units"]} stay with public units.')
    if e["red_first_ambulance_arrival_min"]:
        r = ", ".join(f"{k} {v:.1f} min" for k, v in e["red_first_ambulance_arrival_min"].items())
        nums.append(f'**First ambulance to each red call:** {r}; 15-minute target {"met" if e["red_target_met"] else "missed"}.')
    nums.append(f'**Ljubljana-area ambulances:** {e["ljubljana_area_ambulances_free_at_lowest"]} of {e["ljubljana_area_ambulances_crewed"]} free at the lowest point; at most {e["ljubljana_area_peak_busy_percent"]} percent busy.')
    lines += ["- " + n for n in nums] + ["", "**What to point out:**", ""] + ["- " + p for p in points] + [""]
    n_ev = len(s["engine_events"])
    lines += [f"**Engine events:** {n_ev} `urgent_request` payload{'s' if n_ev > 1 else ''} in the JSON (`engine_events`), each valid against the engine's event model.", "", "---", ""]
    return "\n".join(lines)


def overview():
    a = ["| Scenario | Start | Calls | Patients (red / yellow / green) | Vehicles needed by the rules |", "|---|---|---|---|---|"]
    b = ["| Scenario | Ambulances | Doctor vehicles | Helicopter | Vans | **All vehicles sent** | Initial wave | From other regions | Private (ambulances / vans) | Other services alerted |", "|---|---|---|---|---|---|---|---|---|---|"]
    for sid in sorted(S):
        s = S[sid]
        e = s["expected"]
        n = {"red": 0, "yellow": 0, "green": 0}
        for c in s["calls"]:
            for k, v in pat(c).items():
                n[k] += v
        sr_ = next((o["scene_report"] for o in s["dispatch_log"] if o.get("scene_report")), None)
        if sr_:
            n = dict(sr_["actual"])
        a.append(f'| {sid} {s["name"]} | {s["start_local"]} | {e["calls"]} | {n["red"]} / {n["yellow"]} / {n["green"]} | {need(e["units_needed_by_rule"])} |')
        us = e["units_sent"]
        vans = len(us.get("sanitary_vans", [])) + len(us.get("private_vans", []))
        sv = ", ".join(e["other_services_alerted"]) or "none"
        b.append(f'| {sid} | {len(us["ambulances"]) + len(us["private_ambulances"])} | {len(us["doctor_vehicles"])} | {"yes" if us["helicopter"] else "no"} | {vans} | **{e["total_units_dispatched"]}** | {e["initial_wave_vehicles"] or "same"} | '
                 f'{len(e["other_area_units"])} | {len(us["private_ambulances"])} / {len(us["private_vans"])} | {sv} |')
    return "\n".join(a), "\n".join(b)


def first(sid, cid):
    return next(o for o in S[sid]["dispatch_log"] if o["call"] == cid)


# ---- narrative values -------------------------------------------------------------------------------------------------
d01 = first("D01", "D01-C1")["assignments"][0]
d02 = first("D02", "D02-C1")["assignments"]
d03a = first("D03a", "D03a-C1")
d03b = first("D03b", "D03b-C1")
d04c0 = first("D04", "D04-C0")["assignments"]
d05 = first("D05", "D05-C1")
d07, d08, d09, d10, d11 = S["D07"], S["D08"], S["D09"], S["D10"], S["D11"]
org10 = org_of(d10)
d10a = first("D10", "D10-C1")["assignments"]
amb10 = [a for a in d10a if a["kind"] == "NRV" and not a.get("stood_down_at_min")]
red_amb, yel_amb = amb10[:4], amb10[4:]
doc10 = [a for a in d10a if a["kind"] == "VUZ" and not a.get("stood_down_at_min")]
totals = [S[k]["expected"]["total_units_dispatched"] for k in S]
ov_a, ov_b = overview()
red_eta = ", ".join(f'{a["eta_min"]:.0f}' for a in red_amb)

doc = f"""# Dispatch scenarios: from one call to a mass-casualty event

Scenarios for the agentic flow in [AGENTIC_DISPATCH_DESIGN.md](AGENTIC_DISPATCH_DESIGN.md). They differ in the number of calls, the urgency, the number of patients and so in the **number of responding vehicles**: from **one ambulance** (D01) to **{max(totals)} vehicles** for 22 patients (D10). Machine-readable file: [`scenario/dispatch_scenarios.json`](scenario/dispatch_scenarios.json). Built 2026-11-21. Everything is synthetic.

**Tags:** **[S]** from a source; **[SS]** from a news summary; **[I]** my inference; **[A]** an assumption to confirm.

---

## 1. How the scenarios work

**Colour scheme (kept until told otherwise):** **red** = life-threatening, engine priority `emergency`; **yellow** = possible danger or needs a doctor's assessment, engine priority `urgent`; **non-urgent** = scheduled transport, engine priority `scheduled`. Green appears only as the on-scene severity of walking patients in multi-patient incidents (D05, D10).

**Capacity rule:** **one patient per ambulance.** Every red and every yellow patient needs an ambulance of their own. Green patients (walking wounded) do not go by ambulance: they go by van or bus, 4 per van [A, to confirm].

**Doctors:** a doctor vehicle goes to a red call when triage says a doctor is needed. Which red cases get a doctor is a triage output (the SloIn NMP text is not public). I set it for cardiac arrest, trapped or severe injury, chest pain, severe breathing difficulty and heavy bleeding, and not for a suspected stroke (ambulance and ER pre-alert) [A]. In 2024 about a quarter of urgent interventions at the Ljubljana station had a doctor on board [S, `OPERATIONS_DETAILS.md`].

**Rules used by the model** (the design's rules, run on a seeded stand-in for the dispatcher):

| Rule | Behaviour |
|---|---|
| Red ambulance | Nearest suitable public unit by ETA from its live position, **any area**. A private ambulance only if no public unit reaches in 15 minutes **and** the private one is faster |
| Yellow ambulance | Units in the Ljubljana emergency area only. Other areas only once the demand trigger is on **and** the local arrival is over 30 minutes. A private ambulance only over 45 minutes [A] |
| Scheduled (non-urgent) transports | Stay with public units. Once the trigger is on they go to private vans (at most 6 are available [A]) |
| Doctor vehicle | One per red call with a doctor flag; red calls may draw from other areas, yellow only from the Ljubljana area |
| Helicopter | Considered for red calls that ask for it; only 08:00 to 16:30 local, and not in fog or snow at Brnik [S, `EMS_RESEARCH.md`] |
| Taking a unit off a job | A red call may take a unit that is still driving to a yellow or scheduled job. A yellow call may take one only from a scheduled job. A unit with the patient aboard is never taken. The displaced yellow call is re-planned and its patient told |
| Demand trigger | Free ambulances in the Ljubljana area are 25 percent or less of those crewed, **or** a red arrival is predicted over 15 minutes [A thresholds] |
| Exit time | 1 minute for an ambulance, 5 minutes for a doctor vehicle, when a unit starts from rest (2026 rulebook, reported) [SS] |

**Counting:** "vehicles sent" counts **different vehicles**. A vehicle taken off one call and sent to another counts once. A vehicle that finishes one job and takes a later call also counts once (the reuse is shown where it happens). Fire, police, first responders and the mass-casualty trailer are alerted by dispatch and listed separately; they are not part of the ambulance fleet.

**Travel model:** the same constants as `backend/app/routing.py`: road distance is 1.35 times the straight line, 42 km/h, lights and sirens ×1.3 for red, the engine's weather factor and its time-of-day traffic profile (rush hour 0.65). Units that are driving are placed along their route, so a unit can be diverted from where it is now. **Limits:** one speed for all distances means long runs look slow (a Postojna ambulance needs over an hour to reach Vrhnika in rush hour), and the engine's rush-hour factor of 0.65 is a strong slowdown. Real long runs on a motorway are faster. Treat ETAs over 30 minutes as conservative.

**Service times [A]:** 20 minutes at the scene for red, 15 for yellow, 12 minutes handover, 8 minutes cleaning and restocking.

### The fleet at the start

| | Day (07:00 to 19:00) | Night |
|---|---|---|
| Ambulances in the Ljubljana emergency area | {ROS['day']['ljubljana_area_ambulances']} | {ROS['night']['ljubljana_area_ambulances']} |
| Doctor vehicles in the Ljubljana area | {ROS['day']['ljubljana_area_doctor_vehicles']} | {ROS['night']['ljubljana_area_doctor_vehicles']} |
| Ambulances in neighbouring regions (Kranj, Škofja Loka, Tržič, Litija, Zagorje, Trbovlje, Trebnje, Novo mesto) | {ROS['day']['other_area_ambulances']} | {ROS['night']['other_area_ambulances']} |
| Doctor vehicles in neighbouring regions | {ROS['day']['other_area_doctor_vehicles']} | {ROS['night']['other_area_doctor_vehicles']} |
| Public sanitary vans (UKC station) | {ROS['day']['public_sanitary_vans']} | {ROS['night']['public_sanitary_vans']} |
| Private ambulances with qualified crews [A] | {ROS['day']['private_ambulances']} | {ROS['night']['private_ambulances']} |
| Private non-urgent vans [A] | {ROS['day']['private_vans']} | {ROS['night']['private_vans']} |
| Helicopter H1 at Brnik | 08:00 to 16:30 only | none |

Team counts come from the 2026 insurer's decree (24.0 ambulance teams and 10 doctor-vehicle teams in the Ljubljana area). A count of 1.5 teams becomes 2 by day and 1 by night [A]. Private bases and crew qualifications are not published [?]. A share of units (the "background load") is busy with scheduled transports at the start; 30 percent is the all-day average from about 134 interventions a day, two thirds of them non-urgent.

---

## 2. Overview

**What each scenario asks for:**

{ov_a}

**What was sent** (different vehicles; fire, police and similar are alerted by dispatch and listed in the last column):

{ov_b}

**Reading the tables:** *vehicles needed by the rules* come from the patient counts and doctor flags. *All vehicles sent* can be smaller when a vehicle serves two calls one after the other (D07, D09) and smaller when the helicopter cannot fly (D03b, D05, D09, D10). The ambulance column includes private ambulances; the private column splits them out.

---

## 3. The scenarios

""" + section("D01", "Quiet morning: one yellow call",
              "The smallest case. One patient, one ambulance, procedure-first selection from a live position, no escalation.",
              [f'{d01["unit"]} ({d01["org"]}) goes, {d01["eta_min"]:.0f} minutes away, and is back in service about {d01["free_again_min"]:.0f} minutes after the call (scene, transport, handover, cleaning).',
               "The area rule and the demand trigger are never touched.",
               "Good as the first click of the demo: it shows what \"nothing special\" looks like."]) + section(
    "D02", "Chest pain: ambulance and doctor start from different places",
    "One red call whose triage response includes a doctor. The two units start at different bases.",
    [f'{d02[0]["unit"]} starts at the {d02[0]["org"]} and arrives in {d02[0]["eta_min"]:.0f} minutes; {d02[1]["unit"]} starts at {d02[1]["org"]} and arrives in {d02[1]["eta_min"]:.0f} minutes. Each gets its own route.',
     "The ER dashboard shows the inbound card with the live ETA the moment the units are activated.",
     "First responders nearest the scene are also activated for a life threat (art. 17) [S]."]) + section(
    "D03a", "Cardiac arrest at a mountain trailhead, helicopter flies",
    "A red call far from any base. The agent races the helicopter against the ground units and sends both.",
    [d03a["notes"][0] + ".",
     f'The Kamnik ambulance arrives in {d03a["assignments"][0]["eta_min"]:.0f} minutes and the Kamnik doctor vehicle in {d03a["assignments"][1]["eta_min"]:.0f}. The two arrival times are close, so both go. What the helicopter adds is a doctor on scene and a much shorter way to UKC [I]; the model does not yet compute time to hospital.',
     "First responders nearest the scene are activated for the cardiac arrest (art. 17) [S]."]) + section(
    "D03b", "The same call with fog at Brnik: helicopter grounded",
    "Fog grounds the helicopter. The ground units already left in the first minute, so nothing has to be repaired.",
    [d03b["notes"][0] + ".",
     "The ground response is the same as in D03a: that is the point. Weather only matters if it moves assets before the event.",
     "The brief's fog event (X01 in `SURGE_EVENTS.md`) covers the case where the fog arrives after a launch."]) + section(
    "D04", "Two reds compete for the nearest unit",
    "A yellow call is on its way when two reds arrive three minutes apart. Shows taking a unit off a lower-priority job and re-planning it.",
    [f'At minute 2 the red call D04-C1 takes {d04c0[0]["unit"]}, which was still on its way to the yellow call D04-C0. The yellow patient is re-planned to {d04c0[1]["unit"]} and told.',
     f'At minute 5 the second red call takes {d04c0[1]["unit"]} the same way. The yellow patient is re-planned again, to {d04c0[2]["unit"]}, and told again.',
     "Three calls, four vehicles in all: three ambulances (one for each patient) and one doctor vehicle for the cardiac arrest. The stroke call gets an ambulance and an ER pre-alert, no doctor [A].",
     "If the triage code did not give a clinical order between the two reds, the dispatcher would be asked. Here the nearest unit simply goes to the call that came first."]) + section(
    "D05", "Multi-vehicle crash on the ring road at dusk",
    "One incident, six patients (2 red, 2 yellow, 2 green): seven vehicles plus fire, police and first responders.",
    [f'Four ambulances (one for each red and yellow patient), two doctor vehicles (one for each red patient) and one sanitary van for the two green patients. The first ambulance arrives in {d05["assignments"][0]["eta_min"]:.0f} minutes: rush hour and a closed lane (×0.85) slow every unit.',
     d05["notes"][0] + ".",
     "The ReCO alerts fire and police in parallel for a road accident [S, `EMS_RESEARCH.md`]; the agent only shows them on the incident.",
     "This is below the mass-casualty threshold: no human declaration is needed, the dispatcher's triage already set the levels."]) + section(
    "D06", "Rush hour mix: one red, five yellow",
    "Steady pressure over an hour in rush hour. The agent keeps the area rule and uses the nearest free unit each time.",
    ["Each call gets the nearest unit; the trigger never fires, so the eight scheduled discharges at minute 30 stay with public units.",
     "The one red call (a fall from a ladder with a head injury) gets an ambulance and a doctor vehicle; the five yellow calls get one ambulance each: seven vehicles in all.",
     "The yellow call in Kočevje is served by the Kočevje team, inside the Ljubljana emergency area, and not by an ambulance from the city.",
     "This is what a normal busy hour looks like for the dispatcher: nothing to decide, only to watch."]) + section(
    "D07", "Busy afternoon, teams near full capacity",
    "Eleven calls in 75 minutes (3 red, 8 yellow) while most ambulances are out. The demand trigger is on from the start.",
    [f'The trigger is on at minute 0 ({d07["expected"]["demand_trigger"]["reason"]}). At minute 30, 15 scheduled transports are requested: 6 go to private vans (the whole private-van pool) and 9 stay with public units.',
     f'One yellow call goes to a unit from another region ({", ".join(d07["expected"]["other_area_units"])}): the local wait was over 30 minutes and the trigger was on.',
     f'Eleven ambulance jobs and two doctor jobs are served by {d07["expected"]["total_units_dispatched"]} different vehicles, because {d07["expected"]["units_reused_after_finishing"]} ambulance finished a job and took a later one.',
     "A yellow call in Vrhnika waits over an hour in the model because the nearest local units are busy and other regions are slower in rush hour. That is the flat-speed limit noted above, and also a real warning about thin cover.",
     f'{d07["expected"]["diverted_other_jobs"]} units were taken off scheduled or yellow jobs for red calls.']) + section(
    "D08", "Saturday night, thin staffing, three reds",
    "Night roster (22 ambulances in the area against 26 by day), no helicopter, three reds in 21 minutes at different ends of the area.",
    [f'Each red call gets one ambulance and one doctor vehicle: three ambulances and three doctor vehicles, six vehicles for three patients. The stab wound with heavy bleeding gets a doctor too [A]; fire and police are alerted for the crash and the stabbing.',
     f'The first two reds are reached in {d08["expected"]["red_first_ambulance_arrival_min"]["D08-C1"]:.0f} and {d08["expected"]["red_first_ambulance_arrival_min"]["D08-C2"]:.0f} minutes. The third, in Grosuplje, is {d08["expected"]["red_first_ambulance_arrival_min"]["D08-C3"]:.1f} minutes away, just over the 15-minute target.',
     "That predicted arrival turns the demand trigger on. A private ambulance is **not** used: it needs 15 minutes to mobilise, so it would not be faster than the public unit already available. The rule \"private only if faster\" holds.",
     "The dispatcher is told that the target is missed by a fraction. This is a case where the system shows its reasoning and does not escalate for the sake of it."]) + section(
    "D09", "Snow and ice morning: many calls, slow roads",
    "Fourteen calls in two hours. Snow cuts speed to 0.6 of normal on top of rush hour.",
    [f'The agent does not offer A05 (too little fuel) and offers A03 only after its 30-minute cleaning ends: A03 is used first at minute 38.',
     d09["dispatch_log"][0]["notes"][0] + ".",
     f'Sixteen ambulance and doctor jobs are served by {d09["expected"]["total_units_dispatched"]} different vehicles; {d09["expected"]["units_reused_after_finishing"]} vehicles finished a job and took a later one.',
     "The demand trigger turns on at minute 20 (6 of 26 ambulances free). Of 20 scheduled transports, only 6 can go to private vans; 14 stay with public units, which shows that the private pool is also a limit.",
     "Yellow arrivals stretch to 40 minutes and more at the busiest moments. Weather slows every unit equally, so the order of calls matters more than the choice of unit."]) + section(
    "D10", "Mass-casualty: bus crash on the motorway, 22 patients",
    "The largest case. The caller says about 30 injured, so the agent sends everything it can at once. The first team triages on the spot, reports, and the vehicles that are still on the way and no longer needed are stood down.",
    [f'**Minute 0, before anyone has seen the scene:** the dispatcher triages the call as red with a suspected mass-casualty event. The agent sends the **initial wave** sized for the caller\'s estimate (5 red, 10 yellow, 15 green by assumption): {d10["expected"]["initial_wave_vehicles"]} vehicles, which is as much as the 25-vehicle surge cap allows. Alerted by dispatch: fire, police, first responders, the mass-casualty trailer, an incident commander with a triage team [S, `SURGE_AND_MULTI_SERVICE_COORDINATION.md`].',
     f'**Minute 12, the first team has done start triage on the spot** and reports (METHANE, a human step): 22 patients, 4 red, 8 yellow, 10 green. A human declares the mass-casualty event and the regional coordination group is formed (art. 21) [S].',
     f'**Stand-down:** with one patient per ambulance the real need is 12 ambulances, 4 doctor vehicles and 3 vans. The agent stands down the {len(d10["expected"]["stood_down_units"])} vehicles that are still furthest away ({", ".join(d10["expected"]["stood_down_units"])}). They become free where they are and can cover the rest of the area.',
     f'**What stays: {d10["expected"]["total_units_dispatched"]} vehicles.** 12 ambulances (the four red patients get the first to arrive, in {red_eta} minutes; the yellow patients\' ambulances in {yel_amb[0]["eta_min"]:.0f} to {yel_amb[-1]["eta_min"]:.0f} minutes), 4 doctor vehicles (arriving in {min(a["eta_min"] for a in doc10):.0f} to {max(a["eta_min"] for a in doc10):.0f} minutes) and 3 vans for the 10 green patients.',
     f'**Other regions:** {", ".join(f"{u} ({org10[u]})" for u in d10["expected"]["other_area_units"])}, sent for yellow patients because the demand trigger was on and the local wait was over 30 minutes. **Private:** {", ".join(d10["expected"]["private_units"])}, vans for the green patients, because the public vans were not free within 20 minutes. No private ambulance was needed. No helicopter: it is after dark.',
     "**Hospital distribution** with the synthetic UKC capacity (accepts 3 red, 6 yellow, 20 green at once): one red and two yellow patients overflow to SB Celje. The agent proposes it; the incident medical lead confirms, because the destination of a red patient is a clinical decision.",
     "A slip road is closed by the fire brigade while the units are on their way: ten vehicles are rerouted (see the script).",
     "**How this works in real life is only partly documented.** The Slovenian guideline says the first team sends METHANE with an initial estimate of casualties, starts primary triage and calls additional help as needed, and the dispatcher activates further teams per the unit's plan [S, mass-casualty guideline 2013]. I found no published rule for sending an over-sized first wave or for standing vehicles down; that is common practice elsewhere [I] and is modelled here as the agent's job with a human confirming the declaration."]) + section(
    "D11", "Everything is out: no public unit is free within 15 minutes",
    "A storm-hour extreme. Every ambulance in the area and in the neighbouring regions is tied up for at least 18 minutes. Shows the private-ambulance rule for red calls.",
    [f'The first red call gets the private ambulance PA01, {d11["expected"]["red_first_ambulance_arrival_min"]["D11-C1"]:.0f} minutes away, because every public unit would need longer. The second red gets PA02 at {d11["expected"]["red_first_ambulance_arrival_min"]["D11-C2"]:.0f} minutes. Both miss the 15-minute target, and the dispatcher sees that.',
     "Each red call also gets a doctor vehicle (public: ZD Ljubljana and ZD Domžale).",
     "The two yellow calls wait 17 to 24 minutes for public units; none goes outside the area because no neighbour is faster.",
     "Of 18 scheduled transports, 6 go to private vans and 12 stay with public units.",
     "This is also the scenario for the open question about private crews: whether their staff may take red calls is not published [?]; the rule used here follows your instruction."]) + section(
    "D12", "Everything at once: seven overlapping calls",
    "A 25-minute demo script where events overlap in every way: two calls in the same minute, calls that arrive while others are on the road, a duplicate caller, a closure, a jam, a stale feed, a breakdown with a patient aboard, a capacity drop and a patient who gets worse.",
    ["**Same time:** D12-C1 (red chest pain) and D12-C2 (yellow fall) arrive in the same minute; two ambulances and a doctor vehicle go out at once.",
     "**In between:** a pedestrian crash (C3, minute 3), a wasp-sting allergy (C4, minute 6) and a cardiac arrest (C5, minute 9) arrive while the first units are still on the road. The trigger turns on at the arrest because the predicted arrival is over 15 minutes.",
     f'**Closure:** the road towards Domžale is closed after a collision while the arrest ambulance is on its way. The vehicles heading there ({", ".join(sorted({e["unit"] for e in PB12["events"] if e["type"] == "reroute"}))}) are rerouted, about {round(max(e["data"]["delta_s"] for e in PB12["events"] if e["type"] == "reroute") / 60)} minutes longer. **Jam:** a minor collision delays the Šiška patient\'s ambulance by 4 minutes.',
     "**Duplicate caller:** a second caller reports the pedestrian crash; the dispatcher merges it and no new units go (a human step). **Stale feed:** the traffic feed is stale for 5 minutes and ETAs are marked uncertain.",
     f'**Breakdown:** the ambulance carrying the diabetic patient (C6) breaks down; the agent sends the nearest free ambulance ({next(e["unit"] for e in PB12["events"] if e["type"] == "replacement_dispatched")}) and the patient is transferred.',
     "**Capacity and priority change:** UKC reports one free resuscitation bay (minute 16). The crew reports that the chest tightness (C7) has become a suspected heart attack (minute 21): the call is upgraded to red and a doctor vehicle is added.",
     "Humans involved: seven triages, one merge decision and seven signatures. Everything else is the agent."]) + """## 4. Simulation scripts

Each scenario has a replayable script in [`scenario/playback/`](scenario/playback/): every vehicle's timeline and road path, reroutes, patient vitals and voice entries, and one event stream for all dashboards. Format and how to replay: [SIMULATION_SCRIPTS.md](SIMULATION_SCRIPTS.md).

| Script | Vehicles | Patients | Events | Voice entries | Reroutes | Human steps |
|---|---|---|---|---|---|---|
""" + "\n".join(f'| [{k}](scenario/playback/{v["file"]}) | {v["vehicles"]} | {v["patients"]} | {v["events"]} | {v["voice_entries"]} | {v["reroutes"]} | {v["human_steps"]} |' for k, v in sorted(IDX.items())) + """

*Vehicles* counts every vehicle that appears in the script: in D10 the initial wave of 24, of which 5 are stood down at minute 12; D07 and D12 include a replacement ambulance.

## 5. Using the scenarios

- **With the engine.** Each scenario has `engine_events`: `urgent_request` payloads with a time offset in minutes. Red becomes `priority: "emergency"` and yellow `"urgent"`. All payloads were checked against the engine's event model. The engine holds one trip per request, so patient counts, doctor vehicles, helicopters, private providers and the demand trigger need new code; the JSON carries them as `calls[].patients`, `calls[].doctors` and the `expected` block.
- **As a test of the agent.** Feed the `calls` and compare the agent's choices with `dispatch_log`: the units, the order of events and the totals in `expected`. The model is a stand-in, so a different but defensible choice is not an error; a choice that breaks a rule in section 1 is.
- **For the stage.** A good order is D01, D02, D04, D07, D10. D03a and D03b are the weather pair, D09 shows weather, fuel and cleaning, D11 shows the private-ambulance rule.

## 6. What is assumed

- The speeds, thresholds (25 percent free, 15 and 30 and 45 minutes), service times and the private pool (3 ambulances, 6 vans, 15 and 30 minutes to mobilise) are assumptions [A].
- The model picks initial positions of busy units at random around their base from a fixed seed (20261123). Another seed changes individual ETAs, not the rules.
- The model is greedy: it assigns each call in order and does not re-optimise the whole day.
- Slovenian caller texts are my drafts and should be read by a native speaker before going on stage.
- Hospital capacity is the synthetic set in `scenario/ljubljana_scenario.json`.
- No fuel feed exists: the fuel and cleaning cases in D09 are set by hand.

## 7. Open questions

- **Green patients in a mass-casualty event:** the model sends them by van (4 per van). If every patient should get an ambulance, D10 needs 22 ambulances and would not fit the 25-vehicle cap together with the day's other calls.
- **Yellow calls and private ambulances.** The rule used is: only if even other regions leave a wait over 45 minutes. Say if you want it stricter or looser.
- **Crew qualification of private ambulances** for red calls, and what the rules say about it [?].
- **The demand trigger thresholds** (25 percent free; 15-minute red target) should be confirmed with the contact or the dispatch centre.
- **Which red cases get a doctor** is set by triage; the full SloIn NMP scheme is still outstanding.
"""
open(REPO + "/docs/DISPATCH_SCENARIOS.md", "w", encoding="utf-8").write(doc)
print("written", len(doc.splitlines()), "lines")
