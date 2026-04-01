# Atlas Baseline — v9d

> **Stamped:** 2026-03-31
> **Status:** Current production baseline. All future work should be measured against these numbers.

---

## Baseline Metrics

| Metric | Value | Notes |
|---|---|---|
| **LODO Brier (ensemble)** | **0.196266** | Leave-one-date-out cross-validation |
| **LODO Hit Rate** | **69.86%** | Percentage of legs where calibrated p > 0.5 matched outcome |
| **Raw Brier** | 0.212914 | Before ensemble calibration |
| **Reader Brier (p_adj)** | 0.20046 | Backtest on 49,956 legs from v9d corpus |
| **Reader corpus** | 49,956 legs / 22 runs | Stored in `data/telemetry/v9d_corpus/` |
| **Reader hit3 rate** | 36.15% | 3-leg slip hit rate |
| **Reader hit4 rate** | 21.43% | 4-leg slip hit rate |
| **Reader strict3 rate** | 17.19% | Strict 3-leg (all legs must hit) |

### Previous Baselines

| Version | Brier | Hit Rate | Features | Notes |
|---|---|---|---|---|
| v3 | 0.205815 | — | baseline | Original starting point |
| v9c | 0.200908 | — | 56 | Pre-trim |
| **v9d** | **0.196266** | **69.86%** | **33** | Current (trimmed, T=0.98) |

---

## Architecture

- **Direction-split GBMs**: Separate OVER and UNDER models (different hyperparameters).
- **7-seed ensemble**: Predictions averaged across 7 seeds for stability.
- **Temperature scaling**: T=0.98 applied to ensemble average.
- **33 features** (trimmed from 56 in v9c by dropping low-importance features).
- **2 categorical features**: `stat_cat`, `tier_cat`.

### OVER Model Parameters
```
max_depth=11, num_leaves=50, min_child_samples=200, lambda_l2=1.0
learning_rate=0.03, n_rounds=200, feature_fraction=0.8, bagging_fraction=0.8
```

### UNDER Model Parameters
```
max_depth=15, num_leaves=90, min_child_samples=150, lambda_l2=6.0
learning_rate=0.03, n_rounds=200, feature_fraction=0.8, bagging_fraction=0.8
```

### Training Data
- 171,214 legs across 33 dates
- Player target encoding: smooth_k=20
- Global hit rate: 0.474868

---

## Feature List (33 features)

| # | Feature | Category |
|---|---|---|
| 1 | `z_line` | Line standardization |
| 2 | `min_cv` | Minutes coefficient of variation |
| 3 | `is_combo` | Combo stat flag (PRA, PR, PA, RA) |
| 4 | `bp_score_gated` | BettingPros consensus score (gated) |
| 5 | `bp_has` | BettingPros data available |
| 6 | `is_assists` | Stat family flag |
| 7 | `is_threes` | Stat family flag |
| 8 | `games_norm` | Normalized game count |
| 9 | `thin_flag` | Low-data flag |
| 10 | `line_norm` | Normalized line value |
| 11 | `is_home_feat` | Home team indicator |
| 12 | `min_sensitivity` | Minutes sensitivity to blowout |
| 13 | `game_total_norm` | Normalized game total (pace proxy) |
| 14 | `is_b2b` | Back-to-back flag |
| 15 | `l20_edge` | Last-20-game edge vs line |
| 16 | `l10_has` | Last-10 data available |
| 17 | `margin` | Line margin (how far from mean) |
| 18 | `stat_cat` | Stat category (categorical) |
| 19 | `tier_cat` | PrizePicks tier (categorical) |
| 20 | `l40_hr` | Last-40-game hit rate |
| 21 | `logit_p_x_demon` | Logit(p) × DEMON tier interaction |
| 22 | `player_te` | Player target encoding |
| 23 | `player_stat_te` | Player × stat target encoding |
| 24 | `player_dir_te` | Player × direction target encoding |
| 25 | `player_n_norm` | Player data volume (normalized) |
| 26 | `line_dist` | Distance from line to player mean |
| 27 | `tail_risk` | Tail risk estimate |
| 28 | `line_tightness` | How tight the line is to recent performance |
| 29 | `margin_x_under` | Margin × UNDER direction interaction |
| 30 | `q_blowout` | Blowout probability |
| 31 | `rate_cv` | Rate coefficient of variation |
| 32 | `abs_logit_p` | Absolute logit of base probability |
| 33 | `q_x_under` | Blowout probability × UNDER interaction |

### Dropped Features (23 removed from v9c)

```
logit_p, opp_defense_rel_feat, is_scoring, is_rebounds, pace_factor_feat,
ext_pace_rel, is_goblin, is_demon, l5_edge, l10_edge, l40_edge, stat_cv,
streak, l5_hr, l10_hr, l20_hr, logit_p_x_combo, logit_p_x_goblin,
z_x_under, tail_x_under, opp_def_roll, vol_change, opp_def_roll_x_under,
line_x_under
```

---

## Evaluation Rules

1. **Always compare against v9d baseline numbers** (Brier 0.196266 LODO, 0.20046 reader).
2. **Use replay mode** for testing changes — never compare against a current-day live run.
3. **Single-run replay first**, then 3-run backtest, then full corpus only for final promotion.
4. **Use `eval_legs.csv`** for truth-backed evaluation (not `scored_legs_deduped.csv` which lacks outcomes).
5. **Reader corpus** lives at `data/telemetry/v9d_corpus/` — do not modify or delete.
6. A change must beat v9d on the reader corpus (or at minimum not regress Brier) to be promoted.

---

## What Changed from v9c to v9d

1. **Feature trimming**: 56 → 33 features. Removed low-importance and correlated features.
2. **Temperature**: 1.02 → 0.98 (slightly sharper predictions).
3. **Brier improvement**: 0.200908 → 0.196266 (2.3% relative improvement).
4. **Reader validation**: Full corpus backtest confirmed real-world improvement.

---

## Config Snapshot (v9d production)

Key `config.yaml` settings for reference:

```yaml
posthoc_calibrator:
  enabled: true
  coefficients_path: data/model/posthoc_calibrator_coeffs_enriched.json
  ensemble_dir: data/model/ensemble

telemetry:
  active_calibration: isotonic_hybrid_protect_role_ctx_on
  apply_active_calibration: true

role_ctx:
  enabled: true
  projection_clamp_lo: 0.9
  projection_clamp_hi: 1.2
  variance_k: 0.65
  close_sens_mult: 0.35
  under_relief_factor: 0.0  # (top-level override: 0.11)

slip_build:
  beam_width: 250
  max_slips_per_player: 5
  prefer_calibrated_prob: true

blowout:
  spread_sd: 10.0
  threshold_margin: 15.5

optimizer:
  external_priors:
    enabled: true
    cap: 0.03
    scale: 3.0
```

---

## Workspace State (2026-03-31)

Production workspace is clean. All dead code, old experiments, and stale artifacts have been
archived to `D:\AtlasTestMarch26\`. The workspace contains only:

- `src/` — Production source code (tightened: dead code removed from engine, main, cli)
- `data/` — Production data (model, board, inputs, outputs, v9d corpus)
- `docs/` — This documentation
- `tools/` — Production tools
- `tests/` — Active tests
- `config.yaml` — Production config
- `archives/` — Historical run archives
