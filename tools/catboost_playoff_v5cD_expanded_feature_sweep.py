#!/usr/bin/env python
"""Test expanded CAT feature bundles on the strict-fidelity corpus.

This is the companion to the old ablation runs. Ablation asks "which current
features matter?" This script asks "do newly available live/replay features
improve the CAT if we add them?"

It uses the same fold logic as catboost_playoff_v5cD_iter600.py and starts from
the current winning CAT shape.
"""

from __future__ import annotations

import argparse
import json
import pickle
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / "data/model/candidates/strict_fidelity_corpus_20260501_20260520_v2_cat_cache_20260521_161940.pkl"
META_PATH = ROOT / "data/model/catboost_playoff/catboost_v5cD_full_corpus.meta.json"


def _load_current_features() -> list[str]:
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    features = list(meta.get("features") or [])
    if not features:
        raise RuntimeError(f"No features found in {META_PATH}")
    return features


def _candidate_bundles() -> dict[str, list[str]]:
    return {
        "game_context_plus": [
            "game_spread",
            "game_total",
            "q_blowout_spread_only",
            "q_blowout_team_adj",
            "q_blowout_matchup_adj",
            "spread_ok",
        ],
        "market_exact_plus": [
            "external_prior_market_prob",
            "external_prior_exact_market",
            "external_prior_market_divergence",
            "external_prior_delta_p",
            "external_prior_probability_applied",
            "external_prior_score",
            "external_prior_n",
        ],
        "role_usage_plus": [
            "role_metrics_mult",
            "role_metrics_score",
            "role_metrics_impact_score",
            "role_metrics_usage_projection_weighted",
            "role_metrics_minutes_projection_weighted",
            "role_metrics_load_weighted",
            "role_metrics_touches_weighted",
            "usage_dep_eff",
            "usage_burden_ratio",
            "modeled_minutes",
            "minutes_cv",
        ],
        "single_game_plus": [
            "single_game_slate",
            "single_game_games",
            "single_game_robustness_score",
            "single_game_script_dependency_score",
            "single_game_slate_severity_score",
            "single_game_anchor_flag",
            "single_game_role_shooter_over_flag",
            "single_game_fg3m_over_flag",
            "single_game_non_shooting_volume_flag",
            "single_game_multi_script_survival_flag",
            "single_game_low_line_noise_flag",
        ],
        "minutes_blowout_plus": [
            "minutes_s_blowout",
            "minutes_s_close",
            "blowout_minute_drop",
            "blowout_minute_delta",
            "sim_minutes_close",
            "sim_minutes_blowout",
            "projected_minutes_model",
            "projected_minutes_delta_from_gamelog",
        ],
        "projection_plus": [
            "atlas_projection_mean",
            "atlas_projection_delta",
            "atlas_projection_side_delta",
            "atlas_projection_abs_delta",
            "atlas_projection_line_ratio",
        ],
    }


def _load_cache_columns(cache_path: Path) -> pd.DataFrame:
    with cache_path.open("rb") as fh:
        cache = pickle.load(fh)
    cv = cache["cv"]
    if not isinstance(cv, pd.DataFrame):
        raise RuntimeError("Cache['cv'] is not a DataFrame")
    return cv


def _valid_feature_columns(df: pd.DataFrame, candidates: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
    valid: list[str] = []
    audit: list[dict[str, Any]] = []
    for feature in candidates:
        if feature not in df.columns:
            audit.append({"feature": feature, "status": "missing"})
            continue
        s = pd.to_numeric(df[feature], errors="coerce")
        non_null = int(s.notna().sum())
        nunique = int(s.nunique(dropna=True))
        nonzero_rate = float((s.fillna(0.0) != 0.0).mean()) if len(s) else 0.0
        status = "ok" if non_null > 0 and nunique > 1 else "dead"
        audit.append(
            {
                "feature": feature,
                "status": status,
                "non_null": non_null,
                "nunique": nunique,
                "nonzero_rate": nonzero_rate,
                "mean": float(s.mean()) if non_null else None,
            }
        )
        if status == "ok":
            valid.append(feature)
    return valid, audit


def _best_scale(result: dict[str, Any]) -> dict[str, Any]:
    rows = result.get("scale_results") or []
    if not rows:
        return {}
    return min(rows, key=lambda row: float(row.get("agg_brier_after_cal") or 99.0))


def _run_candidate(
    *,
    cache_path: Path,
    out_dir: Path,
    label: str,
    features: list[str],
    iterations: int,
    depth: int,
    learning_rate: float,
    residual_scales: list[str],
) -> dict[str, Any]:
    out_path = out_dir / f"{label}.json"
    log_path = out_dir / f"{label}.log"
    cmd = [
        sys.executable,
        "tools/catboost_playoff_v5cD_iter600.py",
        "--cache-path",
        str(cache_path),
        "--out-path",
        str(out_path),
        "--label",
        label,
        "--iterations",
        str(iterations),
        "--depth",
        str(depth),
        "--learning-rate",
        str(learning_rate),
        "--l2-leaf-reg",
        "6.0",
        "--min-data-in-leaf",
        "50",
        "--residual-scales",
        *residual_scales,
        "--features",
        *features,
    ]
    print("\n" + "=" * 80, flush=True)
    print(f"{label}: {len(features)} features", flush=True)
    print(" ".join(cmd), flush=True)
    print("=" * 80, flush=True)
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True, check=False)

    result = json.loads(out_path.read_text(encoding="utf-8")) if out_path.is_file() else {}
    best = _best_scale(result)
    importances = result.get("feature_importance") or []
    return {
        "label": label,
        "exit_code": int(proc.returncode),
        "feature_count": len(features),
        "features": features,
        "out_path": str(out_path),
        "log_path": str(log_path),
        "best_scale": best.get("residual_scale"),
        "best_fair_brier": best.get("agg_brier_after_cal"),
        "best_clean_brier": best.get("clean_brier_after_cal"),
        "best_fair_delta_mB": best.get("agg_delta_mB"),
        "best_clean_delta_mB": best.get("clean_agg_delta_mB"),
        "worst_slate_mB": best.get("worst_slate_mB"),
        "clean_worst_slate_mB": best.get("clean_worst_slate_mB"),
        "clean_verdict": best.get("clean_verdict"),
        "top_importance": importances[:15],
    }


def _select_candidates(names: list[str] | None) -> list[str]:
    all_names = ["current", "game_context_plus", "market_exact_plus", "role_usage_plus", "single_game_plus", "minutes_blowout_plus", "projection_plus", "expanded_compact_all"]
    if not names:
        return all_names
    wanted = []
    for raw in names:
        for part in str(raw).replace(",", " ").split():
            if part:
                wanted.append(part)
    unknown = sorted(set(wanted) - set(all_names))
    if unknown:
        raise ValueError(f"Unknown candidates: {unknown}; valid={all_names}")
    return wanted


def main() -> int:
    parser = argparse.ArgumentParser(description="Run expanded CAT feature bundle sweep.")
    parser.add_argument("--cache-path", default=str(DEFAULT_CACHE))
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--candidates", nargs="*", help="Subset: current game_context_plus market_exact_plus role_usage_plus single_game_plus minutes_blowout_plus expanded_compact_all")
    parser.add_argument("--iterations", type=int, default=800)
    parser.add_argument("--depth", type=int, default=5)
    parser.add_argument("--learning-rate", type=float, default=0.03)
    parser.add_argument("--residual-scales", default="0.45 0.50 0.55 0.60")
    args = parser.parse_args()

    cache_path = Path(args.cache_path)
    if not cache_path.is_absolute():
        cache_path = ROOT / cache_path
    if not cache_path.is_file():
        raise FileNotFoundError(cache_path)

    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "data/model/candidates" / f"nba_cat_expanded_features_{datetime.now():%Y%m%d_%H%M%S}"
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    current = _load_current_features()
    df = _load_cache_columns(cache_path)
    bundles = _candidate_bundles()

    bundle_audit: dict[str, list[dict[str, Any]]] = {}
    expanded_features: dict[str, list[str]] = {"current": current}
    for name, candidates in bundles.items():
        valid, audit = _valid_feature_columns(df, candidates)
        bundle_audit[name] = audit
        expanded_features[name] = list(dict.fromkeys(current + valid))

    all_added = []
    for name in bundles:
        all_added.extend([f for f in expanded_features[name] if f not in current])
    expanded_features["expanded_compact_all"] = list(dict.fromkeys(current + all_added))

    residual_scales = [part for part in str(args.residual_scales).replace(",", " ").split() if part.strip()]
    selected = _select_candidates(args.candidates)
    rows: list[dict[str, Any]] = []
    for label in selected:
        rows.append(
            _run_candidate(
                cache_path=cache_path,
                out_dir=out_dir,
                label=label,
                features=expanded_features[label],
                iterations=args.iterations,
                depth=args.depth,
                learning_rate=args.learning_rate,
                residual_scales=residual_scales,
            )
        )

    rows_sorted = sorted(rows, key=lambda row: float(row.get("best_fair_brier") or 99.0))
    summary = {
        "source": "catboost_playoff_v5cD_expanded_feature_sweep",
        "cache_path": str(cache_path),
        "out_dir": str(out_dir),
        "current_features": current,
        "bundle_audit": bundle_audit,
        "candidate_results": rows_sorted,
        "best": rows_sorted[0] if rows_sorted else {},
    }
    (out_dir / "expanded_feature_sweep_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    pd.DataFrame(
        [
            {
                "label": row["label"],
                "feature_count": row["feature_count"],
                "best_scale": row.get("best_scale"),
                "best_fair_brier": row.get("best_fair_brier"),
                "best_clean_brier": row.get("best_clean_brier"),
                "best_fair_delta_mB": row.get("best_fair_delta_mB"),
                "best_clean_delta_mB": row.get("best_clean_delta_mB"),
                "worst_slate_mB": row.get("worst_slate_mB"),
                "clean_worst_slate_mB": row.get("clean_worst_slate_mB"),
                "clean_verdict": row.get("clean_verdict"),
                "out_path": row.get("out_path"),
            }
            for row in rows_sorted
        ]
    ).to_csv(out_dir / "expanded_feature_sweep_results.csv", index=False)

    print("\nEXPANDED FEATURE SWEEP RESULTS", flush=True)
    for row in rows_sorted:
        print(
            f"{row['label']}: features={row['feature_count']} "
            f"fair={row.get('best_fair_brier')} clean={row.get('best_clean_brier')} "
            f"scale={row.get('best_scale')} verdict={row.get('clean_verdict')}",
            flush=True,
        )
    print(f"Summary: {out_dir / 'expanded_feature_sweep_summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
