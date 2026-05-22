# MLB Agent Instructions

Before working in this repo, read:

1. `C:\Users\13142\Atlas\ATLAS_OPERATING_MEMORY.md`
2. `C:\Users\13142\Atlas\ATLAS_INFORMATION_PACKET.md`
3. `C:\Users\13142\Atlas\ai\README.md`
4. `C:\Users\13142\Atlas\MLB\docs\mlb\README.md`
5. `C:\Users\13142\Atlas\MLB\docs\mlb\REPLAY_FIDELITY.md`
6. `C:\Users\13142\Atlas\MLB\config\replay_fidelity_contract.yaml`

## MLB Priorities

- MLB is being prepared for live production.
- Do not delete raw snapshots, run output, bundles, telemetry, archives, model artifacts, weather/lineup files, or backups.
- Replay must match live source contracts as closely as historical data allows.
- Do not run corpus, LODO, CAT training, or builder tuning until preflight passes for every included date.

## Current Workflow

Use repo-local scripts and wrappers. Confirm the current CLI command from `pyproject.toml`, `atlas.ps1`, or `AtlasMLB.ps1` before changing automation.

Expected order:

1. live run/audit;
2. strict replay preflight;
3. single-date replay smoke;
4. corpus replay;
5. LODO/CAT;
6. builder tuning;
7. migration/promotion.

## Protected Data

Never remove:

- `data/mlb/raw`
- `data/mlb/runs`
- `data/mlb/live_runs`
- `data/mlb/test_runs`
- `data/mlb/eval`
- `data/mlb/runtime_state`
- `data/mlb/model`
- `data/mlb/archives`
- `docs/MLB_info_DO_NOT_DELETE`

If disk space is needed, ask before compressing or moving anything.

## MLB Replay Fidelity

Required context includes PrizePicks raw, market odds, game lines, weather/wind, ballpark, lineup, probable pitcher, roster/player history, gamelog truth, injuries, and source manifests. Missing context is a blocker unless explicitly declared nonessential for that replay family.
