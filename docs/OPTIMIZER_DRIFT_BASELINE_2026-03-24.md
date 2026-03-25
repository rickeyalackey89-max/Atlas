# Optimizer Drift Baseline

Date: 2026-03-24
Purpose: Step 1 baseline for the approved next-steps plan.

## Compared Runs

Current replay candidate:

1. `data/telemetry/replay_runs/roleblend_current_vs_baseline_20260317_bundle/20260324_225732/runs/20260324_175821`

Prior replay control:

1. `data/telemetry/replay_runs/roleblend_current_vs_baseline_20260317_bundle/20260324_140826/runs/20260324_092632`

## Core Replay Eval Stability

These values were unchanged between the two runs.

1. `scored_legs_deduped.csv` rows: `4469 -> 4469`
2. `matched_rows`: `3957 -> 3957`
3. `unmatched_rows`: `512 -> 512`
4. `match_rate`: `0.8854329827701947 -> 0.8854329827701947`
5. hits: `1682 -> 1682`
6. misses: `2275 -> 2275`

Interpretation:

1. Replay fidelity and truth coverage are stable.
2. The current drift is in recommendation selection, not in eval reconstruction.

## Recommendation Count Change

The recommendation files changed from `25` rows to `10` rows because the intended slip target was restored.

1. `recommended_3leg.csv`: `25 -> 10`
2. `recommended_4leg.csv`: `25 -> 10`
3. `recommended_5leg.csv`: `25 -> 10`
4. `recommended_3leg_winprob.csv`: `25 -> 10`
5. `recommended_4leg_winprob.csv`: `25 -> 10`
6. `recommended_5leg_winprob.csv`: `25 -> 10`

## Top-10-Only Overlap

To remove the `25 -> 10` count distortion, compare current top `10` against previous top `10` only.

Result:

1. `recommended_3leg.csv`: overlap `0 / 10`
2. `recommended_4leg.csv`: overlap `0 / 10`
3. `recommended_5leg.csv`: overlap `0 / 10`
4. `recommended_3leg_winprob.csv`: overlap `0 / 10`
5. `recommended_4leg_winprob.csv`: overlap `0 / 10`
6. `recommended_5leg_winprob.csv`: overlap `0 / 10`

Interpretation:

1. Recommendation drift is not explained only by restoring `top_n_slips = 10`.
2. Even on an apples-to-apples top-10 basis, the selector turned over completely.

## Top-10 Recommendation Metrics

### System EV files

1. `recommended_3leg.csv`
   - previous top-10 avg hit_prob: `0.17`
   - current top-10 avg hit_prob: `0.28`
   - delta: `+0.11`
   - previous top-10 avg ev_mult: `1.10`
   - current top-10 avg ev_mult: `2.20`
   - delta: `+1.10`
   - previous top-1 hit_prob: `0.19`
   - current top-1 hit_prob: `0.29`

2. `recommended_4leg.csv`
   - previous top-10 avg hit_prob: `0.08`
   - current top-10 avg hit_prob: `0.18`
   - delta: `+0.10`
   - previous top-10 avg ev_mult: `0.63`
   - current top-10 avg ev_mult: `1.74`
   - delta: `+1.11`
   - previous top-1 hit_prob: `0.08`
   - current top-1 hit_prob: `0.21`

3. `recommended_5leg.csv`
   - previous top-10 avg hit_prob: `0.04`
   - current top-10 avg hit_prob: `0.14`
   - delta: `+0.10`
   - previous top-10 avg ev_mult: `0.43`
   - current top-10 avg ev_mult: `1.59`
   - delta: `+1.16`
   - previous top-1 hit_prob: `0.05`
   - current top-1 hit_prob: `0.18`

### Winprob files

1. `recommended_3leg_winprob.csv`
   - previous top-10 avg hit_prob: `0.17`
   - current top-10 avg hit_prob: `0.34`
   - delta: `+0.17`
   - previous top-10 avg ev_mult: `1.02`
   - current top-10 avg ev_mult: `2.02`
   - delta: `+1.00`
   - previous top-1 hit_prob: `0.19`
   - current top-1 hit_prob: `0.36`

2. `recommended_4leg_winprob.csv`
   - previous top-10 avg hit_prob: `0.08`
   - current top-10 avg hit_prob: `0.22`
   - delta: `+0.14`
   - previous top-10 avg ev_mult: `0.83`
   - current top-10 avg ev_mult: `2.25`
   - delta: `+1.42`
   - previous top-1 hit_prob: `0.09`
   - current top-1 hit_prob: `0.25`

3. `recommended_5leg_winprob.csv`
   - previous top-10 avg hit_prob: `0.04`
   - current top-10 avg hit_prob: `0.16`
   - delta: `+0.12`
   - previous top-10 avg ev_mult: `0.81`
   - current top-10 avg ev_mult: `3.20`
   - delta: `+2.39`
   - previous top-1 hit_prob: `0.05`
   - current top-1 hit_prob: `0.18`

## Interpretation Guardrail

These stronger current top-10 metrics do not prove the selector is better yet.

Why not:

1. the recommendation set turned over completely
2. the selector behavior changed materially
3. current averages are being compared across different recommendation sets
4. no small-corpus or reader verdict has confirmed this as a stable improvement

## Current Attribution Hypothesis

The remaining plausible drift drivers are:

1. beam window default decoupling from `target_pool_mult`
2. greedy top-off fallback after beam stall
3. approved beam width increase from `200` to `250`

`top_n_slips = 10` restoration is not enough by itself to explain the drift, because top-10 vs top-10 overlap is still zero.

## Next Planned Experiment

The next experiment should isolate approved beam width sensitivity first, because it is already explicitly approved and easy to vary without conflating unapproved structural changes.

Recommended immediate comparison:

1. current logic with `beam_width = 200`
2. current logic with `beam_width = 250`

Record for both:

1. runtime
2. completion behavior
3. top-10 overlap versus current control
4. top recommendation hit_prob and ev metrics

After that, isolate greedy top-off fallback and beam-window decoupling one at a time.

## Beam Width Sensitivity Result

Experiment run date: 2026-03-24

Compared runs:

1. beam `250` control:
   - `data/telemetry/replay_runs/roleblend_beam250_compare_20260317_bundle/20260324_231807/runs/20260324_181858`
2. beam `200` candidate:
   - `data/telemetry/replay_runs/roleblend_beam200_compare_20260317_bundle/20260324_231912/runs/20260324_182003`

Result:

1. Both runs completed successfully.
2. Runtime was effectively identical:
   - beam `250`: `53.48s`
   - beam `200`: `53.53s`
3. Replay eval reconstruction was identical.
4. Recommendation overlap was complete across all compared files:
   - `10 / 10` overlap for every recommendation family
5. Recommendation metrics were identical across all compared files.

Interpretation:

1. The approved beam-width difference `200 vs 250` is not the source of the observed recommendation drift.
2. The remaining likely drift drivers are still:
   - beam window default decoupling
   - greedy top-off fallback
3. Keeping `beam_width = 250` is reasonable because it did not worsen runtime or selection on this replay.

## Greedy Top-Off Sensitivity Result

Experiment run date: 2026-03-24

Compared runs:

1. top-off enabled control:
   - `data/telemetry/replay_runs/roleblend_topoff_on_compare_20260317_bundle_rerun/20260324_233208/runs/20260324_183259`
2. top-off disabled candidate:
   - `data/telemetry/replay_runs/roleblend_topoff_off_compare_20260317_bundle/20260324_233101/runs/20260324_183152`

Result:

1. Both runs completed successfully.
2. Runtime was essentially unchanged:
   - top-off on: `54.18s`
   - top-off off: `53.13s`
3. Replay eval reconstruction was identical.
4. Recommendation overlap was complete across all compared files:
   - `10 / 10` overlap for every recommendation family
5. Recommendation metrics were identical across all compared files.

Interpretation:

1. Greedy top-off fallback is not the source of the observed recommendation drift on this replay.

## Legacy Beam-Window Sensitivity Result

Experiment run date: 2026-03-24

Compared runs:

1. current beam-window behavior control:
   - `data/telemetry/replay_runs/roleblend_window_current_compare_20260317_bundle/20260324_233349/runs/20260324_183443`
2. legacy tied-window candidate:
   - `data/telemetry/replay_runs/roleblend_window_legacy_compare_20260317_bundle/20260324_233447/runs/20260324_183747`

Result:

1. Both runs completed successfully.
2. Runtime changed materially:
   - current window logic: `56.78s`
   - legacy tied-window logic: `183.06s`
3. Replay eval reconstruction was identical.
4. Recommendation overlap was complete across all compared files:
   - `10 / 10` overlap for every recommendation family
5. Recommendation metrics were identical across all compared files.

Interpretation:

1. Beam-window default decoupling is not the source of the observed recommendation drift on this replay.
2. The current window logic should be preferred on runtime grounds because it preserves outputs while cutting replay time materially.

## Updated Attribution Status

The following candidates have now been cleared on this replay:

1. beam width `200 vs 250`
2. greedy top-off fallback on vs off
3. legacy tied-window defaults vs current window defaults

That means the remaining drift source is likely elsewhere in `src/Atlas/core/slip_builders.py`, most plausibly in ranking or probability-preference behavior rather than beam-search breadth alone.

## Selector Scoring Sensitivity Result

Experiment run date: 2026-03-24

Compared runs:

1. current selector behavior control:
   - `data/telemetry/replay_runs/roleblend_selector_current_compare_20260317_bundle/20260324_234000/runs/20260324_184051`
2. legacy selector-scoring candidate:
   - `data/telemetry/replay_runs/roleblend_selector_legacy_compare_20260317_bundle/20260324_234054/runs/20260324_184147`

Result:

1. Both runs completed successfully.
2. Runtime stayed in the same range:
   - current selector: `53.96s`
   - legacy selector: `55.85s`
3. Replay eval reconstruction was identical.
4. Recommendation overlap was zero across all compared files:
   - `0 / 10` overlap for every recommendation family
5. Recommendation metrics changed materially.

### Current selector vs legacy selector metrics

1. `recommended_3leg.csv`
   - current avg hit_prob: `0.28`
   - legacy avg hit_prob: `0.22`
   - current avg ev_mult: `2.20`
   - legacy avg ev_mult: `1.18`

2. `recommended_4leg.csv`
   - current avg hit_prob: `0.18`
   - legacy avg hit_prob: `0.11`
   - current avg ev_mult: `1.74`
   - legacy avg ev_mult: `0.68`

3. `recommended_5leg.csv`
   - current avg hit_prob: `0.14`
   - legacy avg hit_prob: `0.05`
   - current avg ev_mult: `1.59`
   - legacy avg ev_mult: `0.46`

4. `recommended_3leg_winprob.csv`
   - current avg hit_prob: `0.34`
   - legacy avg hit_prob: `0.23`

5. `recommended_4leg_winprob.csv`
   - current avg hit_prob: `0.22`
   - legacy avg hit_prob: `0.11`

6. `recommended_5leg_winprob.csv`
   - current avg hit_prob: `0.16`
   - legacy avg hit_prob: `0.05`

Interpretation:

1. Selector scoring and ranking behavior is the first isolated change that actually explains the recommendation drift.
2. Beam width, greedy top-off, and beam-window defaults were not the driver on this replay.
3. The dominant remaining source is the newer selector path in `src/Atlas/core/slip_builders.py`, especially:
   - probability preference used to derive `p_eff`
   - role-on override of `p_eff`
   - allocator-score-based ranking
   - role-bonus contribution to `score_adj`

## Practical Baseline Decision

For this replay, the data supports using the current selector path as the working baseline for the next phase, because:

1. it is the only isolated change that materially changes the recommendations
2. it improves the recommendation metrics materially on this replay
3. runtime remains acceptable

This is a working baseline decision for continued candidate testing, not final promotion proof. Final promotion still requires the planned small-corpus and reader-backed evaluation ladder.

## Under-Relief Candidate Wiring Result

Experiment run date: 2026-03-24

Compared runs:

1. current selector control:
   - `data/telemetry/replay_runs/roleblend_selector_current_compare_20260317_bundle/20260324_234000/runs/20260324_184051`
2. under-relief candidate after wiring fix:
   - `data/telemetry/replay_runs/roleblend_under_relief_candidate_20260317_bundle/20260324_235158/runs/20260324_185253`

Wiring note:

1. The top-level `under_relief_*` keys in `config.yaml` were loading correctly but were inert in the active replay path.
2. Root cause: `src/Atlas/engine/new_engine.py` was only passing `cfg.get("role_ctx")` into `simulate_leg_probability_new`, and `src/Atlas/engine/new_probability.py` reads under-relief settings from that narrowed config object.
3. Fix applied: forward top-level `under_relief_factor`, `under_relief_haircut_min`, and `under_relief_q_min` into the kernel config without implicitly enabling the broader role-context layer.

Result:

1. Replay completed successfully.
2. Recommendation membership was unchanged across all compared files:
   - `10 / 10` overlap for every recommendation family
3. Recommendation probabilities moved slightly within the same slip sets.
4. Under-relief application changed at the row level:
   - applied rows: `512 -> 496`
   - average applied factor: `0.1000 -> 0.1100`
   - average applied haircut: `0.1805 -> 0.1846`
   - average applied lift: `0.0024 -> 0.0028`

Interpretation:

1. The under-relief candidate is now active.
2. On this replay, the approved `0.11 / 0.06 / 0.12` candidate is too small to change the actual recommended slip sets.
3. The next under-relief experiment should be a larger, explicitly approved step if we want a realistic chance of changing portfolio selection on replay.

## Calibrated-Probability Selector Result

Experiment run date: 2026-03-25

Compared runs:

1. current selector control:
   - `data/telemetry/replay_runs/roleblend_selector_current_compare_20260317_bundle/20260324_234000/runs/20260324_184051`
2. calibrated-probability selector candidate:
   - `data/telemetry/replay_runs/roleblend_prefer_calibrated_prob_20260317_bundle/20260325_002627/runs/20260324_192720`

Config note:

1. Added `slip_build.prefer_calibrated_prob` as a narrow experiment knob.
2. When enabled, the builder prefers `p_cal` ahead of `p_for_cal` when deriving `p_eff`.

Result:

1. Replay completed successfully.
2. Replay eval reconstruction was identical.
3. Recommendation membership was unchanged across all compared files:
   - `10 / 10` overlap for every recommendation family
4. Recommendation metrics moved materially downward on the same slip sets.

### Current selector vs calibrated-probability selector metrics

1. `recommended_3leg.csv`
   - current avg hit_prob: `0.28`
   - calibrated avg hit_prob: `0.22`
   - current avg ev_mult: `2.20`
   - calibrated avg ev_mult: `1.18`

2. `recommended_4leg.csv`
   - current avg hit_prob: `0.18`
   - calibrated avg hit_prob: `0.11`
   - current avg ev_mult: `1.74`
   - calibrated avg ev_mult: `0.68`

3. `recommended_5leg.csv`
   - current avg hit_prob: `0.14`
   - calibrated avg hit_prob: `0.05`
   - current avg ev_mult: `1.59`
   - calibrated avg ev_mult: `0.46`

4. `recommended_3leg_winprob.csv`
   - current avg hit_prob: `0.34`
   - calibrated avg hit_prob: `0.23`

5. `recommended_4leg_winprob.csv`
   - current avg hit_prob: `0.22`
   - calibrated avg hit_prob: `0.11`

6. `recommended_5leg_winprob.csv`
   - current avg hit_prob: `0.16`
   - calibrated avg hit_prob: `0.05`

Interpretation:

1. Preferring the calibrated surface changes the reported slip probabilities a lot.
2. On this replay, it does not change the actual selected portfolios.
3. That makes this a probability-quality and reader-evaluation question, not a portfolio-drift explanation for this slate.

## Under-Relief Source-Label Result

Experiment run date: 2026-03-25

Compared runs:

1. under-relief candidate before source-label fix:
   - `data/telemetry/replay_runs/roleblend_under_relief_candidate_20260317_bundle/20260324_235158/runs/20260324_185253`
2. under-relief candidate after source-label fix:
   - `data/telemetry/replay_runs/roleblend_under_relief_srclabel_20260317_bundle/20260325_003736/runs/20260324_193830`

Code note:

1. [src/Atlas/engine/main.py](src/Atlas/engine/main.py) and [src/Atlas/engine/new_engine.py](src/Atlas/engine/new_engine.py) now emit `p_cal_src = p_adj_under_relief` when `under_relief_applied` is true and the calibration source remains on the `p_adj` channel.
2. This activates the existing telemetry family `p_adj_under_relief_cool` from [data/model/telemetry_calibration.v2.json](data/model/telemetry_calibration.v2.json).

Result:

1. Replay completed successfully.
2. Recommendation membership was unchanged across all compared files:
   - `10 / 10` overlap for every recommendation family
3. Source-label activation changed scored-leg calibration on the `496` under-relief rows:
   - source counts on under-relief rows: `p_adj -> p_adj_under_relief`
   - under-relief rows abs mean `|p_cal - p_for_cal|`: `0.187229 -> 0.110246`
4. Recommendation probabilities and EV cooled materially on the same slip sets.

Interpretation:

1. The telemetry under-relief source-scale family is now live.
2. On this replay, it still does not change portfolio membership.
3. Like the calibrated-surface selector test, this currently looks more like a probability-quality lever than a selector-turnover lever on a single slate.