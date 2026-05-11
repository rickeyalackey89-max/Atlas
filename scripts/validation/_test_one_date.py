#!/usr/bin/env python
"""Quick test of marketed slip builder on one date."""

import sys
import pickle
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Atlas.core.marketed_slip_builder import MarketedSlipBuilder

# Load one date of data
cache_path = Path('data/model/_v17_resim_cache.pkl')
with open(cache_path, 'rb') as f:
    cache = pickle.load(f)

cv = cache['cv']
dates = sorted(cv['game_date'].unique())
test_date = dates[0]  # First date
date_df = cv[cv['game_date'] == test_date].copy()

print(f'Testing on date {test_date}')
print(f'Available legs: {len(date_df)}')

# Show tier distribution
for tier in ['GOBLIN', 'STANDARD', 'DEMON']:
    n = len(date_df[date_df['tier'] == tier])
    print(f'  {tier}: {n} legs')

# Test current config
config = {
    "enabled": True,
    "calibration_path": "data/model/marketed_calibration.json",
    "excluded_stats": ["BLK", "STL", "TO"],
    "min_thresholds": {
        "GOBLIN": 0.60,
        "STANDARD": 0.40,
        "DEMON": 0.45,
    },
    "direction_filters": {},
    "correlation": {
        "same_team_penalty": 0.03,
        "hedge_bonus": 0.015,
        "blowout_penalty": 0.02,
    },
}

builder = MarketedSlipBuilder(config)
slips = builder.build_slips(date_df)

print(f'\\nBuilt {len(slips)} slips:')
for i, slip in enumerate(slips):
    label = slip['label']
    n_legs = len(slip['legs'])
    hit_prob = slip.get('hit_prob', 0)
    
    # Check actual hits
    n_hit = 0
    for leg in slip['legs']:
        # Find truth from date_df
        player = str(leg.get("player", "")).strip()
        stat = str(leg.get("stat", "")).upper()
        direction = str(leg.get("direction", "")).upper()
        line = float(leg.get("line", 0))
        
        mask = (
            (date_df["player"].str.strip() == player) &
            (date_df["stat"].str.upper() == stat) &
            (date_df["direction"].str.upper() == direction) &
            (abs(date_df["line"] - line) < 0.01)
        )
        
        if mask.any():
            hit = bool(date_df[mask]["hit"].iloc[0])
            if hit:
                n_hit += 1
    
    all_hit = (n_hit == n_legs)
    print(f'  {i+1}. {label}: {n_hit}/{n_legs} hit = {"WIN" if all_hit else "LOSS"} (pred: {hit_prob:.1%})')
    
    # Show leg details
    for j, leg in enumerate(slip['legs']):
        tier = leg.get('tier', 'UNK')
        player = leg.get('player', 'UNK')
        stat = leg.get('stat', 'UNK')
        direction = leg.get('direction', 'UNK')
        line = leg.get('line', 0)
        p_cal = leg.get('p_cal_marketed', leg.get('p_cal', 0))
        print(f'    {j+1}. {player} {stat} {direction} {line} ({tier}, p={p_cal:.2f})')