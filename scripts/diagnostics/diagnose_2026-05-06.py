"""
Diagnose 2026-05-06 -- the persistent worst-slate outlier.

Every v5/v5b variant regresses +7 to +13 mB on this slate alone.
Goal: determine whether the regression is upstream (kernel chain stages)
or downstream (calibrator residual pattern).

Outputs:
  1. Chain-stage Brier on 05-06 only (p, p_role, p_adj_pre_under_relief,
     p_adj, p_for_cal). Compare to corpus mean.
  2. Slate composition: by stat, by direction, by tier, by role/non-role,
     by hit rate.
  3. p_adj reliability decile on 05-06 vs corpus.
  4. Outlier legs: where (hit - p_adj) is largest in magnitude on 05-06.
  5. Counterfactual: if we used p_adj as p_for_cal AND no calibrator
     (identity), how does 05-06 score? Does the calibrator itself add
     the regression, or is it baked into raw probabilities?
"""
from __future__ import annotations

import pathlib
import pickle
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
pd.options.display.float_format = "{:.4f}".format
pd.options.display.width = 200

ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE_PATH = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"
TARGET_DATE = "2026-05-06"


def brier(y, p):
    return float(np.mean((p - y) ** 2))


def main() -> int:
    print("=" * 80)
    print(f"Slate diagnostic: {TARGET_DATE}")
    print("=" * 80)

    with open(CACHE_PATH, "rb") as f:
        cache = pickle.load(f)
    cv = cache["cv"].copy()
    cv = cv.dropna(subset=["hit"]).reset_index(drop=True)
    cv = cv[cv["hit"].isin([0, 1, 0.0, 1.0])].reset_index(drop=True)
    cv["game_date"] = cv["game_date"].astype(str).str[:10]

    target = cv[cv["game_date"] == TARGET_DATE].reset_index(drop=True)
    other  = cv[cv["game_date"] != TARGET_DATE].reset_index(drop=True)
    print(f"target legs: {len(target):,} | corpus legs: {len(cv):,}")
    print()

    # 1. Chain-stage Brier
    stages = ["p", "p_role", "p_adj_pre_under_relief", "p_adj", "p_for_cal"]
    stages = [c for c in stages if c in cv.columns]
    print("=" * 80)
    print("1. Chain-stage Brier (lower=better)")
    print("=" * 80)
    print(f"{'stage':<26} {'05-06':>10} {'others':>10} {'delta_mB':>10}")
    for s in stages:
        bt = brier(target["hit"], target[s].astype(float))
        bo = brier(other["hit"], other[s].astype(float))
        print(f"{s:<26} {bt:>10.4f} {bo:>10.4f} {(bt-bo)*1000:>+10.2f}")
    print()
    # Hit-rate per stage doesn't matter; show observed hit rate
    print(f"  hit rate 05-06: {target['hit'].mean():.4f}  | corpus: {cv['hit'].mean():.4f}")
    print(f"  mean p_adj 05-06: {target['p_adj'].mean():.4f}  | corpus: {cv['p_adj'].mean():.4f}")
    print()

    # 2. Slate composition
    print("=" * 80)
    print("2. Slate composition (vs corpus)")
    print("=" * 80)
    def split(df, col):
        return df[col].value_counts(normalize=True).sort_index()

    for col in ["stat", "direction", "tier"]:
        if col in target.columns:
            print(f"-- {col} --")
            t = split(target, col).rename("target")
            c = split(other, col).rename("other")
            comp = pd.concat([t, c], axis=1).fillna(0.0)
            comp["delta"] = comp["target"] - comp["other"]
            print(comp.to_string())
            print()

    # role-context active rate
    if "role_ctx_outs_used" in target.columns:
        rt = (pd.to_numeric(target["role_ctx_outs_used"], errors="coerce").fillna(0) > 0).mean()
        ro = (pd.to_numeric(other["role_ctx_outs_used"], errors="coerce").fillna(0) > 0).mean()
        print(f"role_ctx active: 05-06 {rt:.3f}  |  others {ro:.3f}")
        print()

    # 3. Reliability decile -- p_adj on 05-06 vs others
    print("=" * 80)
    print("3. p_adj reliability deciles")
    print("=" * 80)
    def decile_table(df, name):
        df = df.copy()
        df["dec"] = pd.qcut(df["p_adj"], 10, labels=False, duplicates="drop")
        g = df.groupby("dec").agg(
            n=("hit", "size"),
            mean_p=("p_adj", "mean"),
            hit_rate=("hit", "mean"),
        )
        g["gap_mB"] = (g["hit_rate"] - g["mean_p"]) * 1000
        g.index.name = name
        return g

    print("-- 05-06 --")
    print(decile_table(target, "decile").to_string())
    print()
    print("-- others --")
    print(decile_table(other, "decile").to_string())
    print()

    # 4. Per-stat Brier on 05-06 (where are the misses?)
    print("=" * 80)
    print("4. Per-stat Brier on 05-06 (sorted worst-first)")
    print("=" * 80)
    rows = []
    for stat, g in target.groupby("stat"):
        rows.append({
            "stat": stat,
            "n": len(g),
            "hit_rate": g["hit"].mean(),
            "mean_p_adj": g["p_adj"].mean(),
            "brier_p_adj": brier(g["hit"], g["p_adj"]),
            "gap_mB": (g["hit"].mean() - g["p_adj"].mean()) * 1000,
        })
    df_stat = pd.DataFrame(rows).sort_values("brier_p_adj", ascending=False)
    print(df_stat.to_string(index=False))
    print()

    # Per-direction
    print("-- 05-06 per direction --")
    rows = []
    for d, g in target.groupby("direction"):
        rows.append({
            "dir": d, "n": len(g),
            "hit": g["hit"].mean(),
            "mean_p": g["p_adj"].mean(),
            "brier": brier(g["hit"], g["p_adj"]),
            "gap_mB": (g["hit"].mean() - g["p_adj"].mean()) * 1000,
        })
    print(pd.DataFrame(rows).to_string(index=False))
    print()

    # Per-tier
    print("-- 05-06 per tier --")
    rows = []
    for t, g in target.groupby("tier"):
        rows.append({
            "tier": t, "n": len(g),
            "hit": g["hit"].mean(),
            "mean_p": g["p_adj"].mean(),
            "brier": brier(g["hit"], g["p_adj"]),
            "gap_mB": (g["hit"].mean() - g["p_adj"].mean()) * 1000,
        })
    print(pd.DataFrame(rows).to_string(index=False))
    print()

    # 5. Big misses on 05-06 -- where calibrator presumably overcorrects
    print("=" * 80)
    print("5. Top 25 worst-Brier legs on 05-06 (p_adj)")
    print("=" * 80)
    target = target.copy()
    target["sq_err"] = (target["hit"] - target["p_adj"]) ** 2
    cols = ["player", "team", "opp", "stat", "line", "direction", "tier", "p", "p_role",
            "p_adj", "p_for_cal", "hit", "sq_err"]
    cols = [c for c in cols if c in target.columns]
    print(target.sort_values("sq_err", ascending=False).head(25)[cols].to_string(index=False))
    print()

    # 6. Game-by-game on 05-06 (is it a single matchup?)
    print("=" * 80)
    print("6. Per-matchup Brier on 05-06")
    print("=" * 80)
    if "team" in target.columns and "opp" in target.columns:
        target["matchup"] = target.apply(
            lambda r: " @ ".join(sorted([str(r["team"]), str(r["opp"])])), axis=1)
        rows = []
        for m, g in target.groupby("matchup"):
            rows.append({
                "matchup": m, "n": len(g),
                "hit": g["hit"].mean(),
                "mean_p": g["p_adj"].mean(),
                "brier": brier(g["hit"], g["p_adj"]),
                "gap_mB": (g["hit"].mean() - g["p_adj"].mean()) * 1000,
            })
        df_match = pd.DataFrame(rows).sort_values("brier", ascending=False)
        print(df_match.to_string(index=False))
        print()

    # 7. Counterfactual: what about with NO calibrator? (identity = p_adj)
    # If 05-06 is bad even with p_adj as final prob, the regression lives upstream.
    print("=" * 80)
    print("7. Counterfactual: identity calibrator (p_cal := p_adj)")
    print("=" * 80)
    b_pre  = brier(target["hit"], target["p_for_cal"].astype(float))
    b_iden = brier(target["hit"], target["p_adj"].astype(float))
    print(f"  raw p_for_cal Brier = {b_pre:.4f}")
    print(f"  identity (p_adj)    = {b_iden:.4f}")
    print(f"  delta vs raw        = {(b_iden - b_pre)*1000:+.2f} mB  (upstream-only)")
    print()
    print("  Interpretation:")
    print("    If identity (p_adj) is already worse than raw p_for_cal on 05-06,")
    print("    the calibrator is fighting an uphill kernel-stage problem.")
    print("    If identity is better, calibrator residuals are the source.")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
