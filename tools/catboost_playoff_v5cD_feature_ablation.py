"""Run strict-fidelity CAT feature ablation for the v5cD residual stack.

This wrapper reuses catboost_playoff_v5cD_iter600.py so the fold logic,
residual scaling, clean-slate gate, and output schema stay identical to the
normal trainer. It runs:

1. Baseline with the selected feature contract.
2. Leave-one-feature-out (LOFO) for every selected feature.

The output ranks drops by fair Brier and clean Brier so we can tell which
features help or hurt under the current strict-fidelity replay cache.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"


def _load_feature_contract() -> list[str]:
    meta_path = ROOT / "data" / "model" / "catboost_playoff" / "catboost_v5cD_full_corpus.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    features = list(meta.get("features") or [])
    if not features:
        raise RuntimeError(f"No features found in {meta_path}")
    return features


def _parse_feature_list(raw: list[str] | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for item in raw:
        for part in str(item).replace(",", " ").split():
            part = part.strip()
            if part:
                out.append(part)
    return out


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
    iterations: int,
    depth: int,
    learning_rate: float,
    l2_leaf_reg: float,
    min_data_in_leaf: int,
    residual_scales: list[str],
    drop_features: list[str],
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
        str(l2_leaf_reg),
        "--min-data-in-leaf",
        str(min_data_in_leaf),
        "--residual-scales",
        *residual_scales,
    ]
    if drop_features:
        cmd.extend(["--drop-features", *drop_features])

    print("\n" + "=" * 80, flush=True)
    print(label, flush=True)
    if drop_features:
        print(f"drop_features={drop_features}", flush=True)
    print(" ".join(cmd), flush=True)
    print("=" * 80, flush=True)

    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

    result = json.loads(out_path.read_text(encoding="utf-8")) if out_path.is_file() else {}
    best = _best_scale(result)
    return {
        "label": label,
        "drop_features": drop_features,
        "exit_code": proc.returncode,
        "out_path": str(out_path),
        "log_path": str(log_path),
        "best_scale": best.get("residual_scale"),
        "best_fair_brier": best.get("agg_brier_after_cal"),
        "best_clean_brier": best.get("clean_brier_after_cal"),
        "best_fair_delta_mB": best.get("agg_delta_mB"),
        "best_clean_delta_mB": best.get("clean_agg_delta_mB"),
        "best_clean_verdict": best.get("clean_verdict"),
        "worst_slate_mB": best.get("worst_slate_mB"),
        "clean_worst_slate_mB": best.get("clean_worst_slate_mB"),
    }


def _classify(row: dict[str, Any], baseline: dict[str, Any]) -> str:
    if row.get("exit_code") != 0:
        return "ERROR"
    base_brier = float(baseline.get("best_fair_brier") or 99.0)
    row_brier = float(row.get("best_fair_brier") or 99.0)
    delta = row_brier - base_brier
    if delta <= -0.00025:
        return "HURTS_MODEL_DROP_HELPED"
    if delta >= 0.00025:
        return "HELPS_MODEL_DROP_HURT"
    return "NEUTRAL"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run v5cD CAT feature ablation.")
    parser.add_argument("--cache-path", default=str(DEFAULT_CACHE), help="Strict-fidelity cache pickle.")
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory. Default: data/model/candidates/nba_cat_feature_ablation_<timestamp>",
    )
    parser.add_argument("--iterations", type=int, default=800)
    parser.add_argument("--depth", type=int, default=5)
    parser.add_argument("--learning-rate", type=float, default=0.03)
    parser.add_argument("--l2-leaf-reg", type=float, default=6.0)
    parser.add_argument("--min-data-in-leaf", type=int, default=50)
    parser.add_argument("--residual-scales", default="0.45 0.50 0.55 0.60")
    parser.add_argument("--features", nargs="*", help="Optional feature subset to test.")
    parser.add_argument("--only", nargs="*", help="Only run LOFO for these features.")
    parser.add_argument("--skip-baseline", action="store_true", help="Reuse an existing baseline JSON in out-dir.")
    args = parser.parse_args()

    cache_path = Path(args.cache_path)
    if not cache_path.is_absolute():
        cache_path = ROOT / cache_path
    if not cache_path.is_file():
        raise FileNotFoundError(f"Cache not found: {cache_path}")

    out_dir = Path(args.out_dir) if args.out_dir else (
        ROOT / "data" / "model" / "candidates" / f"nba_cat_feature_ablation_{datetime.now():%Y%m%d_%H%M%S}"
    )
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    features = _parse_feature_list(args.features) or _load_feature_contract()
    only = set(_parse_feature_list(args.only))
    if only:
        unknown = sorted(only - set(features))
        if unknown:
            raise ValueError(f"--only has unknown features: {unknown}")
        test_features = [feature for feature in features if feature in only]
    else:
        test_features = list(features)

    residual_scales = [part for part in str(args.residual_scales).replace(",", " ").split() if part.strip()]

    summary: dict[str, Any] = {
        "cache_path": str(cache_path),
        "out_dir": str(out_dir),
        "features": features,
        "tested_features": test_features,
        "params": {
            "iterations": args.iterations,
            "depth": args.depth,
            "learning_rate": args.learning_rate,
            "l2_leaf_reg": args.l2_leaf_reg,
            "min_data_in_leaf": args.min_data_in_leaf,
            "residual_scales": residual_scales,
        },
        "results": [],
    }

    baseline_path = out_dir / "baseline_all_features.json"
    if args.skip_baseline and baseline_path.is_file():
        baseline_result = json.loads(baseline_path.read_text(encoding="utf-8"))
        best = _best_scale(baseline_result)
        baseline_row = {
            "label": "baseline_all_features",
            "drop_features": [],
            "exit_code": 0,
            "out_path": str(baseline_path),
            "log_path": str(out_dir / "baseline_all_features.log"),
            "best_scale": best.get("residual_scale"),
            "best_fair_brier": best.get("agg_brier_after_cal"),
            "best_clean_brier": best.get("clean_brier_after_cal"),
            "best_fair_delta_mB": best.get("agg_delta_mB"),
            "best_clean_delta_mB": best.get("clean_agg_delta_mB"),
            "best_clean_verdict": best.get("clean_verdict"),
            "worst_slate_mB": best.get("worst_slate_mB"),
            "clean_worst_slate_mB": best.get("clean_worst_slate_mB"),
        }
    else:
        baseline_row = _run_candidate(
            cache_path=cache_path,
            out_dir=out_dir,
            label="baseline_all_features",
            iterations=args.iterations,
            depth=args.depth,
            learning_rate=args.learning_rate,
            l2_leaf_reg=args.l2_leaf_reg,
            min_data_in_leaf=args.min_data_in_leaf,
            residual_scales=residual_scales,
            drop_features=[],
        )
    summary["baseline"] = baseline_row
    print(
        f"baseline: fair={baseline_row.get('best_fair_brier')} "
        f"clean={baseline_row.get('best_clean_brier')} scale={baseline_row.get('best_scale')}",
        flush=True,
    )
    if baseline_row.get("exit_code") != 0:
        summary_path = out_dir / "feature_ablation_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return int(baseline_row.get("exit_code") or 1)

    rows: list[dict[str, Any]] = []
    for feature in test_features:
        label = "drop_" + "".join(ch if ch.isalnum() else "_" for ch in feature)
        row = _run_candidate(
            cache_path=cache_path,
            out_dir=out_dir,
            label=label,
            iterations=args.iterations,
            depth=args.depth,
            learning_rate=args.learning_rate,
            l2_leaf_reg=args.l2_leaf_reg,
            min_data_in_leaf=args.min_data_in_leaf,
            residual_scales=residual_scales,
            drop_features=[feature],
        )
        row["feature"] = feature
        row["classification"] = _classify(row, baseline_row)
        row["fair_brier_vs_baseline"] = (
            float(row["best_fair_brier"]) - float(baseline_row["best_fair_brier"])
            if row.get("best_fair_brier") is not None and baseline_row.get("best_fair_brier") is not None
            else None
        )
        row["clean_brier_vs_baseline"] = (
            float(row["best_clean_brier"]) - float(baseline_row["best_clean_brier"])
            if row.get("best_clean_brier") is not None and baseline_row.get("best_clean_brier") is not None
            else None
        )
        rows.append(row)
        print(
            f"{feature}: {row['classification']} fair={row.get('best_fair_brier')} "
            f"delta={row.get('fair_brier_vs_baseline'):+.6f}",
            flush=True,
        )
        if row.get("exit_code") != 0:
            break

    rows.sort(
        key=lambda row: (
            1 if row.get("exit_code") else 0,
            float(row.get("best_fair_brier") or 99.0),
        )
    )
    summary["results"] = rows
    summary["harmful_if_present"] = [row for row in rows if row.get("classification") == "HURTS_MODEL_DROP_HELPED"]
    summary["helpful_if_present"] = [row for row in rows if row.get("classification") == "HELPS_MODEL_DROP_HURT"]
    summary_path = out_dir / "feature_ablation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\nWrote summary: {summary_path}", flush=True)
    print("Best drops by fair brier:", flush=True)
    for row in rows[:10]:
        print(
            f"  {row.get('feature')}: fair={row.get('best_fair_brier')} "
            f"clean={row.get('best_clean_brier')} class={row.get('classification')}",
            flush=True,
        )
    return 0 if all(row.get("exit_code") == 0 for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
