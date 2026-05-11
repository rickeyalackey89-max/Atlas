# Playoff Regime Fixes — May 2026

Applied May 9, 2026. These are **temporary mitigations** until the GBM is retrained on playoff data (target: Tuesday, May 13 with 14 playoff dates).

---

## The Problem

The GBM and target encodings were trained on regular-season data. Playoff basketball has a different statistical regime:

- **8-man rotations only** — bench players who padded stats all season are not playing
- **No rest nights** — every game matters, starters play full minutes
- **Tighter lines** — sportsbooks adjust faster than the model's training distribution
- **Slower pace** — half-court offense, more defensive intensity → fewer counting stats

### Observed Calibration Gap (May 8, 2026 eval — 1,036 UNDER legs)

| UNDER Tier | Model says | Actually hits | Gap |
|---|---|---|---|
| 0.50–0.55 | 52.0% | **38.2%** | +13.9% 🚨 |
| 0.55–0.60 | 57.5% | **39.0%** | +18.5% 🚨 |
| 0.60–0.65 | 62.7% | **68.7%** | -6.0% ✅ |
| 0.65–0.70 | 67.6% | **75.9%** | -8.3% ✅ |
| 0.70–0.75 | 72.5% | **52.7%** | +19.8% 🚨 |
| 0.80–0.85 | 81.7% | **43.4%** | +38.3% 🚨 |

**Only the 0.60–0.70 UNDER band is well-calibrated.** Everything else is broken.

### Root Cause: `player_dir_te` Bias

`player_dir_te` is a per-player, per-direction target encoding learned from the full regular season. In playoffs:
- Starters have had their lines tightened by sportsbooks
- Players with high UNDER TE historically went under because rotation minutes were inconsistent — that no longer applies
- The same TE value is stamped across **all stats** for a given player/direction, so one high-TE player floods the top of the selection pool with UNDER legs regardless of individual stat calibration

Example from May 9: Austin Reaves UNDER TE=0.239 → all 8 of his UNDER stats score above most OVER legs.

---

## Fixes Applied

### 1. UNDER Probability Window (slip_builders.py + config.yaml)

Hard filter — UNDER legs outside 0.60–0.70 are excluded from all slip families (System, Windfall, DemonHunter).

```yaml
# config.yaml — slip_build section
min_under_prob: 0.60
max_under_prob: 0.70
```

- Below 0.60: model underestimates, actual hit rate only ~38–39%
- Above 0.70: model overestimates, actual hit rate collapses to 43–53%
- The window preserves the only calibrated UNDER band

### 2. UNDER Window in Marketed Slip Builder (marketed_slip_builder.py + config.yaml)

Same window applied to `_qualify_legs()` using `p_cal` (pre-haircut):

```yaml
# config.yaml — marketed_slips section
min_under_prob: 0.60
max_under_prob: 0.70
```

### 3. STANDARD UNDER Scoring Fix (marketed_slip_builder.py)

For STANDARD tier legs in the marketed builder, `standard_score` was `player_dir_te` for both directions. Changed so:
- **OVER STANDARD** → still uses `player_dir_te` (still valid signal for OVERs)
- **UNDER STANDARD** → uses `p_cal_marketed` (actual model probability)

This prevents high-TE players from flooding the UNDER pool based on stale regular-season history.

### 4. FTA Disabled (config.yaml)

FTA legs were appearing in top slips. Disabled across all families until retrain:

```yaml
# config.yaml — slip_build section
exclude_stat_directions:
- FTA_over
- FTA_under

# config.yaml — marketed_slips section
excluded_stats:
- FTA  # (alongside BLK, STL, TO)
```

---

## What to Do on Tuesday (GBM Retrain)

1. **Run `tools/eval_date.py`** for all playoff dates since May 1 to populate eval legs
2. **Check resim cache** — confirm playoff dates are not already in `_v18_resim_cache.pkl`
3. **Expand LODO corpus** — replay missing playoff dates to add to training data
4. **Retrain GBM** via `tools/gbm_v12_train.py` (or current version) with playoff dates included
5. **Retrain direction isotonic** via `tools/train_direction_calibrator.py` on expanded corpus
6. **Re-evaluate `player_dir_te` window** — consider computing TE on last-30-days only, not full season
7. **Revisit UNDER window bounds** — after retrain, run same tier analysis to see if 0.60–0.70 still holds or shifts
8. **Re-enable FTA** if playoff-era FTA calibration looks reasonable
9. **Revert UNDER STANDARD scoring** if TE signal recovers after playoff-aware retrain

---

## Files Changed

| File | Change |
|---|---|
| `src/Atlas/core/slip_builders.py` | UNDER probability window filter (min/max) |
| `src/Atlas/core/marketed_slip_builder.py` | UNDER window in `_qualify_legs()`; UNDER STANDARD scored on `p_cal_marketed` not TE |
| `config.yaml` | `min_under_prob`, `max_under_prob`, `exclude_stat_directions` (FTA), `marketed_slips.min_under_prob/max_under_prob/excluded_stats` |
