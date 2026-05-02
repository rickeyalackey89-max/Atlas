#!/usr/bin/env python
"""Compare trainer vs validator performance gap."""

import pickle
from pathlib import Path

# Load cache
cache_path = Path('data/model/_v17_resim_cache.pkl')
with open(cache_path, 'rb') as f:
    cache = pickle.load(f)

cv = cache['cv']
dates = sorted(cv['game_date'].unique())

print('Date corpus comparison:')
print(f'Total dates in cache: {len(dates)}')
print(f'Trainer old sample (first 10): {dates[:10]}')
print(f'Trainer new sample (first 25): {dates[:25]}') 
print(f'Validator used all {len(dates)} dates')

# Check sample composition
print('\\nSample composition:')
for n_dates in [10, 25, len(dates)]:
    sample_dates = dates[:n_dates]
    sample_cv = cv[cv['game_date'].isin(sample_dates)]
    print(f'{n_dates:2d} dates: {len(sample_cv):,} legs')

# Show date range
print(f'\\nDate range: {dates[0]} to {dates[-1]}')
print('First 10:', dates[:10])
print('Next 15:', dates[10:25])
print('Remaining:', len(dates) - 25)