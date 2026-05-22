"""Audit MLB replay prop segments for builder tuning.

The output is descriptive only. It does not change tiers or builder choices; it gives
the selector a reproducible view of which prop identifiers, tier/side segments, and
context signals are actually carrying replay hit rate.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PITCHER_MARKETS = {
    "earned_runs_allowed",
    "first_inning_runs_allowed",
    "first_inning_walks_allowed",
    "hits_allowed",
    "pitcher_fantasy_score",
    "pitcher_strikeouts",
    "pitcher_strikeouts_combo",
    "pitches_thrown",
    "pitching_outs",
    "walks_allowed",
}

PROP_MARKET_COLUMNS = (
    "prop_identifier",
    "market",
    "settled_count",
    "win_count",
    "loss_count",
    "push_count",
    "win_rate",
    "avg_model_probability",
    "calibration_gap",
    "brier",
    "logloss",
    "avg_line",
    "avg_projected_opportunity",
    "market_context_available_rate",
    "lineup_context_available_rate",
    "player_history_context_available_rate",
    "batter_lineup_context_available_rate",
    "batter_history_context_available_rate",
    "pitcher_prop_context_available_rate",
    "role_context_available_rate",
    "advanced_context_available_rate",
    "bettingpros_context_available_rate",
    "bettingpros_recommended_side_match_rate",
    "avg_bettingpros_side_rate",
    "avg_stability_score",
    "avg_fragility_score",
    "most_common_loss_flags",
)

SEGMENT_COLUMNS = (
    "prop_identifier",
    "market",
    "tier",
    "side",
    "settled_count",
    "win_count",
    "loss_count",
    "push_count",
    "win_rate",
    "avg_model_probability",
    "calibration_gap",
    "brier",
    "logloss",
    "avg_line",
    "avg_projected_opportunity",
    "market_context_available_rate",
    "lineup_context_available_rate",
    "player_history_context_available_rate",
    "batter_lineup_context_available_rate",
    "batter_history_context_available_rate",
    "pitcher_prop_context_available_rate",
    "role_context_available_rate",
    "advanced_context_available_rate",
    "bettingpros_context_available_rate",
    "bettingpros_recommended_side_match_rate",
    "avg_bettingpros_side_rate",
    "avg_stability_score",
    "avg_fragility_score",
    "most_common_loss_flags",
)

BUILDER_COLUMNS = (
    "prop_identifier",
    "family",
    "tier",
    "market",
    "side",
    "leg_count",
    "settled_count",
    "win_count",
    "loss_count",
    "push_count",
    "win_rate",
    "avg_model_probability",
    "avg_slate_event_count",
)

SELECTED_LEG_COLUMNS = (
    "run_id",
    "date",
    "family",
    "label",
    "slip_result",
    "leg_result",
    "source_projection_id",
    "player_name",
    "event_id",
    "prop_identifier",
    "market",
    "context_role",
    "tier",
    "side",
    "line",
    "model_probability",
    "bettingpros_context_score",
    "bettingpros_recommended_side",
    "bettingpros_recommended_side_match",
    "bettingpros_side_rate",
    "stability_score",
    "fragility_score",
    "edge",
    "lineup_context_available",
    "player_history_context_available",
    "batter_context_applicable",
    "batter_lineup_context_available",
    "batter_history_context_available",
    "pitcher_context_applicable",
    "pitcher_prop_context_available",
    "pitcher_prop_confidence",
    "pitcher_prop_missing_context_flags",
    "role_context_available",
    "advanced_context_available",
    "external_market_context_available",
    "selection_reason",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-dir", required=True, help="Corpus replay directory with replay_single_*.eval.json files.")
    parser.add_argument("--eval-root", default="data/mlb/eval")
    parser.add_argument("--run-root", default="data/mlb/replay_runs")
    parser.add_argument("--feature-root", default="data/mlb/features/player_props")
    parser.add_argument("--matchup-root", default="data/mlb/features/matchups")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--min-market-samples", type=int, default=100)
    parser.add_argument("--min-segment-samples", type=int, default=20)
    args = parser.parse_args()

    corpus_dir = Path(args.corpus_dir)
    output_dir = Path(args.output_dir) if args.output_dir else corpus_dir / "prop_segment_audit"
    output_dir.mkdir(parents=True, exist_ok=True)

    run_ids = _run_ids(corpus_dir)
    scored_by_run = {run_id: _index_rows(Path(args.run_root) / run_id / "scored_legs.csv") for run_id in run_ids}
    features_by_run = {run_id: _index_rows(Path(args.feature_root) / run_id / "feature_table.csv") for run_id in run_ids}
    pitcher_context_by_run = {
        run_id: _index_rows(Path(args.matchup_root) / run_id / "pitcher_prop_context.csv") for run_id in run_ids
    }

    rows: list[dict[str, Any]] = []
    for run_id in run_ids:
        eval_path = Path(args.eval_root) / run_id / "eval_legs.csv"
        if not eval_path.exists():
            continue
        for row in _read_csv(eval_path):
            if str(row.get("result") or "").lower() not in {"win", "loss", "push"}:
                continue
            key = str(row.get("source_projection_id") or "").strip()
            scored = scored_by_run.get(run_id, {}).get(key, {})
            feature = features_by_run.get(run_id, {}).get(key, {})
            pitcher_context = pitcher_context_by_run.get(run_id, {}).get(key, {})
            rows.append(_combined_row(row, scored, feature, pitcher_context))

    market_summary = _summary(rows, keys=("market",))
    ranked_markets = [
        row
        for row in sorted(market_summary, key=lambda item: (-_float(item["win_rate"]), -_int(item["settled_count"]), item["market"]))
        if _int(row["settled_count"]) >= args.min_market_samples
    ]
    prop_ids = {row["market"]: index + 1 for index, row in enumerate(ranked_markets)}

    market_rows = [_with_prop_id(row, prop_ids) for row in ranked_markets]
    segment_rows = [
        _with_prop_id(row, prop_ids)
        for row in sorted(
            _summary(rows, keys=("market", "tier", "side")),
            key=lambda item: (
                _int(prop_ids.get(item["market"], 9999)),
                item["market"],
                item["tier"],
                item["side"],
            ),
        )
        if _int(row["settled_count"]) >= args.min_segment_samples
    ]
    builder_rows = _builder_rows(corpus_dir, prop_ids)
    selected_leg_rows = _selected_leg_rows(
        run_ids=run_ids,
        eval_root=Path(args.eval_root),
        run_root=Path(args.run_root),
        feature_root=Path(args.feature_root),
        matchup_root=Path(args.matchup_root),
        prop_ids=prop_ids,
    )

    _write_csv(output_dir / "prop_market_rankings.csv", market_rows, PROP_MARKET_COLUMNS)
    _write_csv(output_dir / "prop_segment_audit.csv", segment_rows, SEGMENT_COLUMNS)
    _write_csv(output_dir / "builder_selected_prop_audit.csv", builder_rows, BUILDER_COLUMNS)
    _write_csv(output_dir / "builder_selected_leg_reasons.csv", selected_leg_rows, SELECTED_LEG_COLUMNS)
    manifest = {
        "schema_version": "mlb_prop_segment_audit_v2",
        "corpus_dir": str(corpus_dir),
        "run_count": len(run_ids),
        "settled_leg_count": len(rows),
        "min_market_samples": args.min_market_samples,
        "min_segment_samples": args.min_segment_samples,
        "outputs": {
            "prop_market_rankings": str(output_dir / "prop_market_rankings.csv"),
            "prop_segment_audit": str(output_dir / "prop_segment_audit.csv"),
            "builder_selected_prop_audit": str(output_dir / "builder_selected_prop_audit.csv"),
            "builder_selected_leg_reasons": str(output_dir / "builder_selected_leg_reasons.csv"),
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def _run_ids(corpus_dir: Path) -> list[str]:
    return [path.name.removesuffix(".eval.json") for path in sorted(corpus_dir.glob("replay_single_*.eval.json"))]


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _index_rows(path: Path) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("source_projection_id") or "").strip(): row
        for row in _read_csv(path)
        if str(row.get("source_projection_id") or "").strip()
    }


def _combined_row(
    eval_row: dict[str, Any],
    scored_row: dict[str, Any],
    feature_row: dict[str, Any],
    pitcher_context_row: dict[str, Any],
) -> dict[str, Any]:
    row = dict(feature_row)
    row.update({key: value for key, value in scored_row.items() if value not in ("", None)})
    row.update({key: value for key, value in eval_row.items() if value not in ("", None)})
    _add_role_context(row, pitcher_context_row)
    row["market_context_available"] = _truthy(row.get("market_context_available")) or _truthy(
        row.get("external_market_context_available")
    )
    side = str(row.get("side") or "").lower()
    row["bettingpros_context_available"] = _truthy(row.get("external_market_context_available")) or any(
        str(row.get(field) or "").strip()
        for field in (
            "bettingpros_recommended_side",
            "bettingpros_projection_diff",
            "bettingpros_last_5_over_rate",
            "bettingpros_last_5_under_rate",
        )
    )
    row["bettingpros_recommended_side_match"] = (
        str(row.get("bettingpros_recommended_side") or "").strip().lower() == side
        if side in {"over", "under"}
        else False
    )
    row["bettingpros_side_rate"] = _bettingpros_side_rate(row, side=side)
    return row


def _summary(rows: list[dict[str, Any]], *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    buckets: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[tuple(str(row.get(key) or "") for key in keys)].append(row)

    output: list[dict[str, Any]] = []
    for bucket_key, bucket_rows in sorted(buckets.items()):
        item = {key: bucket_key[index] for index, key in enumerate(keys)}
        wins = [row for row in bucket_rows if str(row.get("result") or "").lower() == "win"]
        losses = [row for row in bucket_rows if str(row.get("result") or "").lower() == "loss"]
        pushes = [row for row in bucket_rows if str(row.get("result") or "").lower() == "push"]
        count = len(bucket_rows)
        avg_probability = _mean(_float(row.get("model_probability")) for row in bucket_rows)
        win_rate = _ratio(len(wins), count)
        item.update(
            {
                "settled_count": count,
                "win_count": len(wins),
                "loss_count": len(losses),
                "push_count": len(pushes),
                "win_rate": win_rate,
                "avg_model_probability": avg_probability,
                "calibration_gap": _round(win_rate - avg_probability),
                "brier": _mean(_float(row.get("brier")) for row in bucket_rows if str(row.get("brier") or "") != ""),
                "logloss": _mean(_float(row.get("logloss")) for row in bucket_rows if str(row.get("logloss") or "") != ""),
                "avg_line": _mean(_float(row.get("line")) for row in bucket_rows),
                "avg_projected_opportunity": _mean(_float(row.get("projected_opportunity")) for row in bucket_rows),
                "market_context_available_rate": _flag_rate(bucket_rows, "market_context_available"),
                "lineup_context_available_rate": _flag_rate(bucket_rows, "lineup_context_available"),
                "player_history_context_available_rate": _flag_rate(bucket_rows, "player_history_context_available"),
                "batter_lineup_context_available_rate": _applicable_flag_rate(
                    bucket_rows, field="batter_lineup_context_available", applicable_field="batter_context_applicable"
                ),
                "batter_history_context_available_rate": _applicable_flag_rate(
                    bucket_rows, field="batter_history_context_available", applicable_field="batter_context_applicable"
                ),
                "pitcher_prop_context_available_rate": _applicable_flag_rate(
                    bucket_rows, field="pitcher_prop_context_available", applicable_field="pitcher_context_applicable"
                ),
                "role_context_available_rate": _flag_rate(bucket_rows, "role_context_available"),
                "advanced_context_available_rate": _flag_rate(bucket_rows, "advanced_context_available"),
                "bettingpros_context_available_rate": _flag_rate(bucket_rows, "bettingpros_context_available"),
                "bettingpros_recommended_side_match_rate": _flag_rate(bucket_rows, "bettingpros_recommended_side_match"),
                "avg_bettingpros_side_rate": _mean(_float(row.get("bettingpros_side_rate")) for row in bucket_rows),
                "avg_stability_score": _mean(_float(row.get("stability_score")) for row in bucket_rows),
                "avg_fragility_score": _mean(_float(row.get("fragility_score")) for row in bucket_rows),
                "most_common_loss_flags": _common_loss_flags(losses),
            }
        )
        output.append(item)
    return output


def _builder_rows(corpus_dir: Path, prop_ids: dict[str, int]) -> list[dict[str, Any]]:
    path = corpus_dir / "slip_builder_leg_segment_summary.csv"
    rows = _read_csv(path)
    output = []
    for row in rows:
        market = str(row.get("market") or "")
        item = {key: row.get(key, "") for key in BUILDER_COLUMNS if key != "prop_identifier"}
        item["prop_identifier"] = prop_ids.get(market, 0)
        output.append(item)
    return sorted(output, key=lambda item: (int(item["prop_identifier"] or 9999), item["family"], item["tier"], item["side"]))


def _selected_leg_rows(
    *,
    run_ids: list[str],
    eval_root: Path,
    run_root: Path,
    feature_root: Path,
    matchup_root: Path,
    prop_ids: dict[str, int],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for run_id in run_ids:
        scored = _index_rows(run_root / run_id / "scored_legs.csv")
        features = _index_rows(feature_root / run_id / "feature_table.csv")
        pitcher_context = _index_rows(matchup_root / run_id / "pitcher_prop_context.csv")
        for slip in _read_csv(eval_root / run_id / "eval_slips.csv"):
            for leg in _parse_json_rows(slip.get("leg_results")):
                result = str(leg.get("result") or "").lower()
                if result not in {"win", "loss", "push"}:
                    continue
                projection_id = str(leg.get("source_projection_id") or "").strip()
                row: dict[str, Any] = {}
                row.update(features.get(projection_id, {}))
                row.update(scored.get(projection_id, {}))
                row.update(leg)
                _add_role_context(row, pitcher_context.get(projection_id, {}))
                market = str(row.get("market") or "")
                side = str(row.get("side") or "").lower()
                recommended_side = str(row.get("bettingpros_recommended_side") or "").strip().lower()
                item = {
                    "run_id": run_id,
                    "date": _date_from_run_id(run_id),
                    "family": str(slip.get("family") or ""),
                    "label": str(slip.get("label") or ""),
                    "slip_result": str(slip.get("result") or ""),
                    "leg_result": result,
                    "source_projection_id": projection_id,
                    "player_name": str(row.get("player_name") or ""),
                    "event_id": str(row.get("event_id") or ""),
                    "prop_identifier": prop_ids.get(market, 0),
                    "market": market,
                    "context_role": str(row.get("context_role") or ""),
                    "tier": str(row.get("tier") or ""),
                    "side": side,
                    "line": _float(row.get("line")),
                    "model_probability": _float(row.get("model_probability")),
                    "bettingpros_context_score": _bettingpros_context_score(row, side=side),
                    "bettingpros_recommended_side": recommended_side,
                    "bettingpros_recommended_side_match": int(bool(recommended_side) and recommended_side == side),
                    "bettingpros_side_rate": _bettingpros_side_rate(row, side=side),
                    "stability_score": _float(row.get("stability_score")),
                    "fragility_score": _float(row.get("fragility_score")),
                    "edge": _float(row.get("edge")),
                    "lineup_context_available": int(_truthy(row.get("lineup_context_available"))),
                    "player_history_context_available": int(_truthy(row.get("player_history_context_available"))),
                    "batter_context_applicable": int(_truthy(row.get("batter_context_applicable"))),
                    "batter_lineup_context_available": int(_truthy(row.get("batter_lineup_context_available"))),
                    "batter_history_context_available": int(_truthy(row.get("batter_history_context_available"))),
                    "pitcher_context_applicable": int(_truthy(row.get("pitcher_context_applicable"))),
                    "pitcher_prop_context_available": int(_truthy(row.get("pitcher_prop_context_available"))),
                    "pitcher_prop_confidence": _float(row.get("pitcher_prop_confidence")),
                    "pitcher_prop_missing_context_flags": json.dumps(_parse_flags(row.get("pitcher_prop_missing_context_flags"))),
                    "role_context_available": int(_truthy(row.get("role_context_available"))),
                    "advanced_context_available": int(_truthy(row.get("advanced_context_available"))),
                    "external_market_context_available": int(_truthy(row.get("external_market_context_available"))),
                }
                item["selection_reason"] = _selection_reason(item)
                output.append(item)
    return sorted(
        output,
        key=lambda item: (
            item["date"],
            item["family"],
            item["label"],
            0 if item["leg_result"] == "win" else 1,
            -float(item["model_probability"]),
        ),
    )


def _selection_reason(row: dict[str, Any]) -> str:
    reasons = []
    probability = _float(row.get("model_probability"))
    if probability >= 0.75:
        reasons.append("elite_model_probability")
    elif probability >= 0.65:
        reasons.append("strong_model_probability")
    elif probability >= 0.55:
        reasons.append("playable_model_probability")
    tier = str(row.get("tier") or "").upper()
    side = str(row.get("side") or "").lower()
    if tier in {"GOBLIN", "DEMON"} and side == "over":
        reasons.append("playable_alternate_over")
    if _truthy(row.get("batter_context_applicable")):
        if _truthy(row.get("batter_lineup_context_available")):
            reasons.append("batter_lineup_context_available")
        if _truthy(row.get("batter_history_context_available")):
            reasons.append("batter_history_context_available")
    if _truthy(row.get("pitcher_context_applicable")) and _truthy(row.get("pitcher_prop_context_available")):
        reasons.append("pitcher_prop_context_available")
    if _truthy(row.get("role_context_available")):
        reasons.append("role_context_available")
    if _truthy(row.get("advanced_context_available")):
        reasons.append("advanced_context_available")
    if _truthy(row.get("external_market_context_available")):
        reasons.append("bettingpros_context_available")
    if _float(row.get("edge")) > 0.05:
        reasons.append("positive_edge")
    if _float(row.get("bettingpros_context_score")) >= 0.56:
        reasons.append("bettingpros_directional_support")
    if _truthy(row.get("bettingpros_recommended_side_match")):
        reasons.append("bettingpros_recommended_side_match")
    return "|".join(reasons)


def _add_role_context(row: dict[str, Any], pitcher_context_row: dict[str, Any]) -> None:
    market = str(row.get("market") or "").strip().lower()
    market_group = str(row.get("market_group") or "").strip().lower()
    is_pitcher = market in PITCHER_MARKETS or market_group == "pitcher"
    row["context_role"] = "pitcher" if is_pitcher else "batter"
    row["batter_context_applicable"] = not is_pitcher
    row["pitcher_context_applicable"] = is_pitcher

    batter_lineup = _truthy(row.get("lineup_context_available"))
    batter_history = _truthy(row.get("player_history_context_available"))
    row["batter_lineup_context_available"] = bool(not is_pitcher and batter_lineup)
    row["batter_history_context_available"] = bool(not is_pitcher and batter_history)

    pitcher_flags = _parse_flags(pitcher_context_row.get("missing_context_flags"))
    pitcher_available = bool(pitcher_context_row) and "missing_pitcher_prop_context" not in set(pitcher_flags)
    row["pitcher_prop_context_available"] = bool(is_pitcher and pitcher_available)
    row["pitcher_prop_confidence"] = pitcher_context_row.get("pitcher_prop_confidence", "")
    row["pitcher_prop_missing_context_flags"] = json.dumps(pitcher_flags)

    if is_pitcher:
        row["role_context_available"] = bool(pitcher_available)
    else:
        row["role_context_available"] = bool(batter_history and batter_lineup)


def _parse_json_rows(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return [row for row in parsed if isinstance(row, dict)] if isinstance(parsed, list) else []


def _date_from_run_id(run_id: str) -> str:
    for part in run_id.split("_"):
        if len(part) == 8 and part.isdigit():
            return f"{part[:4]}-{part[4:6]}-{part[6:]}"
    return ""


def _with_prop_id(row: dict[str, Any], prop_ids: dict[str, int]) -> dict[str, Any]:
    item = dict(row)
    item["prop_identifier"] = prop_ids.get(str(row.get("market") or ""), 0)
    return item


def _bettingpros_side_rate(row: dict[str, Any], *, side: str) -> float:
    prefix = "over" if side == "over" else "under"
    values = [
        _rate(row.get(f"bettingpros_last_5_{prefix}_rate")),
        _rate(row.get(f"bettingpros_last_10_{prefix}_rate")),
        _rate(row.get(f"bettingpros_last_20_{prefix}_rate")),
        _rate(row.get(f"bettingpros_season_{prefix}_rate")),
    ]
    values = [value for value in values if value > 0]
    return _mean(values) if values else 0.0


def _bettingpros_context_score(row: dict[str, Any], *, side: str) -> float:
    if side not in {"over", "under"}:
        return 0.5
    score = 0.5
    recommended_side = str(row.get("bettingpros_recommended_side") or "").strip().lower()
    if recommended_side in {"over", "under"}:
        score += 0.08 if recommended_side == side else -0.05
    projection_diff = _float(row.get("bettingpros_projection_diff"))
    if projection_diff:
        direction = 1.0 if side == "over" else -1.0
        score += 0.06 * max(-1.0, min(1.0, direction * projection_diff))
    side_rate = _bettingpros_side_rate(row, side=side)
    if side_rate:
        score += 0.18 * max(-0.5, min(0.5, side_rate - 0.5))
    streak = _float(row.get("bettingpros_streak"))
    streak_type = str(row.get("bettingpros_streak_type") or "").strip().lower()
    if streak and streak_type:
        if side in streak_type:
            score += min(0.04, 0.006 * abs(streak))
        elif "over" in streak_type or "under" in streak_type:
            score -= min(0.03, 0.004 * abs(streak))
    return _round(max(0.0, min(1.0, score)))


def _common_loss_flags(losses: list[dict[str, Any]]) -> str:
    counter: Counter[str] = Counter()
    for row in losses:
        for flag in _parse_flags(row.get("flags")):
            counter[flag] += 1
    return json.dumps(counter.most_common(8))


def _parse_flags(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _flag_rate(rows: list[dict[str, Any]], field: str) -> float:
    return _ratio(sum(1 for row in rows if _truthy(row.get(field))), len(rows))


def _applicable_flag_rate(rows: list[dict[str, Any]], *, field: str, applicable_field: str) -> float:
    applicable = [row for row in rows if _truthy(row.get(applicable_field))]
    return _flag_rate(applicable, field) if applicable else 0.0


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if parsed == parsed else 0.0


def _rate(value: Any) -> float:
    parsed = _float(value)
    if parsed > 1.0:
        parsed /= 100.0
    return max(0.0, min(1.0, parsed))


def _ratio(numerator: float, denominator: float) -> float:
    return _round(float(numerator) / float(denominator)) if denominator else 0.0


def _mean(values) -> float:
    clean = [float(value) for value in values if value is not None]
    return _round(sum(clean) / len(clean)) if clean else 0.0


def _round(value: float) -> float:
    return round(float(value), 6)


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
