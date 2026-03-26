# Telemetry Takeoff 2026-03-26

## Canonical baseline
- Live config path: `config.yaml`
- Live telemetry artifact path: `data/model/telemetry_calibration.isotonic_hybrid_protect_role_ctx_on.json`
- Frozen baseline snapshot: `data/model/telemetry_calibration.isotonic_hybrid_protect_role_ctx_on.20260326_live_baseline.json`
- Runtime mode: protected isotonic hybrid calibration on top of the promoted structural blowout branch

## What is live right now
### Telemetry config knobs
- `telemetry.schema_version: 2`
- `telemetry.active_calibration: isotonic_hybrid_protect_role_ctx_on`
- `telemetry.apply_active_calibration: true`
- `telemetry.active_calibration_path: data/model/telemetry_calibration.isotonic_hybrid_protect_role_ctx_on.json`
- `telemetry.calibration_policy.allow_family_split: true`
- `telemetry.calibration_policy.family_order: [role_off, role_on]`
- `telemetry.calibration_policy.strict_source_gating: true`

### Base probability / under-relief knobs
- `under_relief_factor: 0.11`
- `under_relief_haircut_min: 0.06`
- `under_relief_q_min: 0.12`

### Structural blowout knobs now live
- `spread_sd: 10.0`
- `threshold_margin: 15.5`
- `star_minute_drop: 0.12`
- `role_minute_drop: 0.18`
- targeted `adjustment_rules` on:
  - combo-scoring `OVER`, `q_blowout > 0.35`, starter-like
  - assists `OVER`, `q_blowout > 0.35`, with the narrower March 26 AST-only strengthening (`minute_drop_mult 0.76`, `sensitivity_mult 0.88`)
  - threes `OVER`, `q_blowout > 0.35`
  - rebounds `OVER`, `0.20 < q_blowout <= 0.30`

## Why this is the takeoff point
- This is the first replay-validated baseline that improves both the upstream blowout surface and the downstream calibrated surface without giving back raw `p_adj`.
- The March 26 promotion combined two changes that were each validated before going live:
  - structural blowout softening in the kernel through targeted `adjustment_rules`
  - a corrected stacked `isotonic_hybrid_protect_role_ctx_on` payload that preserves `pre_calibration`

## Promotion evidence
### Truth-backed bundle evidence
- `atlas_bundle_20260317_060713.zip`:
  - prior target config: `brier_p_adj 0.236504`, `brier_p_cal 0.218571`
  - promoted baseline: `brier_p_adj 0.234749`, `brier_p_cal 0.218266`
- `atlas_bundle_20260318_173935.zip`:
  - prior target config: `brier_p_adj 0.219035`, `brier_p_cal 0.215405`
  - promoted baseline: `brier_p_adj 0.218347`, `brier_p_cal 0.213472`
- aggregate truth-backed effect:
  - `p_adj`: `0.226756 -> 0.225597`
  - `p_cal`: `0.216804 -> 0.215591`

### Preserved live-surface evidence
- 2026-03-23 strict replay:
  - original live probabilities: `0.242612 / 0.233384`
  - promoted calibration-only baseline: `0.239062 / 0.227725`
  - promoted structural baseline: `0.237019 / 0.225511`
- 2026-03-24 strict replay:
  - original live probabilities on overlap: `0.242463 / 0.241760`
  - promoted calibration-only baseline: `0.230939 / 0.222564`
  - promoted structural baseline: `0.229967 / 0.221364`

### Narrow follow-up now promoted
- Broad v3 follow-up (`combo_scoring` mid-high-q plus stronger `FG3M` and `AST` high-q) improved raw but regressed preserved-live calibrated Brier overall, so it was rejected.
- Narrow v4 keeping only the stronger high-q `AST OVER` adjustment cleared the preserved-live gate without reopening the March 24 regression:
  - 2026-03-23 strict replay: `0.237019 / 0.225511` -> `0.236987 / 0.225482`
  - 2026-03-24 strict replay: `0.229967 / 0.221364` -> `0.229948 / 0.221370`
  - aggregate matched-leg effect: `0.233853 / 0.223650` -> `0.233828 / 0.223636`
- Practical interpretation: this is a tiny but safe structural improvement, so the live baseline now includes the stronger high-q assists rule and nothing else from the rejected v3 branch.

## What is inside the live telemetry artifact
### Outer layer
- `mode: isotonic_hybrid`
- `candidate: isotonic_hybrid_protect_role_ctx_on`
- `meta.source_col: p_cal`
- protected context: `role_on`
- payload source: `.atlas_audit/diagnostics/telemetry_corpus/20260326_125802/proposed_calibration.json`

### Nested base telemetry layer
- `pre_calibration` is present and runtime-valid
- source-gated v2 telemetry remains bounded to `p_adj`-derived sources

## Tuning objective from here
- Treat this March 26 baseline as the canonical starting space for the next descent.
- Primary goal remains calibrated Brier below `0.20` on settled replay corpora.
- Preserve the current raw and calibrated wins on the promoted structural blowout surface.

## Recommended next tuning order
1. Build a broader settled corpus on this promoted baseline instead of reusing the earlier two-run reader evidence as if it were still current.
2. Audit residual miss slices on the promoted structural surface, especially high-q `OVER` rows where the scoped reader candidates helped but failed current regime gates.
3. Only revisit upstream blowout parameters after the broader corpus shows a repeatable residual miss, not as another blind config sweep.
4. Keep selector work frozen unless a new model branch materially changes the candidate pool.

## Reference artifacts
- Live artifact:
  - `data/model/telemetry_calibration.isotonic_hybrid_protect_role_ctx_on.json`
- Frozen artifact:
  - `data/model/telemetry_calibration.isotonic_hybrid_protect_role_ctx_on.20260326_live_baseline.json`
- Structural replay config:
  - `temp_experiments/blowout_structural_over_v1_iso_hybrid_rolectx_on_20260326/config.yaml`
- Narrow promoted follow-up config:
  - `temp_experiments/blowout_structural_over_v4_ast_only_20260326.yaml`
- Correct reader output:
  - `.atlas_audit/diagnostics/telemetry_corpus/20260326_125802/proposed_calibration.json`