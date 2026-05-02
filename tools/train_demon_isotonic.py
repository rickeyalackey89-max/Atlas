#!/usr/bin/env python
"""
DEMON Isotonic Calibrator Trainer
==================================
Trains a dedicated isotonic regression curve for DEMON-tier legs only,
using the v17 resim cache (44 dates, ~74K DEMON legs).

Why: The current demon_fix applies a flat 0.9 penalty — but the actual
miscalibration is non-linear: the gap grows dramatically at higher p_adj
(model 56% vs actual 29% in the 0.55-0.65 bucket). A shaped isotonic
curve corrects this at every probability level.

Output: data/model/telemetry_calibration.demon_isotonic.json
  - mode: isotonic_hybrid
  - Main curve: global isotonic (from existing demon_fix — used for GOBLIN + STANDARD)
  - protected_calibration: DEMON-specific isotonic curve
  - protected_tier: DEMON (new field — only applies to DEMON legs)

Usage:
  python tools/train_demon_isotonic.py
  python tools/train_demon_isotonic.py --promote   # writes to active config path
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CACHE_PATH = ROOT / "data" / "model" / "_v17_resim_cache.pkl"
BASE_JSON_PATH = ROOT / "data" / "model" / "telemetry_calibration.demon_fix.json"
OUTPUT_PATH = ROOT / "data" / "model" / "telemetry_calibration.demon_isotonic.json"
CONFIG_PATH = ROOT / "config.yaml"


def load_demon_rows() -> pd.DataFrame:
    print(f"Loading cache: {CACHE_PATH}")
    cache = pickle.load(open(CACHE_PATH, "rb"))
    df = cache["cv"]
    print(f"Loaded {len(cache['dates'])} dates, {len(df):,} total legs")

    demon = df[df["tier"] == "DEMON"].copy()
    demon = demon[demon["hit"].notna() & demon["p_adj"].notna()].copy()
    demon["p_adj"] = pd.to_numeric(demon["p_adj"], errors="coerce").clip(0.01, 0.99)
    demon["hit"] = pd.to_numeric(demon["hit"], errors="coerce")
    demon = demon.dropna(subset=["p_adj", "hit"])

    print(f"\nDEMON legs: {len(demon):,}")
    print(f"  Hit rate:  {demon['hit'].mean():.3f}")
    print(f"  p_adj mean: {demon['p_adj'].mean():.3f}")
    return demon


def fit_isotonic(x: np.ndarray, y: np.ndarray) -> tuple[list[float], list[float]]:
    """Fit isotonic regression and return (x_thresholds, y_thresholds) for JSON."""
    iso = IsotonicRegression(increasing=True, out_of_bounds="clip")
    iso.fit(x, y)

    # Use the fitted thresholds directly (step function breakpoints)
    x_th = iso.X_thresholds_.tolist()
    y_th = iso.y_thresholds_.tolist()

    # Clamp y values to reasonable range
    y_th = [max(0.01, min(0.99, v)) for v in y_th]

    return x_th, y_th


def calibration_gap_report(demon: pd.DataFrame, x_th: list, y_th: list) -> None:
    """Print before/after calibration gap by bucket."""
    from numpy import interp
    x_arr = np.array(x_th)
    y_arr = np.array(y_th)

    demon = demon.copy()
    demon["p_demon_cal"] = np.interp(demon["p_adj"].values, x_arr, y_arr)

    buckets = [0, 0.25, 0.35, 0.45, 0.55, 0.65, 1.0]
    demon["bucket"] = pd.cut(demon["p_adj"], bins=buckets)

    print("\nCalibration gap report (DEMON-only):")
    print(f"{'Bucket':<16} {'N':>6}  {'Actual':>8}  {'Before(p_adj)':>14}  {'After(demon_cal)':>16}  {'Gap Before':>10}  {'Gap After':>10}")
    print("-" * 100)
    for grp, sub in demon.groupby("bucket", observed=True):
        if len(sub) < 5:
            continue
        actual = sub["hit"].mean()
        before = sub["p_adj"].mean()
        after = sub["p_demon_cal"].mean()
        print(f"{str(grp):<16} {len(sub):>6}  {actual:>8.3f}  {before:>14.3f}  {after:>16.3f}  {actual-before:>+10.3f}  {actual-after:>+10.3f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--promote", action="store_true", help="Update config.yaml to use the new calibration")
    args = parser.parse_args()

    demon = load_demon_rows()

    print("\n--- Fitting DEMON isotonic curve ---")
    x = demon["p_adj"].values
    y = demon["hit"].values
    x_th, y_th = fit_isotonic(x, y)
    print(f"Curve points: {len(x_th)}")
    print(f"Input range:  [{min(x_th):.3f}, {max(x_th):.3f}]")
    print(f"Output range: [{min(y_th):.3f}, {max(y_th):.3f}]")

    calibration_gap_report(demon, x_th, y_th)

    # Load existing demon_fix to extract the global isotonic curve (used for GOBLIN/STANDARD)
    print(f"\n--- Loading global isotonic from {BASE_JSON_PATH.name} ---")
    base = json.load(open(BASE_JSON_PATH))
    meta = base.get("meta", {})
    global_x = meta.get("x_thresholds", [])
    global_y = meta.get("y_thresholds", [])
    global_mix = meta.get("mix", 1.0)
    global_src = meta.get("source_col", "p_adj")
    print(f"Global curve points: {len(global_x)}")

    # Build the new JSON
    out = {
        "mode": "isotonic_hybrid",
        "candidate": "demon_isotonic",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "meta": {
            # Global isotonic — applied to GOBLIN + STANDARD legs
            "source_col": global_src,
            "mix": global_mix,
            "x_thresholds": global_x,
            "y_thresholds": global_y,
            # DEMON-specific isotonic applied via protected_calibration
            "protected_tier": "DEMON",
            "protected_calibration": {
                "mode": "isotonic_blend",
                "mix": 1.0,
                "source_col": "p_adj",
                "x_thresholds": x_th,
                "y_thresholds": y_th,
            },
        },
        # Keep pre_calibration from demon_fix for any global penalties still needed
        "pre_calibration": base.get("pre_calibration", {}),
    }

    OUTPUT_PATH.write_text(json.dumps(out, indent=2))
    print(f"\n✓ Wrote: {OUTPUT_PATH}")

    if args.promote:
        import yaml
        cfg = yaml.safe_load(CONFIG_PATH.read_text())
        tel = cfg.get("telemetry", {})
        old_candidate = tel.get("active_calibration", "?")
        tel["active_calibration"] = "demon_isotonic"
        tel["active_calibration_path"] = str(OUTPUT_PATH.relative_to(ROOT)).replace("\\", "/")
        cfg["telemetry"] = tel
        CONFIG_PATH.write_text(yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False))
        print(f"✓ Promoted in config.yaml: {old_candidate} -> demon_isotonic")
    else:
        print("\nTo activate, run with --promote or manually set in config.yaml:")
        print(f"  active_calibration: demon_isotonic")
        print(f"  active_calibration_path: data/model/telemetry_calibration.demon_isotonic.json")


if __name__ == "__main__":
    main()
