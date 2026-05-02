"""
simple_slip_optimizer.py

Optimizes premium slip selection for maximum model-predicted hit rate and EV.
No truth validation required - uses model predictions only.

Usage:
    python tools/simple_slip_optimizer.py --run-id 20260430_171008
"""

import argparse
import pandas as pd
import json
from pathlib import Path
import sys
from itertools import product

ATLAS_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = ATLAS_DIR / "data" / "output" / "runs"


def load_slip_file(run_dir: Path, family: str, n_legs: int, winprob: bool = False) -> pd.DataFrame:
    """Load a specific slip CSV file."""
    suffix = "_winprob" if winprob else ""
    
    # Try family subfolder first
    path = run_dir / family / f"recommended_{n_legs}leg{suffix}.csv"
    if not path.exists():
        # Try top-level  
        path = run_dir / f"recommended_{n_legs}leg{suffix}.csv"
    if not path.exists() and family == "DemonHunter":
        # DemonHunter special case
        path = run_dir / "demonhunter.csv"
    
    if not path.exists():
        return pd.DataFrame()
    
    df = pd.read_csv(path)
    if df.empty:
        return df
        
    df["source_family"] = family
    df["source_winprob"] = winprob
    return df


def analyze_slip_pools(run_dir: Path) -> dict:
    """Analyze all available slip pools and their characteristics."""
    results = {}
    
    families = ["System", "Windfall", "DemonHunter"]
    legs = [3, 4, 5]
    
    for family in families:
        for n_leg in legs:
            for winprob in [False, True]:
                df = load_slip_file(run_dir, family, n_leg, winprob)
                if df.empty:
                    continue
                
                # Compute derived metrics
                if "payout_mult_eff" not in df.columns and "payout_mult" in df.columns:
                    df["payout_mult_eff"] = df["payout_mult"]
                if "ev_mult" not in df.columns:
                    payout = df.get("payout_mult_eff", df.get("payout_mult", 0)).astype(float)
                    df["ev_mult"] = df["hit_prob"] * payout
                
                df["has_demon"] = df["legs"].str.contains("(DEMON)", regex=False)
                
                key = f"{family}_{n_leg}leg{'_wp' if winprob else ''}"
                
                results[key] = {
                    "n_slips": len(df),
                    "avg_hit_prob": df["hit_prob"].mean(),
                    "max_hit_prob": df["hit_prob"].max(),
                    "min_hit_prob": df["hit_prob"].min(),
                    "avg_payout_eff": df.get("payout_mult_eff", df.get("payout_mult", pd.Series([0]))).mean(),
                    "avg_ev_mult": df["ev_mult"].mean(),
                    "max_ev_mult": df["ev_mult"].max(),
                    "demon_rate": df["has_demon"].mean(),
                    "top_hit_slip": df.loc[df["hit_prob"].idxmax()].to_dict() if not df.empty else None,
                    "top_ev_slip": df.loc[df["ev_mult"].idxmax()].to_dict() if not df.empty else None
                }
    
    return results


def find_optimal_slips(run_dir: Path) -> dict:
    """Find the optimal 3-slip combination prioritizing hit rate."""
    
    # Strategy: 
    # Slip 1 (3-leg): Highest hit_prob (safest)
    # Slip 2 (4-leg): Best balance of hit_prob and EV, prefer DEMON for payout
    # Slip 3 (5-leg): Best EV with reasonable hit_prob, prefer DEMON
    
    pools = {}
    families = ["System", "Windfall"] 
    legs = [3, 4, 5]
    
    # Load candidate pools
    for family, n_leg in product(families, legs):
        # Prefer winprob variant for higher hit rates
        df_wp = load_slip_file(run_dir, family, n_leg, winprob=True)
        df_reg = load_slip_file(run_dir, family, n_leg, winprob=False)
        
        # Use whichever has data, prefer winprob
        df = df_wp if not df_wp.empty else df_reg
        
        if not df.empty:
            # Ensure ev_mult exists
            if "ev_mult" not in df.columns:
                payout = df.get("payout_mult_eff", df.get("payout_mult", 0)).astype(float)
                df["ev_mult"] = df["hit_prob"] * payout
            
            df["has_demon"] = df["legs"].str.contains("(DEMON)", regex=False)
            pools[f"{family}_{n_leg}"] = df
    
    results = {}
    
    # SLIP 1: 3-leg with highest hit probability
    candidates_3 = pd.concat([pools.get("System_3", pd.DataFrame()), 
                             pools.get("Windfall_3", pd.DataFrame())], ignore_index=True)
    
    if not candidates_3.empty:
        # Sort by hit_prob, no demon requirement for safety
        best_3 = candidates_3.loc[candidates_3["hit_prob"].idxmax()]
        results["slip_1"] = {
            "strategy": "highest_hit_prob",
            "n_legs": 3,
            "hit_prob": best_3["hit_prob"],
            "payout_mult_eff": best_3.get("payout_mult_eff", best_3.get("payout_mult", 0)),
            "ev_mult": best_3["ev_mult"],
            "has_demon": best_3["has_demon"],
            "legs": best_3["legs"],
            "source": best_3.get("source_family", "Unknown")
        }
    
    # SLIP 2: 4-leg with DEMON preference for payout boost, balanced hit/EV
    candidates_4 = pd.concat([pools.get("System_4", pd.DataFrame()), 
                             pools.get("Windfall_4", pd.DataFrame())], ignore_index=True)
    
    if not candidates_4.empty:
        # Prefer DEMON slips, then sort by custom score (hit_prob * 0.6 + ev_mult * 0.4)
        demon_4 = candidates_4[candidates_4["has_demon"]]
        pool_4 = demon_4 if not demon_4.empty else candidates_4
        
        pool_4 = pool_4.copy()
        pool_4["combo_score"] = pool_4["hit_prob"] * 0.6 + (pool_4["ev_mult"] - 1) * 0.4
        best_4 = pool_4.loc[pool_4["combo_score"].idxmax()]
        
        results["slip_2"] = {
            "strategy": "demon_pref_balanced",
            "n_legs": 4,
            "hit_prob": best_4["hit_prob"],
            "payout_mult_eff": best_4.get("payout_mult_eff", best_4.get("payout_mult", 0)),
            "ev_mult": best_4["ev_mult"],
            "has_demon": best_4["has_demon"],
            "combo_score": best_4["combo_score"],
            "legs": best_4["legs"],
            "source": best_4.get("source_family", "Unknown")
        }
    
    # SLIP 3: 5-leg with DEMON for max payout, prioritize EV but require reasonable hit rate
    candidates_5 = pd.concat([pools.get("System_5", pd.DataFrame()), 
                             pools.get("Windfall_5", pd.DataFrame())], ignore_index=True)
    
    if not candidates_5.empty:
        # Filter to reasonable hit rates (>= 15%) and prefer DEMON
        reasonable_5 = candidates_5[candidates_5["hit_prob"] >= 0.15]
        if reasonable_5.empty:
            reasonable_5 = candidates_5  # Fallback if all are too low
        
        demon_5 = reasonable_5[reasonable_5["has_demon"]]
        pool_5 = demon_5 if not demon_5.empty else reasonable_5
        
        # Sort by EV
        best_5 = pool_5.loc[pool_5["ev_mult"].idxmax()]
        
        results["slip_3"] = {
            "strategy": "demon_max_ev_reasonable_hit",
            "n_legs": 5,
            "hit_prob": best_5["hit_prob"],
            "payout_mult_eff": best_5.get("payout_mult_eff", best_5.get("payout_mult", 0)),
            "ev_mult": best_5["ev_mult"],
            "has_demon": best_5["has_demon"],
            "legs": best_5["legs"],
            "source": best_5.get("source_family", "Unknown")
        }
    
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=str, required=True, help="Run ID (YYYYMMDD_HHMMSS)")
    args = parser.parse_args()
    
    run_dir = RUNS_DIR / args.run_id
    if not run_dir.exists():
        print(f"ERROR: Run directory not found: {run_dir}")
        sys.exit(1)
    
    print(f"OPTIMIZING PREMIUM SLIPS FOR RUN: {args.run_id}")
    print(f"{'='*70}\n")
    
    # Analyze pools
    print("SLIP POOL ANALYSIS:")
    print("-" * 50)
    pools = analyze_slip_pools(run_dir)
    
    for key, stats in pools.items():
        print(f"{key:20s}: {stats['n_slips']:3d} slips, "
              f"hit: {stats['avg_hit_prob']:.1%} (max {stats['max_hit_prob']:.1%}), "
              f"EV: {stats['avg_ev_mult']:.2f}x (max {stats['max_ev_mult']:.2f}x), "
              f"DEMON: {stats['demon_rate']:.1%}")
    
    print(f"\n{'='*70}")
    print("OPTIMAL 3-SLIP SELECTION:")
    print(f"{'='*70}")
    
    # Find optimal slips
    optimal = find_optimal_slips(run_dir)
    
    total_ev = 0
    for i, (key, slip) in enumerate(optimal.items(), 1):
        print(f"\nSLIP {i} ({slip['n_legs']}-leg): {slip['strategy']}")
        print(f"  Hit Prob: {slip['hit_prob']:.1%}  (~1 in {int(1/slip['hit_prob']):.0f})")
        print(f"  Payout:   {slip['payout_mult_eff']:.1f}x")
        print(f"  EV:       {slip['ev_mult']:.3f}x")
        print(f"  DEMON:    {'YES' if slip['has_demon'] else 'NO'}")
        print(f"  Source:   {slip['source']}")
        print(f"  Legs:     {slip['legs'][:100]}{'...' if len(slip['legs']) > 100 else ''}")
        
        total_ev += slip['ev_mult']
    
    print(f"\n{'='*70}")
    print("PORTFOLIO SUMMARY:")
    print(f"{'='*70}")
    
    avg_hit = sum(slip['hit_prob'] for slip in optimal.values()) / len(optimal)
    demon_count = sum(1 for slip in optimal.values() if slip['has_demon'])
    
    print(f"Average Hit Rate:     {avg_hit:.1%}")
    print(f"Total Portfolio EV:   {total_ev:.2f}x  (${total_ev:.2f} return per $3 staked)")
    print(f"DEMONs Included:      {demon_count}/3 slips")
    print(f"Expected Win Rate:    {avg_hit:.1%} (model prediction)")
    
    print(f"\nBANKROLL GUIDANCE (per $100 on each slip):")
    for i, slip in enumerate(optimal.values(), 1):
        win_amt = 100 * slip['payout_mult_eff']
        ev_amt = 100 * slip['ev_mult']
        print(f"  Slip {i}: Win ${win_amt:.0f}, EV ${ev_amt:.0f} per play")
    
    # Save results
    output_path = run_dir / "optimal_premium_slips.json"
    with open(output_path, "w") as f:
        json.dump({"analysis_pools": pools, "optimal_slips": optimal, "summary": {
            "avg_hit_rate": avg_hit, "total_ev": total_ev, "demon_count": demon_count
        }}, f, indent=2, default=str)
    
    print(f"\nResults saved: {output_path}")


if __name__ == "__main__":
    main()