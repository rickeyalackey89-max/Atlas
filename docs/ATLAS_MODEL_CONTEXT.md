# Atlas Model Context

## What Atlas Is
Atlas is a PrizePicks-style NBA prop model. Its job is to turn live board data, injuries, minutes, usage, team context, and game environment into the best possible slip candidates for the current slate.

Atlas is not just a probability engine. It is a live decision system built around basketball reasoning and production constraints:
- build slips from live PrizePicks lines
- remove players who should not be in play because of injury state
- redistribute value from unavailable players to the remaining rotation
- adjust for blowout fragility, role changes, and team depth
- produce outputs that can be used for system, probability-only, and hybrid slip families

## Core Model Goal
The central goal is to maximize edge by keeping the math aligned with real basketball behavior.

That means Atlas tries to answer:
- who benefits when someone is out
- how much usage and minutes shift
- which stat lines become more fragile in blowouts
- which overs or unders are structurally stronger in that game context
- which combinations are worth packaging into a slip

## Main Inputs
Atlas is driven by a small set of live inputs:
- PrizePicks board lines
- injury and status data
- team and player game logs
- minutes and usage context
- spread / game environment information
- role and depth information from the teamshare layer

## Main Processing Layers

### 1. Board Ingestion
Atlas pulls the live PrizePicks board and converts it into structured CSV outputs.

### 2. Injury Filtering
Out and doubtful players are removed from slips early. Questionable players are treated explicitly so they are visible in the model instead of being silently mixed into active assumptions.

### 3. Role Allocation
If a player is unavailable, Atlas does not just delete that production. It reallocates the removed value across remaining teammates based on:
- team depth
- minutes
- usage
- rotation structure
- recent patterns
- the size and type of the absence

A star-level absence should create a meaningful redistribution. A low-impact absence should create little or none.

### 4. Probability Kernel
Atlas uses Monte Carlo style probability logic to estimate outcomes for legs and slips.

### 5. Blowout / Fragility Logic
Game spread and blowout risk matter.
- Overs can become less stable when blowout risk is high.
- Unders can become stronger when stars are likely to lose minutes.
- Bench and role players can gain value in the opposite direction.

### 6. Output Families
Atlas currently organizes live outputs into families such as:
- `system`: kernel-driven slips using PrizePicks multiplier structure
- `winprob`: probability-focused picks
- `windfall`: hybrid output combining probability and edge-based logic

## Output Header Groups
The `scored_legs_deduped.csv` output is the best lens for understanding where the math actually lands. Its headers break into a few useful groups.

### 1. Identity and Market Shape
These fields tell you what leg the row represents:
- `projection_id`, `source_projection_id`
- `game_id`, `game_date`, `start_time`, `updated_at`
- `player_key`, `player`, `team`, `home`, `opp`
- `stat`, `stat_raw`, `stat_is_canonical`
- `line`, `direction`, `tier`, `odds_type`
- `main_line`, `alt_line`, `is_main`, `more_allowed`, `less_allowed`

### 2. Game Environment
These are the market and slate context inputs:
- `spread`, `home_team`, `away_team`
- `home_spread`, `away_spread`, `game_spread`
- `spread_source`, `spread_ok`, `spread_reason`
- `q_blowout`

### 3. Core Probability Lineage
This is the core math chain the model builds and then adjusts:
- `p`
- `p_role`
- `p_adj`
- `p_close`, `p_close_raw`, `p_close_role`
- `p_adj_pre_under_relief`
- `under_relief_factor`, `under_relief_applied`

These are the main fields to inspect when you want to understand whether the model math itself is moving correctly.

### 4. Role Allocation and Injury Redistribution
These columns describe how the role layer reacted to injuries or availability shifts:
- `minutes_s`, `minutes_s_close`
- `is_star`
- `fragility`, `fragility_abs`, `fragility_gap_core`, `fragility_gap_usage`, `fragility_gap_dir`
- `usage_dep`, `usage_dep_eff`, `usage_risk_gate`, `usage_baseline`
- `usage_producer_mult`, `usage_pressure_mult`, `usage_target_rate`, `usage_burden_ratio`, `usage_dep_raw`
- `role_ctx_mult`, `role_ctx_mult_raw`, `role_ctx_sigma_mult`
- `role_ctx_reason`, `games_used`, `role_ctx_outs_used`, `role_ctx_outs`
- `role_ctx_bump`, `role_ctx_by_out`, `role_ctx_components`
- `role_ctx_component_mults`, `role_ctx_component_reasons`
- `role_ctx_team`, `role_ctx_stat`, `role_ctx_min_games`

These are the fields that matter most when you are tuning allocator behavior.

### 5. Calibration and Telemetry
These fields show the late-stage calibration overlay and whether it actually changed the row:
- `p_for_cal`
- `p_cal_src`
- `p_cal`
- `telemetry_cal_key`
- `telemetry_k_shrink`
- `telemetry_under_penalty`
- `telemetry_mult`
- `telemetry_cal_applied`
- `telemetry_bucket_mult`

### 6. External Priors and Quality Flags
These are supporting inputs, not the primary math surface:
- `prop_key`
- `external_prior_score`, `external_prior_n`, `external_prior_sources`, `external_prior_epsilon`
- `is_questionable`, `q_out_frac`
- `data_health_flag`

## Fields To Focus On
If the goal is to pinpoint which math needs to be adjusted, the highest-value fields are:

1. `p`, `p_role`, `p_adj`, `p_for_cal`, `p_cal`
2. `role_ctx_reason`, `role_ctx_outs_used`, `role_ctx_components`, `role_ctx_component_reasons`
3. `role_ctx_mult`, `role_ctx_mult_raw`, `role_ctx_sigma_mult`
4. `fragility`, `usage_dep`, `usage_pressure_mult`, `usage_burden_ratio`
5. `under_relief_factor`, `under_relief_applied`, `q_blowout`
6. `telemetry_cal_key`, `telemetry_k_shrink`, `telemetry_under_penalty`, `telemetry_mult`, `telemetry_bucket_mult`

If a row looks wrong, those fields usually tell you whether the problem came from:
- the base probability kernel
- the role allocator
- the blowout / fragility layer
- the under-relief adjustment
- the telemetry overlay

## How To Reason About A Bad Row
When a leg looks off, inspect it in this order:
- start with `p`
- compare `p_role` against `p`
- inspect `role_ctx_reason` and `role_ctx_outs_used`
- check whether `fragility` or `q_blowout` should have moved the probability
- compare `p_adj_pre_under_relief` to `p_adj`
- finally check `p_cal` and the telemetry columns

## Design Philosophy
Atlas is meant to be driven by math, not by guesswork.

The model should stay consistent across live code paths, with minimal drift between:
- the live engine
- the role allocator
- the calibration layer
- telemetry / replay validation

When the system is working well, each layer should reinforce the same answer instead of introducing contradictory assumptions.

## What Atlas Is Trying To Do
Atlas is trying to produce the best daily slip for the slate by combining:
- live data
- basketball context
- injury-driven redistribution
- game-level fragility
- calibrated probability estimates

The intended result is a model that is not only statistically coherent, but also grounded in how NBA rotations actually behave.

## Debugging Origin
This work started because the slips were not winning and the outputs were not showing value even when the model was being backtested heavily.

That led to a few steps:
- running a lot of backtests to see whether the model or the output path was the problem
- building `oracle.py` as a diagnostic layer
- replacing the older backtest flow with `backtest_v2.py`
- adding the reader so the outputs could be audited more directly

The reader sometimes suggested the original path was better, but that did not match the live outputs: the slips were still missing, and if there were hits they were buried deep in large output files.

So the focus shifted to:
- building a slip builder that is easier to reason about
- finding the math bottleneck
- cleaning up the model so the live slips reflect the intended basketball logic

That is the current goal: not just to produce more files, but to unlock the bottleneck in the math and make the model easier to debug, deliberate on, and trust.
