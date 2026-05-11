"""
Retrain playoff isotonic on p_for_cal (MC signal, pre-GBM) so the curves
are calibrated for GBM-disabled mode. Writes the correct isotonic_hybrid
JSON structure that train_playoff_isotonic.py uses.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

LIVE_RUNS_DIR = _REPO_ROOT / "data" / "telemetry" / "live_runs"
OUTPUT_FILE = _REPO_ROOT / "data" / "model" / "telemetry_calibration.playoff_isotonic.json"
PLAYOFF_START = "2026-04-30"
SOURCE_COL = "p_for_cal"

REQUIRED = {"player", "stat", "direction", "line", "game_date", SOURCE_COL, "hit"}

# Load and deduplicate
frames: list[pd.DataFrame] = []
for path in sorted(LIVE_RUNS_DIR.glob("*/eval_legs.csv")):
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        continue
    if not REQUIRED.issubset(df.columns):
        continue
    df = df[df["game_date"] >= PLAYOFF_START].copy()
    if df.empty:
        continue
    df[SOURCE_COL] = pd.to_numeric(df[SOURCE_COL], errors="coerce")
    df["hit"] = pd.to_numeric(df["hit"], errors="coerce")
    df = df[df[SOURCE_COL].notna() & df["hit"].isin([0, 1])].copy()
    df["direction"] = df["direction"].astype(str).str.strip().str.lower()
    df["stat"] = df["stat"].astype(str).str.strip().str.upper()
    frames.append(df[["player", "stat", "direction", "line", "game_date", SOURCE_COL, "hit"]])

combined = pd.concat(frames, ignore_index=True)
before = len(combined)
combined = combined.drop_duplicates(
    subset=["player", "stat", "direction", "line", "game_date"]
).reset_index(drop=True)

dates = sorted(combined["game_date"].unique())
print(f"Dedup: {before:,} -> {len(combined):,} unique legs across {len(dates)} dates")
print(f"Dates: {dates}")

over_df  = combined[combined["direction"] == "over"].copy()
under_df = combined[combined["direction"] == "under"].copy()
print(f"OVER  {len(over_df):,} | {SOURCE_COL} avg={over_df[SOURCE_COL].mean():.3f} actual={over_df['hit'].mean():.3f}")
print(f"UNDER {len(under_df):,} | {SOURCE_COL} avg={under_df[SOURCE_COL].mean():.3f} actual={under_df['hit'].mean():.3f}")


def fit_and_eval(df: pd.DataFrame, label: str) -> tuple[list[float], list[float], float, float]:
    probs = df[SOURCE_COL].to_numpy(dtype=float)
    hits  = df["hit"].to_numpy(dtype=float)
    ir = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds="clip")
    ir.fit(probs, hits)
    cal = ir.predict(probs)
    b_before = float(np.mean((probs - hits) ** 2))
    b_after  = float(np.mean((cal - hits) ** 2))
    print(f"  {label}: Brier {b_before:.6f} -> {b_after:.6f}  ({b_after - b_before:+.6f})")
    print(f"    breakpoints: {len(ir.X_thresholds_)}")
    print(f"    x range: {ir.X_thresholds_.min():.3f} - {ir.X_thresholds_.max():.3f}")
    return ir.X_thresholds_.tolist(), ir.y_thresholds_.tolist(), b_before, b_after


print()
over_x, over_y, _, _   = fit_and_eval(over_df,  "OVER ")
under_x, under_y, _, _ = fit_and_eval(under_df, "UNDER")

# Protected stat|direction keys (UNDER routing)
under_stat_dirs = sorted(
    (under_df["stat"] + "|" + under_df["direction"].str.upper()).unique().tolist()
)

# Build JSON in the correct isotonic_hybrid schema
calibration = {
    "mode": "isotonic_hybrid",
    "candidate": "playoff_isotonic_direction_split",
    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "trained_on_col": SOURCE_COL,
    "note": "Trained on p_for_cal (MC signal, GBM disabled). Curves calibrate MC-based p_cal.",
    "playoff_dates": dates,
    "n_legs": {"total": len(combined), "over": len(over_df), "under": len(under_df)},
    "meta": {
        "family": "isotonic_hybrid",
        "mix": 1.0,
        "source_col": SOURCE_COL,
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

# Backup and save
ts = time.strftime("%Y%m%d_%H%M")
backup = OUTPUT_FILE.with_name(OUTPUT_FILE.stem + f"_backup_{ts}.json")
shutil.copy(OUTPUT_FILE, backup)
print(f"\nBackup: {backup.name}")

OUTPUT_FILE.write_text(json.dumps(calibration, indent=2))
print(f"Saved: {OUTPUT_FILE}")
print()
print(f"Isotonic trained on {SOURCE_COL} (not p_gbm).")
print("GBM is disabled -> p_cal = p_for_cal -> isotonic receives correct input distribution.")

# Validation: show what the curves would produce on existing corpus
print()
print("--- Validation: p_for_cal -> isotonic output ---")
for dir_, df_dir, x_pts, y_pts in [
    ("OVER", over_df, over_x, over_y),
    ("UNDER", under_df, under_x, under_y),
]:
    probs = df_dir[SOURCE_COL].to_numpy(dtype=float)
    hits  = df_dir["hit"].to_numpy(dtype=float)
    cal   = np.interp(probs, x_pts, y_pts)
    b_raw = float(np.mean((probs - hits) ** 2))
    b_cal = float(np.mean((cal - hits) ** 2))
    print(f"  {dir_}: raw Brier={b_raw:.6f}  calibrated={b_cal:.6f}  delta={b_cal - b_raw:+.6f}")
