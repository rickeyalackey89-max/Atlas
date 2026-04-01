#!/usr/bin/env python
"""
Run actual replay A/B comparison between OLD and NEW slip configs.
Tests full model pipeline (not just slip builder) to get real eval results.
"""
from __future__ import annotations

import copy
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

WORKSPACE = Path(__file__).resolve().parents[1]
CONFIG_PATH = WORKSPACE / "config.yaml"
PYTHON = WORKSPACE / ".venv" / "Scripts" / "python.exe"

# Raw files to test (dates with completed games for eval)
TEST_RAWS = [
    "prizepicks_20260319_060003.json",  # 3/19 early
    "prizepicks_20260328_064306.json",  # 3/28 (if exists)
    "prizepicks_20260330_064306.json",  # 3/30
]


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)


def make_old_config(base: dict) -> dict:
    """Create OLD slip_build config (pre-changes)."""
    cfg = copy.deepcopy(base)
    cfg["slip_build"] = {
        "prefer_calibrated_prob": True,
        "max_slips_per_player": 5,
        "target_pool_mult": 200,
        "phase1_frac": 0.20,  # OLD was 0.20
        "phase1_pool_frac": 0.5,
        "beam_width": 250,
        # OLD constraints:
        "no_same_team_within_slip": True,  # OLD had this
        "no_same_game_within_slip": True,  # OLD had this
        # max_players_per_team was implicitly 1 with no_same_team_within_slip
        # NO min_leg_prob filter
        # NO require_healthy_data filter
        # NO max_same_stat filter
        "penalty": {
            "team_w": 0.15,
            "team_power": 2.0,
            "family_w": 0.10,
            "family_power": 2.0,
            "frag_w": 0.20,
            "frag_power": 1.0,
            # NO min_std_w penalty
        },
        "by_legs": base.get("slip_build", {}).get("by_legs", {}),
        "by_sort_mode": base.get("slip_build", {}).get("by_sort_mode", {}),
    }
    return cfg


def run_replay(raw_path: Path, scenario_id: str) -> Path | None:
    """Run replay and return output directory."""
    cmd = [
        str(PYTHON), "-m", "Atlas.cli", "replay",
        "--raw", str(raw_path),
    ]
    
    env = os.environ.copy()
    env["ATLAS_REPLAY_SCENARIO_ID"] = scenario_id
    
    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(WORKSPACE))
    
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr[:500]}")
        return None
    
    # Find the replay output dir
    replay_root = WORKSPACE / "data" / "telemetry" / "replay_runs"
    # Get most recent matching scenario
    candidates = list(replay_root.glob(f"{scenario_id}*"))
    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    
    # Fallback: most recent run
    all_runs = sorted(replay_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    return all_runs[0] if all_runs else None


def get_slip_stats(run_dir: Path) -> dict:
    """Extract slip statistics from replay output."""
    stats = {"slips": 0, "avg_hit_prob": 0.0, "legs": []}
    
    # Check for slips output
    for name in ["slips_ev.csv", "slips.csv"]:
        slips_path = run_dir / name
        if slips_path.exists():
            df = pd.read_csv(slips_path)
            stats["slips"] = len(df)
            if "hit_prob" in df.columns:
                stats["avg_hit_prob"] = df["hit_prob"].mean()
            if "legs" in df.columns:
                stats["legs"] = df["legs"].tolist()
            break
    
    # Check for eval results
    eval_path = run_dir / "eval_legs.csv"
    if eval_path.exists():
        eval_df = pd.read_csv(eval_path)
        stats["eval_legs"] = len(eval_df)
        stats["eval_hits"] = eval_df["hit"].sum() if "hit" in eval_df.columns else 0
    
    return stats


def main():
    print("=" * 60)
    print("REPLAY A/B COMPARISON: OLD vs NEW SLIP CONFIG")
    print("=" * 60)
    
    # Backup original config
    original_cfg = load_config()
    
    # Find available raw files
    raw_dir = WORKSPACE / "data" / "raw"
    available_raws = []
    for raw_name in TEST_RAWS:
        raw_path = raw_dir / raw_name
        if raw_path.exists():
            available_raws.append(raw_path)
    
    if not available_raws:
        # Find any old raw files
        all_raws = sorted(raw_dir.glob("prizepicks_202603*.json"))
        if all_raws:
            available_raws = all_raws[:3]
    
    print(f"\nFound {len(available_raws)} raw files for testing")
    
    results = []
    
    for raw_path in available_raws[:3]:  # Test up to 3 dates
        raw_date = raw_path.stem.split("_")[1]
        print(f"\n{'='*60}")
        print(f"Testing {raw_path.name}")
        print("=" * 60)
        
        # Run with OLD config
        print("\n[OLD CONFIG]")
        old_cfg = make_old_config(original_cfg)
        save_config(old_cfg)
        
        old_dir = run_replay(raw_path, f"ab_old_{raw_date}")
        old_stats = get_slip_stats(old_dir) if old_dir else {}
        
        # Run with NEW config
        print("\n[NEW CONFIG]")
        save_config(original_cfg)
        
        new_dir = run_replay(raw_path, f"ab_new_{raw_date}")
        new_stats = get_slip_stats(new_dir) if new_dir else {}
        
        results.append({
            "date": raw_date,
            "old_slips": old_stats.get("slips", 0),
            "old_hit_prob": old_stats.get("avg_hit_prob", 0),
            "new_slips": new_stats.get("slips", 0),
            "new_hit_prob": new_stats.get("avg_hit_prob", 0),
        })
        
        print(f"\n  OLD: {old_stats.get('slips', 0)} slips, avg_hit_prob={old_stats.get('avg_hit_prob', 0):.3f}")
        print(f"  NEW: {new_stats.get('slips', 0)} slips, avg_hit_prob={new_stats.get('avg_hit_prob', 0):.3f}")
    
    # Restore original config
    save_config(original_cfg)
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    if results:
        df = pd.DataFrame(results)
        print(df.to_string(index=False))
        
        print(f"\nOverall averages:")
        print(f"  OLD avg hit_prob: {df['old_hit_prob'].mean():.3f}")
        print(f"  NEW avg hit_prob: {df['new_hit_prob'].mean():.3f}")


if __name__ == "__main__":
    main()
