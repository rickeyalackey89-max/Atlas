"""
Leave-one-slate-out cross-validation for high-probability shrinkage.

Audit finding (kernel_math_audit.json):
  Calibration gap is monotone-increasing for p_adj >= 0.70:
    [0.70,0.75): +3.0pp
    [0.75,0.80): +4.1pp
    [0.80,0.85): +8.5pp
    [0.85,0.90): +16.4pp

Lever (one parameter):
  For legs with p_adj > p_thr:
    z_thr = logit(p_thr)
    z     = logit(p_adj)
    p_new = sigmoid(z_thr + k * (z - z_thr))
  Else unchanged.
  k = 1.0  -> no change
  k < 1.0  -> shrink toward p_thr (de-confidence)
  k > 1.0  -> sharpen

Methodology:
  Sweep p_thr in {0.65, 0.70, 0.75}. For each, fit k* on full corpus
  (in-sample reference) and via LOSO (fit on N-1 dates, apply to held-out).
  Promote only if (a) LOSO aggregate Brier improves AND (b) zero slates
  regress > 1.0 mB.

Output: data/model/high_prob_shrink_loso.json
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
OUT = ROOT / "data" / "model" / "high_prob_shrink_loso.json"

THRESHOLDS = [0.65, 0.70, 0.75]


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def brier(y, p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return float(np.mean((p - y) ** 2))


def apply_shrink(p, p_thr, k):
    p = np.asarray(p, dtype=float)
    out = p.copy()
    mask = p > p_thr
    if not mask.any():
        return out
    z_thr = float(np.log(p_thr / (1 - p_thr)))
    z = logit(p[mask])
    out[mask] = sigmoid(z_thr + k * (z - z_thr))
    return out


def fit_k(p, hit, p_thr):
    """Find k* in [0.05, 1.5] that minimizes Brier."""
    def obj(k):
        return brier(hit, apply_shrink(p, p_thr, k))
    res = minimize_scalar(obj, bounds=(0.05, 1.5), method="bounded",
                          options={"xatol": 1e-4})
    return float(res.x), float(res.fun)


def show_bins(df, p_thr):
    edges = [p_thr, 0.75, 0.80, 0.85, 0.90, 0.95, 1.001]
    edges = sorted(set([e for e in edges if e >= p_thr]))
    p = df["p_adj_f"].to_numpy()
    h = df["hit_f"].to_numpy()
    print(f"  {'bin':<14} {'n':>6} {'mean_p':>8} {'hit':>8} {'gap_pp':>8}")
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi)
        if m.sum() < 1:
            continue
        gap = (h[m].mean() - p[m].mean()) * 100
        print(f"  [{lo:.2f},{hi:.2f}) {m.sum():>6} "
              f"{p[m].mean():>8.3f} {h[m].mean():>8.3f} {gap:>+7.2f}")


def main() -> None:
    print("=" * 90)
    print("HIGH-PROBABILITY SHRINKAGE — LOSO CROSS-VALIDATION")
    print("=" * 90)

    cv = pickle.load(open(CACHE, "rb"))["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)
    cv["date"] = cv["game_date"].astype(str).str[:10]
    cv["p_adj_f"] = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1)
    cv["hit_f"] = cv["hit"].astype(float)

    dates = sorted(cv["date"].unique())
    print()
    print(f"  N legs:  {len(cv):,}")
    print(f"  N dates: {len(dates)}")
    print()

    print("CALIBRATION BY BIN (p_adj)")
    print("-" * 90)
    show_bins(cv, 0.65)
    print()

    results_by_thr = {}
    for p_thr in THRESHOLDS:
        print("=" * 90)
        print(f"THRESHOLD p_thr = {p_thr:.2f}")
        print("=" * 90)
        n_above = int((cv["p_adj_f"] > p_thr).sum())
        print(f"  Legs with p_adj > {p_thr}: {n_above:,} ({n_above/len(cv)*100:.1f}%)")
        print()

        # Full-corpus fit (reference)
        k_full, _ = fit_k(
            cv["p_adj_f"].to_numpy(),
            cv["hit_f"].to_numpy(),
            p_thr,
        )
        b_before_full = brier(cv["hit_f"].to_numpy(), cv["p_adj_f"].to_numpy())
        b_after_full = brier(
            cv["hit_f"].to_numpy(),
            apply_shrink(cv["p_adj_f"].to_numpy(), p_thr, k_full),
        )
        print(f"  Full-corpus  k* = {k_full:.4f}   "
              f"B {b_before_full:.6f} -> {b_after_full:.6f}  "
              f"({(b_after_full - b_before_full)*1000:+.2f} mB)")
        print()

        # LOSO
        print(f"  {'held':<12} {'n':>6} {'k_train':>8} "
              f"{'B_before':>9} {'B_after':>9} {'delta_mB':>9}")
        rows = []
        for d in dates:
            train = cv[cv["date"] != d]
            test = cv[cv["date"] == d]
            k_train, _ = fit_k(
                train["p_adj_f"].to_numpy(),
                train["hit_f"].to_numpy(),
                p_thr,
            )
            p_test = test["p_adj_f"].to_numpy()
            h_test = test["hit_f"].to_numpy()
            p_shifted = apply_shrink(p_test, p_thr, k_train)
            b_before = brier(h_test, p_test)
            b_after = brier(h_test, p_shifted)
            d_mb = (b_after - b_before) * 1000
            flag = " <- REGRESS" if d_mb > 1.0 else ""
            rows.append({
                "date": d, "n": int(len(test)),
                "k_train": k_train,
                "b_before": b_before, "b_after": b_after,
                "delta_mB": d_mb,
            })
            print(f"  {d:<12} {len(test):>6} {k_train:>8.4f} "
                  f"{b_before:>9.4f} {b_after:>9.4f} {d_mb:>+8.2f}mB{flag}")

        n_total = sum(r["n"] for r in rows)
        b_b = sum(r["b_before"] * r["n"] for r in rows) / n_total
        b_a = sum(r["b_after"] * r["n"] for r in rows) / n_total
        delta_total = (b_a - b_b) * 1000
        n_regress = sum(1 for r in rows if r["delta_mB"] > 1.0)
        worst = max((r["delta_mB"] for r in rows), default=0.0)
        verdict = ("PROMOTE" if (delta_total < 0 and n_regress == 0)
                   else "REJECT")
        print()
        print(f"  LOSO aggregate: B {b_b:.6f} -> {b_a:.6f}  "
              f"({delta_total:+.2f} mB)")
        print(f"  Slates regressing >1mB: {n_regress} of {len(rows)}  "
              f"(worst {worst:+.2f} mB)")
        print(f"  Verdict: {verdict}")
        print()

        results_by_thr[f"{p_thr:.2f}"] = {
            "p_thr": p_thr,
            "n_above": n_above,
            "k_full_corpus": k_full,
            "b_full_before": b_before_full,
            "b_full_after": b_after_full,
            "delta_full_mB": (b_after_full - b_before_full) * 1000,
            "loso_per_slate": rows,
            "loso_aggregate": {
                "brier_before": b_b,
                "brier_after": b_a,
                "delta_mB": delta_total,
                "n_slates_regress_gt_1mB": n_regress,
                "worst_slate_regression_mB": worst,
            },
            "verdict": verdict,
        }

    out = {
        "version": "high_prob_shrink_loso_v1",
        "n_dates": len(dates),
        "n_legs": int(len(cv)),
        "thresholds": results_by_thr,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
