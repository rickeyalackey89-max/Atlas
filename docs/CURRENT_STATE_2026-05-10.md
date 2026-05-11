# Atlas Current State — 2026-05-10

> **Stamped:** 2026-05-10
> **Config fingerprint:** `c23c1419ef945163`
> **Reference live run:** `data/output/runs/20260510_174904/run_manifest.json`
> **Purpose:** Current production/runtime truth for Atlas NBA after the May 10 playoff tuning work.

---

## Executive State

Atlas NBA is no longer running the old "v18 LightGBM ensemble + active playoff isotonic" stack as the final production probability.

The current runtime is:

```text
MC kernel
  -> May 10 kernel transforms
  -> p_for_cal = p_adj
  -> CatBoost playoff v5cD residual calibrator
  -> p_cal
  -> slip builders / marketed builder
```

The v18 LightGBM ensemble remains documented and available as a historical baseline/artifact, but `posthoc_calibrator.enabled` is currently `false`.

The playoff isotonic file remains present, but `telemetry.apply_active_calibration` is currently `false`, so the isotonic overlay is not applied in production.

---

## Active Calibration

| Layer | Current State | Path / Notes |
|---|---|---|
| LightGBM posthoc ensemble | **disabled** | `posthoc_calibrator.enabled: false` |
| Telemetry isotonic overlay | **disabled** | `telemetry.apply_active_calibration: false` |
| CatBoost playoff calibrator | **enabled** | `catboost_playoff_calibrator.enabled: true` |
| CatBoost mode | `regressor`, `replace` | Writes `p_catboost -> p_cal` |
| Model | `catboost_playoff_v5cD` | `data/model/catboost_playoff/catboost_v5cD_full_corpus.cbm` |
| Metadata | active | `data/model/catboost_playoff/catboost_v5cD_full_corpus.meta.json` |

CatBoost v5cD is a residual regressor:

```text
target = hit - p_for_cal
p_cal = clip(p_for_cal + 0.50 * clip(residual, -0.20, +0.20), 0.03, 0.97)
```

It uses 19 runtime features:

```text
p_for_cal, bp_score_gated, bp_has, is_assists, thin_flag, is_home_feat,
min_sensitivity, is_b2b, tier_cat, line_dist, tail_risk, line_tightness,
margin_x_under, q_blowout, rate_cv, q_x_under, player_stat_te, use_role,
game_total_norm
```

Categorical features: `tier_cat`, `use_role`.

---

## CatBoost v5cD Training Snapshot

Source: `data/model/catboost_playoff/catboost_v5cD_full_corpus.meta.json`.

| Field | Value |
|---|---|
| Trained at | `2026-05-10 14:22:14` |
| Model kind | `CatBoostRegressor` |
| Iterations / depth | `600 / 5` |
| Learning rate | `0.075` |
| L2 leaf reg | `6.0` |
| Cache | `data/model/_v1_playoff_resim_cache.pkl` |
| Training dates | 10 |
| Training legs | 29,029 |
| Date range | 2026-04-30 -> 2026-05-09 |
| Baseline Brier | 0.186044 |
| In-sample Brier after | 0.162631 |

10-date replay validation summary:

| Date | Legs | v5cD Brier | Raw `p_adj` Brier | Delta mB |
|---|---:|---:|---:|---:|
| 2026-04-30 | 2,967 | 0.180737 | 0.186032 | +5.30 |
| 2026-05-01 | 3,200 | 0.193406 | 0.194357 | +0.95 |
| 2026-05-02 | 2,753 | 0.202694 | 0.201791 | -0.90 |
| 2026-05-03 | 2,457 | 0.180055 | 0.184852 | +4.80 |
| 2026-05-04 | 2,931 | 0.167748 | 0.176074 | +8.33 |
| 2026-05-05 | 3,026 | 0.166562 | 0.173108 | +6.55 |
| 2026-05-06 | 2,950 | 0.168045 | 0.176448 | +8.40 |
| 2026-05-07 | 2,934 | 0.180315 | 0.183241 | +2.93 |
| 2026-05-08 | 2,902 | 0.176204 | 0.178569 | +2.36 |
| 2026-05-09 | 777 | 0.174833 | 0.179962 | +5.13 |

Positive delta means v5cD improved Brier versus raw `p_adj`; 2026-05-02 is the only small regression in the replay table.

---

## Active Kernel Transforms

The May 10 runtime applies several post-kernel transforms before CatBoost:

| Config Section | Active Setting | Purpose |
|---|---|---|
| `kernel_high_prob_shrink` | `p_thr: 0.75`, `k: 0.0501` | Shrinks extreme high probabilities before calibration handoff |
| `kernel_blowout_bypass` | keep blowout adjustment only for `0.15 <= q_blowout < 0.50` | Bypasses blowout tail zones where the adjustment hurt Brier |
| `kernel_subset_shifts` | UNDER logit delta `-0.1651` | Corrects UNDER overconfidence before CatBoost |
| `kernel_prob_floors` | GOBLIN OVER floor `0.40` | Repairs low-quintile GOBLIN OVER underprediction |
| `kernel_logit_shrinks` | combo stats `RA/PA/PRA/PR`, `k: 0.90` | Adds variance/shrinkage for combo-stat overconfidence |

Current blowout config:

| Key | Value |
|---|---:|
| `spread_sd` | 11.0 |
| `threshold_margin` | 13.0 |
| `star_minute_drop` | 8.0 |
| `role_minute_drop` | 0.5 |
| `post_sim_exponent` | 0.0 |
| `team_blowout_weight` | 0.15 |
| `matchup_blowout_weight` | 0.25 |
| `series_multiplier.enabled` | true |
| `playoff_regime.enabled` | false |

---

## Slip Builder State

Main slip builder:

| Key | Current Value |
|---|---|
| `prefer_calibrated_prob` | `true` |
| `min_leg_prob` | `0.65` |
| `min_under_prob` / `max_under_prob` | `0.0 / 0.0` (UNDER window disabled) |
| `single_game_caps_by_legs` | `3:2`, `4:3`, `5:3` |
| `exclude_stat_directions` | `FTA_over`, `FTA_under` |
| EV sort min probs | 3L/4L/5L = `0.62` |
| hit sort uses `p_cal` | `true` |

Marketed slip builder:

| Key | Current Value |
|---|---|
| `enabled` | `true` |
| `excluded_stats` | `BLK`, `STL`, `TO`, `FTA` |
| post-haircut floors | disabled: all `min_thresholds` are `0.0` |
| raw floors | GOBLIN `0.68`, STANDARD `0.55`, DEMON `0.50` |
| direction filters | GOBLIN/DEMON OVER-only; STANDARD OVER/UNDER |
| UNDER window | disabled: `0.0 / 0.0` |
| hit-prob calibration | 3L `1.37`, 4L `1.33`, 5L `1.34` |
| high-confidence thresholds | 3L `0.65`, 4L `0.40`, 5L `0.20` |

10-date v5cD slip eval:

| Family | Legs | Slips | Actual Win Rate | Claimed Hit Prob | Realized EV Mult |
|---|---:|---:|---:|---:|---:|
| Marketed | 3 | 10 | 70.0% | 51.2% | 1.3517 |
| Marketed | 4 | 10 | 40.0% | 30.0% | 0.7588 |
| Marketed | 5 | 10 | 20.0% | 14.9% | 0.4290 |
| System | 3 | 10 | 70.0% | 45.2% | 4.2000 |
| System | 4 | 10 | 70.0% | 35.5% | 7.0000 |
| System | 5 | 10 | 30.0% | 26.9% | 6.0000 |

---

## Current Data Surface Notes

Latest checked `scored_legs_deduped.csv`:

| Run | Column Count | Notable Current Columns |
|---|---:|---|
| `20260510_174904` | 170 | `p_adj_pre_shrink`, `p_adj_pre_subset_shift`, `p_for_cal`, `p_catboost_residual`, `p_catboost`, `p_cal`, `p_cal_marketed` |

`p_cal` is the production probability used by slip builders. In the current runtime, it is CatBoost v5cD output, not active LightGBM/isotonic output.

---

## Working Rule

When docs and runtime disagree:

1. Trust `config.yaml`, `run_manifest.json`, CatBoost metadata, and runtime code first.
2. Treat `BASELINE_V18.md` as historical LightGBM baseline unless a section explicitly says "current runtime."
3. Do not promote changes using v18-only gates without also evaluating against the current CatBoost v5cD replay/corpus state.