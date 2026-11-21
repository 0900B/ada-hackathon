# Scenario tools

Generators and validators for the dispatch scenarios, the input scripts and the reference runs. Run from the repository root; see [SIMULATION_SCRIPTS.md](../../SIMULATION_SCRIPTS.md) section 6 for the order.

- `dispatch_sim.py`: seeded stand-in dispatcher, writes `scenario/dispatch_scenarios.json`
- `dispatch_validate.py`: checks the engine payloads against `backend/app/models.py` and the counts
- `run_playback.py`, `playback_gen.py`, `playback_emit.py`, `pb_templates.py`: build the reference runs in `scenario/reference_runs/` (the stand-in dispatcher's output)
- `playback_validate.py`: checks reference runs: order, speeds, status chains, signatures
- `make_input_scripts.py`: builds the input scripts in `scenario/scripts/` (what the world does; no vehicle decisions)
- `scripts_validate.py`: checks that no vehicle decision has leaked into an input script
- `make_scenario_doc.py`: writes `DISPATCH_SCENARIOS.md`
- `replay.py`: shows an input script (`--script`) or replays a reference run as one dashboard would see it

Set `OSRM_CACHE` to keep the routing cache somewhere other than the system temp folder.
