#!/usr/bin/env python
"""
Re-calibrate p_cal in all 12 corpus scored_legs_deduped.csv files
using the new direction-split isotonic calibration.

Backs up original p_cal to p_cal_old, then overwrites p_cal
with the new calibrated value from p_adj.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1] / "data" / "telemetry" / "replay_runs"
_TAG_FILE = BASE / ".corpus_tag"
_CORPUS_TAG = _TAG_FILE.read_text().strip() if _TAG_FILE.exists() else "kernel_v2_perstat_corr015"
RUN_DATES = [
    "20260315", "20260316", "20260317", "20260318",
    "20260319", "20260320", "20260321", "20260322",
    "20260323", "20260324", "20260325", "20260326",
]

CAL_PATH = Path(__file__).resolve().parents[1] / "data" / "model" / "telemetry_calibration.isotonic_direction_split.json"


def load_calibration(path: Path):
    """Load the direction-split isotonic JSON and return (over_x, over_y, under_x, under_y, under_stat_dirs)."""
    with open(path) as f:
        cal = json.load(f)
    meta = cal["meta"]
    over_x = np.array(meta["x_thresholds"])
    over_y = np.array(meta["y_thresholds"])
    prot = meta["protected_calibration"]["meta"]
    under_x = np.array(prot["x_thresholds"])
    under_y = np.array(prot["y_thresholds"])
    under_stat_dirs = set(meta["protected_stat_directions"])
    return over_x, over_y, under_x, under_y, under_stat_dirs


def isotonic_predict(x_thresh: np.ndarray, y_thresh: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Apply isotonic piecewise-linear interpolation (same as sklearn)."""
    return np.interp(values, x_thresh, y_thresh).clip(0.01, 0.99)


def main():
    print("Loading calibration from:", CAL_PATH)
    over_x, over_y, under_x, under_y, under_stat_dirs = load_calibration(CAL_PATH)
    print(f"  OVER curve: {len(over_x)} breakpoints")
    print(f"  UNDER curve: {len(under_x)} breakpoints")
    print(f"  Protected stat|directions: {len(under_stat_dirs)}")

    total_files = 0
    total_rows = 0
    t0 = time.time()

    for date in RUN_DATES:
        run_dir = BASE / f"{_CORPUS_TAG}_{date}"
        if not run_dir.exists():
            print(f"  SKIP {date}: dir not found")
            continue
        scored_files = list(run_dir.rglob("scored_legs_deduped.csv"))
        if not scored_files:
            print(f"  SKIP {date}: no scored_legs_deduped.csv")
            continue
        for scored_path in scored_files:
            df = pd.read_csv(scored_path, low_memory=False)
            if "p_adj" not in df.columns or "p_cal" not in df.columns:
                print(f"  SKIP {scored_path}: missing p_adj or p_cal")
                continue

            # Backup original
            df["p_cal_old"] = df["p_cal"].copy()

            # Build stat|direction key for mask
            stat = df["stat"].astype(str).str.upper().str.strip()
            direction = df["direction"].astype(str).str.upper().str.strip()
            stat_dir = stat + "|" + direction

            p_adj = np.asarray(pd.to_numeric(df["p_adj"], errors="coerce").fillna(0.5).values, dtype=float)

            # Default: apply OVER curve to all
            new_p_cal = isotonic_predict(over_x, over_y, p_adj)

            # Override UNDER legs with UNDER curve
            under_mask = np.asarray(stat_dir.isin(under_stat_dirs).values, dtype=bool)
            if under_mask.any():
                new_p_cal[under_mask] = isotonic_predict(under_x, under_y, p_adj[under_mask])

            df["p_cal"] = new_p_cal
            df.to_csv(scored_path, index=False)

            n_under = int(under_mask.sum())
            old_under_mean = df.loc[under_mask, "p_cal_old"].mean() if n_under > 0 else 0
            new_under_mean = df.loc[under_mask, "p_cal"].mean() if n_under > 0 else 0
            print(f"  {date}: {len(df)} rows, {n_under} UNDER legs  "
                  f"p_cal_old={old_under_mean:.3f} -> p_cal={new_under_mean:.3f}")
            total_files += 1
            total_rows += len(df)

    elapsed = time.time() - t0
    print(f"\nDone: {total_files} files, {total_rows} rows re-calibrated in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
