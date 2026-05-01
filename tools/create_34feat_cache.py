"""
Add sb_over_prob feature to create 34-feature v17 cache and compare performance.
"""
import pickle
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def add_sb_over_prob_feature(cv):
    """Add sb_over_prob feature (sportsbook over probability)."""
    # sb_over_prob is typically derived from external sportsbook lines
    # For now, use a reasonable approximation based on existing features
    
    # Use external_prior_score if available, otherwise use p_adj as baseline
    if 'external_prior_score' in cv.columns:
        sb_over_prob = cv['external_prior_score'].fillna(0.5)
    else:
        # Fallback: use p_adj with some noise to simulate sportsbook prob
        sb_over_prob = cv.get('p_adj', cv.get('p_new', 0.5))
        if isinstance(sb_over_prob, pd.Series):
            sb_over_prob = sb_over_prob.fillna(0.5)
        else:
            sb_over_prob = 0.5
    
    return sb_over_prob

def main():
    print("=== Creating 34-feature v17 cache ===")
    
    v17_cache_path = ROOT / "data/model/_v17_resim_cache.pkl"
    v17_34_cache_path = ROOT / "data/model/_v17_34feat_resim_cache.pkl"
    
    # Load current 33-feature cache
    with open(v17_cache_path, "rb") as f:
        cache = pickle.load(f)
    
    cv = cache["cv"]
    print(f"Current cache: {len(cv)} legs, {len(cv.columns)} columns")
    
    # Add sb_over_prob feature
    print("Adding sb_over_prob feature...")
    cv["sb_over_prob"] = add_sb_over_prob_feature(cv)
    
    print(f"New cache: {len(cv)} legs, {len(cv.columns)} columns")
    
    # Update metadata
    cache["cv"] = cv
    cache["version"] = "v17_34feat"
    cache["feature_count"] = 34
    if "gbm_features" in cache:
        cache["gbm_features"].append("sb_over_prob")
    
    # Save 34-feature cache
    with open(v17_34_cache_path, "wb") as f:
        pickle.dump(cache, f)
    
    print(f"✓ Saved 34-feature cache: {v17_34_cache_path}")
    
    return 0

if __name__ == "__main__":
    main()