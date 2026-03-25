# Guarded Isotonic Overlay Result

Date: 2026-03-25

## Goal

Stage a second-stage isotonic overlay that keeps the live guarded hybrid unchanged on known blocker slices and only applies the added isotonic map elsewhere.

This branch is experimental only.

Promotion is blocked unless a candidate:

1. gets Brier under `0.20`
2. does not drop logloss
3. improves realized hit-rate behavior and deltas

## Artifact design

Path: `temp_experiments/isotonic_global_overlay_guarded_20260325/telemetry_calibration.isotonic_global_overlay_guarded.json`

Structure:

1. outer mode: `isotonic_hybrid`
2. outer mix: `1.0`
3. outer curve: reader-derived `isotonic_global_p_cal` fit on the four-slate takeoff corpus
4. pre-calibration: current live `isotonic_hybrid_roleoff_guarded`
5. protected slices: current live blocker set on `role_off`
6. protected calibration: `keep_identity`

Interpretation:

1. protected slices keep the live hybrid output exactly
2. non-protected slices receive the second-stage isotonic overlay

## Validation

Runtime unit tests:

1. `c:/Users/rick/projects/Atlas/.venv/Scripts/python.exe -m unittest tests.test_telemetry_runtime_calibration`
2. result: `OK` (`5` tests)

## Representative blocker replay

Bundle: `atlas_bundle_20260317_060713.zip`

Runs:

1. live: `data/telemetry/replay_runs/live_hybrid_corpus_20260317_bundle/20260325_112242/runs/20260325_062410`
2. guarded overlay: `data/telemetry/replay_runs/isotonic_global_overlay_guarded_20260317_bundle/20260325_124636/runs/20260325_074758`

Result:

1. live hybrid: brier `0.222412`, logloss `0.633639`
2. guarded overlay: brier `0.222311`, logloss `0.633143`
3. delta vs live: brier `-0.000101`, logloss `-0.000495`

## Validation replay

Bundle: `atlas_bundle_20260318_173935.zip`

Runs:

1. live reference: `data/telemetry/replay_runs/live_hybrid_verify_true_20260318_bundle/20260325_111823/runs/20260325_061935`
2. guarded overlay: `data/telemetry/replay_runs/isotonic_global_overlay_guarded_20260318_bundle/20260325_124828/runs/20260325_074938`

Result:

1. live hybrid: brier `0.215050`, logloss `0.693627`
2. guarded overlay: brier `0.213957`, logloss `0.690780`
3. delta vs live: brier `-0.001093`, logloss `-0.002847`

## Combined 2026-03-17 / 2026-03-18 view

Weighted by settled rows:

1. live pair: brier `0.218511`, logloss `0.665428`
2. guarded pair: brier `0.217884`, logloss `0.663686`
3. delta vs live: brier `-0.000627`, logloss `-0.001742`

## Recommendation-side notes

This pass does not yet show the evidence needed for promotion.

Observed state:

1. recommendation hit-prob deltas are small
2. winprob recommendation files are unchanged on both slates
3. realized recommendation hit-rate improvement has not yet been demonstrated from these two replays alone

## Decision

Keep staged, do not promote.

Reason:

1. the guarded overlay is directionally better than live on both validation slates
2. it repairs the blocker-slate failure of the unguarded overlay
3. it still does not meet the required promotion bar because Brier remains above `0.20` and realized hit-rate gains are not yet established

## Next step

Use this guarded overlay as a staged challenger for wider replay evaluation only if the next pass focuses on proving realized hit-rate and delta improvements rather than calibration alone.