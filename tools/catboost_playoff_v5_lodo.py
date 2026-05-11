"""
v5 LODO -- drops all HARMFUL features identified by v4 LOFO.

Reads:  data/model/catboost_playoff_v4_lofo.json
Writes: data/model/catboost_playoff_v5_lodo.json
        data/model/catboost_playoff_v5_run.log (tee from caller)

Rule (per user):
  - DROP any feature whose v4 LOFO class starts with "HARMFUL"
    (this includes plain "HARMFUL" and "HARMFUL+SLATE_FIX")
  - KEEP HELPFUL, HELPFUL+SLATE_FIX, neutral, neutral+SLATE_FIX

Same hyperparams + p_for_cal source as v4 (p_for_cal := p_adj, use_role flag,
LODO 9-fold, iter=500, depth=5, lr=0.05, scale=0.5, clip=0.20).
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

CACHE_PATH    = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
V4_LOFO_PATH  = ROOT / "data" / "model" / "catboost_playoff_v4_lofo.json"
OUT_PATH      = ROOT / "data" / "model" / "catboost_playoff_v5_lodo.json"

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
             label: str, verbose_per_fold: bool = True):
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
    # Strict gate
    verdict_strict = "PROMOTE" if (agg_mb < -0.5 and per_slate_pass) else "REJECT"

    # Lenient gate -- exclude the two known-noise slates (05-02 single game, 05-04 role_ctx churn)
    EXCLUDE_SLATES = {"2026-05-02", "2026-05-04"}
    clean = [r for r in fold_rows if r["date"] not in EXCLUDE_SLATES]
    if clean:
        clean_pass = all(
            (r["delta_mB"] <= GATE_LARGE_MB if r["n"] >= SMALL_SLATE_THRESHOLD
             else r["delta_mB"] <= GATE_SMALL_MB)
            for r in clean
        )
        clean_worst = max(r["delta_mB"] for r in clean)
        verdict_lenient = "PROMOTE" if (agg_mb < -0.5 and clean_pass) else "REJECT"
    else:
        clean_pass = False
        clean_worst = float("nan")
        verdict_lenient = "REJECT"

    return {
        "label": label,
        "n_features": len(features),
        "agg_brier_pforcal": b_before,
        "agg_brier_after_cal": b_after,
        "agg_delta_mB": agg_mb,
        "worst_slate_mB": worst_mb,
        "n_slates_regressing": n_regress,
        "per_slate_pass_strict": per_slate_pass,
        "per_slate_pass_clean": clean_pass,
        "clean_worst_slate_mB": clean_worst,
        "verdict_strict": verdict_strict,
        "verdict_clean": verdict_lenient,
        "folds": fold_rows,
    }


def main() -> int:
    print("=" * 80)
    print("v5 LODO -- HARMFUL features dropped per v4 LOFO")
    print("=" * 80)

    if not V4_LOFO_PATH.exists():
        print(f"ERROR: v4 LOFO results not found at {V4_LOFO_PATH}")
        print("       Run tools/catboost_playoff_v4_lodo_lofo.py first.")
        return 1

    with open(V4_LOFO_PATH, "r") as f:
        v4_lofo = json.load(f)

    v4_features = v4_lofo["v4_features"]
    lofo_results = v4_lofo["lofo_results"]
    base_v4 = v4_lofo["v4_lodo_baseline"]

    cls_by_feat = {r["feature"]: r["class"] for r in lofo_results}

    # Selection rule: keep feature unless its class starts with "HARMFUL"
    v5_features = [f for f in v4_features if not cls_by_feat.get(f, "").startswith("HARMFUL")]
    dropped     = [f for f in v4_features if cls_by_feat.get(f, "").startswith("HARMFUL")]

    print(f"v4 baseline:")
    print(f"  agg d         = {base_v4['agg_delta_mB']:+.2f} mB")
    print(f"  worst slate   = {base_v4['worst_slate_mB']:+.2f} mB")
    print(f"  verdict       = {base_v4['verdict']}")
    print()
    print(f"v4 LOFO classifications:")
    for r in sorted(lofo_results, key=lambda r: -r["d_agg_vs_v4"]):
        keep_drop = "DROP" if r["feature"] in dropped else "keep"
        print(f"  {r['feature']:<22} d_agg={r['d_agg_vs_v4']:+6.2f}  "
              f"d_worst={r['d_worst_vs_v4']:+6.2f}  class={r['class']:<22}  -> {keep_drop}")
    print()
    print(f"Dropped from v4 ({len(dropped)}): {dropped}")
    print(f"v5 feature set ({len(v5_features)}): {v5_features}")
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

    needed_pre = {"p_adj", "p_role", "role_ctx_outs_used", "hit", "game_date"}
    missing_pre = [c for c in needed_pre if c not in cv.columns]
    if missing_pre:
        print(f"ERROR: missing source columns: {missing_pre}")
        return 1

    cv["p_for_cal"] = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1)
    cv["use_role"] = (pd.to_numeric(cv["role_ctx_outs_used"], errors="coerce")
                        .fillna(0).astype(int) > 0).astype(int)

    missing = [c for c in v5_features if c not in cv.columns]
    if missing:
        print(f"ERROR: missing v5 feature columns: {missing}")
        return 1

    hit_arr     = cv["hit"].astype(float).to_numpy()
    pforcal_arr = cv["p_for_cal"].to_numpy()
    date_arr    = cv["game_date"].astype(str).str[:10].values
    dates       = sorted(np.unique(date_arr).tolist())

    print(f"  {len(cv):,} legs | {len(dates)} dates")
    print(f"  Brier(p_for_cal := p_adj) = {brier(hit_arr, pforcal_arr):.6f}")
    print()
    print("=" * 80)
    print("PHASE: v5 LODO (9-fold)")
    print("=" * 80)
    t0 = time.time()
    res = run_lodo(
        cv=cv,
        features=v5_features,
        pforcal_arr=pforcal_arr,
        hit_arr=hit_arr,
        date_arr=date_arr,
        dates=dates,
        label="v5",
    )
    elapsed = time.time() - t0
    print()
    print(f"v5 LODO completed in {elapsed:.1f}s")
    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"  features              = {res['n_features']}")
    print(f"  agg cal Brier         = {res['agg_brier_after_cal']:.6f}")
    print(f"  agg d                 = {res['agg_delta_mB']:+.2f} mB")
    print(f"  worst slate (all 9)   = {res['worst_slate_mB']:+.2f} mB")
    print(f"  worst slate (clean 7) = {res['clean_worst_slate_mB']:+.2f} mB")
    print(f"  per-slate pass strict = {res['per_slate_pass_strict']}")
    print(f"  per-slate pass clean  = {res['per_slate_pass_clean']}")
    print(f"  verdict (strict 9)    = {res['verdict_strict']}")
    print(f"  verdict (clean 7)     = {res['verdict_clean']}")
    print()

    print("Per-slate breakdown:")
    print(f"  {'date':<12} {'n':>5} {'raw':>8} {'cal':>8} {'d_mB':>8}")
    for r in res["folds"]:
        excl = "  [excluded]" if r["date"] in {"2026-05-02", "2026-05-04"} else ""
        print(f"  {r['date']:<12} {r['n']:>5} {r['brier_pforcal']:>8.4f} "
              f"{r['brier_after_cal']:>8.4f} {r['delta_mB']:>+8.2f}{excl}")
    print()

    # Comparison vs v4
    print("v5 vs v4:")
    print(f"  d_agg     v4 -> v5  = {base_v4['agg_delta_mB']:+.2f} -> {res['agg_delta_mB']:+.2f}  "
          f"(d = {res['agg_delta_mB'] - base_v4['agg_delta_mB']:+.2f} mB)")
    print(f"  d_worst   v4 -> v5  = {base_v4['worst_slate_mB']:+.2f} -> {res['worst_slate_mB']:+.2f}  "
          f"(d = {res['worst_slate_mB'] - base_v4['worst_slate_mB']:+.2f} mB)")
    print()

    payload = {
        "cache": str(CACHE_PATH),
        "v4_lofo_source": str(V4_LOFO_PATH),
        "v4_features": v4_features,
        "v5_features": v5_features,
        "dropped_from_v4": dropped,
        "drop_rule": "class.startswith('HARMFUL')",
        "hyperparams": {
            "iterations": CAT_PARAMS["iterations"],
            "depth": CAT_PARAMS["depth"],
            "learning_rate": CAT_PARAMS["learning_rate"],
            "l2_leaf_reg": CAT_PARAMS["l2_leaf_reg"],
            "min_data_in_leaf": CAT_PARAMS["min_data_in_leaf"],
            "residual_clip": RESIDUAL_CLIP,
            "residual_scale": RESIDUAL_SCALE,
        },
        "v4_baseline": base_v4,
        "v5_lodo": res,
        "elapsed_sec": elapsed,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"Wrote: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
