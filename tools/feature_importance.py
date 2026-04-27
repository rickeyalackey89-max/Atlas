"""Extract feature importances from v17 GBM ensemble models."""
import lightgbm as lgb
import json, glob
import numpy as np

meta = json.loads(open("data/model/ensemble/ensemble_meta.json").read())
features = meta["features"]
print(f"v17 features ({len(features)}): {features}\n")

gain_totals = np.zeros(len(features))
split_totals = np.zeros(len(features))
n_models = 0

for mf in sorted(glob.glob("data/model/ensemble/posthoc_calibrator_gbm_*.txt")):
    bst = lgb.Booster(model_file=mf)
    gain = bst.feature_importance(importance_type="gain")
    split = bst.feature_importance(importance_type="split")
    gain_totals += gain
    split_totals += split
    n_models += 1

print(f"Loaded {n_models} models\n")

gain_avg = gain_totals / n_models
split_avg = split_totals / n_models

idx = np.argsort(gain_avg)[::-1]
header = f"{'Feature':<25} {'Avg Gain':>12} {'Avg Splits':>12} {'Gain Rank':>10}"
print(header)
print("-" * len(header))
for rank, i in enumerate(idx, 1):
    print(f"{features[i]:<25} {gain_avg[i]:>12.1f} {split_avg[i]:>12.1f} {rank:>10}")

# Also show OVER vs UNDER breakdown
print("\n\n=== OVER models (7) ===")
gain_over = np.zeros(len(features))
n_over = 0
for mf in sorted(glob.glob("data/model/ensemble/posthoc_calibrator_gbm_over_*.txt")):
    bst = lgb.Booster(model_file=mf)
    gain_over += bst.feature_importance(importance_type="gain")
    n_over += 1
gain_over /= max(n_over, 1)
idx_o = np.argsort(gain_over)[::-1]
print(f"{'Feature':<25} {'Avg Gain':>12} {'Rank':>6}")
print("-" * 45)
for rank, i in enumerate(idx_o, 1):
    print(f"{features[i]:<25} {gain_over[i]:>12.1f} {rank:>6}")

print("\n\n=== UNDER models (7) ===")
gain_under = np.zeros(len(features))
n_under = 0
for mf in sorted(glob.glob("data/model/ensemble/posthoc_calibrator_gbm_under_*.txt")):
    bst = lgb.Booster(model_file=mf)
    gain_under += bst.feature_importance(importance_type="gain")
    n_under += 1
gain_under /= max(n_under, 1)
idx_u = np.argsort(gain_under)[::-1]
print(f"{'Feature':<25} {'Avg Gain':>12} {'Rank':>6}")
print("-" * 45)
for rank, i in enumerate(idx_u, 1):
    print(f"{features[i]:<25} {gain_under[i]:>12.1f} {rank:>6}")
