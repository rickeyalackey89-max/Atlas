"""
Check v17 cache metadata and add missing fields if needed.
"""
import pickle
import sys
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    print("=== v17 Cache Metadata Check ===")
    
    v17_cache_path = ROOT / "data/model/_v17_resim_cache.pkl"
    
    with open(v17_cache_path, "rb") as f:
        cache = pickle.load(f)
    
    print(f"Current cache keys: {list(cache.keys())}")
    
    cv = cache["cv"]
    print(f"Cache has {len(cv)} legs")
    
    # Check if we need to add raw_brier
    if "raw_brier" not in cache:
        print("Adding missing raw_brier field...")
        
        # Calculate raw Brier score from the data
        if "hit" in cv.columns and "p_new" in cv.columns:
            hit_arr = cv["hit"].values.astype(float)
            p_arr = cv["p_new"].fillna(0.5).values.astype(float)
            raw_brier = float(np.mean((p_arr - hit_arr) ** 2))
            cache["raw_brier"] = raw_brier
            print(f"  Calculated raw Brier: {raw_brier:.6f}")
        else:
            # Use a reasonable default
            cache["raw_brier"] = 0.25
            print("  Using default raw Brier: 0.25")
    
    # Add any other missing expected fields
    expected_fields = ["cv", "dates", "version", "raw_brier", "gbm_features", "feature_count"]
    for field in expected_fields:
        if field not in cache:
            if field == "gbm_features":
                cache[field] = [
                    "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
                    "is_assists", "is_threes", "games_norm", "thin_flag", "line_norm",
                    "is_home_feat", "min_sensitivity", "game_total_norm", "is_b2b",
                    "l20_edge", "l10_has", "margin", "stat_cat", "tier_cat", "l40_hr",
                    "logit_p_x_demon", "player_te", "player_stat_te", "player_dir_te",
                    "player_n_norm", "line_dist", "tail_risk", "line_tightness",
                    "margin_x_under", "q_blowout", "rate_cv", "abs_logit_p", "q_x_under",
                ]
            elif field == "feature_count":
                cache[field] = 33
            else:
                print(f"  Missing field: {field}")
    
    # Save updated cache
    print("Saving updated cache...")
    with open(v17_cache_path, "wb") as f:
        pickle.dump(cache, f)
    
    print("✓ Cache metadata updated")
    print(f"Final cache keys: {list(cache.keys())}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())