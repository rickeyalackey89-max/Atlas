#!/usr/bin/env python
"""
Simple Production Config Test
Tests the exact production config to confirm baseline win rate.
"""
import copy
import json
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Atlas.core.marketed_slip_builder import MarketedSlipBuilder

def load_data():
    cache_path = Path("data/model/_v17_resim_cache.pkl")
    
    import pickle
    with open(cache_path, "rb") as f:
        cache = pickle.load(f)
    
    cv = cache["cv"] 
    dates = sorted(cv["game_date"].unique())
    
    # Use corpus dates like trainer
    corpus_path = Path("data/telemetry/v17_corpus/corpus_manifest.json")
    if corpus_path.exists():
        with open(corpus_path) as f:
            manifest = json.load(f)
        corpus_dates = set(manifest.get("dates", []))
        train_dates = [d for d in dates if d.replace("-", "") in corpus_dates]
    else:
        train_dates = dates
    
    return cv[cv["game_date"].isin(train_dates)], train_dates

def evaluate_config(cv, dates, config):
    """Same evaluation as trainer"""
    builder = MarketedSlipBuilder(config)
    builder.templates = [
        {"label": "3-leg", "goblin": 1, "standard": 2, "demon": 0},
        {"label": "4-leg", "goblin": 2, "standard": 2, "demon": 0},
        {"label": "5-leg", "goblin": 2, "standard": 2, "demon": 1},
    ]
    
    total_slips = 0
    total_wins = 0
    
    for date in dates:
        date_df = cv[cv["game_date"] == date].copy()
        if date_df.empty:
            continue
            
        slips = builder.build_slips(date_df)
        if not slips:
            continue
            
        for slip in slips:
            legs = slip["legs"]
            
            all_hit = True
            for leg in legs:
                mask = (
                    (date_df["player"].str.strip() == str(leg.get("player", "")).strip()) &
                    (date_df["stat"].str.upper() == str(leg.get("stat", "")).upper()) &
                    (date_df["direction"].str.upper() == str(leg.get("direction", "")).upper()) &
                    (abs(date_df["line"] - float(leg.get("line", 0))) < 0.01)
                )
                if not mask.any() or not bool(date_df[mask]["hit"].iloc[0]):
                    all_hit = False
                    break
            
            total_slips += 1
            total_wins += int(all_hit)
    
    win_rate = total_wins / max(total_slips, 1)
    return win_rate, total_wins, total_slips

def main():
    print("Testing exact production config from Atlas/config.yaml...")
    
    cv, dates = load_data()
    print(f"Loaded {len(dates)} dates, {len(cv):,} legs")
    
    # EXACT production config from config.yaml
    production_config = {
        "marketed_slips": {
            "enabled": True,
            "calibration_path": "data/model/marketed_calibration.json",
            "excluded_stats": ["BLK", "STL", "TO"],
            "min_thresholds": {
                "GOBLIN": 0.57,
                "STANDARD": 0.3,
                "DEMON": 0.28
            },
            "direction_filters": {},
            "correlation": {
                "same_team_penalty": 0.03,
                "hedge_bonus": 0.015,
                "blowout_penalty": 0.02
            }
        }
    }
    
    win_rate, wins, slips = evaluate_config(cv, dates, production_config)
    
    print(f"\\nPRODUCTION CONFIG RESULT:")
    print(f"Win rate: {win_rate:.1%}")
    print(f"Wins: {wins}")
    print(f"Total slips: {slips}")
    print(f"Expected: 39.5% (51/129)")
    
    if abs(win_rate - 0.395) < 0.02:  # Within 2%
        print("✅ Matches expected 39.5% baseline!")
    else:
        print("❌ Does not match expected baseline - there may be an issue")

if __name__ == "__main__":
    main()