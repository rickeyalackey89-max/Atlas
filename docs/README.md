# Atlas MLB Docs

Status: MLB development only
Last updated: 2026-05-21

This docs folder tracks the Atlas MLB engine. Read the workspace-level operating
memory before changing live, replay, corpus, CAT, builder, publish, or
data-retention code:

- `C:\Users\13142\Atlas\ATLAS_OPERATING_MEMORY.md`
- `C:\Users\13142\Atlas\ai\README.md`

## Start Here

- [MLB Dev](mlb/README.md)
- [Architecture](mlb/ARCHITECTURE.md)
- [Product Flow](mlb/PRODUCT_FLOW.md)
- [Data Contracts](mlb/DATA_CONTRACTS.md)
- [PrizePicks Scoring](mlb/PRIZEPICKS_SCORING.md)
- [Gutting Plan](mlb/GUTTING_PLAN.md)

## Ground Rules

- NBA production lives in `C:\Users\13142\Atlas\NBA`.
- MLB lives in `C:\Users\13142\Atlas\MLB`.
- Old paths such as `C:\Users\13142\Atlas\Atlas` and `C:\Users\13142\Atlas\Atlas-MLB-dev` are rollback references only, not automation roots.
- Use `uv run python -m mlb.cli ...` or `uv run atlas-mlb ...` from `C:\Users\13142\Atlas\MLB` as the canonical CLI.
- Use `.\AtlasMLB.ps1` only as the local Windows convenience wrapper.
- Do not import NBA model artifacts or calibration baselines into MLB.
- Build MLB around replayable raw snapshots, source manifests, and MLB-native settlement.
- Do not run corpus, LODO, CAT training, or builder sweeps until strict replay preflight passes for every included date.
