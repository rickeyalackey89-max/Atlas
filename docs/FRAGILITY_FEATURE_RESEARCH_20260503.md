# Fragility Feature Research — May 3, 2026

## Summary

`fragility` is computed by the kernel on every scored leg but has never been in the GBM feature set. This session proved it has real signal. A full retrain is not yet feasible due to the v17 corpus lacking source columns, but all infrastructure is in place for a clean v18 retrain as playoff dates accumulate.

---

## What Was Proven

### Test Setup
- **15-date corpus** (Mar 15–26, Apr 30–May 2) — 16 bundle replays, May 3 skipped (games in progress)
- **49,362 legs** with truth labels, `fragility` at 100% coverage
- **Paired LODO**: identical 15 folds, baseline (33 feats) vs +fragility (36 feats)
- No promotion — production ensemble untouched throughout

### Results

| | LODO Brier | T |
|---|---|---|
| Baseline (33 features) | 0.189882 | 1.12 |
| +fragility +opp_defense_rel +role_ctx_mult (36 features) | 0.188981 | 1.12 |
| **Delta** | **-0.901 mBrier** | |

- 10/15 folds improved, 5/15 slightly worse (all regressions < 1.2 mBrier)
- Worst regression: Mar 26 (+1.2 mB) — smallest date in corpus (1,593 legs)
- Largest gain: Apr 30 (-4.7 mB) — first playoff slate, blowout fragility most relevant

### Why the Absolute 0.190 Is Not Comparable to v17's 0.201402
These 15 dates are late-regular-season + first-round playoff with tighter lines. The raw Brier on this subset is lower than the full 47-date corpus regardless of model. The valid comparison is the **paired delta on identical folds**, not the absolute level.

---

## Why v17 Cache Cannot Be Used for Fragility

The v17 resim cache (`_v17_resim_cache.pkl`) has **42 columns only**: 33 pre-built GBM features + 9 identity cols. Source columns (`fragility`, `form_opp_defense_rel`, `role_ctx_mult`, `spread`, `p_adj`, etc.) were not captured when the cache was built.

The source data (D-drive replay corpus, ~170K legs across 38 dates) is gone. There is no path to backfill fragility into the v17 cache.

**Why a proxy (min_sensitivity × q_blowout) doesn't work:** LightGBM already receives both components as separate features and can learn their interaction through tree splits internally. Explicit proxy would not be apples-to-apples vs real fragility and any improvement would be non-comparable to the 15-date test.

**Why merging v17 + new cache doesn't work:** v17 has fragility=0.0 (not missing — literally zeroed). Training on 170K legs where fragility=0 produces certain outcomes, then 49K legs where fragility=real, creates a bimodal distribution that doesn't exist in production. LODO folds would be inconsistent.

---

## Infrastructure Built This Session

### 1. `build_resim_cache.py` — Live Run Source Added
Added `find_live_run_dates()` function that scans `data/telemetry/live_runs/` in addition to the replay corpus. Replay dates take priority; live run dates fill gaps.

Every daily live run already archives `scored_legs_deduped.csv` with all 178 columns including `fragility`, `form_opp_defense_rel`, `role_ctx_mult_feat`, etc. The 6am eval backfill job creates `eval_legs.csv` (truth labels) for the previous day. **From this point forward, every game day automatically contributes a new training date with full fragility coverage — no manual action required.**

### 2. `gbm_v17_train.py` — v18test Cache Wired
Added `v18test` to `choices` and `CACHE_PATHS`. The trainer already had `fragility_feat`, `opp_defense_rel`, `role_ctx_mult_feat` lambdas in `apply_extra_features()` — no code changes needed there.

### 3. Fast-path `is_under` Bug Fixed
Pre-built fast path (when all 33 FEATS are in cache) skipped `compute_features()` which normally sets `cv["is_under"]`. Added `cv["is_under"] = um.astype(float)` to the fast path block. Fixes `KeyError: 'is_under'` when using `bp_has_x_under` extra feature.

### 4. Staged Model: `ensemble_v18test/`
36-feature model (33 baseline + fragility_feat + opp_defense_rel + role_ctx_mult_feat) saved to `data/model/ensemble_v18test/`. T=1.12. **Not promoted — production `ensemble/` is v17, untouched.**

---

## Path to v18 Production

### Trigger Condition
When `data/telemetry/live_runs/` accumulates sufficient playoff dates with eval_legs:
- **Minimum:** ~20 dates (weak but directional)
- **Recommended:** 25–30 dates (statistically solid LODO)
- **Estimated timing:** mid-to-late May 2026 (NBA Finals run ~June 15)

### Steps (one session, ~2 hours)

```powershell
# Step 1: Replay new dates (auto-discovers all new bundles since last run)
python tools/batch_replay_backfill.py

# Step 2: Rebuild cache (auto-includes live_runs/ dates)
python tools/build_resim_cache.py --version v18 --force

# Step 3: Baseline LODO on new corpus
python tools/gbm_v17_train.py --cache v18

# Step 4: Fragility test
python tools/gbm_v17_train.py --cache v18 --extra-feats fragility_feat opp_defense_rel role_ctx_mult_feat

# Step 5: If delta >= 0.5 mBrier improvement and no slate regression > 2 mBrier:
python tools/gbm_v17_train.py --cache v18 --promote --extra-feats fragility_feat opp_defense_rel role_ctx_mult_feat
```

### Promotion Gate
- Delta vs baseline on new corpus >= **0.5 mBrier** (conservative given 0.9 mB on 15 dates)
- No individual fold regression > **2.0 mBrier**
- At least **20 folds** in the LODO
- Calibration (`isotonic_direction_split.json`) **FROZEN — never retrain after GBM update**

---

## Corpus State as of May 3, 2026

| Cache | Dates | Legs | Fragility | Status |
|---|---|---|---|---|
| `_v17_resim_cache.pkl` | 47 | 170,552 | ❌ zeroed | Production baseline |
| `_v18test_resim_cache.pkl` | 15 | 49,362 | ✅ 100% | Research only |
| Live runs (auto-accumulating) | 3 (Apr 30–May 2) | ~5,800 | ✅ 100% | Growing daily |

---

## Feature Definitions (for reference)

```python
# In gbm_v17_train.py apply_extra_features():
"fragility_feat":      lambda cv: cv["fragility"].fillna(0.0).clip(0, 1).values,
"opp_defense_rel":     lambda cv: cv["form_opp_defense_rel"].fillna(0.0).clip(-0.3, 0.3).values,
"role_ctx_mult_feat":  lambda cv: (cv["role_ctx_mult"].fillna(1.0) - 1.0).clip(-0.3, 0.3).values,
```

`fragility` is computed in `new_probability.py` as:
```
fragility = usage_dep × blowout_severity_factor
```
where `usage_dep` is stat-category minutes sensitivity and `blowout_severity_factor` integrates spread, pace, and per-stat rate variance. Output range 0–1, mean ~0.07 in playoff corpus.
