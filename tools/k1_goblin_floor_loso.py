"""
K1 — LOSO sweep of GOBLIN OVER probability floor.

Bias is concentrated in q1_low quintile (model 0.163, actual 0.501 -> +33.85 pp).
Lever: for GOBLIN OVER legs only, p_adj_new = max(p_adj, p_floor).

Sweep p_floor in {0.30, 0.35, 0.40, 0.45, 0.50}.
Promote only if LOSO aggregate Brier improves AND zero slates regress >1mB.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
OUT = ROOT / "data" / "model" / "k1_goblin_floor_loso.json"


def brier(y, p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return float(np.mean((p - y) ** 2))


def apply_floor(p, mask, floor):
    out = np.asarray(p, dtype=float).copy()
    out[mask] = np.maximum(out[mask], floor)
    return out


def fit_best_floor(p, hit, mask, candidates):
    """Pick floor that minimizes Brier on training mask."""
    best_floor, best_b = candidates[0], float("inf")
    for f in candidates:
        b = brier(hit, apply_floor(p, mask, f))
        if b < best_b:
            best_b, best_floor = b, f
    return best_floor, best_b


def main() -> None:
    print("=" * 90)
    print("K1 — GOBLIN OVER PROBABILITY FLOOR — LOSO")
    print("=" * 90)

    cv = pickle.load(open(CACHE, "rb"))["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)
    cv["date"] = cv["game_date"].astype(str).str[:10]
    cv["tier_u"] = cv["tier"].astype(str).str.upper().str.strip()
    cv["dir_u"] = cv["direction"].astype(str).str.upper().str.strip()
    cv["p_adj_f"] = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1)
    cv["hit_f"] = cv["hit"].astype(float)

    g_mask = ((cv["tier_u"] == "GOBLIN") & (cv["dir_u"] == "OVER")).to_numpy()
    n_g = int(g_mask.sum())
    print(f"  N total:       {len(cv):,}")
    print(f"  N GOBLIN OVER: {n_g:,} ({n_g/len(cv)*100:.1f}%)")
    print()

    candidates = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55]
    dates = sorted(cv["date"].unique())

    # Full-corpus reference per floor
    print("FULL-CORPUS REFERENCE")
    print("-" * 90)
    print(f"  {'p_floor':>8} {'B_before':>9} {'B_after':>9} {'delta_mB':>9}")
    p_arr = cv["p_adj_f"].to_numpy()
    h_arr = cv["hit_f"].to_numpy()
    b_baseline = brier(h_arr, p_arr)
    full_results = {}
    for f in candidates:
        b_after = brier(h_arr, apply_floor(p_arr, g_mask, f))
        d_mb = (b_after - b_baseline) * 1000
        full_results[f"{f:.2f}"] = {"b_before": b_baseline, "b_after": b_after,
                                     "delta_mB": d_mb}
        print(f"  {f:>8.2f} {b_baseline:>9.6f} {b_after:>9.6f} {d_mb:>+8.2f}mB")
    print()

    # LOSO: pick best floor on N-1 dates, apply on held-out
    print("LOSO (pick-best per train fold)")
    print("-" * 90)
    print(f"  {'held':<12} {'n':>6} {'n_g':>5} {'floor':>6} "
          f"{'B_before':>9} {'B_after':>9} {'delta_mB':>9}")
    rows = []
    for d in dates:
        train = cv["date"].to_numpy() != d
        test = ~train
        floor_best, _ = fit_best_floor(
            p_arr[train], h_arr[train], g_mask[train], candidates,
        )
        p_test_new = apply_floor(p_arr[test], g_mask[test], floor_best)
        b_b = brier(h_arr[test], p_arr[test])
        b_a = brier(h_arr[test], p_test_new)
        d_mb = (b_a - b_b) * 1000
        flag = " <- REGRESS" if d_mb > 1.0 else ""
        rows.append({
            "date": d, "n_test": int(test.sum()),
            "n_g_test": int((g_mask & test).sum()),
            "floor_train": floor_best,
            "b_before": b_b, "b_after": b_a, "delta_mB": d_mb,
        })
        print(f"  {d:<12} {test.sum():>6} {(g_mask & test).sum():>5} "
              f"{floor_best:>6.2f} {b_b:>9.4f} {b_a:>9.4f} {d_mb:>+8.2f}mB{flag}")

    n_total = sum(r["n_test"] for r in rows)
    b_b_w = sum(r["b_before"] * r["n_test"] for r in rows) / n_total
    b_a_w = sum(r["b_after"] * r["n_test"] for r in rows) / n_total
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
        "version": "k1_goblin_floor_loso_v1",
        "n_goblin_over": n_g,
        "candidates": candidates,
        "full_corpus": full_results,
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
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
