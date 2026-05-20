"""Tune CAT residual scale maps from existing LODO predictions.

This script intentionally does not run replays and does not retrain CAT. It
uses date-held-out validation over an artifact's LODO prediction rows to test
whether global, tier, market, or tier+market residual scaling improves the
calibration wrapper.
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
DEFAULT_OUTPUT_DIR = "data/mlb/model/cat_probability_kernel_v6_23date_live_context/scale_tuning"


def main() -> int:
    parser = argparse.ArgumentParser(description="Tune MLB CAT residual scales from existing LODO rows")
    parser.add_argument("--root", default=".")
    parser.add_argument("--artifact", default=DEFAULT_ARTIFACT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--scales", default="0.40,0.45,0.50,0.55,0.60,0.65,0.70,0.75,0.80,0.85,0.90,0.95,1.00,1.05,1.10,1.15,1.20")
    parser.add_argument("--min-tier-rows", type=int, default=1000)
    parser.add_argument("--min-market-rows", type=int, default=1500)
    parser.add_argument("--min-tier-market-rows", type=int, default=900)
    parser.add_argument(
        "--min-train-improvement",
        type=float,
        default=0.00002,
        help="Segment override must beat its fallback by this Brier amount on train rows.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    artifact_path = _resolve(root, args.artifact)
    output_dir = _resolve(root, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    meta = json.loads(artifact_path.read_text(encoding="utf-8"))
    predictions_path = _predictions_path(artifact_path, meta)
    rows = _read_csv(predictions_path)
    if not rows:
        raise RuntimeError(f"No rows found in {predictions_path}")

    scales = [_float(value.strip(), None) for value in str(args.scales).split(",") if value.strip()]
    scales = [value for value in scales if value is not None]
    if not scales:
        raise RuntimeError("No valid scales supplied")

    residual_clip = _float(meta.get("residual_clip"), 0.20)
    p_lo = _float(meta.get("p_lo"), 0.03)
    p_hi = _float(meta.get("p_hi"), 0.97)
    dates = sorted({str(row.get("game_date") or "") for row in rows if row.get("game_date")})
    strategies = ["artifact", "global", "tier", "market", "tier_market"]

    fold_rows: list[dict[str, Any]] = []
    prediction_rows_by_strategy: dict[str, list[dict[str, Any]]] = {strategy: [] for strategy in strategies}
    for holdout_date in dates:
        train_rows = [row for row in rows if str(row.get("game_date") or "") != holdout_date]
        test_rows = [row for row in rows if str(row.get("game_date") or "") == holdout_date]
        fitted = {
            "artifact": {"global": _float(meta.get("residual_scale"), 0.50), "tier": {}, "market": {}, "tier_market": {}},
            "global": _fit_global(train_rows, scales, residual_clip=residual_clip, p_lo=p_lo, p_hi=p_hi),
        }
        fitted["tier"] = _fit_tier(
            train_rows,
            scales,
            fallback=fitted["global"]["global"],
            min_rows=args.min_tier_rows,
            min_train_improvement=args.min_train_improvement,
            residual_clip=residual_clip,
            p_lo=p_lo,
            p_hi=p_hi,
        )
        fitted["market"] = _fit_market(
            train_rows,
            scales,
            fallback=fitted["global"]["global"],
            min_rows=args.min_market_rows,
            min_train_improvement=args.min_train_improvement,
            residual_clip=residual_clip,
            p_lo=p_lo,
            p_hi=p_hi,
        )
        fitted["tier_market"] = _fit_tier_market(
            train_rows,
            scales,
            tier_map=fitted["tier"]["tier"],
            global_scale=fitted["global"]["global"],
            min_rows=args.min_tier_market_rows,
            min_train_improvement=args.min_train_improvement,
            residual_clip=residual_clip,
            p_lo=p_lo,
            p_hi=p_hi,
        )

        for strategy in strategies:
            predictions = _predict_rows(
                test_rows,
                fitted[strategy],
                residual_clip=residual_clip,
                p_lo=p_lo,
                p_hi=p_hi,
            )
            metric = _metrics([item["actual"] for item in predictions], [item["probability"] for item in predictions])
            fold_rows.append(
                {
                    "strategy": strategy,
                    "holdout_date": holdout_date,
                    "rows": len(test_rows),
                    "brier": metric["brier"],
                    "logloss": metric["logloss"],
                    "global_scale": fitted[strategy]["global"],
                    "tier_override_count": len(fitted[strategy].get("tier", {})),
                    "market_override_count": len(fitted[strategy].get("market", {})),
                    "tier_market_override_count": len(fitted[strategy].get("tier_market", {})),
                }
            )
            prediction_rows_by_strategy[strategy].extend(
                {
                    "strategy": strategy,
                    "game_date": str(row.get("game_date") or ""),
                    "source_projection_id": str(row.get("source_projection_id") or ""),
                    "player_name": str(row.get("player_name") or ""),
                    "market": str(row.get("market") or ""),
                    "tier": str(row.get("tier") or ""),
                    "line": str(row.get("line") or ""),
                    "actual_over": item["actual"],
                    "base_over_probability": item["base"],
                    "cat_residual": item["residual"],
                    "tuned_over_probability": item["probability"],
                    "scale_used": item["scale"],
                }
                for row, item in zip(test_rows, predictions, strict=False)
            )

    summary_rows = []
    for strategy in strategies:
        strategy_predictions = prediction_rows_by_strategy[strategy]
        labels = [_float(row.get("actual_over"), 0.0) for row in strategy_predictions]
        probabilities = [_float(row.get("tuned_over_probability"), 0.5) for row in strategy_predictions]
        metric = _metrics(labels, probabilities)
        summary_rows.append(
            {
                "strategy": strategy,
                "rows": len(strategy_predictions),
                "dates": len(dates),
                "brier": metric["brier"],
                "logloss": metric["logloss"],
                "delta_brier_vs_artifact": 0.0,
                "delta_logloss_vs_artifact": 0.0,
            }
        )

    artifact_summary = next(row for row in summary_rows if row["strategy"] == "artifact")
    for row in summary_rows:
        row["delta_brier_vs_artifact"] = round(float(row["brier"]) - float(artifact_summary["brier"]), 8)
        row["delta_logloss_vs_artifact"] = round(float(row["logloss"]) - float(artifact_summary["logloss"]), 8)
    summary_rows = sorted(summary_rows, key=lambda row: (float(row["brier"]), float(row["logloss"])))

    full_fit = {
        "global": _fit_global(rows, scales, residual_clip=residual_clip, p_lo=p_lo, p_hi=p_hi),
    }
    full_fit["tier"] = _fit_tier(
        rows,
        scales,
        fallback=full_fit["global"]["global"],
        min_rows=args.min_tier_rows,
        min_train_improvement=args.min_train_improvement,
        residual_clip=residual_clip,
        p_lo=p_lo,
        p_hi=p_hi,
    )
    full_fit["market"] = _fit_market(
        rows,
        scales,
        fallback=full_fit["global"]["global"],
        min_rows=args.min_market_rows,
        min_train_improvement=args.min_train_improvement,
        residual_clip=residual_clip,
        p_lo=p_lo,
        p_hi=p_hi,
    )
    full_fit["tier_market"] = _fit_tier_market(
        rows,
        scales,
        tier_map=full_fit["tier"]["tier"],
        global_scale=full_fit["global"]["global"],
        min_rows=args.min_tier_market_rows,
        min_train_improvement=args.min_train_improvement,
        residual_clip=residual_clip,
        p_lo=p_lo,
        p_hi=p_hi,
    )

    best_strategy = str(summary_rows[0]["strategy"])
    tuned_artifact = dict(meta)
    tuned_artifact["calibration_version"] = f"{str(meta.get('calibration_version') or meta.get('version') or artifact_path.parent.name)}_scale_tuned"
    tuned_artifact["version"] = tuned_artifact["calibration_version"]
    tuned_artifact["residual_scale_strategy"] = best_strategy
    tuned_artifact["residual_scale"] = full_fit.get(best_strategy, full_fit["global"])["global"]
    tuned_artifact["residual_scale_by_tier"] = full_fit.get(best_strategy, {}).get("tier", {})
    tuned_artifact["residual_scale_by_market"] = full_fit.get(best_strategy, {}).get("market", {})
    tuned_artifact["residual_scale_by_tier_market"] = full_fit.get(best_strategy, {}).get("tier_market", {})
    tuned_artifact["scale_tuning"] = {
        "schema_version": "mlb_cat_residual_scale_tuning_v1",
        "source_artifact_path": str(artifact_path),
        "source_predictions_path": str(predictions_path),
        "best_strategy": best_strategy,
        "date_heldout_summary": summary_rows,
        "min_tier_rows": args.min_tier_rows,
        "min_market_rows": args.min_market_rows,
        "min_tier_market_rows": args.min_tier_market_rows,
        "min_train_improvement": args.min_train_improvement,
        "scales": scales,
    }

    _write_csv(output_dir / "strategy_summary.csv", summary_rows)
    _write_csv(output_dir / "fold_summary.csv", fold_rows)
    _write_csv(output_dir / "tuned_predictions.csv", prediction_rows_by_strategy[best_strategy])
    _write_segment_summary(output_dir / "segment_summary_by_tier.csv", prediction_rows_by_strategy)
    _write_segment_summary(output_dir / "segment_summary_by_market.csv", prediction_rows_by_strategy, segment="market")
    (output_dir / "tuned_best_config.json").write_text(json.dumps(tuned_artifact, indent=2, sort_keys=True), encoding="utf-8")
    manifest = {
        "schema_version": "mlb_cat_residual_scale_tuning_v1",
        "artifact_path": str(artifact_path),
        "predictions_path": str(predictions_path),
        "output_dir": str(output_dir),
        "date_count": len(dates),
        "row_count": len(rows),
        "best_strategy": best_strategy,
        "strategy_summary": summary_rows,
        "tuned_artifact_path": str(output_dir / "tuned_best_config.json"),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def _fit_global(
    rows: list[dict[str, Any]],
    scales: list[float],
    *,
    residual_clip: float,
    p_lo: float,
    p_hi: float,
) -> dict[str, Any]:
    return {"global": _best_scale(rows, scales, residual_clip=residual_clip, p_lo=p_lo, p_hi=p_hi)}


def _fit_tier(
    rows: list[dict[str, Any]],
    scales: list[float],
    *,
    fallback: float,
    min_rows: int,
    min_train_improvement: float,
    residual_clip: float,
    p_lo: float,
    p_hi: float,
) -> dict[str, Any]:
    tier_map = _fit_segment_map(
        rows,
        scales,
        key_fn=lambda row: str(row.get("tier") or "STANDARD").upper(),
        fallback_fn=lambda _key: fallback,
        min_rows=min_rows,
        min_train_improvement=min_train_improvement,
        residual_clip=residual_clip,
        p_lo=p_lo,
        p_hi=p_hi,
    )
    return {"global": fallback, "tier": tier_map, "market": {}, "tier_market": {}}


def _fit_market(
    rows: list[dict[str, Any]],
    scales: list[float],
    *,
    fallback: float,
    min_rows: int,
    min_train_improvement: float,
    residual_clip: float,
    p_lo: float,
    p_hi: float,
) -> dict[str, Any]:
    market_map = _fit_segment_map(
        rows,
        scales,
        key_fn=lambda row: str(row.get("market") or "").strip(),
        fallback_fn=lambda _key: fallback,
        min_rows=min_rows,
        min_train_improvement=min_train_improvement,
        residual_clip=residual_clip,
        p_lo=p_lo,
        p_hi=p_hi,
    )
    return {"global": fallback, "tier": {}, "market": market_map, "tier_market": {}}


def _fit_tier_market(
    rows: list[dict[str, Any]],
    scales: list[float],
    *,
    tier_map: dict[str, float],
    global_scale: float,
    min_rows: int,
    min_train_improvement: float,
    residual_clip: float,
    p_lo: float,
    p_hi: float,
) -> dict[str, Any]:
    tier_market_map = _fit_segment_map(
        rows,
        scales,
        key_fn=lambda row: _tier_market_key(row),
        fallback_fn=lambda key: tier_map.get(key.split("|", 1)[0], global_scale),
        min_rows=min_rows,
        min_train_improvement=min_train_improvement,
        residual_clip=residual_clip,
        p_lo=p_lo,
        p_hi=p_hi,
    )
    return {"global": global_scale, "tier": tier_map, "market": {}, "tier_market": tier_market_map}


def _fit_segment_map(
    rows: list[dict[str, Any]],
    scales: list[float],
    *,
    key_fn: Any,
    fallback_fn: Any,
    min_rows: int,
    min_train_improvement: float,
    residual_clip: float,
    p_lo: float,
    p_hi: float,
) -> dict[str, float]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = str(key_fn(row) or "").strip()
        if key:
            grouped[key].append(row)
    output: dict[str, float] = {}
    for key, segment_rows in grouped.items():
        if len(segment_rows) < min_rows:
            continue
        fallback = float(fallback_fn(key))
        fallback_brier = _brier_for_scale(segment_rows, fallback, residual_clip=residual_clip, p_lo=p_lo, p_hi=p_hi)
        best = _best_scale(segment_rows, scales, residual_clip=residual_clip, p_lo=p_lo, p_hi=p_hi)
        best_brier = _brier_for_scale(segment_rows, best, residual_clip=residual_clip, p_lo=p_lo, p_hi=p_hi)
        if fallback_brier - best_brier >= min_train_improvement:
            output[key] = best
    return output


def _best_scale(
    rows: list[dict[str, Any]],
    scales: list[float],
    *,
    residual_clip: float,
    p_lo: float,
    p_hi: float,
) -> float:
    best_scale = scales[0]
    best_brier = math.inf
    best_logloss = math.inf
    for scale in scales:
        predictions = _predict_rows(
            rows,
            {"global": scale, "tier": {}, "market": {}, "tier_market": {}},
            residual_clip=residual_clip,
            p_lo=p_lo,
            p_hi=p_hi,
        )
        metric = _metrics([item["actual"] for item in predictions], [item["probability"] for item in predictions])
        if metric["brier"] < best_brier or (metric["brier"] == best_brier and metric["logloss"] < best_logloss):
            best_scale = scale
            best_brier = metric["brier"]
            best_logloss = metric["logloss"]
    return best_scale


def _brier_for_scale(
    rows: list[dict[str, Any]],
    scale: float,
    *,
    residual_clip: float,
    p_lo: float,
    p_hi: float,
) -> float:
    predictions = _predict_rows(
        rows,
        {"global": scale, "tier": {}, "market": {}, "tier_market": {}},
        residual_clip=residual_clip,
        p_lo=p_lo,
        p_hi=p_hi,
    )
    return _metrics([item["actual"] for item in predictions], [item["probability"] for item in predictions])["brier"]


def _predict_rows(
    rows: list[dict[str, Any]],
    scale_config: dict[str, Any],
    *,
    residual_clip: float,
    p_lo: float,
    p_hi: float,
) -> list[dict[str, float]]:
    output: list[dict[str, float]] = []
    for row in rows:
        base = _clamp(_float(row.get("base_over_probability"), 0.50), p_lo, p_hi)
        residual = _clamp(_float(row.get("cat_residual"), 0.0), -residual_clip, residual_clip)
        scale = _scale_for_row(row, scale_config)
        probability = _clamp(base + scale * residual, p_lo, p_hi)
        output.append(
            {
                "actual": 1.0 if _float(row.get("actual_over"), 0.0) >= 0.5 else 0.0,
                "base": base,
                "residual": residual,
                "probability": probability,
                "scale": scale,
            }
        )
    return output


def _scale_for_row(row: dict[str, Any], scale_config: dict[str, Any]) -> float:
    tier = str(row.get("tier") or "STANDARD").upper()
    market = str(row.get("market") or "").strip()
    tier_market = f"{tier}|{market}"
    if tier_market in scale_config.get("tier_market", {}):
        return float(scale_config["tier_market"][tier_market])
    if market in scale_config.get("market", {}):
        return float(scale_config["market"][market])
    if tier in scale_config.get("tier", {}):
        return float(scale_config["tier"][tier])
    return float(scale_config.get("global", 0.50))


def _write_segment_summary(
    path: Path,
    prediction_rows_by_strategy: dict[str, list[dict[str, Any]]],
    *,
    segment: str = "tier",
) -> None:
    rows: list[dict[str, Any]] = []
    for strategy, prediction_rows in prediction_rows_by_strategy.items():
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in prediction_rows:
            grouped[str(row.get(segment) or "").strip() or "(blank)"].append(row)
        for segment_value, segment_rows in sorted(grouped.items()):
            metric = _metrics(
                [_float(row.get("actual_over"), 0.0) for row in segment_rows],
                [_float(row.get("tuned_over_probability"), 0.5) for row in segment_rows],
            )
            rows.append(
                {
                    "strategy": strategy,
                    "segment": segment,
                    "segment_value": segment_value,
                    "rows": len(segment_rows),
                    "brier": metric["brier"],
                    "logloss": metric["logloss"],
                }
            )
    _write_csv(path, rows)


def _metrics(labels: list[float], probabilities: list[float]) -> dict[str, float]:
    total = len(labels)
    if total == 0:
        return {"brier": 0.0, "logloss": 0.0}
    brier = 0.0
    logloss = 0.0
    for label, probability in zip(labels, probabilities, strict=False):
        y = 1.0 if label >= 0.5 else 0.0
        p = _clamp(float(probability), 1e-6, 1.0 - 1e-6)
        brier += (p - y) ** 2
        logloss += -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
    return {"brier": round(brier / total, 8), "logloss": round(logloss / total, 8)}


def _tier_market_key(row: dict[str, Any]) -> str:
    tier = str(row.get("tier") or "STANDARD").upper()
    market = str(row.get("market") or "").strip()
    return f"{tier}|{market}"


def _predictions_path(artifact_path: Path, meta: dict[str, Any]) -> Path:
    raw = meta.get("lodo_predictions_csv")
    if raw:
        path = Path(str(raw))
        if not path.is_absolute():
            path = (artifact_path.parent / path).resolve()
        if path.exists():
            return path
    fallback = artifact_path.parent / "lodo_predictions.csv"
    if not fallback.exists():
        raise FileNotFoundError(f"Missing LODO predictions beside {artifact_path}")
    return fallback


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


def _float(value: Any, default: float | None = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        if default is None:
            raise
        return default
    if not math.isfinite(parsed):
        if default is None:
            raise ValueError(f"Non-finite float: {value}")
        return default
    return parsed


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


if __name__ == "__main__":
    raise SystemExit(main())
