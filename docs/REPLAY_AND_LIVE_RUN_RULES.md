# Atlas Live Run and Replay Rules

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
python -m Atlas.cli replay --raw C:\Users\rick\projects\Atlas\data\raw\prizepicks_YYYYMMDD_HHMMSS.json
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
1. Raw PrizePicks JSON files: `C:\Users\rick\projects\Atlas\data\raw`
2. IAEL archive snapshots by date and timestamp: `C:\Users\rick\projects\Atlas\data\archives\iael\2026`
3. Historical normalized injury snapshots: `C:\Users\rick\projects\Atlas\data\output\injury\normalized`
4. Pinned dashboard role-metrics artifacts: `C:\Users\rick\projects\Atlas\data\output\dashboard`
5. Replay output root: `C:\Users\rick\projects\Atlas\data\telemetry\replay_runs`
6. Replay truth source used for eval reconstruction: `C:\Users\rick\projects\Atlas\data\telemetry\Last 10\Last10.csv`

The dashboard folder is also the default fallback location for pinned role metrics in replay when explicit role-metrics env paths are not supplied.

## Replay Environment Contract

Strict replay should use pinned environment paths for the non-live inputs:

```powershell
$env:ATLAS_STRICT_REPLAY = "1"
$env:ATLAS_IAEL_INVALIDATIONS_PATH = "C:\Users\rick\projects\Atlas\data\archives\iael\2026\<date>\<timestamp>\injury_invalidations.json"
$env:ATLAS_IAEL_STATUS_PATH = "C:\Users\rick\projects\Atlas\data\archives\iael\2026\<date>\<timestamp>\status.json"
$env:ATLAS_IAEL_NORMALIZED_PATH = "C:\Users\rick\projects\Atlas\data\output\injury\normalized\<timestamp>.json"
$env:ATLAS_ROTOWIRE_LINES_PATH = "C:\Users\rick\projects\Atlas\data\archives\iael\2026\<date>\<timestamp>\rotowire_lines.json"
```

Optional explicit role-metrics pins:

```powershell
$env:ATLAS_ROLE_METRICS_PATH = "C:\Users\rick\projects\Atlas\data\output\dashboard\role_metrics_latest.json"
$env:ATLAS_ROLE_METRICS_HTML_PATH = "C:\Users\rick\projects\Atlas\data\output\dashboard\role_metrics_latest.html"
$env:ATLAS_ROLE_METRICS_MANIFEST_PATH = "C:\Users\rick\projects\Atlas\data\output\dashboard\role_metrics_snapshot_manifest.json"
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