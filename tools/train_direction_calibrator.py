#!/usr/bin/env python
"""
Direction-Split Isotonic Calibrator Trainer
===========================================
Trains separate isotonic regression curves for OVER vs UNDER legs using
the 12-date D-drive corpus. Outputs an isotonic_hybrid JSON that the
existing telemetry calibration pipeline can load directly.

Root cause addressed:
  - UNDER legs in 0.80+ range: model 91.7%, actual 51.0% (-40.7% gap)
  - OVER legs at 0.60+: model is honest (gap +1.6%)
  - HIT/winprob mode picks highest-prob legs → selects overconfident UNDERs
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

# ── data paths ──────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = _REPO_ROOT / "data" / "telemetry" / "v17_corpus"
OUTPUT_DIR = _REPO_ROOT / "data" / "model"

# Regular-season dates in v17_corpus
RUN_DATES = [
    "20260209", "20260210", "20260211", "20260212",
    "20260225", "20260226", "20260227", "20260228",
    "20260301", "20260302", "20260303", "20260304",
    "20260305", "20260306", "20260307", "20260308",
    "20260309", "20260310", "20260315", "20260316",
    "20260317", "20260318", "20260319", "20260320",
    "20260321", "20260322", "20260323", "20260324",
    "20260325", "20260326", "20260328", "20260330",
    "20260331", "20260401", "20260402", "20260403",
    "20260404", "20260405", "20260406", "20260407",
    "20260408", "20260409", "20260410", "20260412",
]

# Playoff run dirs (explicit paths — not in corpus folder)
EXTRA_RUN_DIRS: list[Path] = [
    _REPO_ROOT / "data" / "output" / "runs" / "20260430_182420",
    _REPO_ROOT / "data" / "telemetry" / "live_runs" / "20260501_110422",
    _REPO_ROOT / "data" / "telemetry" / "live_runs" / "20260502_110546",
]


def _load_run_dir(run_dir: Path, date: str, all_rows: list) -> None:
    """Load one run dir and append rows to all_rows."""
    eval_files = list(run_dir.rglob("eval_legs.csv"))
    scored_files = list(run_dir.rglob("scored_legs_deduped.csv"))
    if not eval_files or not scored_files:
        return
    eval_df = pd.read_csv(eval_files[0], low_memory=False)
    scored_df = pd.read_csv(scored_files[0], low_memory=False)

    # Build truth lookup
    truth: dict[tuple, int] = {}
    for _, row in eval_df.iterrows():
        p = str(row.get("player", "")).strip().lower()
        l = float(row["line"]) if pd.notna(row.get("line")) else 0
        s = str(row.get("stat", "")).strip().upper()
        d = str(row.get("direction", "")).strip().lower()
        if pd.notna(row.get("hit")):
            truth[(p, l, s, d)] = int(row["hit"])

    # Use p_cal (post-GBM) as input — we're correcting what gets displayed
    prob_col = None
    for c in ("p_cal", "p_adj", "p"):
        if c in scored_df.columns:
            prob_col = c
            break
    if not prob_col:
        return

    for _, row in scored_df.iterrows():
        p = str(row.get("player", "")).strip().lower()
        l = float(row["line"]) if pd.notna(row.get("line")) else 0
        s = str(row.get("stat", "")).strip().upper()
        d = str(row.get("direction", "")).strip().lower()
        prob = float(row[prob_col]) if pd.notna(row.get(prob_col)) else 0.5
        key = (p, l, s, d)
        if key in truth:
            all_rows.append({
                "stat": s, "direction": d, "prob": prob,
                "hit": truth[key], "date": date,
                "stat_dir": f"{s}|{d.upper()}",
                "prob_col_used": prob_col,
            })


def load_corpus() -> pd.DataFrame:
    """Load scored legs + truth from all corpus dates (regular season + playoff)."""
    all_rows: list = []
    for date in RUN_DATES:
        run_dir = BASE / date
        if not run_dir.exists():
            continue
        _load_run_dir(run_dir, date, all_rows)

    # Playoff extra dirs
    for run_dir in EXTRA_RUN_DIRS:
        if not run_dir.exists():
            print(f"  [WARN] Playoff dir not found: {run_dir}")
            continue
        date = run_dir.name[:8]
        _load_run_dir(run_dir, date, all_rows)

    return pd.DataFrame(all_rows)


def _load_corpus_OLD() -> pd.DataFrame:
    """Legacy loader kept for reference — not used."""
    all_rows = []
    for date in RUN_DATES:
        run_dir = BASE / date
        if not run_dir.exists():
            continue
        eval_files = list(run_dir.rglob("eval_legs.csv"))
        scored_files = list(run_dir.rglob("scored_legs_deduped.csv"))
        if not eval_files or not scored_files:
            continue
        eval_df = pd.read_csv(eval_files[0], low_memory=False)
        scored_df = pd.read_csv(scored_files[0], low_memory=False)

        # Build truth lookup
        truth: dict[tuple, int] = {}
        for _, row in eval_df.iterrows():
            p = str(row.get("player", "")).strip().lower()
            l = float(row["line"]) if pd.notna(row.get("line")) else 0
            s = str(row.get("stat", "")).strip().upper()
            d = str(row.get("direction", "")).strip().lower()
            if pd.notna(row.get("hit")):
                truth[(p, l, s, d)] = int(row["hit"])

        # Use p_adj as input — this replaces old calibration entirely
        prob_col = None
        for c in ("p_adj", "p"):
            if c in scored_df.columns:
                prob_col = c
                break
        if not prob_col:
            continue

        for _, row in scored_df.iterrows():
            p = str(row.get("player", "")).strip().lower()
            l = float(row["line"]) if pd.notna(row.get("line")) else 0
            s = str(row.get("stat", "")).strip().upper()
            d = str(row.get("direction", "")).strip().lower()
            prob = float(row[prob_col]) if pd.notna(row.get(prob_col)) else 0.5
            key = (p, l, s, d)
            if key in truth:
                all_rows.append({
                    "stat": s, "direction": d, "prob": prob,
                    "hit": truth[key], "date": date,
                    "stat_dir": f"{s}|{d.upper()}",
                })
    return pd.DataFrame(all_rows)


def fit_isotonic(probs: np.ndarray, hits: np.ndarray) -> tuple[list[float], list[float]]:
    """Fit isotonic regression and return (x_thresholds, y_thresholds)."""
    ir = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds="clip")
    ir.fit(probs, hits)

    # Extract the piecewise-linear breakpoints
    x_thresh = ir.X_thresholds_.tolist()
    y_thresh = ir.y_thresholds_.tolist()
    return x_thresh, y_thresh


def evaluate_calibration(
    probs: np.ndarray,
    hits: np.ndarray,
    calibrated: np.ndarray,
    label: str,
) -> None:
    """Print calibration diagnostics before vs after."""
    bins = [(0.0, 0.50), (0.50, 0.55), (0.55, 0.60), (0.60, 0.65),
            (0.65, 0.70), (0.70, 0.80), (0.80, 1.01)]

    print(f"\n  {label} calibration evaluation ({len(probs)} legs):")
    print(f"  {'Range':<12} {'N':>6} {'Before':>8} {'After':>8} {'Actual':>8} {'Gap_B':>7} {'Gap_A':>7}")
    print("  " + "-" * 62)
    for lo, hi in bins:
        mask = (probs >= lo) & (probs < hi)
        n = mask.sum()
        if n == 0:
            continue
        before = probs[mask].mean()
        after = calibrated[mask].mean()
        actual = hits[mask].mean()
        gap_b = actual - before
        gap_a = actual - after
        print(f"  {lo:.2f}-{hi:.2f}   {n:>6} {before:>8.3f} {after:>8.3f} {actual:>8.3f} {gap_b:>+7.3f} {gap_a:>+7.3f}")

    # Overall Brier
    brier_before = np.mean((probs - hits) ** 2)
    brier_after = np.mean((calibrated - hits) ** 2)
    print(f"  Brier: {brier_before:.6f} -> {brier_after:.6f} (delta {brier_after - brier_before:+.6f})")


def main() -> None:
    print("=" * 60)
    print("Direction-Split Isotonic Calibrator")
    print("=" * 60)

    print("\nLoading corpus...")
    t0 = time.time()
    df = load_corpus()
    print(f"Loaded {len(df)} matched legs from {df['date'].nunique()} dates in {time.time()-t0:.1f}s")

    # Split by direction
    over_df = df[df["direction"] == "over"].copy()
    under_df = df[df["direction"] == "under"].copy()
    print(f"  OVER: {len(over_df)} legs, model avg={over_df['prob'].mean():.3f}, actual={over_df['hit'].mean():.3f}")
    print(f"  UNDER: {len(under_df)} legs, model avg={under_df['prob'].mean():.3f}, actual={under_df['hit'].mean():.3f}")

    over_prob = np.asarray(over_df["prob"].values, dtype=float)
    over_hit = np.asarray(over_df["hit"].values, dtype=float)
    under_prob = np.asarray(under_df["prob"].values, dtype=float)
    under_hit = np.asarray(under_df["hit"].values, dtype=float)
    all_prob = np.asarray(df["prob"].values, dtype=float)
    all_hit = np.asarray(df["hit"].values, dtype=float)

    # Fit OVER isotonic
    print("\nFitting OVER isotonic...")
    over_x, over_y = fit_isotonic(over_prob, over_hit)
    print(f"  {len(over_x)} breakpoints")

    # Fit UNDER isotonic
    print("Fitting UNDER isotonic...")
    under_x, under_y = fit_isotonic(under_prob, under_hit)
    print(f"  {len(under_x)} breakpoints")

    # Evaluate
    ir_over = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds="clip")
    ir_over.fit(over_prob, over_hit)
    over_cal = ir_over.predict(over_prob)
    evaluate_calibration(over_prob, over_hit, over_cal, "OVER")

    ir_under = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds="clip")
    ir_under.fit(under_prob, under_hit)
    under_cal = ir_under.predict(under_prob)
    evaluate_calibration(under_prob, under_hit, under_cal, "UNDER")

    # Also evaluate combined (what the main curve would do to UNDER if we didn't split)
    ir_combined = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds="clip")
    ir_combined.fit(all_prob, all_hit)
    combined_under_cal = ir_combined.predict(under_prob)
    evaluate_calibration(under_prob, under_hit, combined_under_cal, "UNDER (if using combined curve)")

    # Get all unique stat|direction combos for UNDER to use as protected_stat_directions
    under_stat_dirs = sorted(under_df["stat_dir"].unique().tolist())
    print(f"\nProtected stat_directions (UNDER): {under_stat_dirs}")

    # Build the isotonic_hybrid JSON
    # Main curve: OVER isotonic (applied to non-protected legs)
    # Protected curve: UNDER isotonic (applied to UNDER legs)
    calibration = {
        "mode": "isotonic_hybrid",
        "candidate": "isotonic_hybrid_direction_split",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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

    # Write to the production file that config.yaml already points to
    out_path = OUTPUT_DIR / "telemetry_calibration.demon_isotonic.json"
    # Also write a dated backup
    backup_path = OUTPUT_DIR / f"telemetry_calibration.isotonic_direction_split_{datetime.now().strftime('%Y%m%d')}.json"
    with open(backup_path, "w") as f:
        json.dump(calibration, f, indent=2)
    print(f"Backup saved to: {backup_path}")
    with open(out_path, "w") as f:
        json.dump(calibration, f, indent=2)
    print(f"\nSaved to: {out_path}")

    # Print the key before/after for UNDER high-prob tail
    print("\n=== KEY RESULT: UNDER 0.80+ tail ===")
    tail = under_df[under_df["prob"] >= 0.80]
    if len(tail) == 0:
        print("  N=0 legs with p_cal >= 0.80 (good — model no longer produces extreme UNDER probs)")
    else:
        tail_cal = ir_under.predict(np.asarray(tail["prob"].values, dtype=float))
        print(f"  N={len(tail)} legs")
        print(f"  Before: model avg={tail['prob'].mean():.3f}, actual={tail['hit'].mean():.3f}")
        print(f"  After:  calibrated avg={tail_cal.mean():.3f}, actual={tail['hit'].mean():.3f}")
        print(f"  Gap reduced: {tail['hit'].mean()-tail['prob'].mean():+.3f} -> {tail['hit'].mean()-tail_cal.mean():+.3f}")


if __name__ == "__main__":
    main()
