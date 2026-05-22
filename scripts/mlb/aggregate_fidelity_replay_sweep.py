"""Aggregate strict-fidelity MLB replay sweep artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from mlb.runtime.source_contract import enforce_corpus_source_contracts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        default="data/mlb/eval/corpus_replay_20260426_20260515_fidelity_v1",
    )
    args = parser.parse_args()
    input_dir = Path(args.input_dir)
    enforce_corpus_source_contracts(input_dir, root=Path.cwd())
    members = []
    market_accumulator: dict[str, dict[str, float]] = {}
    for eval_path in sorted(input_dir.glob("replay_single_*.eval.json")):
        run_id = eval_path.name.removesuffix(".eval.json")
        run_path = input_dir / f"{run_id}.run.json"
        if not run_path.exists():
            continue
        run_payload = _load_json(run_path)
        eval_payload = _load_json(eval_path)
        member = _member_summary(run_payload, eval_payload, run_path=run_path, eval_path=eval_path)
        members.append(member)
        for market, summary in (eval_payload.get("market_summary") or {}).items():
            metric_count = float(summary.get("metric_count") or 0)
            if metric_count <= 0:
                continue
            bucket = market_accumulator.setdefault(
                market,
                {"metric_count": 0.0, "win_rate": 0.0, "brier": 0.0, "logloss": 0.0},
            )
            bucket["metric_count"] += metric_count
            bucket["win_rate"] += float(summary.get("win_rate") or 0.0) * metric_count
            bucket["brier"] += float(summary.get("brier") or 0.0) * metric_count
            bucket["logloss"] += float(summary.get("logloss") or 0.0) * metric_count

    total_metric = sum(int(member["metric_count"]) for member in members)
    total_settled = sum(int(member["settled_count"]) for member in members)
    total_scored = sum(int(member["scored_count"]) for member in members)
    aggregate = {
        "corpus_id": input_dir.name,
        "run_mode": "replay_corpus",
        "replay_type": "corpus",
        "member_count": len(members),
        "total_scored_count": total_scored,
        "total_settled_count": total_settled,
        "total_metric_count": total_metric,
        "weighted_win_rate": _weighted(members, "win_rate", "metric_count"),
        "weighted_brier": _weighted(members, "brier", "metric_count"),
        "weighted_logloss": _weighted(members, "logloss", "metric_count"),
        "kernel_versions": _counts(member["kernel_version"] for member in members),
        "simulation_kernel_versions": _counts(member["simulation_kernel_version"] for member in members),
        "calibration_versions": _counts(member["calibration_version"] for member in members),
        "config_versions": _counts(member["config_version"] for member in members),
        "config_hashes": _counts(member["config_hash"] for member in members),
        "slip_builder_versions": _counts(member["slip_builder_version"] for member in members),
        "context_coverage_mean": {
            "market": _mean(member["market_context_available"] for member in members),
            "lineup": _mean(member["lineup_context_available"] for member in members),
            "probable_pitcher": _mean(member["probable_pitcher_context_available"] for member in members),
            "advanced": _mean(member["advanced_context_available"] for member in members),
            "roster": _mean(member["roster_context_available"] for member in members),
            "player_history": _mean(member["player_history_context_available"] for member in members),
        },
        "best_brier_dates": sorted(
            (member for member in members if member["brier"] is not None),
            key=lambda item: item["brier"],
        )[:5],
        "worst_brier_dates": sorted(
            (member for member in members if member["brier"] is not None),
            key=lambda item: item["brier"],
            reverse=True,
        )[:5],
        "market_summary": _market_summary(market_accumulator),
        "members": members,
    }

    summary_path = input_dir / "aggregate_summary.json"
    csv_path = input_dir / "aggregate_members.csv"
    summary_path.write_text(json.dumps(aggregate, indent=2, sort_keys=True), encoding="utf-8")
    _write_member_csv(csv_path, members)
    print(json.dumps({"summary_path": str(summary_path), "csv_path": str(csv_path), **aggregate}, indent=2, sort_keys=True))
    return 0


def _load_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return json.loads(raw.decode(encoding))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return json.loads(raw.decode("utf-8", errors="replace"))


def _member_summary(run_payload: dict[str, Any], eval_payload: dict[str, Any], *, run_path: Path, eval_path: Path) -> dict[str, Any]:
    feature_completeness = ((run_payload.get("features") or {}).get("source_completeness") or {})
    kernel_contract = ((run_payload.get("score") or {}).get("kernel_contract") or {})
    calibration_manifest = run_payload.get("parameter_calibration") or {}
    config_manifest = run_payload.get("mlb_config") or {}
    slips_manifest = run_payload.get("slips") or {}
    calibration_version = str(
        calibration_manifest.get("calibration_version")
        or _calibration_from_probability_paths(eval_payload.get("probability_path_counts") or {})
        or kernel_contract.get("calibration_version")
        or ""
    )
    return {
        "date": str(run_payload.get("game_date_filter") or ",".join(eval_payload.get("dates") or [])),
        "run_id": str(run_payload.get("run_id") or eval_payload.get("run_id") or run_path.stem),
        "board_count": int(((run_payload.get("engine_board") or {}).get("row_count") or 0)),
        "scored_count": int(((run_payload.get("score") or {}).get("row_count") or 0)),
        "settled_count": int(eval_payload.get("settled_count") or 0),
        "metric_count": int(eval_payload.get("metric_count") or 0),
        "win_rate": _optional_float(eval_payload.get("win_rate")),
        "brier": _optional_float(eval_payload.get("brier")),
        "logloss": _optional_float(eval_payload.get("logloss")),
        "market_context_available": _optional_float(feature_completeness.get("external_market_context_available")),
        "lineup_context_available": _optional_float(feature_completeness.get("lineup_context_available")),
        "probable_pitcher_context_available": _optional_float(
            feature_completeness.get("probable_pitcher_context_available")
        ),
        "advanced_context_available": _optional_float(feature_completeness.get("advanced_context_available")),
        "roster_context_available": _optional_float(feature_completeness.get("roster_context_available")),
        "player_history_context_available": _optional_float(feature_completeness.get("player_history_context_available")),
        "kernel_version": str(kernel_contract.get("kernel_version") or ""),
        "simulation_kernel_version": str(kernel_contract.get("simulation_kernel_version") or ""),
        "calibration_version": calibration_version,
        "config_version": str(config_manifest.get("config_version") or run_payload.get("mlb_config_version") or ""),
        "config_hash": str(config_manifest.get("sha256") or run_payload.get("mlb_config_hash") or ""),
        "slip_builder_version": str(
            slips_manifest.get("selection_model_version")
            or (slips_manifest.get("mlb_config") or {}).get("active_slip_builder_version")
            or ""
        ),
        "run_log": str(run_path),
        "eval_log": str(eval_path),
    }


def _calibration_from_probability_paths(paths: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for path, count in paths.items():
        parts = str(path or "").split("|")
        if len(parts) < 4:
            continue
        version = parts[-1]
        counts[version] = counts.get(version, 0) + int(count or 0)
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda item: item[1], reverse=True)[0][0]


def _market_summary(accumulator: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    summary = {}
    for market, values in sorted(accumulator.items()):
        count = values["metric_count"]
        if count <= 0:
            continue
        summary[market] = {
            "metric_count": int(count),
            "win_rate": round(values["win_rate"] / count, 6),
            "brier": round(values["brier"] / count, 6),
            "logloss": round(values["logloss"] / count, 6),
        }
    return summary


def _write_member_csv(path: Path, members: list[dict[str, Any]]) -> None:
    if not members:
        path.write_text("", encoding="utf-8")
        return
    columns = list(members[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(members)


def _weighted(rows: list[dict[str, Any]], value_key: str, weight_key: str) -> float | None:
    total_weight = 0.0
    total_value = 0.0
    for row in rows:
        value = _optional_float(row.get(value_key))
        weight = _optional_float(row.get(weight_key)) or 0.0
        if value is None or weight <= 0:
            continue
        total_weight += weight
        total_value += value * weight
    if total_weight <= 0:
        return None
    return round(total_value / total_weight, 6)


def _mean(values) -> float | None:
    collected = [value for value in (_optional_float(value) for value in values) if value is not None]
    if not collected:
        return None
    return round(sum(collected) / len(collected), 6)


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
