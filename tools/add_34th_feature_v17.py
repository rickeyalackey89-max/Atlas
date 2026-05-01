"""
Add the missing 34th feature (sb_over_prob) to v17 cache.
"""
import pickle
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    print("=== Adding sb_over_prob (34th feature) to v17 cache ===")
    
    v17_cache_path = ROOT / "data/model/_v17_resim_cache.pkl"
    
    with open(v17_cache_path, "rb") as f:
        cache = pickle.load(f)
    
    cv = cache["cv"]
    print(f"Current: {len(cv)} legs, {len(cv.columns)} columns")
    
    # Add sb_over_prob feature
    # This is typically a sportsbook probability feature - for now add as zeros since we don't have sportsbook data
    cv["sb_over_prob"] = 0.5  # neutral default when no sportsbook data available
    
    print(f"Added sb_over_prob column")
    print(f"Updated: {len(cv)} legs, {len(cv.columns)} columns")
    
    # Update cache metadata
    cache["cv"] = cv
    cache["feature_count"] = 34
    if "gbm_features" in cache:
        current_features = cache["gbm_features"]
        if "sb_over_prob" not in current_features:
            cache["gbm_features"] = current_features + ["sb_over_prob"]
    
    # Save updated cache
    with open(v17_cache_path, "wb") as f:
        pickle.dump(cache, f)
    
    print("✓ v17 cache updated with 34th feature (sb_over_prob)")
    return 0

if __name__ == "__main__":
    main()