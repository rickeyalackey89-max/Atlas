"""
simulate_slips_from_cache.py

Loads the v17 resim cache and runs the full slip pipeline (System, Windfall,
DemonHunter, Marketed) against each date using the CURRENT config.yaml.
Scores every slip against the truth labels already in the cache.

Leg matching uses (player, stat, line, direction) against the cache truth.
The `legs` column from slip builders is a pipe-separated string:
  "Player DIR STAT LINE (TIER) [id:X] | ..."
We parse that + fall back to projection_id lookup.

Usage:
    cd C:/Users/13142/Atlas
    py Atlas/tools/simulate_slips_from_cache.py
"""

from __future__ import annotations

import pickle
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

# ── Paths ───────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parents[2]   # C:\Users\13142\Atlas
ATLAS_ROOT = ROOT / "Atlas"
CACHE_PATH  = ATLAS_ROOT / "data" / "model" / "_v17_resim_cache.pkl"
CONFIG_PATH = ATLAS_ROOT / "config.yaml"

sys.path.insert(0, str(ATLAS_ROOT / "src"))

from Atlas.core.slip_builders import (
    build_system_slips,
    build_windfall_slips,
    build_demonhunter_slips,
)
from Atlas.core.marketed_slip_builder import MarketedSlipBuilder

# ── Load cache ───────────────────────────────────────────────────────────────
print(f"Loading cache: {CACHE_PATH}")
with open(CACHE_PATH, "rb") as f:
    cache = pickle.load(f)

df_all: pd.DataFrame = cache["cv"].copy()
dates: list[str] = sorted(cache["dates"])
print(f"Loaded {len(dates)} dates, {len(df_all):,} legs\n")

# ── Load config ──────────────────────────────────────────────────────────────
with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

slip_cfg      = config.get("slip_build", {})
optimizer_cfg = config.get("optimizer", {})
top_n         = optimizer_cfg.get("top_n_slips", 3)
seed          = optimizer_cfg.get("seed", 42)
pricing_engine = config.get("pricing_engine", "power")

marketed_builder = MarketedSlipBuilder(config)

# ── Build truth lookups ──────────────────────────────────────────────────────
# Primary: (game_date, player, stat, line, direction) -> hit
truth_key: dict[tuple, int] = {}
# Secondary: (game_date, projection_id_str) -> hit  (if proj id exists)
truth_pid: dict[tuple, int] = {}

for _, row in df_all.iterrows():
    d = str(row["game_date"])
    k = (d, str(row["player"]), str(row["stat"]),
         float(row["line"]), str(row["direction"]).upper())
    truth_key[k] = int(row["hit"])
    if "projection_id" in row.index and pd.notna(row["projection_id"]):
        pid = str(row["projection_id"]).strip().rstrip(".0")
        truth_pid[(d, pid)] = int(row["hit"])

# Regex to parse leg strings: "Player DIR STAT LINE (TIER) [id:X]"
_LEG_RE = re.compile(
    r"^(?P<player>.+?)\s+(?P<direction>OVER|UNDER)\s+(?P<stat>[A-Z0-9/]+)"
    r"\s+(?P<line>[+-]?\d+(?:\.\d+)?)\s+\([^)]+\)\s+\[id:(?P<pid>[^\]]+)\]$",
    re.IGNORECASE,
)


def _score_legs_str(date: str, legs_str: str) -> bool | None:
    """Parse pipe-separated leg string and score against truth."""
    parts = [p.strip() for p in legs_str.split("|") if p.strip()]
    if not parts:
        return None
    results = []
    for part in parts:
        m = _LEG_RE.match(part)
        if not m:
            return None  # can't parse — skip slip
        player    = m.group("player").strip()
        direction = m.group("direction").upper()
        stat      = m.group("stat").upper()
        line      = float(m.group("line"))
        pid       = m.group("pid").strip().rstrip(".0")

        k = (date, player, stat, line, direction)
        if k in truth_key:
            results.append(truth_key[k])
        elif (date, pid) in truth_pid:
            results.append(truth_pid[(date, pid)])
        else:
            return None  # unmatched leg
    return all(r == 1 for r in results)


def _score_marketed_legs(date: str, legs_list: list[dict]) -> bool | None:
    """Score marketed slip legs (list of dicts with player/stat/line/dir)."""
    results = []
    for leg in legs_list:
        player    = str(leg.get("player", "")).strip()
        stat      = str(leg.get("stat", "")).strip().upper()
        line      = float(leg.get("line", 0))
        direction = str(leg.get("dir", leg.get("direction", ""))).strip().upper()
        k = (date, player, stat, line, direction)
        if k in truth_key:
            results.append(truth_key[k])
        else:
            return None
    return all(r == 1 for r in results) if results else None


# ── Simulate per date ────────────────────────────────────────────────────────
stats: dict[str, dict[int, dict]] = defaultdict(lambda: defaultdict(lambda: {"won": 0, "n": 0}))

print(f"Simulating {len(dates)} dates...")

for i, date in enumerate(dates):
    day_df = df_all[df_all["game_date"].astype(str) == str(date)].copy().reset_index(drop=True)
    if len(day_df) < 10:
        continue

    if (i + 1) % 10 == 0:
        print(f"  {i+1}/{len(dates)} dates done...")

    # ── System, Windfall, DemonHunter ────────────────────────────────────
    for family, build_fn in [
        ("system",      build_system_slips),
        ("windfall",    build_windfall_slips),
        ("demonhunter", build_demonhunter_slips),
    ]:
        for n_legs in [3, 4, 5]:
            try:
                slips_df = build_fn(
                    legs_df=day_df,
                    n_legs=n_legs,
                    top_n=top_n,
                    seed=seed,
                    pricing_engine=pricing_engine,
                    sort_mode="ev",
                    cfg=slip_cfg,
                )
            except Exception:
                continue

            if slips_df is None or slips_df.empty:
                continue

            # Score top-1 slip
            top = slips_df.iloc[0]
            legs_str = str(top.get("legs", ""))
            if not legs_str:
                continue
            won = _score_legs_str(str(date), legs_str)
            if won is not None:
                stats[family][n_legs]["n"] += 1
                stats[family][n_legs]["won"] += int(won)

    # ── Marketed slips ────────────────────────────────────────────────────
    try:
        marketed_slips = marketed_builder.build_slips(day_df)
    except Exception:
        marketed_slips = []

    for slip in (marketed_slips or []):
        n_legs    = slip.get("n_legs", 0)
        legs_list = slip.get("legs", [])
        if not legs_list:
            continue
        won = _score_marketed_legs(str(date), legs_list)
        if won is not None:
            stats["marketed"][n_legs]["n"] += 1
            stats["marketed"][n_legs]["won"] += int(won)


# ── Aggregate Results ────────────────────────────────────────────────────────
print("\n")
print("=" * 70)
print("  CACHE SIMULATION — CURRENT CONFIG — SLIP WIN RATES")
print("=" * 70)

payouts = {3: 6, 4: 10, 5: 20}
all_families  = ["system", "windfall", "demonhunter", "marketed"]
family_labels = {"system": "System", "windfall": "Windfall",
                 "demonhunter": "DemonHunter", "marketed": "Marketed"}

print(f"\n{'Family':<14} {'Legs':>4}  {'Won':>5} {'Total':>6}  {'Win%':>7}  {'Break%':>7}  {'EV':>8}")
print("-" * 57)

for fam in all_families:
    for n_legs in [3, 4, 5]:
        s = stats[fam][n_legs]
        if s["n"] == 0:
            continue
        wr       = s["won"] / s["n"]
        payout   = payouts.get(n_legs, 1)
        breakeven = 1.0 / payout
        ev       = payout * wr - 1.0
        flag     = " [+EV]" if ev > 0 else ""
        print(f"  {family_labels[fam]:<12} {n_legs:>4}  "
              f"{s['won']:>5} {s['n']:>6}  "
              f"{wr:>7.1%}  {breakeven:>7.1%}  {ev:>+7.3f}{flag}")

# ── Marketed summary ─────────────────────────────────────────────────────────
print("\n── Marketed Slip Summary ───────────────────────────────────────────────")
total_won = sum(stats["marketed"][n]["won"] for n in [3, 4, 5])
total_n   = sum(stats["marketed"][n]["n"]   for n in [3, 4, 5])
if total_n > 0:
    print(f"  Overall:  {total_won}/{total_n} = {total_won/total_n:.1%}")
    for n_legs in [3, 4, 5]:
        s = stats["marketed"][n_legs]
        if s["n"] > 0:
            wr = s["won"] / s["n"]
            print(f"  {n_legs}-leg:   {s['won']}/{s['n']} = {wr:.1%}")
else:
    print("  No marketed slips scored — check min_thresholds in config.yaml")

print(f"\n  Dates simulated: {len(dates)}  ({dates[0]} to {dates[-1]})")
print(f"  Config:          {CONFIG_PATH.name}")
print()
