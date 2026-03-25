# Pipeline Diagnostics

Date: 2026-03-25
Purpose: audit the active runtime from fetch through slip building, then verify which config and telemetry knobs are truly active.

## Active Path

1. The active replay/live scoring path runs through [src/Atlas/engine/main.py](src/Atlas/engine/main.py), not the `NewEngine` class wrapper.
2. `main.py` calls `_run_score_board_new(...)` from [src/Atlas/engine/new_engine.py](src/Atlas/engine/new_engine.py), then applies telemetry calibration in `main.py`, then calls prep and slip building.
3. The `NewEngine` class in [src/Atlas/engine/new_engine.py](src/Atlas/engine/new_engine.py) contains an additional legacy `last10` calibration mutation path, but that class is not instantiated by the active `main.py` runtime.

## Fetch Layer Findings

1. [src/Atlas/stages/fetch/fetch_prizepicks_today.py](src/Atlas/stages/fetch/fetch_prizepicks_today.py) claims no printing, but still emits a slate-gate summary with `print(...)` when rows are dropped.
2. The fetch stage applies two started-game gates:
   - CT-date/start-time gate using `dt_start_ct < now_ct`
   - later UTC gate using `dt < now_utc`
3. The duplicate time gate is probably harmless, but it increases the chance of subtle replay/live drift if one branch is changed later and the other is not.

## Probability And Calibration Findings

1. The active replay baseline materially calibrates probabilities.
2. On the locked selector baseline replay:
   - `p_cal` changed on all `4469` rows relative to `p_for_cal`
   - mean delta `p_cal - p_for_cal`: `+0.094878`
   - mean absolute delta: `0.132824`
3. Every row in that replay had `p_cal_src = p_adj`, so the active telemetry policy is currently operating entirely on the blowout-adjusted channel, not a role-on split channel.
4. The active telemetry JSON in [data/model/telemetry_calibration.v2.json](data/model/telemetry_calibration.v2.json) is strong, not mild:
   - `k_shrink = 0.34`
   - `standard_under_penalty = 1.02`
   - stat-direction multipliers range roughly `0.834` to `1.2064`
5. The field name `standard_under_penalty` is misleading in the current payload because `1.02` boosts standard unders instead of penalizing them.

## Telemetry Config Wiring Findings

1. `telemetry.apply_active_calibration` was previously ignored by the active runtime. That has now been fixed in [src/Atlas/engine/main.py](src/Atlas/engine/main.py), and the current `true` setting preserves existing behavior.
2. `telemetry.active_calibration` is currently name-only in `config.yaml`; runtime reads `active_calibration_path`, not `active_calibration`.
3. The nested `telemetry.calibration_policy` flags in [config.yaml](config.yaml) are not consumed by runtime code:
   - `allow_family_split`
   - `family_order`
   - `strict_source_gating`
4. Source gating is actually driven by the calibration JSON policy payload itself, not by `config.yaml`.

## Under-Relief And Telemetry Coupling Findings

1. The top-level under-relief keys were initially inert because the active kernel only consumed `role_ctx` config. That wiring bug has already been fixed.
2. The telemetry JSON contains a family named `p_adj_under_relief_cool` with source prefix `p_adj_under_relief`.
3. That family was initially inert because [src/Atlas/engine/main.py](src/Atlas/engine/main.py) only emitted `p_cal_src` as `p_adj` or `p_role`.
4. The active path now emits `p_adj_under_relief` for rows where `under_relief_applied` is true and the calibration source is still the `p_adj` surface.
5. On the 2026-03-17 replay, that activated the source-scale family on exactly `496` rows and reduced the average calibration gap on those rows:
   - under-relief rows abs mean `|p_cal - p_for_cal|`: `0.187229 -> 0.110246`
6. Recommendation membership still did not change on that replay, but the reported slip probabilities cooled materially.

## Builder Findings

1. The builder phase knobs are live:
   - `slip_build.target_pool_mult`
   - `slip_build.phase1_frac`
   - `slip_build.phase1_pool_frac`
   - `slip_build.beam_width`
2. The current selector path in [src/Atlas/core/slip_builders.py](src/Atlas/core/slip_builders.py) originally preferred `p_for_cal` ahead of `p_cal` for `p_eff`.
3. That meant telemetry-calibrated probabilities could materially change audit columns while selection still ranked on the pre-calibration surface.
4. A narrow experiment knob has now been added:
   - `slip_build.prefer_calibrated_prob`
5. When enabled, the builder prefers `p_cal` before `p_for_cal`.

## Calibrated-Probability Replay Result

Experiment config:

1. [temp_experiments/prefer_calibrated_prob_20260324/config.yaml](temp_experiments/prefer_calibrated_prob_20260324/config.yaml)

Compared runs:

1. current selector baseline:
   - `data/telemetry/replay_runs/roleblend_selector_current_compare_20260317_bundle/20260324_234000/runs/20260324_184051`
2. calibrated-probability selector candidate:
   - `data/telemetry/replay_runs/roleblend_prefer_calibrated_prob_20260317_bundle/20260325_002627/runs/20260324_192720`

Result:

1. Replay completed successfully.
2. `scored_legs_deduped.csv` row count stayed identical: `4469 -> 4469`
3. `eval_legs.csv` row count stayed identical: `4469 -> 4469`
4. Recommendation membership did not change on this replay:
   - `10 / 10` overlap across all six recommendation families
5. Reported slip probabilities and EV changed materially downward on the same slips.

Interpretation:

1. On this replay, calibrated-surface selection is not changing the chosen portfolios.
2. It is changing the reported probability surface a lot.
3. That means the current telemetry calibration is better treated first as a probability-quality question, not as a portfolio-turnover lever.

## Highest-Value Next Diagnostics

1. Decide whether `p_cal_src` should emit `p_adj_under_relief` when under-relief is applied so the telemetry source-scale family can actually activate.
2. Measure recommendation-level Brier/log loss on a small replay corpus to determine whether the calibrated-surface selector improves probability quality even when slip membership stays fixed.
3. Audit whether the active telemetry payload is too aggressive for live ranking because its shrink/multiplier stack is very large relative to the raw `p_for_cal` surface.