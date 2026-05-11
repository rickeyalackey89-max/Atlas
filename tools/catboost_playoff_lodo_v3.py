"""
CatBoost Playoff LODO Trainer -- v3 (Residual Calibrator)
=========================================================
Structural redesign of v2 to address its failure modes:

  v2 problem: trained as a full classifier with the same TE features the
  upstream v18 GBM already used, with class balancing and 800 trees. It
  effectively re-predicted hit from scratch and overrode p_for_cal, causing
  per-slate regressions on dates where p_for_cal was already well-calibrated.

  v3 design: train a *residual* model that predicts the calibration error
  of p_for_cal as a function of CONTEXT only. Final prediction is
  p_for_cal nudged by a clipped residual.

Key differences from v2:
  - Target = (hit - p_for_cal) instead of hit
  - Loss   = RMSE (regression on residual)
  - Features = CONTEXT-ONLY (no TE features, no player identity signal)
               -> calibrator can only learn "p_for_cal tends to mis-price
                  high q_blowout / under / late-margin / b2b / etc."
  - Class weighting REMOVED (irrelevant for regression anyway)
  - Hyperparameters cut: 200 iter, depth=5, lr=0.05
  - Residual is CLIPPED to [-0.10, +0.10] at inference to forbid override
  - Verdict gate: PROMOTE only if aggregate improves AND no per-slate
    regression worse than +5 mB

Inputs:
    data/model/_v1_playoff_resim_cache.pkl  (built from inference TE)

Outputs (kept separate from v2 so v2 stays as a control):
    data/model/catboost_playoff_v3/                    -- fold + full models
    data/model/catboost_playoff_v3_ensemble_meta.json
    data/model/catboost_playoff_v3_manifest.json
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
from catboost import CatBoostRegressor, Pool  # type: ignore[import-untyped]

warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CACHE_PATH    = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
MODEL_OUT     = ROOT / "data" / "model" / "catboost_playoff_v3"
META_PATH     = ROOT / "data" / "model" / "catboost_playoff_v3_ensemble_meta.json"
MANIFEST_PATH = ROOT / "data" / "model" / "catboost_playoff_v3_manifest.json"

# ---------------------------------------------------------------------------
# Features -- CONTEXT ONLY
#
# Excluded vs v2:
#   - player_te / player_stat_te / player_dir_te / player_n_norm
#       (player identity is already encoded in p_for_cal via v18 GBM)
#   - l40_hr / l20_edge / l10_has  (rolling player hit rates -- same reason)
#   - logit_p_x_demon / abs_logit_p  (functions of p itself, redundant with p_for_cal)
#
# Kept: state-of-game / line-shape / matchup context that p_for_cal might
# systematically mis-price.
# ---------------------------------------------------------------------------
FEATURES = [
    "p_for_cal",        # the value being calibrated
    "z_line",
    "min_cv",
    "is_combo",
    "bp_score_gated",
    "bp_has",
    "is_assists",
    "is_threes",
    "thin_flag",
    "line_norm",
    "is_home_feat",
    "min_sensitivity",
    "game_total_norm",
    "is_b2b",
    "margin",
    "stat_cat",
    "tier_cat",
    "line_dist",
    "tail_risk",
    "line_tightness",
    "margin_x_under",
    "q_blowout",
    "rate_cv",
    "q_x_under",
]
CAT_FEATURES = ["stat_cat", "tier_cat"]

# ---------------------------------------------------------------------------
# Hyperparameters -- light, calibrator-appropriate
# ---------------------------------------------------------------------------
CAT_PARAMS: dict = dict(
    iterations=3000,
    depth=5,
    learning_rate=0.02,
    l2_leaf_reg=6.0,
    min_data_in_leaf=50,
    loss_function="RMSE",
    eval_metric="RMSE",
    random_seed=42,
    verbose=200,
    early_stopping_rounds=100,
    use_best_model=True,
)

# Residual clip applied at inference to keep the calibrator a nudge, not a replacer.
#
# Sized empirically from playoff corpus bucket analysis (2026-04-30 to 2026-05-08,
# 13,186 legs). Largest systematic bucket residuals (n >= 100):
#   p_for_cal in (0, 0.25]:                      +0.161   (n=3,571)
#   joint OVER x low-p x mid q_blowout:          +0.158   (n=3,679)
#   joint UNDER x high-p:                        -0.166   (n=252)
#   tier_cat=1 (DEMON):                          +0.122   (n=4,250)
#   p_for_cal in (0.85, 1.0]:                    -0.283   (n=136, thin)
# 0.20 covers the meaningful (n>=250) pockets at full strength while keeping the
# calibrator a nudge: a p=0.50 prediction can only land in [0.30, 0.70]; a p=0.95
# prediction in [0.75, 1.0]. Tighter (0.10) leaves ~60mB of correction on the table
# in the (0, 0.25] bucket. Wider (0.30) starts to allow override behavior.
RESIDUAL_CLIP = 0.20

# Residual shrinkage: apply only this fraction of the predicted residual.
# 1.0 = full nudge, 0.5 = half-strength, 0.4 = current setting.
# At 0.4 the corpus-mean nudge is dampened enough that mildly off-trend slates
# don't blow past the gate while real signal still survives.
RESIDUAL_SCALE = 0.6

# Per-slate verdict gate (mB). Sub-1000-leg slates have higher per-leg variance,
# so a single 600-leg slate showing +10 mB is noise-dominated, not signal.
PER_SLATE_TOLERANCE_MB_LARGE = 5.0   # n >= 1000
PER_SLATE_TOLERANCE_MB_SMALL = 10.0  # n <  1000
SMALL_SLATE_THRESHOLD = 1000


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


def apply_residual(p_for_cal: np.ndarray, residual: np.ndarray) -> np.ndarray:
    clipped = np.clip(residual, -RESIDUAL_CLIP, RESIDUAL_CLIP)
    return np.clip(p_for_cal + RESIDUAL_SCALE * clipped, 1e-4, 1.0 - 1e-4)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    MODEL_OUT.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("=== CatBoost Playoff LODO Trainer v3 (Residual) ===")
    print(f"Timestamp: {run_ts}")
    print(f"Cache:     {CACHE_PATH}")
    print(f"Mode:      RESIDUAL  (target = hit - p_for_cal)")
    print(f"Features:  {len(FEATURES)} context-only (no TE, no player rolling stats)")
    print(f"Clip:      +/- {RESIDUAL_CLIP:.2f}")
    print(f"Scale:     {RESIDUAL_SCALE:.2f}  (residual shrinkage at inference)")
    print()

    # ------------------------------------------------------------------
    # 1. Load resim cache
    # ------------------------------------------------------------------
    if not CACHE_PATH.exists():
        print(f"ERROR: Cache not found at {CACHE_PATH}")
        return 1

    print("[1/4] Loading resim cache...")
    with open(CACHE_PATH, "rb") as f:
        cache = pickle.load(f)

    cv = cache["cv"].copy()
    print(f"  {len(cv):,} legs | {len(cache['dates'])} dates | cache Brier={cache['raw_brier']:.6f}")

    # ------------------------------------------------------------------
    # 2. Validate / prepare
    # ------------------------------------------------------------------
    print(f"\n[2/4] Validating {len(FEATURES)} features...")

    if "p_for_cal" not in cv.columns:
        print("ERROR: p_for_cal missing from cache")
        return 1

    missing = [f for f in FEATURES if f not in cv.columns]
    if missing:
        print(f"ERROR: missing features: {missing}")
        return 1

    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0.0, 1.0, 0, 1])].reset_index(drop=True)

    hit_arr     = cv["hit"].to_numpy(dtype=float)
    pforcal_arr = pd.to_numeric(cv["p_for_cal"], errors="coerce").fillna(0.5).to_numpy(dtype=float)
    residual    = hit_arr - pforcal_arr  # the regression target
    date_arr    = cv["game_date"].astype(str).str[:10].values
    dates       = sorted(np.unique(date_arr).tolist())

    n_over   = int((cv["direction"].astype(str).str.upper() == "OVER").sum())
    n_under  = int((cv["direction"].astype(str).str.upper() == "UNDER").sum())
    hit_rate = float(hit_arr.mean())
    b_base   = brier(hit_arr, pforcal_arr)

    print(f"  Total legs: {len(cv):,}  |  OVER: {n_over:,}  UNDER: {n_under:,}")
    print(f"  Overall hit rate: {hit_rate:.3f}")
    print(f"  Baseline p_for_cal Brier: {b_base:.6f}")
    print(f"  Residual stats: mean={residual.mean():+.4f}  std={residual.std():.4f}")
    print(f"                  min={residual.min():+.3f}  max={residual.max():+.3f}")

    print(f"\n  Feature coverage:")
    for f in FEATURES:
        vals = pd.to_numeric(cv[f], errors="coerce")
        cov  = vals.notna().sum() / len(cv) * 100
        print(f"    {f:25s}  cov={cov:5.1f}%  mean={vals.mean():+.4f}")

    X_full = prep_X(cv)

    # ------------------------------------------------------------------
    # 3. LODO
    # ------------------------------------------------------------------
    print(f"\n[3/4] LODO cross-validation ({len(dates)} folds)...")
    print(f"  depth={CAT_PARAMS['depth']}  iter={CAT_PARAMS['iterations']}  "
          f"lr={CAT_PARAMS['learning_rate']}  early_stop={CAT_PARAMS['early_stopping_rounds']}")
    print("-" * 76)

    fold_results: list[dict] = []
    oof_residual = np.full(len(cv), np.nan)

    for held_date in dates:
        test_mask  = date_arr == held_date
        train_mask = ~test_mask

        y_train_all = residual[train_mask]
        X_train_all = X_full[train_mask].reset_index(drop=True)
        X_test_df   = X_full[test_mask].reset_index(drop=True)

        rng       = np.random.default_rng(42)
        n_tr      = len(X_train_all)
        eval_idx  = rng.choice(n_tr, size=max(1, n_tr // 10), replace=False)
        train_idx = np.setdiff1d(np.arange(n_tr), eval_idx)

        train_pool = make_pool(X_train_all.iloc[train_idx], y_train_all[train_idx])
        eval_pool  = make_pool(X_train_all.iloc[eval_idx],  y_train_all[eval_idx])
        test_pool  = make_pool(X_test_df)

        model = CatBoostRegressor(**CAT_PARAMS)
        model.fit(train_pool, eval_set=eval_pool)

        residual_pred = model.predict(test_pool)
        oof_residual[test_mask] = residual_pred

        p_after = apply_residual(pforcal_arr[test_mask], residual_pred)
        b_before = brier(hit_arr[test_mask], pforcal_arr[test_mask])
        b_after  = brier(hit_arr[test_mask], p_after)
        best_iter = int(model.get_best_iteration() or CAT_PARAMS["iterations"])

        model_path = MODEL_OUT / f"catboost_v3_fold_{held_date}.cbm"
        model.save_model(str(model_path))

        fold_results.append({
            "date":         held_date,
            "n_test":       int(test_mask.sum()),
            "n_train":      int(train_mask.sum()),
            "best_iter":    best_iter,
            "brier_before": round(b_before, 6),
            "brier_after":  round(b_after,  6),
            "delta":        round(b_after - b_before, 6),
            "delta_mb":     round((b_after - b_before) * 1000, 2),
            "resid_mean":   round(float(residual_pred.mean()), 4),
            "resid_abs":    round(float(np.abs(residual_pred).mean()), 4),
            "model_path":   str(model_path),
        })

        sign = "+" if b_after < b_before else "-"
        print(f"  [{sign}] {held_date}  n={test_mask.sum():>4,}  "
              f"before={b_before:.6f}  after={b_after:.6f}  "
              f"delta={(b_after - b_before)*1000:+7.2f} mB  iter={best_iter}  "
              f"|resid|={np.abs(residual_pred).mean():.4f}")

    # ------------------------------------------------------------------
    # OOF aggregate + verdict
    # ------------------------------------------------------------------
    valid        = ~np.isnan(oof_residual)
    p_oof        = apply_residual(pforcal_arr[valid], oof_residual[valid])
    b_oof_before = brier(hit_arr[valid], pforcal_arr[valid])
    b_oof_after  = brier(hit_arr[valid], p_oof)
    delta_mb     = (b_oof_after - b_oof_before) * 1000

    # Sample-size-aware per-slate gate
    bad_slates = []
    for r in fold_results:
        tol = (PER_SLATE_TOLERANCE_MB_LARGE if r["n_test"] >= SMALL_SLATE_THRESHOLD
               else PER_SLATE_TOLERANCE_MB_SMALL)
        if r["delta_mb"] > tol:
            bad_slates.append((r["date"], r["n_test"], r["delta_mb"], tol))

    worst_per_slate_mb = max(r["delta_mb"] for r in fold_results)
    aggregate_improves = b_oof_after < b_oof_before
    no_bad_slate       = len(bad_slates) == 0

    if aggregate_improves and no_bad_slate:
        verdict = "PROMOTE"
    elif aggregate_improves and not no_bad_slate:
        verdict = "REJECT (per-slate regression)"
    else:
        verdict = "REJECT"

    print()
    print("=== LODO Summary (v3 Residual) ===")
    print(f"  OOF Brier (p_for_cal baseline): {b_oof_before:.6f}")
    print(f"  OOF Brier (CatBoost v3 nudge):  {b_oof_after:.6f}  ({delta_mb:+.2f} mB)")
    print(f"  Worst per-slate delta:          {worst_per_slate_mb:+.2f} mB")
    print(f"  Per-slate gate: <+{PER_SLATE_TOLERANCE_MB_LARGE:.1f} mB (n>={SMALL_SLATE_THRESHOLD}), "
          f"<+{PER_SLATE_TOLERANCE_MB_SMALL:.1f} mB (n<{SMALL_SLATE_THRESHOLD})")
    if bad_slates:
        print(f"  Slates exceeding gate:")
        for date, n, delta, tol in bad_slates:
            print(f"    {date}  n={n:>5,}  delta={delta:+.2f} mB  (tol={tol:.1f})")
    print(f"  Verdict: {verdict}")
    print()
    print(f"  {'Date':<12} {'N':>5}  {'Before':>10}  {'After':>10}  {'mB':>8}  {'|res|':>7}  {'Iter':>5}")
    for r in fold_results:
        print(f"  {r['date']:<12} {r['n_test']:>5,}  {r['brier_before']:>10.6f}  "
              f"{r['brier_after']:>10.6f}  {r['delta_mb']:>+8.2f}  {r['resid_abs']:>7.4f}  {r['best_iter']:>5}")

    # ------------------------------------------------------------------
    # 4. Full-corpus model -- only if PROMOTE
    # ------------------------------------------------------------------
    full_model_path = None
    importances: dict[str, float] = {}

    if verdict == "PROMOTE":
        print("\n[4/4] Training full-corpus model (verdict=PROMOTE)...")
        full_params = {k: v for k, v in CAT_PARAMS.items()
                       if k not in ("early_stopping_rounds", "use_best_model")}
        full_params["verbose"] = 50
        full_pool  = make_pool(X_full, residual)
        full_model = CatBoostRegressor(**full_params)
        full_model.fit(full_pool)
        full_model_path = MODEL_OUT / "catboost_v3_full_corpus.cbm"
        full_model.save_model(str(full_model_path))

        importances = dict(zip(FEATURES, full_model.get_feature_importance().tolist()))
        top_feats = sorted(importances.items(), key=lambda x: x[1], reverse=True)
        print(f"\n  {'Feature':<30}  {'Importance':>10}")
        for feat, imp in top_feats:
            if imp > 0.01:
                print(f"  {feat:<30}  {imp:>10.2f}")
    else:
        print(f"\n[4/4] Skipping full-corpus model save (verdict={verdict})")

    # ------------------------------------------------------------------
    # Save meta + manifest
    # ------------------------------------------------------------------
    meta = {
        "version":            "catboost_playoff_v3_residual",
        "trained_at":         run_ts,
        "cache_path":         str(CACHE_PATH),
        "mode":               "residual",
        "target":             "hit - p_for_cal",
        "loss":               "RMSE",
        "residual_clip":      RESIDUAL_CLIP,
        "residual_scale":     RESIDUAL_SCALE,
        "per_slate_gate_mB_large": PER_SLATE_TOLERANCE_MB_LARGE,
        "per_slate_gate_mB_small": PER_SLATE_TOLERANCE_MB_SMALL,
        "small_slate_threshold":   SMALL_SLATE_THRESHOLD,
        "n_dates":            len(dates),
        "dates":              dates,
        "n_legs_total":       int(len(cv)),
        "n_over":             n_over,
        "n_under":            n_under,
        "hit_rate":           round(hit_rate, 4),
        "oof_brier_before":   round(b_oof_before, 6),
        "oof_brier_after":    round(b_oof_after,  6),
        "oof_brier_delta_mB": round(delta_mb, 2),
        "worst_slate_mB":     round(worst_per_slate_mb, 2),
        "verdict":            verdict,
        "features":           FEATURES,
        "cat_features":       CAT_FEATURES,
        "hyperparams":        CAT_PARAMS,
        "fold_results":       fold_results,
        "model_dir":          str(MODEL_OUT),
        "full_model_path":    str(full_model_path) if full_model_path else None,
        "feature_importance": importances,
    }
    META_PATH.write_text(json.dumps(meta, indent=2))

    manifest = {
        "manifest_type":  "catboost_playoff_lodo_v3",
        "created_at":     run_ts,
        "verdict":        verdict,
        "summary": {
            "n_dates":            len(dates),
            "n_legs_total":       int(len(cv)),
            "oof_brier_baseline": round(b_oof_before, 6),
            "oof_brier_v3":       round(b_oof_after,  6),
            "oof_brier_delta_mB": round(delta_mb, 2),
            "worst_slate_mB":     round(worst_per_slate_mb, 2),
            "per_slate_gate_mB_large": PER_SLATE_TOLERANCE_MB_LARGE,
            "per_slate_gate_mB_small": PER_SLATE_TOLERANCE_MB_SMALL,
            "small_slate_threshold":   SMALL_SLATE_THRESHOLD,
        },
        "config": {
            "cache":          str(CACHE_PATH.name),
            "mode":           "residual",
            "residual_clip":  RESIDUAL_CLIP,
            "residual_scale": RESIDUAL_SCALE,
            "features":       FEATURES,
            "cat_features":   CAT_FEATURES,
            "hyperparams":    CAT_PARAMS,
        },
        "fold_results": fold_results,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))

    print(f"\nMeta     -> {META_PATH}")
    print(f"Manifest -> {MANIFEST_PATH}")
    print(f"\nVerdict: {verdict}  ({delta_mb:+.2f} mB aggregate, worst slate {worst_per_slate_mb:+.2f} mB)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    args = ap.parse_args()
    sys.exit(main())
