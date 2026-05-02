"""
validate_slips_with_cache.py

Validates slip performance against the resim cache truth outcomes.
Completely isolated from all trainers and Atlas core systems.

Usage:
    python tools/validate_slips_with_cache.py --date 2026-04-12
"""

import argparse
import pickle
import pandas as pd
import json
from pathlib import Path
import sys

ATLAS_DIR = Path(__file__).resolve().parent.parent
CACHE_PATH = ATLAS_DIR / "data" / "model" / "_v17_resim_cache.pkl"


def load_cache():
    """Load the resim cache."""
    with open(CACHE_PATH, 'rb') as f:
        cache = pickle.load(f)
    return cache


def get_cache_legs_for_date(cache: dict, date_str: str) -> pd.DataFrame:
    """Get all legs for a specific date from the cache."""
    cv = cache['cv']
    
    # Try different date formats
    date_formats = [date_str, date_str.replace('-', ''), f"2026-{date_str[4:6]}-{date_str[6:8]}"]
    
    for fmt in date_formats:
        legs = cv[cv['game_date'] == fmt]
        if not legs.empty:
            return legs
    
    return pd.DataFrame()


def simulate_slip_from_legs(leg_descriptors: list, cache_legs: pd.DataFrame) -> dict:
    """Simulate a slip outcome using cache truth data."""
    results = []
    all_matched = True
    
    for desc in leg_descriptors:
        # desc is a dict with player, stat, line, direction
        matches = cache_legs[
            (cache_legs['player'] == desc['player']) &
            (cache_legs['stat'] == desc['stat']) &
            (cache_legs['line'] == desc['line']) &
            (cache_legs['direction'] == desc['direction'])
        ]
        
        if len(matches) == 1:
            match = matches.iloc[0]
            hit = bool(match['hit'])
            results.append({
                'player': desc['player'],
                'stat': desc['stat'], 
                'line': desc['line'],
                'direction': desc['direction'],
                'tier': match['tier'],
                'hit': hit,
                'p_cal': float(match['p_cal']),
                'matched': True
            })
        else:
            all_matched = False
            results.append({**desc, 'hit': None, 'matched': False})
    
    slip_won = all([r['hit'] for r in results if r['hit'] is not None]) if all_matched else None
    model_hit_prob = 1.0
    for r in results:
        if r.get('p_cal'):
            model_hit_prob *= r['p_cal']
    
    return {
        'slip_won': slip_won,
        'all_legs_matched': all_matched,
        'n_legs': len(leg_descriptors),
        'model_hit_prob': model_hit_prob,
        'leg_results': results
    }


def build_synthetic_slips(cache_legs: pd.DataFrame) -> dict:
    """Build synthetic optimal slips using cache data and the same optimization logic."""
    
    print("Building synthetic slips using cache data...")
    
    # Create fake slip candidates from cache legs
    # Group by tiers and build combinations
    
    goblins = cache_legs[cache_legs['tier'] == 'GOBLIN'].sort_values('p_cal', ascending=False)
    standards = cache_legs[cache_legs['tier'] == 'STANDARD'].sort_values('p_cal', ascending=False)
    demons = cache_legs[cache_legs['tier'] == 'DEMON'].sort_values('p_cal', ascending=False)
    
    print(f"Available legs: {len(goblins)} GOBLIN, {len(standards)} STANDARD, {len(demons)} DEMON")
    
    if len(goblins) < 2 or len(standards) < 2:
        return {}
    
    synthetic_slips = {}
    
    # SLIP 1: 3-leg safe (2 GOBLIN + 1 STANDARD with highest individual probabilities)
    if len(goblins) >= 2 and len(standards) >= 1:
        top_goblins = goblins.head(2)
        top_standard = standards.head(1)
        
        legs = pd.concat([top_goblins, top_standard])
        leg_descriptors = []
        for _, row in legs.iterrows():
            leg_descriptors.append({
                'player': row['player'],
                'stat': row['stat'],
                'line': row['line'],
                'direction': row['direction']
            })
        
        # Calculate combined hit prob
        combined_prob = 1.0
        for p in legs['p_cal']:
            combined_prob *= p
        
        synthetic_slips['slip_1'] = {
            'strategy': 'safe_3leg_high_prob',
            'n_legs': 3,
            'model_hit_prob': combined_prob,
            'leg_descriptors': leg_descriptors,
            'tier_mix': '2G+1S',
            'has_demon': False,
            'legs_desc': ' | '.join([f"{row['player']} {row['direction']} {row['stat']} {row['line']} ({row['tier']})" 
                                   for _, row in legs.iterrows()])
        }
    
    # SLIP 2: 4-leg with DEMON (1G + 2S + 1D, balanced for probability)
    if len(goblins) >= 1 and len(standards) >= 2 and len(demons) >= 1:
        # Take best GOBLIN, next 2 best STANDARDS, and best DEMON
        selected_legs = pd.concat([
            goblins.head(1),
            standards.iloc[1:3],  # Skip the one used in slip 1
            demons.head(1)
        ])
        
        leg_descriptors = []
        for _, row in selected_legs.iterrows():
            leg_descriptors.append({
                'player': row['player'],
                'stat': row['stat'],
                'line': row['line'],
                'direction': row['direction']
            })
        
        combined_prob = 1.0
        for p in selected_legs['p_cal']:
            combined_prob *= p
        
        synthetic_slips['slip_2'] = {
            'strategy': '4leg_with_demon',
            'n_legs': 4,
            'model_hit_prob': combined_prob,
            'leg_descriptors': leg_descriptors,
            'tier_mix': '1G+2S+1D',
            'has_demon': True,
            'legs_desc': ' | '.join([f"{row['player']} {row['direction']} {row['stat']} {row['line']} ({row['tier']})" 
                                   for _, row in selected_legs.iterrows()])
        }
    
    # SLIP 3: 5-leg jackpot (2G + 2S + 1D)
    if len(goblins) >= 3 and len(standards) >= 4 and len(demons) >= 1:
        selected_legs = pd.concat([
            goblins.iloc[2:4],     # Next 2 goblins
            standards.iloc[3:5],   # Next 2 standards  
            demons.head(1)         # Same best demon
        ])
        
        leg_descriptors = []
        for _, row in selected_legs.iterrows():
            leg_descriptors.append({
                'player': row['player'],
                'stat': row['stat'],
                'line': row['line'],
                'direction': row['direction']
            })
        
        combined_prob = 1.0
        for p in selected_legs['p_cal']:
            combined_prob *= p
        
        synthetic_slips['slip_3'] = {
            'strategy': '5leg_jackpot_demon',
            'n_legs': 5,
            'model_hit_prob': combined_prob,
            'leg_descriptors': leg_descriptors,
            'tier_mix': '2G+2S+1D',
            'has_demon': True,
            'legs_desc': ' | '.join([f"{row['player']} {row['direction']} {row['stat']} {row['line']} ({row['tier']})" 
                                   for _, row in selected_legs.iterrows()])
        }
    
    return synthetic_slips


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, required=True, help="Date in YYYY-MM-DD or YYYYMMDD format")
    args = parser.parse_args()
    
    print(f"CACHE-BASED SLIP VALIDATION")
    print(f"{'='*60}\n")
    
    # Load cache
    print("Loading resim cache...")
    cache = load_cache()
    
    print(f"Cache version: {cache.get('version', 'unknown')}")
    print(f"Available dates: {len(cache['dates'])}")
    print(f"Total legs in cache: {len(cache['cv'])}")
    print()
    
    # Get legs for the date
    cache_legs = get_cache_legs_for_date(cache, args.date)
    
    if cache_legs.empty:
        print(f"ERROR: No cache data found for date {args.date}")
        print(f"Available cache dates: {sorted(cache['dates'])}")
        sys.exit(1)
    
    print(f"Found {len(cache_legs)} legs for {args.date}")
    
    # Analyze the cache data for this date
    tier_counts = cache_legs['tier'].value_counts()
    hit_rates = cache_legs.groupby('tier')['hit'].agg(['count', 'sum', 'mean'])
    
    print(f"\nTIER BREAKDOWN:")
    for tier in ['GOBLIN', 'STANDARD', 'DEMON']:
        if tier in hit_rates.index:
            count = int(hit_rates.loc[tier, 'count'])
            hits = int(hit_rates.loc[tier, 'sum'])
            rate = hit_rates.loc[tier, 'mean']
            print(f"  {tier:8s}: {count:3d} legs, {hits:3d} hits, {rate:.1%} hit rate")
    
    print(f"\nOverall hit rate: {cache_legs['hit'].mean():.1%} ({int(cache_legs['hit'].sum())}/{len(cache_legs)})")
    
    # Build synthetic optimal slips
    synthetic_slips = build_synthetic_slips(cache_legs)
    
    if not synthetic_slips:
        print("ERROR: Could not build synthetic slips (insufficient legs by tier)")
        sys.exit(1)
    
    print(f"\n{'='*60}")
    print("SYNTHETIC OPTIMAL SLIPS & TRUTH VALIDATION")
    print(f"{'='*60}")
    
    # Validate each slip
    validation_results = {}
    
    for slip_key, slip in synthetic_slips.items():
        print(f"\n{slip_key.upper()}: {slip['strategy']}")
        print(f"  Strategy:     {slip['tier_mix']}")
        print(f"  Model Prob:   {slip['model_hit_prob']:.1%}")
        print(f"  Legs:         {slip['legs_desc'][:80]}{'...' if len(slip['legs_desc']) > 80 else ''}")
        
        # Validate against truth
        validation = simulate_slip_from_legs(slip['leg_descriptors'], cache_legs)
        validation_results[slip_key] = validation
        
        if validation['all_legs_matched']:
            outcome = "✓ WON" if validation['slip_won'] else "✗ LOST"
            print(f"  TRUTH RESULT: {outcome}")
            print(f"  Calibration:  Model {slip['model_hit_prob']:.1%} vs Actual {int(validation['slip_won'])}")
            
            # Show individual leg results
            print(f"  Leg Details:")
            for leg in validation['leg_results']:
                hit_mark = "✓" if leg['hit'] else "✗"
                print(f"    {hit_mark} {leg['player']} {leg['direction']} {leg['stat']} {leg['line']} ({leg['tier']}) - {leg['p_cal']:.1%}")
        else:
            print(f"  TRUTH RESULT: INCOMPLETE (some legs not matched)")
    
    print(f"\n{'='*60}")
    print("PORTFOLIO TRUTH SUMMARY")
    print(f"{'='*60}")
    
    # Calculate portfolio metrics
    validated_slips = [v for v in validation_results.values() if v['all_legs_matched']]
    total_slips = len(validated_slips)
    wins = sum(1 for v in validated_slips if v['slip_won'])
    
    model_avg_prob = sum(s['model_hit_prob'] for s in synthetic_slips.values()) / len(synthetic_slips)
    actual_win_rate = wins / total_slips if total_slips > 0 else 0
    
    print(f"Slips tested:       {total_slips}")
    print(f"Slips won:          {wins}")
    print(f"Actual win rate:    {actual_win_rate:.1%}")
    print(f"Model prediction:   {model_avg_prob:.1%}")
    print(f"Calibration error:  {abs(actual_win_rate - model_avg_prob):.1%}")
    
    # Save results  
    output = {
        'date': args.date,
        'cache_legs_count': len(cache_legs),
        'synthetic_slips': synthetic_slips,
        'validation_results': validation_results,
        'portfolio_summary': {
            'total_slips': total_slips,
            'wins': wins,
            'actual_win_rate': actual_win_rate,
            'model_avg_prob': model_avg_prob,
            'calibration_error': abs(actual_win_rate - model_avg_prob)
        }
    }
    
    output_path = ATLAS_DIR / "data" / "output" / f"slip_validation_{args.date.replace('-', '')}.json"
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"\nResults saved: {output_path}")
    
    if actual_win_rate > 0.25:
        print(f"\n🎯 SUCCESS: {actual_win_rate:.0%} win rate beats typical parlay expectations!")
    else:
        print(f"\n⚠️  CAUTION: {actual_win_rate:.0%} win rate - need to adjust selection strategy")


if __name__ == "__main__":
    main()