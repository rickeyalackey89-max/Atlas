#!/usr/bin/env python
"""
Marketed Slip Trainer v1
========================
Optimizes marketed slip builder parameters for maximum win rate.

Sweeps:
  - min_thresholds per tier (GOBLIN, STANDARD, DEMON)
  - correlation adjustments (same_team_penalty, hedge_bonus, blowout_penalty)
  - calibration multipliers in marketed_calibration.json
  - template compositions (if needed)

Uses v17 cache corpus for truth-backed evaluation.
"""
from __future__ import annotations

import copy
import json
import itertools
import multiprocessing as mp
from multiprocessing.pool import Pool
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Atlas.core.marketed_slip_builder import MarketedSlipBuilder

# ── Data paths ──────────────────────────────────────────────────────
BASE = Path(r"C:\Users\13142\Atlas\Atlas\data\telemetry\v17_corpus")
CACHE_PATH = Path(r"C:\Users\13142\Atlas\Atlas\data\model\_v17_resim_cache.pkl")

def _load_run_dates() -> list[str]:
    """Load dates from corpus_manifest.json if available, else hardcoded fallback."""
    manifest = BASE / "corpus_manifest.json"
    if manifest.exists():
        import json
        data = json.loads(manifest.read_text(encoding="utf-8"))
        dates = data.get("dates", [])
        if dates:
            print(f"Loaded {len(dates)} dates from {manifest.name}")
            return dates
    # Fallback: scan directory for date folders
    if BASE.exists():
        found = sorted(d.name for d in BASE.iterdir()
                       if d.is_dir() and d.name.isdigit() and len(d.name) == 8)
        if found:
            print(f"Discovered {len(found)} date dirs in {BASE.name}")
            return found
    return []

RUN_DATES = _load_run_dates()[:25]  # Use 25 dates for better optimization
FOCUSED_MODE = True  # Set to False for full parameter sweep

# ── Base configuration ─────────────────────────────────────────────
BASE_CONFIG = {
    "marketed_slips": {
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
}

# ── Parameter grids ────────────────────────────────────────────────
THRESHOLD_GRIDS = {
    "GOBLIN":   [0.50, 0.55, 0.60, 0.65, 0.70],  # Expanded range
    "STANDARD": [0.30, 0.35, 0.40, 0.45, 0.50],  # Expanded range
    "DEMON":    [0.25, 0.30, 0.35, 0.40, 0.45],  # Much lower range (4.1% pass 0.45)
}

# Focused grids for faster optimization
THRESHOLD_GRIDS_FOCUSED = {
    "GOBLIN":   [0.55, 0.60, 0.65],  # Key range
    "STANDARD": [0.35, 0.40, 0.45],  # Key range  
    "DEMON":    [0.30, 0.35, 0.40],  # Lower range (demon rarely used)
}

CORRELATION_GRIDS = {
    "same_team_penalty": [0.01, 0.02, 0.03, 0.04, 0.05],     # Expanded range
    "hedge_bonus":       [0.005, 0.010, 0.015, 0.020, 0.025], # Expanded range
    "blowout_penalty":   [0.01, 0.015, 0.02, 0.025, 0.03],   # Expanded range
}

# Focused correlation grids
CORRELATION_GRIDS_FOCUSED = {
    "same_team_penalty": [0.02, 0.03, 0.04],     # Key range
    "hedge_bonus":       [0.010, 0.015, 0.020],  # Key range
    "blowout_penalty":   [0.015, 0.02, 0.025],   # Key range
}

# Templates to test (current 1G+2S, 2G+2S, 3G+2S is good, but test alternatives)
TEMPLATE_OPTIONS = [
    # Current (validated)
    "current",
    # More conservative (more STANDARD)
    "conservative", 
    # More aggressive (more GOBLIN)
    "aggressive",
]

TEMPLATES = {
    "current": [
        {"label": "3-leg", "goblin": 1, "standard": 2, "demon": 0},
        {"label": "4-leg", "goblin": 2, "standard": 2, "demon": 0},
        {"label": "5-leg", "goblin": 2, "standard": 2, "demon": 1},
    ],
    "conservative": [
        {"label": "3-leg", "goblin": 1, "standard": 2, "demon": 0},
        {"label": "4-leg", "goblin": 1, "standard": 3, "demon": 0},
        {"label": "5-leg", "goblin": 2, "standard": 3, "demon": 0},
    ],
    "aggressive": [
        {"label": "3-leg", "goblin": 2, "standard": 1, "demon": 0},
        {"label": "4-leg", "goblin": 3, "standard": 1, "demon": 0},
        {"label": "5-leg", "goblin": 4, "standard": 1, "demon": 0},
    ],
}

# ── Data loading ───────────────────────────────────────────────────
CV_TRAIN = None
TRAIN_DATES = None

def load_cache_data():
    """Load the resim cache with all dates and truth data."""
    global CV_TRAIN, TRAIN_DATES
    
    if CV_TRAIN is not None:
        return CV_TRAIN, TRAIN_DATES
    
    import pickle
    print(f"Loading cache from {CACHE_PATH}")
    with open(CACHE_PATH, 'rb') as f:
        cache = pickle.load(f)
    
    cv = cache['cv']
    dates = sorted(cv['game_date'].unique())
    print(f"Cache contains {len(cv)} legs across {len(dates)} dates")
    
    # Filter to trainer dates
    train_dates = [d for d in dates if d.replace('-', '') in RUN_DATES]
    cv_train = cv[cv['game_date'].isin(train_dates)].copy()
    print(f"Training on {len(train_dates)} dates, {len(cv_train)} legs")
    
    CV_TRAIN = cv_train
    TRAIN_DATES = train_dates
    
    return cv_train, train_dates

def evaluate_slip(slip_legs: list[dict], truth_df: pd.DataFrame) -> tuple[bool, int, int]:
    """Check if all legs in a slip hit using truth data."""
    all_hit = True
    n_legs = len(slip_legs)
    n_hit = 0
    
    for leg in slip_legs:
        player = str(leg.get("player", "")).strip()
        stat = str(leg.get("stat", "")).upper()
        direction = str(leg.get("direction", "")).upper()
        line = float(leg.get("line", 0))
        
        # Find matching truth row
        mask = (
            (truth_df["player"].str.strip() == player) &
            (truth_df["stat"].str.upper() == stat) &
            (truth_df["direction"].str.upper() == direction) &
            (abs(truth_df["line"] - line) < 0.01)
        )
        
        if not mask.any():
            all_hit = False  # No truth data = miss
            continue
            
        hit = bool(truth_df[mask]["hit"].iloc[0])
        if hit:
            n_hit += 1
        else:
            all_hit = False
    
    return all_hit, n_hit, n_legs

def test_config(params: dict) -> dict:
    """Test a single parameter configuration across all dates."""
    config = copy.deepcopy(BASE_CONFIG)
    
    # Apply parameter overrides
    if "thresholds" in params:
        config["marketed_slips"]["min_thresholds"].update(params["thresholds"])
    if "correlation" in params:
        config["marketed_slips"]["correlation"].update(params["correlation"])
    
    # Template override
    template_name = params.get("templates", "current")
    
    try:
        builder = MarketedSlipBuilder(config)
        # Override templates if needed
        if template_name != "current":
            builder.templates = TEMPLATES[template_name]
        
        total_slips = 0
        total_wins = 0
        wins_by_template = {"3-leg": 0, "4-leg": 0, "5-leg": 0}
        slips_by_template = {"3-leg": 0, "4-leg": 0, "5-leg": 0}
        
        cv_train, train_dates = load_cache_data()
        
        for date in train_dates:
            date_df = cv_train[cv_train["game_date"] == date].copy()
            if len(date_df) == 0:
                continue
            
            # Build slips for this date
            slips = builder.build_slips(date_df)
            if not slips:
                continue
                
            # Evaluate each slip
            for slip in slips:
                label = slip["label"]
                legs = slip["legs"]
                
                slip_won, _, _ = evaluate_slip(legs, date_df)
                
                total_slips += 1
                slips_by_template[label] = slips_by_template.get(label, 0) + 1
                
                if slip_won:
                    total_wins += 1
                    wins_by_template[label] = wins_by_template.get(label, 0) + 1
        
        win_rate = total_wins / max(total_slips, 1)
        
        # Template-specific win rates
        template_rates = {}
        for template in ["3-leg", "4-leg", "5-leg"]:
            n_slips = slips_by_template.get(template, 0)
            n_wins = wins_by_template.get(template, 0)
            template_rates[template] = n_wins / max(n_slips, 1)
        
        result = {
            "params": params,
            "win_rate": win_rate,
            "total_slips": total_slips,
            "total_wins": total_wins,
            "template_rates": template_rates,
            "slips_by_template": slips_by_template,
        }
        
        print(f"Config {params}: {win_rate:.1%} ({total_wins}/{total_slips}) "
              f"3L={template_rates.get('3-leg', 0):.1%} "
              f"4L={template_rates.get('4-leg', 0):.1%} "
              f"5L={template_rates.get('5-leg', 0):.1%}")
        
        return result
        
    except Exception as e:
        print(f"ERROR in config {params}: {e}")
        return {
            "params": params,
            "win_rate": 0.0,
            "total_slips": 0,
            "total_wins": 0,
            "template_rates": {},
            "slips_by_template": {},
            "error": str(e),
        }

def run_threshold_sweep():
    """Sweep min_thresholds parameters."""
    print("\n" + "="*60)
    print("THRESHOLD SWEEP")
    print("="*60)
    
    results = []
    
    # Choose parameter grids based on mode
    grids = THRESHOLD_GRIDS_FOCUSED if FOCUSED_MODE else THRESHOLD_GRIDS
    
    # Generate all combinations
    combinations = list(itertools.product(
        grids["GOBLIN"],
        grids["STANDARD"], 
        grids["DEMON"]
    ))
    
    print(f"Testing {len(combinations)} threshold combinations...")
    
    for i, (goblin_th, standard_th, demon_th) in enumerate(combinations):
        params = {
            "thresholds": {
                "GOBLIN": goblin_th,
                "STANDARD": standard_th,
                "DEMON": demon_th,
            }
        }
        result = test_config(params)
        results.append(result)
        
        # Progress update
        if (i + 1) % 9 == 0 or (i + 1) == len(combinations):
            print(f"  Progress: {i+1}/{len(combinations)} ({(i+1)/len(combinations)*100:.0f}%)")
    
    # Sort by win rate
    results.sort(key=lambda x: x["win_rate"], reverse=True)
    
    print(f"\nTop 5 threshold configurations:")
    for i, result in enumerate(results[:5]):
        params = result["params"]["thresholds"]
        print(f"{i+1}. Win rate: {result['win_rate']:.1%} "
              f"G={params['GOBLIN']:.2f} S={params['STANDARD']:.2f} D={params['DEMON']:.2f} "
              f"({result['total_wins']}/{result['total_slips']})")
    
    return results[0] if results else None

def run_correlation_sweep(best_thresholds: dict = None):
    """Sweep correlation adjustment parameters."""
    print("\n" + "="*60) 
    print("CORRELATION SWEEP")
    print("="*60)
    
    results = []
    
    # Choose parameter grids based on mode
    grids = CORRELATION_GRIDS_FOCUSED if FOCUSED_MODE else CORRELATION_GRIDS
    
    # Generate all combinations
    combinations = list(itertools.product(
        grids["same_team_penalty"],
        grids["hedge_bonus"],
        grids["blowout_penalty"]
    ))
    
    print(f"Testing {len(combinations)} correlation combinations...")
    
    for same_team, hedge, blowout in combinations:
        params = {
            "correlation": {
                "same_team_penalty": same_team,
                "hedge_bonus": hedge,
                "blowout_penalty": blowout,
            }
        }
        
        # Include best thresholds if available
        if best_thresholds:
            params["thresholds"] = best_thresholds
            
        result = test_config(params)
        results.append(result)
    
    # Sort by win rate
    results.sort(key=lambda x: x["win_rate"], reverse=True)
    
    print(f"\nTop 5 correlation configurations:")
    for i, result in enumerate(results[:5]):
        params = result["params"]["correlation"]
        print(f"{i+1}. Win rate: {result['win_rate']:.1%} "
              f"team={params['same_team_penalty']:.3f} hedge={params['hedge_bonus']:.3f} blow={params['blowout_penalty']:.3f} "
              f"({result['total_wins']}/{result['total_slips']})")
    
    return results[0] if results else None

def run_template_sweep(best_params: dict = None):
    """Test different template compositions."""
    print("\n" + "="*60)
    print("TEMPLATE SWEEP") 
    print("="*60)
    
    results = []
    
    for template_name in TEMPLATE_OPTIONS:
        params = {"templates": template_name}
        
        # Include best params if available
        if best_params:
            params.update(best_params)
            
        result = test_config(params)
        results.append(result)
    
    # Sort by win rate
    results.sort(key=lambda x: x["win_rate"], reverse=True)
    
    print(f"\nTemplate comparison:")
    for result in results:
        template = result["params"]["templates"]
        rates = result["template_rates"]
        print(f"{template:>12}: {result['win_rate']:.1%} overall "
              f"(3L={rates.get('3-leg', 0):.1%} 4L={rates.get('4-leg', 0):.1%} 5L={rates.get('5-leg', 0):.1%})")
    
    return results[0] if results else None

def main():
    """Run the complete parameter optimization."""
    print("MARKETED SLIP TRAINER v1")
    print(f"Training dates: {len(RUN_DATES)}")
    print(f"Cache path: {CACHE_PATH}")
    
    # Load cache once at start
    cv_train, train_dates = load_cache_data()
    
    start_time = time.time()
    
    # Test baseline first
    print("\n" + "="*60)
    print("BASELINE TEST")
    print("="*60)
    baseline = test_config({})
    print(f"Baseline win rate: {baseline['win_rate']:.1%} ({baseline['total_wins']}/{baseline['total_slips']})")
    
    # 1. Optimize thresholds
    best_threshold_result = run_threshold_sweep()
    best_thresholds = best_threshold_result["params"]["thresholds"] if best_threshold_result else None
    
    # 2. Optimize correlations (with best thresholds)
    best_corr_result = run_correlation_sweep(best_thresholds)
    
    # 3. Test templates (with best params so far)
    best_params = {}
    if best_thresholds:
        best_params["thresholds"] = best_thresholds
    if best_corr_result and "correlation" in best_corr_result["params"]:
        best_params["correlation"] = best_corr_result["params"]["correlation"]
    
    best_template_result = run_template_sweep(best_params)
    
    # Final summary
    print("\n" + "="*70)
    print("OPTIMIZATION SUMMARY")
    print("="*70)
    
    print(f"Baseline:        {baseline['win_rate']:.1%}")
    if best_threshold_result:
        print(f"Best thresholds: {best_threshold_result['win_rate']:.1%} "
              f"(+{best_threshold_result['win_rate']-baseline['win_rate']:+.1%})")
    if best_corr_result:
        print(f"Best correlation: {best_corr_result['win_rate']:.1%} "
              f"(+{best_corr_result['win_rate']-baseline['win_rate']:+.1%})")
    if best_template_result:
        print(f"Best templates:  {best_template_result['win_rate']:.1%} "
              f"(+{best_template_result['win_rate']-baseline['win_rate']:+.1%})")
    
    # Show recommended config
    print(f"\nRECOMMENDED CONFIG:")
    final_config = copy.deepcopy(BASE_CONFIG)
    
    if best_threshold_result:
        final_config["marketed_slips"]["min_thresholds"].update(best_threshold_result["params"]["thresholds"])
        print(f"min_thresholds: {best_threshold_result['params']['thresholds']}")
    
    if best_corr_result and "correlation" in best_corr_result["params"]:
        final_config["marketed_slips"]["correlation"].update(best_corr_result["params"]["correlation"])
        print(f"correlation: {best_corr_result['params']['correlation']}")
        
    if best_template_result and best_template_result["params"]["templates"] != "current":
        template_name = best_template_result["params"]["templates"]
        print(f"templates: {template_name}")
        print(f"  {TEMPLATES[template_name]}")
    
    elapsed = time.time() - start_time
    print(f"\nTraining completed in {elapsed:.1f}s")

if __name__ == "__main__":
    main()