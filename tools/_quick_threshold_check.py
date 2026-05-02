#!/usr/bin/env python
"""Quick check of p_cal distributions vs thresholds."""

import pickle
from pathlib import Path

# Load cache and check threshold stats
cache_path = Path('data/model/_v17_resim_cache.pkl')
with open(cache_path, 'rb') as f:
    cache = pickle.load(f)

cv = cache['cv']
dates = sorted(cv['game_date'].unique())[:10]
cv_sample = cv[cv['game_date'].isin(dates)]

print(f'Sample size: {len(cv_sample)} legs from {len(dates)} dates')

# Check p_cal distribution by tier
for tier in ['GOBLIN', 'STANDARD', 'DEMON']:
    tier_df = cv_sample[cv_sample['tier'] == tier]
    if len(tier_df) > 0:
        p_cal_stats = tier_df['p_cal'].describe()
        print(f'{tier} tier (n={len(tier_df)}):')
        print(f'  p_cal: min={p_cal_stats["min"]:.3f}, median={p_cal_stats["50%"]:.3f}, max={p_cal_stats["max"]:.3f}')
        
        # Check how many would pass current thresholds
        current_thresholds = {'GOBLIN': 0.60, 'STANDARD': 0.40, 'DEMON': 0.45}
        threshold = current_thresholds[tier]
        passing = (tier_df['p_cal'] >= threshold).sum()
        print(f'  {passing}/{len(tier_df)} ({passing/len(tier_df)*100:.1f}%) pass threshold {threshold}')