"""
K4 — blowout bypass at tails.

Diagnostic showed blowout adjustment hurts at q_blowout < ~0.15 (+0.58 mB)
and q_blowout > ~0.50 (+1.98 mB) but helps strongly in the middle.

Lever: replace p_adj with p_role (pre-blowout) in tail slices.
  for q in [q_lo_test_max, q_hi_test_min]: use p_adj (current)
  outside that band: use p_role

Sweep q_lo in {0.10, 0.15, 0.20} and q_hi in {0.40, 0.50, 0.60, 0.70}.
LOSO per-slate non-regression gate.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
OUT = ROOT / "data" / "model" / "k4_blowout_bypass_loso.json"


def brier(y, p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return float(np.mean((p - y) ** 2))


def main() -> None:
    cv = pickle.load(open(CACHE, "rb"))["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)
    cv["date"] = cv["game_date"].astype(str).str[:10]
    p_adj = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1).to_numpy()
    p_role = pd.to_numeric(cv["p_role"], errors="coerce").fillna(0.5).clip(0, 1).to_numpy()
    h = cv["hit"].astype(float).to_numpy()
    q = pd.to_numeric(cv["q_blowout"], errors="coerce").fillna(0.0).to_numpy()
    dates = sorted(cv["date"].unique())

    # Baseline
    print("=" * 90)
    print("K4 — BLOWOUT TAIL BYPASS — LOSO")
    print("=" * 90)
    print(f"  N legs: {len(cv):,}")
    print(f"  Baseline B(p_adj) = {brier(h, p_adj):.6f}")
    print(f"  B(p_role) on full corpus = {brier(h, p_role):.6f}")
    print()

    candidates = [
        (0.10, 0.50), (0.10, 0.60), (0.10, 0.70),
        (0.15, 0.50), (0.15, 0.60), (0.15, 0.70),
        (0.20, 0.50), (0.20, 0.60), (0.20, 0.70),
    ]
    by_band = {}
    for q_lo, q_hi in candidates:
        in_band = (q >= q_lo) & (q < q_hi)
        p_new = np.where(in_band, p_adj, p_role)
        rows = []
        for d in dates:
            test = (cv["date"].to_numpy() == d)
            b_b = brier(h[test], p_adj[test])
            b_a = brier(h[test], p_new[test])
            d_mb = (b_a - b_b) * 1000
            rows.append({"date": d, "n": int(test.sum()),
                         "n_bypass": int(((~in_band) & test).sum()),
                         "b_before": b_b, "b_after": b_a, "delta_mB": d_mb})
        n_total = sum(r["n"] for r in rows)
        b_b_w = sum(r["b_before"] * r["n"] for r in rows) / n_total
        b_a_w = sum(r["b_after"] * r["n"] for r in rows) / n_total
        delta_total = (b_a_w - b_b_w) * 1000
        n_regress = sum(1 for r in rows if r["delta_mB"] > 1.0)
        worst = max((r["delta_mB"] for r in rows), default=0.0)
        verdict = "PROMOTE" if (delta_total < 0 and n_regress == 0) else "REJECT"
        n_bypass_total = int(((~in_band)).sum())
        by_band[f"{q_lo}_{q_hi}"] = {
            "q_lo": q_lo, "q_hi": q_hi,
            "n_bypass": n_bypass_total,
            "rows": rows,
            "agg_delta_mB": delta_total,
            "n_regress_gt_1mB": n_regress,
            "worst": worst, "verdict": verdict,
        }
        print(f"keep band [{q_lo:.2f},{q_hi:.2f})   "
              f"bypass {n_bypass_total:>5}  "
              f"agg {delta_total:+7.2f}mB  "
              f"regress {n_regress}/9  worst {worst:+.2f}mB  -> {verdict}")
        for r in rows:
            flag = " <-" if r["delta_mB"] > 1.0 else ""
            print(f"    {r['date']}: {r['delta_mB']:+7.2f}mB{flag}")
        print()

    out = {
        "version": "k4_blowout_bypass_loso_v1",
        "by_band": by_band,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
