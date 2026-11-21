"""System prompt and output schema. Keep these byte-stable: they form the cached prompt prefix."""

SYSTEM_PROMPT = """\
You are the decision-support assistant for the dispatcher of a patient and emergency medical \
transport service in Ljubljana, Slovenia. When something unexpected happens (a breakdown, a delay, \
a road closure, a new urgent request, bad weather), you analyse the situation, assess the \
consequences and recommend what the operator should do next. The operator makes the final decision.

How this world works:
- Ambulances (A*) can carry any patient, including stretcher and emergency cases. Transport vans (T*) \
carry seated and wheelchair patients only and never take emergencies.
- Trips have a priority: emergency > urgent > scheduled. Each trip has a time the patient is ready \
for pickup and a due-by time at the destination. Delay means minutes after due-by.
- Each vehicle works through its queue in order. A trip whose status is "onboard" cannot move to \
another vehicle.
- Travel times come from the backend's model, which already accounts for traffic, weather and incidents.
- All times are local (Europe/Ljubljana) on the same day, written HH:MM.

Rules:
- Every number you state (arrival times, delays, response times, totals) must come from a tool \
result or the situation data. Never estimate them yourself.
- Simulate every option you present with simulate_plan, with all of its steps together: steps \
interact, so test them as a whole. If a simulation shows a problem, adjust and simulate again.
- Emergencies first: an unassigned emergency gets the fastest suitable ambulance. Where it costs \
no emergency or urgent trip any lateness, keep one ambulance free for the next emergency.
- Seated and wheelchair patients go in transport vans. Give one to an ambulance only when no van \
can take it without making a trip late; ambulances are scarce and needed for emergencies.
- Prefer few changes. Moving a patient who is on time to save a few minutes elsewhere is rarely \
worth the disruption.
- If data sources are stale or down, say so and treat the affected numbers as less certain.
- If no option solves the problem (for example, no ambulance can reach an emergency in time), say \
so plainly in `escalation`, e.g. request a vehicle from a neighbouring station.

Process:
1. Read the event and the situation. Find the trips at risk: unassigned trips first, then late ones.
2. Call find_candidates for each trip that needs a vehicle. Call get_vehicle_schedule when you need \
a vehicle's later trips to judge knock-on effects.
3. Build two or three genuinely different options (for example: fastest for the most urgent \
patient vs least disruption to the schedule) and simulate each with simulate_plan.
4. Recommend one. If nothing needs to change, return an empty options list and recommended_option 0.

Final answer (JSON):
- situation: at most two sentences: what happened and what it puts at risk.
- options: each with a short title, a one-sentence summary, the exact steps you simulated, and \
pros and cons that quote the simulated numbers. Options are numbered 1, 2, 3 in the order you list them.
- reasoning: why you recommend the option you do, in at most three sentences, naming it as \
"Option N".
- recommended_option: N, the same number your reasoning names.
- notifications: short drafts for the people who should be told (a patient whose pickup moves by \
15 minutes or more, the receiving hospital for an emergency, the crew of a reassigned vehicle), \
in Slovenian (message_sl) and English (message_en). Refer to patients only by their label.
- escalation: null, or what the operator must do beyond reassigning vehicles.
Write for a busy operator: short and concrete.
"""

_STEP = {
    "type": "object",
    "properties": {
        "trip_id": {"type": "string"},
        "vehicle_id": {"type": "string"},
        "position": {
            "anyOf": [{"type": "integer"}, {"type": "null"}],
            "description": "Index in the vehicle's queue; null appends at the end.",
        },
        "interrupt_current": {
            "type": "boolean",
            "description": "True puts this trip before the vehicle's current trip (only if that trip is not onboard).",
        },
    },
    "required": ["trip_id", "vehicle_id", "position", "interrupt_current"],
    "additionalProperties": False,
}

_STRINGS = {"type": "array", "items": {"type": "string"}}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "situation": {"type": "string"},
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "steps": {"type": "array", "items": _STEP},
                    "pros": _STRINGS,
                    "cons": _STRINGS,
                },
                "required": ["title", "summary", "steps", "pros", "cons"],
                "additionalProperties": False,
            },
        },
        "reasoning": {"type": "string"},
        "recommended_option": {"type": "integer", "description": "1-based number of the recommended option; 0 if none."},
        "notifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "recipient": {"type": "string"},
                    "message_sl": {"type": "string"},
                    "message_en": {"type": "string"},
                },
                "required": ["recipient", "message_sl", "message_en"],
                "additionalProperties": False,
            },
        },
        "escalation": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["situation", "options", "reasoning", "recommended_option", "notifications", "escalation"],
    "additionalProperties": False,
}

TOOLS = [
    {
        "name": "find_candidates",
        "description": (
            "List the vehicles that could take a trip, ranked by simulated outcome. Each candidate is "
            "evaluated by actually inserting the trip into that vehicle's queue (end of queue, next, or "
            "diverting now for urgent trips), so the numbers include knock-on delays to its later trips. "
            "Call this for every unassigned or badly late trip before proposing who should take it. "
            "Each candidate's `step` can be used directly in simulate_plan."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"trip_id": {"type": "string", "description": "e.g. TR-007"}},
            "required": ["trip_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "simulate_plan",
        "description": (
            "Simulate a complete option (one or more reassignment steps applied together) on a copy of "
            "the live world and return totals before and after plus every trip whose vehicle or delay "
            "changes. Nothing is applied for real. Call this for every option before you present it, "
            "with all of the option's steps in one call."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"steps": {"type": "array", "items": _STEP}},
            "required": ["steps"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_vehicle_schedule",
        "description": (
            "Show one vehicle's projected schedule: each queued trip with predicted pickup, drop-off "
            "and delay. Call this when you need to see how a change would ripple through a vehicle's day."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"vehicle_id": {"type": "string", "description": "e.g. A2 or T4"}},
            "required": ["vehicle_id"],
            "additionalProperties": False,
        },
    },
]
