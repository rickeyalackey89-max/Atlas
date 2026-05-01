"""
GBM 34-feature test trainer - separate from production gbm_v12_train.py
Tests 34-feature model performance vs 33-feature baseline.
"""
import argparse
import json
import pickle
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logit as sp_logit
from sklearn.model_selection import LeavePGroupsOut

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# 34-feature set (33 base + sb_over_prob)
FEATS_34 = [
    "z_line", "min_cv", "is_combo", "bp_score_gated", "bp_has",
    "is_assists", "is_threes", "games_norm", "thin_flag", "line_norm",
    "is_home_feat", "min_sensitivity", "game_total_norm", "is_b2b",
    "l20_edge", "l10_has", "margin", "stat_cat", "tier_cat", "l40_hr",
    "logit_p_x_demon", "player_te", "player_stat_te", "player_dir_te",
    "player_n_norm", "line_dist", "tail_risk", "line_tightness",
    "margin_x_under", "q_blowout", "rate_cv", "abs_logit_p", "q_x_under",
    "sb_over_prob",
]

CAT_FEATURES = ["stat_cat", "tier_cat"]
CAT_IDX = [FEATS_34.index(f) for f in CAT_FEATURES]

PARAMS_OVER = {
    "objective": "binary", "metric": "binary_logloss",
    "max_depth": 8, "num_leaves": 30,
    "learning_rate": 0.03, "min_child_samples": 200,
    "feature_fraction": 0.8, "bagging_fraction": 0.8,
    "bagging_freq": 1, "lambda_l2": 1.0, "verbose": -1,
}
PARAMS_UNDER = {
    "objective": "binary", "metric": "binary_logloss",
    "max_depth": 11, "num_leaves": 50,
    "learning_rate": 0.03, "min_child_samples": 150,
    "feature_fraction": 0.8, "bagging_fraction": 0.8,
    "bagging_freq": 1, "lambda_l2": 6.0, "verbose": -1,
}

SEEDS = [65536, 9999, 137, 999, 98765, 54321, 12345]
N_ROUNDS = 200
TEMP_CANDIDATES = [1.00, 1.02, 1.04, 1.06, 1.08, 1.10, 1.12]

def main():
    parser = argparse.ArgumentParser(description="Test 34-feature GBM performance")
    args = parser.parse_args()
    
    print("=== GBM 34-Feature Test ===")
    
    # Load 34-feature cache
    cache_path = ROOT / "data/model/_v17_34feat_resim_cache.pkl"
    print(f"Loading cache: {cache_path}")
    
    with open(cache_path, "rb") as f:
        cache = pickle.load(f)
    
    cv = cache["cv"]
    dates = sorted(cv["game_date"].unique())
    
    print(f"Cache: {len(cv)} legs, {len(dates)} dates")
    print(f"Date range: {dates[0]} to {dates[-1]}")
    
    # Check feature availability
    missing_feats = [f for f in FEATS_34 if f not in cv.columns]
    if missing_feats:
        print(f"ERROR: Missing features: {missing_feats}")
        return 1
    
    print(f"✓ All 34 features present")
    
    # LODO cross-validation
    print("\n=== LODO Cross-Validation ===")
    
    X = cv[FEATS_34].values
    y = cv["hit"].values.astype(float)
    groups = cv["game_date"].values
    
    lpgo = LeavePGroupsOut(n_groups=1)
    fold_results = []
    
    for fold_idx, (train_idx, test_idx) in enumerate(lpgo.split(X, y, groups)):
        test_date = pd.Series(groups).iloc[test_idx].iloc[0]
        
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        
        # Split by direction for separate models
        train_df = cv.iloc[train_idx]
        test_df = cv.iloc[test_idx]
        
        over_mask_train = train_df["direction"] == "OVER"
        over_mask_test = test_df["direction"] == "OVER"
        
        # Train OVER model
        over_train = lgb.Dataset(X_train[over_mask_train], y_train[over_mask_train], 
                                categorical_feature=CAT_IDX)
        over_model = lgb.train(PARAMS_OVER, over_train, N_ROUNDS)
        
        # Train UNDER model  
        under_train = lgb.Dataset(X_train[~over_mask_train], y_train[~over_mask_train],
                                 categorical_feature=CAT_IDX)
        under_model = lgb.train(PARAMS_UNDER, under_train, N_ROUNDS)
        
        # Predict
        preds = np.zeros(len(test_idx))
        preds[over_mask_test] = over_model.predict(X_test[over_mask_test])
        preds[~over_mask_test] = under_model.predict(X_test[~over_mask_test])
        
        # Compute Brier
        fold_brier = np.mean((preds - y_test) ** 2)
        fold_results.append({
            "date": test_date,
            "brier": fold_brier,
            "n": len(test_idx)
        })
        
        print(f"  Fold {fold_idx+1:2d}/{len(dates)}: {test_date}  N={len(test_idx):4d}  Brier={fold_brier:.6f}")
    
    # Overall results
    overall_brier = np.mean([r["brier"] for r in fold_results])
    
    print(f"\n=== 34-Feature Results ===")
    print(f"LODO Brier: {overall_brier:.6f}")
    print(f"Baseline (33-feat): 0.200748")
    print(f"Difference: {(overall_brier - 0.200748)*1000:+.1f} mB")
    
    if overall_brier < 0.200748:
        print("✅ 34-feature model is BETTER")
        recommendation = "34-feature"
    else:
        print("❌ 33-feature model is BETTER") 
        recommendation = "33-feature"
    
    print(f"\nRecommendation: Use {recommendation} model")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())