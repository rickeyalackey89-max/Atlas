"""
A/B test for slip constraint changes.
Compares old (strict) vs new (relaxed) constraint configs on historical data.
"""
from __future__ import annotations

import argparse
import copy
import sys
import zipfile
from pathlib import Path

import pandas as pd
import yaml

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Atlas.core.slip_builders import build_slips_by_tier_buckets


def load_bundle_legs(bundle_path: Path) -> tuple[pd.DataFrame | None, dict, pd.DataFrame | None]:
    """Load scored legs and config from a bundle or run directory."""
    legs_df = None
    cfg = {}
    eval_df = None
    
    if bundle_path.is_dir():
        # Load from run directory
        for name in ["scored_legs_deduped.csv", "scored_legs.csv"]:
            p = bundle_path / name
            if p.exists():
                legs_df = pd.read_csv(p)
                break
        
        cfg_path = bundle_path / "config.yaml"
        if cfg_path.exists():
            cfg = yaml.safe_load(cfg_path.read_text())
        else:
            # Load from project root
            root_cfg = Path(__file__).resolve().parents[1] / "config.yaml"
            if root_cfg.exists():
                cfg = yaml.safe_load(root_cfg.read_text())
        
        eval_path = bundle_path / "eval_legs.csv"
        if eval_path.exists():
            eval_df = pd.read_csv(eval_path)
    else:
        # Load from bundle zip
        with zipfile.ZipFile(bundle_path, "r") as zf:
            for name in zf.namelist():
                if "scored_legs" in name and name.endswith(".csv"):
                    with zf.open(name) as f:
                        legs_df = pd.read_csv(f)
                    break
            
            for name in zf.namelist():
                if name.endswith("config.yaml"):
                    with zf.open(name) as f:
                        cfg = yaml.safe_load(f)
                    break
            
            for name in zf.namelist():
                if "eval_legs" in name and name.endswith(".csv"):
                    with zf.open(name) as f:
                        eval_df = pd.read_csv(f)
                    break
    
    return legs_df, cfg, eval_df


def build_with_config(legs_df: pd.DataFrame, cfg: dict, n_legs: int, sort_mode: str) -> pd.DataFrame:
    """Build slips with given config."""
    # Standard mixes and tiers
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
        top_n=50,
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


def calc_hit_rate(slips_df: pd.DataFrame, eval_df: pd.DataFrame | None = None) -> dict:
    """Calculate theoretical hit rate stats from slip hit_prob column."""
    if slips_df.empty:
        return {"slips": 0, "avg_hit_prob": None, "max_hit_prob": None, "avg_ev": None}
    
    return {
        "slips": len(slips_df),
        "avg_hit_prob": slips_df["hit_prob"].mean() if "hit_prob" in slips_df.columns else None,
        "max_hit_prob": slips_df["hit_prob"].max() if "hit_prob" in slips_df.columns else None,
        "avg_ev": slips_df["ev_mult"].mean() if "ev_mult" in slips_df.columns else None,
    }


def identify_same_game_slips(slips_df: pd.DataFrame) -> int:
    """Count slips that have legs from the same game (different teams)."""
    count = 0
    for _, slip in slips_df.iterrows():
        games = []
        teams = []
        for i in range(1, 6):
            game_id = slip.get(f"leg{i}_game_id") or slip.get(f"leg{i}_gameId")
            team = slip.get(f"leg{i}_team")
            if pd.notna(game_id) and game_id:
                games.append(str(game_id))
            if pd.notna(team) and team:
                teams.append(str(team))
        
        # Same game appears twice = same-game slip
        if len(games) != len(set(games)):
            count += 1
    return count


def identify_same_team_pairs(slips_df: pd.DataFrame) -> int:
    """Count slips that have 2 players from same team."""
    count = 0
    for _, slip in slips_df.iterrows():
        teams = []
        for i in range(1, 6):
            team = slip.get(f"leg{i}_team")
            if pd.notna(team) and team:
                teams.append(str(team))
        
        from collections import Counter
        tc = Counter(teams)
        if tc and max(tc.values()) >= 2:
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description="A/B test slip constraints")
    parser.add_argument("bundle", help="Path to bundle zip")
    parser.add_argument("--legs", type=int, default=3, help="Slip size (3, 4, 5)")
    parser.add_argument("--sort-mode", default="ev", help="Sort mode (ev, hit)")
    args = parser.parse_args()
    
    bundle_path = Path(args.bundle)
    if not bundle_path.exists():
        print(f"Bundle not found: {bundle_path}")
        return 1
    
    print(f"Loading bundle: {bundle_path.name}")
    legs_df, base_cfg, eval_df = load_bundle_legs(bundle_path)
    
    if legs_df is None or legs_df.empty:
        print("No scored legs found in bundle")
        return 1
    
    print(f"Loaded {len(legs_df)} legs, eval_df={'YES' if eval_df is not None else 'NO'}")
    
    # Config A: OLD strict constraints
    cfg_old = copy.deepcopy(base_cfg)
    cfg_old.setdefault("slip_build", {})
    cfg_old["slip_build"]["no_same_game_within_slip"] = True
    cfg_old["slip_build"]["max_players_per_team"] = 1
    cfg_old["slip_build"]["min_leg_prob"] = 0.0  # No filter for fair comparison
    
    # Config B: NEW relaxed constraints  
    cfg_new = copy.deepcopy(base_cfg)
    cfg_new.setdefault("slip_build", {})
    cfg_new["slip_build"]["no_same_game_within_slip"] = False
    cfg_new["slip_build"]["max_players_per_team"] = 2
    cfg_new["slip_build"]["min_leg_prob"] = 0.0  # No filter for fair comparison
    
    print(f"\n=== Building {args.legs}-leg slips (sort_mode={args.sort_mode}) ===")
    
    # Build with OLD config
    print("\n[CONFIG A] OLD: no_same_game=True, max_players_per_team=1")
    slips_old = build_with_config(legs_df, cfg_old, args.legs, args.sort_mode)
    stats_old = calc_hit_rate(slips_old, eval_df)
    same_game_old = identify_same_game_slips(slips_old)
    same_team_old = identify_same_team_pairs(slips_old)
    print(f"  Slips: {stats_old['slips']}")
    print(f"  Same-game slips: {same_game_old}")
    print(f"  2-per-team slips: {same_team_old}")
    if stats_old.get("avg_hit_prob") is not None:
        print(f"  Avg hit_prob: {stats_old['avg_hit_prob']:.3f}")
        print(f"  Max hit_prob: {stats_old['max_hit_prob']:.3f}")
        print(f"  Avg EV: {stats_old['avg_ev']:.3f}")
    
    # Build with NEW config
    print("\n[CONFIG B] NEW: no_same_game=False, max_players_per_team=2")
    slips_new = build_with_config(legs_df, cfg_new, args.legs, args.sort_mode)
    stats_new = calc_hit_rate(slips_new, eval_df)
    same_game_new = identify_same_game_slips(slips_new)
    same_team_new = identify_same_team_pairs(slips_new)
    print(f"  Slips: {stats_new['slips']}")
    print(f"  Same-game slips: {same_game_new}")
    print(f"  2-per-team slips: {same_team_new}")
    if stats_new.get("avg_hit_prob") is not None:
        print(f"  Avg hit_prob: {stats_new['avg_hit_prob']:.3f}")
        print(f"  Max hit_prob: {stats_new['max_hit_prob']:.3f}")
        print(f"  Avg EV: {stats_new['avg_ev']:.3f}")
    
    # Summary
    print("\n=== SUMMARY ===")
    print(f"Additional same-game slips enabled: {same_game_new - same_game_old}")
    print(f"Additional 2-per-team slips enabled: {same_team_new - same_team_old}")
    
    if stats_old.get("avg_hit_prob") is not None and stats_new.get("avg_hit_prob") is not None:
        delta = stats_new["avg_hit_prob"] - stats_old["avg_hit_prob"]
        print(f"Avg hit_prob delta: {delta:+.4f}")
        if delta >= -0.001:
            print("✓ Relaxed constraints maintain or improve theoretical hit probability")
        else:
            print("⚠ Relaxed constraints reduced theoretical hit probability")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
