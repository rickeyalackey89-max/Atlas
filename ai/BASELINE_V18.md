# Atlas Baseline Reference — v18 + Current Runtime

> **Stamped:** 2026-05-09 (retrained with 50 dates through 2026-05-05)
> **Status:** **HISTORICAL LIGHTGBM BASELINE**
> **Supersedes:** v17 (stamped 2026-05-03, 47 dates)
> **Current runtime:** CatBoost playoff v5cD, stamped 2026-05-10. See `ai/CURRENT_STATE_2026-05-10.md`.

---

## Current Runtime Baseline — 2026-05-10

v18 is no longer the final active probability surface. Current production uses:

```text
MC kernel + May 10 transforms -> p_for_cal -> CatBoost playoff v5cD -> p_cal
```

Current switches:

| Layer | State |
|---|---|
| `posthoc_calibrator.enabled` | `false` |
| `telemetry.apply_active_calibration` | `false` |
| `catboost_playoff_calibrator.enabled` | `true` |
| CatBoost version | `catboost_playoff_v5cD` |
| CatBoost mode | `regressor`, `replace` |
| CatBoost features | 19 |
| CatBoost training cache | `data/model/_v1_playoff_resim_cache.pkl` |
| CatBoost training dates | 2026-04-30 -> 2026-05-09 |
| Reference live run | `data/output/runs/20260510_174904/` |

10-date replay validation against raw `p_adj`:

| Metric | Value |
|---|---:|
| Replay dates | 10 |
| Replay legs | 26,897 |
| Mean v5cD Brier | 0.179322 |
| Mean raw `p_adj` Brier | 0.183652 |
| Net improvement | +4.33 mB |
| Per-date regressions | 1 date (`2026-05-02`, -0.90 mB) |

10-date v5cD slip eval:

| Family | Legs | Actual Win Rate | Claimed Hit Prob | Realized EV Mult |
|---|---:|---:|---:|---:|
| Marketed | 3 | 70.0% | 51.2% | 1.3517 |
| Marketed | 4 | 40.0% | 30.0% | 0.7588 |
| Marketed | 5 | 20.0% | 14.9% | 0.4290 |
| System | 3 | 70.0% | 45.2% | 4.2000 |
| System | 4 | 70.0% | 35.5% | 7.0000 |
| System | 5 | 30.0% | 26.9% | 6.0000 |

**Promotion rule now:** any future probability change must be evaluated against the current CatBoost v5cD replay/corpus state, not only against v18 LightGBM LODO.

---

## Golden Baseline Metrics

| Metric | v18 (current) | v17 (prior) | Delta |
|---|---|---|---|
| **LODO Brier (ensemble)** | **0.201529** | 0.201402 | +0.127 mB (playoff dilution) |
| **Features** | 33 (v9d contract) | 33 (v9d contract) | — |
| **Temperature** | 1.04 | 1.04 | — |
| **Seeds** | 65536, 9999, 137, 999, 98765, 54321, 12345 | same | — |
| **Architecture** | direction-split GBMs (OVER d8/nl30, UNDER d11/nl50) | same | — |
| **Training legs** | **173,495** across **50 dates** | 170,552 across 47 dates | +2,943 legs, +3 dates |
| **Date range** | 2026-02-09 → 2026-05-05 | 2026-02-09 → 2026-05-02 | +3 playoff dates |
| **Training cache** | `data/model/_v18_resim_cache.pkl` | `data/model/_v17_resim_cache.pkl` | — |

> Historical note: the marginal +0.127 mB regression vs v17 is attributable entirely to playoff dilution
> (small slate sizes, higher variance). The 44-date non-playoff subset is non-regressive.

---

## Marketed Slip Baseline — VERIFIED 2026-05-03

> Source: `tools/simulate_slips_from_cache.py` — 44 dates, 165,792 legs.
> Config: hardcoded fallback thresholds (GOBLIN=0.57, STANDARD=0.30, DEMON=0.28).
> **This is the number to beat. Do not compare against any other test.**

| Slip | Won | Total | Win Rate | Breakeven | EV |
|---|---|---|---|---|---|
| **3-leg** | 26 | 43 | **60.5%** | 16.7% | **+2.63x** |
| **4-leg** | 16 | 43 | **37.2%** | 10.0% | **+2.72x** |
| **5-leg** | 9  | 43 | **20.9%** | 5.0%  | **+3.19x** |
| **Overall** | **51** | **129** | **39.5%** | — | **All +EV** |

All three slip sizes are positive EV. This baseline must be beaten before any config change is applied to production.

---

## Slip Performance by Tier

| Tier | Slip-Eligible Legs | Hit Rate | Role |
|---|---|---|---|
| **GOBLIN OVER** | 48,708 | **64.6%** | Profit engine |
| **STANDARD OVER** | 8,311 | **49.8%** | Volume filler |
| **DEMON OVER** | 417 | **51.8%** | Selective multiplier |
| **STANDARD UNDER** | 1,739 | **55.5%** | Hedge quality |

**Total slip-eligible:** 59,175 of 165,792 corpus legs (35.7%)

---

## Direction Split

| Direction | Brier | % of Legs | Calibration Status |
|---|---|---|---|
| OVER | 0.2094 | ~87.5% | Well-calibrated |
| UNDER | 0.2596 | ~12.5% | +3.5pp overconfident, AUC ~0.52 |

UNDER legs have near-random discrimination. Direction-split isotonic calibration (`isotonic_direction_split.json`) provides partial UNDER correction. The GBM compensates via `logit_p_x_under` and `margin_x_under` features.

---

## GBM Architecture

### Parameters

| Parameter | OVER | UNDER |
|---|---|---|
| max_depth | 8 | 11 |
| num_leaves | 30 | 50 |
| min_child_samples | 200 | 150 |
| lambda_l2 | 1.0 | 6.0 |
| learning_rate | 0.03 | 0.03 |
| n_rounds | 200 | 200 |
| feature_fraction | 0.8 | 0.8 |
| bagging_fraction | 0.8 | 0.8 |

### Feature List (33 — exact v9d contract)

```text
z_line, min_cv, is_combo, bp_score_gated, bp_has, is_assists, is_threes,
games_norm, thin_flag, line_norm, is_home_feat, min_sensitivity,
game_total_norm, is_b2b, l20_edge, l10_has, margin, stat_cat, tier_cat,
l40_hr, logit_p_x_demon, player_te, player_stat_te, player_dir_te,
player_n_norm, line_dist, tail_risk, line_tightness, margin_x_under,
q_blowout, rate_cv, abs_logit_p, q_x_under
```

Categorical: `stat_cat`, `tier_cat`.

---

## Artifacts

| Artifact | Path |
|---|---|
| Ensemble models (14 files) | `data/model/ensemble/` |
| Ensemble metadata | `data/model/ensemble/ensemble_meta.json` |
| Resim cache | `data/model/_v18_resim_cache.pkl` |
| Active calibration | `data/model/telemetry_calibration.playoff_isotonic.json` |
| Model contract | `src/Atlas/contracts/model_contract.py` |

---

## LODO Brier Progression

| Version | Brier | Dates | Notes |
|---|---|---|---|
| raw MC kernel | 0.250000 | — | No GBM |
| v5 | 0.212238 | — | First GBM |
| v7 | 0.212154 | — | |
| v8 | 0.212118 | — | |
| v12 | 0.199212 | 38 | First sub-0.20 |
| v17 | 0.201402 | 47 | +playoff dates |
| **v18** | **0.201529** | **50** | +3 more playoff dates |

---

## Baseline Rules

1. **All future models must beat 0.201529 LODO** on the same 50-date corpus to be considered for promotion.
2. **No slate regressions allowed** — every fold must be non-regressive vs v18 on that specific date.
3. **Contract validation required** (`src/Atlas/contracts/model_contract.py`) before any promotion.
4. **Marketed slip win rates must remain ≥ v17 verified baseline** (3-leg ≥ 60.5%, 4-leg ≥ 37.2%, 5-leg ≥ 20.9%).
5. **Do not promote a model that was trained on today's date** — wait for eval legs before evaluating that slate.
