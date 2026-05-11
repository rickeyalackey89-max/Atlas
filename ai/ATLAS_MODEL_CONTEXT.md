# Atlas Model Context

> **Last updated:** 2026-05-10 — reflects current CatBoost v5cD playoff runtime.
> **Config fingerprint:** `c23c1419ef945163`
> **Current state reference:** `ai/CURRENT_STATE_2026-05-10.md`

---

## What Atlas Is

Atlas is an NBA player-prop probability engine and daily slip builder targeting PrizePicks.
It ingests the live PrizePicks board, injury data, game logs, spreads, and team-context
information, then produces calibrated over/under probabilities for every leg and assembles
optimized multi-leg slip candidates.

Atlas is **not** just a probability calculator. It is a full decision pipeline:

1. Fetch the current PrizePicks board and convert it to structured data.
2. Freeze the injury state and redistribute production from out players to teammates.
3. Score every leg through a Monte-Carlo probability kernel.
4. Apply May 10 kernel transforms and set `p_for_cal = p_adj`.
5. Apply CatBoost playoff v5cD residual calibration.
6. Build slips across three output families (System, Windfall, DemonHunter).
7. Publish run artifacts and optional bundle zip.

---

## Current Production — 2026-05-10 Runtime

| Metric | Value |
|---|---|
| **Active probability calibrator** | CatBoost playoff v5cD residual regressor |
| **Model path** | `data/model/catboost_playoff/catboost_v5cD_full_corpus.cbm` |
| **Meta path** | `data/model/catboost_playoff/catboost_v5cD_full_corpus.meta.json` |
| **Mode** | `replace` (`p_catboost -> p_cal`) |
| **Features** | 19 CatBoost runtime features |
| **Training legs** | 29,029 across 10 playoff dates |
| **Training cache** | `data/model/_v1_playoff_resim_cache.pkl` |
| **Date range** | 2026-04-30 to 2026-05-09 |
| **Reference live run** | `data/output/runs/20260510_174904/` |
| **LightGBM v18 ensemble** | Historical baseline; currently disabled |
| **Telemetry isotonic** | Present but currently disabled |

Current CatBoost metadata is the active feature contract. The historical v18 LightGBM
contract remains in `src/Atlas/contracts/model_contract.py` and
`data/model/ensemble/ensemble_meta.json`.

### Marketed Slip Baselines

Historical v18 baseline, verified 2026-05-03:

| Slip | Win Rate | EV |
|---|---|---|
| 3-leg | 60.5% (26/43) | +2.63x |
| 4-leg | 37.2% (16/43) | +2.72x |
| 5-leg | 20.9% (9/43)  | +3.19x |
| **Overall** | **39.5% (51/129)** | **All +EV** |

Current v5cD 10-date marketed eval:

| Slip | Win Rate | Claimed Hit Prob | Realized EV Mult |
|---|---:|---:|---:|
| 3-leg | 70.0% | 51.2% | 1.3517 |
| 4-leg | 40.0% | 30.0% | 0.7588 |
| 5-leg | 20.0% | 14.9% | 0.4290 |

### Active CatBoost v5cD Parameters

| Parameter | Value |
|---|---|
| model_kind | `CatBoostRegressor` |
| target | `hit - p_for_cal` |
| iterations | 600 |
| depth | 5 |
| learning_rate | 0.075 |
| l2_leaf_reg | 6.0 |
| min_data_in_leaf | 50 |
| residual_scale | 0.50 |
| residual_clip | 0.20 |
| p_lo / p_hi | 0.03 / 0.97 |

The active transform:

```text
p_cal = clip(p_for_cal + 0.50 * clip(residual, -0.20, +0.20), 0.03, 0.97)
```

### Active CatBoost Feature List (19 features)

```text
p_for_cal, bp_score_gated, bp_has, is_assists, thin_flag, is_home_feat,
min_sensitivity, is_b2b, tier_cat, line_dist, tail_risk, line_tightness,
margin_x_under, q_blowout, rate_cv, q_x_under, player_stat_te, use_role,
game_total_norm
```

Categorical features: `tier_cat`, `use_role`.

### Historical v18 LightGBM Parameters

| Parameter | OVER | UNDER |
|---|---|---|
| max_depth | 8 | 11 |
| num_leaves | 30 | 50 |
| min_child_samples | 200 | 150 |
| lambda_l2 | 1.0 | 6.0 |
| learning_rate | 0.03 | 0.03 |
| n_rounds | 200 | 200 |

The v18 ensemble produces 14 model files (7 OVER + 7 UNDER, one per seed) stored in
`data/model/ensemble/`, but `posthoc_calibrator.enabled` is currently `false`.

### Feature List (33 features)

```
z_line, min_cv, is_combo, bp_score_gated, bp_has, is_assists, is_threes,
games_norm, thin_flag, line_norm, is_home_feat, min_sensitivity,
game_total_norm, is_b2b, l20_edge, l10_has, margin, stat_cat, tier_cat,
l40_hr, logit_p_x_demon, player_te, player_stat_te, player_dir_te,
player_n_norm, line_dist, tail_risk, line_tightness, margin_x_under,
q_blowout, rate_cv, abs_logit_p, q_x_under
```

Categorical features: `stat_cat`, `tier_cat`.

### Kernel Parameters (Active in Production)

The May 10 runtime uses Kernel Trainer v2 LOSO Phase 1 values plus targeted
post-kernel transforms before CatBoost:

| Parameter | Value |
|---|---|
| spread_sd | 11.0 |
| threshold_margin | 13.0 |
| star_minute_drop | 8.0 |
| role_minute_drop | 0.5 |
| post_sim_exponent | 0.0 |
| rate_min_correlation | 0.45 |
| thin_window_games | 20 |
| thin_window_max_mult | 1.3 |
| opp_defense_strength | 1.0 |
| rate_std_PTS | 1.3 |
| rate_std_AST | 1.196 |
| rate_std_REB | 1.001 |
| rate_std_FG3M | 1.001 |
| rate_std_PRA | 1.105 |
| rate_std_PR | 1.105 |
| rate_std_PA | 1.105 |
| rate_std_RA | 0.939 |
| series_multiplier.enabled | true |
| playoff_regime.enabled | false |

Active post-kernel transforms:

| Transform | Current Setting |
|---|---|
| high-prob shrink | `p_thr=0.75`, `k=0.0501` |
| blowout bypass | bypass when `q_blowout < 0.15` or `q_blowout >= 0.50` |
| UNDER subset shift | logit delta `-0.1651` |
| GOBLIN OVER floor | `0.40` |
| combo logit shrink | `RA/PA/PRA/PR`, `k=0.90` |

### Role Context

~24% of legs have active role context adjustments (`role_ctx_outs_used > 0`).
The production GBM (v18) was trained on v18 cache data that includes role context
effects in `p_role`.

### Direction Split (OVER vs UNDER)

| Direction | Brier | % of Legs | Calibration |
|---|---|---|---|
| OVER | 0.2094 | ~87.5% | Well-calibrated |
| UNDER | 0.2596 | ~12.5% | +3.5pp overconfident, AUC ~0.52 |

UNDER legs have near-random discrimination. The GBM partially compensates via
`logit_p_x_under` and `margin_x_under` features. Direction-split isotonic
calibration (`isotonic_direction_split.json`) provides additional UNDER correction.

---

## Core Model Goal

Maximize edge by keeping the math aligned with real basketball behavior:

- **Who benefits when someone is out?** → Share matrix + role context allocator.
- **How much do usage and minutes shift?** → Team share allocator v2.
- **Which stat lines are fragile in blowouts?** → Blowout / fragility layer.
- **Which overs or unders are structurally stronger?** → Structural blowout rules.
- **Which combinations build the best slip?** → Beam-search slip builder.

---

## Main Inputs

| Input | Source | Path |
|---|---|---|
| PrizePicks board | Live fetch or pinned raw JSON | `data/raw/prizepicks_*.json` → `data/board/today.csv` |
| Injury data | IAEL (Injury/Absence/Eligibility Layer) | `data/output/dashboard/injury_invalidations_latest.json` |
| Game logs | NBA API rolling refresh | `data/gamelogs/nba_gamelogs.csv` |
| Spreads & totals | Rotowire fetch | `data/input/rotowire_lines.json` |
| External priors | BettingPros props | `data/input/external_priors_today.csv` |
| Role metrics | External adapter snapshot | `data/output/dashboard/role_metrics_latest.json` |
| Share matrix | Prebuilt from game logs | `data/model/share_matrix.csv` |
| Roster map | Manual/semi-auto | `data/input/roster_map.csv` |
| Slate schedule | Derived from board | `data/input/slate.csv` |

---

## Processing Layers (in order)

### 1. Board Ingestion
Fetches the live PrizePicks board (or loads a pinned raw JSON in replay mode) and
converts it into `data/board/today.csv` — the canonical input for the scoring kernel.

### 2. Injury Filtering (IAEL)
Out and doubtful players are removed. Questionable players are tagged with `is_questionable`
and `q_out_frac` so the model can reason about them explicitly rather than silently treating
them as active.

### 3. Share Matrix & Role Allocation
`team_share_allocator_v2.py` computes a **share matrix** (`data/model/share_matrix.csv`)
that maps: "when player X is out, how much of their stat production flows to player Y?"

This is built from historical game logs by comparing a player's stats in games where a
teammate was absent vs. present. The matrix columns are:
`team, out_player, beneficiary_player, stat, games, weight`.

At scoring time, `new_probability.py` loads this matrix and uses it to compute `role_ctx_mult`
— a clamped multiplier that adjusts a player's expected rate when a teammate is out. The
multiplier is clamped between 0.9 and 1.2 (`projection_clamp_lo/hi` in config) and the
variance is conservatively inflated via `variance_k`.

### 4. Probability Kernel (Monte Carlo)
`new_probability.py` → `simulate_leg_probability_new()`:

1. Loads the player's recent game log window.
2. Computes per-minute rate mean and standard deviation.
3. Applies role context adjustment (if injuries are present).
4. Runs a Monte Carlo simulation of minutes × rate to estimate `p` (probability of hitting the line).
5. Adjusts for blowout risk and role/game-script effects → produces `p_adj`.
6. Applies May 10 transforms such as high-prob shrink, UNDER subset shift,
   GOBLIN OVER floor, and combo-stat logit shrink.

The probability chain for each leg:
```
p (raw MC) → p_role → p_adj → p_for_cal → p_catboost → p_cal
```

### 5. Kernel Transform Handoff

`engine/main.py` applies the May 10 post-kernel transforms and then sets
`p_for_cal := p_adj` universally. This is an intentional fork fix so CatBoost sees
the true post-kernel probability surface rather than stale LightGBM-era inputs.

### 6. CatBoost Playoff Calibration

`catboost_calibrator.py` applies the active v5cD residual regressor. It reads
19 runtime features directly from `scored_legs_deduped`-compatible columns and writes:

```text
p_catboost_residual
p_catboost
p_cal
```

In current production, `p_cal` is CatBoost output.

### 7. LightGBM / Telemetry State

The historical v18 LightGBM ensemble remains available in `data/model/ensemble/`,
but `posthoc_calibrator.enabled: false`.

The playoff isotonic JSON remains available at
`data/model/telemetry_calibration.playoff_isotonic.json`, but
`telemetry.apply_active_calibration: false`. It is not applied after CatBoost.

### 8. Blowout / Fragility Logic
Game spread drives `q_blowout` — the probability of a blowout scenario. The blowout layer:
- Reduces OVER probabilities when blowout risk is high (stars lose minutes).
- Can boost UNDER probabilities in the same scenario.
- Uses structural adjustment rules by stat family (e.g., combo scoring overs get different
  treatment than assists or rebounds).

Key config: `blowout.spread_sd`, `blowout.threshold_margin`,
`kernel_blowout_bypass`, and `blowout.adjustment_rules`.

### 9. Slip Building
Three slip families are built from the scored legs:

| Family | Description | Sort Basis |
|---|---|---|
| **System** | Main output — beam-search optimized slips | `score_adj` (edge × probability) |
| **Windfall** | Hybrid probability + edge | `score_adj` variant |
| **DemonHunter** | All-DEMON tier legs only, highest-multiplier | DEMON-only filter |

Each family produces 3-leg, 4-leg, and 5-leg slips. The slip builder uses:
- Beam search with configurable width (250 default, 400 for 4-leg, 500 for 5-leg).
- Diversity penalties for same-team, same-stat-family, and fragility concentration.
- Per-player caps (`max_slips_per_player: 5`).
- A `winprob` sort mode variant that ranks by pure hit probability.
- Single-game slate caps (`3:2`, `4:3`, `5:3`) so one-game boards can still
  build while limiting team/player concentration.

The current runtime disables the old UNDER probability window (`0.0 / 0.0`) because
v5cD is treated as the active calibrated surface.

### 10. Publishing
`publish_run_outputs.py` writes all artifacts to `data/output/runs/<timestamp>/` and
copies latest surfaces to `data/output/latest/`. A bundle zip is optionally created
in `data/bundles/`.

---

## Output CSV Reference

### `scored_legs_deduped.csv` — The Master Diagnostic File

This is the single most important file for understanding a run. Every leg the model scored
appears here with the full probability chain and all diagnostic columns.

**Column Groups:**

#### Identity & Market
`projection_id`, `player_key`, `player`, `team`, `home`, `opp`, `stat`, `line`,
`direction`, `tier`, `odds_type`, `game_id`, `game_date`, `start_time`

#### Probability Chain
| Column | Meaning |
|---|---|
| `p` | Raw Monte Carlo probability (no role adjustment) |
| `p_role` | After role context adjustment for injuries |
| `p_adj` | After blowout/fragility adjustment |
| `p_adj_pre_under_relief` | p_adj before under-relief restoration |
| `p_for_cal` | Probability sent to the active calibrator; currently the post-transform `p_adj` handoff |
| `p_catboost_residual` | CatBoost v5cD residual prediction |
| `p_catboost` | CatBoost v5cD probability after residual application |
| `p_cal` | Final calibrated probability |
| `p_close` / `p_close_raw` | Close-line probability variants |

#### Role Context Diagnostics
`role_ctx_mult`, `role_ctx_mult_raw`, `role_ctx_sigma_mult`, `role_ctx_reason`,
`role_ctx_outs_used`, `role_ctx_components`, `role_ctx_component_mults`

#### Blowout & Fragility
`q_blowout`, `fragility`, `fragility_abs`, `usage_dep`, `usage_pressure_mult`,
`minutes_s`, `is_star`

#### Calibration & Telemetry
`p_cal_src`, `p_catboost_residual`, `p_catboost`, `telemetry_cal_key`,
`telemetry_k_shrink`, `telemetry_under_penalty`, `telemetry_mult`,
`telemetry_cal_applied`

#### External Priors
`external_prior_score`, `external_prior_n`, `external_prior_sources`

### `eval_legs.csv` — Truth-Backed Evaluation

Produced during replay evaluation. Contains the scored legs **plus** the actual outcome
(`actual_stat`, `hit`) so Brier scores can be computed. This is the file used for all
backtest and reader evaluations.

### Slip CSVs

| File | Contents |
|---|---|
| `System/system_3.csv` ... `system_5.csv` | System family slips (3/4/5-leg) |
| `Windfall/windfall_3.csv` ... `windfall_5.csv` | Windfall family slips |
| `demonhunter.csv` | Best all-DEMON slips at each leg count |
| `*_winprob.csv` variants | Same families sorted by pure hit probability |

---

## How To Debug A Bad Row

When a leg looks wrong, inspect in this order:

1. **Start with `p`** — is the raw Monte Carlo probability reasonable given the player's
   recent stats and the line?
2. **Compare `p_role` vs `p`** — did the role context move it? Check `role_ctx_reason`
   and `role_ctx_outs_used` to see which absences drove the adjustment.
3. **Check `q_blowout` and `fragility`** — did the blowout layer move the probability
   too aggressively?
4. **Compare `p_adj_pre_under_relief` vs `p_adj`** — did under-relief restore too much
   or too little?
5. **Check transform snapshots** — compare `p_adj_pre_shrink`,
   `p_adj_pre_subset_shift`, `p_for_cal`, and `p_adj`.
6. **Check CatBoost** — compare `p_for_cal`, `p_catboost_residual`,
   `p_catboost`, and `p_cal`.
7. **Check telemetry columns** — in current production they should show that
   the legacy telemetry isotonic layer was not applied unless config changed.

The problem almost always maps to one of:
- Base kernel (wrong rate/minutes estimate)
- Role allocator (wrong redistribution)
- Blowout layer (over/under-correction)
- Calibrator (CatBoost residual, historical GBM, or isotonic distortion if re-enabled)

---

## Key Config Knobs (`config.yaml`)

| Section | Key Settings | What They Control |
|---|---|---|
| `pp_kernel` | `coeffs` per stat/tier | PrizePicks pricing model coefficients |
| `role_ctx` | `projection_clamp_lo/hi`, `variance_k`, `close_sens_mult` | Role context adjustment bounds |
| `role_ctx` | `under_relief_q_min/haircut_min/factor` | Under-relief gate and strength |
| `posthoc_calibrator` | `enabled`, `coefficients_path`, `ensemble_dir` | Historical GBM ensemble calibrator; currently disabled |
| `catboost_playoff_calibrator` | `enabled`, `model_path`, `meta_path`, `mode` | Active playoff calibrator |
| `telemetry` | `active_calibration`, `apply_active_calibration` | Isotonic calibration overlay; currently disabled |
| `blowout` | `spread_sd`, `threshold_margin`, `adjustment_rules` | Blowout sensitivity |
| `kernel_*` transforms | high-prob shrink, blowout bypass, subset shifts, floors | May 10 pre-CatBoost probability shaping |
| `slip_build` | `beam_width`, `max_slips_per_player`, `penalty.*` | Slip builder behavior |
| `optimizer` | `top_n_slips`, `external_priors.*` | Final slip selection and priors |

---

## Design Philosophy

1. **Math over guesswork** — every adjustment should be traceable through the probability chain.
2. **Basketball grounding** — role allocation mirrors how NBA rotations actually behave when
   players are absent.
3. **Layer consistency** — the kernel, allocator, calibrator, and telemetry overlay should
   reinforce the same answer, not introduce contradictory assumptions.
4. **Replay reproducibility** — any live run can be replayed from pinned artifacts to verify
   that the model produces the same outputs.
5. **Narrow changes** — prefer config-only adjustments and bounded fixes over broad
   refactors. Get explicit approval before changing core model behavior.
