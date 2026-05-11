# Atlas Tools

`tools/` is for repeatable Atlas operators: scripts that are expected to be run as part of live operations, replay operations, model training, publishing, backfills, or durable data generation.

## Keep Here

- `fetch_*` data fetchers
- `refresh_*` daily refresh utilities
- `backfill_*` historical data and replay backfills
- `replay_*` repeatable replay runners
- `*_trainer*` model and calibration trainers
- `train_*` calibration/model training utilities
- `generate_*` durable output generators
- `publish_*`, `discord_*`, `twitter_*` publishing utilities
- durable readers and corpus builders
- active cache/build utilities used by the live or replay pipeline

## Move To Scripts

New files should usually go under `scripts/` if their names or purpose are mostly:

- audit
- diagnostic/debug/inspect/examine
- smoke/test/check/validate/verify
- analysis/evaluation/report
- sweep/ablation/prototype/research

When a script graduates from investigation to daily operations, move it back into `tools/` and document the command in `docs/PIPELINE_REFERENCE.md` or `docs/TUNING_PLAYBOOK.md`.

## Safety

Before moving an existing `tools/` file, search for references in:

- `scripts/run_iael_*.cmd`
- `src/Atlas/`
- `docs/`
- `ai/`

Scheduled IAEL scripts may depend on exact paths.
