#!/usr/bin/env python3
"""
Backfill eval_legs.csv for all live run dirs on a specific date.

Usage:
    py tools/eval_date.py --date 20260430
    py tools/eval_date.py --date 20260430 --dry-run
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_RUNS = ROOT / "data" / "telemetry" / "live_runs"
GAMELOGS = ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"
EVAL_TOOL = ROOT / "tools" / "create_eval_leg_backtestv2.py"


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill eval_legs for a single date.")
    ap.add_argument("--date", required=True, help="Date in YYYYMMDD format, e.g. 20260430")
    ap.add_argument("--dry-run", action="store_true", help="Analyze only, do not write files")
    args = ap.parse_args()

    date = args.date.strip()

    # Find all live_run dirs matching the date prefix
    run_dirs = sorted(LIVE_RUNS.glob(f"{date}_*"))
    if not run_dirs:
        print(f"[ERROR] No live run dirs found matching {date}_* in {LIVE_RUNS}")
        return 1

    # Filter to dirs that have scored_legs_deduped.csv (required input)
    eligible = [d for d in run_dirs if (d / "scored_legs_deduped.csv").exists()]
    already_done = [d for d in eligible if (d / "eval_legs.csv").exists()]
    needs_eval = [d for d in eligible if not (d / "eval_legs.csv").exists()]

    print(f"Date: {date}")
    print(f"  Total run dirs:  {len(run_dirs)}")
    print(f"  Have scored:     {len(eligible)}")
    print(f"  Already have eval_legs: {len(already_done)}")
    print(f"  Need eval_legs:  {len(needs_eval)}")

    if not needs_eval:
        print("[OK] All eligible dirs already have eval_legs.csv — nothing to do.")
        return 0

    if args.dry_run:
        print("\n[DRY RUN] Would process:")
        for d in needs_eval:
            print(f"  {d.name}")
        return 0

    # Build --run-dir args list
    run_dir_args = []
    for d in needs_eval:
        run_dir_args += ["--run-dir", str(d)]

    cmd = [
        sys.executable,
        str(EVAL_TOOL),
        "--gamelogs-path", str(GAMELOGS),
    ] + run_dir_args

    print(f"\nRunning eval on {len(needs_eval)} dir(s)...")
    result = subprocess.run(cmd)

    if result.returncode != 0:
        print(f"[FAIL] eval tool exited with code {result.returncode}")
        return result.returncode

    # Verify output
    written = [d for d in needs_eval if (d / "eval_legs.csv").exists()]
    print(f"\n[DONE] eval_legs.csv written to {len(written)}/{len(needs_eval)} dirs.")
    for d in needs_eval:
        status = "OK" if (d / "eval_legs.csv").exists() else "MISSING"
        rows = ""
        if status == "OK":
            try:
                import pandas as pd
                rows = f"  ({len(pd.read_csv(d / 'eval_legs.csv'))} rows)"
            except Exception:
                pass
        print(f"  [{status}] {d.name}{rows}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
