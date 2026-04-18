#!/usr/bin/env python
r"""
Backfill eval_legs.csv for all corpus dates missing them,
then refresh the v12_corpus folder.

Usage:
    python tools/backfill_eval_and_refresh_corpus.py
    python tools/backfill_eval_and_refresh_corpus.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CORPUS = ROOT / "data" / "telemetry" / "replay_runs"
GAMELOGS = ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"


def find_all_replay_dirs() -> list[tuple[str, Path]]:
    """Find all kernel_v2 dirs in the workspace corpus, return (date, run_dir) pairs."""
    import re
    results = []
    for base in [CORPUS]:
        if not base.exists():
            continue
        _tag_file = base / ".corpus_tag"
        _tag = _tag_file.read_text().strip() if _tag_file.exists() else "kernel_v2_perstat_corr015"
        for d in sorted(base.glob(f"{_tag}_*")):
            m = re.search(r"(\d{8})$", d.name)
            if not m:
                continue
            date = m.group(1)
            # Find the actual run dir (could be nested)
            scored_files = list(d.rglob("scored_legs_deduped.csv"))
            if scored_files:
                run_dir = scored_files[-1].parent
                results.append((date, run_dir))
    # Dedupe by date (prefer D drive)
    seen = {}
    for date, run_dir in results:
        if date not in seen:
            seen[date] = run_dir
    return sorted(seen.items())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from Atlas.runtime.replay_eval import backfill_eval_legs_for_run

    all_dirs = find_all_replay_dirs()
    print(f"Found {len(all_dirs)} replay dates")

    missing_eval = []
    for date, run_dir in all_dirs:
        eval_path = run_dir / "eval_legs.csv"
        if not eval_path.exists() or eval_path.stat().st_size < 100:
            missing_eval.append((date, run_dir))

    print(f"Missing eval_legs: {len(missing_eval)}")
    for date, run_dir in missing_eval:
        print(f"  {date}: {run_dir}")

    if args.dry_run:
        return 0

    if not GAMELOGS.exists():
        print(f"ERROR: gamelogs not found at {GAMELOGS}")
        return 1

    ok = 0
    fail = 0
    for date, run_dir in missing_eval:
        print(f"\nBackfilling eval_legs for {date}...")

        # Fix game_date if it doesn't match the corpus date
        # (raw JSON replays stamp today's date instead of the slate date)
        scored_path = run_dir / "scored_legs_deduped.csv"
        if scored_path.exists():
            iso_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            df_check = pd.read_csv(scored_path, usecols=["game_date"], nrows=3)
            if df_check["game_date"].iloc[0] != iso_date:
                print(f"  Fixing game_date: {df_check['game_date'].iloc[0]} -> {iso_date}")
                df_fix = pd.read_csv(scored_path, low_memory=False)
                df_fix["game_date"] = iso_date
                df_fix.to_csv(scored_path, index=False)
                # Also fix scored_legs.csv if present
                scored_all = run_dir / "scored_legs.csv"
                if scored_all.exists():
                    df_all = pd.read_csv(scored_all, low_memory=False)
                    df_all["game_date"] = iso_date
                    df_all.to_csv(scored_all, index=False)

        try:
            result = backfill_eval_legs_for_run(
                run_dir=run_dir,
                gamelogs_path=GAMELOGS,
                repo_root=ROOT,
            )
            df = pd.read_csv(result)
            n_hit = df["hit"].notna().sum() if "hit" in df.columns else 0
            print(f"  OK: {len(df)} rows, {n_hit} with truth")
            ok += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            fail += 1

    print(f"\nEval backfill: {ok} ok, {fail} failed")

    # Now refresh v12 corpus
    print("\nRefreshing v12 corpus...")
    import subprocess
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "build_v12_corpus.py"), "--force"],
        cwd=str(ROOT),
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
