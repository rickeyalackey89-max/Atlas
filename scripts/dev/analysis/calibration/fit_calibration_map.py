#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from sklearn.isotonic import IsotonicRegression
except Exception as e:  # pragma: no cover
    raise SystemExit(
        "Missing dependency: scikit-learn. Install with:\n"
        "  pip install scikit-learn\n"
        f"Original error: {e}"
    )


# -----------------------------
# Utilities
# -----------------------------
def to_float(x: Any) -> float:
    try:
        if x is None:
            return float("nan")
        s = str(x).strip()
        if s == "" or s.lower() in {"na", "nan", "none", "null"}:
            return float("nan")
        return float(s)
    except Exception:
        return float("nan")


def to_hit01(x: Any) -> float:
    if x is None:
        return float("nan")
    s = str(x).strip().lower()
    if s in {"1", "true", "t", "yes", "y", "hit"}:
        return 1.0
    if s in {"0", "false", "f", "no", "n", "miss"}:
        return 0.0
    # sometimes it may already be numeric-like
    try:
        v = float(s)
        if v in (0.0, 1.0):
            return v
    except Exception:
        pass
    return float("nan")


def is_push(x: Any) -> bool:
    if x is None:
        return False
    s = str(x).strip().lower()
    return s in {"1", "true", "t", "yes", "y"}


def clamp01(a: np.ndarray) -> np.ndarray:
    return np.clip(a, 1e-9, 1.0 - 1e-9)


def brier(y: np.ndarray, p: np.ndarray) -> float:
    p = clamp01(p.astype(float))
    y = y.astype(float)
    return float(np.mean((p - y) ** 2))


def ece_10(y: np.ndarray, p: np.ndarray) -> float:
    """Expected calibration error using 10 fixed bins."""
    p = np.clip(p.astype(float), 0.0, 1.0)
    y = y.astype(float)
    bins = np.minimum(9, np.floor(p * 10).astype(int))
    ece = 0.0
    n = len(p)
    for b in range(10):
        mask = bins == b
        if not mask.any():
            continue
        pb = float(np.mean(p[mask]))
        yb = float(np.mean(y[mask]))
        ece += (mask.sum() / n) * abs(yb - pb)
    return float(ece)


# -----------------------------
# Output schema
# -----------------------------
@dataclass
class CalibrationMap:
    method: str
    source_prob_col: str
    target_col: str
    n: int
    grid_p_in: list[float]
    grid_p_out: list[float]
    clip_min: float = 1e-9
    clip_max: float = 1.0 - 1e-9

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "source_prob_col": self.source_prob_col,
            "target_col": self.target_col,
            "n": self.n,
            "clip_min": self.clip_min,
            "clip_max": self.clip_max,
            "grid_p_in": self.grid_p_in,
            "grid_p_out": self.grid_p_out,
        }


def apply_grid_map(p: np.ndarray, grid_in: np.ndarray, grid_out: np.ndarray) -> np.ndarray:
    """Piecewise-linear interpolation on a dense grid (stable + portable)."""
    p = np.clip(p.astype(float), 0.0, 1.0)
    return np.interp(p, grid_in, grid_out)


# -----------------------------
# Main
# -----------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Backtest CSV path (from backtest_role_layer_ctx.py)")
    ap.add_argument("--prob-col", default="p_adj_role", help="Probability column to calibrate")
    ap.add_argument("--hit-col", default="hit", help="Outcome/hit column (0/1 or bool-like)")
    ap.add_argument("--push-col", default="push", help="Push indicator column")
    ap.add_argument("--out", required=True, help="Output calibration_map.json path")
    ap.add_argument("--report-out", default=None, help="Optional calibration_report.json path")

    ap.add_argument("--grid-size", type=int, default=2001, help="Calibration grid resolution (>= 1001 recommended)")
    ap.add_argument("--min-samples", type=int, default=2000, help="Minimum samples required to fit")
    ap.add_argument("--seed", type=int, default=1337)

    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)

    for c in [args.prob_col, args.hit_col]:
        if c not in df.columns:
            raise SystemExit(f"Missing required column '{c}' in CSV.")

    # filter pushes + parse
    push_mask = np.zeros(len(df), dtype=bool)
    if args.push_col in df.columns:
        push_mask = df[args.push_col].map(is_push).to_numpy(dtype=bool)

    p = df[args.prob_col].map(to_float).to_numpy(dtype=float)
    y = df[args.hit_col].map(to_hit01).to_numpy(dtype=float)

    ok = (~push_mask) & np.isfinite(p) & np.isfinite(y)
    p = p[ok]
    y = y[ok].astype(float)

    n = len(p)
    if n < args.min_samples:
        raise SystemExit(f"Not enough samples to calibrate: n={n} < min_samples={args.min_samples}")

    # Fit isotonic (monotonic mapping)
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip")

    # Optional: tiny jitter to break exact ties (helps with heavy quantization)
    p_fit = np.clip(p + rng.normal(0.0, 1e-12, size=n), 0.0, 1.0)
    iso.fit(p_fit, y)

    # Dense grid for portable JSON
    grid_n = max(1001, int(args.grid_size))
    grid_in = np.linspace(0.0, 1.0, grid_n)
    grid_out = np.clip(iso.predict(grid_in), 0.0, 1.0)

    # Report metrics
    p_cal = apply_grid_map(p, grid_in, grid_out)

    report = {
        "n": int(n),
        "prob_col": args.prob_col,
        "hit_col": args.hit_col,
        "push_col": args.push_col if args.push_col in df.columns else None,
        "brier_before": brier(y, p),
        "brier_after": brier(y, p_cal),
        "ece10_before": ece_10(y, p),
        "ece10_after": ece_10(y, p_cal),
        "avg_p_before": float(np.mean(p)),
        "avg_p_after": float(np.mean(p_cal)),
        "hit_rate": float(np.mean(y)),
    }

    out_map = CalibrationMap(
        method="isotonic_grid_v1",
        source_prob_col=args.prob_col,
        target_col=args.hit_col,
        n=int(n),
        grid_p_in=[float(x) for x in grid_in.tolist()],
        grid_p_out=[float(x) for x in grid_out.tolist()],
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_map.to_dict(), indent=2), encoding="utf-8")

    if args.report_out:
        rep_path = Path(args.report_out)
        rep_path.parent.mkdir(parents=True, exist_ok=True)
        rep_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("Wrote:", str(out_path))
    if args.report_out:
        print("Wrote:", str(Path(args.report_out)))
    print("Report:", json.dumps(report, indent=2))


if __name__ == "__main__":
    main()