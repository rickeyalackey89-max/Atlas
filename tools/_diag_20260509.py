#!/usr/bin/env python
"""Diagnose 5/09 slip performance: why did every System slip miss?"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import re

ROOT = Path(__file__).resolve().parents[1]
TAG = "atlas_replay_v5cD_corpus_20260510_163434"
DATE = "20260509"


def _norm(s):
    return re.sub(r"\s+", " ", str(s)).strip().lower() if s else ""


def main():
    run_root = ROOT / "data" / "telemetry" / "replay_runs" / f"{TAG}_{DATE}" / "runs"
    run = sorted(run_root.glob("*"))[-1]
    print(f"[DIAG] {DATE} run = {run.name}")

    ev = pd.read_csv(run / "eval_legs.csv")
    print(f"[DIAG] eval_legs n={len(ev)}  hit_rate_overall={ev['hit'].mean():.3f}")

    # Build truth map
    truth = {}
    for _, r in ev.iterrows():
        try:
            key = (_norm(r["player"]), str(r["stat"]).upper(), float(r["line"]), str(r["direction"]).upper())
            truth[key] = {"hit": float(r["hit"]), "actual_value": r.get("actual_value", None), "p_cal": float(r.get("p_cal", 0)), "p_adj": float(r.get("p_adj", 0))}
        except Exception:
            continue

    # Look at each System slip
    print("\n" + "="*78)
    print(f"SYSTEM 5/09 ALL SLIPS")
    print("="*78)
    for n in (3, 4, 5):
        slip = pd.read_csv(run / f"recommended_{n}leg.csv")
        if len(slip) == 0:
            print(f"\n--- recommended_{n}leg: EMPTY")
            continue
        row = slip.iloc[0]
        legs_str = str(row.get("legs", ""))
        print(f"\n--- {n}-leg slip (claimed hit_prob={row.get('hit_prob', 0):.3f}, payout={row.get('payout_mult', 0)})")
        legs = legs_str.split("|")
        for leg in legs:
            m = re.match(r"^\s*(.+?)\s+(OVER|UNDER)\s+([A-Z0-9]+)\s+([\d.]+)\s+\(([A-Z]+)\)", leg.strip())
            if not m:
                continue
            player, direction, stat, line_str, tier = m.groups()
            line = float(line_str)
            key = (_norm(player), stat, line, direction)
            t = truth.get(key, {})
            hit = t.get("hit", "?")
            actual = t.get("actual_value", "?")
            p_cal = t.get("p_cal", 0)
            mark = "WIN " if hit == 1.0 else ("LOSS" if hit == 0.0 else "????")
            print(f"  [{mark}] {player:<22} {direction:<5} {stat:<5} {line:>5}  ({tier:<8})  actual={actual}  p_cal={p_cal:.3f}")

    # Why was the slate hard? Check overall hit rates by tier/direction
    print("\n" + "="*78)
    print(f"5/09 LEG QUALITY BREAKDOWN")
    print("="*78)
    by_tier = ev.groupby(["tier", "direction"]).agg(
        n=("hit", "count"),
        actual_hit=("hit", "mean"),
        mean_p_cal=("p_cal", "mean"),
    ).reset_index()
    by_tier["calib_gap"] = by_tier["actual_hit"] - by_tier["mean_p_cal"]
    print(by_tier.to_string(index=False))

    # Compare 5/09 to corpus mean
    print(f"\n5/09 overall:  n={len(ev)}  actual_hit_rate={ev['hit'].mean():.3f}  mean_p_cal={ev['p_cal'].mean():.3f}")
    # Slate context — how many games?
    if "game_date" in ev.columns:
        teams = pd.concat([ev["team"], ev["opp"]]).dropna().unique()
        print(f"  teams in slate: {sorted([str(t) for t in teams])}")
        print(f"  unique players: {ev['player'].nunique()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
