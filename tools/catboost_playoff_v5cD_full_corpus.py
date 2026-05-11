"""Train final v5cD full-corpus CatBoost residual regressor.

Trains a SINGLE model on all 10 playoff dates (no holdout) using the v5cD
config: 19 features, iter=600, depth=5, lr=0.075. Saves the model file used
by runtime inference.

Outputs:
    data/model/catboost_playoff/catboost_v5cD_full_corpus.cbm
    data/model/catboost_playoff/catboost_v5cD_full_corpus.meta.json
"""
from __future__ import annotations

import json
import pathlib
import pickle
import time
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool  # type: ignore[import-untyped]

warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).resolve().parents[1]

CACHE_PATH    = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
V5B_PATH      = ROOT / "data" / "model" / "catboost_playoff_v5b_lodo.json"
OUT_DIR       = ROOT / "data" / "model" / "catboost_playoff"
MODEL_OUT     = OUT_DIR / "catboost_v5cD_full_corpus.cbm"
META_OUT      = OUT_DIR / "catboost_v5cD_full_corpus.meta.json"

CAT_FEATURES_ALL = ["stat_cat", "tier_cat", "use_role"]

# v5cD architecture constants (must match runtime applier exactly)
RESIDUAL_CLIP  = 0.20
RESIDUAL_SCALE = 0.50
P_LO, P_HI     = 0.03, 0.97

PARAMS = dict(
    iterations=600,
    depth=5,
    learning_rate=0.075,
    l2_leaf_reg=6.0,
    min_data_in_leaf=50,
    loss_function="RMSE",
    eval_metric="RMSE",
    random_seed=42,
    verbose=100,  # show progress every 100 iters
)


def brier(y, p):
    return float(np.mean((p - y) ** 2))


def prep_X(df, features):
    cat_in = [c for c in CAT_FEATURES_ALL if c in features]
    X = df[features].copy()
    for col in features:
        if col in cat_in:
            X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0).astype(int).astype(str)
        else:
            X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0.0).astype(float)
    return X, cat_in


def apply_residual(p, r):
    return np.clip(p + RESIDUAL_SCALE * np.clip(r, -RESIDUAL_CLIP, RESIDUAL_CLIP),
                   P_LO, P_HI)


def main() -> int:
    print("=" * 80, flush=True)
    print("v5cD FULL-CORPUS Trainer (residual regressor, 19 features)", flush=True)
    print("=" * 80, flush=True)

    # Read v5b features (the canonical 19-feature set)
    with open(V5B_PATH, "r") as f:
        v5b = json.load(f)
    features = v5b["v5b_features"]
    print(f"features ({len(features)}): {features}", flush=True)
    print(flush=True)

    # Load cache
    print("Loading cache...", flush=True)
    with open(CACHE_PATH, "rb") as f:
        cache = pickle.load(f)
    cv = cache["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)
    cv["p_for_cal"] = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1)
    cv["use_role"] = (pd.to_numeric(cv["role_ctx_outs_used"], errors="coerce")
                        .fillna(0).astype(int) > 0).astype(int)

    hit      = cv["hit"].astype(float).to_numpy()
    p_in     = cv["p_for_cal"].to_numpy()
    dates    = sorted(cv["game_date"].astype(str).str[:10].unique().tolist())
    print(f"  {len(cv):,} legs | {len(dates)} dates", flush=True)
    print(f"  Date range: {dates[0]} -> {dates[-1]}", flush=True)
    print(flush=True)

    # Prepare features
    residual_tgt = hit - p_in
    X, cat_in = prep_X(cv, features)
    print(f"  Features: {len(features)} | Categoricals: {cat_in}", flush=True)
    print(f"  Residual target: mean={residual_tgt.mean():+.4f}  "
          f"std={residual_tgt.std():.4f}  "
          f"range=[{residual_tgt.min():.4f}, {residual_tgt.max():.4f}]", flush=True)
    print(flush=True)

    # Baseline (no calibration)
    b_baseline = brier(hit, p_in)
    print(f"Baseline Brier (p_for_cal alone): {b_baseline:.6f}", flush=True)
    print(flush=True)

    # Train on full corpus
    print(f"Training full-corpus model (no holdout)...", flush=True)
    print(f"  iter={PARAMS['iterations']}  depth={PARAMS['depth']}  "
          f"lr={PARAMS['learning_rate']}  l2={PARAMS['l2_leaf_reg']}", flush=True)
    print("-" * 80, flush=True)

    t0 = time.time()
    pool = Pool(X, label=residual_tgt, cat_features=cat_in)
    model = CatBoostRegressor(**PARAMS)
    model.fit(pool)
    elapsed = time.time() - t0

    print("-" * 80, flush=True)
    print(f"Training complete in {elapsed:.1f}s  ({model.tree_count_} trees)", flush=True)
    print(flush=True)

    # In-sample sanity check (NOT a generalization metric)
    pred_resid = model.predict(pool)
    p_after = apply_residual(p_in, pred_resid)
    b_after = brier(hit, p_after)
    print(f"In-sample Brier after calibration: {b_after:.6f}  "
          f"({(b_after - b_baseline) * 1000:+.2f} mB vs baseline)", flush=True)
    print(f"  (LODO is the real generalization metric -- this is just a fit check)", flush=True)

    # Feature importance
    importances = dict(zip(features, model.get_feature_importance().tolist()))
    print(f"\nFeature importances:", flush=True)
    for f, imp in sorted(importances.items(), key=lambda x: x[1], reverse=True):
        print(f"  {f:<25s}  {imp:>8.2f}", flush=True)

    # Save model
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(str(MODEL_OUT))
    print(f"\nSaved model: {MODEL_OUT}", flush=True)

    # Save meta — runtime applier reads this
    meta = {
        "version": "catboost_playoff_v5cD",
        "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model_kind": "CatBoostRegressor",
        "target": "hit - p_for_cal",
        "applier": "p + RESIDUAL_SCALE * clip(residual, -RESIDUAL_CLIP, RESIDUAL_CLIP)",
        "residual_scale": RESIDUAL_SCALE,
        "residual_clip":  RESIDUAL_CLIP,
        "p_lo": P_LO,
        "p_hi": P_HI,
        "features":     features,
        "cat_features": cat_in,
        "n_features":   len(features),
        "params":       {k: (str(v) if not isinstance(v, (int, float, str, bool)) else v)
                         for k, v in PARAMS.items()},
        "cache_path":   str(CACHE_PATH),
        "n_legs":       int(len(cv)),
        "n_dates":      len(dates),
        "dates":        dates,
        "baseline_brier": round(b_baseline, 6),
        "in_sample_brier_after": round(b_after, 6),
        "feature_importances": importances,
        "tree_count": int(model.tree_count_),
        "elapsed_sec": round(elapsed, 1),
    }
    with open(META_OUT, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Saved meta:  {META_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
