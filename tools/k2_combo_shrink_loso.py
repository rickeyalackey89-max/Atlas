"""
K2 — LOSO sweep of combo-stat logit shrinkage toward 0.5.

Audit pattern (data/model/kernel_math_audit.json):
  Combo stats (RA/PA/PRA/PR) under-estimate variance:
    OVER  mean_p < 0.5, hit > mean_p (+pp gap)
    UNDER mean_p > 0.5, hit < mean_p (-pp gap)

Symmetric lever:
  For combo legs only: p_new = sigmoid(k * logit(p))
  k=1.0  -> identity
  k<1    -> shrinks toward 0.5 (variance inflation effect)

Sweep k in {0.50, 0.60, 0.70, 0.80, 0.90}. Promote only if 0/9 slates regress >1mB.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
OUT = ROOT / "data" / "model" / "k2_combo_shrink_loso.json"

COMBO_STATS = ["RA", "PA", "PRA", "PR"]


def brier(y, p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return float(np.mean((p - y) ** 2))


def shrink_to_half(p, k):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    z = np.log(p / (1 - p))
    return 1.0 / (1.0 + np.exp(-k * z))


def main() -> None:
    cv = pickle.load(open(CACHE, "rb"))["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)
    cv["date"] = cv["game_date"].astype(str).str[:10]
    cv["stat_u"] = cv["stat"].astype(str).str.upper().str.strip()
    p_arr = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1).to_numpy()
    h_arr = cv["hit"].astype(float).to_numpy()
    c_mask = cv["stat_u"].isin(COMBO_STATS).to_numpy()
    dates = sorted(cv["date"].unique())

    print("=" * 90)
    print("K2 — COMBO LOGIT SHRINK TOWARD 0.5 — LOSO PER-SLATE")
    print("=" * 90)
    print(f"  N legs:       {len(cv):,}")
    print(f"  N combo:      {int(c_mask.sum()):,} ({c_mask.mean()*100:.1f}%)")
    print(f"  combo stats:  {COMBO_STATS}")
    print()

    candidates = [0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
    by_k = {}
    for k in candidates:
        p_new = p_arr.copy()
        p_new[c_mask] = shrink_to_half(p_new[c_mask], k)
        rows = []
        for d in dates:
            test = (cv["date"].to_numpy() == d)
            b_b = brier(h_arr[test], p_arr[test])
            b_a = brier(h_arr[test], p_new[test])
            d_mb = (b_a - b_b) * 1000
            rows.append({"date": d, "n": int(test.sum()),
                         "b_before": b_b, "b_after": b_a, "delta_mB": d_mb})
        n_total = sum(r["n"] for r in rows)
        b_b_w = sum(r["b_before"] * r["n"] for r in rows) / n_total
        b_a_w = sum(r["b_after"] * r["n"] for r in rows) / n_total
        delta_total = (b_a_w - b_b_w) * 1000
        n_regress = sum(1 for r in rows if r["delta_mB"] > 1.0)
        worst = max((r["delta_mB"] for r in rows), default=0.0)
        verdict = "PROMOTE" if (delta_total < 0 and n_regress == 0) else "REJECT"
        by_k[f"{k:.2f}"] = {
            "k": k, "rows": rows,
            "agg_delta_mB": delta_total,
            "n_regress_gt_1mB": n_regress,
            "worst": worst, "verdict": verdict,
        }
        print(f"k = {k:.2f}  agg {delta_total:+7.2f}mB  "
              f"regress {n_regress}/{len(rows)}  worst {worst:+.2f}mB  -> {verdict}")
        for r in rows:
            flag = " <-" if r["delta_mB"] > 1.0 else ""
            print(f"    {r['date']}: {r['delta_mB']:+7.2f}mB{flag}")
        print()

    out = {
        "version": "k2_combo_shrink_loso_v1",
        "n_combo": int(c_mask.sum()),
        "combo_stats": COMBO_STATS,
        "by_k": by_k,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
