#!/usr/bin/env python
"""
Playoff Isotonic Calibrator Trainer
=====================================
Trains direction-split isotonic regression curves using PLAYOFF eval legs only
(Apr 30, 2026 onwards). Uses eval_legs.csv directly — no join with scored_legs
required since eval_legs already contains p_cal + hit.

Key difference from train_direction_calibrator.py:
  - Loads from data/telemetry/live_runs/ (live run eval archive)
  - Playoff dates only (>= PLAYOFF_START_DATE)
  - Deduplicates across multiple same-day runs (each real leg counted once)
  - Saves to telemetry_calibration.playoff_isotonic.json
  - Prints enable/disable instructions at the end

Usage:
    python tools/train_playoff_isotonic.py

To activate in config.yaml:
    telemetry:
      active_calibration: playoff_isotonic
      active_calibration_path: data/model/telemetry_calibration.playoff_isotonic.json
      apply_active_calibration: true

To deactivate:
      apply_active_calibration: false
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

_REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_RUNS_DIR = _REPO_ROOT / "data" / "telemetry" / "live_runs"
OUTPUT_DIR = _REPO_ROOT / "data" / "model"
OUTPUT_FILE = OUTPUT_DIR / "telemetry_calibration.playoff_isotonic.json"

# Playoffs start date (inclusive) — Round 1 tipped Apr 19, but we have eval from Apr 30
PLAYOFF_START_DATE = "2026-04-30"

# Columns we need from eval_legs
REQUIRED_COLS = {"player", "stat", "direction", "line", "game_date", "p_cal", "hit"}


def load_playoff_corpus() -> pd.DataFrame:
    """
    Load all eval_legs.csv from live_runs, filter to playoff dates,
    and deduplicate so each (player, stat, direction, line, game_date) counts once.
    """
    all_frames: list[pd.DataFrame] = []

    eval_files = sorted(LIVE_RUNS_DIR.glob("*/eval_legs.csv"))
    print(f"Found {len(eval_files)} eval_legs files in live_runs/")

    for path in eval_files:
        try:
            df = pd.read_csv(path, low_memory=False)
        except Exception as e:
            print(f"  [SKIP] {path.parent.name}: {e}")
            continue

        # Check required columns
        missing = REQUIRED_COLS - set(df.columns)
        if missing:
            print(f"  [SKIP] {path.parent.name}: missing columns {missing}")
            continue

        # Filter to playoff dates
        df = df[df["game_date"] >= PLAYOFF_START_DATE].copy()
        if df.empty:
            continue

        # Keep only valid rows (hit must be 0 or 1, p_cal must be numeric)
        df["p_cal"] = pd.to_numeric(df["p_cal"], errors="coerce")
        df["hit"] = pd.to_numeric(df["hit"], errors="coerce")
        df = df[df["p_cal"].notna() & df["hit"].notna() & df["hit"].isin([0, 1])].copy()

        if df.empty:
            continue

        # Normalize direction to lowercase for internal use (isotonic keys are lowercase)
        df["direction"] = df["direction"].astype(str).str.strip().str.lower()
        df["stat"] = df["stat"].astype(str).str.strip().str.upper()
        df["player"] = df["player"].astype(str).str.strip().str.lower()

        all_frames.append(df[["player", "stat", "direction", "line", "game_date", "p_cal", "hit"]])

    if not all_frames:
        print("ERROR: No valid playoff eval legs found.")
        sys.exit(1)

    combined = pd.concat(all_frames, ignore_index=True)

    # Deduplicate — same leg may appear across multiple same-day runs.
    # Keep first occurrence (all runs of the same day have the same p_cal for a given leg
    # since it's the same board scored by the same model snapshot).
    before = len(combined)
    combined = combined.drop_duplicates(
        subset=["player", "stat", "direction", "line", "game_date"]
    ).reset_index(drop=True)
    after = len(combined)

    print(f"Deduplication: {before:,} rows -> {after:,} unique legs")
    return combined


def fit_isotonic(probs: np.ndarray, hits: np.ndarray) -> tuple[list[float], list[float]]:
    """Fit monotonic isotonic regression and return breakpoint lists."""
    ir = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds="clip")
    ir.fit(probs, hits)
    return ir.X_thresholds_.tolist(), ir.y_thresholds_.tolist()


def evaluate(probs: np.ndarray, hits: np.ndarray, cal: np.ndarray, label: str) -> float:
    """Print tier-by-tier calibration table and return post-calibration Brier."""
    bins = [
        (0.0,  0.50),
        (0.50, 0.55),
        (0.55, 0.60),
        (0.60, 0.65),
        (0.65, 0.70),
        (0.70, 0.75),
        (0.75, 0.80),
        (0.80, 0.85),
        (0.85, 1.01),
    ]
    print(f"\n  {label}  ({len(probs):,} legs)")
    print(f"  {'Tier':<12} {'N':>6} {'Before':>8} {'After':>8} {'Actual':>8} {'Gap_B':>7} {'Gap_A':>7}")
    print("  " + "-" * 64)
    for lo, hi in bins:
        mask = (probs >= lo) & (probs < hi)
        n = int(mask.sum())
        if n < 5:
            continue
        before = float(probs[mask].mean())
        after  = float(cal[mask].mean())
        actual = float(hits[mask].mean())
        print(f"  {lo:.2f}-{hi:.2f}   {n:>6} {before:>8.3f} {after:>8.3f} {actual:>8.3f} "
              f"{actual-before:>+7.3f} {actual-after:>+7.3f}")

    brier_b = float(np.mean((probs - hits) ** 2))
    brier_a = float(np.mean((cal - hits) ** 2))
    print(f"  Brier: {brier_b:.6f} -> {brier_a:.6f}  (delta {brier_a-brier_b:+.6f})")
    return brier_a


def main() -> None:
    print("=" * 60)
    print("Playoff Isotonic Calibrator — Direction Split")
    print(f"Playoff corpus: {PLAYOFF_START_DATE} onwards")
    print("=" * 60)

    t0 = time.time()
    df = load_playoff_corpus()

    dates = sorted(df["game_date"].unique())
    print(f"\nLoaded {len(df):,} unique legs across {len(dates)} playoff dates")
    print(f"Dates: {dates}")
    print(f"Load time: {time.time()-t0:.1f}s")

    # Split by direction
    over_df  = df[df["direction"] == "over"].copy()
    under_df = df[df["direction"] == "under"].copy()
    print(f"\n  OVER  : {len(over_df):,} legs | model avg={over_df['p_cal'].mean():.3f} | actual={over_df['hit'].mean():.3f}")
    print(f"  UNDER : {len(under_df):,} legs | model avg={under_df['p_cal'].mean():.3f} | actual={under_df['hit'].mean():.3f}")

    if len(over_df) < 200 or len(under_df) < 200:
        print("\nWARNING: Very few legs for one direction — isotonic may overfit. Proceed with caution.")

    over_prob  = over_df["p_cal"].to_numpy(dtype=float)
    over_hit   = over_df["hit"].to_numpy(dtype=float)
    under_prob = under_df["p_cal"].to_numpy(dtype=float)
    under_hit  = under_df["hit"].to_numpy(dtype=float)

    # Fit curves
    print("\nFitting OVER isotonic...")
    over_x, over_y = fit_isotonic(over_prob, over_hit)
    ir_over = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds="clip")
    ir_over.fit(over_prob, over_hit)
    over_cal = ir_over.predict(over_prob)
    print(f"  {len(over_x)} breakpoints")

    print("Fitting UNDER isotonic...")
    under_x, under_y = fit_isotonic(under_prob, under_hit)
    ir_under = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds="clip")
    ir_under.fit(under_prob, under_hit)
    under_cal = ir_under.predict(under_prob)
    print(f"  {len(under_x)} breakpoints")

    # Evaluate
    print("\n--- Calibration Diagnostics ---")
    evaluate(over_prob, over_hit, over_cal, "OVER")
    evaluate(under_prob, under_hit, under_cal, "UNDER")

    # Build stat|direction keys for all UNDER combos (used as protected routing keys)
    under_stat_dirs = sorted(
        (under_df["stat"] + "|" + under_df["direction"].str.upper())
        .unique().tolist()
    )
    print(f"\nProtected stat_directions (UNDER routing): {len(under_stat_dirs)} keys")

    # Build output JSON — same schema as existing calibrators
    # Main curve: OVER isotonic (applied to all non-protected legs)
    # Protected curve: UNDER isotonic (routed via protected_stat_directions)
    calibration = {
        "mode": "isotonic_hybrid",
        "candidate": "playoff_isotonic_direction_split",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "playoff_dates": dates,
        "n_legs": {"total": len(df), "over": len(over_df), "under": len(under_df)},
        "meta": {
            "family": "isotonic_hybrid",
            "mix": 1.0,
            "source_col": "p_cal",
            "x_thresholds": over_x,
            "y_thresholds": over_y,
            "protected_calibration": {
                "mode": "isotonic_global",
                "meta": {
                    "mix": 1.0,
                    "x_thresholds": under_x,
                    "y_thresholds": under_y,
                },
            },
            "protected_stat_directions": under_stat_dirs,
        },
    }

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = OUTPUT_DIR / f"telemetry_calibration.playoff_isotonic_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(OUTPUT_FILE, "w") as f:
        json.dump(calibration, f, indent=2)
    with open(backup_path, "w") as f:
        json.dump(calibration, f, indent=2)

    print(f"\nSaved: {OUTPUT_FILE}")
    print(f"Backup: {backup_path}")

    print("\n" + "=" * 60)
    print("TO ACTIVATE in config.yaml:")
    print("  telemetry:")
    print("    active_calibration: playoff_isotonic")
    print("    active_calibration_path: data/model/telemetry_calibration.playoff_isotonic.json")
    print("    apply_active_calibration: true")
    print()
    print("TO DEACTIVATE:")
    print("    apply_active_calibration: false")
    print()
    print("NOTE: This isotonic sits ON TOP of the GBM p_cal output.")
    print("      It does NOT replace the GBM — it corrects its output probabilities")
    print("      for the playoff regime. Re-run this trainer as more playoff dates")
    print("      accumulate (target: weekly refresh).")
    print("=" * 60)


if __name__ == "__main__":
    main()
