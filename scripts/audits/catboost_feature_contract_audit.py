"""CatBoost runtime feature contract audit.

This audit is intentionally strict. If the promoted CAT model has a trained
feature that the live/replay scored surface cannot rebuild without defaulting,
that run is not safe to use for replay corpus, LODO, or promotion decisions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

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


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _series_nonzero_or_unique(frame: pd.DataFrame, cat_features: set[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in frame.columns:
        if col in cat_features:
            vals = frame[col].fillna("").astype(str)
            out[col] = {
                "kind": "categorical",
                "unique_count": int(vals.nunique(dropna=False)),
                "top_values": {str(k): int(v) for k, v in vals.value_counts(dropna=False).head(8).to_dict().items()},
            }
        else:
            vals = pd.to_numeric(frame[col], errors="coerce")
            non_null = vals.dropna()
            filled = vals.fillna(0.0)
            out[col] = {
                "kind": "numeric",
                "null_rows": int(vals.isna().sum()),
                "unique_count": int(non_null.nunique(dropna=True)),
                "nonzero_rate": float((filled.abs() > 1e-12).mean()) if len(filled) else 0.0,
                "mean": float(non_null.mean()) if not non_null.empty else None,
                "min": float(non_null.min()) if not non_null.empty else None,
                "max": float(non_null.max()) if not non_null.empty else None,
            }
    return out


def audit_run(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    scored = _read_csv(run_dir / "scored_legs_deduped.csv")
    if scored.empty:
        scored = _read_csv(run_dir / "scored_legs.csv")

    failures: list[str] = []
    warnings: list[str] = []

    if scored.empty:
        failures.append("missing_or_empty_scored_surface")

    meta_path = ROOT / "data" / "model" / "catboost_playoff" / "catboost_v5cD_full_corpus.meta.json"
    logs_path = ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"
    ensemble_dir = ROOT / "data" / "model" / "ensemble"
    meta = _read_json(meta_path)
    features = list(meta.get("features") or [])
    cat_features = set(meta.get("cat_features") or [])

    if not meta:
        failures.append(f"missing_catboost_meta:{meta_path}")
    if not features:
        failures.append("catboost_meta_has_no_features")
    if not logs_path.exists():
        failures.append(f"missing_gamelogs:{logs_path}")

    diagnostics: dict[str, Any] = {}
    feature_summary: dict[str, Any] = {}
    built_columns: list[str] = []

    if not failures:
        try:
            from Atlas.engine.catboost_calibrator import _build_feature_df_regressor

            logs = pd.read_csv(logs_path, low_memory=False)
            feature_frame, diagnostics = _build_feature_df_regressor(
                scored.copy(),
                logs,
                features=features,
                cat_features=list(cat_features),
                ensemble_dir=ensemble_dir,
            )
            built_columns = list(feature_frame.columns)
            feature_summary = _series_nonzero_or_unique(feature_frame, cat_features)
        except Exception as exc:
            failures.append(f"catboost_feature_builder_error:{type(exc).__name__}:{exc}")

    defaulted = list(diagnostics.get("defaulted_features") or [])
    if defaulted:
        failures.append("catboost_defaulted_features:" + ",".join(defaulted))

    reported_defaulted: list[str] = []
    if "catboost_defaulted_features" in scored.columns:
        reported_defaulted = sorted(
            x for x in set(scored["catboost_defaulted_features"].fillna("").astype(str).tolist()) if x
        )
        if reported_defaulted:
            failures.append("published_catboost_defaulted_features:" + ",".join(reported_defaulted))
    else:
        warnings.append("missing_published_catboost_defaulted_features_column")

    reported_count_values: list[int] = []
    if "catboost_feature_count" in scored.columns:
        counts = pd.to_numeric(scored["catboost_feature_count"], errors="coerce").dropna()
        reported_count_values = sorted(set(counts.astype(int).tolist()))
        if len(reported_count_values) != 1:
            failures.append(f"published_catboost_feature_count_not_constant:{reported_count_values}")
        elif features and reported_count_values[0] != len(features):
            failures.append(f"published_catboost_feature_count_mismatch:{reported_count_values[0]}!={len(features)}")
    else:
        warnings.append("missing_published_catboost_feature_count_column")

    if built_columns and built_columns != features:
        failures.append("catboost_built_feature_order_mismatch")

    payload = {
        "schema": "nba_catboost_feature_contract_v1",
        "verdict": "FAIL" if failures else ("WARN" if warnings else "PASS"),
        "failures": failures,
        "warnings": warnings,
        "run_dir": str(run_dir),
        "rows": int(len(scored)),
        "meta": {
            "path": str(meta_path),
            "version": meta.get("version"),
            "model_kind": meta.get("model_kind"),
            "feature_count": len(features),
            "cat_features": sorted(cat_features),
        },
        "runtime": {
            "diagnostics": diagnostics,
            "built_feature_count": len(built_columns),
            "reported_feature_count_values": reported_count_values,
            "reported_defaulted_features": reported_defaulted,
        },
        "features": feature_summary,
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit CatBoost runtime feature contract.")
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
