"""Strict replay fidelity audit.

This audit is intentionally narrower and harder than the normal live surface
audit. A replay that feeds model training must prove it used a single historical
slate plus pinned context artifacts instead of whatever live files happen to be
in data/input today.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_UNMARKETED_EXACT_STATS = {"FTA"}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def _num(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    values = pd.to_numeric(df[col], errors="coerce")
    if not isinstance(values, pd.Series):
        values = pd.Series(values, index=df.index)
    return values.fillna(default).astype(float)


def _bool(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    values = df[col]
    if values.dtype == bool:
        return values.fillna(False).astype(bool)
    text = values.astype(str).str.strip().str.lower()
    return text.isin({"1", "true", "yes", "y"})


def _find_run_dir(path: Path) -> Path:
    path = path.resolve()
    if (path / "scored_legs_deduped.csv").is_file():
        return path
    found = sorted(path.rglob("scored_legs_deduped.csv"))
    if not found:
        raise FileNotFoundError(f"No scored_legs_deduped.csv found under {path}")
    return found[-1].parent.resolve()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _run_manifest_dir(run_dir: Path) -> Path | None:
    # Replay outputs are usually <scenario>/<stamp>/runs/<run_id>.
    replay_root = run_dir.parent.parent
    candidate = replay_root / "runs_manifest" / run_dir.name
    if candidate.is_dir():
        return candidate
    candidates = sorted(run_dir.parents[0].rglob("runs_manifest")) if run_dir.parents else []
    for root in candidates:
        child = root / run_dir.name
        if child.is_dir():
            return child
    return None


def _single_date_summary(scored: pd.DataFrame) -> dict[str, Any]:
    values = []
    if "game_date" in scored.columns:
        values = sorted(scored["game_date"].dropna().astype(str).str[:10].unique().tolist())
    return {
        "dates": values,
        "single_date": len(values) == 1,
        "date": values[0] if len(values) == 1 else None,
    }


def _coverage(scored: pd.DataFrame) -> dict[str, Any]:
    rows = int(len(scored))
    prior_n = _num(scored, "external_prior_n", 0.0)
    exact_market = _bool(scored, "external_prior_exact_market")
    stat = (
        scored["stat"].fillna("").astype(str).str.strip().str.upper()
        if "stat" in scored.columns
        else pd.Series("", index=scored.index)
    )
    expected_unmarketed = stat.isin(EXPECTED_UNMARKETED_EXACT_STATS)
    market_eligible = ~expected_unmarketed
    market_eligible_rows = int(market_eligible.sum()) if rows else 0
    role_snapshot = (
        scored.get("role_metrics_snapshot_id", pd.Series("", index=scored.index))
        .fillna("")
        .astype(str)
        .str.len()
        .gt(0)
        if rows
        else pd.Series(dtype=bool)
    )
    role_minutes = pd.to_numeric(
        scored.get("role_metrics_minutes_projection", pd.Series(dtype=float)),
        errors="coerce",
    )
    spread_ok = _bool(scored, "spread_ok")
    game_total = pd.to_numeric(scored.get("game_total_norm", pd.Series(dtype=float)), errors="coerce")
    probability_cols = ["p", "p_role", "p_adj", "p_for_cal", "p_cal"]

    return {
        "rows": rows,
        "external_prior_share": float((prior_n > 0).mean()) if rows else 0.0,
        "exact_market_share": float(exact_market.mean()) if rows else 0.0,
        "market_eligible_rows": market_eligible_rows,
        "expected_unmarketed_exact_rows": int(expected_unmarketed.sum()) if rows else 0,
        "expected_unmarketed_exact_stats": {
            str(k): int(v)
            for k, v in stat[expected_unmarketed].value_counts(dropna=False).to_dict().items()
        } if rows else {},
        "external_prior_share_market_eligible": float((prior_n[market_eligible] > 0).mean()) if market_eligible_rows else 0.0,
        "exact_market_share_market_eligible": float(exact_market[market_eligible].mean()) if market_eligible_rows else 0.0,
        "role_metrics_snapshot_share": float(role_snapshot.mean()) if rows else 0.0,
        "role_metrics_minutes_share": float(role_minutes.notna().mean()) if rows else 0.0,
        "spread_ok_share": float(spread_ok.mean()) if rows else 0.0,
        "game_total_norm_nonzero_share": float(game_total.fillna(0.0).ne(0.0).mean()) if rows else 0.0,
        "probability_columns_present": [col for col in probability_cols if col in scored.columns],
        "probability_columns_missing": [col for col in probability_cols if col not in scored.columns],
        "projected_minutes_columns_present": [
            col
            for col in [
                "projected_minutes_model",
                "projected_minutes_source",
                "sim_minutes_close",
                "sim_minutes_blowout",
                "atlas_projection_mean",
                "atlas_projection_delta",
                "atlas_projection_side_delta",
                "atlas_projection_line_ratio",
            ]
            if col in scored.columns
        ],
    }


def _source_manifest_summary(run_dir: Path) -> dict[str, Any]:
    manifest_dir = _run_manifest_dir(run_dir)
    out: dict[str, Any] = {
        "manifest_dir": str(manifest_dir) if manifest_dir else None,
        "manifest_dir_exists": bool(manifest_dir and manifest_dir.is_dir()),
        "files": [],
        "injury_snapshot_manifest": {},
        "source_context_manifest": {},
    }
    if not manifest_dir:
        return out
    files = sorted(p.name for p in manifest_dir.iterdir() if p.is_file())
    out["files"] = files
    out["injury_snapshot_manifest"] = _load_json(manifest_dir / "injury_snapshot_manifest.json")
    out["source_context_manifest"] = _load_json(manifest_dir / "source_context_manifest.json")
    return out


def _source_context_failures(source_manifest: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    ctx = source_manifest.get("source_context_manifest") or {}
    artifacts = ctx.get("artifacts") or {}
    if not ctx:
        return ["missing_source_context_manifest"]

    for required in ["prizepicks_raw", "rotowire_lines", "external_priors"]:
        if required not in artifacts:
            failures.append(f"source_context_missing_artifact={required}")

    strict_replay = bool(ctx.get("strict_replay", False))
    if strict_replay:
        live_input_root = (ROOT / "data" / "input").resolve()
        for label in [
            "rotowire_lines",
            "prizepicks_raw",
            "external_priors",
            "odds_market",
            "bettingpros_props",
            "draftkings_props",
            "github_prop_odds",
        ]:
            item = artifacts.get(label) or {}
            source_raw = str(item.get("source") or "").strip()
            if not source_raw:
                continue
            try:
                source_path = Path(source_raw).resolve()
                source_path.relative_to(live_input_root)
            except Exception:
                continue
            failures.append(f"strict_replay_used_live_data_input_source={label}:{source_path}")

    return failures


def audit_run(run_dir: Path, *, expected_date: str | None = None) -> dict[str, Any]:
    run_dir = _find_run_dir(run_dir)
    scored_path = run_dir / "scored_legs_deduped.csv"
    eval_path = run_dir / "eval_legs.csv"
    scored = _read_csv(scored_path)
    eval_df = _read_csv(eval_path)

    failures: list[str] = []
    warnings: list[str] = []

    if scored.empty:
        failures.append("missing_or_empty_scored_legs_deduped")
    if eval_df.empty:
        failures.append("missing_or_empty_eval_legs")

    date_summary = _single_date_summary(scored)
    if not date_summary["single_date"]:
        failures.append(f"replay_must_have_one_game_date_found={date_summary['dates']}")
    if expected_date and date_summary.get("date") != expected_date:
        failures.append(f"expected_date_mismatch expected={expected_date} found={date_summary.get('date')}")

    cov = _coverage(scored)
    if cov["probability_columns_missing"]:
        failures.append(f"missing_probability_columns={cov['probability_columns_missing']}")
    if cov["spread_ok_share"] < 0.99:
        failures.append(f"spread_context_incomplete share={cov['spread_ok_share']:.3f}")
    if cov["game_total_norm_nonzero_share"] < 0.99:
        failures.append(f"game_total_context_dead share={cov['game_total_norm_nonzero_share']:.3f}")
    if cov["role_metrics_snapshot_share"] < 0.90:
        failures.append(f"role_metrics_snapshot_incomplete share={cov['role_metrics_snapshot_share']:.3f}")
    if cov["role_metrics_minutes_share"] < 0.90:
        failures.append(f"role_metrics_minutes_incomplete share={cov['role_metrics_minutes_share']:.3f}")
    if cov["external_prior_share"] < 0.15:
        failures.append(f"market_prior_coverage_too_low share={cov['external_prior_share']:.3f}")

    source_manifest = _source_manifest_summary(run_dir)
    if not source_manifest["manifest_dir_exists"]:
        failures.append("missing_run_scoped_manifest_dir")
    manifest_files = set(source_manifest.get("files") or [])
    required_any = {
        "injury_snapshot_manifest.json",
        "source_context_manifest.json",
        "injury_invalidations_latest.json",
        "status_latest.json",
        "rotowire_lines.json",
    }
    missing_manifest_files = sorted(required_any - manifest_files)
    if missing_manifest_files:
        failures.append(f"missing_run_scoped_source_files={missing_manifest_files}")
    source_artifacts = (source_manifest.get("source_context_manifest") or {}).get("artifacts") or {}
    external_priors_artifact = source_artifacts.get("external_priors") or {}
    external_priors_destination = Path(str(external_priors_artifact.get("destination") or ""))
    if not external_priors_artifact or not external_priors_destination.name or external_priors_destination.name not in manifest_files:
        failures.append("missing_run_scoped_external_priors_artifact")
    if "role_metrics_latest.json" not in manifest_files:
        failures.append("missing_run_scoped_role_metrics_latest_json")
    failures.extend(_source_context_failures(source_manifest))

    pipeline_audit = _load_json(run_dir / "pipeline_contract_audit.json")
    if pipeline_audit and pipeline_audit.get("verdict") != "PASS":
        failures.append(f"pipeline_contract_audit_not_pass={pipeline_audit.get('verdict')}")
    hard_audit = _load_json(run_dir / "hard_pipeline_audit.json")
    if hard_audit and hard_audit.get("verdict") == "FAIL":
        failures.append("hard_pipeline_audit_failed")
    probability_audit = _load_json(run_dir / "probability_surface_audit.json")
    if probability_audit and probability_audit.get("verdict") == "FAIL":
        failures.append("probability_surface_audit_failed")
    role_audit = _load_json(run_dir / "role_context_audit.json")
    if role_audit and role_audit.get("verdict") == "FAIL":
        failures.append("role_context_audit_failed")
    cat_contract = _load_json(run_dir / "catboost_feature_contract.json")
    if cat_contract and cat_contract.get("verdict") == "FAIL":
        failures.append("catboost_feature_contract_failed")
    if cat_contract and (cat_contract.get("runtime", {}) or {}).get("reported_defaulted_features"):
        failures.append("catboost_reported_defaulted_features")

    result = {
        "verdict": "FAIL" if failures else ("WARN" if warnings else "PASS"),
        "failures": failures,
        "warnings": warnings,
        "run_dir": str(run_dir),
        "expected_date": expected_date,
        "date_summary": date_summary,
        "coverage": cov,
        "source_manifest": source_manifest,
        "pipeline_contract_verdict": pipeline_audit.get("verdict") if pipeline_audit else None,
        "hard_pipeline_verdict": hard_audit.get("verdict") if hard_audit else None,
        "probability_surface_verdict": probability_audit.get("verdict") if probability_audit else None,
        "role_context_verdict": role_audit.get("verdict") if role_audit else None,
        "catboost_feature_contract_verdict": cat_contract.get("verdict") if cat_contract else None,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Hard-stop audit for strict replay fidelity.")
    parser.add_argument("--run-dir", required=True, help="Replay run directory or scenario root.")
    parser.add_argument("--expected-date", default=None, help="Expected game date, YYYY-MM-DD.")
    parser.add_argument("--json-out", default=None, help="Optional JSON output path.")
    args = parser.parse_args()

    result = audit_run(Path(args.run_dir), expected_date=args.expected_date)
    print(json.dumps(result, indent=2, sort_keys=True))
    out = Path(args.json_out) if args.json_out else _find_run_dir(Path(args.run_dir)) / "strict_replay_fidelity_audit.json"
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
