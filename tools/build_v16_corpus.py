"""
Extract today's v16 replay runs into a clean, organized corpus folder.

Structure:
    data/telemetry/v16_corpus/
        20260209/
            scored_legs_deduped.csv
            eval_legs.csv
        20260210/
            ...

Also includes the 3 dates already replayed with v16 kernel (Apr 9, 10, 12).
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPLAY_DIR = ROOT / "data" / "telemetry" / "replay_runs"
_TAG_FILE = REPLAY_DIR / ".corpus_tag"
_CORPUS_TAG = _TAG_FILE.read_text().strip() if _TAG_FILE.exists() else "kernel_v2_perstat_corr015"
V16_CORPUS = ROOT / "data" / "telemetry" / "v16_corpus"

# Columns that only exist in v16 kernel output
V16_MARKERS = {"blowout_base_min_for_curve", "blowout_minute_delta", "role_ctx_damp_applied"}

# Dates to skip
SKIP_DATES = {"20260213", "20260214", "20260215", "20260216", "20260217", "20260218", "test"}

# Apr 14 has Apr 15 games (no truth yet)
SKIP_DATES.add("20260414")


def _find_latest_v16_run(scenario_dir: Path) -> Path | None:
    """Find the latest scored_legs_deduped.csv that has v16 kernel markers.
    
    Returns the run directory (parent of scored_legs), not the file itself.
    """
    candidates = sorted(scenario_dir.rglob("scored_legs_deduped.csv"))
    
    # Walk backwards from newest to find the latest v16 file
    for sf in reversed(candidates):
        try:
            cols = set(pd.read_csv(sf, nrows=0).columns)
            if V16_MARKERS.issubset(cols):
                return sf.parent  # the run dir containing scored_legs
        except Exception:
            continue
    return None


def _find_eval_for_run(run_dir: Path, scenario_dir: Path) -> Path | None:
    """Find eval_legs.csv — prefer same run dir, fall back to scenario dir."""
    # First: check same run directory
    eval_f = run_dir / "eval_legs.csv"
    if eval_f.is_file():
        return eval_f
    
    # Second: check parent dirs up to scenario_dir
    for parent in run_dir.parents:
        if parent == scenario_dir.parent:
            break
        ef = parent / "eval_legs.csv"
        if ef.is_file():
            return ef
    
    # Third: find the most recent eval_legs anywhere in scenario_dir
    all_evals = sorted(scenario_dir.rglob("eval_legs.csv"), key=lambda p: p.stat().st_mtime)
    if all_evals:
        return all_evals[-1]
    
    return None


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    # Create clean corpus dir
    if not dry_run:
        V16_CORPUS.mkdir(parents=True, exist_ok=True)

    dates_found = []
    dates_missing_v16 = []
    dates_missing_eval = []
    
    for d in sorted(REPLAY_DIR.glob(f"{_CORPUS_TAG}_*")):
        date_str = d.name.split("_")[-1]
        if date_str in SKIP_DATES:
            continue
        
        # Find the latest v16 run
        run_dir = _find_latest_v16_run(d)
        if not run_dir:
            dates_missing_v16.append(date_str)
            continue
        
        scored_path = run_dir / "scored_legs_deduped.csv"
        
        # Find eval_legs
        eval_path = _find_eval_for_run(run_dir, d)
        
        # Check hit fill
        hit_fill = "N/A"
        n_eval = 0
        if eval_path:
            try:
                ef = pd.read_csv(eval_path, low_memory=False)
                n_eval = len(ef)
                if "hit" in ef.columns:
                    hit_fill = f"{ef.hit.notna().mean() * 100:.0f}%"
            except Exception:
                pass
        
        if not eval_path or hit_fill in ("N/A", "0%"):
            dates_missing_eval.append((date_str, eval_path is not None))
            # Still include — eval might be regeneratable
            if not eval_path:
                continue
        
        n_scored = len(pd.read_csv(scored_path, usecols=["player"]))
        
        dates_found.append({
            "date": date_str,
            "scored_path": scored_path,
            "eval_path": eval_path,
            "n_scored": n_scored,
            "n_eval": n_eval,
            "hit_fill": hit_fill,
            "run_dir": run_dir,
        })
    
    # Report
    print(f"{'='*70}")
    print(f"v16 Corpus Builder")
    print(f"{'='*70}")
    print(f"Source: {REPLAY_DIR}")
    print(f"Destination: {V16_CORPUS}")
    print(f"")
    print(f"Found {len(dates_found)} dates with v16 kernel scored_legs")
    if dates_missing_v16:
        print(f"Missing v16 kernel: {len(dates_missing_v16)} dates: {dates_missing_v16}")
    if dates_missing_eval:
        print(f"Missing/bad eval: {len(dates_missing_eval)} dates: {[(d,e) for d,e in dates_missing_eval]}")
    print()
    
    total_legs = 0
    print(f"{'Date':>10s} {'Scored':>7s} {'Eval':>6s} {'Hit':>5s} {'Run Dir'}")
    print("-" * 90)
    for info in dates_found:
        rel_run = info["run_dir"].relative_to(REPLAY_DIR)
        print(f"{info['date']:>10s} {info['n_scored']:>7d} {info['n_eval']:>6d} {info['hit_fill']:>5s} {rel_run}")
        total_legs += info["n_scored"]
    
    print(f"\nTotal: {len(dates_found)} dates, {total_legs:,} scored legs")
    
    if dry_run:
        print("\n[DRY RUN] No files copied.")
        return 0
    
    # Copy files into clean structure
    print(f"\nCopying to {V16_CORPUS}...")
    for info in dates_found:
        dest_dir = V16_CORPUS / info["date"]
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy scored_legs_deduped.csv
        shutil.copy2(str(info["scored_path"]), str(dest_dir / "scored_legs_deduped.csv"))
        
        # Copy eval_legs.csv
        if info["eval_path"]:
            shutil.copy2(str(info["eval_path"]), str(dest_dir / "eval_legs.csv"))
        
        # Also copy scored_legs.csv if it exists (some tools use it)
        scored_full = info["run_dir"] / "scored_legs.csv"
        if scored_full.is_file():
            shutil.copy2(str(scored_full), str(dest_dir / "scored_legs.csv"))
        
        # Copy any recommended slip CSVs
        for slip_csv in info["run_dir"].glob("recommended_*.csv"):
            shutil.copy2(str(slip_csv), str(dest_dir / slip_csv.name))
    
    print(f"Done. {len(dates_found)} date folders created in {V16_CORPUS}")
    
    # Verify
    print(f"\nVerification:")
    for info in dates_found:
        dest_dir = V16_CORPUS / info["date"]
        has_scored = (dest_dir / "scored_legs_deduped.csv").is_file()
        has_eval = (dest_dir / "eval_legs.csv").is_file()
        status = "OK" if has_scored and has_eval else "MISSING"
        if not has_eval:
            status = "NO_EVAL"
        print(f"  {info['date']}  {status}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
