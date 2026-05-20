"""Compare MLB CAT artifacts using existing LODO prediction files.

This is intentionally not a replay runner. It compares artifacts on the same
projection keys that already exist in each artifact's LODO predictions, so we
can make a fast, fair-ish promotion check without rebuilding 20+ replay dates.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from mlb.domain.playability import is_over_only_tier


DEFAULT_ARTIFACTS = [
    "data/mlb/model/cat_probability_kernel_v5_reorg_bettingpros_on/best_config.json",
    "data/mlb/model/cat_probability_kernel_v6_23date_live_context/best_config.json",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare MLB CAT artifacts from existing LODO predictions")
    parser.add_argument("--root", default=".")
    parser.add_argument("--artifacts", nargs="+", default=DEFAULT_ARTIFACTS)
    parser.add_argument("--output-dir", default="data/mlb/model/cat_lodo_artifact_comparison")
    parser.add_argument(
        "--min-overlap-rows",
        type=int,
        default=1000,
        help="Fail if the common prediction-key overlap is below this count.",
    )
    parser.add_argument(
        "--promotion-brier-margin",
        type=float,
        default=0.0,
        help="Required challenger Brier improvement over incumbent. First artifact is incumbent, second is challenger.",
    )
    parser.add_argument(
        "--promotion-logloss-margin",
        type=float,
        default=0.0,
        help="Allowed challenger logloss worsening over incumbent. First artifact is incumbent, second is challenger.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output_dir = _resolve_path(root, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts = [_load_artifact(root, raw_path) for raw_path in args.artifacts]
    if len(artifacts) < 2:
        raise RuntimeError("At least two artifacts are required for comparison")

    common_keys = set(artifacts[0]["rows_by_key"].keys())
    for artifact in artifacts[1:]:
        common_keys &= set(artifact["rows_by_key"].keys())
    common_keys = set(sorted(common_keys))
    if len(common_keys) < args.min_overlap_rows:
        raise RuntimeError(
            f"Only {len(common_keys)} overlapping LODO prediction rows found; "
            f"minimum required is {args.min_overlap_rows}."
        )

    comparison_rows: list[dict[str, Any]] = []
    per_date_rows: list[dict[str, Any]] = []
    per_tier_rows: list[dict[str, Any]] = []
    per_market_rows: list[dict[str, Any]] = []
    full_summary_rows: list[dict[str, Any]] = []
    full_date_rows: list[dict[str, Any]] = []
    full_tier_rows: list[dict[str, Any]] = []
    full_market_rows: list[dict[str, Any]] = []

    for artifact in artifacts:
        rows = [artifact["rows_by_key"][key] for key in common_keys]
        summary = _summarize(rows, artifact=artifact)
        comparison_rows.append(summary)
        per_date_rows.extend(_segment(rows, artifact=artifact, segment_name="game_date"))
        per_tier_rows.extend(_segment(rows, artifact=artifact, segment_name="tier"))
        per_market_rows.extend(_segment(rows, artifact=artifact, segment_name="market"))

        full_rows = list(artifact["rows_by_key"].values())
        full_summary_rows.append(_summarize(full_rows, artifact=artifact))
        full_date_rows.extend(_segment(full_rows, artifact=artifact, segment_name="game_date"))
        full_tier_rows.extend(_segment(full_rows, artifact=artifact, segment_name="tier"))
        full_market_rows.extend(_segment(full_rows, artifact=artifact, segment_name="market"))

    comparison_rows = sorted(comparison_rows, key=lambda row: (row["brier"], row["logloss"], -row["pick_win_rate"]))
    baseline = comparison_rows[0]
    for row in comparison_rows:
        row["delta_brier_vs_best"] = round(float(row["brier"]) - float(baseline["brier"]), 8)
        row["delta_logloss_vs_best"] = round(float(row["logloss"]) - float(baseline["logloss"]), 8)

    promotion_gate = _promotion_gate(
        comparison_rows=comparison_rows,
        artifacts=artifacts,
        brier_margin=args.promotion_brier_margin,
        logloss_margin=args.promotion_logloss_margin,
    )

    summary = {
        "schema_version": "mlb_cat_lodo_artifact_comparison_v1",
        "mode": "existing_lodo_prediction_key_overlap",
        "artifact_count": len(artifacts),
        "overlap_rows": len(common_keys),
        "overlap_dates": sorted({key.split("|", 1)[0] for key in common_keys}),
        "promotion_gate": promotion_gate,
        "artifacts": [
            {
                "name": artifact["name"],
                "version": artifact["version"],
                "artifact_path": str(artifact["artifact_path"]),
                "lodo_predictions_csv": str(artifact["predictions_path"]),
                "total_lodo_rows": artifact["total_rows"],
                "artifact_date_count": artifact["date_count"],
                "artifact_best_lodo": artifact["best_lodo"],
            }
            for artifact in artifacts
        ],
        "comparison": comparison_rows,
        "notes": [
            "This does not rerun replays.",
            "This does not apply final full-corpus models in-sample.",
            "Rows are compared only where every artifact has an existing LODO prediction for the same date/projection/market/line/tier key.",
        ],
    }

    _write_csv(output_dir / "comparison_summary.csv", comparison_rows)
    _write_csv(output_dir / "comparison_by_date.csv", per_date_rows)
    _write_csv(output_dir / "comparison_by_tier.csv", per_tier_rows)
    _write_csv(output_dir / "comparison_by_market.csv", per_market_rows)
    _write_csv(output_dir / "comparison_delta_by_date.csv", _segment_deltas(per_date_rows, artifacts=artifacts))
    _write_csv(output_dir / "comparison_delta_by_tier.csv", _segment_deltas(per_tier_rows, artifacts=artifacts))
    _write_csv(output_dir / "comparison_delta_by_market.csv", _segment_deltas(per_market_rows, artifacts=artifacts))
    _write_csv(output_dir / "artifact_full_summary.csv", full_summary_rows)
    _write_csv(output_dir / "artifact_full_by_date.csv", full_date_rows)
    _write_csv(output_dir / "artifact_full_by_tier.csv", full_tier_rows)
    _write_csv(output_dir / "artifact_full_by_market.csv", full_market_rows)
    (output_dir / "comparison_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _promotion_gate(
    *,
    comparison_rows: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    brier_margin: float,
    logloss_margin: float,
) -> dict[str, Any]:
    if len(artifacts) < 2:
        return {"available": False, "reason": "requires at least incumbent and challenger artifacts"}
    by_name = {str(row["artifact"]): row for row in comparison_rows}
    incumbent_name = artifacts[0]["name"]
    challenger_name = artifacts[1]["name"]
    incumbent = by_name.get(incumbent_name)
    challenger = by_name.get(challenger_name)
    if not incumbent or not challenger:
        return {"available": False, "reason": "incumbent/challenger rows missing from comparison"}
    challenger_brier_delta = round(float(challenger["brier"]) - float(incumbent["brier"]), 8)
    challenger_logloss_delta = round(float(challenger["logloss"]) - float(incumbent["logloss"]), 8)
    brier_pass = challenger_brier_delta <= -abs(float(brier_margin))
    logloss_pass = challenger_logloss_delta <= abs(float(logloss_margin))
    return {
        "available": True,
        "incumbent": incumbent_name,
        "challenger": challenger_name,
        "promote_challenger": bool(brier_pass and logloss_pass),
        "brier_pass": bool(brier_pass),
        "logloss_pass": bool(logloss_pass),
        "challenger_brier_delta_vs_incumbent": challenger_brier_delta,
        "challenger_logloss_delta_vs_incumbent": challenger_logloss_delta,
        "required_brier_improvement": abs(float(brier_margin)),
        "allowed_logloss_worsening": abs(float(logloss_margin)),
    }


def _load_artifact(root: Path, raw_path: str) -> dict[str, Any]:
    artifact_path = _resolve_path(root, raw_path)
    meta = json.loads(artifact_path.read_text(encoding="utf-8"))
    predictions_path = Path(str(meta.get("lodo_predictions_csv") or artifact_path.parent / "lodo_predictions.csv"))
    if not predictions_path.is_absolute():
        predictions_path = (artifact_path.parent / predictions_path).resolve()
    if not predictions_path.exists():
        fallback = artifact_path.parent / "lodo_predictions.csv"
        if fallback.exists():
            predictions_path = fallback
        else:
            raise FileNotFoundError(f"Missing LODO predictions for {artifact_path}: {predictions_path}")

    rows_by_key: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    rows = _read_csv(predictions_path)
    for row in rows:
        key = _prediction_key(row)
        if key in rows_by_key:
            duplicate_count += 1
            continue
        rows_by_key[key] = row

    return {
        "name": artifact_path.parent.name,
        "version": str(meta.get("version") or meta.get("calibration_version") or artifact_path.parent.name),
        "artifact_path": artifact_path,
        "predictions_path": predictions_path,
        "rows_by_key": rows_by_key,
        "total_rows": len(rows),
        "duplicate_key_count": duplicate_count,
        "date_count": int(_float(meta.get("date_count"), 0)),
        "best_lodo": meta.get("best_lodo") or {},
    }


def _prediction_key(row: dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("game_date") or "").strip(),
            str(row.get("source_projection_id") or "").strip(),
            str(row.get("market") or "").strip(),
            _line_key(row.get("line")),
            str(row.get("tier") or "STANDARD").strip().upper() or "STANDARD",
        ]
    )


def _summarize(rows: list[dict[str, Any]], *, artifact: dict[str, Any]) -> dict[str, Any]:
    labels = [_float(row.get("actual_over"), 0.0) for row in rows]
    probabilities = [_float(row.get("adjusted_over_probability"), 0.5) for row in rows]
    baseline_probabilities = [_float(row.get("base_over_probability"), 0.5) for row in rows]
    tiers = [str(row.get("tier") or "STANDARD").upper() for row in rows]
    metric = _metrics(labels, probabilities)
    baseline = _metrics(labels, baseline_probabilities)
    pick_metric = _pick_metrics(labels, probabilities, tiers=tiers)
    return {
        "artifact": artifact["name"],
        "version": artifact["version"],
        "rows": len(rows),
        "dates": len({str(row.get("game_date") or "") for row in rows}),
        "brier": metric["brier"],
        "logloss": metric["logloss"],
        "baseline_brier": baseline["brier"],
        "baseline_logloss": baseline["logloss"],
        "delta_brier_vs_baseline": round(metric["brier"] - baseline["brier"], 8),
        "delta_logloss_vs_baseline": round(metric["logloss"] - baseline["logloss"], 8),
        "pick_brier": pick_metric["brier"],
        "pick_logloss": pick_metric["logloss"],
        "pick_win_rate": pick_metric["win_rate"],
        "artifact_lodo_brier": _nested_float(artifact["best_lodo"], "brier_over"),
        "artifact_lodo_logloss": _nested_float(artifact["best_lodo"], "logloss_over"),
        "artifact_sweep_id": str((artifact["best_lodo"] or {}).get("sweep_id") or ""),
    }


def _segment(rows: list[dict[str, Any]], *, artifact: dict[str, Any], segment_name: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(segment_name) or "").strip() or "(blank)"].append(row)
    output = []
    for segment_value, segment_rows in sorted(grouped.items()):
        metric = _summarize(segment_rows, artifact=artifact)
        metric["segment"] = segment_name
        metric["segment_value"] = segment_value
        output.append(metric)
    return output


def _segment_deltas(rows: list[dict[str, Any]], *, artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(artifacts) < 2:
        return []
    incumbent_name = str(artifacts[0]["name"])
    challenger_name = str(artifacts[1]["name"])
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        key = str(row.get("segment_value") or "")
        grouped[key][str(row.get("artifact") or "")] = row

    output: list[dict[str, Any]] = []
    for segment_value, artifact_rows in grouped.items():
        incumbent = artifact_rows.get(incumbent_name)
        challenger = artifact_rows.get(challenger_name)
        if not incumbent or not challenger:
            continue
        rows_count = int(_float(challenger.get("rows"), 0.0))
        brier_delta = _float(challenger.get("brier"), 0.0) - _float(incumbent.get("brier"), 0.0)
        logloss_delta = _float(challenger.get("logloss"), 0.0) - _float(incumbent.get("logloss"), 0.0)
        pick_win_rate_delta = _float(challenger.get("pick_win_rate"), 0.0) - _float(incumbent.get("pick_win_rate"), 0.0)
        output.append(
            {
                "segment": str(challenger.get("segment") or incumbent.get("segment") or ""),
                "segment_value": segment_value,
                "rows": rows_count,
                "incumbent": incumbent_name,
                "challenger": challenger_name,
                "incumbent_brier": incumbent.get("brier"),
                "challenger_brier": challenger.get("brier"),
                "delta_brier": round(brier_delta, 8),
                "weighted_delta_brier": round(brier_delta * rows_count, 8),
                "incumbent_logloss": incumbent.get("logloss"),
                "challenger_logloss": challenger.get("logloss"),
                "delta_logloss": round(logloss_delta, 8),
                "weighted_delta_logloss": round(logloss_delta * rows_count, 8),
                "incumbent_pick_win_rate": incumbent.get("pick_win_rate"),
                "challenger_pick_win_rate": challenger.get("pick_win_rate"),
                "delta_pick_win_rate": round(pick_win_rate_delta, 8),
            }
        )
    return sorted(output, key=lambda row: (-float(row["weighted_delta_brier"]), -float(row["delta_brier"])))


def _metrics(labels: list[float], probabilities: list[float]) -> dict[str, float]:
    total = len(labels)
    if total == 0:
        return {"brier": 0.0, "logloss": 0.0}
    brier = 0.0
    logloss = 0.0
    for label, probability in zip(labels, probabilities, strict=False):
        p = _clamp(probability, 1e-6, 1.0 - 1e-6)
        y = 1.0 if label >= 0.5 else 0.0
        brier += (p - y) ** 2
        logloss += -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
    return {"brier": round(brier / total, 8), "logloss": round(logloss / total, 8)}


def _pick_metrics(labels: list[float], probabilities: list[float], *, tiers: list[str]) -> dict[str, float]:
    pick_labels: list[float] = []
    pick_probabilities: list[float] = []
    for label, probability, tier in zip(labels, probabilities, tiers, strict=False):
        p = _clamp(probability, 1e-6, 1.0 - 1e-6)
        pick_is_over = True if is_over_only_tier(tier) else p >= 0.5
        hit = bool(label >= 0.5) if pick_is_over else bool(label < 0.5)
        pick_labels.append(1.0 if hit else 0.0)
        pick_probabilities.append(p if pick_is_over else 1.0 - p)
    metric = _metrics(pick_labels, pick_probabilities)
    metric["win_rate"] = round(sum(pick_labels) / len(pick_labels), 8) if pick_labels else 0.0
    return metric


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _resolve_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def _line_key(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _nested_float(data: Any, key: str) -> float:
    if not isinstance(data, dict):
        return 0.0
    return _float(data.get(key), 0.0)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


if __name__ == "__main__":
    raise SystemExit(main())
