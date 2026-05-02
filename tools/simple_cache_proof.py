"""
simple_cache_proof.py

Simple proof of concept showing actual slip validation against cache.
Picks specific legs manually to prove the validation works.
"""

import pickle
import pandas as pd

CACHE_PATH = "data/model/_v17_resim_cache.pkl"

def main():
    print("SIMPLE CACHE VALIDATION PROOF")
    print("="*50)
    
    # Load cache
    with open(CACHE_PATH, 'rb') as f:
        cache = pickle.load(f)
    
    # Get April 12 data
    cv = cache['cv']
    apr12 = cv[cv['game_date'] == '2026-04-12'].copy()
    
    print(f"April 12 legs: {len(apr12)}")
    
    # Show tier hit rates
    tier_hits = apr12.groupby('tier')['hit'].agg(['count', 'sum', 'mean'])
    print("\nTier performance:")
    for tier in tier_hits.index:
        count = int(tier_hits.loc[tier, 'count'])
        hits = int(tier_hits.loc[tier, 'sum'])
        rate = tier_hits.loc[tier, 'mean']
        print(f"  {tier}: {hits}/{count} = {rate:.1%}")
    
    # Pick the top 3 GOBLIN legs by p_cal
    top_goblins = apr12[apr12['tier'] == 'GOBLIN'].nlargest(3, 'p_cal')
    
    print(f"\nTop 3 GOBLIN legs by model probability:")
    for i, (_, row) in enumerate(top_goblins.iterrows(), 1):
        hit_mark = "✓ HIT" if row['hit'] else "✗ MISS" 
        print(f"  {i}. {row['player']} {row['direction']} {row['stat']} {row['line']} - Model: {row['p_cal']:.1%} - {hit_mark}")
    
    # Simple 3-leg slip: take top 3 goblins
    slip_hit_prob = 1.0
    slip_won = True
    
    print(f"\n3-LEG SLIP (Top 3 GOBLIN legs):")
    for i, (_, row) in enumerate(top_goblins.iterrows(), 1):
        hit_mark = "✓" if row['hit'] else "✗"
        slip_hit_prob *= row['p_cal']
        if not row['hit']:
            slip_won = False
        print(f"  Leg {i}: {hit_mark} {row['player']} {row['direction']} {row['stat']} {row['line']} ({row['p_cal']:.1%})")
    
    print(f"\nSLIP RESULT:")
    print(f"  Model probability: {slip_hit_prob:.1%}")
    print(f"  Actual outcome: {'✓ WON' if slip_won else '✗ LOST'}")
    print(f"  All legs hit: {slip_won}")
    
    # Try a few more combinations
    print(f"\n" + "="*50)
    print("TESTING MULTIPLE SLIP STRATEGIES")
    print("="*50)
    
    strategies = [
        ("Top 3 GOBLIN", apr12[apr12['tier'] == 'GOBLIN'].nlargest(3, 'p_cal')),
        ("Top 2 GOBLIN + 1 STANDARD", pd.concat([
            apr12[apr12['tier'] == 'GOBLIN'].nlargest(2, 'p_cal'),
            apr12[apr12['tier'] == 'STANDARD'].nlargest(1, 'p_cal')
        ])),
        ("1 GOBLIN + 1 STANDARD + 1 DEMON", pd.concat([
            apr12[apr12['tier'] == 'GOBLIN'].nlargest(1, 'p_cal'),
            apr12[apr12['tier'] == 'STANDARD'].nlargest(1, 'p_cal'),
            apr12[apr12['tier'] == 'DEMON'].nlargest(1, 'p_cal')
        ])),
    ]
    
    for strategy_name, legs in strategies:
        model_prob = 1.0
        actual_won = True
        
        print(f"\n{strategy_name}:")
        for i, (_, row) in enumerate(legs.iterrows(), 1):
            model_prob *= row['p_cal']
            if not row['hit']:
                actual_won = False
            
            hit_mark = "✓" if row['hit'] else "✗"
            print(f"  {hit_mark} {row['player']} {row['direction']} {row['stat']} {row['line']} ({row['tier']}) - {row['p_cal']:.1%}")
        
        outcome = "WON" if actual_won else "LOST"
        print(f"  Result: Model {model_prob:.1%} → {outcome}")
    
    print(f"\n" + "="*50)
    print("PORTFOLIO SIMULATION")
    print("="*50)
    
    # Test 10 different 3-leg combinations
    portfolio_results = []
    
    for i in range(10):
        # Take different combinations of high-probability legs
        start_idx = i * 2
        test_legs = apr12[apr12['tier'] == 'GOBLIN'].iloc[start_idx:start_idx+3]
        
        if len(test_legs) < 3:
            break
            
        model_prob = 1.0
        actual_won = True
        
        for _, row in test_legs.iterrows():
            model_prob *= row['p_cal']
            if not row['hit']:
                actual_won = False
        
        portfolio_results.append({
            'slip_id': i+1,
            'model_prob': model_prob,
            'actual_won': actual_won
        })
        
        outcome = "W" if actual_won else "L"
        print(f"  Slip {i+1:2d}: {model_prob:.1%} → {outcome}")
    
    # Portfolio summary
    total_slips = len(portfolio_results)
    wins = sum(1 for r in portfolio_results if r['actual_won'])
    avg_model_prob = sum(r['model_prob'] for r in portfolio_results) / total_slips
    actual_win_rate = wins / total_slips
    
    print(f"\nPORTFOLIO SUMMARY:")
    print(f"  Total slips: {total_slips}")
    print(f"  Wins: {wins}")
    print(f"  Actual win rate: {actual_win_rate:.1%}")
    print(f"  Model prediction: {avg_model_prob:.1%}")
    print(f"  Calibration error: {abs(actual_win_rate - avg_model_prob):.1%}")
    
    if actual_win_rate >= 0.30:
        print(f"\n🎯 EXCELLENT: {actual_win_rate:.0%} win rate proves the strategy works!")
    elif actual_win_rate >= 0.20:
        print(f"\n✅ GOOD: {actual_win_rate:.0%} win rate is solid for parlays")
    else:
        print(f"\n⚠️ POOR: {actual_win_rate:.0%} win rate needs improvement")


if __name__ == "__main__":
    main()