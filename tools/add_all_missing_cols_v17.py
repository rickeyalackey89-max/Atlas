"""
Add all missing columns from v16 cache that the GBM trainer needs.
"""
import pickle
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    print("=== Adding All Missing GBM Columns to v17 ===")
    
    v16_cache_path = ROOT / "data/model/_v16_resim_cache.pkl"
    v17_cache_path = ROOT / "data/model/_v17_resim_cache.pkl"
    
    # Load both caches
    with open(v16_cache_path, "rb") as f:
        v16_cache = pickle.load(f)
    
    with open(v17_cache_path, "rb") as f:
        v17_cache = pickle.load(f)
    
    v16_cv = v16_cache["cv"]
    v17_cv = v17_cache["cv"]
    
    print(f"v16 cache: {len(v16_cv)} legs, {len(v16_cv.columns)} columns")
    print(f"v17 cache: {len(v17_cv)} legs, {len(v17_cv.columns)} columns")
    
    # Essential columns the trainer needs
    essential_cols = [
        'rate_mean', 'rate_std', 'min_mean', 'min_std', 
        'opp', 'is_home', 'spread', 'minutes_s',
        'is_star', 'fragility', 'usage_dep',
        'recent_form_blend', 'opp_defense_strength',
        'games_used', 'thin_window_mult',
        'external_prior_score', 'external_prior_sources',
        'is_questionable', 'rotowire_game_spread'
    ]
    
    # Merge keys
    merge_keys = ['game_date', 'player', 'stat', 'line', 'direction']
    
    added_count = 0
    for col in essential_cols:
        if col in v16_cv.columns and col not in v17_cv.columns:
            print(f"Adding {col}...")
            
            v16_subset = v16_cv[merge_keys + [col]].copy()
            
            # Before merge - check current size
            pre_size = len(v17_cv)
            
            # Merge
            v17_cv = v17_cv.merge(v16_subset, on=merge_keys, how='left', suffixes=('', '_v16'))
            
            # Check if merge created duplicates (shouldn't happen with left join)
            if len(v17_cv) > pre_size:
                print(f"  Warning: merge increased size from {pre_size} to {len(v17_cv)}")
            
            # Check merge success
            if col in v17_cv.columns:
                matched = v17_cv[col].notna().sum()
                total = len(v17_cv)
                print(f"  Merged {matched}/{total} rows ({matched/total*100:.1f}%)")
                added_count += 1
            else:
                print(f"  Failed to add {col}")
    
    print(f"\nSuccessfully added {added_count} columns")
    
    # Update the cache
    v17_cache["cv"] = v17_cv
    
    # Save
    with open(v17_cache_path, "wb") as f:
        pickle.dump(v17_cache, f)
    
    print(f"✓ Updated v17 cache")
    print(f"Final v17 cache: {len(v17_cv)} legs, {len(v17_cv.columns)} columns")
    
    return 0

if __name__ == "__main__":
    main()