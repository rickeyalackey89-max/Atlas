#!/usr/bin/env python
import pickle
import pandas as pd

cache_path = 'data/model/_v17_resim_cache.pkl'
with open(cache_path, 'rb') as f:
    cache = pickle.load(f)

cv = cache['cv']
print('Cache keys:', list(cache.keys()))
print('CV shape:', cv.shape)
print('CV columns:', list(cv.columns))

# Check if hit column exists
if 'hit' in cv.columns:
    print(f'\nHit rate: {cv["hit"].mean():.3f}')
    print(f'Hit values: {cv["hit"].value_counts()}')
else:
    print('\nNo hit column found!')
    
print(f'\nTier distribution:')
print(cv['tier'].value_counts())

# Sample with key columns
sample_cols = ['player', 'stat', 'line', 'direction', 'tier', 'p_cal']
if 'hit' in cv.columns:
    sample_cols.append('hit')
if 'l20_edge' in cv.columns:
    sample_cols.append('l20_edge')
if 'player_dir_te' in cv.columns:
    sample_cols.append('player_dir_te')

sample = cv.head(5)[sample_cols]
print(f'\nSample data:')
print(sample.to_string())