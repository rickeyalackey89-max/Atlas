"""
CatBoost Playoff LODO Trainer -- v2
=====================================
Reads _v1_playoff_resim_cache.pkl (same structure as GBM resim cache).
Trains a CatBoost calibrator using all 33 GBM features + p_for_cal on the
9-date playoff corpus via Leave-One-Date-Out cross-validation.

This is an apples-to-apples comparison with the GBM LODO: same features,
same corpus, same LODO split logic, same evaluation metric.

Cache must be built first:
    python tools/build_playoff_resim_cache.py

Then:
    python tools/catboost_playoff_lodo.py
    python tools/catboost_playoff_lodo.py --promote
"""
from __future__ import annotations

import argparse
import json
import pathlib
import pickle
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool  # type: ignore[import-untyped]

warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CACHE_PATH    = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
MODEL_OUT     = ROOT / "data" / "model" / "catboost_playoff"
META_PATH     = ROOT / "data" / "model" / "catboost_playoff_ensemble_meta.json"
MANIFEST_PATH = ROOT / "data" / "model" / "catboost_playoff_manifest.json"

# ---------------------------------------------------------------------------
# Features
# 33 base GBM features (v9d contract) + p_for_cal as the primary prob signal.
# stat_cat and tier_cat are treated as CatBoost native categoricals.
# ---------------------------------------------------------------------------
BASE_FEATS = [
    "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
    "is_assists", "is_threes", "games_norm", "thin_flag", "line_norm",
    "is_home_feat", "min_sensitivity", "game_total_norm", "is_b2b",
    "l20_edge", "l10_has", "margin", "stat_cat", "tier_cat", "l40_hr",
    "logit_p_x_demon", "player_te", "player_stat_te", "player_dir_te",
    "player_n_norm", "line_dist", "tail_risk", "line_tightness",
    "margin_x_under", "q_blowout", "rate_cv", "abs_logit_p", "q_x_under",
]
# p_for_cal added as the 34th feature
FEATURES     = BASE_FEATS + ["p_for_cal"]
CAT_FEATURES = ["stat_cat", "tier_cat"]

# ---------------------------------------------------------------------------
# CatBoost hyperparameters -- deep, thorough sweep
# ---------------------------------------------------------------------------
CAT_PARAMS: dict = dict(
    iterations=800,
    depth=8,
    learning_rate=0.02,
    l2_leaf_reg=6,
    bagging_temperature=1.0,
    random_strength=2.0,
    min_data_in_leaf=30,
    loss_function="Logloss",
    eval_metric="Logloss",
    auto_class_weights="Balanced",
    random_seed=42,
    verbose=100,
    early_stopping_rounds=50,
    use_best_model=True,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def brier(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean((y_pred - y_true) ** 2))


def prep_X(df: pd.DataFrame) -> pd.DataFrame:
    X = df[FEATURES].copy()
    for col in FEATURES:
        if col in CAT_FEATURES:
            X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0).astype(int).astype(str)
        else:
            X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0.0).astype(float)
    return X


def make_pool(X: pd.DataFrame, y: np.ndarray | None = None) -> Pool:
    if y is not None:
        return Pool(X, label=y, cat_features=CAT_FEATURES)
    return Pool(X, cat_features=CAT_FEATURES)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(promote: bool = False) -> int:
    MODEL_OUT.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("=== CatBoost Playoff LODO Trainer v2 ===")
    print(f"Timestamp: {run_ts}")
    print(f"Cache:     {CACHE_PATH}")
    print()

    # ------------------------------------------------------------------
    # 1. Load resim cache
    # ------------------------------------------------------------------
    if not CACHE_PATH.exists():
        print(f"ERROR: Cache not found at {CACHE_PATH}")
        print("  Run: python tools/build_playoff_resim_cache.py")
        return 1

    print("[1/4] Loading resim cache...")
    with open(CACHE_PATH, "rb") as f:
        cache = pickle.load(f)

    cv              = cache["cv"].copy()
    dates_cached    = cache["dates"]
    raw_brier_cache = cache["raw_brier"]

    print(f"  {len(cv):,} legs | {len(dates_cached)} dates | cache Brier={raw_brier_cache:.6f}")
    print(f"  Dates: {dates_cached}")

    # ------------------------------------------------------------------
    # 2. Validate and prepare
    # ------------------------------------------------------------------
    print(f"\n[2/4] Validating {len(FEATURES)} features...")

    if "p_for_cal" not in cv.columns:
        if "p_cal" in cv.columns:
            cv["p_for_cal"] = cv["p_cal"]
            print("  [WARN] p_for_cal missing -- using p_cal")
        elif "p_new" in cv.columns:
            cv["p_for_cal"] = cv["p_new"]
            print("  [WARN] p_for_cal missing -- using p_new")
        else:
            print("ERROR: No probability column found")
            return 1

    missing = [f for f in FEATURES if f not in cv.columns]
    if missing:
        print(f"ERROR: {len(missing)} features missing from cache: {missing}")
        print("  Rebuild: python tools/build_playoff_resim_cache.py --force")
        return 1

    n_before = len(cv)
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0.0, 1.0, 0, 1])].reset_index(drop=True)
    if len(cv) < n_before:
        print(f"  Dropped {n_before - len(cv):,} rows without hit -> {len(cv):,} remain")

    hit_arr     = cv["hit"].to_numpy(dtype=float)
    pforcal_arr = pd.to_numeric(cv["p_for_cal"], errors="coerce").fillna(0.5).to_numpy(dtype=float)
    date_arr    = cv["game_date"].astype(str).str[:10].values
    dates       = sorted(np.unique(date_arr).tolist())

    n_over   = int((cv["direction"].astype(str).str.upper() == "OVER").sum())
    n_under  = int((cv["direction"].astype(str).str.upper() == "UNDER").sum())
    hit_rate = float(hit_arr.mean())
    b_base   = brier(hit_arr, pforcal_arr)

    print(f"  Total legs: {len(cv):,}  |  OVER: {n_over:,}  UNDER: {n_under:,}")
    print(f"  Overall hit rate: {hit_rate:.3f}")
    print(f"  p_for_cal Brier (baseline): {b_base:.6f}")

    print(f"\n  Feature coverage ({len(FEATURES)} features):")
    for f in FEATURES:
        vals = pd.to_numeric(cv[f], errors="coerce")
        cov  = vals.notna().sum() / len(cv) * 100
        nz   = (vals.fillna(0) != 0).mean() * 100
        print(f"    {f:25s}  cov={cov:5.1f}%  nonzero={nz:5.1f}%  mean={vals.mean():+.4f}")

    X_full = prep_X(cv)

    # ------------------------------------------------------------------
    # 3. LODO
    # ------------------------------------------------------------------
    print(f"\n[3/4] LODO cross-validation ({len(dates)} folds)...")
    print(f"  depth={CAT_PARAMS['depth']}  iterations={CAT_PARAMS['iterations']}  "
          f"lr={CAT_PARAMS['learning_rate']}  early_stop={CAT_PARAMS['early_stopping_rounds']}")
    print("-" * 76)

    fold_results: list[dict] = []
    oof_preds = np.full(len(cv), np.nan)

    for held_date in dates:
        test_mask  = date_arr == held_date
        train_mask = ~test_mask

        y_train_all = hit_arr[train_mask]
        y_test      = hit_arr[test_mask]
        X_train_all = X_full[train_mask].reset_index(drop=True)
        X_test_df   = X_full[test_mask].reset_index(drop=True)

        rng       = np.random.default_rng(42)
        n_tr      = len(X_train_all)
        eval_idx  = rng.choice(n_tr, size=max(1, n_tr // 10), replace=False)
        train_idx = np.setdiff1d(np.arange(n_tr), eval_idx)

        train_pool = make_pool(X_train_all.iloc[train_idx], y_train_all[train_idx])
        eval_pool  = make_pool(X_train_all.iloc[eval_idx],  y_train_all[eval_idx])
        test_pool  = make_pool(X_test_df)

        model = CatBoostClassifier(**CAT_PARAMS)
        model.fit(train_pool, eval_set=eval_pool)

        preds: np.ndarray = model.predict_proba(test_pool)[:, 1]
        oof_preds[test_mask] = preds

        b_before = brier(y_test, pforcal_arr[test_mask])
        b_after  = brier(y_test, preds)
        best_iter = int(model.get_best_iteration() or CAT_PARAMS["iterations"])

        model_path = MODEL_OUT / f"catboost_fold_{held_date}.cbm"
        model.save_model(str(model_path))

        fold_results.append({
            "date":         held_date,
            "n_test":       int(test_mask.sum()),
            "n_train":      int(train_mask.sum()),
            "best_iter":    best_iter,
            "brier_before": round(b_before, 6),
            "brier_after":  round(b_after,  6),
            "delta":        round(b_after - b_before, 6),
            "model_path":   str(model_path),
        })

        sign = "+" if b_after < b_before else "-"
        print(f"  [{sign}] {held_date}  n={test_mask.sum():>4,}  "
              f"before={b_before:.6f}  after={b_after:.6f}  "
              f"delta={b_after - b_before:+.6f}  iter={best_iter}")

    # ------------------------------------------------------------------
    # OOF aggregate
    # ------------------------------------------------------------------
    valid        = ~np.isnan(oof_preds)
    b_oof_before = brier(hit_arr[valid], pforcal_arr[valid])
    b_oof_after  = brier(hit_arr[valid], oof_preds[valid])
    delta_mb     = (b_oof_after - b_oof_before) * 1000
    improved     = b_oof_after < b_oof_before
    verdict      = "PROMOTE" if improved else "REJECT"

    print()
    print("=== LODO Summary ===")
    print(f"  OOF Brier (p_for_cal baseline): {b_oof_before:.6f}")
    print(f"  OOF Brier (CatBoost LODO):      {b_oof_after:.6f}  ({delta_mb:+.2f} mB)")
    print(f"  Verdict: {verdict}")
    print()
    print(f"  {'Date':<12} {'N':>5}  {'Before':>10}  {'After':>10}  {'Delta':>10}  {'Iter':>5}")
    for r in fold_results:
        print(f"  {r['date']:<12} {r['n_test']:>5,}  {r['brier_before']:>10.6f}  "
              f"{r['brier_after']:>10.6f}  {r['delta']:>+10.6f}  {r['best_iter']:>5}")

    # ------------------------------------------------------------------
    # 4. Full-corpus model
    # ------------------------------------------------------------------
    print("\n[4/4] Training full-corpus model...")
    full_params = {k: v for k, v in CAT_PARAMS.items()
                   if k not in ("early_stopping_rounds", "use_best_model")}
    full_params["verbose"] = 200
    full_pool  = make_pool(X_full, hit_arr)
    full_model = CatBoostClassifier(**full_params)
    full_model.fit(full_pool)
    full_model_path = MODEL_OUT / "catboost_full_corpus.cbm"
    full_model.save_model(str(full_model_path))

    importances: dict[str, float] = dict(
        zip(FEATURES, full_model.get_feature_importance().tolist())
    )
    top_feats = sorted(importances.items(), key=lambda x: x[1], reverse=True)
    print(f"\n  {'Feature':<30}  {'Importance':>10}")
    for feat, imp in top_feats:
        if imp > 0.01:
            print(f"  {feat:<30}  {imp:>10.2f}")

    # ------------------------------------------------------------------
    # Save meta + manifest
    # ------------------------------------------------------------------
    meta = {
        "version":            "catboost_playoff_v2",
        "trained_at":         run_ts,
        "cache_path":         str(CACHE_PATH),
        "source_col":         "p_for_cal",
        "n_dates":            len(dates),
        "dates":              dates,
        "n_legs_total":       int(len(cv)),
        "n_over":             n_over,
        "n_under":            n_under,
        "hit_rate":           round(hit_rate, 4),
        "oof_brier_before":   round(b_oof_before, 6),
        "oof_brier_after":    round(b_oof_after,  6),
        "oof_brier_delta":    round(b_oof_after - b_oof_before, 6),
        "oof_brier_delta_mB": round(delta_mb, 2),
        "verdict":            verdict,
        "features":           FEATURES,
        "cat_features":       CAT_FEATURES,
        "hyperparams":        CAT_PARAMS,
        "fold_results":       fold_results,
        "model_dir":          str(MODEL_OUT),
        "full_model_path":    str(full_model_path),
        "feature_importance": importances,
    }
    META_PATH.write_text(json.dumps(meta, indent=2))

    manifest = {
        "manifest_type":  "catboost_playoff_lodo_v2",
        "created_at":     run_ts,
        "verdict":        verdict,
        "summary": {
            "n_dates":            len(dates),
            "n_legs_total":       int(len(cv)),
            "oof_brier_baseline": round(b_oof_before, 6),
            "oof_brier_catboost": round(b_oof_after,  6),
            "oof_brier_delta_mB": round(delta_mb, 2),
        },
        "config": {
            "cache":        str(CACHE_PATH.name),
            "features":     FEATURES,
            "cat_features": CAT_FEATURES,
            "hyperparams":  CAT_PARAMS,
        },
        "fold_results": fold_results,
        "feature_importance_top10": [
            {"feature": f, "importance": round(i, 2)} for f, i in top_feats[:10]
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))

    print(f"\nMeta     -> {META_PATH}")
    print(f"Manifest -> {MANIFEST_PATH}")
    print(f"\nVerdict: {verdict}  ({delta_mb:+.2f} mB vs p_for_cal baseline)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--promote", action="store_true")
    args = ap.parse_args()
    sys.exit(main(promote=args.promote))
