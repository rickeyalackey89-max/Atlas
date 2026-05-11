"""
Quick test to verify the v17 cache works with the GBM trainer.
"""
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

def main():
    print("=== v17 Cache Compatibility Test ===")
    
    # Load v17 cache
    v17_cache_path = ROOT / "data/model/_v17_resim_cache.pkl"
    print(f"Loading v17 cache: {v17_cache_path}")
    
    if not v17_cache_path.exists():
        print(f"ERROR: v17 cache not found at {v17_cache_path}")
        return 1
    
    with open(v17_cache_path, "rb") as f:
        v17_cache = pickle.load(f)
    
    cv = v17_cache["cv"]
    print(f"Loaded: {len(cv)} legs, {len(cv.columns)} columns")
    print(f"Version: {v17_cache.get('version')}")
    print(f"Dates: {len(v17_cache.get('dates', []))} dates")
    
    # Check required GBM features
    required_feats = [
        "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
        "is_assists", "is_threes", "games_norm", "thin_flag", "line_norm",
        "is_home_feat", "min_sensitivity", "game_total_norm", "is_b2b",
        "l20_edge", "l10_has", "margin", "stat_cat", "tier_cat", "l40_hr",
        "logit_p_x_demon", "player_te", "player_stat_te", "player_dir_te",
        "player_n_norm", "line_dist", "tail_risk", "line_tightness",
        "margin_x_under", "q_blowout", "rate_cv", "abs_logit_p", "q_x_under",
    ]
    
    print(f"\nFeature validation:")
    missing = []
    for feat in required_feats:
        if feat in cv.columns:
            print(f"  ✓ {feat}")
        else:
            print(f"  ✗ {feat} MISSING")
            missing.append(feat)
    
    if missing:
        print(f"\nERROR: Missing features: {missing}")
        return 1
    
    # Check data types and basic stats
    print(f"\nData validation:")
    print(f"  Rows: {len(cv):,}")
    print(f"  Features: {len(required_feats)}")
    print(f"  Date range: {cv['game_date'].min()} to {cv['game_date'].max()}")
    
    if "hit" in cv.columns:
        hit_rate = cv["hit"].mean()
        print(f"  Overall hit rate: {hit_rate:.1%}")
    
    # Test feature arrays can be created
    import numpy as np
    try:
        X = cv[required_feats].values.astype(float)
        X_clean = np.nan_to_num(X, nan=0.0)
        print(f"  Feature matrix shape: {X_clean.shape}")
        print(f"  NaN values replaced: {np.isnan(X).sum()}")
        print(f"  Feature means range: [{X_clean.mean(axis=0).min():.3f}, {X_clean.mean(axis=0).max():.3f}]")
    except Exception as e:
        print(f"  ERROR creating feature matrix: {e}")
        return 1
    
    print(f"\n🎉 SUCCESS: v17 cache is fully compatible!")
    print(f"Ready for GBM training with {len(cv):,} legs and {len(required_feats)} features")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())