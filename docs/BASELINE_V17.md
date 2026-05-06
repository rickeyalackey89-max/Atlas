# Atlas Golden Baseline — v17

> **Stamped:** 2026-05-03 (retrained with 47 dates May 3 2026)  
> **Status:** **GOLDEN BASELINE** — Current production model and canonical reference

---

## **GOLDEN BASELINE METRICS**

| Metric | Value | Notes |
|---|---|---|
| **LODO Brier (ensemble)** | **0.201402** | 47-date LODO — includes 3 playoff dates (Apr 30/May 1/May 2) |
| **Previous LODO (44 dates)** | 0.200748 | Pre-playoff baseline — delta +0.654 mB from playoff dilution |
| **Raw Brier (p)** | 0.250000 | Raw MC kernel (pre-built features fast path) |
| **Features** | **33** (v9d contract — NO sb_over_prob) | |
| **Temperature** | **1.04** | |
| **Seeds** | 65536, 9999, 137, 999, 98765, 54321, 12345 | |
| **Architecture** | direction-split GBMs (OVER d8/nl30, UNDER d11/nl50) | |
| **Training legs** | **170,552** across 47 dates | |
| **Date range** | 2026-02-09 to 2026-05-02 | |
| **Folds helped** | 46/47 | Only May 2 hurt (+16.4 mB — N=628 tiny playoff slate) |
| **GBM savings vs raw** | 48.6 mB | vs raw 0.250 kernel |
| **Global hit rate** | 0.4273 | |
| **Cache** | `data/model/_v17_resim_cache.pkl` | |

---

## **MARKETED SLIP BASELINE — VERIFIED 2026-05-03**

> Source: `tools/simulate_slips_from_cache.py` — 44 dates, 165,792 legs, scored against truth labels.  
> Config: hardcoded fallback thresholds (GOBLIN=0.57, STANDARD=0.30, DEMON=0.28). No `marketed_calibration.json`.  
> **This is the number to beat. Do not compare against any other test.**

| Slip | Won | Total | Win Rate | Breakeven | EV |
|---|---|---|---|---|---|
| **3-leg** | 26 | 43 | **60.5%** | 16.7% | **+2.63x** |
| **4-leg** | 16 | 43 | **37.2%** | 10.0% | **+2.72x** |
| **5-leg** | 9  | 43 | **20.9%** | 5.0%  | **+3.19x** |
| **Overall** | **51** | **129** | **39.5%** | — | **All +EV** |

**All three slip sizes are positive EV.** This baseline must be beaten before any config change is applied to production.

## **🔥 SLIP PERFORMANCE BY TIER**

| Tier | Slip-Eligible Legs | Hit Rate | Status |
|---|---|---|---|
| **GOBLIN OVER** | 48,708 | **64.6%** | 💰 **Profit engine** |
| **STANDARD OVER** | 8,311 | **49.8%** | ✅ **Volume filler** |
| **DEMON OVER** | 417 | **51.8%** | ⚡ **Selective multiplier** |
| **STANDARD UNDER** | 1,739 | **55.5%** | ✅ **Hedge quality** |

**Total slip-eligible:** 59,175 of 165,792 corpus legs (35.7%)

---

## Architecture

- **Direction-split GBMs**: Separate OVER and UNDER models (optimized hyperparameters).
- **7-seed ensemble**: Predictions averaged across 7 seeds for stability.
- **Temperature scaling**: T=1.04 applied to ensemble average.
- **33 features** (proven v9d feature set).
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

---

## Artifacts

- **Ensemble metadata:** `data/model/ensemble/ensemble_meta.json`
- **Resim cache:** `data/model/_v17_resim_cache.pkl` (44 dates, 165K legs)
- **Frozen backup:** `data/model/GOLDEN_V17_BASELINE/` (**IMMUTABLE**)
- **Contract:** `src/Atlas/contracts/model_contract.py`

---

## **⚠️ GOLDEN BASELINE RULES**

1. **This v17 model is FROZEN** — backed up to `GOLDEN_V17_BASELINE/`
2. **All future models must beat 0.200748 LODO** to be considered for promotion
3. **No regressions allowed** — every fold must improve over v17
4. **Contract validation required** before any production deployment
5. **This baseline represents the gold standard** for Atlas model performance

---

**🏆 v17 is the culmination of Atlas development — treat it as the definitive reference point.**