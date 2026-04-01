"""
Multi-replay slip simulation.
Compares OLD vs NEW slip builder configs across multiple historical runs with eval data.
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Atlas.core.slip_builders import build_slips_by_tier_buckets


def load_run_data(run_dir: Path) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Load scored legs and eval legs from a run directory."""
    legs_df = None
    eval_df = None
    
    for name in ["scored_legs_deduped.csv", "scored_legs.csv"]:
        p = run_dir / name
        if p.exists():
            legs_df = pd.read_csv(p)
            break
    
    eval_path = run_dir / "eval_legs.csv"
    if eval_path.exists():
        eval_df = pd.read_csv(eval_path)
    
    return legs_df, eval_df


def build_with_config(legs_df: pd.DataFrame, cfg: dict, n_legs: int, sort_mode: str) -> pd.DataFrame:
    """Build slips with given config."""
    mixes = {
        3: {"STANDARD": 2, "DEMON": 1},
        4: {"STANDARD": 2, "DEMON": 2},
        5: {"STANDARD": 3, "DEMON": 2},
    }
    required_tiers = ["STANDARD", "DEMON"]
    
    def mix_ok_fn(n_legs, legs_str):
        return True
    
    return build_slips_by_tier_buckets(
        legs_df=legs_df,
        n_legs=n_legs,
        top_n=10,
        payout_power_mult=1.0,
        payout_flex={"3": 2.25, "4": 5.0, "5": 10.0},
        pricing_engine="atlas",
        cfg=cfg,
        seed=42,
        per_tier=500,
        max_attempts=100000,
        sort_mode=sort_mode,
        mixes=mixes,
        required_tiers=required_tiers,
        mix_ok_fn=mix_ok_fn,
    )


def calc_actual_hit_rate(slips_df: pd.DataFrame, eval_df: pd.DataFrame) -> dict:
    """Calculate actual hit rate using eval legs truth data."""
    if slips_df.empty or eval_df is None or eval_df.empty:
        return {"evaluated": 0, "hits": 0, "hit_rate": None}
    
    # Build truth lookup: (player_lower, line, stat_upper, direction_lower) -> hit
    truth: dict[tuple, int] = {}
    for _, row in eval_df.iterrows():
        player = str(row.get("player", row.get("player_name", ""))).strip().lower()
        line = float(row.get("line", 0) if pd.notna(row.get("line")) else 0)
        stat = str(row.get("stat", row.get("stat_type", ""))).strip().upper()
        direction = str(row.get("direction", "")).strip().lower()
        hit_val = row.get("hit", 0)
        if pd.isna(hit_val):
            continue  # Skip legs with no truth data
        hit = int(hit_val)
        
        if player and stat:
            truth[(player, line, stat, direction)] = hit
    
    hits = 0
    evaluated = 0
    
    for _, slip in slips_df.iterrows():
        legs_str = str(slip.get("legs", ""))
        # Parse legs from string format: "Player OVER STAT LINE (TIER) | ..."
        parts = legs_str.split(" | ")
        
        slip_results = []
        for part in parts:
            # Example: "Josh Giddey UNDER REB 9.5 (STANDARD) [id:11034...]"
            part = part.strip()
            if not part:
                continue
            
            # Extract components
            tokens = part.split()
            if len(tokens) < 5:
                continue
            
            # Find direction (OVER/UNDER)
            dir_idx = -1
            for i, t in enumerate(tokens):
                if t.upper() in ("OVER", "UNDER"):
                    dir_idx = i
                    break
            
            if dir_idx < 1:
                continue
            
            player = " ".join(tokens[:dir_idx]).lower()
            direction = tokens[dir_idx].lower()
            stat = tokens[dir_idx + 1].upper() if dir_idx + 1 < len(tokens) else ""
            
            # Find line (numeric value)
            line = 0.0
            for t in tokens[dir_idx + 2:]:
                try:
                    line = float(t)
                    break
                except ValueError:
                    continue
            
            key = (player, line, stat, direction)
            if key in truth:
                slip_results.append(truth[key])
        
        if len(slip_results) >= 3:  # Only count if we found enough legs
            evaluated += 1
            if all(slip_results):
                hits += 1
    
    return {
        "evaluated": evaluated,
        "hits": hits,
        "hit_rate": hits / evaluated if evaluated > 0 else None,
    }


def main():
    parser = argparse.ArgumentParser(description="Multi-replay slip simulation")
    parser.add_argument("--legs", type=int, default=3, help="Slip size (3, 4, 5)")
    parser.add_argument("--sort-mode", default="ev", help="Sort mode (ev, hit)")
    parser.add_argument("--runs-dir", default="data/output/runs", help="Runs directory")
    args = parser.parse_args()
    
    runs_dir = Path(args.runs_dir)
    
    # Find all runs with eval data
    run_dirs = []
    for d in sorted(runs_dir.iterdir()):
        if d.is_dir() and (d / "eval_legs.csv").exists():
            run_dirs.append(d)
    
    if not run_dirs:
        print("No runs with eval_legs.csv found")
        return 1
    
    print(f"Found {len(run_dirs)} runs with eval data")
    print(f"Testing {args.legs}-leg slips, sort_mode={args.sort_mode}")
    print()
    
    # Load base config
    cfg_path = Path(__file__).resolve().parents[1] / "config.yaml"
    base_cfg = yaml.safe_load(cfg_path.read_text())
    
    # Config OLD: Pre-constraint (strict)
    cfg_old = copy.deepcopy(base_cfg)
    cfg_old["slip_build"]["max_players_per_team"] = 1
    cfg_old["slip_build"]["no_same_game_within_slip"] = True
    cfg_old["slip_build"]["min_leg_prob"] = 0.0
    cfg_old["slip_build"]["require_healthy_data"] = False
    cfg_old["slip_build"]["max_same_stat"] = 0  # disabled
    cfg_old["slip_build"]["penalty"]["min_std_w"] = 0.0
    
    # Config NEW: With constraints (current)
    cfg_new = copy.deepcopy(base_cfg)
    # Uses current config values
    
    results_old: list[dict] = []
    results_new: list[dict] = []
    
    for run_dir in run_dirs:
        print(f"\n--- {run_dir.name} ---")
        legs_df, eval_df = load_run_data(run_dir)
        
        if legs_df is None or legs_df.empty:
            print("  No scored legs, skipping")
            continue
        
        print(f"  Legs: {len(legs_df)}, Eval: {len(eval_df) if eval_df is not None else 0}")
        
        # Build with OLD config
        try:
            slips_old = build_with_config(legs_df, cfg_old, args.legs, args.sort_mode)
            if not slips_old.empty and eval_df is not None:
                actual_old = calc_actual_hit_rate(slips_old, eval_df)
                results_old.append({
                    "run": run_dir.name,
                    "slips": len(slips_old),
                    "avg_hit_prob": slips_old["hit_prob"].mean(),
                    "max_hit_prob": slips_old["hit_prob"].max(),
                    **actual_old,
                })
                print(f"  OLD: {len(slips_old)} slips, avg_hit_prob={slips_old['hit_prob'].mean():.3f}, "
                      f"actual={actual_old['hits']}/{actual_old['evaluated']}")
        except Exception as e:
            print(f"  OLD failed: {e}")
        
        # Build with NEW config
        try:
            slips_new = build_with_config(legs_df, cfg_new, args.legs, args.sort_mode)
            if not slips_new.empty and eval_df is not None:
                actual_new = calc_actual_hit_rate(slips_new, eval_df)
                results_new.append({
                    "run": run_dir.name,
                    "slips": len(slips_new),
                    "avg_hit_prob": slips_new["hit_prob"].mean(),
                    "max_hit_prob": slips_new["hit_prob"].max(),
                    **actual_new,
                })
                print(f"  NEW: {len(slips_new)} slips, avg_hit_prob={slips_new['hit_prob'].mean():.3f}, "
                      f"actual={actual_new['hits']}/{actual_new['evaluated']}")
        except Exception as e:
            print(f"  NEW failed: {e}")
    
    # Summary
    print("\n" + "=" * 60)
    print("MULTI-REPLAY SIMULATION SUMMARY")
    print("=" * 60)
    
    if results_old and results_new:
        df_old = pd.DataFrame(results_old)
        df_new = pd.DataFrame(results_new)
        
        print("\n[OLD CONFIG] Pre-constraint (strict)")
        print(f"  Runs tested: {len(df_old)}")
        print(f"  Avg hit_prob (mean): {df_old['avg_hit_prob'].mean():.4f}")
        print(f"  Max hit_prob (mean): {df_old['max_hit_prob'].mean():.4f}")
        
        total_hits_old = df_old["hits"].sum()
        total_eval_old = df_old["evaluated"].sum()
        if total_eval_old > 0:
            print(f"  Actual hit rate: {total_hits_old}/{total_eval_old} = {total_hits_old/total_eval_old:.1%}")
        
        print("\n[NEW CONFIG] With constraints (current)")
        print(f"  Runs tested: {len(df_new)}")
        print(f"  Avg hit_prob (mean): {df_new['avg_hit_prob'].mean():.4f}")
        print(f"  Max hit_prob (mean): {df_new['max_hit_prob'].mean():.4f}")
        
        total_hits_new = df_new["hits"].sum()
        total_eval_new = df_new["evaluated"].sum()
        if total_eval_new > 0:
            print(f"  Actual hit rate: {total_hits_new}/{total_eval_new} = {total_hits_new/total_eval_new:.1%}")
        
        print("\n[DELTA]")
        delta_prob = df_new["avg_hit_prob"].mean() - df_old["avg_hit_prob"].mean()
        print(f"  Avg hit_prob: {delta_prob:+.4f}")
        
        if total_eval_old > 0 and total_eval_new > 0:
            delta_actual = (total_hits_new/total_eval_new) - (total_hits_old/total_eval_old)
            print(f"  Actual hit rate: {delta_actual:+.1%}")
            
            if delta_actual >= 0:
                print("\n✓ NEW constraints improve or maintain actual hit rate")
            else:
                print("\n⚠ NEW constraints reduced actual hit rate")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
