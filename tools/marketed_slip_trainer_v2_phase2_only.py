#!/usr/bin/env python
"""
Marketed Slip Trainer v2 - Phase 2 Only
========================================
Re-run Phase 2 scoring weight sweep with populated l20_edge and player_dir_te data.

Uses optimal Phase 1 thresholds from previous run:
- GOBLIN: 0.57, STANDARD: 0.30, DEMON: 0.28

Only sweeps scoring weights:
- GOBLIN score = p_cal^(1-w) * l20_edge^w
- STANDARD score = dir_te^(1-v) * p_cal^v  
- DEMON score = p_cal^(1-w) * l20_edge^w
"""
from __future__ import annotations

import copy
import itertools
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Atlas.core.marketed_slip_builder import build_marketed_slips

# ── Paths ────────────────────────────────────────────────────────────
CACHE_PATH = Path(r"C:\Users\13142\Atlas\NBA\data\model\_v17_resim_cache.pkl")
BASE = Path(r"C:\Users\13142\Atlas\NBA\data\telemetry\v18_corpus")
CONFIG_PATH = Path(r"C:\Users\13142\Atlas\NBA\config.yaml")

# ── Fixed templates ──────────────────────────────────────────────────
FIXED_TEMPLATES = [
    {"label": "3-leg", "goblin": 1, "standard": 2, "demon": 0},
    {"label": "4-leg", "goblin": 2, "standard": 2, "demon": 0},
    {"label": "5-leg", "goblin": 2, "standard": 2, "demon": 1},
]

# ── Phase 1 optimal config (from previous run) ───────────────────────
OPTIMAL_CONFIG = {
    "marketed_slips": {
        "enabled": True,
        "calibration_path": "data/model/marketed_calibration.json",
        "excluded_stats": ["BLK", "STL", "TO"],
        "min_thresholds": {
            "GOBLIN": 0.57,     # ← Phase 1 optimal
            "STANDARD": 0.30,   # ← Phase 1 optimal  
            "DEMON": 0.28,      # ← Phase 1 optimal
        },
        "direction_filters": {},
        "correlation": {
            "same_team_penalty": 0.03,
            "hedge_bonus": 0.015,
            "blowout_penalty": 0.02,
        },
    }
}

# ── Phase 2: Scoring weight sweep ────────────────────────────────────
GOBLIN_L20_WEIGHTS  = [0.0, 0.25, 0.50, 0.75, 1.0]   # weight on l20_edge in GOBLIN score
STANDARD_TE_WEIGHTS = [0.5, 0.65, 0.75, 0.85, 1.0]   # weight on dir_te in STANDARD score  
DEMON_L20_WEIGHTS   = [0.0, 0.25, 0.50, 0.75, 1.0]   # weight on l20_edge in DEMON score

# ── Data ─────────────────────────────────────────────────────────────
_CV_CACHE: pd.DataFrame | None = None

def load_data() -> pd.DataFrame:
    """Load the v17 resim cache."""
    global _CV_CACHE
    if _CV_CACHE is not None:
        return _CV_CACHE

    print(f"Loading resim cache: {CACHE_PATH}")
    import pickle
    with open(CACHE_PATH, "rb") as f:
        cache = pickle.load(f)
    
    _CV_CACHE = cache["cv"].copy()
    print(f"  Loaded {len(_CV_CACHE)} legs, {_CV_CACHE['game_date'].nunique()} dates")
    
    # Verify l20_edge and player_dir_te columns exist and have non-zero values
    if 'l20_edge' not in _CV_CACHE.columns:
        raise ValueError("l20_edge column missing from cache!")
    if 'player_dir_te' not in _CV_CACHE.columns:
        raise ValueError("player_dir_te column missing from cache!")
        
    l20_nonzero = (_CV_CACHE['l20_edge'] != 0).sum()
    te_nonzero = (_CV_CACHE['player_dir_te'] != 0).sum() 
    print(f"  l20_edge non-zero values: {l20_nonzero}/{len(_CV_CACHE)} ({100*l20_nonzero/len(_CV_CACHE):.1f}%)")
    print(f"  player_dir_te non-zero values: {te_nonzero}/{len(_CV_CACHE)} ({100*te_nonzero/len(_CV_CACHE):.1f}%)")
    
    if l20_nonzero == 0:
        print("  WARNING: All l20_edge values are zero - Phase 2 may still be flat")
    if te_nonzero == 0:
        print("  WARNING: All player_dir_te values are zero - Phase 2 may still be flat")
    
    return _CV_CACHE

def evaluate_config(config: dict, scoring_overrides: dict[str, float] = None) -> dict[str, Any]:
    """Evaluate a config across all training dates."""
    cv = load_data()
    dates = sorted(cv['game_date'].unique())
    
    per_date_results = []
    total_built = 0
    total_wins = 0
    
    for date_str in dates:
        date_legs = cv[cv['game_date'] == date_str].copy()
        if len(date_legs) == 0:
            continue
            
        try:
            # Apply scoring overrides if provided
            if scoring_overrides:
                date_legs = apply_scoring_overrides(date_legs, scoring_overrides)
            
            # Build slips using the Atlas function
            date_slips = build_marketed_slips(date_legs, config)
            
            # Compute all_hit for each slip (not included by default)
            for slip in date_slips:
                if 'legs' in slip:
                    slip['all_hit'] = all(leg.get('hit', 0) == 1.0 for leg in slip['legs'])
                else:
                    slip['all_hit'] = False
            
            date_built = len(date_slips)
            date_wins = sum(1 for slip in date_slips if slip.get("all_hit", False))
            
            per_date_results.append({
                "date": date_str,
                "built": date_built,
                "wins": date_wins,
                "win_rate": date_wins / date_built if date_built > 0 else 0.0
            })
            
            total_built += date_built
            total_wins += date_wins
            
        except Exception as e:
            print(f"    Error on {date_str}: {e}")
            per_date_results.append({
                "date": date_str, 
                "built": 0,
                "wins": 0,
                "win_rate": 0.0
            })
    
    overall_win_rate = total_wins / total_built if total_built > 0 else 0.0
    
    return {
        "win_rate": overall_win_rate,
        "total_built": total_built,
        "total_wins": total_wins,
        "per_date": per_date_results
    }

def apply_scoring_overrides(df: pd.DataFrame, overrides: dict[str, float]) -> pd.DataFrame:
    """Apply custom scoring weights to the legs DataFrame."""
    df = df.copy()
    
    # Extract scoring weights with defaults (current behavior)
    goblin_l20_w = overrides.get("goblin_l20_w", 1.0)    # default: pure l20_edge * p_cal
    standard_te_w = overrides.get("standard_te_w", 1.0)  # default: pure dir_te
    demon_l20_w = overrides.get("demon_l20_w", 1.0)      # default: pure l20_edge * p_cal
    
    # Get required columns
    p_cal  = pd.to_numeric(df["p_cal"], errors="coerce").fillna(0.5)
    l20    = pd.to_numeric(df.get("l20_edge", pd.Series(0.0, index=df.index)), errors="coerce").fillna(0.0).clip(0, 1) 
    dir_te = pd.to_numeric(df.get("player_dir_te", pd.Series(0.0, index=df.index)), errors="coerce").fillna(0.0)
    
    # Apply weighted scoring formulas:
    # GOBLIN:   score = p_cal^(1-w) * (p_cal * l20_edge)^w = p_cal * l20_edge^w
    # STANDARD: score = dir_te^(1-v) * p_cal^v  
    # DEMON:    score = p_cal^(1-w) * (p_cal * l20_edge)^w = p_cal * l20_edge^w
    
    goblin_score   = (p_cal * (l20 ** goblin_l20_w)).values
    standard_score = ((dir_te ** (1 - standard_te_w)) * (p_cal ** standard_te_w)).values  
    demon_score    = (p_cal * (l20 ** demon_l20_w)).values
    
    # Apply tier-specific scores
    tier_arr = df["tier"].values
    df["marketed_score"] = np.where(
        tier_arr == "STANDARD", standard_score,
        np.where(tier_arr == "DEMON", demon_score, goblin_score)
    )
    
    return df

def fmt(result: dict) -> str:
    """Format result for display."""
    return f"{result['win_rate']:.1%} ({result['total_wins']}/{result['total_built']})"

def print_breakdown(result: dict, title: str = None):
    """Print per-date breakdown."""
    if title:
        print(f"\n  {title}:")
    else:
        print(f"\n  Per-date breakdown:")
    
    for day in result["per_date"]:
        if day["built"] > 0:
            print(f"    {day['date']}: {day['win_rate']:.1%} ({day['wins']}/{day['built']})")
        else:
            print(f"    {day['date']}: no slips built")

def update_config_file(best_overrides: dict[str, float]):
    """Update config.yaml with optimal scoring weights."""
    print(f"\n  Updating config.yaml with optimal weights: {best_overrides}")
    
    # Load current config
    with open(CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)
    
    # Update scoring weights (these don't exist in config yet, so add them)
    if "marketed_slips" not in config:
        config["marketed_slips"] = {}
        
    config["marketed_slips"]["scoring_weights"] = {
        "goblin_l20_weight": best_overrides["goblin_l20_w"],
        "standard_te_weight": best_overrides["standard_te_w"],
        "demon_l20_weight": best_overrides["demon_l20_w"]
    }
    
    # Backup original
    backup_path = CONFIG_PATH.with_suffix('.yaml.bak')
    if not backup_path.exists():
        import shutil
        shutil.copy2(CONFIG_PATH, backup_path)
        print(f"  Backup saved: {backup_path}")
    
    # Write updated config
    with open(CONFIG_PATH, "w") as f:
        yaml.safe_dump(config, f, indent=2, sort_keys=False)
    
    print(f"  ✅ Updated {CONFIG_PATH}")

def main():
    t0 = time.time()
    
    print("="*70)
    print("  MARKETED SLIP TRAINER v2 - PHASE 2 ONLY")
    print("="*70)
    print("  Re-running scoring weight sweep with populated l20_edge/player_dir_te")
    print(f"  Using Phase 1 optimal thresholds: G=0.57 S=0.30 D=0.28")
    print()
    
    # Load and validate data
    load_data()
    
    # Baseline with current optimal config
    print("\n" + "="*70)
    print("  BASELINE (Phase 1 optimal)")
    print("="*70)
    baseline_result = evaluate_config(copy.deepcopy(OPTIMAL_CONFIG))
    print(f"  Baseline: {fmt(baseline_result)}")
    print_breakdown(baseline_result)
    
    # Phase 2: Scoring weight sweep
    print("\n" + "="*70)
    print("  PHASE 2 — SCORING WEIGHT SWEEP")
    print("="*70)
    
    combos = list(itertools.product(GOBLIN_L20_WEIGHTS, STANDARD_TE_WEIGHTS, DEMON_L20_WEIGHTS))
    print(f"  Testing {len(combos)} weight combinations...")
    print(f"  GOBLIN weights (l20_edge): {GOBLIN_L20_WEIGHTS}")
    print(f"  STANDARD weights (dir_te): {STANDARD_TE_WEIGHTS}")
    print(f"  DEMON weights (l20_edge): {DEMON_L20_WEIGHTS}")
    print()

    phase2_results = []
    for i, (gw, sw, dw) in enumerate(combos, 1):
        overrides = {"goblin_l20_w": gw, "standard_te_w": sw, "demon_l20_w": dw}
        r = evaluate_config(copy.deepcopy(OPTIMAL_CONFIG), scoring_overrides=overrides)
        phase2_results.append((r["win_rate"], gw, sw, dw, r))
        
        if i % 5 == 0:
            print(f"  Progress: {i}/{len(combos)} - Current: G={gw:.2f} S={sw:.2f} D={dw:.2f} -> {fmt(r)}")

    # Sort and display results
    phase2_results.sort(key=lambda x: -x[0])
    best_gw, best_sw, best_dw, best_phase2 = phase2_results[0][1], phase2_results[0][2], phase2_results[0][3], phase2_results[0][4]

    print(f"\n  🏆 TOP 10 SCORING WEIGHT COMBINATIONS:")
    for i, (wr, gw, sw, dw, r) in enumerate(phase2_results[:10], 1):
        marker = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i:2d}."
        print(f"    {marker} goblin_l20={gw:.2f} std_te={sw:.2f} demon_l20={dw:.2f}  ->  {fmt(r)}")

    # Check for improvement
    baseline_rate = baseline_result["win_rate"]
    best_rate = best_phase2["win_rate"]
    improvement = best_rate - baseline_rate
    
    print(f"\n  📊 PHASE 2 RESULTS:")
    print(f"    Baseline (current):     {baseline_rate:.3%}")
    print(f"    Best scoring weights:   {best_rate:.3%}")
    print(f"    Improvement:            {improvement:+.3%} ({improvement*100:+.1f}pp)")
    
    if improvement > 0.001:  # At least 0.1pp improvement
        print(f"\n  ✅ PHASE 2 IMPROVED! Applying optimal weights...")
        best_overrides = {"goblin_l20_w": best_gw, "standard_te_w": best_sw, "demon_l20_w": best_dw}
        update_config_file(best_overrides)
        print_breakdown(best_phase2, f"🎯 Optimal weights breakdown")
        
    else:
        print(f"\n  ⚪ PHASE 2: No significant improvement")  
        print(f"     Current scoring approach is already near-optimal")
        print_breakdown(best_phase2, f"Best attempted weights breakdown")

    elapsed = time.time() - t0
    print(f"\n  ⏱️ Phase 2 completed in {elapsed:.1f} seconds")
    print(f"  💾 Cache used: {CACHE_PATH}")
    print()

if __name__ == "__main__":
    main()
