"""
Check what columns are available in the v17 cache.
"""
import pickle
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    print("=== v17 Cache Column Check ===")
    
    v17_cache_path = ROOT / "data/model/_v17_resim_cache.pkl"
    
    with open(v17_cache_path, "rb") as f:
        cache = pickle.load(f)
    
    cv = cache["cv"]
    print(f"Cache has {len(cv)} legs and {len(cv.columns)} columns")
    print(f"\nAll columns:")
    for i, col in enumerate(cv.columns):
        print(f"  {i+1:2d}. {col}")
    
    # Look for probability columns
    prob_cols = [col for col in cv.columns if any(p in col.lower() for p in ['p_', 'prob'])]
    print(f"\nProbability-related columns: {prob_cols}")
    
    return 0

if __name__ == "__main__":
    main()