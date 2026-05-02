"""
analyze_standard_performance.py

Deep dive into STANDARD leg performance to improve hit rates.
Finds what separates good STANDARD legs from bad ones.
"""

import pickle
import pandas as pd
import numpy as np

CACHE_PATH = "data/model/_v17_resim_cache.pkl"

def main():
    print("STANDARD LEG PERFORMANCE ANALYSIS")
    print("="*60)
    
    # Load cache
    with open(CACHE_PATH, 'rb') as f:
        cache = pickle.load(f)
    
    cv = cache['cv']
    
    # Focus on STANDARD legs across all dates
    standards = cv[cv['tier'] == 'STANDARD'].copy()
    demons = cv[cv['tier'] == 'DEMON'].copy()
    
    print(f"Total STANDARD legs: {len(standards)}")
    print(f"Total DEMON legs: {len(demons)}")
    print(f"STANDARD hit rate: {standards['hit'].mean():.1%}")
    print(f"DEMON hit rate: {demons['hit'].mean():.1%}")
    
    print(f"\n" + "="*60)
    print("STANDARD LEG ANALYSIS - WHAT MAKES THEM HIT?")
    print("="*60)
    
    # Analyze STANDARD legs by different factors
    factors = {
        'p_cal_bucket': pd.cut(standards['p_cal'], bins=[0, 0.4, 0.5, 0.6, 0.7, 1.0], 
                              labels=['<40%', '40-50%', '50-60%', '60-70%', '>70%']),
        'stat': standards['stat'],
        'direction': standards['direction'],
        'is_home': standards['is_home'].map({0: 'Away', 1: 'Home'}),
        'is_b2b': standards['is_b2b'].map({0: 'Rested', 1: 'B2B'}),
        'fragility_bucket': pd.cut(standards['fragility'], bins=[0, 0.1, 0.2, 0.3, 1.0],
                                  labels=['Low', 'Med-Low', 'Med-High', 'High'])
    }
    
    for factor_name, factor_values in factors.items():
        if factor_values.isna().all():
            continue
            
        analysis = standards.groupby(factor_values, observed=True)['hit'].agg(['count', 'sum', 'mean']).round(3)
        analysis = analysis.sort_values('mean', ascending=False)
        
        print(f"\n{factor_name.upper()}:")
        for idx, row in analysis.iterrows():
            if row['count'] >= 50:  # Only show categories with meaningful sample size
                print(f"  {str(idx):12s}: {int(row['sum']):3d}/{int(row['count']):3d} = {row['mean']:.1%}")
    
    print(f"\n" + "="*60)
    print("HIGH-QUALITY STANDARD SELECTION CRITERIA")
    print("="*60)
    
    # Find combinations that hit >50%
    high_quality = standards[
        (standards['p_cal'] >= 0.55) &  # Model confidence
        (standards['fragility'] <= 0.2) &  # Low fragility
        (standards['is_b2b'] == 0)  # Not back-to-back
    ]
    
    if len(high_quality) > 0:
        hq_hit_rate = high_quality['hit'].mean()
        print(f"\nHIGH-QUALITY STANDARD criteria (p_cal >= 55%, fragility <= 0.2, not B2B):")
        print(f"  Sample size: {len(high_quality)} legs")
        print(f"  Hit rate: {hq_hit_rate:.1%}")
        print(f"  Improvement: +{(hq_hit_rate - standards['hit'].mean()):.1%} vs all STANDARD")
        
        if len(high_quality) >= 10:
            print(f"\n  Top 10 high-quality STANDARD legs:")
            top_hq = high_quality.nlargest(10, 'p_cal')
            for i, (_, row) in enumerate(top_hq.iterrows(), 1):
                hit_mark = "✓" if row['hit'] else "✗"
                print(f"    {hit_mark} {row['player']} {row['direction']} {row['stat']} {row['line']} ({row['p_cal']:.1%})")
    
    # Try different thresholds
    print(f"\n" + "="*60)
    print("STANDARD FILTERING EFFECTIVENESS")
    print("="*60)
    
    thresholds = [0.45, 0.50, 0.55, 0.60, 0.65]
    
    for thresh in thresholds:
        filtered = standards[standards['p_cal'] >= thresh]
        if len(filtered) > 0:
            hit_rate = filtered['hit'].mean()
            print(f"p_cal >= {thresh:.0%}: {len(filtered):4d} legs, {hit_rate:.1%} hit rate")
    
    print(f"\n" + "="*60)
    print("DEMON ANALYSIS (Spoiler: It's Bad)")
    print("="*60)
    
    print(f"Overall DEMON hit rate: {demons['hit'].mean():.1%}")
    
    # DEMON by p_cal buckets
    demon_buckets = pd.cut(demons['p_cal'], bins=[0, 0.3, 0.4, 0.5, 0.6, 1.0], 
                          labels=['<30%', '30-40%', '40-50%', '50-60%', '>60%'])
    demon_analysis = demons.groupby(demon_buckets, observed=True)['hit'].agg(['count', 'sum', 'mean'])
    
    print(f"\nDEMON by model confidence:")
    for idx, row in demon_analysis.iterrows():
        if row['count'] >= 50:
            print(f"  {str(idx):8s}: {int(row['sum']):3d}/{int(row['count']):4d} = {row['mean']:.1%}")
    
    # High-confidence DEMONs
    high_conf_demons = demons[demons['p_cal'] >= 0.45]
    if len(high_conf_demons) > 0:
        hcd_rate = high_conf_demons['hit'].mean()
        print(f"\nHigh-confidence DEMONs (p_cal >= 45%):")
        print(f"  Sample: {len(high_conf_demons)} legs")  
        print(f"  Hit rate: {hcd_rate:.1%}")
        print(f"  Still terrible, but less terrible")
    
    print(f"\n" + "="*60)
    print("OPTIMAL SLIP STRATEGY RECOMMENDATIONS")  
    print("="*60)
    
    # Calculate portfolio performance with improved filters
    goblins = cv[cv['tier'] == 'GOBLIN']
    goblin_hit_rate = goblins['hit'].mean()
    
    improved_standards = standards[
        (standards['p_cal'] >= 0.55) &
        (standards['fragility'] <= 0.2)
    ]
    improved_standard_rate = improved_standards['hit'].mean() if len(improved_standards) > 0 else 0
    
    best_demons = demons[demons['p_cal'] >= 0.45] 
    best_demon_rate = best_demons['hit'].mean() if len(best_demons) > 0 else 0
    
    print(f"Tier hit rates with improved filters:")
    print(f"  GOBLIN (baseline):           {goblin_hit_rate:.1%}")
    print(f"  STANDARD (filtered):         {improved_standard_rate:.1%} (was {standards['hit'].mean():.1%})")
    print(f"  DEMON (high-conf only):      {best_demon_rate:.1%} (was {demons['hit'].mean():.1%})")
    
    # Simulate slip combinations
    strategies = [
        ("3 GOBLIN", [goblin_hit_rate] * 3),
        ("2 GOBLIN + 1 STANDARD (filtered)", [goblin_hit_rate, goblin_hit_rate, improved_standard_rate]),
        ("2 GOBLIN + 1 DEMON (high-conf)", [goblin_hit_rate, goblin_hit_rate, best_demon_rate]),
        ("1G + 1S + 1D (all filtered)", [goblin_hit_rate, improved_standard_rate, best_demon_rate]),
    ]
    
    print(f"\nProjected slip win rates with improved selection:")
    for strategy, rates in strategies:
        if 0 not in rates:  # Only if we have data for all tiers
            win_prob = np.prod(rates)
            print(f"  {strategy:35s}: {win_prob:.1%}")
    
    print(f"\n" + "="*60)
    print("IMPLEMENTATION RULES")
    print("="*60)
    
    print("For STANDARD legs, require:")
    print("  ✓ p_cal >= 55% (model confidence)")
    print("  ✓ fragility <= 0.2 (low injury risk)")
    print("  ✓ Not back-to-back game")
    print("  ✓ Target: 50%+ hit rate")
    
    print("\nFor DEMON legs:")
    print("  ⚠️ Use sparingly - even best DEMONs hit <35%")
    print("  ✓ If using, require p_cal >= 45%")
    print("  ✓ Only in 4-leg+ for payout boost")
    print("  ✓ Never more than 1 DEMON per slip")
    
    print("\nRecommended slip structure:")
    print("  💰 Safe play: 3 GOBLIN (54%^3 = 15.7% slip win)")
    print("  🎯 Balanced: 2 GOBLIN + 1 filtered STANDARD (54%^2 × 55% = 16.0%)")
    print("  🚀 Jackpot: 2 GOBLIN + 1 STANDARD + 1 DEMON for payout (lower % but bigger reward)")


if __name__ == "__main__":
    main()