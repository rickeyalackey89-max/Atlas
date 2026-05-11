"""
Diagnostic: quantify the engine fork bug at src/Atlas/engine/main.py:911.

Production fork:   p_for_cal = where(role_ctx_outs_used > 0, p_role, p_adj)
Proposed fix:      p_for_cal = p_adj  (universally)

Computes Brier(p_for_cal_prod) vs Brier(p_for_cal_fix) on the playoff resim
cache, overall and on the use_role=True subset where the fork actually fires.
"""
from __future__ import annotations
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path("data/model/_v1_playoff_resim_cache.pkl")
OUT = Path("data/model/engine_fork_diagnostic.json")


def brier(p, y) -> float:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, dtype=float)
    return float(np.mean((p - y) ** 2))


def main() -> None:
    with CACHE.open("rb") as f:
        cache = pickle.load(f)
    cv: pd.DataFrame = cache["cv"].copy()

    # Required columns
    for col in ("p_adj", "p_role", "role_ctx_outs_used", "hit", "game_date"):
        if col not in cv.columns:
            raise SystemExit(f"missing column: {col}")

    cv["use_role"] = (pd.to_numeric(cv["role_ctx_outs_used"], errors="coerce").fillna(0) > 0).astype(int)
    p_adj = pd.to_numeric(cv["p_adj"], errors="coerce").fillna(0.5).clip(0, 1)
    p_role = pd.to_numeric(cv["p_role"], errors="coerce").fillna(p_adj).clip(0, 1)
    hit = pd.to_numeric(cv["hit"], errors="coerce").fillna(0).astype(int)

    # Production fork (current main.py:911 behavior)
    p_for_cal_prod = np.where(cv["use_role"].astype(bool), p_role, p_adj)
    # Proposed fix (cache-side has used this all along)
    p_for_cal_fix = p_adj.values

    n = len(cv)
    n_use_role = int(cv["use_role"].sum())
    pct_use_role = 100.0 * n_use_role / n

    overall = {
        "n_legs": n,
        "n_use_role_legs": n_use_role,
        "pct_use_role": round(pct_use_role, 2),
        "brier_prod_fork": brier(p_for_cal_prod, hit),
        "brier_fix_padj": brier(p_for_cal_fix, hit),
        "delta_mB_fix_minus_prod": (brier(p_for_cal_fix, hit) - brier(p_for_cal_prod, hit)) * 1000.0,
    }

    # Subset: only legs where the fork fires
    mask_role = cv["use_role"].astype(bool).values
    if mask_role.sum() > 0:
        sub_prod = brier(p_for_cal_prod[mask_role], hit.values[mask_role])
        sub_fix = brier(p_for_cal_fix[mask_role], hit.values[mask_role])
        sub_p = brier(p_adj.values[mask_role], hit.values[mask_role])
        sub_proll = brier(p_role.values[mask_role], hit.values[mask_role])
        use_role_only = {
            "n_legs": int(mask_role.sum()),
            "brier_p_role": sub_proll,
            "brier_p_adj": sub_p,
            "brier_prod_fork": sub_prod,
            "brier_fix_padj": sub_fix,
            "delta_mB_fix_minus_prod": (sub_fix - sub_prod) * 1000.0,
        }
    else:
        use_role_only = {"n_legs": 0}

    # Per-slate breakdown
    per_slate = []
    for date, grp in cv.groupby("game_date"):
        m = grp["use_role"].astype(bool).values
        h = pd.to_numeric(grp["hit"], errors="coerce").fillna(0).astype(int).values
        pa_s = pd.to_numeric(grp["p_adj"], errors="coerce").fillna(0.5).clip(0, 1)
        pr_s = pd.to_numeric(grp["p_role"], errors="coerce").clip(0, 1)
        pr_s = pr_s.fillna(pa_s)
        pa = pa_s.values
        pr = pr_s.values
        prod = np.where(m, pr, pa)
        per_slate.append({
            "date": str(date),
            "n_legs": int(len(grp)),
            "n_use_role": int(m.sum()),
            "brier_prod_fork": brier(prod, h),
            "brier_fix_padj": brier(pa, h),
            "delta_mB_fix_minus_prod": (brier(pa, h) - brier(prod, h)) * 1000.0,
        })

    out = {
        "cache_path": str(CACHE),
        "overall": overall,
        "use_role_only": use_role_only,
        "per_slate": per_slate,
        "interpretation": {
            "negative_delta": "fix improves Brier (lower is better)",
            "positive_delta": "fix regresses Brier vs production fork",
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2))

    print("=" * 70)
    print("ENGINE FORK DIAGNOSTIC (main.py:911)")
    print("=" * 70)
    print(f"Total legs:        {overall['n_legs']:,}")
    print(f"use_role legs:     {overall['n_use_role_legs']:,}  ({overall['pct_use_role']:.2f}%)")
    print()
    print(f"Brier(prod_fork):  {overall['brier_prod_fork']:.6f}")
    print(f"Brier(fix=p_adj):  {overall['brier_fix_padj']:.6f}")
    print(f"Delta (fix-prod):  {overall['delta_mB_fix_minus_prod']:+.3f} mB")
    print()
    print("--- use_role=True subset only ---")
    if use_role_only["n_legs"] > 0:
        print(f"  n:                 {use_role_only['n_legs']:,}")
        print(f"  Brier(p_role):     {use_role_only['brier_p_role']:.6f}")
        print(f"  Brier(p_adj):      {use_role_only['brier_p_adj']:.6f}")
        print(f"  Delta (adj-role):  {(use_role_only['brier_p_adj']-use_role_only['brier_p_role'])*1000:+.3f} mB")
    print()
    print("--- per-slate ---")
    print(f"{'date':<12}  {'n':>6}  {'n_role':>6}  {'prod':>10}  {'fix':>10}  {'delta_mB':>9}")
    for s in per_slate:
        print(f"{s['date']:<12}  {s['n_legs']:>6}  {s['n_use_role']:>6}  "
              f"{s['brier_prod_fork']:>10.6f}  {s['brier_fix_padj']:>10.6f}  "
              f"{s['delta_mB_fix_minus_prod']:>+9.3f}")
    print()
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
