"""Run a small nearby CAT/LODO sweep from the promoted v5cD family.

This is intentionally narrow. It assumes the replay corpus has already passed
strict fidelity and the cache was built by build_playoff_resim_cache.py.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / "data" / "model" / "_v1_playoff_resim_cache.pkl"


CONFIGS = [
    {
        "label": "current_v5cD_iter600_depth5_lr075",
        "iterations": 600,
        "depth": 5,
        "learning_rate": 0.075,
        "l2_leaf_reg": 6.0,
        "min_data_in_leaf": 50,
    },
    {
        "label": "near_v5cA_iter500_depth5_lr075",
        "iterations": 500,
        "depth": 5,
        "learning_rate": 0.075,
        "l2_leaf_reg": 6.0,
        "min_data_in_leaf": 50,
    },
    {
        "label": "near_iter700_depth5_lr060",
        "iterations": 700,
        "depth": 5,
        "learning_rate": 0.060,
        "l2_leaf_reg": 6.0,
        "min_data_in_leaf": 50,
    },
    {
        "label": "near_iter800_depth5_lr030",
        "iterations": 800,
        "depth": 5,
        "learning_rate": 0.030,
        "l2_leaf_reg": 6.0,
        "min_data_in_leaf": 50,
    },
    {
        "label": "near_depth4_iter700_lr060",
        "iterations": 700,
        "depth": 4,
        "learning_rate": 0.060,
        "l2_leaf_reg": 6.0,
        "min_data_in_leaf": 50,
    },
]


def _best_scale(result: dict) -> dict:
    rows = result.get("scale_results") or []
    if not rows:
        return {}
    return min(rows, key=lambda r: float(r.get("agg_brier_after_cal", 99.0)))


def main() -> int:
    ap = argparse.ArgumentParser(description="Run nearby v5cD CAT LODO candidates.")
    ap.add_argument("--cache-path", default=str(DEFAULT_CACHE), help="Strict-fidelity cache pickle.")
    ap.add_argument(
        "--out-dir",
        default=None,
        help="Output directory. Default: data/model/candidates/nba_cat_nearby_sweep_<timestamp>",
    )
    ap.add_argument(
        "--residual-scales",
        default="0.45 0.50 0.55 0.60",
        help="Space/comma separated residual scales evaluated from each LODO prediction set.",
    )
    ap.add_argument("--only", nargs="*", help="Optional labels to run.")
    args = ap.parse_args()

    cache_path = Path(args.cache_path)
    if not cache_path.is_absolute():
        cache_path = ROOT / cache_path
    if not cache_path.is_file():
        raise FileNotFoundError(f"Cache not found: {cache_path}")

    out_dir = Path(args.out_dir) if args.out_dir else (
        ROOT / "data" / "model" / "candidates" / f"nba_cat_nearby_sweep_{datetime.now():%Y%m%d_%H%M%S}"
    )
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    selected = CONFIGS
    if args.only:
        wanted = set(args.only)
        selected = [cfg for cfg in CONFIGS if cfg["label"] in wanted]
        missing = wanted - {cfg["label"] for cfg in selected}
        if missing:
            raise ValueError(f"Unknown --only labels: {sorted(missing)}")

    residual_scales = [
        part
        for item in str(args.residual_scales).replace(",", " ").split()
        if (part := item.strip())
    ]

    summary = {
        "cache_path": str(cache_path),
        "out_dir": str(out_dir),
        "residual_scales": residual_scales,
        "configs": selected,
        "results": [],
    }

    for cfg in selected:
        out_path = out_dir / f"{cfg['label']}.json"
        log_path = out_dir / f"{cfg['label']}.log"
        cmd = [
            sys.executable,
            "tools/catboost_playoff_v5cD_iter600.py",
            "--cache-path",
            str(cache_path),
            "--out-path",
            str(out_path),
            "--label",
            cfg["label"],
            "--iterations",
            str(cfg["iterations"]),
            "--depth",
            str(cfg["depth"]),
            "--learning-rate",
            str(cfg["learning_rate"]),
            "--l2-leaf-reg",
            str(cfg["l2_leaf_reg"]),
            "--min-data-in-leaf",
            str(cfg["min_data_in_leaf"]),
            "--residual-scales",
            *residual_scales,
        ]
        print("\n" + "=" * 80, flush=True)
        print(cfg["label"], flush=True)
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
        row = {
            "label": cfg["label"],
            "exit_code": proc.returncode,
            "out_path": str(out_path),
            "log_path": str(log_path),
            "best_scale": best.get("residual_scale"),
            "best_fair_brier": best.get("agg_brier_after_cal"),
            "best_clean_brier": best.get("clean_brier_after_cal"),
            "best_fair_delta_mB": best.get("agg_delta_mB"),
            "best_clean_delta_mB": best.get("clean_agg_delta_mB"),
            "best_clean_verdict": best.get("clean_verdict"),
        }
        summary["results"].append(row)
        print(
            f"{cfg['label']}: exit={proc.returncode} "
            f"best_scale={row['best_scale']} fair_brier={row['best_fair_brier']} "
            f"clean_brier={row['best_clean_brier']}",
            flush=True,
        )
        if proc.returncode != 0:
            break

    summary["results"].sort(
        key=lambda r: (
            1 if r.get("exit_code") else 0,
            float(r.get("best_fair_brier") or 99.0),
        )
    )
    summary_path = out_dir / "nearby_sweep_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nWrote summary: {summary_path}", flush=True)
    if summary["results"]:
        print("Best candidates by fair brier:", flush=True)
        for row in summary["results"][:5]:
            print(
                f"  {row['label']}: fair={row['best_fair_brier']} "
                f"clean={row['best_clean_brier']} scale={row['best_scale']}",
                flush=True,
            )
    return 0 if all(r.get("exit_code") == 0 for r in summary["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
