#!/usr/bin/env python
"""
Aggressive Hit Rate Optimization
Attempts to beat the current 39.5% win rate with more aggressive strategies.
"""
import copy
import json
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Atlas"))

from Atlas.core.marketed_slip_builder import MarketedSlipBuilder

# Same fixed templates - NON-NEGOTIABLE
FIXED_TEMPLATES = [
    {"label": "3-leg", "goblin": 1, "standard": 2, "demon": 0},
    {"label": "4-leg", "goblin": 2, "standard": 2, "demon": 0},
    {"label": "5-leg", "goblin": 2, "standard": 2, "demon": 1},
]

# Aggressive optimization strategies beyond standard trainer
AGGRESSIVE_CONFIGS = [
    # Strategy 1: Ultra-conservative thresholds
    {
        "name": "Ultra Conservative",
        "min_thresholds": {"GOBLIN": 0.75, "STANDARD": 0.55, "DEMON": 0.45},
        "excluded_stats": ["BLK", "STL", "TO", "AST", "REB"],  # Remove worst performers
    },
    
    # Strategy 2: Focus on top performing stats only
    {
        "name": "Top Stats Only", 
        "min_thresholds": {"GOBLIN": 0.65, "STANDARD": 0.40, "DEMON": 0.35},
        "excluded_stats": ["BLK", "STL", "TO", "AST", "REB", "PA", "PTS"],  # Keep only PRA, RA, FG3M, PR
    },
    
    # Strategy 3: UNDER bias (UNDER performs better: 39.5% vs OVER 33.3%)
    {
        "name": "UNDER Focused",
        "min_thresholds": {"GOBLIN": 0.60, "STANDARD": 0.35, "DEMON": 0.30},
        "excluded_stats": ["BLK", "STL", "TO"],
        "direction_filters": {"GOBLIN": ["UNDER"], "STANDARD": ["UNDER"], "DEMON": ["UNDER"]},
    },
    
    # Strategy 4: Combo stats focus (PRA, RA, PR perform well)
    {
        "name": "Combo Stats Only",
        "min_thresholds": {"GOBLIN": 0.60, "STANDARD": 0.35, "DEMON": 0.30}, 
        "excluded_stats": ["BLK", "STL", "TO", "AST", "REB", "FG3M", "PTS", "PA"],  # Only combo stats
    },
    
    # Strategy 5: Ultra-selective GOBLIN heavy
    {
        "name": "GOBLIN Heavy",
        "min_thresholds": {"GOBLIN": 0.70, "STANDARD": 0.25, "DEMON": 0.25},  # Lower others to get more GOBLINs
        "excluded_stats": ["BLK", "STL", "TO"],
    },
    
    # Strategy 6: Best stat + direction combo
    {
        "name": "PRA + UNDER Only",
        "min_thresholds": {"GOBLIN": 0.55, "STANDARD": 0.30, "DEMON": 0.28},
        "excluded_stats": ["BLK", "STL", "TO", "AST", "REB", "FG3M", "PTS", "PA", "RA", "PR"],  # Only PRA
        "direction_filters": {"GOBLIN": ["UNDER"], "STANDARD": ["UNDER"], "DEMON": ["UNDER"]},
    },
    
    # Strategy 7: Granular current + tweaks
    {
        "name": "Current + Tweak 1",
        "min_thresholds": {"GOBLIN": 0.58, "STANDARD": 0.31, "DEMON": 0.29},  # Slightly higher
        "excluded_stats": ["BLK", "STL", "TO", "AST"],  # Remove worst stat
    },
    
    {
        "name": "Current + Tweak 2", 
        "min_thresholds": {"GOBLIN": 0.59, "STANDARD": 0.28, "DEMON": 0.26},  # Higher GOBLIN, lower others
        "excluded_stats": ["BLK", "STL", "TO"],
    },
]

def load_data():
    """Load the same data as the trainer"""
    cache_path = Path(r"C:\Users\13142\Atlas\Atlas\data\model\_v17_resim_cache.pkl")
    
    import pickle
    with open(cache_path, "rb") as f:
        cache = pickle.load(f)
    
    cv = cache["cv"]
    dates = sorted(cv["game_date"].unique())
    
    # Match trainer corpus 
    corpus_path = Path(r"C:\Users\13142\Atlas\Atlas\data\telemetry\v18_corpus\corpus_manifest.json")
    if corpus_path.exists():
        with open(corpus_path) as f:
            manifest = json.load(f)
        corpus_dates = set(manifest.get("dates", []))
        train_dates = [d for d in dates if d.replace("-", "") in corpus_dates]
    else:
        train_dates = dates
    
    return cv[cv["game_date"].isin(train_dates)], train_dates

def evaluate_config(cv, dates, config):
    """Exact same evaluation as trainer"""
    builder = MarketedSlipBuilder({"marketed_slips": config})
    builder.templates = FIXED_TEMPLATES
    
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
            
            # Evaluate all legs against truth
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
    return {
        "win_rate": win_rate,
        "total_wins": total_wins, 
        "total_slips": total_slips
    }

def main():
    print("=" * 80)
    print("  AGGRESSIVE HIT RATE OPTIMIZATION")  
    print("  Target: Beat current 39.5% (51/129)")
    print("=" * 80)
    
    cv, dates = load_data()
    print(f"Loaded {len(dates)} dates, {len(cv):,} legs\\n")
    
    # Exact trainer baseline for comparison (this should give ~30.2%)
    trainer_baseline_config = {
        "enabled": True,
        "calibration_path": "data/model/marketed_calibration.json",
        "excluded_stats": ["BLK", "STL", "TO"],
        "min_thresholds": {"GOBLIN": 0.55, "STANDARD": 0.40, "DEMON": 0.30},
        "direction_filters": {},
        "correlation": {"same_team_penalty": 0.03, "hedge_bonus": 0.015, "blowout_penalty": 0.02}
    }
    
    # Current production config (this should give 39.5% - our target to beat)
    production_config = {
        "enabled": True,
        "calibration_path": "data/model/marketed_calibration.json", 
        "excluded_stats": ["BLK", "STL", "TO"],
        "min_thresholds": {"GOBLIN": 0.57, "STANDARD": 0.30, "DEMON": 0.28},
        "direction_filters": {},
        "correlation": {"same_team_penalty": 0.03, "hedge_bonus": 0.015, "blowout_penalty": 0.02}
    }
    
    trainer_baseline = evaluate_config(cv, dates, trainer_baseline_config)
    production_baseline = evaluate_config(cv, dates, production_config)
    
    print(f"TRAINER BASELINE: {trainer_baseline['win_rate']:.1%} ({trainer_baseline['total_wins']}/{trainer_baseline['total_slips']})")
    print(f"PRODUCTION CURRENT: {production_baseline['win_rate']:.1%} ({production_baseline['total_wins']}/{production_baseline['total_slips']}) ← TARGET TO BEAT")
    
    best_result = production_baseline
    best_config = None
    
    print(f"\\nTesting {len(AGGRESSIVE_CONFIGS)} aggressive strategies:\\n")
    
    for i, strategy in enumerate(AGGRESSIVE_CONFIGS, 1):
        config = copy.deepcopy(trainer_baseline_config)  # Start from trainer baseline
        config.update({k: v for k, v in strategy.items() if k != "name"})
        
        result = evaluate_config(cv, dates, config)
        
        improvement = "🔥" if result['win_rate'] > best_result['win_rate'] else "  "
        print(f"{improvement} {i}. {strategy['name']:<20} {result['win_rate']:.1%} ({result['total_wins']}/{result['total_slips']})")
        
        if result['win_rate'] > best_result['win_rate']:
            best_result = result
            best_config = strategy
            print(f"     ⭐ NEW BEST! +{(result['win_rate'] - production_baseline['win_rate'])*100:.1f}pp improvement over production")
    
    print(f"\\n{'='*80}")
    print(f"  OPTIMIZATION RESULTS")
    print(f"{'='*80}")
    print(f"Trainer Baseline:  {trainer_baseline['win_rate']:.1%} ({trainer_baseline['total_wins']}/{trainer_baseline['total_slips']})")
    print(f"Production Current: {production_baseline['win_rate']:.1%} ({production_baseline['total_wins']}/{production_baseline['total_slips']}) ← TARGET")
    print(f"Best Found:        {best_result['win_rate']:.1%} ({best_result['total_wins']}/{best_result['total_slips']})")
    
    if best_config:
        improvement_pp = (best_result['win_rate'] - production_baseline['win_rate']) * 100
        print(f"Improvement over production: {improvement_pp:+.1f} percentage points")
        print(f"\\n🎯 WINNING STRATEGY: {best_config['name']}")
        print(f"   Thresholds: {best_config['min_thresholds']}")
        print(f"   Excluded: {best_config['excluded_stats']}")
        if 'direction_filters' in best_config:
            print(f"   Directions: {best_config['direction_filters']}")
            
        if best_result['win_rate'] > production_baseline['win_rate']:
            print(f"\\n✅ SUCCESS! Beat 39.5% production baseline with {best_result['win_rate']:.1%} win rate!")
        else:
            print(f"\\n❌ Could not beat 39.5% production baseline. Current config is already optimal.")
    else:
        print(f"\\n❌ No improvement found. Current 39.5% production config is already optimal.")

if __name__ == "__main__":
    main()