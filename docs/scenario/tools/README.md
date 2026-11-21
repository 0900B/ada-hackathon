# Scenario tools

Generators and validators for the dispatch scenarios and simulation scripts. Run from the repository root; see [SIMULATION_SCRIPTS.md](../../SIMULATION_SCRIPTS.md) section 9 for the order and what each step checks.

- `dispatch_sim.py`: seeded dispatch model, writes `scenario/dispatch_scenarios.json`
- `dispatch_validate.py`: checks the engine payloads against `backend/app/models.py` and the counts
- `run_playback.py`, `playback_gen.py`, `playback_emit.py`, `pb_templates.py`: build the scripts in `scenario/playback/`
- `playback_validate.py`: checks order, speeds, status chains and signatures
- `make_scenario_doc.py`: writes `DISPATCH_SCENARIOS.md`
- `replay.py`: replays a script as one dashboard would see it

Set `OSRM_CACHE` to keep the routing cache somewhere other than the system temp folder.
