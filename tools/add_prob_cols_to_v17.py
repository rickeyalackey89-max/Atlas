"""
Check v16 cache columns and add missing probability columns to v17 cache.
"""
import pickle
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    print("=== v16 Cache Column Check ===")
    
    v16_cache_path = ROOT / "data/model/_v16_resim_cache.pkl"
    v17_cache_path = ROOT / "data/model/_v17_resim_cache.pkl"
    
    # Load both caches
    with open(v16_cache_path, "rb") as f:
        v16_cache = pickle.load(f)
    
    with open(v17_cache_path, "rb") as f:
        v17_cache = pickle.load(f)
    
    v16_cv = v16_cache["cv"]
    v17_cv = v17_cache["cv"]
    
    print(f"v16 cache columns ({len(v16_cv.columns)}):")
    for i, col in enumerate(v16_cv.columns):
        print(f"  {i+1:2d}. {col}")
    
    print(f"\nv16 probability columns:")
    v16_prob_cols = [col for col in v16_cv.columns if any(p in col.lower() for p in ['p_', 'prob'])]
    for col in v16_prob_cols:
        print(f"  {col}")
    
    # Find missing columns in v17
    missing_cols = set(v16_cv.columns) - set(v17_cv.columns)
    print(f"\nMissing columns in v17: {sorted(missing_cols)}")
    
    # Add essential probability columns to v17
    essential_prob_cols = ['p_new', 'p_raw', 'p', 'p_role', 'p_adj', 'p_for_cal', 'p_cal']
    added_cols = []
    
    for col in essential_prob_cols:
        if col in v16_cv.columns and col not in v17_cv.columns:
            print(f"\nAdding {col} to v17 cache...")
            
            # Merge the column based on game_date + player + stat + line + direction
            merge_keys = ['game_date', 'player', 'stat', 'line', 'direction']
            
            # Check if all merge keys exist in both
            v16_keys = set(v16_cv.columns)
            v17_keys = set(v17_cv.columns)
            available_keys = [k for k in merge_keys if k in v16_keys and k in v17_keys]
            
            if len(available_keys) >= 4:  # Need at least 4 keys for good match
                v16_subset = v16_cv[available_keys + [col]].copy()
                
                # Merge
                v17_cv = v17_cv.merge(v16_subset, on=available_keys, how='left', suffixes=('', '_v16'))
                
                # Check merge success
                matched = v17_cv[col].notna().sum()
                total = len(v17_cv)
                print(f"  Merged {matched}/{total} rows ({matched/total*100:.1f}%)")
                
                if matched > total * 0.8:  # Good match rate
                    added_cols.append(col)
                else:
                    print(f"  Poor match rate, dropping {col}")
                    v17_cv = v17_cv.drop(columns=[col])
            else:
                print(f"  Insufficient merge keys for {col}")
    
    if added_cols:
        print(f"\nSuccessfully added columns: {added_cols}")
        
        # Update the cache
        v17_cache["cv"] = v17_cv
        
        with open(v17_cache_path, "wb") as f:
            pickle.dump(v17_cache, f)
        
        print(f"✓ Updated v17 cache with {len(added_cols)} new columns")
        print(f"New v17 cache has {len(v17_cv)} legs and {len(v17_cv.columns)} columns")
    else:
        print("No columns added to v17 cache")
    
    return 0

if __name__ == "__main__":
    main()