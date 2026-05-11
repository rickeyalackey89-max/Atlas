"""
v4 LODO + LOFO Ablation
========================
v4 feature set (synthesizes prior LOFO + addback + fork-test findings):

  Start:  v3 24 base
  Drop:   LOFO HARMFUL+SLATE_FIX  -> min_cv, margin, is_threes        (-3)
  Add:    addback HELPFUL         -> player_te, player_stat_te,
                                     player_n_norm                     (+3)
  Add:    fork test OPT_C flag    -> use_role                          (+1)
  p_for_cal source: p_adj (always; bypass engine fork)

  v4 = 25 features.

Phase 1: v4 LODO with 9-fold CV. Same hyperparams as LOFO/addback for direct
         comparability:  iter=500  depth=5  lr=0.05  scale=0.5  clip=0.20.

Phase 2: v4 LOFO ablation -- drop each v4 feature one at a time, measure
         d_agg and d_worst vs v4 baseline. Classify HELPFUL / HARMFUL /
         neutral / +SLATE_FIX with same thresholds as the original LOFO pass:
            d_agg >= +0.5 mB  -> HELPFUL  (dropping it hurt -> keep)
            d_agg <= -0.5 mB  -> HARMFUL  (dropping it helped -> drop)
            else              -> neutral
            d_worst <= -0.5 mB additional tag -> +SLATE_FIX

Cost: v4 LODO ~2 min; v4 LOFO 25*9*13s ~50 min. Total ~52 min.

Outputs:
  data/model/catboost_playoff_v4_lodo.json
  data/model/catboost_playoff_v4_lofo.json
  data/model/catboost_playoff_v4_run.log (tee from caller)
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

CACHE_PATH        = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
LODO_OUT_PATH     = ROOT / "data" / "model" / "catboost_playoff_v4_lodo.json"
LOFO_OUT_PATH     = ROOT / "data" / "model" / "catboost_playoff_v4_lofo.json"

# v3 24-feature base
V3_FEATURES = [
    "p_for_cal", "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
    "is_assists", "is_threes", "thin_flag", "line_norm", "is_home_feat",
    "min_sensitivity", "game_total_norm", "is_b2b", "margin", "stat_cat",
    "tier_cat", "line_dist", "tail_risk", "line_tightness", "margin_x_under",
    "q_blowout", "rate_cv", "q_x_under",
]

# Drops from v3 LOFO HARMFUL+SLATE_FIX
LOFO_DROPS = ["min_cv", "margin", "is_threes"]

# Addback HELPFUL features (positive on aggregate)
ADDBACK_ADDS = ["player_te", "player_stat_te", "player_n_norm"]

# Fork-test OPT_C flag
FORK_TEST_ADD = ["use_role"]

V4_FEATURES = (
    [f for f in V3_FEATURES if f not in LOFO_DROPS]
    + ADDBACK_ADDS
    + FORK_TEST_ADD
)

# Categorical columns (any present in feature set is auto-detected)
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

# Per-slate gate thresholds
SMALL_SLATE_THRESHOLD = 1000
GATE_LARGE_MB         = 5.0
GATE_SMALL_MB         = 10.0


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
             hit_arr: np.ndarray, date_arr: np.ndarray, dates: list[str],
             label: str, verbose_per_fold: bool = False):
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
        if verbose_per_fold:
            print(f"  [{label}] {held}  n={int(test_mask.sum()):>5}  "
                  f"raw={b_before:.4f}  cal={b_after:.4f}  d={delta_mb:+6.2f}mB", flush=True)

    valid    = ~np.isnan(oof_residual)
    p_oof    = apply_residual(pforcal_arr[valid], oof_residual[valid])
    b_before = brier(hit_arr[valid], pforcal_arr[valid])
    b_after  = brier(hit_arr[valid], p_oof)
    agg_mb   = (b_after - b_before) * 1000.0
    worst_mb = max(r["delta_mB"] for r in fold_rows)
    n_regress = sum(1 for r in fold_rows if r["delta_mB"] > 0.5)

    per_slate_pass = all(
        (r["delta_mB"] <= GATE_LARGE_MB if r["n"] >= SMALL_SLATE_THRESHOLD
         else r["delta_mB"] <= GATE_SMALL_MB)
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
    print("=" * 80)
    print("v4 LODO + LOFO Ablation")
    print("=" * 80)
    print(f"Cache:    {CACHE_PATH}")
    print(f"Settings: iter={CAT_PARAMS['iterations']}  depth={CAT_PARAMS['depth']}  "
          f"lr={CAT_PARAMS['learning_rate']}  scale={RESIDUAL_SCALE}  clip={RESIDUAL_CLIP}")
    print(f"v4 features ({len(V4_FEATURES)}):")
    for f in V4_FEATURES:
        tag = ""
        if f in ADDBACK_ADDS:
            tag = "(+addback)"
        elif f in FORK_TEST_ADD:
            tag = "(+fork-test flag)"
        elif f not in V3_FEATURES:
            tag = "(+new)"
        print(f"  {f:<22} {tag}")
    print(f"Dropped from v3: {LOFO_DROPS}")
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

    # OPT_C source: p_for_cal := p_adj for all legs; use_role derived from outs count
    needed_pre = {"p_adj", "p_role", "role_ctx_outs_used", "hit", "game_date"}
    missing_pre = [c for c in needed_pre if c not in cv.columns]
    if missing_pre:
        print(f"ERROR: missing source columns: {missing_pre}")
        return 1
    cv["p_for_cal"] = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1)
    cv["use_role"] = (pd.to_numeric(cv["role_ctx_outs_used"], errors="coerce")
                        .fillna(0).astype(int) > 0).astype(int)

    # Now verify all v4 features exist (use_role is now derived)
    missing = [c for c in V4_FEATURES if c not in cv.columns]
    if missing:
        print(f"ERROR: missing v4 feature columns: {missing}")
        return 1

    hit_arr     = cv["hit"].astype(float).to_numpy()
    pforcal_arr = cv["p_for_cal"].to_numpy()
    date_arr    = cv["game_date"].astype(str).str[:10].values
    dates       = sorted(np.unique(date_arr).tolist())

    n_use_role = int(cv["use_role"].sum())
    print(f"  {len(cv):,} legs | {len(dates)} dates")
    print(f"  use_role=1 legs: {n_use_role:,} ({100*n_use_role/len(cv):.1f}%)")
    print(f"  Brier(p_for_cal := p_adj) = {brier(hit_arr, pforcal_arr):.6f}")
    print()

    # ============================================================
    # PHASE 1: v4 LODO baseline
    # ============================================================
    print("=" * 80)
    print("PHASE 1: v4 LODO baseline")
    print("=" * 80)
    t0 = time.time()
    res_v4 = run_lodo(
        cv=cv,
        features=V4_FEATURES,
        pforcal_arr=pforcal_arr,
        hit_arr=hit_arr,
        date_arr=date_arr,
        dates=dates,
        label="v4",
        verbose_per_fold=True,
    )
    t_v4 = time.time() - t0
    print()
    print(f"v4 LODO completed in {t_v4:.1f}s")
    print(f"  agg cal Brier = {res_v4['agg_brier_after_cal']:.6f}")
    print(f"  agg d         = {res_v4['agg_delta_mB']:+.2f} mB")
    print(f"  worst slate   = {res_v4['worst_slate_mB']:+.2f} mB")
    print(f"  per_slate_pass= {res_v4['per_slate_pass']}")
    print(f"  verdict       = {res_v4['verdict']}")
    print()

    # Persist v4 LODO result early
    payload_v4 = {
        "cache": str(CACHE_PATH),
        "n_legs": int(len(cv)),
        "n_dates": int(len(dates)),
        "n_use_role": n_use_role,
        "v4_features": V4_FEATURES,
        "lofo_drops_from_v3": LOFO_DROPS,
        "addback_adds": ADDBACK_ADDS,
        "fork_test_add": FORK_TEST_ADD,
        "p_for_cal_source": "p_adj",
        "hyperparams": {
            "iterations": CAT_PARAMS["iterations"],
            "depth": CAT_PARAMS["depth"],
            "learning_rate": CAT_PARAMS["learning_rate"],
            "l2_leaf_reg": CAT_PARAMS["l2_leaf_reg"],
            "min_data_in_leaf": CAT_PARAMS["min_data_in_leaf"],
            "residual_clip": RESIDUAL_CLIP,
            "residual_scale": RESIDUAL_SCALE,
        },
        "v4_lodo": res_v4,
        "elapsed_sec": t_v4,
    }
    LODO_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LODO_OUT_PATH, "w") as f:
        json.dump(payload_v4, f, indent=2, default=str)
    print(f"Wrote: {LODO_OUT_PATH}")
    print()

    # ============================================================
    # PHASE 2: v4 LOFO ablation
    # ============================================================
    print("=" * 80)
    print("PHASE 2: v4 LOFO ablation (drop each feature, measure delta)")
    print("=" * 80)
    print()

    base_agg   = res_v4["agg_delta_mB"]
    base_worst = res_v4["worst_slate_mB"]

    print(f"{'feature':<22} {'agg_mB':>8} {'d_agg':>8} {'worst_mB':>9} {'d_worst':>9} {'sec':>6}  class")
    print("-" * 88)

    lofo_rows = []
    t_total = time.time()
    for feat in V4_FEATURES:
        sub_features = [f for f in V4_FEATURES if f != feat]
        t0 = time.time()
        res = run_lodo(
            cv=cv,
            features=sub_features,
            pforcal_arr=pforcal_arr,
            hit_arr=hit_arr,
            date_arr=date_arr,
            dates=dates,
            label=f"-{feat}",
            verbose_per_fold=False,
        )
        sec = time.time() - t0
        d_agg   = res["agg_delta_mB"] - base_agg     # >0 means dropping HURT (feature was HELPFUL)
        d_worst = res["worst_slate_mB"] - base_worst

        # LOFO classification
        if d_agg >= 0.5:
            cls = "HELPFUL"
        elif d_agg <= -0.5:
            cls = "HARMFUL"
        else:
            cls = "neutral"
        if d_worst <= -0.5:
            cls += "+SLATE_FIX"

        lofo_rows.append({
            "feature": feat,
            "agg_brier_after_cal": res["agg_brier_after_cal"],
            "agg_delta_mB": res["agg_delta_mB"],
            "worst_slate_mB": res["worst_slate_mB"],
            "d_agg_vs_v4": d_agg,
            "d_worst_vs_v4": d_worst,
            "elapsed_sec": sec,
            "class": cls,
        })
        print(f"{feat:<22} {res['agg_delta_mB']:>+7.2f}  {d_agg:>+7.2f}  "
              f"{res['worst_slate_mB']:>+8.2f}  {d_worst:>+8.2f}  {sec:>5.1f}  {cls}", flush=True)

    t_lofo_total = time.time() - t_total
    print()
    print(f"v4 LOFO completed in {t_lofo_total/60:.1f} min")
    print()

    # Sorted summary -- most HELPFUL first
    lofo_sorted = sorted(lofo_rows, key=lambda r: -r["d_agg_vs_v4"])
    print("=" * 80)
    print("v4 LOFO summary (sorted: most HELPFUL = top, most HARMFUL = bottom)")
    print("=" * 80)
    print(f"{'feature':<22} {'d_agg':>8} {'d_worst':>9}  class")
    print("-" * 60)
    for r in lofo_sorted:
        print(f"{r['feature']:<22} {r['d_agg_vs_v4']:>+7.2f}  "
              f"{r['d_worst_vs_v4']:>+8.2f}  {r['class']}")
    print()

    helpful   = [r for r in lofo_rows if r["class"].startswith("HELPFUL")]
    harmful   = [r for r in lofo_rows if r["class"].startswith("HARMFUL")]
    slate_fix = [r for r in lofo_rows if "+SLATE_FIX" in r["class"]]
    neutral   = [r for r in lofo_rows if r["class"] == "neutral"]

    print(f"Buckets:")
    print(f"  HELPFUL   ({len(helpful)}, KEEP):           "
          f"{', '.join(r['feature'] for r in helpful)}")
    print(f"  HARMFUL   ({len(harmful)}, candidates to DROP): "
          f"{', '.join(r['feature'] for r in harmful)}")
    print(f"  +SLATE_FIX({len(slate_fix)}, dropping helps worst-slate too): "
          f"{', '.join(r['feature'] for r in slate_fix)}")
    print(f"  neutral   ({len(neutral)}, no significant impact)")
    print()

    payload_lofo = {
        "cache": str(CACHE_PATH),
        "v4_features": V4_FEATURES,
        "v4_lodo_baseline": {
            "agg_delta_mB":   base_agg,
            "worst_slate_mB": base_worst,
            "verdict":        res_v4["verdict"],
        },
        "lofo_results": lofo_rows,
        "elapsed_sec": t_lofo_total,
    }
    with open(LOFO_OUT_PATH, "w") as f:
        json.dump(payload_lofo, f, indent=2, default=str)
    print(f"Wrote: {LOFO_OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
