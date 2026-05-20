"""
Test GBM trainer cache loading with v17 cache.
"""
import sys
from pathlib import Path

# Setup path like gbm_v12_train.py
sys.path.insert(0, str(Path(r"C:/Users/13142/Atlas/NBA/src")))

import pickle
import pandas as pd

def main():
    print("=== GBM v17 Cache Loading Test ===")
    
    # Test cache path
    cache_path = Path(r"C:/Users/13142/Atlas/NBA/data/model/_v17_resim_cache.pkl")
    print(f"Loading cache: {cache_path}")
    
    if not cache_path.exists():
        print("ERROR: v17 cache not found")
        return 1
    
    # Load like gbm_v12_train.py does
    print("Loading cache...")
    with open(cache_path, "rb") as f:
        cache = pickle.load(f)
    
    cv = cache["cv"]
    dates = cache.get("dates", [])
    
    print(f"✓ Cache loaded: {len(cv)} legs, {len(dates)} dates")
    print(f"✓ Version: {cache.get('version', 'unknown')}")
    
    # Check required features exist
    FEATS = [
        "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
        "is_assists", "is_threes", "games_norm", "thin_flag", "line_norm",
        "is_home_feat", "min_sensitivity", "game_total_norm", "is_b2b",
        "l20_edge", "l10_has", "margin", "stat_cat", "tier_cat", "l40_hr",
        "logit_p_x_demon", "player_te", "player_stat_te", "player_dir_te",
        "player_n_norm", "line_dist", "tail_risk", "line_tightness",
        "margin_x_under", "q_blowout", "rate_cv", "abs_logit_p", "q_x_under",
    ]
    
    missing = [f for f in FEATS if f not in cv.columns]
    if missing:
        print(f"ERROR: Missing features: {missing}")
        return 1
    
    print(f"✓ All {len(FEATS)} GBM features present")
    
    # Test feature matrix creation
    import numpy as np
    try:
        X_all = np.nan_to_num(cv[FEATS].values.astype(float), nan=0.0)
        y_all = cv["hit"].values.astype(float) if "hit" in cv.columns else None
        
        print(f"✓ Feature matrix: {X_all.shape}")
        if y_all is not None:
            print(f"✓ Target labels: {len(y_all)} (hit rate: {y_all.mean():.1%})")
        
        # Test date array 
        date_arr = cv["game_date"].astype(str).str[:10].values
        unique_dates = sorted(set(date_arr))
        print(f"✓ Date array: {len(unique_dates)} unique dates")
        print(f"  Date range: {unique_dates[0]} to {unique_dates[-1]}")
        
    except Exception as e:
        print(f"ERROR in feature processing: {e}")
        return 1
    
    print(f"\n🎉 SUCCESS: GBM trainer can load and process v17 cache!")
    print(f"Cache is ready for LODO training with {len(cv):,} legs")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
