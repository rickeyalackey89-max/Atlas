"""
Smart merge to add essential columns without duplicating rows.
"""
import pickle
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    print("=== Smart Merge for v17 Cache ===")
    
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
    
    # Create a unique subset from v16 for merging
    # Drop duplicates based on merge keys, keeping the first occurrence
    print("Creating unique v16 subset...")
    v16_subset = v16_cv[merge_keys + essential_cols].copy()
    v16_subset = v16_subset.drop_duplicates(subset=merge_keys, keep='first')
    print(f"v16 subset: {len(v16_subset)} unique legs")
    
    # Save original v17 size
    original_size = len(v17_cv)
    print(f"Original v17 size: {original_size}")
    
    # Perform the merge
    print("Merging...")
    v17_cv_merged = v17_cv.merge(v16_subset, on=merge_keys, how='left', suffixes=('', '_v16'))
    
    print(f"After merge: {len(v17_cv_merged)} legs")
    
    # Check for unexpected size increase
    if len(v17_cv_merged) > original_size:
        print(f"ERROR: Merge created {len(v17_cv_merged) - original_size} extra rows!")
        print("This suggests duplicate keys in the merge. Aborting.")
        return 1
    
    # Check merge success for each column
    added_cols = []
    for col in essential_cols:
        if col in v17_cv_merged.columns:
            matched = v17_cv_merged[col].notna().sum()
            total = len(v17_cv_merged)
            print(f"{col}: {matched}/{total} rows ({matched/total*100:.1f}%)")
            added_cols.append(col)
    
    print(f"\nSuccessfully added {len(added_cols)} columns: {added_cols}")
    
    # Update the cache
    v17_cache["cv"] = v17_cv_merged
    
    # Save
    with open(v17_cache_path, "wb") as f:
        pickle.dump(v17_cache, f)
    
    print(f"✓ Updated v17 cache")
    print(f"Final v17 cache: {len(v17_cv_merged)} legs, {len(v17_cv_merged.columns)} columns")
    
    return 0

if __name__ == "__main__":
    main()