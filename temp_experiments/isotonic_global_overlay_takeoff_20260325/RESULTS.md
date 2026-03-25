# Isotonic Global Overlay Takeoff Result

Date: 2026-03-25

## Goal

Test the first post-takeoff calibration challenger against the live guarded hybrid baseline.

Candidate:

1. reader-generated second-stage `isotonic_global_p_cal` overlay
2. staged at `temp_experiments/isotonic_global_overlay_takeoff_20260325/telemetry_calibration.isotonic_global_overlay_takeoff.json`
3. wired through `temp_experiments/isotonic_global_overlay_takeoff_20260325/config.yaml`

## Why this was tested

The four-slate live-hybrid takeoff corpus reader picked this as the top calibration-only lead.

Reader output:

1. corpus root: `temp_experiments/live_hybrid_corpus_takeoff_20260325`
2. reader output: `temp_experiments/live_hybrid_corpus_takeoff_20260325/.atlas_audit/diagnostics/telemetry_corpus/20260325_073616`
3. top candidate: `isotonic_global_p_cal`
4. corpus Brier: `0.221188 -> 0.218652`
5. corpus logloss: `0.670477 -> 0.626252`
6. gate result: `7 / 7` slices passed

## Smoke replay

Representative blocker replay:

1. bundle: `atlas_bundle_20260317_060713.zip`
2. live run: `data/telemetry/replay_runs/live_hybrid_corpus_20260317_bundle/20260325_112242/runs/20260325_062410`
3. challenger run: `data/telemetry/replay_runs/isotonic_global_overlay_takeoff_20260317_bundle/20260325_123815/runs/20260325_073913`

Replay result:

1. live hybrid: brier `0.222412`, logloss `0.633639`, mean p_cal `0.421015`
2. challenger: brier `0.223129`, logloss `0.635286`, mean p_cal `0.413489`
3. delta vs live: brier `+0.000717`, logloss `+0.001648`

## Decision

Do not promote this challenger.

Reason:

1. it is a clean offline corpus calibration lead
2. it does not survive the representative blocker replay
3. the replay regression means it is not safe to replace the live guarded hybrid directly

## Takeaway

The next viable branch should keep the current guarded hybrid behavior on the 2026-03-17 blocker slices and only apply any further isotonic overlay where that blocker slate is not harmed.