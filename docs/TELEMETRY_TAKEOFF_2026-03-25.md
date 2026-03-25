# Telemetry Takeoff 2026-03-25

## Canonical baseline
- Live config path: `config.yaml`
- Live telemetry artifact path: `data/model/telemetry_calibration.isotonic_hybrid_roleoff_guarded.json`
- Frozen baseline snapshot: `data/model/telemetry_calibration.isotonic_hybrid_roleoff_guarded.20260325_live_baseline.json`
- Runtime mode: stacked isotonic hybrid calibration that preserves the live curve on protected `role_off` slices and applies the broader `0.75` blend elsewhere

## Why this is the takeoff point
- This is the first runtime-valid calibration artifact that reproduced the offline isotonic win inside the actual replay path.
- The key fix was stacking isotonic on top of the live telemetry surface rather than replacing raw `p_for_cal` directly.
- Representative replay evidence on `atlas_bundle_20260317_060713.zip`:
  - `brier_p_cal`: `0.23532059096548347 -> 0.22229187357789862`
  - `logloss_p_cal`: `0.6624725715370446 -> 0.6329850280564892`
  - `mean_p_cal`: `0.3846644326713607 -> 0.4250703630669369`

## What is live right now
### Telemetry config knobs
- `telemetry.schema_version: 2`
- `telemetry.active_calibration: isotonic_hybrid_roleoff_guarded`
- `telemetry.apply_active_calibration: true`
- `telemetry.active_calibration_path: data/model/telemetry_calibration.isotonic_hybrid_roleoff_guarded.json`
- `telemetry.calibration_policy.allow_family_split: true`
- `telemetry.calibration_policy.family_order: [role_off, role_on]`
- `telemetry.calibration_policy.strict_source_gating: true`

### Base probability / under-relief knobs
- `under_relief_factor: 0.11`
- `under_relief_haircut_min: 0.06`
- `under_relief_q_min: 0.12`

### Slip-build knobs currently live
- `slip_build.target_pool_mult: 200`
- `slip_build.phase1_frac: 0.2`
- `slip_build.phase1_pool_frac: 0.5`
- `slip_build.beam_width: 250`
- `optimizer.top_n_slips: 10`
- `optimizer.seed: 7`

## What is inside the live telemetry artifact
### Outer layer
- `mode: isotonic_hybrid`
- `candidate: isotonic_hybrid_roleoff_guarded`
- `meta.source_col: p_cal`
- main curve: broader settled-corpus isotonic blend with `mix: 0.75`
- protected curve: the prior live `isotonic_global_p_cal`
- protected role-context: `role_off`
- protected stat-direction keys: `PRA|OVER`, `PR|OVER`, `PA|OVER`, `RA|OVER`, `PTS|OVER`, `AST|UNDER`, `PTS|UNDER`, `REB|UNDER`, `PA|UNDER`, `PRA|UNDER`, `PR|UNDER`

### Nested base telemetry layer
- `version: 2`
- `policy.apply_only_p_cal_src_prefixes: [p_adj]`
- `policy.cap.min/max: 0.01 / 0.99`
- `base.k_shrink: 0.34`
- `base.standard_under_penalty: 1.02`
- role families:
  - `role_off`
  - `role_on`
- source-scale family:
  - `p_adj_under_relief_cool.scale: 0.9`

## Tuning objective from here
- Treat this baseline as the canonical starting space for further telemetry calibration work.
- Primary calibration goal: drive median corpus Brier below `0.20`.
- Secondary realized-performance goal: drive median hit rate to at least whole-percent `25%` or better on the chosen evaluation surface.
- Preserve the current improvement on the large `OVER` slices while avoiding new collapses on thin `UNDER` slices.

## Rules for iteration from this point
- Do not edit the frozen baseline snapshot.
- Keep the live working artifact path mutable, but regenerate a new frozen snapshot for any candidate that becomes the next baseline.
- If the underlying v2 telemetry base changes, the stacked isotonic artifact must be regenerated rather than reused blindly.
- Prefer representative replay or small settled corpus checks first; reserve broader backtests for finalists.
- Compare all challengers against this exact baseline, not against older soft90-only or role-aware branches.

## Recommended next tuning order
1. Tune the hybrid protection list and protection strength rather than reverting to fully global curves.
2. Search for the next artifact family or knob that improves both the protected `role_off` slices and the 2026-03-18 high-confidence tail.
3. Revisit source-gated family weights only after the hybrid baseline stabilizes across a broader corpus.
4. Keep role-aware extensions bounded; the preserved `role_on_blend_0.05` branch already regressed on the representative replay.

## Reference artifacts
- Representative promoted replay diagnostics:
  - `temp_experiments/isotonic_runtime_smoke_20260325/.atlas_audit/diagnostics/telemetry_calibration_diagnostic/20260325_023915/diagnostic_summary.json`
  - `temp_experiments/isotonic_runtime_smoke_20260325/.atlas_audit/diagnostics/telemetry_calibration_diagnostic/20260325_023915/per_run_diagnostics.csv`
- Prior soft90 baseline reference:
  - `temp_experiments/small_corpus_under_relief_20260325/soft90/.atlas_audit/diagnostics/telemetry_calibration_diagnostic/20260325_014640/per_run_diagnostics.csv`