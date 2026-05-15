#!/usr/bin/env python3
"""Audit eval_slips output against public slip quality fields."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "data" / "output" / "runs"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Run folders or eval_slips.csv files.")
    parser.add_argument("--json-out", help="Optional JSON report path.")
    args = parser.parse_args()

    frames: list[pd.DataFrame] = []
    for value in args.paths:
        path = _resolve_path(value)
        df = pd.read_csv(path)
        df["eval_slips_path"] = str(path)
        df["run_id"] = path.parent.name
        frames.append(df)

    if not frames:
        raise SystemExit("No eval_slips files found.")

    all_slips = pd.concat(frames, ignore_index=True)
    report = build_report(all_slips)
    print_report(report)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
        print(f"Wrote JSON: {out}")

    return 0


def build_report(df: pd.DataFrame) -> dict[str, Any]:
    graded = df[df["status"].isin(["win", "loss"])].copy() if "status" in df.columns else df.copy()
    return {
        "runs": sorted(df["run_id"].dropna().astype(str).unique().tolist()) if "run_id" in df.columns else [],
        "overall": _summary(graded),
        "by_family": _group_summary(graded, ["family"]),
        "by_family_label": _group_summary(graded, ["family", "slip_label"]),
        "by_quality_pass": _group_summary(graded, ["public_quality_pass"]) if "public_quality_pass" in graded.columns else [],
        "by_survival_bucket": _survival_bucket_summary(graded),
        "failed_quality_slips": _failed_quality_rows(df),
    }


def print_report(report: dict[str, Any]) -> None:
    overall = report["overall"]
    print("Eval Slip Quality Audit")
    print(f"runs={len(report.get('runs', []))} slips={overall['slips']} wins={overall['wins']} losses={overall['losses']} win_rate={_fmt(overall['win_rate'])}")

    print("\nBy family:")
    for row in report["by_family"]:
        print(f"  {row['family']}: slips={row['slips']} wins={row['wins']} losses={row['losses']} win_rate={_fmt(row['win_rate'])}")

    buckets = report.get("by_survival_bucket", [])
    if buckets:
        print("\nBy public_survival_score:")
        for row in buckets:
            print(f"  {row['bucket']}: slips={row['slips']} wins={row['wins']} losses={row['losses']} win_rate={_fmt(row['win_rate'])}")

    failed = report.get("failed_quality_slips", [])
    if failed:
        print("\nQuality failures present in eval file:")
        for row in failed[:20]:
            print(f"  {row['run_id']} {row['family']} {row['slip_label']} reason={row['public_quality_reasons']}")


def _resolve_path(value: str) -> Path:
    path = Path(value)
    if path.is_dir():
        path = path / "eval_slips.csv"
    elif not path.exists():
        path = RUNS_DIR / value / "eval_slips.csv"
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _summary(df: pd.DataFrame) -> dict[str, Any]:
    wins = int((df["status"] == "win").sum()) if "status" in df.columns else 0
    losses = int((df["status"] == "loss").sum()) if "status" in df.columns else 0
    graded = wins + losses
    return {
        "slips": int(len(df)),
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / graded) if graded else None,
    }


def _group_summary(df: pd.DataFrame, cols: list[str]) -> list[dict[str, Any]]:
    if df.empty or any(col not in df.columns for col in cols):
        return []
    rows: list[dict[str, Any]] = []
    for keys, group in df.groupby(cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {col: str(value) for col, value in zip(cols, keys)}
        row.update(_summary(group))
        rows.append(row)
    return rows


def _survival_bucket_summary(df: pd.DataFrame) -> list[dict[str, Any]]:
    if "public_survival_score" not in df.columns:
        return []
    out = df.copy()
    score = pd.to_numeric(out["public_survival_score"], errors="coerce")
    out = out[score.notna()].copy()
    if out.empty:
        return []
    out["bucket"] = pd.cut(
        pd.to_numeric(out["public_survival_score"], errors="coerce"),
        bins=[0.0, 0.50, 0.55, 0.60, 0.65, 0.70, 1.0],
        include_lowest=True,
    ).astype(str)
    return _group_summary(out, ["bucket"])


def _failed_quality_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    if "public_quality_pass" not in df.columns:
        return []
    vals = df["public_quality_pass"].astype(str).str.lower()
    failed = df[vals.isin(["false", "0", "no"])]
    cols = [
        "run_id",
        "family",
        "slip_label",
        "status",
        "public_survival_score",
        "public_quality_reasons",
        "legs",
    ]
    return failed[[col for col in cols if col in failed.columns]].to_dict("records")


def _fmt(value: Any) -> str:
    if value is None:
        return "NA"
    try:
        return f"{float(value):.3f}"
    except Exception:
        return "NA"


if __name__ == "__main__":
    raise SystemExit(main())
