# Atlas Live Run and Replay Rules

> **Last updated:** 2026-05-11
> **Current runtime:** CatBoost playoff v5cD. Replay should exercise the current pipeline unless a test explicitly pins an older baseline.

This document is the reference for what live runs are for, what replay is for, how replay should be launched during testing, where the pinned inputs live, and where each mode is allowed to write outputs.

## Purpose

Live is the production path. It is allowed to fetch current data, refresh mutable sources, score the current slate, publish latest artifacts, and write live outputs.

Replay is the testing path for the current model. The point of replay is to run today's Atlas logic against a pinned historical slate so the outputs can be inspected, compared, and tuned without contaminating live surfaces.

Replay is not for publishing live artifacts. Replay is not allowed to write into the live run tree.

## Live Versus Replay

| Topic | Live | Replay |
| --- | --- | --- |
| Main purpose | Produce the current model run | Test the current model on pinned historical inputs |
| PrizePicks source | Fresh fetch | Pinned raw JSON |
| Injury source | Fresh IAEL refresh and publish | Pinned IAEL status, invalidations, and normalized snapshot |
| Rotowire source | Fresh fetch | Pinned Rotowire snapshot |
| Role metrics | Current fetch or current configured source | Pinned role-metrics artifact, with dashboard artifact fallback if explicit env paths are not set |
| Output root | `data/output` | `data/telemetry/replay_runs/<run_id>` |
| Missing artifact behavior | Usually recoverable by fetching | Fail closed |
| Publish latest surfaces | Yes | No |

## Output Rules

Live outputs belong under `data/output`, including `data/output/runs/<run_id>` and the live publish surfaces under `data/output/latest` and `data/output/injury/normalized/latest.json`.

Replay outputs belong under `data/telemetry/replay_runs/<run_id>`.

Replay must not use `data/output/runs/<run_id>` as its destination. That path is strictly for live model runs.

The replay output folder is where the scored CSVs, replay diagnostics, replay dashboard snapshot, and replay `eval_legs.csv` should be inspected during testing.

## Canonical Replay Command

Use the direct raw replay entrypoint:

```powershell
python -m Atlas.cli replay --raw C:\Users\13142\Atlas\Atlas\data\raw\prizepicks_YYYYMMDD_HHMMSS.json
```

That is the preferred replay path for testing. A bundle is not required when the pinned raw file and matching archive artifacts are already available.

## Required Replay Inputs

Replay should be launched from pinned artifacts only:
1. Raw PrizePicks JSON for the target slate.
2. IAEL invalidations snapshot for the same replay window.
3. IAEL status snapshot for the same replay window.
4. IAEL normalized injury snapshot for the same replay window.
5. Rotowire snapshot for the same replay window.
6. Role-metrics JSON artifact for the replayed model context.

If the pinned artifact set is incomplete, strict replay should stop and report the missing input instead of substituting fresh live data.

## Where The Replay Inputs Live

Use these locations during replay setup:
1. Raw PrizePicks JSON files: `C:\Users\13142\Atlas\Atlas\data\raw`
2. IAEL archive snapshots by date and timestamp: `C:\Users\13142\Atlas\Atlas\data\archives\iael\2026`
3. Historical normalized injury snapshots: `C:\Users\13142\Atlas\Atlas\data\output\injury\normalized`
4. Pinned dashboard role-metrics artifacts: `C:\Users\13142\Atlas\Atlas\data\output\dashboard`
5. Replay output root: `C:\Users\13142\Atlas\Atlas\data\telemetry\replay_runs`
6. Replay truth source: `C:\Users\13142\Atlas\Atlas\data\gamelogs\nba_gamelogs.csv`

The dashboard folder is also the default fallback location for pinned role metrics in replay when explicit role-metrics env paths are not supplied.

## Replay Environment Contract

Strict replay should use pinned environment paths for the non-live inputs:

```powershell
$env:ATLAS_STRICT_REPLAY = "1"
$env:ATLAS_IAEL_INVALIDATIONS_PATH = "C:\Users\13142\Atlas\Atlas\data\archives\iael\2026\<date>\<timestamp>\injury_invalidations.json"
$env:ATLAS_IAEL_STATUS_PATH = "C:\Users\13142\Atlas\Atlas\data\archives\iael\2026\<date>\<timestamp>\status.json"
$env:ATLAS_IAEL_NORMALIZED_PATH = "C:\Users\13142\Atlas\Atlas\data\output\injury\normalized\<timestamp>.json"
$env:ATLAS_ROTOWIRE_LINES_PATH = "C:\Users\13142\Atlas\Atlas\data\archives\iael\2026\<date>\<timestamp>\rotowire_lines.json"
```

Optional explicit role-metrics pins:

```powershell
$env:ATLAS_ROLE_METRICS_PATH = "C:\Users\13142\Atlas\Atlas\data\output\dashboard\role_metrics_latest.json"
$env:ATLAS_ROLE_METRICS_HTML_PATH = "C:\Users\13142\Atlas\Atlas\data\output\dashboard\role_metrics_latest.html"
$env:ATLAS_ROLE_METRICS_MANIFEST_PATH = "C:\Users\13142\Atlas\Atlas\data\output\dashboard\role_metrics_snapshot_manifest.json"
```

If those role-metrics env vars are not provided, strict replay should fall back to the pinned dashboard artifacts above. Replay should not skip role metrics and should not fetch them from a live URL during strict replay.

## Replay Rules

1. Replay exists to test the current model against pinned historical inputs.
2. Replay should use `python -m Atlas.cli replay --raw ...` as the normal entrypoint.
3. Replay should use pinned raw, IAEL, Rotowire, and role-metrics artifacts only.
4. Replay should not quietly substitute fresh live data when a pinned artifact is missing.
5. Replay should not write into `data/output/runs`.
6. Replay should not publish `latest` live surfaces.
7. Replay should use the historical raw payload as the source of truth for slate timing.
8. Replay should fail closed if the pinned artifact set is incomplete.

## Live Run Rules

1. Live run starts from `run.ps1` or `python -m Atlas.cli live`.
2. Live IAEL preflight may refresh injury state and enforce freshness.
3. Live run rebuilds `today.csv` from the freshest raw PrizePicks snapshot.
4. Live run fetches Rotowire lines for the current slate date.
5. Live run fetches or refreshes current role metrics as needed.
6. Live run builds the share matrix after the board and injury state are ready.
7. Live run scores, publishes, and bundles the outputs.
8. Live run writes its run artifacts under `data/output/runs/<run_id>`.

## What To Inspect After A Replay

After a replay finishes, inspect the replay folder under `data/telemetry/replay_runs/<run_id>` for:
1. `scored_legs.csv`
2. `scored_legs_deduped.csv`
3. `eval_legs.csv`
4. replay dashboard snapshot files copied into the run
5. telemetry diagnostics and comparison outputs

Those replay outputs are the testing surface for model tuning. They are the artifacts that should be compared against baseline replay runs when evaluating a model change.

## Practical Rule Of Thumb

If the goal is to place or publish the current slate, use live.

If the goal is to measure, compare, and tune the current model on a pinned historical slate, use replay.

---

## Batch Replay (Corpus Building)

Batch replay re-runs the full Atlas pipeline across many historical dates to build a consistent training/evaluation corpus. This section documents the tooling, common failures, and resolution steps so the process does not require debugging from scratch each time.

### Tools

| Tool | Purpose |
| --- | --- |
| `tools/batch_replay_backfill.py` | Orchestrates per-date replays (bundles + raw JSONs), copies output to D drive corpus and local v13_corpus |
| `tools/build_v16_corpus.py` | Extracts latest v16-kernel runs into clean `data/telemetry/v16_corpus/<YYYYMMDD>/` folder |
| `tools/replay_bundle.py` | Single-bundle replay with `--scenario-id` and optional `--oddsapi-overlay` |

### Batch Replay Architecture

`batch_replay_backfill.py` has two replay paths depending on the source material:

**Bundle path** (Mar 15+): Calls `tools/replay_bundle.py` as a subprocess. The bundle script handles all env setup, extraction, and output routing internally. Output lands in `data/telemetry/replay_runs/<scenario_id>/`.

**Raw JSON path** (early dates without bundles): Sets up all env vars explicitly (ATLAS_OUT_DIR, ATLAS_GAME_DATE, ATLAS_STRICT_REPLAY, IAEL paths, rotowire, gamelogs, external priors) then calls `run_today()` directly via `python -c`. Output lands in `data/telemetry/replay_runs/<scenario_id>/runs/<timestamp>/`.

### Common Failures and Fixes

#### 1. Wrong game_date (legs show today's date instead of replay date)

**Symptom**: `scored_legs_deduped.csv` shows `game_date=2026-04-15` (today) instead of `2026-02-09` (replay date). Players from today's slate appear instead of the historical slate.

**Root cause**: `ATLAS_GAME_DATE` was not set, so the orchestrator fell back to `datetime.now()`. Or: the CLI replay path (`Atlas.cli replay`) was used instead of direct `run_today()` — the CLI overrides `ATLAS_OUT_DIR` on line 639 of `cli.py`, which also disrupts the batch backfill's output routing.

**Fix**: The batch backfill must call `run_today()` directly (not via `Atlas.cli replay`) and must set `ATLAS_GAME_DATE` in the env to the correct date in `YYYY-MM-DD` format. The orchestrator reads it at line 1030 of `orchestrator.py`.

**Verification**: Check the first data row of `scored_legs_deduped.csv` — `game_date` column must match the replay date, not today.

#### 2. Low or wrong leg counts

**Symptom**: A date that should produce 5,000-8,000 scored legs only produces 1,000-1,500.

**Root cause**: Usually the same as #1 — wrong game_date causes the engine to look up the wrong set of games, resulting in fewer player matches after the board is intersected with today's schedule.

**Fix**: Same as #1. Correct the game_date.

**Verification**: Compare `n_scored` against the historical run for that date. Typical full-slate dates produce 3,000-8,000 scored legs.

#### 3. `scored=N` in summary means N files, not N rows

**Symptom**: The backfill summary says `scored=4` which looks like only 4 rows were produced.

**Root cause**: The old counting logic used `rglob("scored_legs_deduped.csv")` which finds ALL versions of the file across multiple old+new timestamp dirs. `len(scored)` counted files, not rows.

**Fix**: The backfill now navigates into `runs/` to find the latest timestamp dir, reads the exact file, and counts rows with `len(pd.read_csv(...))`.

#### 4. CLI replay overrides ATLAS_OUT_DIR

**Symptom**: Output goes to `data/telemetry/replay_runs/<cli_timestamp>/` instead of the batch backfill's scenario dir.

**Root cause**: `Atlas.cli` replay handler (line 639 of `cli.py`) unconditionally sets `ATLAS_OUT_DIR` to its own path, ignoring the env var set by the batch backfill.

**Fix**: Never use `Atlas.cli replay` from batch_replay_backfill.py. Always call `run_today()` directly. The CLI replay path is only for interactive single-date replays.

#### 5. fetch_apis.py contract failures on early dates

**Symptom**: `FETCH CONTRACT FAIL: missing columns` error from `tools/fetch_apis.py` during replay.

**Root cause**: The orchestrator tries to run fetch stages (BettingPros, role metrics) that call `fetch_apis.py`. On very early dates (Feb 8), the external priors CSV may be malformed or the fetch script may not handle the replay context correctly.

**Fix**: Typically date-specific. Check that the IAEL archive, rotowire, and external priors files exist and have the expected schema. For dates where this persists, the date may need to be excluded from the corpus.

### Output Directory Structure

After batch replay, each date lives at:
```
data/telemetry/replay_runs/{corpus_tag}_{YYYYMMDD}/
    runs/
        <YYYYMMDD_HHMMSS>/          # timestamp of replay execution
            scored_legs.csv
            scored_legs_deduped.csv
            eval_legs.csv
            recommended_3leg.csv
            recommended_4leg.csv
            recommended_5leg.csv
            ...
```

The `build_v16_corpus.py` script extracts the latest v16-kernel run from each date into a flat structure:
```
data/telemetry/v16_corpus/
    20260209/
        scored_legs_deduped.csv
        eval_legs.csv
    20260210/
        ...
```

### Kernel Version Verification

v16 kernel output is identified by these columns in `scored_legs_deduped.csv`:
- `blowout_base_min_for_curve`
- `blowout_minute_delta`
- `role_ctx_damp_applied`

If these columns are missing, the output was produced by an older kernel.

### OddsAPI Historical Data

Historical OddsAPI archives live at `data/archives/oddsapi/historical/oddsapi_props_<YYYYMMDD>.csv`. The batch backfill merges these into the external priors CSV via `_build_merged_priors()`. For bundle replays, the `--oddsapi-overlay` flag passes the archive path to `replay_bundle.py`.

Do NOT re-fetch from the OddsAPI — it costs credits. Always use the archived historical files.

### D Drive Corpus

The canonical corpus for leg trainers lives at:
```
data/telemetry/replay_runs/{corpus_tag}_{YYYYMMDD}/
```
The active tag is in `data/telemetry/replay_runs/.corpus_tag`. Each batch auto-generates a timestamped tag (`atlas_replay_YYYYMMDD_HHMMSS`).
Each date dir is a copy of the latest replay timestamp dir. Previous batch runs are preserved (never overwritten).

A local copy is also written to `data/telemetry/v13_corpus/<YYYYMMDD>/` on C drive.

### Checklist: Full Corpus Rebuild

1. Ensure gamelogs are current: `python tools/refresh_nba_gamelogs.py`
2. Ensure IAEL archives exist for all target dates: check `data/archives/iael/2026/`
3. Dry run: `python tools/batch_replay_backfill.py --dry-run`
4. Execute: `python tools/batch_replay_backfill.py --force` (add `--dates YYYYMMDD ...` to target specific dates)
5. Verify: Check summary output — every date should show `scored=3000+` and `eval_legs=3000+`
6. Extract clean corpus: `python tools/build_v16_corpus.py` (use `--dry-run` first)
7. Build resim cache from clean corpus
8. Retrain only through the current tuning plan. As of 2026-05-11, CatBoost v5cD should be revalidated before historical GBM promotion paths are used.
9. Re-run DemonHunter trainer or reapply saved configs (see below)

### After Trainer Changes: Verify Slip/Discord Configs

The GBM trainer does not modify `config.yaml`, but the leg trainer workflow (when auto-applied) can inadvertently clobber the `demonhunter:` section at the bottom of config.yaml. After any trainer-driven config change, verify the `demonhunter:` block still exists in `config.yaml`.

The canonical DemonHunter trainer results are saved in `tools/demonhunter_trainer_results_v4.yaml`. If the config section is missing, reapply from that file.
