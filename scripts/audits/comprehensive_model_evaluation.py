#!/usr/bin/env python3

"""
Comprehensive Model & Feature Evaluation

Analyzes whether we're using optimal metrics, features, and optimization targets
for the Atlas marketed slip system by examining:

1. Performance across multiple evaluation metrics (not just win rate)
2. Feature importance and redundancy analysis  
3. Alternative optimization targets (EV, Kelly, Sharpe)
4. Segment-specific performance (tier, stat, slip size, temporal)
5. Market efficiency analysis across different dimensions

Usage:
    python scripts/audits/comprehensive_model_evaluation.py
"""

import pandas as pd
import numpy as np
from pathlib import Path
import pickle
from typing import Dict, List, Tuple, Any
from sklearn.metrics import roc_auc_score
from sklearn.feature_selection import mutual_info_regression
from scipy.stats import pearsonr, spearmanr
import warnings
warnings.filterwarnings('ignore')

def load_resim_cache(cache_path: str) -> pd.DataFrame:
    """Load the v17 resim cache"""
    print(f"Loading resim cache: {cache_path}")
    with open(cache_path, 'rb') as f:
        cache = pickle.load(f)
    
    df = cache['cv'].copy()
    print(f"  Loaded {len(df):,} legs across {len(cache['dates'])} dates")
    return df

def calculate_comprehensive_metrics(df: pd.DataFrame) -> Dict[str, float]:
    """Calculate all evaluation metrics beyond just win rate"""
    
    # Basic performance
    hit_rate = df['hit'].mean()
    
    # Probabilistic metrics (require valid probabilities)
    valid_prob_mask = (df['p_cal'].notna()) & (df['p_cal'] > 0) & (df['p_cal'] < 1)
    valid_df = df[valid_prob_mask]
    
    if len(valid_df) > 0:
        brier_score = ((valid_df['p_cal'] - valid_df['hit']) ** 2).mean()
        
        # Log loss with epsilon to avoid log(0)
        epsilon = 1e-15
        p_safe = np.clip(valid_df['p_cal'], epsilon, 1-epsilon)
        log_loss = -(valid_df['hit'] * np.log(p_safe) + (1 - valid_df['hit']) * np.log(1 - p_safe)).mean()
        
        # AUC
        try:
            auc = roc_auc_score(valid_df['hit'], valid_df['p_cal'])
        except:
            auc = np.nan
            
        # Calibration gap (actual vs predicted by probability decile)
        valid_df_copy = valid_df.copy()
        valid_df_copy['prob_decile'] = pd.qcut(valid_df_copy['p_cal'], 10, labels=False, duplicates='drop')
        cal_gaps = []
        for decile in valid_df_copy['prob_decile'].unique():
            if pd.notna(decile):
                decile_data = valid_df_copy[valid_df_copy['prob_decile'] == decile]
                if len(decile_data) > 0:
                    predicted = decile_data['p_cal'].mean()
                    actual = decile_data['hit'].mean()
                    cal_gaps.append(abs(actual - predicted))
        
        avg_calibration_gap = np.mean(cal_gaps) if cal_gaps else np.nan
    else:
        brier_score = log_loss = auc = avg_calibration_gap = np.nan
    
    return {
        'hit_rate': hit_rate,
        'brier_score': brier_score,
        'log_loss': log_loss,  
        'auc': auc,
        'calibration_gap': avg_calibration_gap,
        'sample_size': len(df)
    }

def analyze_feature_importance(df: pd.DataFrame) -> Dict[str, float]:
    """Analyze feature importance using multiple methods"""
    
    # GBM feature list (33+ features from v17)
    feature_cols = [
        'z_line', 'min_cv', 'is_combo', 'bp_score_gated', 'bp_has', 'is_assists', 'is_threes',
        'games_norm', 'thin_flag', 'line_norm', 'is_home_feat', 'min_sensitivity',
        'game_total_norm', 'is_b2b', 'l20_edge', 'l10_has', 'margin', 'stat_cat', 'tier_cat',
        'l40_hr', 'logit_p_x_demon', 'player_te', 'player_stat_te', 'player_dir_te',
        'player_n_norm', 'line_dist', 'tail_risk', 'line_tightness', 'margin_x_under',
        'q_blowout', 'rate_cv', 'abs_logit_p', 'q_x_under'
    ]
    
    # Only analyze features that exist in the dataset
    available_features = [col for col in feature_cols if col in df.columns]
    print(f"  Analyzing {len(available_features)} available features")
    
    feature_analysis = {}
    
    # Valid data for analysis (non-null features and target)
    analysis_df = df[available_features + ['hit']].dropna()
    
    if len(analysis_df) < 100:
        print("  Warning: Insufficient data for feature analysis")
        return feature_analysis
    
    X = analysis_df[available_features]
    y = analysis_df['hit']
    
    # Correlation with target (hit outcome)  
    correlations = {}
    for feat in available_features:
        try:
            corr, _ = pearsonr(X[feat], y)
            correlations[feat] = abs(corr)
        except:
            correlations[feat] = 0.0
    
    # Mutual information (non-linear relationship detection)
    try:
        mi_scores = mutual_info_regression(X, y, random_state=42)
        mutual_info = dict(zip(available_features, mi_scores))
    except:
        mutual_info = {feat: 0.0 for feat in available_features}
    
    # Combine into feature importance ranking
    for feat in available_features:
        # Weighted combination of correlation and mutual info
        importance = 0.6 * correlations.get(feat, 0) + 0.4 * mutual_info.get(feat, 0)
        feature_analysis[feat] = importance
    
    return feature_analysis

def segment_performance_analysis(df: pd.DataFrame) -> Dict[str, Any]:
    """Analyze performance across different segments"""
    
    segments = {}
    
    # By tier
    if 'tier' in df.columns:
        tier_performance = {}
        for tier in df['tier'].unique():
            if pd.notna(tier):
                tier_data = df[df['tier'] == tier]
                tier_performance[tier] = calculate_comprehensive_metrics(tier_data)
        segments['by_tier'] = tier_performance
    
    # By stat category
    if 'stat' in df.columns:
        stat_performance = {}
        for stat in df['stat'].value_counts().head(10).index:  # Top 10 most common
            stat_data = df[df['stat'] == stat]
            stat_performance[stat] = calculate_comprehensive_metrics(stat_data)
        segments['by_stat'] = stat_performance
    
    # By direction  
    if 'direction' in df.columns:
        direction_performance = {}
        for direction in df['direction'].unique():
            if pd.notna(direction):
                dir_data = df[df['direction'] == direction]
                direction_performance[direction] = calculate_comprehensive_metrics(dir_data)
        segments['by_direction'] = direction_performance
    
    # By probability tier (confidence levels)
    if 'p_cal' in df.columns:
        prob_tiers = {'Low (0.3-0.5)': (0.3, 0.5), 'Mid (0.5-0.7)': (0.5, 0.7), 'High (0.7+)': (0.7, 1.0)}
        prob_performance = {}
        for tier_name, (low, high) in prob_tiers.items():
            tier_mask = (df['p_cal'] >= low) & (df['p_cal'] < high)
            if tier_mask.sum() > 0:
                prob_performance[tier_name] = calculate_comprehensive_metrics(df[tier_mask])
        segments['by_probability'] = prob_performance
    
    return segments

def alternative_optimization_analysis(df: pd.DataFrame) -> Dict[str, Any]:
    """Analyze alternative optimization targets beyond win rate"""
    
    alternatives = {}
    
    # Expected Value analysis (if we had payout multipliers)
    # For now, simulate based on typical PrizePicks payouts
    if 'p_cal' in df.columns:
        # Simulate 3-leg slip EV (typical ~6x payout)
        simulated_3leg_payout = 6.0
        df_copy = df.copy()
        df_copy['implied_ev'] = df_copy['p_cal'] * simulated_3leg_payout - 1.0
        
        alternatives['ev_analysis'] = {
            'mean_implied_ev': df_copy['implied_ev'].mean(),
            'positive_ev_rate': (df_copy['implied_ev'] > 0).mean(),
            'ev_std': df_copy['implied_ev'].std()
        }
    
    # Kelly Criterion analysis (optimal bet sizing)
    if 'p_cal' in df.columns:
        # Kelly = (bp - q) / b, where b=odds-1, p=win_prob, q=1-p
        df_copy = df.copy() 
        odds = 6.0  # Typical 3-leg odds
        df_copy['kelly_fraction'] = np.maximum(0, 
            (df_copy['p_cal'] * odds - 1) / (odds - 1))
        
        alternatives['kelly_analysis'] = {
            'mean_kelly_fraction': df_copy['kelly_fraction'].mean(),
            'positive_kelly_rate': (df_copy['kelly_fraction'] > 0).mean(),
            'optimal_sizing_legs': len(df_copy[df_copy['kelly_fraction'] > 0.05])  # >5% Kelly
        }
    
    # Sharpe-like ratio (return/volatility)
    if 'p_cal' in df.columns and 'hit' in df.columns:
        df_copy = df.copy()
        df_copy['return'] = np.where(df_copy['hit'] == 1, 5.0, -1.0)  # +5x or -1x
        
        alternatives['sharpe_analysis'] = {
            'mean_return': df_copy['return'].mean(),
            'return_std': df_copy['return'].std(), 
            'sharpe_ratio': df_copy['return'].mean() / df_copy['return'].std() if df_copy['return'].std() > 0 else 0
        }
    
    return alternatives

def temporal_analysis(df: pd.DataFrame) -> Dict[str, Any]:
    """Analyze performance over time"""
    
    temporal = {}
    
    if 'game_date' in df.columns:
        df_copy = df.copy()
        df_copy['game_date'] = pd.to_datetime(df_copy['game_date'])
        df_copy = df_copy.sort_values('game_date')
        
        # Monthly performance
        df_copy['month'] = df_copy['game_date'].dt.to_period('M')
        monthly_performance = {}
        for month in df_copy['month'].unique():
            if pd.notna(month):
                month_data = df_copy[df_copy['month'] == month]
                monthly_performance[str(month)] = calculate_comprehensive_metrics(month_data)
        temporal['monthly'] = monthly_performance
        
        # Early vs late season (if we have enough date range)
        date_range = df_copy['game_date'].max() - df_copy['game_date'].min()
        if date_range.days > 30:
            midpoint = df_copy['game_date'].min() + date_range / 2
            early_data = df_copy[df_copy['game_date'] <= midpoint]
            late_data = df_copy[df_copy['game_date'] > midpoint]
            
            temporal['seasonal'] = {
                'early_season': calculate_comprehensive_metrics(early_data),
                'late_season': calculate_comprehensive_metrics(late_data)
            }
    
    return temporal

def print_comprehensive_report(
    overall_metrics: Dict,
    feature_importance: Dict,
    segment_performance: Dict,
    alternative_optimization: Dict,
    temporal_analysis: Dict
):
    """Print comprehensive evaluation report"""
    
    print("=" * 80)
    print("  COMPREHENSIVE MODEL & FEATURE EVALUATION")
    print("=" * 80)
    
    # Overall performance
    print(f"\n📊 OVERALL PERFORMANCE ({overall_metrics['sample_size']:,} legs)")
    print(f"  Hit Rate:         {overall_metrics['hit_rate']:.3f}")
    print(f"  Brier Score:      {overall_metrics['brier_score']:.6f}")
    print(f"  Log Loss:         {overall_metrics['log_loss']:.6f}")  
    print(f"  AUC:              {overall_metrics['auc']:.3f}")
    print(f"  Calibration Gap:  {overall_metrics['calibration_gap']:.4f}")
    
    # Feature importance
    print(f"\n🎯 TOP 10 MOST IMPORTANT FEATURES")
    sorted_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)[:10]
    for i, (feature, importance) in enumerate(sorted_features, 1):
        print(f"  {i:2d}. {feature:<20} {importance:.4f}")
    
    # Segment analysis
    print(f"\n🔍 SEGMENT PERFORMANCE ANALYSIS")
    
    if 'by_tier' in segment_performance:
        print(f"\n  By Tier:")
        for tier, metrics in segment_performance['by_tier'].items():
            print(f"    {tier}: {metrics['hit_rate']:.3f} hit rate, Brier {metrics['brier_score']:.4f} ({metrics['sample_size']:,} legs)")
    
    if 'by_direction' in segment_performance:
        print(f"\n  By Direction:")
        for direction, metrics in segment_performance['by_direction'].items():
            print(f"    {direction}: {metrics['hit_rate']:.3f} hit rate, AUC {metrics['auc']:.3f} ({metrics['sample_size']:,} legs)")
    
    if 'by_probability' in segment_performance:
        print(f"\n  By Probability Tier:")
        for prob_tier, metrics in segment_performance['by_probability'].items():
            calibration_gap = metrics['calibration_gap']
            print(f"    {prob_tier}: {metrics['hit_rate']:.3f} hit rate, Cal Gap {calibration_gap:.4f} ({metrics['sample_size']:,} legs)")
    
    # Alternative optimization
    print(f"\n💰 ALTERNATIVE OPTIMIZATION TARGETS")
    
    if 'ev_analysis' in alternative_optimization:
        ev_data = alternative_optimization['ev_analysis']
        print(f"  Expected Value:")
        print(f"    Mean EV:          {ev_data['mean_implied_ev']:+.4f}")
        print(f"    Positive EV Rate: {ev_data['positive_ev_rate']:.1%}")
        print(f"    EV Volatility:    {ev_data['ev_std']:.4f}")
    
    if 'kelly_analysis' in alternative_optimization:
        kelly_data = alternative_optimization['kelly_analysis']
        print(f"  Kelly Criterion:")
        print(f"    Mean Kelly:       {kelly_data['mean_kelly_fraction']:.4f}")
        print(f"    Positive Kelly:   {kelly_data['positive_kelly_rate']:.1%}")
        print(f"    Optimal Size:     {kelly_data['optimal_sizing_legs']:,} legs")
    
    if 'sharpe_analysis' in alternative_optimization:
        sharpe_data = alternative_optimization['sharpe_analysis']
        print(f"  Risk-Adjusted Returns:")
        print(f"    Mean Return:      {sharpe_data['mean_return']:+.4f}")
        print(f"    Sharpe Ratio:     {sharpe_data['sharpe_ratio']:+.4f}")
    
    # Temporal analysis
    if 'seasonal' in temporal_analysis:
        print(f"\n📅 TEMPORAL ANALYSIS")
        seasonal = temporal_analysis['seasonal']
        early = seasonal['early_season']
        late = seasonal['late_season']
        print(f"  Early Season: {early['hit_rate']:.3f} hit rate, Brier {early['brier_score']:.4f}")
        print(f"  Late Season:  {late['hit_rate']:.3f} hit rate, Brier {late['brier_score']:.4f}")
        
        hit_rate_change = late['hit_rate'] - early['hit_rate']
        brier_change = late['brier_score'] - early['brier_score']
        print(f"  Drift: Hit rate {hit_rate_change:+.3f}, Brier {brier_change:+.4f}")

def main():
    """Run comprehensive evaluation"""
    
    # Load data
    cache_path = "data/model/_v17_resim_cache.pkl"
    df = load_resim_cache(cache_path)
    
    print(f"\n🔬 RUNNING COMPREHENSIVE ANALYSIS...")
    
    # Calculate overall metrics
    overall_metrics = calculate_comprehensive_metrics(df)
    
    # Feature importance analysis
    print(f"  Analyzing feature importance...")
    feature_importance = analyze_feature_importance(df)
    
    # Segment performance
    print(f"  Analyzing segment performance...")
    segment_performance = segment_performance_analysis(df)
    
    # Alternative optimization targets
    print(f"  Analyzing alternative optimization targets...")
    alternative_optimization = alternative_optimization_analysis(df)
    
    # Temporal analysis
    print(f"  Analyzing temporal performance...")
    temporal = temporal_analysis(df)
    
    # Print comprehensive report
    print_comprehensive_report(
        overall_metrics, feature_importance, segment_performance, 
        alternative_optimization, temporal
    )
    
    print(f"\n" + "=" * 80)
    print("  EVALUATION COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    main()