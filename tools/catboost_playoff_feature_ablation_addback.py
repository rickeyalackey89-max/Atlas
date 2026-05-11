"""
CatBoost Playoff Feature Ablation -- ADDBACK pass
==================================================
Tests the 9 features that v3 originally excluded by design (TE family,
rolling player hit rates, logit-p functions). For each, adds it to the
24-feature baseline and reruns LODO to see whether it carries signal that
v3's structural exclusion missed.

Method: leave-one-feature-IN
  baseline = 24 features (current v3)
  for each candidate in OMITTED_FEATURES:
      run LODO with baseline + candidate
      if d_agg > +0.5 mB worse than baseline -> ADD-BACK helped (feature carries signal)
      if d_agg < -0.5 mB better than baseline -> correctly excluded
      else neutral

Same hyperparams as the LOFO ablation for comparability:
  iter=500  depth=5  lr=0.05  scale=0.5  clip=0.20

Cost: 9 features x 9 folds x ~13s = ~20 min.

Output: data/model/catboost_playoff_feature_addback.json
"""
from __future__ import annotations

import json
import pathlib
import pickle
import time
import warnings

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool  # type: ignore[import-untyped]

warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).resolve().parents[1]

CACHE_PATH = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
OUT_PATH   = ROOT / "data" / "model" / "catboost_playoff_feature_addback.json"

# v3 baseline (24 features that were tested in LOFO pass)
BASELINE_FEATURES = [
    "p_for_cal", "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
    "is_assists", "is_threes", "thin_flag", "line_norm", "is_home_feat",
    "min_sensitivity", "game_total_norm", "is_b2b", "margin", "stat_cat",
    "tier_cat", "line_dist", "tail_risk", "line_tightness", "margin_x_under",
    "q_blowout", "rate_cv", "q_x_under",
]

# Features v3 excluded by design -- now testing whether that was correct
OMITTED_FEATURES = [
    "player_te",
    "player_stat_te",
    "player_dir_te",
    "player_n_norm",
    "l40_hr",
    "l20_edge",
    "l10_has",
    "logit_p_x_demon",
    "abs_logit_p",
]

CAT_FEATURES_ALL = ["stat_cat", "tier_cat"]

CAT_PARAMS: dict = dict(
    iterations=500,
    depth=5,
    learning_rate=0.05,
    l2_leaf_reg=6.0,
    min_data_in_leaf=50,
    loss_function="RMSE",
    eval_metric="RMSE",
    random_seed=42,
    verbose=False,
    early_stopping_rounds=50,
    use_best_model=True,
)
RESIDUAL_CLIP  = 0.20
RESIDUAL_SCALE = 0.5


def brier(y_true, y_pred):
    return float(np.mean((y_pred - y_true) ** 2))


def prep_X(df: pd.DataFrame, features: list[str]):
    cat_in = [c for c in CAT_FEATURES_ALL if c in features]
    X = df[features].copy()
    for col in features:
        if col in cat_in:
            X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0).astype(int).astype(str)
        else:
            X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0.0).astype(float)
    return X, cat_in


def make_pool(X, y, cat_in):
    if y is not None:
        return Pool(X, label=y, cat_features=cat_in)
    return Pool(X, cat_features=cat_in)


def apply_residual(p, r):
    return np.clip(p + RESIDUAL_SCALE * np.clip(r, -RESIDUAL_CLIP, RESIDUAL_CLIP),
                   1e-4, 1.0 - 1e-4)


def run_lodo(cv, features, hit_arr, pforcal_arr, residual_target, date_arr, dates):
    X_full, cat_in = prep_X(cv, features)
    oof_residual = np.full(len(cv), np.nan)
    fold_deltas_mb = []

    for held in dates:
        test_mask  = date_arr == held
        train_mask = ~test_mask
        y_tr_all   = residual_target[train_mask]
        X_tr_all   = X_full[train_mask].reset_index(drop=True)
        X_te       = X_full[test_mask].reset_index(drop=True)

        rng       = np.random.default_rng(42)
        n_tr      = len(X_tr_all)
        eval_idx  = rng.choice(n_tr, size=max(1, n_tr // 10), replace=False)
        train_idx = np.setdiff1d(np.arange(n_tr), eval_idx)

        train_pool = make_pool(X_tr_all.iloc[train_idx], y_tr_all[train_idx], cat_in)
        eval_pool  = make_pool(X_tr_all.iloc[eval_idx],  y_tr_all[eval_idx],  cat_in)
        test_pool  = make_pool(X_te, None, cat_in)

        m = CatBoostRegressor(**CAT_PARAMS)
        m.fit(train_pool, eval_set=eval_pool)
        pred = m.predict(test_pool)
        oof_residual[test_mask] = pred

        p_after  = apply_residual(pforcal_arr[test_mask], pred)
        b_before = brier(hit_arr[test_mask], pforcal_arr[test_mask])
        b_after  = brier(hit_arr[test_mask], p_after)
        fold_deltas_mb.append((held, int(test_mask.sum()), (b_after - b_before) * 1000))

    valid    = ~np.isnan(oof_residual)
    p_oof    = apply_residual(pforcal_arr[valid], oof_residual[valid])
    b_before = brier(hit_arr[valid], pforcal_arr[valid])
    b_after  = brier(hit_arr[valid], p_oof)
    agg_mb   = (b_after - b_before) * 1000
    worst_mb = max(d for _, _, d in fold_deltas_mb)

    return {
        "agg_brier_after": b_after,
        "agg_delta_mB":    agg_mb,
        "worst_slate_mB":  worst_mb,
        "fold_deltas":     [{"date": d, "n": n, "delta_mB": dm} for d, n, dm in fold_deltas_mb],
    }


def main() -> int:
    print("=== CatBoost Playoff Feature ADDBACK Ablation ===")
    print(f"Cache:    {CACHE_PATH}")
    print(f"Settings: iter={CAT_PARAMS['iterations']}  depth={CAT_PARAMS['depth']}  "
          f"lr={CAT_PARAMS['learning_rate']}  scale={RESIDUAL_SCALE}  clip={RESIDUAL_CLIP}")
    print(f"Baseline: {len(BASELINE_FEATURES)} features (v3 default)")
    print(f"Testing:  {len(OMITTED_FEATURES)} omitted features")
    print()

    if not CACHE_PATH.exists():
        print(f"ERROR: cache not found at {CACHE_PATH}")
        return 1

    print("Loading cache...")
    with open(CACHE_PATH, "rb") as f:
        cache = pickle.load(f)
    cv = cache["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)

    # Verify all candidate features exist in the cache
    missing = [f for f in OMITTED_FEATURES if f not in cv.columns]
    if missing:
        print(f"ERROR: features missing from cache: {missing}")
        return 1

    hit_arr      = cv["hit"].astype(float).to_numpy()
    pforcal_arr  = pd.to_numeric(cv["p_for_cal"], errors="coerce").fillna(0.5).to_numpy()
    residual_tgt = hit_arr - pforcal_arr
    date_arr     = cv["game_date"].astype(str).str[:10].values
    dates        = sorted(np.unique(date_arr).tolist())

    print(f"  {len(cv):,} legs | {len(dates)} dates")
    print(f"  Baseline p_for_cal Brier: {brier(hit_arr, pforcal_arr):.6f}")
    print()

    # Show coverage of candidate features
    print("Candidate feature stats in cache:")
    for f in OMITTED_FEATURES:
        v = pd.to_numeric(cv[f], errors="coerce")
        cov = v.notna().sum() / len(cv) * 100
        nz = (v.fillna(0) != 0).mean() * 100
        print(f"  {f:<22}  cov={cov:5.1f}%  nonzero={nz:5.1f}%  mean={v.mean():+.4f}  std={v.std():.4f}")
    print()

    print(f"[BASELINE] {len(BASELINE_FEATURES)} features...", flush=True)
    t0 = time.time()
    baseline = run_lodo(cv, BASELINE_FEATURES, hit_arr, pforcal_arr, residual_tgt, date_arr, dates)
    print(f"  agg={baseline['agg_delta_mB']:+7.2f} mB  worst={baseline['worst_slate_mB']:+6.2f} mB  ({time.time()-t0:.1f}s)")
    print()

    base_agg   = baseline["agg_delta_mB"]
    base_worst = baseline["worst_slate_mB"]

    print(f"[ADDBACK] adding each omitted feature, comparing to baseline...")
    print(f"  {'feature':<22}  {'agg_mB':>8}  {'d_agg':>8}  {'worst_mB':>9}  {'d_worst':>8}  {'sec':>5}  class")
    print(f"  {'-'*22}  {'-'*8}  {'-'*8}  {'-'*9}  {'-'*8}  {'-'*5}  -----")

    results = {}
    for feat in OMITTED_FEATURES:
        feats_plus = BASELINE_FEATURES + [feat]
        t0 = time.time()
        r = run_lodo(cv, feats_plus, hit_arr, pforcal_arr, residual_tgt,
                     date_arr, dates)
        elapsed = time.time() - t0
        d_agg   = r["agg_delta_mB"]   - base_agg     # negative = adding helped (better than baseline)
        d_worst = r["worst_slate_mB"] - base_worst   # negative = adding fixed worst slate

        # For ADDBACK, sign convention is OPPOSITE of LOFO:
        #   d_agg < -0.5  -> adding feature improved aggregate -> HELPFUL (should be added)
        #   d_agg > +0.5  -> adding feature hurt aggregate     -> HARMFUL (correctly excluded)
        if d_agg < -0.5:
            cls = "HELPFUL"
        elif d_agg > +0.5:
            cls = "HARMFUL"
        else:
            cls = "neutral"
        if d_worst < -1.0:
            cls += "+SLATE_FIX"

        results[feat] = {
            "agg_delta_mB":         d_agg,
            "worst_slate_delta_mB": d_worst,
            "agg_after_add_mB":     r["agg_delta_mB"],
            "worst_after_add_mB":   r["worst_slate_mB"],
            "fold_deltas":          r["fold_deltas"],
            "classification":       cls,
            "elapsed_sec":          round(elapsed, 1),
        }
        print(f"  {feat:<22}  {r['agg_delta_mB']:>+8.2f}  {d_agg:>+8.2f}  "
              f"{r['worst_slate_mB']:>+9.2f}  {d_worst:>+8.2f}  {elapsed:>5.1f}  {cls}",
              flush=True)

    print()
    print("=== Summary (sorted by impact -- most helpful first) ===")
    sorted_results = sorted(results.items(), key=lambda kv: kv[1]["agg_delta_mB"])
    print(f"  {'feature':<22}  {'d_agg':>8}  {'d_worst':>8}  class")
    print(f"  {'-'*22}  {'-'*8}  {'-'*8}  -----")
    for feat, r in sorted_results:
        print(f"  {feat:<22}  {r['agg_delta_mB']:>+8.2f}  {r['worst_slate_delta_mB']:>+8.2f}  {r['classification']}")

    print()
    print("Buckets (ADDBACK semantics):")
    helpful = [f for f, r in sorted_results if r["classification"].startswith("HELPFUL")]
    harmful = [f for f, r in sorted_results if r["classification"].startswith("HARMFUL")]
    neutral = [f for f, r in sorted_results if r["classification"].startswith("neutral")]
    slate_fix = [f for f, r in sorted_results if "SLATE_FIX" in r["classification"]]
    print(f"  HELPFUL  ({len(helpful)}, should be ADDED): {', '.join(helpful) if helpful else '(none)'}")
    print(f"  neutral  ({len(neutral)}, no benefit):       {', '.join(neutral) if neutral else '(none)'}")
    print(f"  HARMFUL  ({len(harmful)}, correctly EXCLUDED): {', '.join(harmful) if harmful else '(none)'}")
    print(f"  +SLATE_FIX ({len(slate_fix)}):                {', '.join(slate_fix) if slate_fix else '(none)'}")

    payload = {
        "settings":          {**CAT_PARAMS, "residual_clip": RESIDUAL_CLIP, "residual_scale": RESIDUAL_SCALE},
        "baseline":          baseline,
        "baseline_features": BASELINE_FEATURES,
        "tested_features":   OMITTED_FEATURES,
        "addback":           results,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"\nWrote: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
