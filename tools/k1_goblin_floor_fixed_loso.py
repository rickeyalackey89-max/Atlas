"""K1 — fixed-floor LOSO (no per-fold picker)."""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
OUT = ROOT / "data" / "model" / "k1_goblin_floor_fixed_loso.json"


def brier(y, p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return float(np.mean((p - y) ** 2))


def main() -> None:
    cv = pickle.load(open(CACHE, "rb"))["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)
    cv["date"] = cv["game_date"].astype(str).str[:10]
    cv["tier_u"] = cv["tier"].astype(str).str.upper().str.strip()
    cv["dir_u"] = cv["direction"].astype(str).str.upper().str.strip()
    p_arr = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1).to_numpy()
    h_arr = cv["hit"].astype(float).to_numpy()
    g_mask = ((cv["tier_u"] == "GOBLIN") & (cv["dir_u"] == "OVER")).to_numpy()
    dates = sorted(cv["date"].unique())

    print("=" * 90)
    print("K1 — FIXED FLOOR LOSO PER-SLATE TABLE")
    print("=" * 90)
    print(f"  N legs:       {len(cv):,}")
    print(f"  N GOBLIN OVR: {int(g_mask.sum()):,}")
    print()

    candidates = [0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
    by_floor: dict[str, dict] = {}
    for f in candidates:
        p_new = p_arr.copy()
        p_new[g_mask] = np.maximum(p_new[g_mask], f)
        rows = []
        for d in dates:
            test = (cv["date"].to_numpy() == d)
            b_b = brier(h_arr[test], p_arr[test])
            b_a = brier(h_arr[test], p_new[test])
            d_mb = (b_a - b_b) * 1000
            rows.append({
                "date": d, "n_test": int(test.sum()),
                "b_before": b_b, "b_after": b_a, "delta_mB": d_mb,
            })
        n_total = sum(r["n_test"] for r in rows)
        b_b_w = sum(r["b_before"] * r["n_test"] for r in rows) / n_total
        b_a_w = sum(r["b_after"] * r["n_test"] for r in rows) / n_total
        delta_total = (b_a_w - b_b_w) * 1000
        n_regress = sum(1 for r in rows if r["delta_mB"] > 1.0)
        worst = max((r["delta_mB"] for r in rows), default=0.0)
        verdict = "PROMOTE" if (delta_total < 0 and n_regress == 0) else "REJECT"
        by_floor[f"{f:.2f}"] = {
            "floor": f, "rows": rows,
            "agg_delta_mB": delta_total,
            "n_regress_gt_1mB": n_regress,
            "worst": worst, "verdict": verdict,
        }
        print(f"floor = {f:.2f}  agg {delta_total:+7.2f}mB  "
              f"regress {n_regress}/{len(rows)}  worst {worst:+.2f}mB  -> {verdict}")
        for r in rows:
            flag = " <-" if r["delta_mB"] > 1.0 else ""
            print(f"    {r['date']}: {r['delta_mB']:+7.2f}mB{flag}")
        print()

    out = {
        "version": "k1_goblin_floor_fixed_loso_v1",
        "n_goblin_over": int(g_mask.sum()),
        "by_floor": by_floor,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
