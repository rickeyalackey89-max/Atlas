"""
Generic LOSO subset logit-shift validator.

For a named subset (filter mask), fit a single logit shift delta on N-1 dates
and apply on the held-out date. Promote only if LOSO aggregate Brier improves
AND zero slates regress > 1.0 mB.

Subsets handled:
  B  under         direction == UNDER
  C  combo         stat in {RA, PA, PRA}  (per-stat sub-fits also reported)
  D  role_on       role_ctx_outs_used > 0
  E  goblin_over   tier == GOBLIN AND direction == OVER

Usage:
  python tools\\loso_subset_shift.py <subset_name>

Output:
  data/model/loso_subset_shift_<subset_name>.json
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq, minimize_scalar

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def brier(y, p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return float(np.mean((p - y) ** 2))


def fit_delta_brier(p, hit):
    """Find delta in [-3, 3] minimizing brier on this subset."""
    z = logit(p)

    def obj(d):
        return brier(hit, sigmoid(z + d))

    res = minimize_scalar(obj, bounds=(-3.0, 3.0), method="bounded",
                          options={"xatol": 1e-4})
    return float(res.x), float(res.fun)


def get_mask(cv: pd.DataFrame, name: str) -> np.ndarray:
    name = name.lower()
    if name == "under":
        return (cv["dir_u"] == "UNDER").to_numpy()
    if name == "combo":
        return cv["stat_u"].isin(["RA", "PA", "PRA"]).to_numpy()
    if name == "role_on":
        ru = pd.to_numeric(cv.get("role_ctx_outs_used", 0),
                           errors="coerce").fillna(0)
        return (ru > 0).to_numpy()
    if name == "goblin_over":
        return ((cv["tier_u"] == "GOBLIN") & (cv["dir_u"] == "OVER")).to_numpy()
    raise ValueError(f"Unknown subset: {name}")


def main(subset: str) -> None:
    print("=" * 90)
    print(f"LOSO SUBSET LOGIT-SHIFT — subset = {subset}")
    print("=" * 90)

    cv = pickle.load(open(CACHE, "rb"))["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)
    cv["date"] = cv["game_date"].astype(str).str[:10]
    cv["tier_u"] = cv["tier"].astype(str).str.upper().str.strip()
    cv["dir_u"] = cv["direction"].astype(str).str.upper().str.strip()
    cv["stat_u"] = cv["stat"].astype(str).str.upper().str.strip()
    cv["p_adj_f"] = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1)
    cv["hit_f"] = cv["hit"].astype(float)

    mask = get_mask(cv, subset)
    n_sub = int(mask.sum())
    n_total = len(cv)
    print(f"  N total:  {n_total:,}")
    print(f"  N subset: {n_sub:,} ({n_sub/n_total*100:.1f}%)")
    print(f"  hit_rate(subset): {cv.loc[mask, 'hit_f'].mean():.4f}")
    print(f"  mean_p(subset):   {cv.loc[mask, 'p_adj_f'].mean():.4f}")
    print(f"  gap (pp):         "
          f"{(cv.loc[mask, 'hit_f'].mean() - cv.loc[mask, 'p_adj_f'].mean())*100:+.2f}")
    print()

    # Full corpus reference
    delta_full, _ = fit_delta_brier(
        cv.loc[mask, "p_adj_f"].to_numpy(),
        cv.loc[mask, "hit_f"].to_numpy(),
    )
    p_new_full = cv["p_adj_f"].to_numpy().copy()
    p_new_full[mask] = sigmoid(logit(p_new_full[mask]) + delta_full)
    b_b_full = brier(cv["hit_f"].to_numpy(), cv["p_adj_f"].to_numpy())
    b_a_full = brier(cv["hit_f"].to_numpy(), p_new_full)
    print(f"  Full-corpus delta = {delta_full:+.4f}   "
          f"B {b_b_full:.6f} -> {b_a_full:.6f}  "
          f"({(b_a_full - b_b_full) * 1000:+.2f} mB)")
    print()

    # LOSO
    dates = sorted(cv["date"].unique())
    print("LEAVE-ONE-SLATE-OUT")
    print("-" * 90)
    print(f"  {'held':<12} {'n':>6} {'n_sub':>6} {'delta':>8} "
          f"{'B_before':>9} {'B_after':>9} {'delta_mB':>9}")
    rows = []
    for d in dates:
        train_mask_full = cv["date"].to_numpy() != d
        sub_train = mask & train_mask_full
        if sub_train.sum() < 30:
            continue
        delta, _ = fit_delta_brier(
            cv.loc[sub_train, "p_adj_f"].to_numpy(),
            cv.loc[sub_train, "hit_f"].to_numpy(),
        )
        test_mask = cv["date"].to_numpy() == d
        p_new = cv["p_adj_f"].to_numpy().copy()
        affected = test_mask & mask
        p_new[affected] = sigmoid(logit(p_new[affected]) + delta)
        h_test = cv.loc[test_mask, "hit_f"].to_numpy()
        b_b = brier(h_test, cv.loc[test_mask, "p_adj_f"].to_numpy())
        b_a = brier(h_test, p_new[test_mask])
        d_mb = (b_a - b_b) * 1000
        flag = " <- REGRESS" if d_mb > 1.0 else ""
        rows.append({
            "date": d,
            "n_test": int(test_mask.sum()),
            "n_test_sub": int(affected.sum()),
            "delta": delta,
            "b_before": b_b,
            "b_after": b_a,
            "delta_mB": d_mb,
        })
        print(f"  {d:<12} {test_mask.sum():>6} {affected.sum():>6} "
              f"{delta:>+8.4f} {b_b:>9.4f} {b_a:>9.4f} {d_mb:>+8.2f}mB{flag}")

    n_total_loso = sum(r["n_test"] for r in rows)
    b_b_w = sum(r["b_before"] * r["n_test"] for r in rows) / n_total_loso
    b_a_w = sum(r["b_after"] * r["n_test"] for r in rows) / n_total_loso
    delta_total = (b_a_w - b_b_w) * 1000
    n_regress = sum(1 for r in rows if r["delta_mB"] > 1.0)
    worst = max((r["delta_mB"] for r in rows), default=0.0)
    verdict = "PROMOTE" if (delta_total < 0 and n_regress == 0) else "REJECT"

    print()
    print(f"  LOSO aggregate: B {b_b_w:.6f} -> {b_a_w:.6f}  "
          f"({delta_total:+.2f} mB)")
    print(f"  Slates regressing >1mB: {n_regress} of {len(rows)}  "
          f"(worst {worst:+.2f} mB)")
    print(f"  Verdict: {verdict}")

    out = {
        "version": "loso_subset_shift_v1",
        "subset": subset,
        "n_subset": n_sub,
        "n_total": n_total,
        "delta_full_corpus": delta_full,
        "b_full_before": b_b_full,
        "b_full_after": b_a_full,
        "delta_full_mB": (b_a_full - b_b_full) * 1000,
        "loso_per_slate": rows,
        "loso_aggregate": {
            "brier_before": b_b_w,
            "brier_after": b_a_w,
            "delta_mB": delta_total,
            "n_slates_regress_gt_1mB": n_regress,
            "worst_slate_regression_mB": worst,
        },
        "verdict": verdict,
    }
    out_path = ROOT / "data" / "model" / f"loso_subset_shift_{subset}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: loso_subset_shift.py <under|combo|role_on|goblin_over>")
        sys.exit(1)
    main(sys.argv[1])
