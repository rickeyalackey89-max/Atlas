"""
Quick script to examine v16 cache columns and understand the feature mismatch
"""
import pickle
import sys
from pathlib import Path

# Add Atlas modules to path  
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

def main():
    v16_cache_path = ROOT / "data/model/_v16_resim_cache.pkl"
    print(f"Loading v16 cache: {v16_cache_path}")
    
    with open(v16_cache_path, "rb") as f:
        v16_cache = pickle.load(f)
    
    cv = v16_cache["cv"]
    print(f"Cache has {len(cv)} rows and {len(cv.columns)} columns")
    print(f"Cache version: {v16_cache.get('version', 'unknown')}")
    print(f"Cache dates: {v16_cache.get('dates', [])[:5]}...")
    
    print(f"\nFirst 20 columns:")
    for i, col in enumerate(cv.columns[:20]):
        print(f"  {i+1:2d}. {col}")
    
    print(f"\nAll columns matching v17 feature names:")
    v17_features = [
        "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
        "is_assists", "is_threes", "games_norm", "thin_flag", "line_norm", 
        "is_home_feat", "min_sensitivity", "game_total_norm", "is_b2b",
        "l20_edge", "l10_has", "margin", "stat_cat", "tier_cat", "l40_hr",
        "logit_p_x_demon", "player_te", "player_stat_te", "player_dir_te", 
        "player_n_norm", "line_dist", "tail_risk", "line_tightness",
        "margin_x_under", "q_blowout", "rate_cv", "abs_logit_p", "q_x_under", "form_z_line"
    ]
    
    matching = [f for f in v17_features if f in cv.columns]
    print(f"Found {len(matching)} matching: {matching}")
    
    print(f"\nAll {len(cv.columns)} columns:")
    for i, col in enumerate(cv.columns):
        print(f"  {i+1:3d}. {col}")

if __name__ == "__main__":
    main()