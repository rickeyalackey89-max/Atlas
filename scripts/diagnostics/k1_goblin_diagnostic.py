"""
K1 — GOBLIN under-prediction diagnostic.

Hypothesis: the kernel under-shoots GOBLIN OVER hits because the line is set
materially below the model's expected value, but the kernel does not model
the "line discount" relationship. Slice the calibration gap by line_dist
(line / mean_proj or similar) AND tier and look for a clean bias contour.

Outputs:
  data/model/k1_goblin_diagnostic.json
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
OUT = ROOT / "data" / "model" / "k1_goblin_diagnostic.json"


def main() -> None:
    print("=" * 90)
    print("K1 — GOBLIN UNDER-PREDICTION DIAGNOSTIC")
    print("=" * 90)

    cv = pickle.load(open(CACHE, "rb"))["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)
    cv["tier_u"] = cv["tier"].astype(str).str.upper().str.strip()
    cv["dir_u"] = cv["direction"].astype(str).str.upper().str.strip()
    cv["stat_u"] = cv["stat"].astype(str).str.upper().str.strip()
    cv["p_adj_f"] = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1)
    cv["p_f"] = pd.to_numeric(cv["p"], errors="coerce").fillna(0.5).clip(0, 1)
    cv["hit_f"] = cv["hit"].astype(float)
    cv["line_dist_f"] = pd.to_numeric(cv["line_dist"], errors="coerce")
    cv["line_norm_f"] = pd.to_numeric(cv["line_norm"], errors="coerce")
    cv["line_f"] = pd.to_numeric(cv["line"], errors="coerce")

    # 1. Tier × line_dist contour
    print()
    print("TIER x LINE_DIST  (line_dist = line / per-min-rate * minutes_s ratio)")
    print("-" * 90)
    cv["ld_bin"] = pd.cut(
        cv["line_dist_f"],
        bins=[-np.inf, 0.7, 0.85, 0.95, 1.05, 1.15, 1.30, np.inf],
        labels=["<0.70", "[0.70,0.85)", "[0.85,0.95)", "[0.95,1.05)",
                "[1.05,1.15)", "[1.15,1.30)", ">=1.30"],
    )
    rows_grid = []
    for tier in ["GOBLIN", "STANDARD", "DEMON"]:
        for ldb in cv["ld_bin"].cat.categories:
            m = (cv["tier_u"] == tier) & (cv["ld_bin"] == ldb) & (cv["dir_u"] == "OVER")
            n = int(m.sum())
            if n < 30:
                continue
            mp = float(cv.loc[m, "p_adj_f"].mean())
            mh = float(cv.loc[m, "hit_f"].mean())
            gap = (mh - mp) * 100
            rows_grid.append({
                "tier": tier, "ld_bin": str(ldb), "n": n,
                "mean_p_adj": mp, "hit_rate": mh, "gap_pp": gap,
            })
    print(f"  {'tier':<10} {'ld_bin':<14} {'n':>5} {'mean_p':>8} {'hit':>8} {'gap':>8}")
    for r in rows_grid:
        print(f"  {r['tier']:<10} {r['ld_bin']:<14} {r['n']:>5} "
              f"{r['mean_p_adj']:>8.3f} {r['hit_rate']:>8.3f} {r['gap_pp']:>+7.2f}")

    # 2. Tier × stat (where does the GOBLIN bias concentrate?)
    print()
    print("GOBLIN OVER by stat")
    print("-" * 90)
    rows_stat = []
    g_over = (cv["tier_u"] == "GOBLIN") & (cv["dir_u"] == "OVER")
    for stat in sorted(cv.loc[g_over, "stat_u"].unique()):
        m = g_over & (cv["stat_u"] == stat)
        n = int(m.sum())
        if n < 50:
            continue
        mp = float(cv.loc[m, "p_adj_f"].mean())
        mh = float(cv.loc[m, "hit_f"].mean())
        gap = (mh - mp) * 100
        rows_stat.append({
            "stat": stat, "n": n,
            "mean_p_adj": mp, "hit_rate": mh, "gap_pp": gap,
        })
    print(f"  {'stat':<8} {'n':>5} {'mean_p':>8} {'hit':>8} {'gap':>8}")
    for r in rows_stat:
        print(f"  {r['stat']:<8} {r['n']:>5} "
              f"{r['mean_p_adj']:>8.3f} {r['hit_rate']:>8.3f} {r['gap_pp']:>+7.2f}")

    # 3. GOBLIN OVER by raw p tier (is bias bigger when model is more confident?)
    print()
    print("GOBLIN OVER by mean_p_adj quintile")
    print("-" * 90)
    g_idx = cv.index[g_over]
    if len(g_idx) >= 5:
        cv.loc[g_idx, "_pq"] = pd.qcut(
            cv.loc[g_idx, "p_adj_f"], 5,
            labels=["q1_low", "q2", "q3", "q4", "q5_high"],
            duplicates="drop",
        )
        print(f"  {'q':<10} {'n':>5} {'mean_p':>8} {'hit':>8} {'gap':>8}")
        for q in ["q1_low", "q2", "q3", "q4", "q5_high"]:
            m = g_over & (cv["_pq"] == q)
            n = int(m.sum())
            if n < 30:
                continue
            mp = float(cv.loc[m, "p_adj_f"].mean())
            mh = float(cv.loc[m, "hit_f"].mean())
            gap = (mh - mp) * 100
            print(f"  {q:<10} {n:>5} {mp:>8.3f} {mh:>8.3f} {gap:>+7.2f}")

    # 4. Estimate a GOBLIN OVER residual rate-bump
    # Model: rate' = rate * f(stat) where f minimizes Brier on GOBLIN OVER subset.
    # Approximation: shift in logit space. Per-stat fit.
    print()
    print("PER-STAT GOBLIN OVER LOGIT SHIFT (full corpus reference)")
    print("-" * 90)
    print(f"  {'stat':<8} {'n':>5} {'delta':>8} {'B_before':>9} {'B_after':>9}")
    rows_shift = []
    for stat in sorted(cv.loc[g_over, "stat_u"].unique()):
        m = g_over & (cv["stat_u"] == stat)
        if m.sum() < 50:
            continue
        p = cv.loc[m, "p_adj_f"].to_numpy()
        h = cv.loc[m, "hit_f"].to_numpy()
        from scipy.optimize import minimize_scalar
        z = np.log(np.clip(p, 1e-6, 1-1e-6) / np.clip(1-p, 1e-6, 1-1e-6))
        def obj(d):
            pn = 1.0 / (1.0 + np.exp(-(z + d)))
            return float(np.mean((pn - h) ** 2))
        res = minimize_scalar(obj, bounds=(-2.0, 2.0), method="bounded",
                              options={"xatol": 1e-4})
        d_opt = float(res.x)
        b0 = float(np.mean((p - h) ** 2))
        pn = 1.0 / (1.0 + np.exp(-(z + d_opt)))
        b1 = float(np.mean((pn - h) ** 2))
        rows_shift.append({"stat": stat, "n": int(m.sum()),
                           "delta": d_opt, "b_before": b0, "b_after": b1})
        print(f"  {stat:<8} {m.sum():>5} {d_opt:>+8.4f} {b0:>9.4f} {b1:>9.4f}")

    out = {
        "version": "k1_goblin_diagnostic_v1",
        "n_goblin_over": int(g_over.sum()),
        "tier_x_line_dist": rows_grid,
        "goblin_over_by_stat": rows_stat,
        "per_stat_logit_shift": rows_shift,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print()
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
