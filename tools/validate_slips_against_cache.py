#!/usr/bin/env python3
"""
Validate specific slips against cache truth data.
Load the optimized slips and check how similar legs performed historically.
"""

import pandas as pd
import json
import pickle
import sys
from pathlib import Path

def load_cache():
    """Load the resim cache with truth data."""
    cache_path = Path("data/model/_v17_resim_cache.pkl")
    if not cache_path.exists():
        print(f"ERROR: Cache not found at {cache_path}")
        return None
    
    print(f"Loading cache: {cache_path}")
    with open(cache_path, 'rb') as f:
        cache = pickle.load(f)
    
    df = cache['cv']
    print(f"Cache loaded: {len(df):,} legs across {len(cache['dates'])} dates")
    print(f"Date range: {min(cache['dates'])} to {max(cache['dates'])}")
    
    return df

def parse_leg_string(leg_str):
    """Parse a leg string into components."""
    # Format: "Player OVER/UNDER STAT LINE (TIER) [id:...]"
    try:
        if "[id:" not in leg_str:
            return None
            
        parts = leg_str.split(" [id:")[0].strip()
        if "(" not in parts or ")" not in parts:
            return None
            
        tier = parts.split("(")[-1].split(")")[0].strip()
        main_part = parts.split("(")[0].strip()
        
        if " OVER " in main_part:
            direction = "OVER"
            left_part, right_part = main_part.split(" OVER ", 1)
        elif " UNDER " in main_part:
            direction = "UNDER"  
            left_part, right_part = main_part.split(" UNDER ", 1)
        else:
            return None
        
        player = left_part.strip()
        right_parts = right_part.strip().split()
        if len(right_parts) >= 2:
            stat = right_parts[0]  
            line_str = " ".join(right_parts[1:])
            
            try:
                line_val = float(line_str.strip())
                return {
                    'player': player,
                    'stat': stat,
                    'line': line_val,
                    'direction': direction,
                    'tier': tier
                }
            except ValueError:
                return None
    except Exception as e:
        print(f"Error parsing leg '{leg_str}': {e}")
        return None

def find_similar_legs(cache_df, leg_data, tolerance=0.5):
    """Find similar legs in cache data."""
    filters = []
    
    # Match stat and tier exactly
    filters.append(cache_df['stat'] == leg_data['stat'])
    filters.append(cache_df['tier'] == leg_data['tier'])
    filters.append(cache_df['direction'] == leg_data['direction'])
    
    # Line tolerance
    filters.append(abs(cache_df['line'] - leg_data['line']) <= tolerance)
    
    # Combine all filters
    mask = filters[0]
    for f in filters[1:]:
        mask = mask & f
    
    similar = cache_df[mask]
    return similar

def validate_slip(cache_df, slip_data):
    """Validate a single slip against cache."""
    print(f"\n{'='*60}")
    print(f"VALIDATING: {slip_data['strategy']}")
    print(f"{'='*60}")
    
    legs_str = slip_data['slip']['legs']
    leg_strings = legs_str.split(" | ")
    
    leg_results = []
    
    for i, leg_str in enumerate(leg_strings, 1):
        print(f"\nLeg {i}: {leg_str}")
        
        leg_data = parse_leg_string(leg_str)
        if not leg_data:
            print("  ❌ Failed to parse leg")
            continue
            
        similar = find_similar_legs(cache_df, leg_data)
        
        if len(similar) == 0:
            print(f"  ⚠️  No similar legs found in cache")
            continue
        
        hit_rate = similar['hit'].mean()
        avg_prob = similar['p_cal'].mean()
        calibration_error = abs(hit_rate - avg_prob)
        
        print(f"  📊 Similar legs in cache: {len(similar):,}")
        print(f"  🎯 Actual hit rate: {hit_rate:.1%}")
        print(f"  🤖 Avg model prob: {avg_prob:.1%}")
        print(f"  📏 Calibration error: {calibration_error:.1%}")
        
        # Tier breakdown
        tier_performance = similar.groupby('tier')['hit'].mean()
        for tier, rate in tier_performance.items():
            print(f"     {tier}: {rate:.1%}")
        
        leg_results.append({
            'leg': leg_str,
            'similar_count': len(similar),
            'hit_rate': hit_rate,
            'model_prob': avg_prob,
            'calibration_error': calibration_error
        })
    
    if not leg_results:
        print("  ❌ No valid legs to analyze")
        return None
    
    # Calculate slip probability (independent legs assumption)
    slip_hit_rates = [r['hit_rate'] for r in leg_results]
    slip_model_probs = [r['model_prob'] for r in leg_results]
    
    predicted_slip_prob = 1.0
    for prob in slip_model_probs:
        predicted_slip_prob *= prob
        
    historical_slip_prob = 1.0
    for rate in slip_hit_rates:
        historical_slip_prob *= rate
    
    payout = slip_data['slip']['payout_eff']
    predicted_ev = predicted_slip_prob * payout
    historical_ev = historical_slip_prob * payout
    
    print(f"\n📈 SLIP SUMMARY:")
    print(f"  Model prediction: {predicted_slip_prob:.1%}")
    print(f"  Historical reality: {historical_slip_prob:.1%}")
    print(f"  Prediction error: {abs(predicted_slip_prob - historical_slip_prob):.1%}")
    print(f"  Payout: {payout:.1f}x")
    print(f"  Predicted EV: {predicted_ev:.2f}x")
    print(f"  Historical EV: {historical_ev:.2f}x")
    
    if historical_ev > 1.0:
        print(f"  ✅ PROFITABLE (Historical EV: {historical_ev:.2f}x)")
    else:
        print(f"  ❌ UNPROFITABLE (Historical EV: {historical_ev:.2f}x)")
    
    return {
        'strategy': slip_data['strategy'],
        'legs': leg_results,
        'predicted_prob': predicted_slip_prob,
        'historical_prob': historical_slip_prob,
        'predicted_ev': predicted_ev,
        'historical_ev': historical_ev,
        'profitable': historical_ev > 1.0
    }

def main():
    # Load cache
    cache_df = load_cache()
    if cache_df is None:
        return
    
    # Load slips
    slips_file = "data/output/runs/20260501_080424/improved_premium_slips.json"
    print(f"\nLoading slips: {slips_file}")
    
    with open(slips_file, 'r') as f:
        slips_data = json.load(f)
    
    results = []
    
    # Validate each slip
    for slip_key, slip_data in slips_data.items():
        result = validate_slip(cache_df, slip_data)
        if result:
            results.append(result)
    
    # Overall summary
    print(f"\n{'='*60}")
    print("CACHE VALIDATION SUMMARY")
    print(f"{'='*60}")
    
    profitable_count = sum(1 for r in results if r['profitable'])
    
    print(f"Total slips validated: {len(results)}")
    print(f"Profitable slips: {profitable_count}/{len(results)}")
    
    if results:
        avg_historical_ev = sum(r['historical_ev'] for r in results) / len(results)
        avg_predicted_ev = sum(r['predicted_ev'] for r in results) / len(results)
        
        print(f"Average Historical EV: {avg_historical_ev:.2f}x")
        print(f"Average Predicted EV: {avg_predicted_ev:.2f}x")
        print(f"Model accuracy: {abs(avg_predicted_ev - avg_historical_ev):.2f}x error")
        
        if avg_historical_ev > 1.0:
            print(f"🎯 CACHE VALIDATION: PASSED")
            print(f"   These slip types are historically profitable!")
        else:
            print(f"⚠️  CACHE VALIDATION: FAILED") 
            print(f"   These slip types lose money historically")

if __name__ == "__main__":
    main()