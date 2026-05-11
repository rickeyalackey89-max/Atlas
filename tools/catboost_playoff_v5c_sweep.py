"""
v5c hyperparam sweep on the v5b 19-feature set.

Per user direction (revised after iter=800 was killed):
  - iter: held at 500 (v5b baseline)
  - learning_rate: 0.05 -> 0.075
  - residual scale: bump up. Sweep {0.50, 0.60, 0.70} -- 0.50 acts as control
    (tests pure lr lift) and 0.60/0.70 test residual strength.

Architectural fixtures held constant (v5b architecture):
  - p_for_cal := p_adj (engine fork bypassed in cache)
  - use_role categorical (0/1) included
  - 19 features from v5b
  - Clean-6 verdict gate (excludes 2026-05-02, 2026-05-04, 2026-05-06)

Output: data/model/catboost_playoff_v5c_sweep.json
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
V5B_PATH   = ROOT / "data" / "model" / "catboost_playoff_v5b_lodo.json"
OUT_PATH   = ROOT / "data" / "model" / "catboost_playoff_v5c_sweep.json"

CAT_FEATURES_ALL = ["stat_cat", "tier_cat", "use_role"]

SMALL_SLATE_THRESHOLD = 1000
GATE_LARGE_MB         = 5.0
GATE_SMALL_MB         = 10.0
EXCLUDE_SLATES        = {"2026-05-02", "2026-05-04", "2026-05-06"}  # clean-6

RESIDUAL_CLIP = 0.20

# Sweep grid (3 configs)
SWEEP = [
    {"name": "v5c-A_iter500_lr0075_scale050", "iterations": 500,
     "learning_rate": 0.075, "residual_scale": 0.50},
    {"name": "v5c-B_iter500_lr0075_scale060", "iterations": 500,
     "learning_rate": 0.075, "residual_scale": 0.60},
    {"name": "v5c-C_iter500_lr0075_scale070", "iterations": 500,
     "learning_rate": 0.075, "residual_scale": 0.70},
]

V5B_BASELINE = dict(iterations=500, learning_rate=0.05, residual_scale=0.50)


def base_params(iters: int, lr: float) -> dict:
    return dict(
        iterations=iters,
        depth=5,
        learning_rate=lr,
        l2_leaf_reg=6.0,
        min_data_in_leaf=50,
        loss_function="RMSE",
        eval_metric="RMSE",
        random_seed=42,
        verbose=False,
        early_stopping_rounds=50,
        use_best_model=True,
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


def make_pool(X, y, cat_in):
    if y is not None:
        return Pool(X, label=y, cat_features=cat_in)
    return Pool(X, cat_features=cat_in)


def apply_residual(p, r, scale: float, clip: float):
    return np.clip(p + scale * np.clip(r, -clip, clip),
                   1e-4, 1.0 - 1e-4)


def run_lodo(cv, features, pforcal_arr, hit_arr, date_arr, dates,
             label, params, residual_scale):
    residual_tgt = hit_arr - pforcal_arr
    X_full, cat_in = prep_X(cv, features)
    oof_residual = np.full(len(cv), np.nan)
    fold_rows = []

    for held in dates:
        test_mask  = date_arr == held
        train_mask = ~test_mask
        y_tr_all   = residual_tgt[train_mask]
        X_tr_all   = X_full[train_mask].reset_index(drop=True)
        X_te       = X_full[test_mask].reset_index(drop=True)

        rng       = np.random.default_rng(42)
        n_tr      = len(X_tr_all)
        eval_idx  = rng.choice(n_tr, size=max(1, n_tr // 10), replace=False)
        train_idx = np.setdiff1d(np.arange(n_tr), eval_idx)

        train_pool = make_pool(X_tr_all.iloc[train_idx], y_tr_all[train_idx], cat_in)
        eval_pool  = make_pool(X_tr_all.iloc[eval_idx],  y_tr_all[eval_idx],  cat_in)
        test_pool  = make_pool(X_te, None, cat_in)

        m = CatBoostRegressor(**params)
        m.fit(train_pool, eval_set=eval_pool)
        pred = m.predict(test_pool)
        oof_residual[test_mask] = pred

        p_after  = apply_residual(pforcal_arr[test_mask], pred,
                                   residual_scale, RESIDUAL_CLIP)
        b_before = brier(hit_arr[test_mask], pforcal_arr[test_mask])
        b_after  = brier(hit_arr[test_mask], p_after)
        delta_mb = (b_after - b_before) * 1000.0
        fold_rows.append({
            "date": held, "n": int(test_mask.sum()),
            "brier_pforcal": b_before, "brier_after_cal": b_after,
            "delta_mB": delta_mb,
        })
        print(f"  [{label}] {held}  n={int(test_mask.sum()):>5}  "
              f"raw={b_before:.4f}  cal={b_after:.4f}  d={delta_mb:+6.2f}mB",
              flush=True)

    valid    = ~np.isnan(oof_residual)
    p_oof    = apply_residual(pforcal_arr[valid], oof_residual[valid],
                               residual_scale, RESIDUAL_CLIP)
    b_before = brier(hit_arr[valid], pforcal_arr[valid])
    b_after  = brier(hit_arr[valid], p_oof)
    agg_mb   = (b_after - b_before) * 1000.0
    worst_mb = max(r["delta_mB"] for r in fold_rows)

    strict_pass = all(
        (r["delta_mB"] <= GATE_LARGE_MB if r["n"] >= SMALL_SLATE_THRESHOLD
         else r["delta_mB"] <= GATE_SMALL_MB)
        for r in fold_rows
    )
    clean = [r for r in fold_rows if r["date"] not in EXCLUDE_SLATES]
    clean_pass = all(
        (r["delta_mB"] <= GATE_LARGE_MB if r["n"] >= SMALL_SLATE_THRESHOLD
         else r["delta_mB"] <= GATE_SMALL_MB)
        for r in clean
    )
    clean_worst = max(r["delta_mB"] for r in clean) if clean else float("nan")

    # Active-corpus aggregate (clean only)
    active_mask = np.isin(date_arr, list(set(dates) - EXCLUDE_SLATES))
    valid_clean = valid & active_mask
    if valid_clean.any():
        b_clean_pre  = brier(hit_arr[valid_clean], pforcal_arr[valid_clean])
        # OOF residual already computed for valid; restrict
        idx = np.where(valid_clean)[0]
        # Align oof_residual values for valid_clean rows
        r_clean = oof_residual[valid_clean]
        p_clean_after = apply_residual(pforcal_arr[valid_clean], r_clean,
                                        residual_scale, RESIDUAL_CLIP)
        b_clean_post = brier(hit_arr[valid_clean], p_clean_after)
        clean_agg_mb = (b_clean_post - b_clean_pre) * 1000.0
    else:
        clean_agg_mb = float("nan")

    return {
        "n_features": len(features),
        "agg_brier_after_cal": b_after,
        "agg_delta_mB": agg_mb,
        "clean_agg_delta_mB": clean_agg_mb,
        "worst_slate_mB": worst_mb,
        "clean_worst_slate_mB": clean_worst,
        "verdict_strict": "PROMOTE" if (agg_mb < -0.5 and strict_pass) else "REJECT",
        "verdict_clean":  "PROMOTE" if (clean_agg_mb < -0.5 and clean_pass) else "REJECT",
        "folds": fold_rows,
    }


def main() -> int:
    print("=" * 80)
    print("v5c hyperparam sweep -- 19-feature v5b architecture, clean-6 gate")
    print("=" * 80)

    if not V5B_PATH.exists():
        print(f"ERROR: v5b results not found at {V5B_PATH}")
        return 1

    with open(V5B_PATH, "r") as f:
        v5b = json.load(f)
    features = v5b["v5b_features"]
    print(f"v5b features ({len(features)}): {features}")
    print(f"clean-6 excludes: {sorted(EXCLUDE_SLATES)}")
    print()
    print("Sweep configs:")
    for cfg in SWEEP:
        print(f"  {cfg['name']:<35}  iter={cfg['iterations']}  "
              f"lr={cfg['learning_rate']}  scale={cfg['residual_scale']}")
    print()

    print("Loading cache...")
    with open(CACHE_PATH, "rb") as f:
        cache = pickle.load(f)
    cv = cache["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)

    cv["p_for_cal"] = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1)
    cv["use_role"] = (pd.to_numeric(cv["role_ctx_outs_used"], errors="coerce")
                        .fillna(0).astype(int) > 0).astype(int)

    hit_arr     = cv["hit"].astype(float).to_numpy()
    pforcal_arr = cv["p_for_cal"].to_numpy()
    date_arr    = cv["game_date"].astype(str).str[:10].values
    dates       = sorted(np.unique(date_arr).tolist())

    print(f"  {len(cv):,} legs | {len(dates)} dates")
    print()

    results = {}
    t_start = time.time()
    for cfg in SWEEP:
        print("=" * 80)
        print(f"{cfg['name']}")
        print("=" * 80)
        params = base_params(cfg["iterations"], cfg["learning_rate"])
        t0 = time.time()
        r = run_lodo(cv, features, pforcal_arr, hit_arr, date_arr, dates,
                     cfg["name"], params, cfg["residual_scale"])
        r["elapsed_sec"] = time.time() - t0
        r["config"] = cfg
        results[cfg["name"]] = r
        print()
        print(f"  agg (all 9)   = {r['agg_delta_mB']:+.2f} mB")
        print(f"  agg (clean-6) = {r['clean_agg_delta_mB']:+.2f} mB")
        print(f"  worst (all 9) = {r['worst_slate_mB']:+.2f} mB")
        print(f"  worst clean-6 = {r['clean_worst_slate_mB']:+.2f} mB")
        print(f"  verdict strict (9) = {r['verdict_strict']}")
        print(f"  verdict clean (6)  = {r['verdict_clean']}")
        print()

    elapsed = time.time() - t_start
    print("=" * 80)
    print("SWEEP COMPLETE")
    print("=" * 80)
    print(f"{'config':<40} {'agg9':>8} {'agg6':>8} {'w9':>8} {'w6':>8} {'strict':>8} {'clean':>8}")
    # baseline ref from v5b
    v5b_lodo = v5b["v5b_lodo"]
    # v5b was computed with clean-7. Recompute clean-6 for comparison from folds.
    folds = v5b_lodo["folds"]
    clean6 = [r for r in folds if r["date"] not in EXCLUDE_SLATES]
    v5b_clean6_worst = max(r["delta_mB"] for r in clean6) if clean6 else float("nan")
    print(f"{'v5b (iter500/lr0.05/scale0.50)':<40} "
          f"{v5b_lodo['agg_delta_mB']:>+8.2f} "
          f"{'-':>8} "
          f"{v5b_lodo['worst_slate_mB']:>+8.2f} "
          f"{v5b_clean6_worst:>+8.2f} "
          f"{'REJECT':>8} {'?':>8}  (baseline)")
    for name, r in results.items():
        print(f"{name:<40} "
              f"{r['agg_delta_mB']:>+8.2f} "
              f"{r['clean_agg_delta_mB']:>+8.2f} "
              f"{r['worst_slate_mB']:>+8.2f} "
              f"{r['clean_worst_slate_mB']:>+8.2f} "
              f"{r['verdict_strict']:>8} "
              f"{r['verdict_clean']:>8}")
    print()
    print(f"Total elapsed: {elapsed:.1f}s")

    payload = {
        "cache": str(CACHE_PATH),
        "features": features,
        "exclude_slates_clean6": sorted(EXCLUDE_SLATES),
        "v5b_baseline": V5B_BASELINE,
        "v5b_baseline_metrics": {
            "agg_delta_mB": v5b_lodo["agg_delta_mB"],
            "worst_slate_mB": v5b_lodo["worst_slate_mB"],
            "clean6_worst_mB": v5b_clean6_worst,
        },
        "sweep": SWEEP,
        "results": results,
        "elapsed_sec": elapsed,
    }
    with open(OUT_PATH, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"\nWrote: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
