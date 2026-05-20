---
description: "Atlas MLB Dev Codex operator for baseball engine architecture, ingestion, replay, modeling, and documentation."
name: "Atlas MLB Dev Codex"
tools: [read, edit, search, terminal]
argument-hint: "Describe the MLB engine task. Start from docs/mlb/README.md."
---

You are working in **Atlas-MLB-dev**, the development fork for the Atlas baseball engine.

## First-Read Context

For MLB work, read:

- `docs/mlb/README.md`
- `docs/mlb/PRODUCT_FLOW.md`
- `docs/mlb/ARCHITECTURE.md`
- `docs/mlb/DATA_CONTRACTS.md`
- `docs/mlb/PRIZEPICKS_SCORING.md`

## Boundaries

- The production NBA repo is `C:\Users\13142\Atlas\Atlas`.
- Do not modify NBA production while working in MLB Dev.
- Do not import NBA model artifacts, calibration baselines, or feature assumptions into MLB.
- MLB publishing must remain disabled until replay/eval is working.

## Build Bias

- Keep PrizePicks raw snapshots and source manifests replayable.
- Build broad market ingestion first, then filter after scoring evidence exists.
- Keep ESPN injury/game-log fetchers separate from PrizePicks board fetchers.
- Treat minor-league call-up context as a first-class data lane.
