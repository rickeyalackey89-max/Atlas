"""Audit live/replay probability-contract alignment.

Checks the failure modes that can silently pollute Atlas outputs:
- external priors must be attached before CatBoost, not only after builders prep
- CatBoost must build the trained feature contract without zero-defaulting
- published run artifacts must expose enough columns to verify the contract
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


def _bool_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    vals = pd.to_numeric(df[col], errors="coerce")
    if not isinstance(vals, pd.Series):
        vals = pd.Series(vals, index=df.index)
    return vals.fillna(0).astype(bool)


def _source_order_audit() -> dict[str, Any]:
    main_path = ROOT / "src" / "Atlas" / "engine" / "main.py"
    text = main_path.read_text(encoding="utf-8")
    pre_cat_idx = text.find("EXTERNAL PRIORS (pre-CAT)")
    cat_idx = text.find("apply_catboost_calibrator")
    prep_idx = text.find("run_prep_for_optimizer")
    return {
        "main_path": str(main_path.relative_to(ROOT)),
        "pre_cat_external_priors_found": pre_cat_idx >= 0,
        "pre_cat_external_priors_before_cat": pre_cat_idx >= 0 and cat_idx >= 0 and pre_cat_idx < cat_idx,
        "cat_before_optimizer_prep": cat_idx >= 0 and prep_idx >= 0 and cat_idx < prep_idx,
        "pre_cat_idx": pre_cat_idx,
        "cat_idx": cat_idx,
        "prep_idx": prep_idx,
    }


def _cat_feature_audit(scored: pd.DataFrame) -> dict[str, Any]:
    from Atlas.engine.catboost_calibrator import _build_feature_df_regressor

    meta_path = ROOT / "data" / "model" / "catboost_playoff" / "catboost_v5cD_full_corpus.meta.json"
    logs_path = ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    logs = pd.read_csv(logs_path, low_memory=False)
    X, diag = _build_feature_df_regressor(
        scored,
        logs,
        list(meta.get("features") or []),
        list(meta.get("cat_features") or []),
        ROOT / "data" / "model" / "ensemble",
    )
    nonzero = {}
    for col in X.columns:
        if col in set(meta.get("cat_features") or []):
            nonzero[col] = int(X[col].astype(str).nunique(dropna=False))
        else:
            vals = pd.to_numeric(X[col], errors="coerce").fillna(0.0)
            nonzero[col] = float((vals != 0.0).mean())
    return {
        "meta_path": str(meta_path.relative_to(ROOT)),
        "feature_source": diag.get("feature_source"),
        "feature_count": int(diag.get("feature_count", len(X.columns))),
        "defaulted_features": diag.get("defaulted_features", []),
        "feature_nonzero_or_unique": nonzero,
    }


def audit_run(run_dir: Path) -> dict[str, Any]:
    scored_path = run_dir / "scored_legs_deduped.csv"
    if not scored_path.exists():
        raise FileNotFoundError(f"Missing scored_legs_deduped.csv: {scored_path}")
    scored = pd.read_csv(scored_path, low_memory=False)

    source_order = _source_order_audit()
    cat_features = _cat_feature_audit(scored)
    prior_n = pd.to_numeric(scored.get("external_prior_n", pd.Series(0, index=scored.index)), errors="coerce").fillna(0)
    prior_applied = _bool_series(scored, "external_prior_probability_applied")

    artifact = {
        "run_dir": str(run_dir),
        "rows": int(len(scored)),
        "external_prior_rows": int((prior_n > 0).sum()),
        "external_prior_probability_applied_rows": int(prior_applied.sum()),
        "catboost_feature_source_values": sorted(scored.get("catboost_feature_source", pd.Series(dtype=str)).dropna().astype(str).unique().tolist()),
        "catboost_defaulted_features_values": sorted(scored.get("catboost_defaulted_features", pd.Series(dtype=str)).dropna().astype(str).unique().tolist()),
    }

    failures: list[str] = []
    if not source_order["pre_cat_external_priors_before_cat"]:
        failures.append("external priors are not attached before CatBoost in main.py")
    if cat_features["defaulted_features"]:
        failures.append("CatBoost runtime feature builder defaulted trained features")
    if artifact["external_prior_rows"] > 0 and artifact["external_prior_probability_applied_rows"] == 0:
        failures.append("run has external-prior rows but no probability-applied audit flag")
    if artifact["catboost_defaulted_features_values"] and artifact["catboost_defaulted_features_values"] != [""]:
        failures.append("published run reports CatBoost defaulted features")

    return {
        "verdict": "FAIL" if failures else "PASS",
        "failures": failures,
        "source_order": source_order,
        "artifact": artifact,
        "cat_features": cat_features,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Atlas probability pipeline contracts.")
    parser.add_argument("--run-dir", default=None, help="Run directory to inspect. Defaults to latest data/output/runs/*.")
    parser.add_argument("--json-out", default=None, help="Optional JSON output path.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else _latest_run_dir()
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir

    result = audit_run(run_dir)
    print(json.dumps(result, indent=2))
    if args.json_out:
        out = Path(args.json_out)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
