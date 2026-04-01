#!/usr/bin/env python
"""
Slip Builder Trainer
====================
Grid-searches slip_build parameters PER OUTPUT CATEGORY to find
the best config for each (n_legs, sort_mode) combination.

Uses the D-drive replay corpus (scored_legs + eval_legs) as training data.
Outputs optimal per-category overrides for config.yaml.
"""
from __future__ import annotations

import copy
import itertools
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Atlas.core.slip_builders import build_slips_by_tier_buckets
from Atlas.stages.optimize.build_slips_today import _cfg_for_n_legs

# ── data paths ──────────────────────────────────────────────────────
BASE = Path(r"D:\AtlasTestMarch26\telemetry_replay_runs")
RUN_DATES = [
    "20260315", "20260316", "20260317", "20260318",
    "20260319", "20260320", "20260321", "20260322",
]

# ── categories to train ─────────────────────────────────────────────
CATEGORIES = [
    ("3-leg EV",  3, "ev"),
    ("3-leg HIT", 3, "hit"),
    ("4-leg EV",  4, "ev"),
    ("5-leg EV",  5, "ev"),
]

# ── parameter grid ──────────────────────────────────────────────────
# Each key maps to a list of candidate values to sweep.
PARAM_GRID: dict[str, list[Any]] = {
    "max_leg_prob":  [0.0, 0.55, 0.58, 0.60, 0.65, 0.70],
    "min_leg_prob":  [0.50, 0.52, 0.55],
    "frag_w":        [0.0, 0.20],
    "min_std_w":     [0.0, 0.10],
}

# ── tier mixes (fixed) ──────────────────────────────────────────────
MIXES = {
    3: {"STANDARD": 2, "DEMON": 1},
    4: {"STANDARD": 2, "DEMON": 2},
    5: {"STANDARD": 3, "DEMON": 2},
}

PAYOUT_FLEX = {"3": 2.25, "4": 5.0, "5": 10.0}


# ── data loading ────────────────────────────────────────────────────
def load_all_dates() -> list[tuple[str, pd.DataFrame, dict]]:
    """Return [(date, scored_df, truth_dict), ...]"""
    loaded = []
    for date in RUN_DATES:
        run_dir = BASE / f"kernel_v2_perstat_corr015_{date}"
        if not run_dir.exists():
            continue
        eval_files = list(run_dir.rglob("eval_legs.csv"))
        scored_files = list(run_dir.rglob("scored_legs_deduped.csv"))
        if not eval_files or not scored_files:
            continue
        eval_df = pd.read_csv(eval_files[0], low_memory=False)
        scored_df = pd.read_csv(scored_files[0], low_memory=False)

        truth: dict[tuple, int] = {}
        for _, row in eval_df.iterrows():
            player = str(row.get("player", "")).strip().lower()
            line_val = row.get("line", 0)
            line = float(line_val if pd.notna(line_val) else 0)
            stat = str(row.get("stat", "")).strip().upper()
            direction = str(row.get("direction", "")).strip().lower()
            hit_val = row.get("hit", 0)
            if pd.isna(hit_val):
                continue
            truth[(player, line, stat, direction)] = int(hit_val)
        loaded.append((date, scored_df, truth))
    return loaded


# ── slip evaluation ─────────────────────────────────────────────────
def evaluate_top_slip(slip_row, truth: dict) -> tuple[bool, int, int]:
    """Return (all_hit, matched, hit_count)."""
    legs_str = str(slip_row.get("legs", ""))
    parts = legs_str.split(" | ")
    matched = hit = 0
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "[id:" in part:
            part = part[: part.index("[id:")].strip()
        if "(" in part:
            part = part[: part.rindex("(")].strip()
        tokens = part.split()
        if len(tokens) < 4:
            continue
        direction = tokens[-3].lower()
        stat = tokens[-2].upper()
        try:
            line = float(tokens[-1])
        except ValueError:
            continue
        player = " ".join(tokens[:-3]).strip().lower()
        key = (player, line, stat, direction)
        if key in truth:
            matched += 1
            hit += truth[key]
    all_hit = hit == matched and matched > 0
    return all_hit, matched, hit


# ── builder wrapper ─────────────────────────────────────────────────
def build_top1(scored_df: pd.DataFrame, cfg: dict, n_legs: int,
               sort_mode: str) -> pd.Series | None:
    """Build slips and return top-1, or None."""
    resolved_cfg, top_n = _cfg_for_n_legs(cfg, n_legs, 10, sort_mode)
    sb = resolved_cfg.get("slip_build", {})
    try:
        slips = build_slips_by_tier_buckets(
            legs_df=scored_df,
            n_legs=n_legs,
            top_n=10,
            payout_power_mult=1.0,
            payout_flex=PAYOUT_FLEX,
            pricing_engine="atlas",
            cfg=resolved_cfg,
            seed=42,
            per_tier=500,
            max_attempts=100_000,
            sort_mode=sort_mode,
            mixes=MIXES,
            required_tiers=["STANDARD", "DEMON"],
            mix_ok_fn=lambda n, s: True,
        )
    except Exception:
        return None
    if slips is None or slips.empty:
        return None
    return slips.iloc[0]


# ── scoring a parameter combo across all dates ──────────────────────
def score_combo(
    combo: dict[str, Any],
    base_cfg: dict,
    n_legs: int,
    sort_mode: str,
    data: list[tuple[str, pd.DataFrame, dict]],
) -> dict[str, Any]:
    """Score one parameter combination. Returns metrics dict."""
    cfg = copy.deepcopy(base_cfg)
    sb = cfg.setdefault("slip_build", {})
    pen = sb.setdefault("penalty", {})

    # Apply parameter overrides
    for k, v in combo.items():
        if k in ("frag_w", "min_std_w"):
            pen[k] = v
        else:
            sb[k] = v

    total_slip_wins = 0
    total_dates = 0
    total_legs_matched = 0
    total_legs_hit = 0

    for date, scored_df, truth in data:
        top1 = build_top1(scored_df, cfg, n_legs, sort_mode)
        if top1 is None:
            continue
        total_dates += 1
        all_hit, matched, hit_count = evaluate_top_slip(top1, truth)
        if all_hit:
            total_slip_wins += 1
        total_legs_matched += matched
        total_legs_hit += hit_count

    slip_rate = total_slip_wins / max(total_dates, 1)
    leg_rate = total_legs_hit / max(total_legs_matched, 1)

    return {
        "combo": combo,
        "slip_wins": total_slip_wins,
        "dates": total_dates,
        "slip_rate": slip_rate,
        "legs_hit": total_legs_hit,
        "legs_matched": total_legs_matched,
        "leg_rate": leg_rate,
        # Composite: slip wins are king, leg rate is tiebreaker
        "score": slip_rate * 1000 + leg_rate * 100,
    }


# ── main ────────────────────────────────────────────────────────────
def main():
    base_cfg = yaml.safe_load(open("config.yaml"))
    print("Loading replay data...")
    data = load_all_dates()
    print(f"Loaded {len(data)} dates of replay data.\n")

    # Generate all combos
    param_names = sorted(PARAM_GRID.keys())
    all_values = [PARAM_GRID[k] for k in param_names]
    combos = [dict(zip(param_names, vals)) for vals in itertools.product(*all_values)]
    print(f"Parameter grid: {len(combos)} combinations per category\n")

    best_per_category: dict[str, dict] = {}

    for cat_name, n_legs, sort_mode in CATEGORIES:
        print(f"{'='*60}")
        print(f"  TRAINING: {cat_name}  (n_legs={n_legs}, sort={sort_mode})")
        print(f"{'='*60}")

        results = []
        for i, combo in enumerate(combos):
            if (i + 1) % 50 == 0:
                print(f"  ... {i+1}/{len(combos)} combos tested")
            result = score_combo(combo, base_cfg, n_legs, sort_mode, data)
            results.append(result)

        # Sort by composite score (slip wins first, leg rate tiebreaker)
        results.sort(key=lambda r: r["score"], reverse=True)

        best = results[0]
        print(f"\n  BEST: {best['combo']}")
        print(f"  Slip wins: {best['slip_wins']}/{best['dates']} = {best['slip_rate']:.1%}")
        print(f"  Leg rate:  {best['legs_hit']}/{best['legs_matched']} = {best['leg_rate']:.1%}")
        print()

        # Show top-5
        print("  TOP 5 COMBOS:")
        for rank, r in enumerate(results[:5], 1):
            print(f"    #{rank}: slips={r['slip_wins']}/{r['dates']} ({r['slip_rate']:.0%})"
                  f"  legs={r['legs_hit']}/{r['legs_matched']} ({r['leg_rate']:.0%})"
                  f"  | {r['combo']}")
        print()

        best_per_category[cat_name] = best

    # ── Summary ─────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  TRAINER RESULTS — OPTIMAL PER-CATEGORY CONFIG")
    print("=" * 70)

    # Baseline: run with current config (no overrides)
    print("\nCURRENT CONFIG (baseline):")
    for cat_name, n_legs, sort_mode in CATEGORIES:
        r = score_combo({}, base_cfg, n_legs, sort_mode, data)
        print(f"  {cat_name:12s}: slips={r['slip_wins']}/{r['dates']} ({r['slip_rate']:.0%})"
              f"  legs={r['legs_hit']}/{r['legs_matched']} ({r['leg_rate']:.0%})")

    print("\nOPTIMAL PER-CATEGORY:")
    total_wins_baseline = 0
    total_wins_optimal = 0
    for cat_name, n_legs, sort_mode in CATEGORIES:
        best = best_per_category[cat_name]
        baseline = score_combo({}, base_cfg, n_legs, sort_mode, data)
        total_wins_baseline += baseline["slip_wins"]
        total_wins_optimal += best["slip_wins"]
        delta_slip = best["slip_wins"] - baseline["slip_wins"]
        sign = "+" if delta_slip >= 0 else ""
        print(f"  {cat_name:12s}: slips={best['slip_wins']}/{best['dates']} ({best['slip_rate']:.0%})"
              f"  legs={best['legs_hit']}/{best['legs_matched']} ({best['leg_rate']:.0%})"
              f"  [{sign}{delta_slip} slips vs baseline]")
        print(f"    config: {best['combo']}")

    print(f"\n  TOTAL TOP-1 SLIP WINS: baseline={total_wins_baseline}"
          f"  optimal={total_wins_optimal}"
          f"  delta={total_wins_optimal - total_wins_baseline:+d}")

    # ── Generate YAML snippet ───────────────────────────────────────
    print("\n\n" + "=" * 70)
    print("  RECOMMENDED config.yaml OVERRIDES")
    print("=" * 70)

    # Group by sort_mode for by_sort_mode structure
    sort_overrides: dict[str, dict] = {}
    leg_overrides: dict[int, dict] = {}

    for cat_name, n_legs, sort_mode in CATEGORIES:
        best = best_per_category[cat_name]
        combo = best["combo"]
        if not combo:
            continue

        # Build the override dict for this category
        override: dict[str, Any] = {}
        pen_override: dict[str, Any] = {}
        for k, v in combo.items():
            if k in ("frag_w", "min_std_w"):
                pen_override[k] = v
            else:
                override[k] = v
        if pen_override:
            override["penalty"] = pen_override

        # Place in by_sort_mode → by_legs structure
        sort_key = sort_mode if sort_mode != "ev" else None
        leg_key = n_legs

        if sort_key:
            sort_overrides.setdefault(sort_key, {}).setdefault("by_legs", {})[str(leg_key)] = override
        else:
            leg_overrides[leg_key] = override

    print("\nslip_build:")
    # Default (EV) by_legs overrides
    if leg_overrides:
        print("  by_legs:")
        for n, ovr in sorted(leg_overrides.items()):
            print(f'    "{n}":')
            for k, v in ovr.items():
                if isinstance(v, dict):
                    print(f"      {k}:")
                    for k2, v2 in v.items():
                        print(f"        {k2}: {v2}")
                else:
                    print(f"      {k}: {v}")
    # by_sort_mode overrides
    if sort_overrides:
        print("  by_sort_mode:")
        for sm, sm_data in sort_overrides.items():
            print(f"    {sm}:")
            if "by_legs" in sm_data:
                print("      by_legs:")
                for n, ovr in sorted(sm_data["by_legs"].items()):
                    print(f'        "{n}":')
                    for k, v in ovr.items():
                        if isinstance(v, dict):
                            print(f"          {k}:")
                            for k2, v2 in v.items():
                                print(f"            {k2}: {v2}")
                        else:
                            print(f"          {k}: {v}")


if __name__ == "__main__":
    main()
