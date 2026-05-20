# Atlas MLB Docs

Status: MLB development only
Last updated: 2026-05-11

This docs folder now tracks the Atlas MLB engine buildout. Copied NBA production docs were removed to avoid mixing the stable NBA model with this development fork.

## Start Here

- [MLB Dev](mlb/README.md)
- [Architecture](mlb/ARCHITECTURE.md)
- [Product Flow](mlb/PRODUCT_FLOW.md)
- [Data Contracts](mlb/DATA_CONTRACTS.md)
- [PrizePicks Scoring](mlb/PRIZEPICKS_SCORING.md)
- [Gutting Plan](mlb/GUTTING_PLAN.md)

## Ground Rules

- NBA Atlas lives in `C:\Users\13142\Atlas\Atlas` and remains production.
- MLB Dev lives in `C:\Users\13142\Atlas\Atlas-MLB-dev` and is safe to refactor heavily.
- Use `uv run atlas-mlb` as the canonical CLI.
- Use `.\AtlasMLB.ps1` only as the local Windows convenience wrapper.
- Do not import NBA model artifacts or calibration baselines into MLB.
- Build MLB around replayable raw snapshots, source manifests, and MLB-native settlement.
