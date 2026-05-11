# Docs Audit — 2026-05-11

## Scope

Reviewed `docs/` for stale production references, duplicate root Markdown files, and mobile workflow readiness.

Trainer requirements were intentionally not fully refreshed because current trainer compatibility with the May 10 CatBoost runtime still needs a dedicated audit.

## Current Truth Applied

- Active runtime: CatBoost playoff v5cD.
- Historical baseline: v18 LightGBM.
- Disabled in production: v18 posthoc LightGBM calibrator and telemetry isotonic overlay.
- Current reference run: `data/output/runs/20260510_174904/`.
- Website eval report rule: 6AM eval owns Performance windows and yesterday slip results.

## Root Docs Updated

- `ATLAS_MODEL_CONTEXT.md` synced to current CatBoost v5cD state.
- `PIPELINE_REFERENCE.md` synced to current pipeline state.
- `SCORED_LEGS_DEDUPED_DATA_DICTIONARY.md` synced to the 170-column v5cD run surface.
- `DATA_DICTIONARY.md` updated for CatBoost artifacts, disabled isotonic, live eval archive, and current probability chain.
- `REPLAY_AND_LIVE_RUN_RULES.md` updated for current local paths and v5cD replay expectations.
- `PLAYOFF_REGIME_FIXES_2026.md` marked historical/superseded by the May 10 runtime.
- `2026-05-09_playoff_adj.md` marked historical/superseded by the May 10 runtime.
- `TRAINER_REQUIREMENTS.md` marked intentionally unaudited for this pass.

## Added Docs

- `README.md` — docs folder entry point and map.
- `CURRENT_STATE_2026-05-10.md` — current runtime truth copied from the AI docs.
- `BASELINE_V18.md` — historical LightGBM baseline plus current runtime context.
- `KNOWN_UNCERTAINTIES.md` — current known risks.
- `TUNING_PLAYBOOK.md` — current tuning/replay guidance.
- `WEBSITE_TODO.md` — website, 6AM eval, and Discord requirements.
- `mobileGPT/README.md` — mobile folder entry point.
- `mobileGPT/MOBILE_WORKFLOW.md` — mobile operational playbook.

## Reorganized / Removed From Root

Moved or accepted existing moves into subfolders:

- `DEMON_CALIBRATION_PROTECTION.md` -> `experiments/DEMON_CALIBRATION_PROTECTION.md`
- `FRAGILITY_FEATURE_RESEARCH_20260503.md` -> `experiments/FRAGILITY_FEATURE_RESEARCH_20260503.md`
- `REPLAY_BACKTEST_EVALUATION_PLAN.md` -> `experiments/REPLAY_BACKTEST_EVALUATION_PLAN.md`
- `CRAFTEDNBA_ROLE_WORKLOAD_PLAN_2026-03-26.md` -> `features/CRAFTEDNBA_ROLE_WORKLOAD_PLAN_2026-03-26.md`
- `SHARE_ALLOCATOR_REVIEW_20260510.md` -> `features/SHARE_ALLOCATOR_REVIEW_20260510.md`
- `SHARE_MATRIX_REFERENCE.md` -> `features/SHARE_MATRIX_REFERENCE.md`
- `TEAM_SHARE_ALLOCATOR_V2_DESIGN.md` -> `features/TEAM_SHARE_ALLOCATOR_V2_DESIGN.md`

Removed from docs root:

- `BASELINE_V17.md` — replaced by `BASELINE_V18.md` and current-state docs.
- `BLOWOUT_CURVE_V1.md` — superseded by current state and tuning docs.
- `profile_run_today.txt` — raw trace artifact, not durable docs.
- `trace_run_today_full.txt` — raw trace artifact, not durable docs.

## Historical Docs Marked

- `experiments/DEMON_CALIBRATION_PROTECTION.md`
- `experiments/FRAGILITY_FEATURE_RESEARCH_20260503.md`
- `PLAYOFF_REGIME_FIXES_2026.md`
- `2026-05-09_playoff_adj.md`

## Still Needs A Dedicated Pass

- `TRAINER_REQUIREMENTS.md`
- Trainer scripts and manifests:
  - `tools/gbm_v19_train.py`
  - `tools/catboost_playoff_v5cD_full_corpus.py`
  - `tools/replay_v5cD_corpus.py`
  - `scripts/audits/slip_eval_v5cD_corpus.py`
  - leg trainers under `tools/leg_trainer_*`
- Whether each trainer reads/writes the current CatBoost v5cD probability surface correctly.
