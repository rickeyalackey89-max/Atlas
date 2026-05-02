#!/usr/bin/env python3
"""
Daily Graphics CSV Generator - Top 10 Picks by Tier
===========================================
Extracts top 10 GOBLIN, STANDARD, and DEMON picks for daily paid graphics.

Usage:
    python -m tools.generate_daily_graphics_csv --run-id 20260430_182420
    python -m tools.generate_daily_graphics_csv --latest  # uses most recent run
"""

import argparse
import pandas as pd
import os
from pathlib import Path
from datetime import datetime

def find_repo_root(start_path=None):
    """Find the repository root directory."""
    if start_path is None:
        start_path = Path(__file__).parent
    else:
        start_path = Path(start_path)
    
    current = start_path.resolve()
    while current != current.parent:
        if (current / "config.yaml").exists() and (current / "src").exists():
            return current
        current = current.parent
    
    raise RuntimeError("Could not find Atlas repository root")

def find_latest_run(runs_dir):
    """Find the most recent run directory."""
    runs = [d for d in os.listdir(runs_dir) if os.path.isdir(os.path.join(runs_dir, d))]
    if not runs:
        raise ValueError("No run directories found")
    return sorted(runs)[-1]

def load_scored_legs(run_path):
    """Load and validate scored legs data."""
    legs_file = os.path.join(run_path, "scored_legs_deduped.csv")
    if not os.path.exists(legs_file):
        raise FileNotFoundError(f"Scored legs file not found: {legs_file}")
    
    df = pd.read_csv(legs_file)
    
    # Validate required columns
    required_cols = ['player', 'stat', 'line', 'direction', 'tier', 'p_cal', 'game_date']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    
    return df

def get_top_picks_by_tier(df, tier, n=10):
    """Get top N picks for a specific tier, ranked by tier-specific selection signal.

    GOBLIN:   p_cal * l20_edge  (model confidence × recent form)
    STANDARD: player_dir_te     (historical hit rate for this player/stat/direction)
    DEMON:    p_cal * l20_edge  (same as GOBLIN)
    """
    import numpy as np
    tier_df = df[df['tier'] == tier].copy()

    if len(tier_df) == 0:
        print(f"Warning: No {tier} picks found")
        return pd.DataFrame()

    # Build tier-specific ranking score — mirrors marketed_slip_builder logic
    p_cal  = pd.to_numeric(tier_df.get('p_cal',        pd.Series(0.5, index=tier_df.index)), errors='coerce').fillna(0.5)
    l20    = pd.to_numeric(tier_df.get('l20_edge',      pd.Series(0.0, index=tier_df.index)), errors='coerce').fillna(0.0).clip(0, 1)
    dir_te = pd.to_numeric(tier_df.get('player_dir_te', pd.Series(0.0, index=tier_df.index)), errors='coerce').fillna(0.0)

    if tier == 'STANDARD':
        tier_df['_rank_score'] = dir_te.values
    else:  # GOBLIN and DEMON
        tier_df['_rank_score'] = (p_cal * l20).values

    tier_df = tier_df.sort_values('_rank_score', ascending=False)
    
    # Select top N and relevant columns for graphics
    graphics_cols = [
        'player', 'stat', 'line', 'direction', 'tier', 'p_cal',
        'team', 'opp', 'game_date', 'start_time'
    ]
    
    # Add available columns only
    available_cols = [col for col in graphics_cols if col in tier_df.columns]
    top_picks = tier_df[available_cols].head(n).copy()
    
    # Add rank and format probability as percentage
    top_picks['rank'] = range(1, len(top_picks) + 1)
    top_picks['hit_probability_pct'] = (top_picks['p_cal'] * 100).round(1)
    
    return top_picks

def generate_graphics_csv(atlas_root, output_file, run_id=None):
    """Generate the daily graphics CSV with top picks by tier."""
    
    runs_dir = os.path.join(atlas_root, "data", "output", "runs")
    
    # Find run directory
    if run_id:
        run_dir = os.path.join(runs_dir, run_id)
        if not os.path.exists(run_dir):
            raise ValueError(f"Run directory not found: {run_dir}")
    else:
        run_id = find_latest_run(runs_dir)
        run_dir = os.path.join(runs_dir, run_id)
    
    print(f"Processing run: {run_id}")
    
    # Load data
    df = load_scored_legs(run_dir)
    print(f"Loaded {len(df)} total legs")
    
    # Get tier distribution
    tier_counts = df['tier'].value_counts()
    print("Tier distribution:")
    for tier, count in tier_counts.items():
        print(f"  {tier}: {count}")
    
    # Extract top picks by tier
    all_picks = []
    
    for tier in ['GOBLIN', 'STANDARD', 'DEMON']:
        top_picks = get_top_picks_by_tier(df, tier, n=10)
        if not top_picks.empty:
            print(f"\\nTop {len(top_picks)} {tier} picks:")
            for _, row in top_picks.head(3).iterrows():  # Show top 3
                print(f"  {row['rank']}. {row['player']} {row['stat']} {row['direction']} {row['line']} ({row['hit_probability_pct']}%)")
            all_picks.append(top_picks)
    
    if not all_picks:
        raise ValueError("No picks found for any tier")
    
    # Combine all picks
    final_df = pd.concat(all_picks, ignore_index=True)
    
    # Add metadata
    final_df['run_id'] = run_id
    final_df['generated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Reorder columns for graphics team
    column_order = [
        'rank', 'tier', 'player', 'team', 'opp', 'stat', 'direction', 'line',
        'hit_probability_pct', 'p_cal', 'game_date', 'start_time', 'run_id', 'generated_at'
    ]
    
    # Include only available columns
    available_order = [col for col in column_order if col in final_df.columns]
    final_df = final_df[available_order]
    
    # Save CSV
    final_df.to_csv(output_file, index=False)
    
    print(f"\\n✅ Daily graphics CSV generated: {output_file}")
    print(f"Total picks: {len(final_df)}")
    print(f"Breakdown: {final_df.groupby('tier').size().to_dict()}")
    
    return final_df

def main():
    parser = argparse.ArgumentParser(description="Generate daily graphics CSV with top picks by tier")
    parser.add_argument("--run-id", help="Specific run ID to process (e.g., 20260430_182420)")
    parser.add_argument("--latest", action="store_true", help="Use the most recent run")
    parser.add_argument("--output", required=True,
                       help="Output CSV file path")
    
    args = parser.parse_args()
    
    if not args.run_id and not args.latest:
        parser.error("Must specify either --run-id or --latest")
    
    try:
        # Find Atlas repository root
        atlas_root = find_repo_root()
        
        df = generate_graphics_csv(
            atlas_root=atlas_root,
            output_file=args.output,
            run_id=args.run_id
        )
        
        print(f"\\n🎨 Ready for graphics team!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())