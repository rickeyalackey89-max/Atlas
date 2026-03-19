#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def clamp01(x: np.ndarray) -> np.ndarray:
    return np.clip(x, 0.0, 1.0)


def to_numeric(series: pd.Series) -> np.ndarray:
    return pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)


def load_map(map_path: Path) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    obj = json.loads(map_path.read_text(encoding="utf-8"))
    grid_in = np.asarray(obj["grid_p_in"], dtype=float)
    grid_out = np.asarray(obj["grid_p_out"], dtype=float)

    if grid_in.ndim != 1 or grid_out.ndim != 1 or len(grid_in) != len(grid_out):
        raise ValueError("Invalid calibration map grid arrays.")
    if len(grid_in) < 2:
        raise ValueError("Calibration grid too small.")
    if not np.all(np.diff(grid_in) >= 0):
        raise ValueError("grid_p_in must be non-decreasing.")

    return grid_in, grid_out, obj


def apply_interp(p: np.ndarray, grid_in: np.ndarray, grid_out: np.ndarray) -> np.ndarray:
    p = clamp01(p.astype(float))
    # np.interp does piecewise-linear interpolation; same behavior we used in fitting/reporting
    return np.interp(p, grid_in, grid_out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply isotonic grid calibration map to a CSV.")
    ap.add_argument("--map", required=True, help="Path to calibration_map.json")
    ap.add_argument("--in", dest="inp", required=True, help="Input CSV path")
    ap.add_argument("--out", required=True, help="Output CSV path")

    ap.add_argument("--prob-col", default="p_adj_role", help="Probability column to calibrate")
    ap.add_argument("--out-col", default="p_cal_role", help="New calibrated probability column name")
    ap.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting --out-col if it already exists (default: refuse).",
    )

    ap.add_argument(
        "--also-calibrate-base",
        action="store_true",
        help="Also calibrate p_adj_base -> p_cal_base if p_adj_base exists in CSV.",
    )
    ap.add_argument("--base-prob-col", default="p_adj_base", help="Base probability column name")
    ap.add_argument("--base-out-col", default="p_cal_base", help="Base calibrated output column name")

    args = ap.parse_args()

    map_path = Path(args.map)
    in_path = Path(args.inp)
    out_path = Path(args.out)

    if not map_path.exists():
        raise SystemExit(f"Map not found: {map_path}")
    if not in_path.exists():
        raise SystemExit(f"Input CSV not found: {in_path}")

    grid_in, grid_out, meta = load_map(map_path)

    df = pd.read_csv(in_path, low_memory=False)

    if args.prob_col not in df.columns:
        raise SystemExit(f"Missing prob column '{args.prob_col}' in input CSV.")

    if (args.out_col in df.columns) and (not args.overwrite):
        raise SystemExit(
            f"Refusing to overwrite existing column '{args.out_col}'. "
            f"Pick a new --out-col or pass --overwrite."
        )

    p = to_numeric(df[args.prob_col])
    p_cal = np.full_like(p, np.nan, dtype=float)
    ok = np.isfinite(p)
    p_cal[ok] = apply_interp(p[ok], grid_in, grid_out)

    df[args.out_col] = p_cal

    # Optional: also calibrate base
    if args.also_calibrate_base and (args.base_prob_col in df.columns):
        if (args.base_out_col in df.columns) and (not args.overwrite):
            raise SystemExit(
                f"Refusing to overwrite existing column '{args.base_out_col}'. "
                f"Pick a new --base-out-col or pass --overwrite."
            )

        pb = to_numeric(df[args.base_prob_col])
        pb_cal = np.full_like(pb, np.nan, dtype=float)
        okb = np.isfinite(pb)
        pb_cal[okb] = apply_interp(pb[okb], grid_in, grid_out)
        df[args.base_out_col] = pb_cal

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)

    # Minimal, useful summary
    n = int(ok.sum())
    print("Applied calibration map:")
    print(f"  map: {map_path}")
    print(f"  in : {in_path}")
    print(f"  out: {out_path}")
    print(f"  calibrated: {n} rows from '{args.prob_col}' -> '{args.out_col}'")
    print(f"  method: {meta.get('method')}, source_prob_col: {meta.get('source_prob_col')}")


if __name__ == "__main__":
    main()