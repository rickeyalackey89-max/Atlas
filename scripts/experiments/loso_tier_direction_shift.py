"""
Leave-one-slate-out cross-validation for tier x direction logit shift.

For each date d in cache:
  fit deltas on cv[date != d]
  apply shifts to cv[date == d]
  measure brier_before / brier_after on that held-out date

If LOSO Brier improves AND no slate regresses materially, the shift generalizes.
If LOSO is positive on multiple slates, the in-sample fit was fitting noise.

Output: data/model/tier_dir_logit_shift_loso.json
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
OUT = ROOT / "data" / "model" / "tier_dir_logit_shift_loso.json"

SLICES = [("DEMON", "OVER"), ("GOBLIN", "OVER"),
          ("STANDARD", "OVER"), ("STANDARD", "UNDER")]


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def brier(y, p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return float(np.mean((p - y) ** 2))


def fit_delta(p_adj, hit):
    target = float(hit.mean())
    z = logit(p_adj)

    def f(d):
        return float(sigmoid(z + d).mean() - target)

    f_lo, f_hi = f(-5.0), f(5.0)
    if f_lo * f_hi > 0:
        return -5.0 if abs(f_lo) < abs(f_hi) else 5.0
    return float(brentq(f, -5.0, 5.0, xtol=1e-6))


def fit_all_deltas(df):
    """Fit deltas for all slices on a corpus subset."""
    out = {}
    for tier, direction in SLICES:
        m = (df["tier_u"] == tier) & (df["dir_u"] == direction)
        if m.sum() < 30:
            out[(tier, direction)] = 0.0
            continue
        out[(tier, direction)] = fit_delta(
            df.loc[m, "p_adj_f"].to_numpy(),
            df.loc[m, "hit_f"].to_numpy(),
        )
    return out


def apply_deltas(df, deltas):
    z = logit(df["p_adj_f"].to_numpy())
    delta_arr = np.zeros(len(df))
    for tier, direction in SLICES:
        m = ((df["tier_u"] == tier) & (df["dir_u"] == direction)).to_numpy()
        delta_arr[m] = deltas.get((tier, direction), 0.0)
    return sigmoid(z + delta_arr)


def main() -> None:
    print("=" * 90)
    print("LEAVE-ONE-SLATE-OUT CROSS-VALIDATION")
    print("=" * 90)

    cv = pickle.load(open(CACHE, "rb"))["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)
    cv["tier_u"] = cv["tier"].astype(str).str.upper().str.strip()
    cv["dir_u"] = cv["direction"].astype(str).str.upper().str.strip()
    cv["date"] = cv["game_date"].astype(str).str[:10]
    cv["p_adj_f"] = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1)
    cv["hit_f"] = cv["hit"].astype(float)

    dates = sorted(cv["date"].unique())
    print()
    print(f"  N dates: {len(dates)}")
    print(f"  N legs:  {len(cv):,}")
    print()

    # Fit on full corpus for reference
    full_deltas = fit_all_deltas(cv)
    print("FULL-CORPUS DELTAS (reference)")
    print("-" * 90)
    for (tier, direction), d in full_deltas.items():
        print(f"  {tier:<10} {direction:<6}  delta = {d:+.4f}")
    print()

    # LOSO loop
    print("LEAVE-ONE-SLATE-OUT")
    print("-" * 90)
    print(f"  {'held':<12} {'n':>6}  "
          f"{'B_before':>9} {'B_after':>9} {'delta':>8}  fitted-deltas")
    rows = []
    for d in dates:
        train = cv[cv["date"] != d]
        test = cv[cv["date"] == d]
        deltas = fit_all_deltas(train)
        p_shift = apply_deltas(test, deltas)
        h = test["hit_f"].to_numpy()
        b_before = brier(h, test["p_adj_f"].to_numpy())
        b_after = brier(h, p_shift)
        delta_mb = (b_after - b_before) * 1000
        flag = " <- REGRESS" if delta_mb > 1.0 else ""
        rows.append({
            "date": d, "n": int(len(test)),
            "b_before": b_before, "b_after": b_after, "delta_mB": delta_mb,
            "fitted_deltas": {f"{t}|{dr}": deltas[(t, dr)] for t, dr in SLICES},
        })
        d_str = ", ".join(f"{t[0]}{dr[0]}={deltas[(t, dr)]:+.3f}"
                          for t, dr in SLICES)
        print(f"  {d:<12} {len(test):>6}  "
              f"{b_before:>9.4f} {b_after:>9.4f} {delta_mb:>+7.2f}mB{flag}")
        print(f"             deltas: {d_str}")

    # Aggregate LOSO
    n_total = sum(r["n"] for r in rows)
    b_before_w = sum(r["b_before"] * r["n"] for r in rows) / n_total
    b_after_w = sum(r["b_after"] * r["n"] for r in rows) / n_total
    delta_total = (b_after_w - b_before_w) * 1000
    n_regress = sum(1 for r in rows if r["delta_mB"] > 1.0)
    worst_regress = max((r["delta_mB"] for r in rows), default=0.0)
    print()
    print("LOSO AGGREGATE")
    print("-" * 90)
    print(f"  N legs:                 {n_total:,}")
    print(f"  Brier before:           {b_before_w:.6f}")
    print(f"  Brier after:            {b_after_w:.6f}")
    print(f"  Delta:                  {delta_total:+.3f} mB")
    print(f"  Slates regressing >1mB: {n_regress} of {len(rows)}")
    print(f"  Worst slate regression: {worst_regress:+.2f} mB")

    out = {
        "version": "tier_dir_logit_shift_loso_v1",
        "n_dates": len(dates),
        "n_legs": int(n_total),
        "full_corpus_deltas": {f"{t}|{dr}": full_deltas[(t, dr)] for t, dr in SLICES},
        "loso_per_slate": rows,
        "loso_aggregate": {
            "brier_before": b_before_w,
            "brier_after": b_after_w,
            "delta_mB": delta_total,
            "n_slates_regress_gt_1mB": n_regress,
            "worst_slate_regression_mB": worst_regress,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print()
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
