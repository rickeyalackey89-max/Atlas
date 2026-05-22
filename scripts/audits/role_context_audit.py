"""Run-level role/injury context audit for NBA scored legs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def _latest_run_dir() -> Path:
    runs = ROOT / "data" / "output" / "runs"
    candidates = [p for p in runs.iterdir() if p.is_dir()] if runs.exists() else []
    if not candidates:
        raise FileNotFoundError(f"No run directories found under {runs}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def _num(df: pd.DataFrame, col: str, default: float = np.nan) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    values = pd.to_numeric(df[col], errors="coerce")
    if not isinstance(values, pd.Series):
        values = pd.Series(values, index=df.index)
    return values.astype("float64")


def _describe(series: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    non_null = values.dropna()
    if non_null.empty:
        return {"status": "all_null", "rows": int(len(values)), "null_rows": int(values.isna().sum())}
    return {
        "status": "active" if non_null.nunique(dropna=True) > 1 else "constant",
        "rows": int(len(values)),
        "null_rows": int(values.isna().sum()),
        "unique_count": int(non_null.nunique(dropna=True)),
        "mean": float(non_null.mean()),
        "min": float(non_null.min()),
        "max": float(non_null.max()),
        "p50": float(non_null.quantile(0.50)),
        "p90": float(non_null.quantile(0.90)),
        "p99": float(non_null.quantile(0.99)),
    }


def _source_manifest(run_dir: Path) -> dict[str, Any]:
    path = ROOT / "data" / "output" / "runs_manifest" / run_dir.name / "injury_snapshot_manifest.json"
    if not path.exists():
        path = run_dir.parent.parent / "runs_manifest" / run_dir.name / "injury_snapshot_manifest.json"
    if not path.exists():
        return {"missing": True, "path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"path": str(path), "read_error": str(exc)}
    data["path"] = str(path)
    return data


def audit_run(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    scored = _read_csv(run_dir / "scored_legs_deduped.csv")
    if scored.empty:
        scored = _read_csv(run_dir / "scored_legs.csv")

    failures: list[str] = []
    warnings: list[str] = []

    if scored.empty:
        failures.append("empty_scored_frame")

    role_cols = [
        "role_ctx_mult",
        "role_ctx_rate_mult",
        "role_metrics_mult",
        "role_ctx_outs_used",
        "role_ctx_bump",
        "role_metrics_impact_mult",
        "zero_dnp_mult",
        "q_out_frac",
        "is_questionable",
    ]
    summaries = {col: _describe(_num(scored, col)) for col in role_cols}

    outs_used = _num(scored, "role_ctx_outs_used", 0.0).fillna(0.0)
    role_metrics_mult = _num(scored, "role_metrics_mult", 1.0).fillna(1.0)
    role_ctx_mult = _num(scored, "role_ctx_mult", 1.0).fillna(1.0)
    role_rate_mult = _num(scored, "role_ctx_rate_mult", 1.0).fillna(1.0)
    zero_dnp_mult = _num(scored, "zero_dnp_mult", 1.0).fillna(1.0)

    blind_role_metrics = ((outs_used <= 0) & ((role_metrics_mult - 1.0).abs() > 1e-6)).sum()
    blind_role_ctx = ((outs_used <= 0) & (((role_ctx_mult - 1.0).abs() > 1e-6) | ((role_rate_mult - 1.0).abs() > 1e-6))).sum()
    if int(blind_role_metrics):
        failures.append(f"role_metrics_moved_without_role_outs:{int(blind_role_metrics)}")
    if int(blind_role_ctx):
        warnings.append(f"role_ctx_moved_without_role_outs:{int(blind_role_ctx)}")

    if (zero_dnp_mult > 1.30).any() and (outs_used <= 0).all():
        failures.append("zero_dnp_active_without_share_matrix_outs")

    role_snapshot_share = 0.0
    if "role_metrics_snapshot_id" in scored.columns and len(scored):
        role_snapshot_share = float(scored["role_metrics_snapshot_id"].fillna("").astype(str).str.len().gt(0).mean())
    role_minutes_share = 0.0
    if "role_metrics_minutes_projection" in scored.columns and len(scored):
        role_minutes_share = float(pd.to_numeric(scored["role_metrics_minutes_projection"], errors="coerce").notna().mean())

    if len(scored) and role_snapshot_share < 0.90:
        warnings.append(f"role_metrics_snapshot_low_coverage:{role_snapshot_share:.3f}")
    if len(scored) and role_minutes_share < 0.90:
        warnings.append(f"role_metrics_minutes_low_coverage:{role_minutes_share:.3f}")

    payload = {
        "schema": "nba_role_context_audit_v1",
        "verdict": "FAIL" if failures else ("WARN" if warnings else "PASS"),
        "failures": failures,
        "warnings": warnings,
        "run_dir": str(run_dir),
        "rows": int(len(scored)),
        "coverage": {
            "role_metrics_snapshot_share": role_snapshot_share,
            "role_metrics_minutes_share": role_minutes_share,
            "role_ctx_outs_used_share_gt0": float((outs_used > 0).mean()) if len(outs_used) else 0.0,
            "zero_dnp_share_gt_130": float((zero_dnp_mult > 1.30).mean()) if len(zero_dnp_mult) else 0.0,
        },
        "columns": summaries,
        "injury_snapshot_manifest": _source_manifest(run_dir),
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit run-level role context behavior.")
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    run_dir = Path(args.run_dir) if args.run_dir else _latest_run_dir()
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    result = audit_run(run_dir)
    text = json.dumps(result, indent=2, sort_keys=True, default=str)
    print(text)
    if args.json_out:
        out = Path(args.json_out)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    return 0 if result["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
