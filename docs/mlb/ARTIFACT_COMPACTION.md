# MLB Artifact Compaction Contract

The MLB engine keeps two classes of files:

- Durable source/model/runtime state: required to run live, replay accurately, audit a published run, or train from settled truth.
- Generated rebuild artifacts: useful while debugging a run, but too large to keep indefinitely.

Compaction may remove generated rebuild artifacts only after the durable state files below exist.

## Never Delete

These paths are protected by policy:

- `data/mlb/raw/` source snapshots and source manifests.
- `data/mlb/model/` trained models, CAT artifacts, calibration configs, and slip-builder policies.
- `data/mlb/live_runs/` by default. Live runs are only compacted with an explicit `--include-live-runs`.
- `data/mlb/season_gamelogs/` running season truth store.
- `data/mlb/runtime_state/` running operational state.

## Durable Runtime State

`data/mlb/runtime_state/` is the small running store used to keep daily state after large artifacts are compacted.

Current files:

- `runtime_state_manifest.json`: latest runtime-state write manifest.
- `runs/run_summaries.jsonl`: one idempotent summary row per run id.
- `source_manifests/source_manifests_running.jsonl`: one idempotent source contract row per run id.
- `source_manifests/latest_source_selection_manifest.json`: latest full source-selection contract.
- `market_priors/market_priors_running.csv`: running market-prior/context rows keyed by run/projection/market.
- `market_priors/latest_market_priors.csv`: latest market-prior/context rows.
- `eval/eval_legs_running.csv`: running settled leg truth keyed by run/projection/market/side.
- `eval/eval_slips_running.csv`: running settled slip truth keyed by run/family/label/slip id.
- `eval/daily_eval_summary.jsonl`: one idempotent eval summary row per run id.
- `eval/latest_eval_summary.json`: latest eval summary.
- `eval/latest_slip_eval.json`: latest slip-eval payload.

The live/replay pipeline writes runtime state automatically at the end of a run. `atlas-mlb audit eval` also appends settled eval rows automatically, so the 6am prior-day eval keeps the running eval files current.

## Generated Artifacts

These are rebuild/debug artifacts and may be compacted:

- `data/mlb/features/`
- `data/mlb/staged/`
- `data/mlb/replay_runs/`
- `data/mlb/test_runs/` legacy compatibility only
- `data/mlb/eval/`

The compactor archives small audit files and manifests before deleting bulky generated CSV/JSON/JSONL files. It does not touch `raw`, `model`, `live_runs`, `season_gamelogs`, or `runtime_state` unless explicitly configured.

## Commands

Dry run:

```powershell
cd C:\Users\13142\Atlas\MLB
uv run python scripts\mlb\compact_generated_artifacts.py
```

Apply after reviewing the dry-run manifest:

```powershell
cd C:\Users\13142\Atlas\MLB
uv run python scripts\mlb\compact_generated_artifacts.py --apply
```

The compactor writes:

```text
data/mlb/archives/compacted_artifacts/<archive_id>/compaction_manifest.json
```

On `--apply`, small preserved audit files are copied under:

```text
data/mlb/archives/compacted_artifacts/<archive_id>/files/
```

## Pre-Compaction Checklist

Run these checks before applying cleanup:

```powershell
cd C:\Users\13142\Atlas\MLB
Test-Path data\mlb\season_gamelogs\latest.jsonl
Test-Path data\mlb\runtime_state\runtime_state_manifest.json
Test-Path data\mlb\runtime_state\market_priors\market_priors_running.csv
Test-Path data\mlb\runtime_state\eval\eval_legs_running.csv
Test-Path data\mlb\runtime_state\source_manifests\source_manifests_running.jsonl
```

For live-only cleanup before a prior-day eval has run, `eval/eval_legs_running.csv` can be missing. Do not compact historical eval artifacts until the prior-day eval has populated it.

## Recovery

If a compacted generated artifact is needed:

1. Check the archive manifest for the original path and checksum.
2. Restore small archived audit files from `archives/compacted_artifacts/<archive_id>/files/`.
3. Rebuild bulky feature/staged/test/eval rows from protected raw snapshots, model artifacts, season gamelogs, and runtime-state files.

Compaction is a disk-space operation, not a source-data deletion operation.
