"""
Fit per-(tier, direction) logit-shift to close calibration gaps in p_adj.

Model:  p_shifted = sigmoid(logit(p_adj) + delta[(tier, direction)])

Fit:    delta solved by 1D root-find so that mean(p_shifted) == mean(hit)
        on cache slice (the right loss for closing calibration gap).

Validate:
  - Per-(tier, direction) slice gap drops to <=2 pp.
  - Per-slate Brier non-regressive (every slate).
  - Aggregate Brier improves.

Output: data/model/tier_dir_logit_shift.json
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
OUT = ROOT / "data" / "model" / "tier_dir_logit_shift.json"


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def brier(y, p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return float(np.mean((p - y) ** 2))


def fit_delta(p_adj, hit):
    """Solve delta s.t. mean(sigmoid(logit(p)+delta)) == mean(hit)."""
    target = float(hit.mean())
    z = logit(p_adj)

    def f(d):
        return float(sigmoid(z + d).mean() - target)

    # Bracket: f is monotone increasing in delta
    lo, hi = -5.0, 5.0
    f_lo, f_hi = f(lo), f(hi)
    if f_lo * f_hi > 0:
        # No sign change in bracket — return clamped end
        return lo if abs(f_lo) < abs(f_hi) else hi
    return float(brentq(f, lo, hi, xtol=1e-6))


def main() -> None:
    print("=" * 90)
    print("TIER x DIRECTION LOGIT-SHIFT FITTER")
    print("=" * 90)

    cache = pickle.load(open(CACHE, "rb"))
    cv = cache["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)

    cv["tier_u"] = cv["tier"].astype(str).str.upper().str.strip()
    cv["dir_u"] = cv["direction"].astype(str).str.upper().str.strip()
    cv["date"] = cv["game_date"].astype(str).str[:10]
    cv["p_adj_f"] = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1)
    cv["hit_f"] = cv["hit"].astype(float)

    # Identify slices to fit (only valid tier x direction combos that exist in cache)
    print()
    print("STEP 1: Identify slices")
    print("-" * 90)
    slices = []
    for (tier, direction), grp in cv.groupby(["tier_u", "dir_u"]):
        if len(grp) < 50:
            continue
        slices.append((tier, direction, len(grp)))
        print(f"  {tier:<10} {direction:<6}  n={len(grp):,}")

    # Step 2: Fit delta for each slice
    print()
    print("STEP 2: Fit delta per slice")
    print("-" * 90)
    print(f"  {'tier':<10} {'dir':<6} {'n':>6} {'mean(p)':>9} {'hit':>9} {'gap':>7} -> {'delta':>8}")
    deltas = {}
    for tier, direction, n in slices:
        m = (cv["tier_u"] == tier) & (cv["dir_u"] == direction)
        p = cv.loc[m, "p_adj_f"].to_numpy()
        h = cv.loc[m, "hit_f"].to_numpy()
        d = fit_delta(p, h)
        deltas[f"{tier}|{direction}"] = d
        print(f"  {tier:<10} {direction:<6} {n:>6} {p.mean():>9.4f} {h.mean():>9.4f} "
              f"{(p.mean() - h.mean()) * 100:>+6.2f}pp -> {d:>+8.4f}")

    # Step 3: Apply shifts and recompute
    print()
    print("STEP 3: Apply shifts -> p_shifted")
    print("-" * 90)
    z = logit(cv["p_adj_f"].to_numpy())
    delta_arr = np.zeros(len(cv))
    for tier, direction, _ in slices:
        m = ((cv["tier_u"] == tier) & (cv["dir_u"] == direction)).to_numpy()
        delta_arr[m] = deltas[f"{tier}|{direction}"]
    p_shift = sigmoid(z + delta_arr)
    cv["p_shift"] = p_shift

    # Step 4: Calibration check
    print()
    print("STEP 4: Calibration check (per slice)")
    print("-" * 90)
    print(f"  {'tier':<10} {'dir':<6} {'n':>6} "
          f"{'mean(p_adj)':>12} {'mean(p_shift)':>14} {'mean(hit)':>10} "
          f"{'gap_before':>11} {'gap_after':>10}")
    slice_results = []
    for tier, direction, _ in slices:
        m = (cv["tier_u"] == tier) & (cv["dir_u"] == direction)
        p_old = cv.loc[m, "p_adj_f"].to_numpy()
        p_new = cv.loc[m, "p_shift"].to_numpy()
        h = cv.loc[m, "hit_f"].to_numpy()
        gap_before = (p_old.mean() - h.mean()) * 100
        gap_after = (p_new.mean() - h.mean()) * 100
        b_before = brier(h, p_old)
        b_after = brier(h, p_new)
        slice_results.append({
            "tier": tier, "direction": direction, "n": int(m.sum()),
            "mean_p_adj": float(p_old.mean()), "mean_p_shift": float(p_new.mean()),
            "mean_hit": float(h.mean()),
            "gap_before_pp": gap_before, "gap_after_pp": gap_after,
            "brier_before": b_before, "brier_after": b_after,
            "delta_mB": (b_after - b_before) * 1000,
        })
        print(f"  {tier:<10} {direction:<6} {int(m.sum()):>6} "
              f"{p_old.mean():>12.4f} {p_new.mean():>14.4f} {h.mean():>10.4f} "
              f"{gap_before:>+10.2f}pp {gap_after:>+9.2f}pp")

    # Step 5: Per-slate Brier (must be non-regressive)
    print()
    print("STEP 5: Per-slate Brier (non-regression gate)")
    print("-" * 90)
    print(f"  {'date':<12} {'n':>6} {'B(p_adj)':>10} {'B(p_shift)':>11} {'delta_mB':>10}")
    per_slate = []
    any_regress = False
    for date, grp in cv.groupby("date"):
        h = grp["hit_f"].to_numpy()
        b_before = brier(h, grp["p_adj_f"].to_numpy())
        b_after = brier(h, grp["p_shift"].to_numpy())
        delta = (b_after - b_before) * 1000
        per_slate.append({"date": date, "n": int(len(grp)),
                           "b_before": b_before, "b_after": b_after,
                           "delta_mB": delta})
        flag = " <- REGRESS" if delta > 1.0 else ""
        if delta > 1.0:
            any_regress = True
        print(f"  {date:<12} {len(grp):>6} {b_before:>10.4f} {b_after:>11.4f} {delta:>+9.2f}mB{flag}")

    # Step 6: Aggregate
    h_all = cv["hit_f"].to_numpy()
    b_before = brier(h_all, cv["p_adj_f"].to_numpy())
    b_after = brier(h_all, cv["p_shift"].to_numpy())
    print()
    print("STEP 6: Aggregate Brier")
    print("-" * 90)
    print(f"  Before (p_adj):    {b_before:.6f}")
    print(f"  After  (p_shift):  {b_after:.6f}")
    print(f"  Delta:             {(b_after - b_before) * 1000:+.3f} mB  (negative = improvement)")
    print()
    print(f"  Per-slate regression detected: {any_regress}")

    # Save
    out = {
        "version": "tier_dir_logit_shift_v1",
        "trained_on": "data/model/_v1_playoff_resim_cache.pkl",
        "n_legs": int(len(cv)),
        "deltas": deltas,
        "slice_results": slice_results,
        "per_slate": per_slate,
        "aggregate": {
            "brier_before": b_before,
            "brier_after": b_after,
            "delta_mB": (b_after - b_before) * 1000,
        },
        "any_slate_regression": bool(any_regress),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print()
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
