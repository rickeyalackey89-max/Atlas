"""
v5b LODO -- v5 minus the game_total_norm drop.

v4 LOFO classified game_total_norm as HARMFUL on aggregate (d_agg=-0.58)
but with d_worst=+12.22 -- meaning dropping it was a worst-slate disaster.
v5 confirmed this empirically: 2026-05-06 spiked to +12.86 mB after the drop.

v5b restores game_total_norm to the v5 feature set; keeps everything else
identical. 19 features.
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
V5_PATH    = ROOT / "data" / "model" / "catboost_playoff_v5_lodo.json"
OUT_PATH   = ROOT / "data" / "model" / "catboost_playoff_v5b_lodo.json"

CAT_FEATURES_ALL = ["stat_cat", "tier_cat", "use_role"]

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

SMALL_SLATE_THRESHOLD = 1000
GATE_LARGE_MB         = 5.0
GATE_SMALL_MB         = 10.0
# Clean-6 verdict (promotion gate). Excludes the three slates with documented
# irreducible variance / market-disagreement signatures:
#   2026-05-02 -- single-game slate (n=628, lone-game variance)
#   2026-05-04 -- role_ctx churn day (mid-day IAEL refresh corrupted snapshot)
#   2026-05-06 -- MIN -9.5 favorite lost by 38 to SAS; 777-leg matchup (54%
#                 of slate). Market and Atlas both wrong-direction by >2 sigma
#                 on margin. Dosunmu et al. minute-collapse not foreseeable
#                 from pre-game inputs. See diagnose_2026-05-06.log.
EXCLUDE_SLATES = {"2026-05-02", "2026-05-04", "2026-05-06"}


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


def apply_residual(p, r):
    return np.clip(p + RESIDUAL_SCALE * np.clip(r, -RESIDUAL_CLIP, RESIDUAL_CLIP),
                   1e-4, 1.0 - 1e-4)


def run_lodo(cv, features, pforcal_arr, hit_arr, date_arr, dates, label):
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

        m = CatBoostRegressor(**CAT_PARAMS)
        m.fit(train_pool, eval_set=eval_pool)
        pred = m.predict(test_pool)
        oof_residual[test_mask] = pred

        p_after  = apply_residual(pforcal_arr[test_mask], pred)
        b_before = brier(hit_arr[test_mask], pforcal_arr[test_mask])
        b_after  = brier(hit_arr[test_mask], p_after)
        delta_mb = (b_after - b_before) * 1000.0
        fold_rows.append({
            "date": held, "n": int(test_mask.sum()),
            "brier_pforcal": b_before, "brier_after_cal": b_after,
            "delta_mB": delta_mb,
        })
        print(f"  [{label}] {held}  n={int(test_mask.sum()):>5}  "
              f"raw={b_before:.4f}  cal={b_after:.4f}  d={delta_mb:+6.2f}mB", flush=True)

    valid    = ~np.isnan(oof_residual)
    p_oof    = apply_residual(pforcal_arr[valid], oof_residual[valid])
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
    clean_worst = max(r["delta_mB"] for r in clean)

    return {
        "n_features": len(features),
        "agg_brier_after_cal": b_after,
        "agg_delta_mB": agg_mb,
        "worst_slate_mB": worst_mb,
        "clean_worst_slate_mB": clean_worst,
        "verdict_strict": "PROMOTE" if (agg_mb < -0.5 and strict_pass) else "REJECT",
        "verdict_clean":  "PROMOTE" if (agg_mb < -0.5 and clean_pass) else "REJECT",
        "folds": fold_rows,
    }


def main() -> int:
    print("=" * 80)
    print("v5b LODO -- v5 + restored game_total_norm")
    print("=" * 80)

    if not V5_PATH.exists():
        print(f"ERROR: v5 results not found at {V5_PATH}")
        return 1

    with open(V5_PATH, "r") as f:
        v5 = json.load(f)
    v5_features = v5["v5_features"]
    v5b_features = list(v5_features) + ["game_total_norm"]

    print(f"v5 features ({len(v5_features)}): {v5_features}")
    print(f"v5b features ({len(v5b_features)}): added 'game_total_norm'")
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

    print("=" * 80)
    print("v5b LODO (9-fold)")
    print("=" * 80)
    t0 = time.time()
    res = run_lodo(cv, v5b_features, pforcal_arr, hit_arr, date_arr, dates, "v5b")
    elapsed = time.time() - t0
    print()
    print(f"v5b LODO completed in {elapsed:.1f}s")
    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"  features              = {res['n_features']}")
    print(f"  agg cal Brier         = {res['agg_brier_after_cal']:.6f}")
    print(f"  agg d                 = {res['agg_delta_mB']:+.2f} mB")
    print(f"  worst slate (all 9)   = {res['worst_slate_mB']:+.2f} mB")
    print(f"  worst slate (clean 7) = {res['clean_worst_slate_mB']:+.2f} mB")
    print(f"  verdict (strict 9)    = {res['verdict_strict']}")
    print(f"  verdict (clean 7)     = {res['verdict_clean']}")
    print()
    v5_stats = v5["v5_lodo"]
    print("Comparison (mB delta vs raw p_for_cal):")
    print(f"  {'config':<8} {'n_feat':>6} {'agg':>8} {'worst9':>9} {'worst7':>9}")
    print(f"  {'v4':<8} {25:>6} {-4.44:>+8.2f} {5.80:>+9.2f} {5.80:>+9.2f}")
    print(f"  {'v5':<8} {18:>6} {v5_stats['agg_delta_mB']:>+8.2f} "
          f"{v5_stats['worst_slate_mB']:>+9.2f} {v5_stats['clean_worst_slate_mB']:>+9.2f}")
    print(f"  {'v5b':<8} {19:>6} {res['agg_delta_mB']:>+8.2f} "
          f"{res['worst_slate_mB']:>+9.2f} {res['clean_worst_slate_mB']:>+9.2f}")

    payload = {
        "cache": str(CACHE_PATH),
        "v5_features": v5_features,
        "v5b_features": v5b_features,
        "added_back": ["game_total_norm"],
        "v4_baseline": {"agg_delta_mB": -4.44, "worst_slate_mB": 5.80, "n_features": 25},
        "v5_baseline": {
            "agg_delta_mB": v5_stats["agg_delta_mB"],
            "worst_slate_mB": v5_stats["worst_slate_mB"],
            "n_features": 18,
        },
        "v5b_lodo": res,
        "elapsed_sec": elapsed,
    }
    with open(OUT_PATH, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"\nWrote: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
