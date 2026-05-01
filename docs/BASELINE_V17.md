# Atlas Golden Baseline — v17

> **Stamped:** 2026-04-30  
> **Status:** **GOLDEN BASELINE** — Current production model and canonical reference

---

## **🥇 GOLDEN BASELINE METRICS**

| Metric | Value | Notes |
|---|---|---|
| **🎯 LODO Brier (ensemble)** | **0.200748** | Leave-one-date-out cross-validation |
| **🎯 Slip-eligible hit rate** | **62.3%** | p_cal ≥ 0.52 (actual slip input) |
| **Raw Brier (p_adj)** | 0.216164 | After blowout + under-relief adjustments |
| **Raw Brier (p)** | 0.216503 | Raw Monte Carlo kernel output |
| **Features** | **33** (v9d architecture) |
| **Temperature** | **1.04** |
| **Seeds** | 65536, 9999, 137, 999, 98765, 54321, 12345 |
| **Architecture** | **dn-d11nl50-top7-33feat** (direction-split GBMs) |
| **Training legs** | **165,792** across 44 dates |
| **Date range** | 2026-02-09 to 2026-04-12 |
| **LODO improvement** | **44/44 folds improved** (no regressions) |
| **Previous baseline** | v12: 0.201094 → **0.346 mB improvement** |

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