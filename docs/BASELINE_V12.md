# Atlas Baseline — v12

> **Stamped:** 2026-04-08
> **Status:** Historical baseline (superseded by v14). Retained for reference only.

---

## Baseline Metrics

| Metric | Value | Notes |
|---|---|---|
| **LODO Brier (ensemble)** | **0.199212** | Leave-one-date-out cross-validation |
| **Raw Brier (p_role)** | 0.212041 | Before ensemble calibration, after opp-defense + pace |
| **Raw Brier (p_adj)** | 0.217823 | After blowout + under-relief adjustments |
| **Raw Brier (p)** | 0.238639 | Raw Monte Carlo kernel output |
| **Features** | 33 (v9d architecture) |
| **Temperature** | 1.06 |
| **Seeds** | 65536, 9999, 137, 999, 98765, 54321, 12345 |
| **Architecture** | dn-d8nl30/d11nl50 (direction-split GBMs) |
| **Training legs** | 189,545 across 38 dates |
| **Date range** | 2026-02-09 to 2026-04-04 |
| **Global hit rate** | 0.4753 |
| **Previous version** | v9d (LODO 0.196266, trained on OLD kernel — not comparable) |

Full metadata is stamped in `data/model/ensemble/ensemble_meta.json`.
Resim cache: `data/model/_v12_resim_cache.pkl` (38 dates, 189K legs, 210 columns).

---

## Architecture

- **Direction-split GBMs**: Separate OVER and UNDER models (different hyperparameters).
- **7-seed ensemble**: Predictions averaged across 7 seeds for stability.
- **Temperature scaling**: T=1.06 applied to ensemble average.
- **33 features** (same v9d feature set).
- **2 categorical features**: `stat_cat`, `tier_cat`.

### GBM Parameters

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

### v9d → v12 Changes

| Aspect | v9d (old kernel) | v12 (current kernel) |
|---|---|---|
| GBM OVER depth/leaves | 11/50 | **8/30** |
| GBM UNDER depth/leaves | 15/90 | **11/50** |
| Temperature | 0.98 | **1.06** |
| `star_minute_drop` | ~3.0 | **6.0** |
| `starter_minute_drop` | N/A | **3.5** |
| `recency_halflife` | 12 | **4** |
| `rate_min_correlation` | 0.15 | **0.35** |
| Per-stat `rate_std_mult` | flat 1.0 | **PTS 1.3, PRA 1.3, AST 1.2, etc.** |
| Training legs | 171K / 33 dates | **189K / 38 dates** |
| LODO Brier | 0.196266 | **0.199212** |

**Note:** v9d LODO (0.196266) is NOT a valid comparison target — it was trained on a kernel
that no longer exists. The v12 ensemble is the correct calibrator for today's kernel output.

---

## Probability Chain Quality

The kernel produces probabilities through three stages. Each stage's Brier on the 189K
training corpus:

| Stage | Brier | Delta vs prior | What happens |
|---|---|---|---|
| `p` (raw MC) | 0.238639 | — | 10K sim of minutes × rate |
| `p_role` (opp-defense + pace) | 0.212041 | **-26.6 mB** | Opponent defense, pace adjustments |
| `p_adj` (blowout + under-relief) | 0.217823 | **+5.8 mB** | Blowout minute drops, under-relief |
| `p_cal` (GBM LODO) | 0.199212 | **-18.6 mB** | 7-seed ensemble calibration |

**Critical finding:** The blowout/under-relief layer (p_role → p_adj) **destroys 5.8 mB of
signal**. The GBM partially recovers this via q_blowout features, but some information is
permanently lost.

---

## Diagnostic Breakdowns

### Per-Stat Brier (p_adj)

| Stat | Brier | Hit Rate | N |
|---|---|---|---|
| FG3M | 0.1935 | 0.4539 | 13,894 |
| REB | 0.2052 | 0.4616 | 25,250 |
| AST | 0.2058 | 0.4635 | 19,960 |
| RA | 0.2188 | 0.4716 | 24,792 |
| PR | 0.2210 | 0.4797 | 24,528 |
| PA | 0.2220 | 0.4817 | 20,412 |
| PTS | 0.2254 | 0.4871 | 32,349 |
| PRA | 0.2342 | 0.4876 | 28,360 |

**Combo stats (PRA, PA, PR) and PTS are the worst.** FG3M, REB, AST are cleanest.

### Per-Tier Brier (p_adj)

| Tier | Brier | Hit Rate | N |
|---|---|---|---|
| DEMON | 0.1863 | 0.4151 | 91,491 |
| GOBLIN | 0.2403 | 0.5504 | 61,589 |
| STANDARD | 0.2589 | 0.4995 | 36,465 |

**DEMON is easiest** (lines far from player mean → more predictable).
**STANDARD is hardest** (tight lines, ~50% coin flip).

### Per-Direction Brier (p_adj)

| Direction | Brier | Hit Rate | N |
|---|---|---|---|
| OVER | 0.2123 | 0.4147 | 121,033 |
| UNDER | 0.2277 | 0.5824 | 68,512 |

**UNDER is 15.4 mB worse** than OVER. UNDER actual hit rate (58.2%) is systematically
higher than the model's average prediction — the kernel consistently underestimates UNDER
hit probability.

### Calibration Gap (p_adj vs actual)

| p_adj Tier | Model Mean | Actual HR | Gap | N |
|---|---|---|---|---|
| 0.0-0.3 | 0.195 | 0.229 | +3.5pp | 52,378 |
| 0.3-0.4 | 0.351 | 0.413 | +6.2pp | 33,593 |
| 0.4-0.45 | 0.425 | 0.495 | +7.0pp | 18,519 |
| 0.45-0.5 | 0.475 | 0.542 | +6.7pp | 18,388 |
| 0.5-0.55 | 0.525 | 0.587 | +6.2pp | 17,697 |
| 0.55-0.6 | 0.575 | 0.644 | +6.9pp | 16,368 |
| 0.6-0.7 | 0.647 | 0.738 | **+9.2pp** | 27,913 |
| 0.7-1.0 | 0.744 | 0.753 | +0.9pp | 4,689 |

**Systematic positive gap across all tiers** — the raw kernel under-predicts outcomes
everywhere. The GBM calibrator's primary job is to correct this bias. The 0.6-0.7 tier
has the worst gap (+9.2pp).

### Under-Relief Impact

- Legs with under-relief active: 33,667 (17.8%)
- Brier before relief: 0.222820
- Brier after relief: 0.227944
- **Impact: +5.1 mB WORSE** on affected legs

Under-relief is actively harmful in its current form.

### Blowout Distribution

- q_blowout range: 0.123 to 1.000 (minimum is 0.123 — no close games exist)
- Mean q_blowout: 0.455
- All legs have blowout exposure; the adjustment is universal, not selective

### Role Context

- **0% of legs have role_ctx_mult active** in the training corpus
- The share matrix / role context layer is not contributing to the resim cache data
- All role context signal would come from live runs with actual injury state

### External Priors

- 7.5% of legs have BettingPros external prior data
- Sparse coverage limits the feature's contribution

### Date-Level Volatility

| Stat | Value |
|---|---|
| Mean per-date Brier | 0.217466 |
| Std | 0.009258 |
| Best date | 2026-03-30 (0.1871, N=3842) |
| Worst date | 2026-03-15 (0.2393, N=3476) |

---

## Feature List (33 features)

```
z_line, min_cv, is_combo, bp_score_gated, bp_has, is_assists, is_threes,
games_norm, thin_flag, line_norm, is_home_feat, min_sensitivity,
game_total_norm, is_b2b, l20_edge, l10_has, margin, stat_cat, tier_cat,
l40_hr, logit_p_x_demon, player_te, player_stat_te, player_dir_te,
player_n_norm, line_dist, tail_risk, line_tightness, margin_x_under,
q_blowout, rate_cv, abs_logit_p, q_x_under
```

Categorical: `stat_cat`, `tier_cat`.

---

## Evaluation Rules (v12-era — see ATLAS_MODEL_CONTEXT.md for current v14 rules)

1. **Compare against v14 production** (LODO 0.198097, raw Brier 0.215645). v12 metrics below are historical only.
2. **Use replay mode** for testing changes — never compare against a current-day live run.
3. **Single-run replay first**, then 3-run backtest, then full corpus only for final promotion.
4. **Use `eval_legs.csv`** for truth-backed evaluation (not `scored_legs_deduped.csv` which lacks outcomes).
5. **Reader corpus** lives at `data/telemetry/v9d_corpus/` — do not modify or delete.
6. **Resim cache** at `data/model/_v14_resim_cache.pkl` — check this BEFORE running batch replays.
7. A change must beat v14 on LODO or live replay corpus (and not regress any single slate) to be promoted.

---

## Kernel Config (v12 production)

```yaml
blowout:
  spread_sd: 10.0
  threshold_margin: 15.5
  star_minute_drop: 6.0
  role_minute_drop: 0.5
  recency_halflife: 4
  rate_min_correlation: 0.35
  rate_std_multiplier_by_stat:
    PTS: 1.3, PRA: 1.3, PR: 1.3, PA: 1.3
    AST: 1.2, RA: 1.1, REB: 1.0, FG3M: 1.0
  rotation_tiers:
    starter_minute_drop: 3.5
    bench_minute_drop: 0.5

posthoc_calibrator:
  enabled: true
  ensemble_dir: data/model/ensemble
  mode: replace

telemetry:
  active_calibration: isotonic_hybrid_protect_role_ctx_on

role_ctx:
  enabled: true
  projection_clamp_lo: 0.9
  projection_clamp_hi: 1.2
  variance_k: 0.65
  under_relief_factor: 0.0  # (top-level override: 0.11)
```

---

## Known Issues & Opportunities

1. **Blowout layer is net-negative** — p_role → p_adj destroys 5.8 mB. The GBM partially
   compensates via q_blowout features but can't fully recover the damage.
2. **Under-relief actively hurts** — +5.1 mB on affected legs. Current factor (0.11 top-level,
   0.0 in role_ctx) is harmful.
3. **UNDER direction AUC ~0.52** — near coin-flip discrimination. OVER has real signal,
   UNDER does not.
4. **Role context at 0% in training data** — the GBM has never seen role-adjusted legs.
   Live runs with injuries will produce different distributions than training.
5. **Systematic positive calibration gap** — kernel under-predicts everywhere, worst at p=0.6-0.7.
6. **PRA/PTS combo stats are weakest** — highest Brier, may benefit from targeted improvement.
7. **External priors have only 7.5% coverage** — too sparse to reliably help.
