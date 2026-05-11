"""
v5c-E: head-to-head LODO test answering the user's core question:
  "Are the v4-flagged HARMFUL features actually harmful, or did the small
  per-fold corpus just fail to learn their signal?"

Identical architecture to v5c-A (the promoted candidate):
  - iter=500, lr=0.075, depth=5, l2=6.0, min_data_in_leaf=50, seed=42
  - residual_scale=0.50, residual_clip=0.20
  - RMSE residual model (target = hit - p_for_cal)
  - Same LODO setup, same clean-6 gate

Only diff: feature set.
  - v5c-A:  19 features (v5b set + use_role)
  - v5c-E:  full set = all 33 GBM base features + p_for_cal + use_role = 35

If v5c-E ties or beats v5c-A on clean-6:
   -> features were not truly harmful; LOFO classification was hyperparam-bound.
   -> Save full-corpus .cbm with full feature set for runtime.
If v5c-E loses on clean-6:
   -> features genuinely harmful; v5c-A 19-set stands.

Output: data/model/catboost_playoff_v5cE_fullfeat.json
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
V5C_PATH   = ROOT / "data" / "model" / "catboost_playoff_v5c_sweep.json"
OUT_PATH   = ROOT / "data" / "model" / "catboost_playoff_v5cE_fullfeat.json"

# Full GBM base feature contract (matches BASE_FEATS in catboost_calibrator.py)
GBM_BASE_FEATURES = [
    "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
    "is_assists", "is_threes", "games_norm", "thin_flag", "line_norm",
    "is_home_feat", "min_sensitivity", "game_total_norm", "is_b2b",
    "l20_edge", "l10_has", "margin", "stat_cat", "tier_cat", "l40_hr",
    "logit_p_x_demon", "player_te", "player_stat_te", "player_dir_te",
    "player_n_norm", "line_dist", "tail_risk", "line_tightness",
    "margin_x_under", "q_blowout", "rate_cv", "abs_logit_p", "q_x_under",
]

# v5c-E feature set: full GBM base + p_for_cal + use_role
FULL_FEATURES = GBM_BASE_FEATURES + ["p_for_cal", "use_role"]

CAT_FEATURES_ALL = ["stat_cat", "tier_cat", "use_role"]

# v5c-A architecture (identical to promoted)
HYPERPARAMS = dict(
    iterations=500,
    depth=5,
    learning_rate=0.075,
    l2_leaf_reg=6.0,
    min_data_in_leaf=50,
    loss_function="RMSE",
    eval_metric="RMSE",
    random_seed=42,
    verbose=False,
    early_stopping_rounds=50,
    use_best_model=True,
)
RESIDUAL_SCALE = 0.50
RESIDUAL_CLIP = 0.20

# Clean-6 gate
SMALL_SLATE_THRESHOLD = 1000
GATE_LARGE_MB         = 5.0
GATE_SMALL_MB         = 10.0
EXCLUDE_SLATES        = {"2026-05-02", "2026-05-04", "2026-05-06"}


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


def apply_residual(p, r, scale, clip):
    return np.clip(p + scale * np.clip(r, -clip, clip), 1e-4, 1.0 - 1e-4)


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

        m = CatBoostRegressor(**HYPERPARAMS)
        m.fit(train_pool, eval_set=eval_pool)
        pred = m.predict(test_pool)
        oof_residual[test_mask] = pred

        p_after  = apply_residual(pforcal_arr[test_mask], pred, RESIDUAL_SCALE, RESIDUAL_CLIP)
        b_before = brier(hit_arr[test_mask], pforcal_arr[test_mask])
        b_after  = brier(hit_arr[test_mask], p_after)
        delta_mb = (b_after - b_before) * 1000.0
        fold_rows.append({
            "date": held, "n": int(test_mask.sum()),
            "brier_pforcal": b_before, "brier_after_cal": b_after,
            "delta_mB": delta_mb, "best_iter": int(m.tree_count_),
        })
        print(f"  [{label}] {held}  n={int(test_mask.sum()):>5}  "
              f"raw={b_before:.4f}  cal={b_after:.4f}  d={delta_mb:+6.2f}mB  "
              f"trees={m.tree_count_}", flush=True)

    valid    = ~np.isnan(oof_residual)
    p_oof    = apply_residual(pforcal_arr[valid], oof_residual[valid], RESIDUAL_SCALE, RESIDUAL_CLIP)
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

    active_mask = np.isin(date_arr, list(set(dates) - EXCLUDE_SLATES))
    valid_clean = valid & active_mask
    if valid_clean.any():
        b_clean_pre  = brier(hit_arr[valid_clean], pforcal_arr[valid_clean])
        r_clean = oof_residual[valid_clean]
        p_clean_after = apply_residual(pforcal_arr[valid_clean], r_clean, RESIDUAL_SCALE, RESIDUAL_CLIP)
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
    print("v5c-E: full feature set (35) at v5c-A architecture")
    print("=" * 80)
    print(f"Features ({len(FULL_FEATURES)}):")
    for f in FULL_FEATURES:
        print(f"  {f}")
    print()
    print(f"Hyperparams: iter={HYPERPARAMS['iterations']}, lr={HYPERPARAMS['learning_rate']}, "
          f"depth={HYPERPARAMS['depth']}, l2={HYPERPARAMS['l2_leaf_reg']}, "
          f"min_leaf={HYPERPARAMS['min_data_in_leaf']}, scale={RESIDUAL_SCALE}")
    print(f"Clean-6 excludes: {sorted(EXCLUDE_SLATES)}")
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

    # Verify all 35 features present
    missing = [f for f in FULL_FEATURES if f not in cv.columns]
    if missing:
        print(f"ERROR: missing features in cache: {missing}")
        return 1

    hit_arr     = cv["hit"].astype(float).to_numpy()
    pforcal_arr = cv["p_for_cal"].to_numpy()
    date_arr    = cv["game_date"].astype(str).str[:10].values
    dates       = sorted(np.unique(date_arr).tolist())

    print(f"  {len(cv):,} legs | {len(dates)} dates")
    print()

    t0 = time.time()
    r = run_lodo(cv, FULL_FEATURES, pforcal_arr, hit_arr, date_arr, dates, "v5c-E")
    elapsed = time.time() - t0

    # Compare to v5c-A from sweep file
    v5c = json.loads(V5C_PATH.read_text())
    v5cA_key = next((k for k in v5c if "scale050" in k), None)
    v5cA = v5c[v5cA_key] if v5cA_key else None

    print()
    print("=" * 80)
    print("v5c-E COMPLETE")
    print("=" * 80)
    print(f"agg (all 9):    {r['agg_delta_mB']:+.3f} mB")
    print(f"agg (clean-6):  {r['clean_agg_delta_mB']:+.3f} mB")
    print(f"worst (all 9):  {r['worst_slate_mB']:+.3f} mB")
    print(f"worst clean-6:  {r['clean_worst_slate_mB']:+.3f} mB")
    print(f"verdict strict: {r['verdict_strict']}")
    print(f"verdict clean:  {r['verdict_clean']}")
    print(f"elapsed:        {elapsed:.1f}s")
    print()
    print("=" * 80)
    print("HEAD-TO-HEAD vs v5c-A (19 features)")
    print("=" * 80)
    if v5cA:
        print(f"{'metric':<25} {'v5c-A (19)':>12} {'v5c-E (35)':>12} {'delta':>10}")
        for label, key in [
            ("agg (all 9)",        "agg_delta_mB"),
            ("agg (clean-6)",      "clean_agg_delta_mB"),
            ("worst (all 9)",      "worst_slate_mB"),
            ("worst clean-6",      "clean_worst_slate_mB"),
        ]:
            a = v5cA[key]; e = r[key]
            d = e - a
            print(f"{label:<25} {a:>+12.3f} {e:>+12.3f} {d:>+10.3f}")
        print()
        print(f"v5c-A verdict_clean: {v5cA['verdict_clean']}")
        print(f"v5c-E verdict_clean: {r['verdict_clean']}")
        print()
        # Per-slate diff
        print("Per-slate clean-6 deltas (v5c-E - v5c-A, negative = E better):")
        a_folds = {f["date"]: f["delta_mB"] for f in v5cA["folds"]}
        for f in r["folds"]:
            if f["date"] in EXCLUDE_SLATES:
                tag = " [excluded]"
            else:
                tag = ""
            d = f["delta_mB"] - a_folds.get(f["date"], 0)
            print(f"  {f['date']}  v5cA={a_folds.get(f['date'],0):+6.2f}  "
                  f"v5cE={f['delta_mB']:+6.2f}  diff={d:+6.2f}{tag}")
    else:
        print("(could not load v5c-A baseline)")

    out = {
        "version": "v5c-E_fullfeat",
        "test": "head_to_head_full_vs_19_at_v5cA_arch",
        "features": FULL_FEATURES,
        "n_features": len(FULL_FEATURES),
        "hyperparams": HYPERPARAMS,
        "residual_scale": RESIDUAL_SCALE,
        "residual_clip": RESIDUAL_CLIP,
        "clean6_excludes": sorted(EXCLUDE_SLATES),
        "results": r,
        "v5cA_baseline": v5cA,
        "elapsed_sec": elapsed,
    }
    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))
    print()
    print(f"Wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
