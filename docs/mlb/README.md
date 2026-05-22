# Atlas MLB Dev

Status: active development engine  
Last updated: 2026-05-21

Atlas MLB is a separate engine under the umbrella Atlas workspace. Read the
workspace-level operating memory before changing live, replay, corpus, CAT,
builder, publish, or data-retention code:

- `C:\Users\13142\Atlas\ATLAS_OPERATING_MEMORY.md`
- `C:\Users\13142\Atlas\ai\README.md`
- `C:\Users\13142\Atlas\MLB\config\replay_fidelity_contract.yaml`

## Operating Rules

- NBA Atlas remains the working production model.
- MLB may be refactored aggressively, but source snapshots, run outputs,
  manifests, telemetry, archives, and `MLB_info_DO_NOT_DELETE` files are
  protected data and must not be deleted.
- Do not run copied NBA live jobs as MLB production.
- Keep the Python environment compatible with NBA Atlas while MLB architecture is built.
- Prefer new MLB modules under `src/mlb/`. Imports remain `mlb.*`.
- Treat copied NBA modules as reference material until they are explicitly migrated or removed.
- Do not run corpus, LODO, CAT training, or builder sweeps until replay source
  contracts pass for every included date.

## Start Here

- [Architecture](ARCHITECTURE.md)
- [Pipeline Reference](PIPELINE_REFERENCE.md)
- [Implementation Phases](IMPLEMENTATION_PHASES.md)
- [Sobol / QMC Engine Decision](SOBOL_QMC_ENGINE_DECISION.md)
- [Replay Fidelity Rule](REPLAY_FIDELITY.md)
- [Matchup Matrix Architecture](MATCHUP_MATRIX_ARCHITECTURE.md)
- [Product Flow](PRODUCT_FLOW.md)
- [Data Contracts](DATA_CONTRACTS.md)
- [Active Operational Contract](ACTIVE_OPERATIONAL_CONTRACT.md)
- [Source Snapshots](SOURCE_SNAPSHOTS.md)
- [Artifact Compaction](ARTIFACT_COMPACTION.md)
- [Operator AI Workflow](OPERATOR_AI_WORKFLOW.md)
- [PrizePicks Scoring](PRIZEPICKS_SCORING.md)
- [Gutting Plan](GUTTING_PLAN.md)

## Active Folder Map

- `src/mlb/cli.py` - CLI command surface.
- `src/mlb/contracts/` - typed data contracts.
- `src/mlb/domain/` - markets, scoring helpers, and slip families.
- `src/mlb/fetchers/` - source API fetchers.
- `src/mlb/normalizers/` - source-specific normalization writers.
- `src/mlb/sources/` - source catalog and immutable raw snapshot helpers.
- `src/mlb/matchups/` - lineup, starter, bullpen, and environment matrix contracts.
- `src/mlb/modeling/` - model-side skeletons such as share matrix contracts.
- `src/mlb/runtime/` - preflight, paths, pipeline definition, publishing, bundles, inspection, live, and replay boundaries.
- `src/mlb/evaluation/` - deterministic anomalies, OpenAI operator review, reports, and publish decisions.
- `src/core/` - shared non-sport helpers currently used by MLB, including PrizePicks payout quoting.
- `config/sports/mlb.yaml` - MLB dev configuration draft.
- `data/mlb/raw/` - immutable raw source pulls.
- `data/mlb/staged/` - normalized source tables.
- `data/mlb/features/` - model-ready feature tables.
- `data/mlb/model/` - active and candidate MLB model artifacts.
- `data/mlb/test_runs/` - replay, smoke-test, and corpus-member run outputs.
- `data/mlb/live_runs/` - actual live model run outputs and live slip files.
- `data/mlb/eval/` - scored historical outcomes and evaluation reports.
- `data/mlb/season_gamelogs/` - running season truth store used by replay eval and history context.
- `data/mlb/runtime_state/` - compact running source/market/eval state preserved through artifact compaction.
- `data/mlb/archives/` - cached source snapshots and audit artifacts.

## Current Non-Goals

- No live subscription-impacting MLB publishing.
- No direct reuse of NBA calibration as MLB truth.
- No production Discord posting.
- No automatic dashboard deployment from MLB Dev until explicitly enabled.

## Command Surface

- Canonical CLI: `uv run atlas-mlb`
- Local Windows wrapper: `.\AtlasMLB.ps1`
- Direct module form: `uv run python -m mlb.cli`
- CLI rule: parse arguments only; runtime modules own execution decisions.

Core run surfaces:

- `uv run atlas-mlb live`
- `uv run atlas-mlb replay single`
- `uv run atlas-mlb replay corpus`
- `uv run atlas-mlb operator`
