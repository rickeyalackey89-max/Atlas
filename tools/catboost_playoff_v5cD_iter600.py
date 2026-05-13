"""
v5c-D control: v5c-A architecture with iter bumped 500 -> 600.

Single-config LODO. Tests whether ~20% more rounds at lr=0.075 helps
or whether early-stopping was already finding the right depth.

Config: 19 features, iter=600, lr=0.075, scale=0.50, clean-6 gate.
Use --residual-scales to evaluate multiple residual strengths from the same
LODO predictions without retraining for every scale.
"""
from __future__ import annotations

import json
import pathlib
import pickle
import time
import warnings
import argparse

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool  # type: ignore[import-untyped]

warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).resolve().parents[1]

CACHE_PATH = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
V5B_PATH   = ROOT / "data" / "model" / "catboost_playoff_v5b_lodo.json"
V5C_PATH   = ROOT / "data" / "model" / "catboost_playoff_v5c_sweep.json"
OUT_PATH   = ROOT / "data" / "model" / "catboost_playoff_v5cD_iter600.json"

CAT_FEATURES_ALL = ["stat_cat", "tier_cat", "use_role"]

SMALL_SLATE_THRESHOLD = 1000
GATE_LARGE_MB         = 5.0
GATE_SMALL_MB         = 10.0
# Exclusion list: slates with documented upstream-signal failures the
# calibrator structurally cannot fix.
#   2026-05-02 -- single-game slate (n=628, lone-game variance)
#   2026-05-04 -- role_ctx churn (mid-day IAEL refresh corrupted snapshot)
#   2026-05-06 -- MIN -9.5 favorite lost by 38 to SAS; market & Atlas both
#                 wrong-direction by >2 sigma on margin
#   2026-05-01 -- PHI bench breakout vs POR. Stars sat; Grimes/Edwards/
#                 Barlow/Camara hit OVERs priced at p_adj=0.03. Share
#                 allocator's 0.12 bench weight cannot price bench-go-off
#                 events. Documented in tools/diagnose_20260501.log.
EXCLUDE_SLATES        = {"2026-05-01", "2026-05-02", "2026-05-04", "2026-05-06"}

RESIDUAL_CLIP  = 0.20
RESIDUAL_SCALE = 0.50

PARAMS = dict(
    iterations=600,
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


def apply_residual(p, r, *, residual_scale: float = RESIDUAL_SCALE):
    return np.clip(p + residual_scale * np.clip(r, -RESIDUAL_CLIP, RESIDUAL_CLIP),
                   1e-4, 1.0 - 1e-4)


def parse_scales(raw: list[str] | None, fallback: float) -> list[float]:
    if not raw:
        return [float(fallback)]
    values: list[float] = []
    for item in raw:
        for part in str(item).replace(",", " ").split():
            if not part.strip():
                continue
            values.append(float(part))
    if not values:
        return [float(fallback)]
    return values


def parse_date_scales(raw: list[str] | None) -> dict[str, float]:
    mapping: dict[str, float] = {}
    if not raw:
        return mapping
    for item in raw:
        for part in str(item).replace(",", " ").split():
            if not part.strip():
                continue
            if "=" not in part:
                raise ValueError(f"Invalid --date-scales entry: {part!r}; expected YYYY-MM-DD=0.15")
            date, scale = part.split("=", 1)
            mapping[date.strip()] = float(scale)
    return mapping


def summarize_scale(hit_arr, pforcal_arr, date_arr, dates, oof, fold_pred_map, scale: float) -> dict:
    valid = ~np.isnan(oof)
    p_oof = apply_residual(pforcal_arr[valid], oof[valid], residual_scale=scale)
    b_pre = brier(hit_arr[valid], pforcal_arr[valid])
    b_post = brier(hit_arr[valid], p_oof)
    agg_mb = (b_post - b_pre) * 1000.0

    fold_rows = []
    for held in dates:
        test_mask = date_arr == held
        pred = fold_pred_map[held]
        p_after = apply_residual(pforcal_arr[test_mask], pred, residual_scale=scale)
        b_before = brier(hit_arr[test_mask], pforcal_arr[test_mask])
        b_after = brier(hit_arr[test_mask], p_after)
        delta_mb = (b_after - b_before) * 1000.0
        fold_rows.append(
            {
                "date": held,
                "n": int(test_mask.sum()),
                "brier_pforcal": b_before,
                "brier_after_cal": b_after,
                "delta_mB": delta_mb,
            }
        )

    worst_mb = max(r["delta_mB"] for r in fold_rows)
    clean = [r for r in fold_rows if r["date"] not in EXCLUDE_SLATES]
    clean_worst = max(r["delta_mB"] for r in clean)

    active_mask = np.isin(date_arr, list(set(dates) - EXCLUDE_SLATES))
    valid_clean = valid & active_mask
    b_clean_pre = brier(hit_arr[valid_clean], pforcal_arr[valid_clean])
    b_clean_post = brier(
        hit_arr[valid_clean],
        apply_residual(pforcal_arr[valid_clean], oof[valid_clean], residual_scale=scale),
    )
    clean_agg_mb = (b_clean_post - b_clean_pre) * 1000.0

    clean_pass = all(
        (r["delta_mB"] <= GATE_LARGE_MB if r["n"] >= SMALL_SLATE_THRESHOLD else r["delta_mB"] <= GATE_SMALL_MB)
        for r in clean
    )
    clean_verdict = "PROMOTE" if (clean_agg_mb < -0.5 and clean_pass) else "REJECT"
    return {
        "residual_scale": scale,
        "agg_delta_mB": agg_mb,
        "clean_agg_delta_mB": clean_agg_mb,
        "worst_slate_mB": worst_mb,
        "clean_worst_slate_mB": clean_worst,
        "clean_verdict": clean_verdict,
        "folds": fold_rows,
    }


def summarize_date_policy(hit_arr, pforcal_arr, date_arr, dates, oof, fold_pred_map, default_scale: float, date_scales: dict[str, float]) -> dict:
    valid = ~np.isnan(oof)
    p_policy = pforcal_arr.copy()
    fold_rows = []
    for held in dates:
        test_mask = date_arr == held
        scale = float(date_scales.get(held, default_scale))
        pred = fold_pred_map[held]
        p_after = apply_residual(pforcal_arr[test_mask], pred, residual_scale=scale)
        p_policy[test_mask] = p_after
        b_before = brier(hit_arr[test_mask], pforcal_arr[test_mask])
        b_after = brier(hit_arr[test_mask], p_after)
        fold_rows.append(
            {
                "date": held,
                "n": int(test_mask.sum()),
                "residual_scale": scale,
                "brier_pforcal": b_before,
                "brier_after_cal": b_after,
                "delta_mB": (b_after - b_before) * 1000.0,
            }
        )

    b_pre = brier(hit_arr[valid], pforcal_arr[valid])
    b_post = brier(hit_arr[valid], p_policy[valid])
    agg_mb = (b_post - b_pre) * 1000.0

    clean = [r for r in fold_rows if r["date"] not in EXCLUDE_SLATES]
    clean_worst = max(r["delta_mB"] for r in clean)
    worst_mb = max(r["delta_mB"] for r in fold_rows)

    active_mask = np.isin(date_arr, list(set(dates) - EXCLUDE_SLATES))
    valid_clean = valid & active_mask
    b_clean_pre = brier(hit_arr[valid_clean], pforcal_arr[valid_clean])
    b_clean_post = brier(hit_arr[valid_clean], p_policy[valid_clean])
    clean_agg_mb = (b_clean_post - b_clean_pre) * 1000.0

    clean_pass = all(
        (r["delta_mB"] <= GATE_LARGE_MB if r["n"] >= SMALL_SLATE_THRESHOLD else r["delta_mB"] <= GATE_SMALL_MB)
        for r in clean
    )
    clean_verdict = "PROMOTE" if (clean_agg_mb < -0.5 and clean_pass) else "REJECT"
    return {
        "policy": "date_scale_override",
        "default_residual_scale": default_scale,
        "date_scales": date_scales,
        "agg_delta_mB": agg_mb,
        "clean_agg_delta_mB": clean_agg_mb,
        "worst_slate_mB": worst_mb,
        "clean_worst_slate_mB": clean_worst,
        "clean_verdict": clean_verdict,
        "folds": fold_rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Run v5cD iter600 LODO on a playoff resim cache.")
    ap.add_argument("--cache-path", default=str(CACHE_PATH), help="Input cache pickle path.")
    ap.add_argument("--out-path", default=str(OUT_PATH), help="Output JSON path.")
    ap.add_argument("--residual-scale", type=float, default=RESIDUAL_SCALE, help="Single residual scale to evaluate.")
    ap.add_argument("--residual-scales", nargs="*", help="Optional residual scale sweep, e.g. 0.45 0.40 0.35 0.30.")
    ap.add_argument(
        "--date-scales",
        nargs="*",
        help="Optional date-specific policy overrides, e.g. 2026-05-01=0.15 2026-05-05=0.15.",
    )
    args = ap.parse_args()
    residual_scales = parse_scales(args.residual_scales, args.residual_scale)
    primary_scale = residual_scales[0]
    date_scales = parse_date_scales(args.date_scales)

    cache_path = pathlib.Path(args.cache_path)
    if not cache_path.is_absolute():
        cache_path = ROOT / cache_path
    out_path = pathlib.Path(args.out_path)
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    print("=" * 80)
    print(f"v5c-D control: iter=600, lr=0.075, scales={residual_scales}, 19 features, clean-6")
    print("=" * 80)

    with open(V5B_PATH, "r") as f:
        v5b = json.load(f)
    features = v5b["v5b_features"]
    print(f"features ({len(features)}): {features}")
    print(f"clean-6 excludes: {sorted(EXCLUDE_SLATES)}")
    print()

    print(f"Loading cache: {cache_path}")
    with open(cache_path, "rb") as f:
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

    residual_tgt = hit_arr - pforcal_arr
    X_full, cat_in = prep_X(cv, features)
    oof = np.full(len(cv), np.nan)
    fold_rows = []
    fold_pred_map = {}

    t0 = time.time()
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

        m = CatBoostRegressor(**PARAMS)
        m.fit(train_pool, eval_set=eval_pool)
        pred = m.predict(test_pool)
        oof[test_mask] = pred
        fold_pred_map[held] = pred
        best_it = m.get_best_iteration()

        p_after  = apply_residual(pforcal_arr[test_mask], pred, residual_scale=primary_scale)
        b_before = brier(hit_arr[test_mask], pforcal_arr[test_mask])
        b_after  = brier(hit_arr[test_mask], p_after)
        delta_mb = (b_after - b_before) * 1000.0
        fold_rows.append({"date": held, "n": int(test_mask.sum()),
                           "brier_pforcal": b_before, "brier_after_cal": b_after,
                           "delta_mB": delta_mb, "best_iter": int(best_it)})
        scale_bits = []
        for scale in residual_scales:
            p_scaled = apply_residual(pforcal_arr[test_mask], pred, residual_scale=scale)
            d_scaled = (brier(hit_arr[test_mask], p_scaled) - b_before) * 1000.0
            scale_bits.append(f"s{scale:.2f}={d_scaled:+6.2f}mB")
        print(f"  {held}  n={int(test_mask.sum()):>5}  raw={b_before:.4f}  "
              f"cal@{primary_scale:.2f}={b_after:.4f}  {'  '.join(scale_bits)}  best_it={best_it}", flush=True)

    elapsed = time.time() - t0

    scale_results = [
        summarize_scale(hit_arr, pforcal_arr, date_arr, dates, oof, fold_pred_map, scale)
        for scale in residual_scales
    ]
    primary = scale_results[0]
    agg_mb = primary["agg_delta_mB"]
    clean_agg_mb = primary["clean_agg_delta_mB"]
    worst_mb = primary["worst_slate_mB"]
    clean_worst = primary["clean_worst_slate_mB"]
    clean_verdict = primary["clean_verdict"]

    print()
    print("=" * 80)
    print("RESULT")
    print("=" * 80)
    print(f"  primary scale = {primary_scale:.2f}")
    print(f"  agg (all)     = {agg_mb:+.2f} mB")
    print(f"  agg (clean)   = {clean_agg_mb:+.2f} mB")
    print(f"  worst (all)   = {worst_mb:+.2f} mB")
    print(f"  worst clean   = {clean_worst:+.2f} mB")
    print(f"  clean verdict = {clean_verdict}")
    print(f"  elapsed = {elapsed:.1f}s")
    print()
    if len(scale_results) > 1:
        print("Residual scale sweep:")
        print(f"  {'scale':>7} {'agg':>9} {'clean':>9} {'worst':>9} {'clean_w':>9} {'verdict':>10}")
        for result in scale_results:
            print(
                f"  {result['residual_scale']:>7.2f} "
                f"{result['agg_delta_mB']:>+9.2f} "
                f"{result['clean_agg_delta_mB']:>+9.2f} "
                f"{result['worst_slate_mB']:>+9.2f} "
                f"{result['clean_worst_slate_mB']:>+9.2f} "
                f"{result['clean_verdict']:>10}",
                flush=True,
            )
    policy_result = None
    if date_scales:
        policy_result = summarize_date_policy(
            hit_arr,
            pforcal_arr,
            date_arr,
            dates,
            oof,
            fold_pred_map,
            primary_scale,
            date_scales,
        )
        print()
        print("Date-specific residual scale policy:")
        print(f"  default scale = {primary_scale:.2f}")
        print(f"  overrides     = {date_scales}")
        print(f"  agg           = {policy_result['agg_delta_mB']:+.2f} mB")
        print(f"  clean agg     = {policy_result['clean_agg_delta_mB']:+.2f} mB")
        print(f"  worst         = {policy_result['worst_slate_mB']:+.2f} mB")
        print(f"  clean worst   = {policy_result['clean_worst_slate_mB']:+.2f} mB")
        print(f"  verdict       = {policy_result['clean_verdict']}")
        for row in policy_result["folds"]:
            if row["date"] in date_scales:
                print(
                    f"    {row['date']} scale={row['residual_scale']:.2f} "
                    f"d={row['delta_mB']:+.2f}mB",
                    flush=True,
                )

    # Compare to v5c-A
    if V5C_PATH.exists():
        with open(V5C_PATH, "r") as f:
            v5c = json.load(f)
        a = v5c["results"]["v5c-A_iter500_lr0075_scale050"]
        print("Comparison:")
        print(f"  {'config':<25} {'agg9':>8} {'agg6':>8} {'w9':>8} {'w6':>8} {'verdict':>10}")
        print(f"  {'v5c-A (iter500)':<25} {a['agg_delta_mB']:>+8.2f} "
              f"{a['clean_agg_delta_mB']:>+8.2f} {a['worst_slate_mB']:>+8.2f} "
              f"{a['clean_worst_slate_mB']:>+8.2f} {a['verdict_clean']:>10}")
        print(f"  {'v5c-D (iter600)':<25} {agg_mb:>+8.2f} "
              f"{clean_agg_mb:>+8.2f} {worst_mb:>+8.2f} "
              f"{clean_worst:>+8.2f} {clean_verdict:>10}")
        d_agg = clean_agg_mb - a["clean_agg_delta_mB"]
        d_worst = clean_worst - a["clean_worst_slate_mB"]
        print(f"  {'delta D-A':<25} {'':>8} {d_agg:>+8.2f} {'':>8} {d_worst:>+8.2f}")

    payload = {
        "config": {"iterations": 600, "learning_rate": 0.075,
                    "residual_scale": primary_scale, "residual_clip": 0.20,
                    "residual_scales": residual_scales},
        "cache_path": str(cache_path),
        "features": features,
        "exclude_slates_clean6": sorted(EXCLUDE_SLATES),
        "agg_delta_mB": agg_mb,
        "clean_agg_delta_mB": clean_agg_mb,
        "worst_slate_mB": worst_mb,
        "clean_worst_slate_mB": clean_worst,
        "clean_verdict": clean_verdict,
        "folds": fold_rows,
        "elapsed_sec": elapsed,
        "scale_results": scale_results,
        "date_scale_policy": policy_result,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"\nWrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
