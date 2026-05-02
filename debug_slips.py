#!/usr/bin/env python
import pickle
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from Atlas.core.marketed_slip_builder import build_marketed_slips

# Load cache
cache_path = 'data/model/_v17_resim_cache.pkl'
with open(cache_path, 'rb') as f:
    cache = pickle.load(f)

cv = cache['cv']

# Use one date of data
test_date = '2026-03-15'
date_legs = cv[cv['game_date'] == test_date].copy()

print(f"Test date: {test_date}")
print(f"Legs available: {len(date_legs)}")
print(f"Hit rate for this date: {date_legs['hit'].mean():.3f}")

# Test config (Phase 1 optimal)
config = {
    "marketed_slips": {
        "enabled": True,
        "calibration_path": "data/model/marketed_calibration.json",
        "excluded_stats": ["BLK", "STL", "TO"],
        "min_thresholds": {
            "GOBLIN": 0.57,
            "STANDARD": 0.30,
            "DEMON": 0.28,
        },
        "direction_filters": {},
        "correlation": {
            "same_team_penalty": 0.03,
            "hedge_bonus": 0.015,
            "blowout_penalty": 0.02,
        },
    }
}

# Build slips
print(f"\nBuilding slips...")
try:
    slips = build_marketed_slips(date_legs, config)
    print(f"Generated {len(slips)} slips")
    
    if len(slips) > 0:
        print(f"\nFirst slip structure:")
        for k, v in slips[0].items():
            print(f"  {k}: {v}")
            
        # Check if any slips won
        wins = sum(1 for slip in slips if slip.get("all_hit", False))
        print(f"\nWin rate: {wins}/{len(slips)} = {wins/len(slips) if len(slips) > 0 else 0:.1%}")
        
    else:
        print("No slips generated!")
        
        # Debug: check what legs qualify
        print(f"\nDebugging qualification...")
        print(f"Tier distribution:")
        print(date_legs['tier'].value_counts())
        
        # Check thresholds
        for tier in ['GOBLIN', 'STANDARD', 'DEMON']:
            tier_legs = date_legs[date_legs['tier'] == tier]
            threshold = config["marketed_slips"]["min_thresholds"][tier]
            qualified = (tier_legs['p_cal'] >= threshold).sum()
            print(f"{tier}: {qualified}/{len(tier_legs)} legs >= {threshold:.2f} threshold")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()