"""
Kernel-side math audit.

Goal: trace `p` -> `p_role` -> `p_adj` and identify where the kernel
systematically over/under-shoots reality, by slate, stat, direction, tier,
blowout regime, role-context regime, and probability tier.

The calibrator is downstream of all this. If the kernel itself has biased
slices, the calibrator can only correct after the fact. The right fix is
to find those biases and adjust kernel parameters (rate/minute scaling,
blowout curve, role context, under-relief, fragility) at the source.

Output: data/model/kernel_math_audit.json
        data/model/kernel_math_audit.log
"""
from __future__ import annotations

import json
import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
OUT = ROOT / "data" / "model" / "kernel_math_audit.json"


def brier(y, p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, dtype=float)
    return float(np.mean((p - y) ** 2))


def calib_gap(y, p):
    """Mean(p) - Mean(y). Positive = kernel over-predicts, negative = under-predicts."""
    return float(np.mean(p) - np.mean(y))


def num(s, default=0.0):
    return pd.to_numeric(s, errors="coerce").fillna(default)


def slice_diag(df, mask, label):
    """Compute brier + calib gap for each kernel stage on a slice."""
    if mask.sum() < 30:
        return None
    sub = df[mask]
    h = sub["hit"].astype(float).to_numpy()
    out = {"label": label, "n": int(mask.sum()), "hit_rate": float(h.mean())}
    for stage in ("p", "p_role", "p_adj_pre_under_relief", "p_adj"):
        if stage in sub.columns:
            p = num(sub[stage]).clip(0, 1).to_numpy()
            out[f"brier_{stage}"] = brier(h, p)
            out[f"gap_{stage}_pct"] = round(calib_gap(h, p) * 100, 2)
    return out


def main() -> None:
    print("=" * 90)
    print("KERNEL MATH AUDIT")
    print("=" * 90)
    with open(CACHE, "rb") as f:
        cache = pickle.load(f)
    cv = cache["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)

    cv["use_role"] = (num(cv.get("role_ctx_outs_used", 0)) > 0).astype(int)
    cv["under_relief"] = num(cv.get("under_relief_applied", 0)).astype(int)
    cv["dir_u"] = cv["direction"].astype(str).str.upper().str.strip()
    cv["stat_u"] = cv["stat"].astype(str).str.upper().str.strip()
    cv["tier_u"] = cv["tier"].astype(str).str.upper().str.strip()
    cv["date"] = cv["game_date"].astype(str).str[:10]

    h = cv["hit"].astype(float).to_numpy()
    n = len(cv)

    # =============== Stage-by-stage Brier + calib gap (CORPUS) ===============
    print()
    print("CORPUS-LEVEL CHAIN (n={:,})".format(n))
    print("-" * 90)
    print(f"  {'stage':<28} {'brier':>10} {'gap_pct':>10}    {'mean(p)':>10} {'mean(hit)':>10}")
    chain_corpus = {}
    for stage in ("p", "p_role", "p_adj_pre_under_relief", "p_adj"):
        if stage in cv.columns:
            p = num(cv[stage]).clip(0, 1).to_numpy()
            b = brier(h, p)
            g = calib_gap(h, p) * 100
            chain_corpus[stage] = {"brier": b, "gap_pct": g, "mean_p": float(p.mean())}
            print(f"  {stage:<28} {b:>10.6f} {g:>+10.3f}    {p.mean():>10.4f} {h.mean():>10.4f}")
    base_hit = float(h.mean())
    print()
    print(f"  Base hit rate: {base_hit:.4f}")
    print()

    # =============== Per-slate chain ===============
    print("PER-SLATE CHAIN (delta = p_adj_brier - p_brier, negative = layers help)")
    print("-" * 90)
    print(f"  {'date':<12} {'n':>6} {'hit':>7}  {'B(p)':>9} {'B(p_role)':>10} {'B(p_adj)':>10}  {'gap(p)':>8} {'gap(adj)':>8}")
    per_slate = []
    for date, grp in cv.groupby("date"):
        gh = grp["hit"].astype(float).to_numpy()
        d = {"date": date, "n": int(len(grp)), "hit_rate": float(gh.mean())}
        for stage in ("p", "p_role", "p_adj"):
            p = num(grp[stage]).clip(0, 1).to_numpy()
            d[f"b_{stage}"] = brier(gh, p)
            d[f"gap_{stage}"] = calib_gap(gh, p) * 100
        per_slate.append(d)
        print(f"  {date:<12} {d['n']:>6} {d['hit_rate']:>7.3f}  "
              f"{d['b_p']:>9.4f} {d['b_p_role']:>10.4f} {d['b_p_adj']:>10.4f}  "
              f"{d['gap_p']:>+8.2f} {d['gap_p_adj']:>+8.2f}")

    # =============== Per-stat chain (corpus) ===============
    print()
    print("PER-STAT CHAIN (corpus, sorted by n)")
    print("-" * 90)
    print(f"  {'stat':<8} {'n':>6} {'hit':>7}  {'B(p)':>9} {'B(p_adj)':>10}  {'gap(p)':>8} {'gap(adj)':>8} {'delta':>9}")
    per_stat = []
    for stat, grp in cv.groupby("stat_u"):
        if len(grp) < 100:
            continue
        gh = grp["hit"].astype(float).to_numpy()
        bp = brier(gh, num(grp["p"]).clip(0, 1).to_numpy())
        ba = brier(gh, num(grp["p_adj"]).clip(0, 1).to_numpy())
        gp = calib_gap(gh, num(grp["p"]).clip(0, 1).to_numpy()) * 100
        ga = calib_gap(gh, num(grp["p_adj"]).clip(0, 1).to_numpy()) * 100
        per_stat.append({"stat": stat, "n": int(len(grp)), "hit_rate": float(gh.mean()),
                          "b_p": bp, "b_p_adj": ba, "gap_p": gp, "gap_p_adj": ga,
                          "delta_mB": (ba - bp) * 1000})
    per_stat.sort(key=lambda r: -r["n"])
    for r in per_stat:
        print(f"  {r['stat']:<8} {r['n']:>6} {r['hit_rate']:>7.3f}  "
              f"{r['b_p']:>9.4f} {r['b_p_adj']:>10.4f}  "
              f"{r['gap_p']:>+8.2f} {r['gap_p_adj']:>+8.2f} {r['delta_mB']:>+9.2f}mB")

    # =============== Direction split ===============
    print()
    print("DIRECTION SPLIT")
    print("-" * 90)
    direction_split = []
    for d in ("OVER", "UNDER"):
        m = cv["dir_u"] == d
        if m.sum() == 0: continue
        gh = cv.loc[m, "hit"].astype(float).to_numpy()
        bp = brier(gh, num(cv.loc[m, "p"]).clip(0, 1).to_numpy())
        ba = brier(gh, num(cv.loc[m, "p_adj"]).clip(0, 1).to_numpy())
        gp = calib_gap(gh, num(cv.loc[m, "p"]).clip(0, 1).to_numpy()) * 100
        ga = calib_gap(gh, num(cv.loc[m, "p_adj"]).clip(0, 1).to_numpy()) * 100
        direction_split.append({"direction": d, "n": int(m.sum()), "hit": float(gh.mean()),
                                "b_p": bp, "b_p_adj": ba, "gap_p": gp, "gap_p_adj": ga})
        print(f"  {d:<6} n={int(m.sum()):>6}  hit={gh.mean():.3f}  "
              f"B(p)={bp:.4f} B(p_adj)={ba:.4f}  gap(p)={gp:+.2f}  gap(adj)={ga:+.2f}  "
              f"delta={(ba - bp) * 1000:+.2f}mB")

    # =============== Tier split ===============
    print()
    print("TIER SPLIT")
    print("-" * 90)
    tier_split = []
    for t in ("STANDARD", "GOBLIN", "DEMON"):
        m = cv["tier_u"] == t
        if m.sum() == 0: continue
        gh = cv.loc[m, "hit"].astype(float).to_numpy()
        bp = brier(gh, num(cv.loc[m, "p"]).clip(0, 1).to_numpy())
        ba = brier(gh, num(cv.loc[m, "p_adj"]).clip(0, 1).to_numpy())
        gp = calib_gap(gh, num(cv.loc[m, "p"]).clip(0, 1).to_numpy()) * 100
        ga = calib_gap(gh, num(cv.loc[m, "p_adj"]).clip(0, 1).to_numpy()) * 100
        tier_split.append({"tier": t, "n": int(m.sum()), "hit": float(gh.mean()),
                            "b_p": bp, "b_p_adj": ba, "gap_p": gp, "gap_p_adj": ga})
        print(f"  {t:<10} n={int(m.sum()):>6}  hit={gh.mean():.3f}  "
              f"B(p)={bp:.4f} B(p_adj)={ba:.4f}  gap(p)={gp:+.2f}  gap(adj)={ga:+.2f}")

    # =============== Blowout regime ===============
    print()
    print("BLOWOUT REGIME (q_blowout buckets)")
    print("-" * 90)
    qb = num(cv["q_blowout"]).to_numpy()
    blowout_split = []
    for lo, hi, lbl in [(0.0, 0.10, "low"), (0.10, 0.30, "mid_lo"),
                         (0.30, 0.50, "mid_hi"), (0.50, 1.01, "high")]:
        m = (qb >= lo) & (qb < hi)
        if m.sum() < 30: continue
        gh = cv.loc[m, "hit"].astype(float).to_numpy()
        bp = brier(gh, num(cv.loc[m, "p"]).clip(0, 1).to_numpy())
        ba = brier(gh, num(cv.loc[m, "p_adj"]).clip(0, 1).to_numpy())
        gp = calib_gap(gh, num(cv.loc[m, "p"]).clip(0, 1).to_numpy()) * 100
        ga = calib_gap(gh, num(cv.loc[m, "p_adj"]).clip(0, 1).to_numpy()) * 100
        delta_mb = (ba - bp) * 1000
        blowout_split.append({"bucket": lbl, "range": f"[{lo:.2f},{hi:.2f})",
                               "n": int(m.sum()), "hit": float(gh.mean()),
                               "b_p": bp, "b_p_adj": ba, "gap_p": gp, "gap_p_adj": ga,
                               "delta_mB": delta_mb})
        print(f"  {lbl:<8} q_b in [{lo:.2f},{hi:.2f}) n={int(m.sum()):>5}  hit={gh.mean():.3f}  "
              f"B(p)={bp:.4f} B(adj)={ba:.4f}  gap(p)={gp:+.2f} gap(adj)={ga:+.2f}  delta={delta_mb:+.2f}mB")

    # =============== Role context regime ===============
    print()
    print("ROLE CONTEXT REGIME")
    print("-" * 90)
    role_split = []
    for r, lbl in [(0, "role_off"), (1, "role_on")]:
        m = cv["use_role"] == r
        if m.sum() == 0: continue
        gh = cv.loc[m, "hit"].astype(float).to_numpy()
        bp = brier(gh, num(cv.loc[m, "p"]).clip(0, 1).to_numpy())
        br = brier(gh, num(cv.loc[m, "p_role"]).clip(0, 1).to_numpy())
        ba = brier(gh, num(cv.loc[m, "p_adj"]).clip(0, 1).to_numpy())
        gp = calib_gap(gh, num(cv.loc[m, "p"]).clip(0, 1).to_numpy()) * 100
        gr = calib_gap(gh, num(cv.loc[m, "p_role"]).clip(0, 1).to_numpy()) * 100
        ga = calib_gap(gh, num(cv.loc[m, "p_adj"]).clip(0, 1).to_numpy()) * 100
        role_split.append({"label": lbl, "n": int(m.sum()), "hit": float(gh.mean()),
                            "b_p": bp, "b_p_role": br, "b_p_adj": ba,
                            "gap_p": gp, "gap_p_role": gr, "gap_p_adj": ga})
        print(f"  {lbl:<10} n={int(m.sum()):>5}  hit={gh.mean():.3f}  "
              f"B(p)={bp:.4f} B(role)={br:.4f} B(adj)={ba:.4f}  "
              f"gap(p)={gp:+.2f} gap(role)={gr:+.2f} gap(adj)={ga:+.2f}")

    # =============== Under-relief regime ===============
    print()
    print("UNDER-RELIEF REGIME (UNDER legs only)")
    print("-" * 90)
    relief_split = []
    cv_under = cv[cv["dir_u"] == "UNDER"]
    for r, lbl in [(0, "no_relief"), (1, "relief_applied")]:
        m = cv_under["under_relief"] == r
        if m.sum() == 0: continue
        gh = cv_under.loc[m, "hit"].astype(float).to_numpy()
        b_pre = brier(gh, num(cv_under.loc[m, "p_adj_pre_under_relief"]).clip(0, 1).to_numpy())
        b_post = brier(gh, num(cv_under.loc[m, "p_adj"]).clip(0, 1).to_numpy())
        g_pre = calib_gap(gh, num(cv_under.loc[m, "p_adj_pre_under_relief"]).clip(0, 1).to_numpy()) * 100
        g_post = calib_gap(gh, num(cv_under.loc[m, "p_adj"]).clip(0, 1).to_numpy()) * 100
        relief_split.append({"label": lbl, "n": int(m.sum()), "hit": float(gh.mean()),
                              "b_pre": b_pre, "b_post": b_post,
                              "gap_pre": g_pre, "gap_post": g_post,
                              "delta_mB": (b_post - b_pre) * 1000})
        print(f"  {lbl:<16} n={int(m.sum()):>5}  hit={gh.mean():.3f}  "
              f"B(pre)={b_pre:.4f} B(post)={b_post:.4f}  "
              f"gap(pre)={g_pre:+.2f} gap(post)={g_post:+.2f}  delta={(b_post - b_pre) * 1000:+.2f}mB")

    # =============== Probability tier (calibration plot, p_adj) ===============
    print()
    print("PROBABILITY TIER CALIBRATION (p_adj vs hit)")
    print("-" * 90)
    print(f"  {'bucket':<10} {'n':>6} {'mean(p_adj)':>12} {'mean(hit)':>10} {'gap_pct':>9}")
    p_adj_arr = num(cv["p_adj"]).clip(0, 1).to_numpy()
    prob_tier = []
    edges = [0.0, 0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 1.01]
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p_adj_arr >= lo) & (p_adj_arr < hi)
        if m.sum() < 30:
            continue
        gh = h[m]
        gp = p_adj_arr[m]
        gap = (gp.mean() - gh.mean()) * 100
        prob_tier.append({"range": f"[{lo:.2f},{hi:.2f})", "n": int(m.sum()),
                           "mean_p": float(gp.mean()), "mean_hit": float(gh.mean()),
                           "gap_pct": gap})
        print(f"  [{lo:.2f},{hi:.2f}) {int(m.sum()):>6} {gp.mean():>12.4f} {gh.mean():>10.4f} {gap:>+9.2f}")

    # =============== Stat x Direction matrix ===============
    print()
    print("STAT x DIRECTION (largest signed gap on p_adj, n>=200)")
    print("-" * 90)
    print(f"  {'stat':<8} {'dir':<6} {'n':>5} {'hit':>7} {'mean_p':>9} {'gap_pct':>9}")
    sd_grid = []
    for (stat, d), grp in cv.groupby(["stat_u", "dir_u"]):
        if len(grp) < 200: continue
        gh = grp["hit"].astype(float).to_numpy()
        gp = num(grp["p_adj"]).clip(0, 1).to_numpy()
        gap = (gp.mean() - gh.mean()) * 100
        sd_grid.append({"stat": stat, "direction": d, "n": int(len(grp)),
                         "hit": float(gh.mean()), "mean_p": float(gp.mean()),
                         "gap_pct": gap})
    sd_grid.sort(key=lambda r: -abs(r["gap_pct"]))
    for r in sd_grid[:25]:
        print(f"  {r['stat']:<8} {r['direction']:<6} {r['n']:>5} {r['hit']:>7.3f} "
              f"{r['mean_p']:>9.4f} {r['gap_pct']:>+9.2f}")

    # =============== Layer marginal effects (corpus) ===============
    print()
    print("LAYER MARGINAL EFFECTS (corpus brier)")
    print("-" * 90)
    layers = []
    for prev, cur, name in [
        ("p", "p_role", "role_context"),
        ("p_role", "p_adj_pre_under_relief", "blowout"),
        ("p_adj_pre_under_relief", "p_adj", "under_relief"),
    ]:
        if prev in cv.columns and cur in cv.columns:
            bp = brier(h, num(cv[prev]).clip(0, 1).to_numpy())
            bc = brier(h, num(cv[cur]).clip(0, 1).to_numpy())
            delta_mb = (bc - bp) * 1000
            layers.append({"layer": name, "from": prev, "to": cur,
                            "b_from": bp, "b_to": bc, "delta_mB": delta_mb})
            print(f"  {name:<16} {prev:<28} -> {cur:<28}  delta = {delta_mb:+.3f} mB")

    # =============== Save ===============
    out = {
        "n_legs": n,
        "base_hit_rate": base_hit,
        "chain_corpus": chain_corpus,
        "per_slate": per_slate,
        "per_stat": per_stat,
        "direction_split": direction_split,
        "tier_split": tier_split,
        "blowout_regime": blowout_split,
        "role_regime": role_split,
        "under_relief_regime": relief_split,
        "probability_tier": prob_tier,
        "stat_direction_grid": sd_grid,
        "layer_marginals": layers,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print()
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
