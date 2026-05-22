# NBA Agent Instructions

Before working in this repo, read:

1. `C:\Users\13142\Atlas\ATLAS_OPERATING_MEMORY.md`
2. `C:\Users\13142\Atlas\ATLAS_INFORMATION_PACKET.md`
3. `C:\Users\13142\Atlas\ai\README.md`
4. `C:\Users\13142\Atlas\NBA\ai\AGENT.md`
5. `C:\Users\13142\Atlas\NBA\ai\PIPELINE_REFERENCE.md`
6. `C:\Users\13142\Atlas\NBA\ai\ATLAS_MODEL_CONTEXT.md`
7. `C:\Users\13142\Atlas\NBA\docs\REPLAY_AND_LIVE_RUN_RULES.md`
8. `C:\Users\13142\Atlas\NBA\docs\TRAINER_REQUIREMENTS.md`
9. `C:\Users\13142\Atlas\NBA\config\replay_fidelity_contract.yaml`

The `NBA\ai` folder already contains important historical model/operator context. Do not skip it.

## NBA Priorities

- NBA is customer-facing production.
- Do not delete run output, raw snapshots, bundles, telemetry, archives, model artifacts, or backups.
- Live output and Cloudflare publish must stay functional.
- Replay is valid only when strict fidelity passes first.
- Do not run corpus, LODO, CAT training, or builder tuning until preflight passes for every included date.

## Current Workflow

Use repo-local scripts and wrappers. Confirm the current CLI command from `pyproject.toml`, `atlas.ps1`, or `run.ps1` before changing automation.

Expected order:

1. live run/audit;
2. strict replay preflight;
3. single-date replay smoke;
4. corpus replay;
5. LODO/CAT;
6. builder tuning;
7. publish/promotion.

## Protected Data

Never remove:

- `data/raw`
- `data/output/runs`
- `data/bundles`
- `data/telemetry`
- `data/archives`
- `data/gamelogs`
- `data/model`
- `logs` from active long runs

If disk space is needed, ask before compressing or moving anything.

## Probability Rules

- Exact market probability first.
- Source-specific exact fallback second.
- Anchor/blended prior last.
- No silent defaulting for CAT-weighted features.
- Game spread/total, injury, role, market, and single-game features must be audited before training.
