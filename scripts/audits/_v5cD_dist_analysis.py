"""Analyze v5cD p_cal distribution vs marketed/slip_build thresholds.

Reads the two smoke-replay scored_legs_deduped.csv files and reports:
  1. p_cal distribution by tier (GOBLIN / STANDARD / DEMON)
  2. Count of legs crossing current marketed floors (min_raw_thresholds)
  3. Count crossing min_thresholds (post-haircut)
  4. p_cal vs p_adj headroom by tier
  5. min_leg_prob (slip_build) qualifying counts
  6. UNDER window qualifying counts
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
TAG = "atlas_replay_v5cD_smoke_20260510_144329"

cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
mk = cfg["marketed_slips"]
sb = cfg["slip_build"]

MIN_RAW = mk["min_raw_thresholds"]          # GOBLIN/STD/DEMON pre-haircut p_cal
MIN_FIN = mk["min_thresholds"]               # post-haircut p_cal_marketed
HAIRCUT = {"GOBLIN": 0.95, "STANDARD": 0.85, "DEMON": 0.75}
MIN_LEG_PROB = float(sb["min_leg_prob"])
MIN_UNDER, MAX_UNDER = float(sb["min_under_prob"]), float(sb["max_under_prob"])

print(f"Config snapshot:")
print(f"  marketed.min_raw_thresholds = {MIN_RAW}")
print(f"  marketed.min_thresholds     = {MIN_FIN}")
print(f"  slip_build.min_leg_prob     = {MIN_LEG_PROB}")
print(f"  slip_build.under window     = [{MIN_UNDER}, {MAX_UNDER}]")
print()


def load_scored(date: str) -> pd.DataFrame:
    base = ROOT / "data" / "telemetry" / "replay_runs" / f"{TAG}_{date}" / "runs"
    run = sorted(base.glob("*"))[-1]
    df = pd.read_csv(run / "scored_legs_deduped.csv")
    df["date"] = date
    return df


def report_one(df: pd.DataFrame, date: str) -> None:
    print("=" * 80)
    print(f"DATE {date}  total legs = {len(df):,}")
    print("=" * 80)

    # global p_cal distribution
    p = df["p_cal"].astype(float)
    print(f"\np_cal overall:")
    print(f"  count={len(p):,}  mean={p.mean():.4f}  median={p.median():.4f}")
    print(f"  pct  10/25/50/75/90/95/99 = "
          f"{p.quantile(0.10):.3f}/{p.quantile(0.25):.3f}/"
          f"{p.quantile(0.50):.3f}/{p.quantile(0.75):.3f}/"
          f"{p.quantile(0.90):.3f}/{p.quantile(0.95):.3f}/{p.quantile(0.99):.3f}")

    # by tier
    print(f"\np_cal by tier (OVER + UNDER combined):")
    print(f"  {'tier':<10} {'n':>6} {'mean':>8} {'med':>8} {'p90':>8} {'max':>8}  "
          f"{'>=raw':>10} {'>=fin*':>10}")
    for tier in ["GOBLIN", "STANDARD", "DEMON"]:
        sub = df[df["tier"] == tier]
        if len(sub) == 0:
            continue
        pp = sub["p_cal"].astype(float)
        raw_floor = MIN_RAW.get(tier, 0)
        fin_floor = MIN_FIN.get(tier, 0)
        haircut = HAIRCUT.get(tier, 1.0)
        # post-haircut: p_cal_marketed = p_cal * haircut
        n_raw = int((pp >= raw_floor).sum())
        n_fin = int((pp * haircut >= fin_floor).sum())
        print(f"  {tier:<10} {len(sub):>6} {pp.mean():>8.4f} {pp.median():>8.4f} "
              f"{pp.quantile(0.9):>8.4f} {pp.max():>8.4f}  "
              f"{n_raw:>10} {n_fin:>10}")
    print(f"  *fin counts use post-haircut p_cal_marketed = p_cal * haircut")

    # By tier OVER only (GOBLIN/DEMON structurally OVER only)
    print(f"\np_cal by tier (OVER only -- relevant for GOBLIN/DEMON):")
    for tier in ["GOBLIN", "STANDARD", "DEMON"]:
        sub = df[(df["tier"] == tier) & (df["direction"].str.upper() == "OVER")]
        if len(sub) == 0:
            continue
        pp = sub["p_cal"].astype(float)
        raw_floor = MIN_RAW.get(tier, 0)
        haircut = HAIRCUT.get(tier, 1.0)
        fin_floor = MIN_FIN.get(tier, 0)
        n_raw = int((pp >= raw_floor).sum())
        n_fin = int((pp * haircut >= fin_floor).sum())
        print(f"  {tier:<10} OVER n={len(sub):>5}  mean={pp.mean():.3f}  "
              f">=raw({raw_floor:.2f})={n_raw}  >=fin({fin_floor:.2f})={n_fin}")

    # slip_build min_leg_prob coverage
    over = df[df["direction"].str.upper() == "OVER"]
    under = df[df["direction"].str.upper() == "UNDER"]
    n_over_qual = int((over["p_cal"].astype(float) >= MIN_LEG_PROB).sum())
    n_under_qual = int(((under["p_cal"].astype(float) >= MIN_UNDER) &
                        (under["p_cal"].astype(float) <= MAX_UNDER)).sum())
    print(f"\nslip_build leg pool:")
    print(f"  OVER  n={len(over):>5}  >= min_leg_prob({MIN_LEG_PROB}) = {n_over_qual}")
    print(f"  UNDER n={len(under):>5}  in [{MIN_UNDER},{MAX_UNDER}] = {n_under_qual}")
    print(f"  total qualifying for builder pool = {n_over_qual + n_under_qual}")

    # p_cal vs p_adj movement (does v5cD compress, expand, or shift?)
    p_adj = df["p_adj"].astype(float)
    delta = p - p_adj
    print(f"\np_cal vs p_adj movement:")
    print(f"  mean delta = {delta.mean():+.4f}  std = {delta.std():.4f}")
    print(f"  delta percentiles 10/50/90 = "
          f"{delta.quantile(0.1):+.3f}/{delta.quantile(0.5):+.3f}/{delta.quantile(0.9):+.3f}")
    print(f"  legs where v5cD INCREASED p: {(delta > 0.01).sum()}")
    print(f"  legs where v5cD DECREASED p: {(delta < -0.01).sum()}")
    print(f"  legs essentially unchanged (|d|<0.01): {((delta.abs() < 0.01)).sum()}")
    print()


def report_combined(dfs: list[pd.DataFrame]) -> None:
    df = pd.concat(dfs, ignore_index=True)
    print("=" * 80)
    print(f"COMBINED  total = {len(df):,} legs across {len(dfs)} dates")
    print("=" * 80)
    p = df["p_cal"].astype(float)
    print(f"\np_cal combined: mean={p.mean():.4f}  median={p.median():.4f}")

    print(f"\nUnique players qualifying for marketed pool (raw threshold):")
    for tier in ["GOBLIN", "STANDARD", "DEMON"]:
        sub = df[df["tier"] == tier]
        raw_floor = MIN_RAW.get(tier, 0)
        haircut = HAIRCUT.get(tier, 1.0)
        fin_floor = MIN_FIN.get(tier, 0)
        # Marketed builder gates on BOTH raw and post-haircut
        if tier in ("GOBLIN", "DEMON"):
            sub = sub[sub["direction"].str.upper() == "OVER"]
        passes = sub[
            (sub["p_cal"].astype(float) >= raw_floor) &
            (sub["p_cal"].astype(float) * haircut >= fin_floor)
        ]
        n_players = passes["player"].nunique() if len(passes) else 0
        print(f"  {tier:<10} legs_passing_both={len(passes):>4}  unique_players={n_players}")
    print()


def main() -> int:
    dfs = []
    for date in ["20260505", "20260507"]:
        df = load_scored(date)
        report_one(df, date)
        dfs.append(df)
    report_combined(dfs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
