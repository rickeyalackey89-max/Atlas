"""Raw-chain diagnostic on the playoff resim cache.

Two complementary tests evaluated on truth-backed legs (`hit` column):

  TEST 1  Chain stage ablation
          Compute Brier at every chain stage and per-stage delta vs the
          previous stage.  A POSITIVE delta means the stage HURTS on this
          corpus; a NEGATIVE delta means it HELPS.  Reported aggregate +
          per-slate + per-stat + per-tier + per-direction.

  TEST 2  Kernel feature residual bias
          Bin every kernel context feature into 5 quintiles and measure
          (mean_hit - mean_p_for_cal) within each bin.
              * monotonic + wide range  -> feature is UNDER-USED
              * flat                     -> NEUTRAL on this corpus
              * U / non-monotonic        -> NOISY / over-trusted

Outputs:
    data/model/kernel_chain_diagnostic.json
    data/model/kernel_chain_diagnostic_run.log  (tee from caller)
"""

from __future__ import annotations
import json, pickle
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(r"C:\Users\13142\Atlas\NBA")
CACHE = REPO / "data/model/_v1_playoff_resim_cache.pkl"
OUT_JSON = REPO / "data/model/kernel_chain_diagnostic.json"

CHAIN = ["p", "p_role", "p_adj_pre_under_relief", "p_adj", "p_for_cal", "p_cal"]

# Kernel-stage context features to probe.  Restricted to columns produced by
# or consumed by the kernel (NOT GBM-only features like player_te etc).
KERNEL_FEATURES = [
    "q_blowout", "fragility", "usage_dep", "minutes_s",
    "role_ctx_mult", "role_ctx_outs_used",
    "margin", "spread", "game_total_norm",
    "min_cv", "min_sensitivity", "tail_risk", "rate_cv",
    "is_star",
]


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def _stage_brier_table(df: pd.DataFrame) -> dict:
    """Brier per stage + delta vs previous stage."""
    y = df["hit"].astype(float).to_numpy()
    out = []
    prev = None
    for stage in CHAIN:
        if stage not in df.columns:
            continue
        p = df[stage].astype(float).to_numpy()
        b = brier(p, y)
        d_prev = None if prev is None else (b - prev) * 1000.0
        out.append({"stage": stage, "brier": b, "delta_mB_vs_prev": d_prev})
        prev = b
    return out


def _grouped_chain(df: pd.DataFrame, group_col: str) -> dict:
    """Per-group chain Brier."""
    rows = []
    for g, sub in df.groupby(group_col):
        if len(sub) < 50:
            continue
        rec = {"group": str(g), "n": int(len(sub))}
        y = sub["hit"].astype(float).to_numpy()
        for stage in CHAIN:
            if stage in sub.columns:
                rec[stage] = brier(sub[stage].astype(float).to_numpy(), y)
        rows.append(rec)
    return rows


def _residual_quintile_table(df: pd.DataFrame, feat: str, ref_stage: str = "p_for_cal") -> dict:
    """Bin feature into 5 quantile buckets, report per-bin mean(hit-p)."""
    if feat not in df.columns:
        return None
    s = df[feat].astype(float)
    valid = s.notna() & df[ref_stage].notna() & df["hit"].notna()
    if int(valid.sum()) < 200:
        return None
    sub = df.loc[valid, [feat, ref_stage, "hit"]].copy()
    # If feature is binary or has few uniques, just split on uniques (cap to 5).
    nunq = sub[feat].nunique()
    if nunq <= 5:
        bins = sorted(sub[feat].unique())
        sub["_bin"] = sub[feat]
        bin_labels = [str(b) for b in bins]
    else:
        try:
            sub["_bin"] = pd.qcut(sub[feat], q=5, duplicates="drop", labels=False)
        except ValueError:
            return None
        bin_labels = None

    rows = []
    for b, g in sub.groupby("_bin"):
        n = len(g)
        if n < 20:
            continue
        mean_p = float(g[ref_stage].mean())
        mean_hit = float(g["hit"].mean())
        rows.append({
            "bin": (bin_labels[int(b)] if bin_labels else int(b)),
            "n": int(n),
            "feat_lo": float(g[feat].min()),
            "feat_hi": float(g[feat].max()),
            "feat_mean": float(g[feat].mean()),
            "mean_p": mean_p,
            "mean_hit": mean_hit,
            "bias_mB": (mean_hit - mean_p) * 1000.0,
        })
    if len(rows) < 2:
        return None
    biases = [r["bias_mB"] for r in rows]
    rng = max(biases) - min(biases)
    # Monotonicity: count sign changes in successive diffs.
    diffs = np.diff(biases)
    sign_changes = int(np.sum(np.sign(diffs[:-1]) * np.sign(diffs[1:]) < 0)) if len(diffs) >= 2 else 0
    if sign_changes == 0 and rng >= 20:
        verdict = "UNDER-USED (monotonic, wide)"
    elif sign_changes == 0 and rng >= 10:
        verdict = "mild signal (monotonic)"
    elif rng < 10:
        verdict = "neutral"
    elif sign_changes >= 2:
        verdict = "NOISY (multi-sign-change)"
    else:
        verdict = "ambiguous"
    return {
        "feature": feat,
        "n_used": int(valid.sum()),
        "bin_count": len(rows),
        "bias_range_mB": rng,
        "sign_changes": sign_changes,
        "verdict": verdict,
        "bins": rows,
    }


def main():
    print("=== Kernel Chain Diagnostic ===")
    print(f"Cache: {CACHE}")
    cv = pickle.load(open(CACHE, "rb"))["cv"]
    print(f"  legs={len(cv):,}  dates={cv['game_date'].nunique()}")
    print(f"  hit_rate={cv['hit'].mean():.4f}")
    print()

    # === TEST 1: Stage ablation ===
    print("--- TEST 1: Chain stage Brier (aggregate) ---")
    agg = _stage_brier_table(cv)
    print(f"{'stage':<26} {'brier':>10}  {'d_prev_mB':>10}")
    for r in agg:
        d = "" if r["delta_mB_vs_prev"] is None else f"{r['delta_mB_vs_prev']:+.2f}"
        print(f"{r['stage']:<26} {r['brier']:>10.6f}  {d:>10}")
    print()

    print("--- TEST 1b: Per-slate stage Brier ---")
    per_slate = _grouped_chain(cv, "game_date")
    if per_slate:
        head = ["date", "n"] + CHAIN
        print(" | ".join(f"{h:<14}" for h in head[:5]) + " ...")
        for rec in per_slate:
            cells = [str(rec["group"])[:10], str(rec["n"])]
            for s in CHAIN:
                v = rec.get(s)
                cells.append(f"{v:.4f}" if v is not None else "--")
            print(" | ".join(f"{c:<14}" for c in cells))
    print()

    print("--- TEST 1c: Per-stat stage Brier ---")
    per_stat = _grouped_chain(cv, "stat")
    for rec in per_stat:
        cells = [str(rec["group"])[:14], str(rec["n"])]
        for s in CHAIN:
            v = rec.get(s)
            cells.append(f"{v:.4f}" if v is not None else "--")
        print(" | ".join(f"{c:<14}" for c in cells))
    print()

    print("--- TEST 1d: Per-tier stage Brier ---")
    if "tier" in cv.columns:
        per_tier = _grouped_chain(cv, "tier")
        for rec in per_tier:
            cells = [str(rec["group"]), str(rec["n"])]
            for s in CHAIN:
                v = rec.get(s)
                cells.append(f"{v:.4f}" if v is not None else "--")
            print(" | ".join(f"{c:<14}" for c in cells))
    else:
        per_tier = []
    print()

    print("--- TEST 1e: Per-direction stage Brier ---")
    if "direction" in cv.columns:
        per_dir = _grouped_chain(cv, "direction")
        for rec in per_dir:
            cells = [str(rec["group"]), str(rec["n"])]
            for s in CHAIN:
                v = rec.get(s)
                cells.append(f"{v:.4f}" if v is not None else "--")
            print(" | ".join(f"{c:<14}" for c in cells))
    else:
        per_dir = []
    print()

    # === TEST 2: Kernel feature residual bias ===
    print("--- TEST 2: Kernel feature residual bias (vs p_for_cal) ---")
    feature_results = []
    for feat in KERNEL_FEATURES:
        rec = _residual_quintile_table(cv, feat, ref_stage="p_for_cal")
        if rec is None:
            print(f"  {feat:<24} SKIP (insufficient data)")
            continue
        feature_results.append(rec)
        print(f"  {feat:<24} range={rec['bias_range_mB']:+6.1f}mB  signs={rec['sign_changes']}  -> {rec['verdict']}")

    print()
    print("--- TEST 2 detail (worst-bias features) ---")
    feature_results_sorted = sorted(feature_results, key=lambda r: -r["bias_range_mB"])
    for rec in feature_results_sorted[:6]:
        print(f"\n  [{rec['feature']}]  range={rec['bias_range_mB']:.2f}mB  -> {rec['verdict']}")
        print(f"  {'bin':<8} {'n':>6} {'feat_mean':>12} {'mean_p':>10} {'mean_hit':>10} {'bias_mB':>10}")
        for b in rec["bins"]:
            print(f"  {str(b['bin']):<8} {b['n']:>6} {b['feat_mean']:>12.4f} {b['mean_p']:>10.4f} {b['mean_hit']:>10.4f} {b['bias_mB']:>10.2f}")

    # === Summary ===
    print()
    print("=== HEADLINE SUMMARY ===")
    print()
    print("Stage transitions (positive = stage HURT, negative = stage HELPED):")
    for r in agg:
        if r["delta_mB_vs_prev"] is None:
            continue
        flag = "  <-- HURTS" if r["delta_mB_vs_prev"] > 0.5 else ("  helps" if r["delta_mB_vs_prev"] < -0.5 else "")
        print(f"  -> {r['stage']:<24} {r['delta_mB_vs_prev']:+.2f} mB{flag}")
    print()
    under_used = [r for r in feature_results if "UNDER-USED" in r["verdict"]]
    noisy = [r for r in feature_results if "NOISY" in r["verdict"]]
    print(f"Under-used features (potential lift): {len(under_used)}")
    for r in under_used:
        print(f"  - {r['feature']:<24} bias_range={r['bias_range_mB']:+.1f} mB")
    print(f"Noisy features (potential drag): {len(noisy)}")
    for r in noisy:
        print(f"  - {r['feature']:<24} sign_changes={r['sign_changes']}  range={r['bias_range_mB']:.1f} mB")

    # Persist
    payload = {
        "cache": str(CACHE),
        "n_legs": int(len(cv)),
        "n_dates": int(cv["game_date"].nunique()),
        "stage_brier_aggregate": agg,
        "stage_brier_per_slate": per_slate,
        "stage_brier_per_stat": per_stat,
        "stage_brier_per_tier": per_tier,
        "stage_brier_per_direction": per_dir,
        "feature_residuals": feature_results,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"\nWrote: {OUT_JSON}")


if __name__ == "__main__":
    main()

