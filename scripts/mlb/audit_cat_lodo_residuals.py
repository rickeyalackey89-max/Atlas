"""Audit CAT LODO residual quality by replay-safe model segments.

This is a fast diagnostic: it reads an existing CAT artifact, joins its
``lodo_predictions.csv`` to the artifact training corpus, and writes segment
summaries. It does not retrain CAT and does not run replays.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_ARTIFACT = "data/mlb/model/cat_probability_kernel_v6_23date_live_context/best_config.json"

SEGMENTS = (
    "market",
    "tier",
    "market|tier",
    "market_context_source_type",
    "external_market_context_source",
    "market_line_match_type",
    "line_bucket",
    "market|line_bucket",
    "market|market_context_source_type",
    "tier|market_context_source_type",
    "feature_external_market_context_available",
    "feature_prizepicks_line_only_market_context",
    "feature_market_source_is_bettingpros",
    "feature_market_source_is_dk_pick6",
    "feature_market_source_is_dk_sportsbook",
    "feature_lineup_context_available",
    "feature_probable_pitcher_context_available",
    "feature_roster_context_available",
    "feature_player_history_context_available",
    "advanced_context_available",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit MLB CAT LODO residuals by segment")
    parser.add_argument("--root", default=".")
    parser.add_argument("--artifact", default=DEFAULT_ARTIFACT)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--min-rows", type=int, default=50)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    artifact_path = _resolve(root, args.artifact)
    meta = json.loads(artifact_path.read_text(encoding="utf-8"))
    predictions_path = _artifact_path(artifact_path, meta.get("lodo_predictions_csv"), "lodo_predictions.csv")
    training_corpus_path = _artifact_path(artifact_path, meta.get("training_corpus_csv"), "training_corpus.csv")
    output_dir = _resolve(root, args.output_dir) if args.output_dir else artifact_path.parent / "lodo_residual_audit"
    output_dir.mkdir(parents=True, exist_ok=True)

    predictions = _read_csv(predictions_path)
    training_by_key = {_key(row): row for row in _read_csv(training_corpus_path)}
    rows = []
    missing_training_rows = 0
    for prediction in predictions:
        training = training_by_key.get(_key(prediction), {})
        if not training:
            missing_training_rows += 1
        row = dict(training)
        row.update({key: value for key, value in prediction.items() if value not in ("", None)})
        rows.append(_normalized_row(row))

    overall = _summary(rows, segment="overall", segment_value="all")
    segment_rows: list[dict[str, Any]] = []
    for segment in SEGMENTS:
        segment_rows.extend(
            row
            for row in _segment(rows, segment=segment)
            if int(row["rows"]) >= args.min_rows
        )
    segment_rows = sorted(segment_rows, key=lambda row: (row["segment"], -int(row["rows"]), row["segment_value"]))

    worst_rows = sorted(
        (row for row in segment_rows if int(row["rows"]) >= args.min_rows),
        key=lambda row: (-abs(float(row["calibration_gap"])), -float(row["brier"]), -int(row["rows"])),
    )[:75]

    _write_csv(output_dir / "overall.csv", [overall])
    _write_csv(output_dir / "segment_summary.csv", segment_rows)
    _write_csv(output_dir / "worst_calibration_segments.csv", worst_rows)
    manifest = {
        "schema_version": "mlb_cat_lodo_residual_audit_v1",
        "artifact_path": str(artifact_path),
        "predictions_path": str(predictions_path),
        "training_corpus_path": str(training_corpus_path),
        "output_dir": str(output_dir),
        "row_count": len(rows),
        "missing_training_rows": missing_training_rows,
        "min_rows": args.min_rows,
        "overall": overall,
        "outputs": {
            "overall": str(output_dir / "overall.csv"),
            "segment_summary": str(output_dir / "segment_summary.csv"),
            "worst_calibration_segments": str(output_dir / "worst_calibration_segments.csv"),
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def _normalized_row(row: dict[str, Any]) -> dict[str, Any]:
    output = dict(row)
    output["actual_over"] = 1.0 if _float(row.get("actual_over"), 0.0) >= 0.5 else 0.0
    output["base_over_probability"] = _clamp(_float(row.get("base_over_probability"), 0.5), 1e-6, 1 - 1e-6)
    output["adjusted_over_probability"] = _clamp(_float(row.get("adjusted_over_probability"), 0.5), 1e-6, 1 - 1e-6)
    output["cat_residual"] = _float(row.get("cat_residual"), 0.0)
    if not str(output.get("line_bucket") or "").strip():
        output["line_bucket"] = _line_bucket(_float(output.get("line"), 0.0))
    if not str(output.get("market_context_source_type") or "").strip():
        output["market_context_source_type"] = (
            "prizepicks_line_only"
            if _truthy(output.get("feature_prizepicks_line_only_market_context"))
            else "external_market"
        )
    return output


def _segment(rows: list[dict[str, Any]], *, segment: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    keys = segment.split("|")
    for row in rows:
        grouped["|".join(_segment_value(row, key) for key in keys)].append(row)
    return [_summary(segment_rows, segment=segment, segment_value=value) for value, segment_rows in sorted(grouped.items())]


def _segment_value(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if key.startswith("feature_"):
        return "true" if _truthy(value) else "false"
    return str(value or "(blank)").strip() or "(blank)"


def _summary(rows: list[dict[str, Any]], *, segment: str, segment_value: str) -> dict[str, Any]:
    labels = [float(row["actual_over"]) for row in rows]
    base = [float(row["base_over_probability"]) for row in rows]
    adjusted = [float(row["adjusted_over_probability"]) for row in rows]
    base_metric = _metrics(labels, base)
    adjusted_metric = _metrics(labels, adjusted)
    actual_rate = _mean(labels)
    avg_prob = _mean(adjusted)
    return {
        "segment": segment,
        "segment_value": segment_value,
        "rows": len(rows),
        "actual_over_rate": round(actual_rate, 8),
        "avg_adjusted_probability": round(avg_prob, 8),
        "calibration_gap": round(actual_rate - avg_prob, 8),
        "brier": adjusted_metric["brier"],
        "logloss": adjusted_metric["logloss"],
        "base_brier": base_metric["brier"],
        "base_logloss": base_metric["logloss"],
        "delta_brier_vs_base": round(adjusted_metric["brier"] - base_metric["brier"], 8),
        "mean_residual": round(_mean(_float(row.get("cat_residual"), 0.0) for row in rows), 8),
        "avg_line": round(_mean(_float(row.get("line"), 0.0) for row in rows), 8),
    }


def _metrics(labels: list[float], probabilities: list[float]) -> dict[str, float]:
    if not labels:
        return {"brier": 0.0, "logloss": 0.0}
    brier = 0.0
    logloss = 0.0
    for label, probability in zip(labels, probabilities, strict=False):
        y = 1.0 if label >= 0.5 else 0.0
        p = _clamp(probability, 1e-6, 1.0 - 1e-6)
        brier += (p - y) ** 2
        logloss += -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
    return {"brier": round(brier / len(labels), 8), "logloss": round(logloss / len(labels), 8)}


def _key(row: dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("run_id") or "").strip(),
            str(row.get("game_date") or "").strip(),
            str(row.get("source_projection_id") or "").strip(),
            str(row.get("market") or "").strip(),
            _line_key(row.get("line")),
            str(row.get("tier") or "STANDARD").strip().upper() or "STANDARD",
        ]
    )


def _line_key(value: Any) -> str:
    parsed = _float(value, 0.0)
    return f"{parsed:.4f}".rstrip("0").rstrip(".")


def _line_bucket(value: float) -> str:
    if value <= 0:
        return "line_unknown"
    if value < 0.75:
        return "line_0_0.5"
    if value < 1.75:
        return "line_1_1.5"
    if value < 2.75:
        return "line_2_2.5"
    if value < 4.75:
        return "line_3_4.5"
    if value < 7.75:
        return "line_5_7.5"
    if value < 12.75:
        return "line_8_12.5"
    if value < 25:
        return "line_13_24.5"
    return "line_25_plus"


def _artifact_path(artifact_path: Path, raw: Any, fallback_name: str) -> Path:
    if raw:
        path = Path(str(raw))
        if not path.is_absolute():
            path = (artifact_path.parent / path).resolve()
        if path.exists():
            return path
    fallback = artifact_path.parent / fallback_name
    if fallback.exists():
        return fallback
    raise FileNotFoundError(f"Missing {fallback_name} for {artifact_path}")


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


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _mean(values: Any) -> float:
    items = [float(value) for value in values]
    return sum(items) / len(items) if items else 0.0


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "over", "available"}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


if __name__ == "__main__":
    raise SystemExit(main())
