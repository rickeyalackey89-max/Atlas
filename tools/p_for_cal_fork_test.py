"""
p_for_cal Fork Test
====================
Tests three configurations of the p_for_cal source against the v3 24-feature
CatBoost residual calibrator under identical 9-fold LODO:

  BASELINE:  current engine fork
             p_for_cal = where(role_ctx_outs_used > 0, p_role, p_adj)
             features = 24 v3 base
  OPT_A:     drop the fork
             p_for_cal := p_adj for all legs
             features = 24 v3 base
  OPT_C:     drop the fork + surface use_role as a feature
             p_for_cal := p_adj for all legs
             features = 24 v3 base + ["use_role"]
             (use_role becomes a categorical: 0/1 string)

Hyperparams are pinned to the LOFO/addback values for comparability:
  iter=500  depth=5  lr=0.05  scale=0.5  clip=0.20

Reports for each configuration:
  - aggregate Brier delta vs raw p_for_cal of that configuration
  - worst-slate delta (per-slate max regression)
  - per-slate Brier on raw p_for_cal AND post-calibration

The verdict picks itself from the worst-slate non-regression rule.

Output: data/model/p_for_cal_fork_test.json
        data/model/p_for_cal_fork_test_run.log (tee from caller)
"""
from __future__ import annotations

import json
import pathlib
import pickle
import warnings

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool  # type: ignore[import-untyped]

warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).resolve().parents[1]

CACHE_PATH = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
OUT_PATH   = ROOT / "data" / "model" / "p_for_cal_fork_test.json"

# v3 24-feature base
BASELINE_FEATURES = [
    "p_for_cal", "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
    "is_assists", "is_threes", "thin_flag", "line_norm", "is_home_feat",
    "min_sensitivity", "game_total_norm", "is_b2b", "margin", "stat_cat",
    "tier_cat", "line_dist", "tail_risk", "line_tightness", "margin_x_under",
    "q_blowout", "rate_cv", "q_x_under",
]

# stat_cat and tier_cat are categorical; use_role added in OPT_C is also categorical
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


def run_lodo(cv: pd.DataFrame, features: list[str], pforcal_arr: np.ndarray,
             hit_arr: np.ndarray, date_arr: np.ndarray, dates: list[str], label: str):
    """Run 9-fold LODO. NOTE: pforcal_arr is the configuration-specific p_for_cal
    AND it is also expected to be in the cv frame as column 'p_for_cal'."""
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
            "date": held,
            "n": int(test_mask.sum()),
            "brier_pforcal": b_before,
            "brier_after_cal": b_after,
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
    n_regress = sum(1 for r in fold_rows if r["delta_mB"] > 0.5)

    SMALL_SLATE_THRESHOLD = 1000
    per_slate_pass = all(
        (r["delta_mB"] <= 5.0 if r["n"] >= SMALL_SLATE_THRESHOLD else r["delta_mB"] <= 10.0)
        for r in fold_rows
    )
    verdict = "PROMOTE" if (agg_mb < -0.5 and per_slate_pass) else "REJECT"

    return {
        "label": label,
        "n_features": len(features),
        "agg_brier_pforcal": b_before,
        "agg_brier_after_cal": b_after,
        "agg_delta_mB": agg_mb,
        "worst_slate_mB": worst_mb,
        "n_slates_regressing": n_regress,
        "per_slate_pass": per_slate_pass,
        "verdict": verdict,
        "folds": fold_rows,
    }


def main() -> int:
    print("=== p_for_cal Fork Test (BASELINE / OPT_A / OPT_C) ===")
    print(f"Cache:    {CACHE_PATH}")
    print(f"Settings: iter={CAT_PARAMS['iterations']}  depth={CAT_PARAMS['depth']}  "
          f"lr={CAT_PARAMS['learning_rate']}  scale={RESIDUAL_SCALE}  clip={RESIDUAL_CLIP}")
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

    for col in ["p_for_cal", "p_adj", "p_role", "role_ctx_outs_used"]:
        if col not in cv.columns:
            print(f"ERROR: column missing: {col}")
            return 1

    cv["p_for_cal_baseline"] = pd.to_numeric(cv["p_for_cal"], errors="coerce").fillna(0.5).clip(0, 1)
    cv["p_for_cal_padj"]     = pd.to_numeric(cv["p_adj"],     errors="coerce").fillna(0.5).clip(0, 1)
    cv["use_role"]           = (pd.to_numeric(cv["role_ctx_outs_used"], errors="coerce")
                                  .fillna(0).astype(int) > 0).astype(int)

    hit_arr  = cv["hit"].astype(float).to_numpy()
    date_arr = cv["game_date"].astype(str).str[:10].values
    dates    = sorted(np.unique(date_arr).tolist())

    n_use_role = int(cv["use_role"].sum())
    print(f"  {len(cv):,} legs | {len(dates)} dates")
    print(f"  use_role=1 legs: {n_use_role:,} ({100*n_use_role/len(cv):.1f}%)")
    print(f"  Brier(p_for_cal current fork) = {brier(hit_arr, cv['p_for_cal_baseline'].to_numpy()):.6f}")
    print(f"  Brier(p_adj as p_for_cal)     = {brier(hit_arr, cv['p_for_cal_padj'].to_numpy()):.6f}")
    print()

    # --- BASELINE: current fork, 24 v3 features ---
    print("[BASELINE] current fork (p_for_cal as in cache), 24 features")
    cv_b = cv.copy()
    cv_b["p_for_cal"] = cv_b["p_for_cal_baseline"]
    res_baseline = run_lodo(
        cv=cv_b,
        features=BASELINE_FEATURES,
        pforcal_arr=cv_b["p_for_cal"].to_numpy(),
        hit_arr=hit_arr,
        date_arr=date_arr,
        dates=dates,
        label="BASE",
    )
    print(f"  -> AGG d={res_baseline['agg_delta_mB']:+.2f}mB  "
          f"worst={res_baseline['worst_slate_mB']:+.2f}mB  "
          f"verdict={res_baseline['verdict']}")
    print()

    # --- OPT_A: p_for_cal := p_adj, 24 v3 features ---
    print("[OPT_A] p_for_cal := p_adj for all legs, 24 features")
    cv_a = cv.copy()
    cv_a["p_for_cal"] = cv_a["p_for_cal_padj"]
    res_a = run_lodo(
        cv=cv_a,
        features=BASELINE_FEATURES,
        pforcal_arr=cv_a["p_for_cal"].to_numpy(),
        hit_arr=hit_arr,
        date_arr=date_arr,
        dates=dates,
        label="OPT_A",
    )
    print(f"  -> AGG d={res_a['agg_delta_mB']:+.2f}mB  "
          f"worst={res_a['worst_slate_mB']:+.2f}mB  "
          f"verdict={res_a['verdict']}")
    print()

    # --- OPT_C: p_for_cal := p_adj + use_role categorical, 25 features ---
    print("[OPT_C] p_for_cal := p_adj + use_role flag, 25 features")
    cv_c = cv.copy()
    cv_c["p_for_cal"] = cv_c["p_for_cal_padj"]
    res_c = run_lodo(
        cv=cv_c,
        features=BASELINE_FEATURES + ["use_role"],
        pforcal_arr=cv_c["p_for_cal"].to_numpy(),
        hit_arr=hit_arr,
        date_arr=date_arr,
        dates=dates,
        label="OPT_C",
    )
    print(f"  -> AGG d={res_c['agg_delta_mB']:+.2f}mB  "
          f"worst={res_c['worst_slate_mB']:+.2f}mB  "
          f"verdict={res_c['verdict']}")
    print()

    # --- Comparison summary ---
    print("=" * 80)
    print("HEADLINE COMPARISON")
    print("=" * 80)
    print()
    print("Raw p_for_cal Brier (no calibrator):")
    b_raw_base = brier(hit_arr, cv["p_for_cal_baseline"].to_numpy())
    b_raw_padj = brier(hit_arr, cv["p_for_cal_padj"].to_numpy())
    print(f"  BASELINE (fork)        = {b_raw_base:.6f}")
    print(f"  OPT_A / OPT_C (p_adj)  = {b_raw_padj:.6f}")
    print(f"  raw delta              = {(b_raw_padj - b_raw_base)*1000:+.2f} mB (negative is better)")
    print()
    print("Post-calibration Brier and verdict:")
    hdr = ["config", "n_feat", "raw_Brier", "cal_Brier", "agg_d_mB", "worst_d_mB", "n_regress", "verdict"]
    print("  " + "  ".join(f"{h:<11}" for h in hdr))
    for r in [res_baseline, res_a, res_c]:
        cells = [
            r["label"],
            str(r["n_features"]),
            f'{r["agg_brier_pforcal"]:.4f}',
            f'{r["agg_brier_after_cal"]:.4f}',
            f'{r["agg_delta_mB"]:+.2f}',
            f'{r["worst_slate_mB"]:+.2f}',
            str(r["n_slates_regressing"]),
            r["verdict"],
        ]
        print("  " + "  ".join(f"{c:<11}" for c in cells))
    print()
    # Compare A vs BASELINE
    print("OPT_A vs BASELINE:")
    print(f"  agg cal Brier delta   = {(res_a['agg_brier_after_cal'] - res_baseline['agg_brier_after_cal'])*1000:+.2f} mB")
    print(f"  worst-slate diff      = {res_a['worst_slate_mB'] - res_baseline['worst_slate_mB']:+.2f} mB")
    # Compare C vs BASELINE
    print("OPT_C vs BASELINE:")
    print(f"  agg cal Brier delta   = {(res_c['agg_brier_after_cal'] - res_baseline['agg_brier_after_cal'])*1000:+.2f} mB")
    print(f"  worst-slate diff      = {res_c['worst_slate_mB'] - res_baseline['worst_slate_mB']:+.2f} mB")
    # Compare C vs A
    print("OPT_C vs OPT_A:")
    print(f"  agg cal Brier delta   = {(res_c['agg_brier_after_cal'] - res_a['agg_brier_after_cal'])*1000:+.2f} mB")
    print(f"  worst-slate diff      = {res_c['worst_slate_mB'] - res_a['worst_slate_mB']:+.2f} mB")
    print()

    # Per-slate side-by-side
    print("Per-slate post-cal Brier:")
    print(f"  {'date':<12} {'n':>5} | {'BASE':>8} {'OPT_A':>8} {'OPT_C':>8} | "
          f"{'A-BASE':>8} {'C-BASE':>8} {'C-A':>8}")
    by_date = {f["date"]: f for f in res_baseline["folds"]}
    by_date_a = {f["date"]: f for f in res_a["folds"]}
    by_date_c = {f["date"]: f for f in res_c["folds"]}
    for d in dates:
        b = by_date[d]
        a = by_date_a[d]
        c = by_date_c[d]
        d_a = (a["brier_after_cal"] - b["brier_after_cal"]) * 1000
        d_c = (c["brier_after_cal"] - b["brier_after_cal"]) * 1000
        d_ca = (c["brier_after_cal"] - a["brier_after_cal"]) * 1000
        print(f"  {d:<12} {b['n']:>5} | {b['brier_after_cal']:.4f}  {a['brier_after_cal']:.4f}  "
              f"{c['brier_after_cal']:.4f} | {d_a:+8.2f} {d_c:+8.2f} {d_ca:+8.2f}")

    payload = {
        "cache": str(CACHE_PATH),
        "n_legs": int(len(cv)),
        "n_dates": int(len(dates)),
        "n_use_role": n_use_role,
        "raw_brier_baseline": b_raw_base,
        "raw_brier_padj": b_raw_padj,
        "hyperparams": {
            "iterations": CAT_PARAMS["iterations"],
            "depth": CAT_PARAMS["depth"],
            "learning_rate": CAT_PARAMS["learning_rate"],
            "l2_leaf_reg": CAT_PARAMS["l2_leaf_reg"],
            "min_data_in_leaf": CAT_PARAMS["min_data_in_leaf"],
            "residual_clip": RESIDUAL_CLIP,
            "residual_scale": RESIDUAL_SCALE,
        },
        "results": {
            "BASELINE": res_baseline,
            "OPT_A":    res_a,
            "OPT_C":    res_c,
        },
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"\nWrote: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
