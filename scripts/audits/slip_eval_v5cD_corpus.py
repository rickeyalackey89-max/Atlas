#!/usr/bin/env python
"""Slip-level evaluation across the v5cD corpus replay.

For each of the 10 corpus dates, joins recommended_{3,4,5}leg.csv (System +
Windfall) and marketed_slips.csv legs against eval_legs.csv `hit` truth,
then computes per-slip won/lost outcome and aggregates:

  - hit rate per family / leg-count
  - mean hit_prob (claimed) vs actual hit rate
  - EV realized
  - per-slate breakdown

Saves a summary CSV to logs/.
"""
from __future__ import annotations
import sys
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

TAG = "atlas_replay_v5cD_corpus_20260510_163434"
DATES = [
    "20260430","20260501","20260502","20260503","20260504",
    "20260505","20260506","20260507","20260508","20260509",
]


def _norm_player(s: str) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def _parse_leg_field(leg_str: str) -> dict:
    """Parse '<Player> <DIR> <STAT> <LINE> (<TIER>) [id:<id>]' format."""
    if not isinstance(leg_str, str):
        return {}
    m = re.match(
        r"^\s*(.+?)\s+(OVER|UNDER)\s+([A-Z0-9]+)\s+([\d.]+)\s+\(([A-Z]+)\)(?:\s+\[id:(\d+)\])?\s*$",
        leg_str.strip(),
    )
    if not m:
        return {}
    return {
        "player": m.group(1).strip(),
        "direction": m.group(2),
        "stat": m.group(3),
        "line": float(m.group(4)),
        "tier": m.group(5),
        "leg_id": m.group(6) or "",
    }


def _build_leg_truth_map(eval_df: pd.DataFrame) -> dict:
    """Build (player_norm, stat, line, direction) -> hit lookup."""
    cols_needed = {"player", "stat", "line", "direction", "hit"}
    if not cols_needed.issubset(eval_df.columns):
        return {}
    out = {}
    for _, r in eval_df.iterrows():
        try:
            key = (
                _norm_player(r["player"]),
                str(r["stat"]).upper(),
                float(r["line"]),
                str(r["direction"]).upper(),
            )
            out[key] = float(r["hit"])
        except Exception:
            continue
    return out


def _score_legs(leg_dicts: list, truth_map: dict) -> tuple[int, int, list]:
    """Returns (hits, total, miss_keys). hits/total only count legs we can resolve."""
    hits = 0
    total = 0
    misses = []
    for ld in leg_dicts:
        if not ld:
            continue
        key = (_norm_player(ld["player"]), ld["stat"], ld["line"], ld["direction"])
        if key in truth_map:
            total += 1
            hits += int(truth_map[key] >= 0.5)
        else:
            misses.append(key)
    return hits, total, misses


def _eval_recommended(run_dir: Path, family: str, truth_map: dict, n_legs: int) -> dict:
    """Score a single recommended_{n}leg.csv slip (top-1) for given family."""
    # Family is encoded by which subdir the CSV came from; in replay output the
    # top-level recommended_*.csv corresponds to System (sort_mode=ev). For
    # Windfall we look under a windfall-flagged file if it exists.
    csv = run_dir / f"recommended_{n_legs}leg.csv"
    if not csv.exists():
        return {"family": family, "n_legs": n_legs, "status": "MISSING"}
    df = pd.read_csv(csv)
    if len(df) == 0:
        return {"family": family, "n_legs": n_legs, "status": "EMPTY"}
    row = df.iloc[0]
    legs_str = str(row.get("legs", ""))
    leg_parts = [_parse_leg_field(s) for s in legs_str.split("|")]
    claimed_hit_prob = float(row.get("hit_prob", 0.0) or 0.0)
    payout = float(row.get("payout_mult", 0.0) or 0.0)

    hits, total, _ = _score_legs(leg_parts, truth_map)
    all_hit = (total == n_legs and hits == n_legs)
    return {
        "family": family,
        "n_legs": n_legs,
        "status": "OK" if total == n_legs else f"PARTIAL_{total}_{n_legs}",
        "claimed_hit_prob": claimed_hit_prob,
        "payout_mult": payout,
        "legs_hit": hits,
        "legs_total": total,
        "slip_won": int(all_hit),
        "legs": legs_str,
    }


def _eval_marketed(run_dir: Path, truth_map: dict) -> list:
    csv = run_dir / "marketed_slips.csv"
    if not csv.exists():
        return []
    df = pd.read_csv(csv)
    if "slip" not in df.columns:
        return []
    rows = []
    for slip_label, grp in df.groupby("slip"):
        # parse n_legs from label like "3-leg"
        try:
            n_legs = int(str(slip_label).split("-")[0])
        except Exception:
            n_legs = len(grp)
        leg_parts = []
        for _, r in grp.iterrows():
            leg_parts.append({
                "player": str(r.get("player", "")),
                "stat": str(r.get("stat", "")).upper(),
                "line": float(r.get("line", 0.0) or 0.0),
                "direction": str(r.get("direction", "")).upper(),
                "tier": str(r.get("tier", "")).upper(),
                "leg_id": "",
            })
        claimed_hit_prob = float(grp.iloc[0].get("hit_prob", 0.0) or 0.0)
        payout = float(grp.iloc[0].get("payout_mult", 0.0) or 0.0)
        hits, total, _ = _score_legs(leg_parts, truth_map)
        all_hit = (total == n_legs and hits == n_legs)
        rows.append({
            "family": "Marketed",
            "n_legs": n_legs,
            "status": "OK" if total == n_legs else f"PARTIAL_{total}_{n_legs}",
            "claimed_hit_prob": claimed_hit_prob,
            "payout_mult": payout,
            "legs_hit": hits,
            "legs_total": total,
            "slip_won": int(all_hit),
        })
    return rows


def main() -> int:
    all_rows = []
    for date in DATES:
        base = ROOT / "data" / "telemetry" / "replay_runs" / f"{TAG}_{date}" / "runs"
        if not base.exists():
            print(f"[SKIP] {date} no runs dir")
            continue
        run_dirs = sorted(base.glob("*"))
        if not run_dirs:
            print(f"[SKIP] {date} empty runs dir")
            continue
        run = run_dirs[-1]
        eval_csv = run / "eval_legs.csv"
        if not eval_csv.exists():
            print(f"[SKIP] {date} no eval_legs.csv")
            continue
        eval_df = pd.read_csv(eval_csv)
        truth_map = _build_leg_truth_map(eval_df)
        print(f"[EVAL] {date}  truth_map size={len(truth_map)}")

        # System (top recommended_*.csv = sort_mode=ev = System)
        for n in (3, 4, 5):
            r = _eval_recommended(run, "System", truth_map, n)
            r["date"] = date
            all_rows.append(r)

        # Marketed
        for r in _eval_marketed(run, truth_map):
            r["date"] = date
            all_rows.append(r)

    df = pd.DataFrame(all_rows)
    out_csv = ROOT / "logs" / f"slip_eval_v5cD_corpus_{TAG}.csv"
    df.to_csv(out_csv, index=False)

    print("\n" + "="*78)
    print("PER-SLIP DETAIL")
    print("="*78)
    print(df.to_string(index=False))

    # Aggregate by family + n_legs
    print("\n" + "="*78)
    print("AGGREGATE: hit rate, claimed vs actual")
    print("="*78)
    ok = df[df["status"] == "OK"].copy()
    if len(ok) > 0:
        agg = (ok.groupby(["family", "n_legs"])
                 .agg(n_slips=("slip_won", "count"),
                      actual_winrate=("slip_won", "mean"),
                      claimed_hit_prob=("claimed_hit_prob", "mean"),
                      mean_payout=("payout_mult", "mean"))
                 .reset_index())
        agg["calib_gap"] = agg["actual_winrate"] - agg["claimed_hit_prob"]
        agg["realized_ev_mult"] = agg["actual_winrate"] * agg["mean_payout"]
        print(agg.to_string(index=False))
        agg.to_csv(ROOT / "logs" / f"slip_eval_v5cD_corpus_{TAG}_agg.csv", index=False)

    print(f"\n[SUMMARY] {out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
