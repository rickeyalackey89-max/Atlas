"""MLB scoring engine boundary."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

from mlb.contracts.engine import BETTINGPROS_CONTEXT_FIELDS, EngineBoardRow, ScoredLeg
from mlb.modeling.probability import (
    CALIBRATION_VERSION,
    KERNEL_VERSION,
    METHOD,
    MODEL_VERSION,
    probability_input_from_engine_row,
    score_probability,
)
from mlb.modeling.qmc import SIMULATION_KERNEL_VERSION
from mlb.runtime.paths import ensure_mlb_dirs, output_runs_dir

SCORED_LEG_COLUMNS = (
    "run_id",
    "source_run_id",
    "snapshot_id",
    "source_projection_id",
    "event_id",
    "game_date",
    "start_time_utc",
    "player_id",
    "player_name",
    "player_team",
    "opponent",
    "market",
    "source_market",
    "line",
    "side",
    "over_probability",
    "under_probability",
    "push_probability",
    "model_probability",
    "mean_projection",
    "median_projection",
    "p10",
    "p25",
    "p75",
    "p90",
    "volatility_score",
    "fragility_score",
    "stability_score",
    "opportunity_model_version",
    "opportunity_type",
    "projected_opportunity",
    "opportunity_confidence",
    "opportunity_fragility_score",
    "lineup_score",
    "starter_matchup_score",
    "bullpen_matchup_score",
    "environment_score",
    "matchup_composite_score",
    "matchup_confidence",
    "matchup_target_shift",
    "matchup_context_available",
    "simulation_n",
    "simulation_seed",
    "simulation_kernel_version",
    "parameter_model_version",
    "calibration_version",
    "fair_price",
    "fair_decimal",
    "market_price",
    "edge",
    "confidence_tier",
    "kernel_version",
    "model_version",
    "method",
    "flags",
    *BETTINGPROS_CONTEXT_FIELDS,
    "tier",
    "status",
    "is_live",
    "is_combo",
    "pulled_at_utc",
)


def score_engine_board(
    *,
    engine_board_path: Path | None = None,
    parameter_table_path: Path | None = None,
    feature_table_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    run_mode: str = "replay_single",
) -> dict[str, Any]:
    """Score an engine-board JSON artifact and write scored-leg outputs."""

    resolved_board_path = _resolve_engine_board_json(engine_board_path, root=root)
    paths = ensure_mlb_dirs(root or _infer_root_from_engine_board_path(resolved_board_path))
    engine_board = _load_json(resolved_board_path)
    source_run_id = str(engine_board.get("run_id") or resolved_board_path.parent.name)
    resolved_run_id = run_id or source_run_id
    rows = [
        EngineBoardRow.from_mapping(row, run_id=source_run_id)
        for row in engine_board.get("rows", [])
        if isinstance(row, dict)
    ]
    parameter_rows = _load_parameter_rows(parameter_table_path)
    feature_rows, feature_projection_rows, resolved_feature_table_path = _load_feature_rows(
        feature_table_path,
        paths=paths,
        run_ids=(resolved_run_id, source_run_id),
    )
    scored_legs = [
        score_engine_board_row(
            row,
            run_id=resolved_run_id,
            parameter_row=parameter_rows.get(_parameter_key(row)),
            feature_row=_feature_context_for_row(row, feature_rows, feature_projection_rows),
        )
        for row in rows
    ]
    parameter_match_count = sum(1 for row in rows if _parameter_key(row) in parameter_rows)
    feature_match_count = sum(
        1 for row in rows if _feature_context_for_row(row, feature_rows, feature_projection_rows)
    )
    scored_legs = sorted(
        scored_legs,
        key=lambda leg: (
            leg.game_date,
            leg.start_time_utc,
            leg.player_name,
            leg.market,
            leg.line,
            leg.side,
        ),
    )

    runs_dir = output_runs_dir(paths, run_mode)
    output_dir = runs_dir / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "scored_legs.csv"
    deduped_csv_path = output_dir / "scored_legs_deduped.csv"
    json_path = output_dir / "scored_legs.json"
    manifest_path = output_dir / "score_manifest.json"
    simulation_manifest_path = output_dir / "simulation_manifest.json"

    scored_payload = {
        "run_id": resolved_run_id,
        "source_run_id": source_run_id,
        "engine_board_path": str(resolved_board_path),
        "parameter_table_path": str(parameter_table_path.resolve()) if parameter_table_path else None,
        "feature_table_path": str(resolved_feature_table_path) if resolved_feature_table_path else None,
        "row_count": len(scored_legs),
        "scored_legs": [leg.to_mapping() for leg in scored_legs],
    }
    _write_csv(csv_path, scored_legs)
    _write_csv(deduped_csv_path, _deduped_scored_legs(scored_legs))
    json_path.write_text(json.dumps(scored_payload, indent=2, sort_keys=True), encoding="utf-8")

    manifest = _score_manifest(
        run_id=resolved_run_id,
        run_mode=run_mode,
        source_run_id=source_run_id,
        engine_board_path=resolved_board_path,
        parameter_table_path=parameter_table_path,
        feature_table_path=resolved_feature_table_path,
        parameter_match_count=parameter_match_count,
        parameter_missing_count=max(0, len(rows) - parameter_match_count),
        feature_match_count=feature_match_count,
        scored_legs=scored_legs,
        csv_path=csv_path,
        deduped_csv_path=deduped_csv_path,
        json_path=json_path,
        manifest_path=manifest_path,
        simulation_manifest_path=simulation_manifest_path,
        runs_dir=runs_dir,
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    simulation_manifest_path.write_text(
        json.dumps(_simulation_manifest(run_id=resolved_run_id, scored_legs=scored_legs), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _copy_latest(csv_path, runs_dir / "latest_scored_legs.csv")
    _copy_latest(deduped_csv_path, runs_dir / "latest_scored_legs_deduped.csv")
    _copy_latest(json_path, runs_dir / "latest_scored_legs.json")
    _copy_latest(manifest_path, runs_dir / "latest_score_manifest.json")
    _copy_latest(simulation_manifest_path, runs_dir / "latest_simulation_manifest.json")
    return manifest


def score_engine_board_row(
    row: EngineBoardRow,
    *,
    run_id: str,
    parameter_row: dict[str, Any] | None = None,
    feature_row: dict[str, Any] | None = None,
) -> ScoredLeg:
    probability = score_probability(probability_input_from_engine_row(row, parameter_row=parameter_row))
    bettingpros = _bettingpros_context(feature_row)
    return ScoredLeg(
        run_id=run_id,
        source_run_id=row.run_id,
        snapshot_id=row.snapshot_id,
        source_projection_id=row.source_projection_id,
        event_id=row.event_id,
        game_date=row.game_date,
        start_time_utc=row.start_time_utc,
        player_id=row.player_id,
        player_name=row.player_name,
        player_team=row.player_team,
        opponent=row.opponent,
        market=row.market,
        source_market=row.source_market,
        line=row.line,
        side=probability.recommended_side,
        over_probability=probability.over_probability,
        under_probability=probability.under_probability,
        push_probability=probability.push_probability,
        model_probability=probability.model_probability,
        mean_projection=probability.mean_projection,
        median_projection=probability.median_projection,
        p10=probability.p10,
        p25=probability.p25,
        p75=probability.p75,
        p90=probability.p90,
        volatility_score=probability.volatility_score,
        fragility_score=probability.fragility_score,
        stability_score=probability.stability_score,
        opportunity_model_version=probability.opportunity_model_version,
        opportunity_type=probability.opportunity_type,
        projected_opportunity=probability.projected_opportunity,
        opportunity_confidence=probability.opportunity_confidence,
        opportunity_fragility_score=probability.opportunity_fragility_score,
        lineup_score=probability.lineup_score,
        starter_matchup_score=probability.starter_matchup_score,
        bullpen_matchup_score=probability.bullpen_matchup_score,
        environment_score=probability.environment_score,
        matchup_composite_score=probability.matchup_composite_score,
        matchup_confidence=probability.matchup_confidence,
        matchup_target_shift=probability.matchup_target_shift,
        matchup_context_available=probability.matchup_context_available,
        simulation_n=probability.simulation_n,
        simulation_seed=probability.simulation_seed,
        simulation_kernel_version=probability.simulation_kernel_version,
        parameter_model_version=probability.parameter_model_version,
        calibration_version=probability.calibration_version,
        fair_price=probability.fair_american,
        fair_decimal=probability.fair_decimal,
        market_price=None,
        edge=probability.edge,
        confidence_tier=probability.confidence_tier,
        kernel_version=probability.kernel_version,
        model_version=probability.model_version,
        method=probability.method,
        flags=probability.flags,
        external_market_context_available=bettingpros["external_market_context_available"],
        market_context_source_type=bettingpros["market_context_source_type"],
        external_market_context_source=bettingpros["external_market_context_source"],
        prizepicks_line_only_market_context=bettingpros["prizepicks_line_only_market_context"],
        bettingpros_recommended_side=bettingpros["bettingpros_recommended_side"],
        bettingpros_projection_value=bettingpros["bettingpros_projection_value"],
        bettingpros_projection_probability=bettingpros["bettingpros_projection_probability"],
        bettingpros_projection_expected_value=bettingpros["bettingpros_projection_expected_value"],
        bettingpros_projection_diff=bettingpros["bettingpros_projection_diff"],
        bettingpros_streak=bettingpros["bettingpros_streak"],
        bettingpros_streak_type=bettingpros["bettingpros_streak_type"],
        bettingpros_last_5_over_rate=bettingpros["bettingpros_last_5_over_rate"],
        bettingpros_last_5_under_rate=bettingpros["bettingpros_last_5_under_rate"],
        bettingpros_last_10_over_rate=bettingpros["bettingpros_last_10_over_rate"],
        bettingpros_last_10_under_rate=bettingpros["bettingpros_last_10_under_rate"],
        bettingpros_last_20_over_rate=bettingpros["bettingpros_last_20_over_rate"],
        bettingpros_last_20_under_rate=bettingpros["bettingpros_last_20_under_rate"],
        bettingpros_season_over_rate=bettingpros["bettingpros_season_over_rate"],
        bettingpros_season_under_rate=bettingpros["bettingpros_season_under_rate"],
        bettingpros_prior_season_over_rate=bettingpros["bettingpros_prior_season_over_rate"],
        bettingpros_prior_season_under_rate=bettingpros["bettingpros_prior_season_under_rate"],
        tier=row.tier,
        status=row.status,
        is_live=row.is_live,
        is_combo=row.is_combo,
        pulled_at_utc=row.pulled_at_utc,
    )


def _resolve_engine_board_json(path: Path | None, *, root: Path | None = None) -> Path:
    if path is None:
        paths = ensure_mlb_dirs(root)
        candidate = paths.staged / "engine_board" / "latest.json"
    elif path.is_dir():
        candidate = path / "engine_board.json"
    elif path.name.endswith("_manifest.json") or path.name == "latest_manifest.json":
        manifest = _load_json(path)
        candidate = Path(str(manifest["json_path"]))
    else:
        candidate = path

    if not candidate.exists():
        raise FileNotFoundError(f"Engine board JSON not found: {candidate}")
    return candidate.resolve()


def _infer_root_from_engine_board_path(path: Path) -> Path | None:
    parts = path.parts
    marker = ("data", "mlb", "staged", "engine_board")
    for index in range(0, len(parts) - len(marker) + 1):
        if tuple(parts[index : index + len(marker)]) == marker:
            return Path(*parts[:index])
    return None


def _score_manifest(
    *,
    run_id: str,
    run_mode: str,
    source_run_id: str,
    engine_board_path: Path,
    parameter_table_path: Path | None,
    feature_table_path: Path | None,
    parameter_match_count: int,
    parameter_missing_count: int,
    feature_match_count: int,
    scored_legs: list[ScoredLeg],
    csv_path: Path,
    deduped_csv_path: Path,
    json_path: Path,
    manifest_path: Path,
    simulation_manifest_path: Path,
    runs_dir: Path,
) -> dict[str, Any]:
    probabilities = [leg.model_probability for leg in scored_legs]
    sides = _counts(leg.side for leg in scored_legs)
    confidence = _counts(leg.confidence_tier for leg in scored_legs)
    markets = _counts(leg.market for leg in scored_legs)
    calibration_versions = _calibration_version_counts(scored_legs)
    return {
        "run_id": run_id,
        "run_mode": run_mode,
        "source_run_id": source_run_id,
        "engine_board_path": str(engine_board_path),
        "parameter_table_path": str(parameter_table_path.resolve()) if parameter_table_path else None,
        "feature_table_path": str(feature_table_path.resolve()) if feature_table_path else None,
        "parameter_row_match_count": parameter_match_count,
        "parameter_row_missing_count": parameter_missing_count,
        "feature_row_match_count": feature_match_count,
        "feature_row_missing_count": max(0, len(scored_legs) - feature_match_count),
        "row_count": len(scored_legs),
        "model_probability_min": min(probabilities) if probabilities else None,
        "model_probability_max": max(probabilities) if probabilities else None,
        "kernel_contract": _kernel_contract(scored_legs),
        "calibration_versions": calibration_versions,
        "side_counts": sides,
        "confidence_tier_counts": confidence,
        "market_counts": markets,
        "csv_path": str(csv_path),
        "deduped_csv_path": str(deduped_csv_path),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
        "simulation_manifest_path": str(simulation_manifest_path),
        "latest_csv_path": str(runs_dir / "latest_scored_legs.csv"),
        "latest_deduped_csv_path": str(runs_dir / "latest_scored_legs_deduped.csv"),
        "latest_json_path": str(runs_dir / "latest_scored_legs.json"),
        "latest_manifest_path": str(runs_dir / "latest_score_manifest.json"),
        "latest_simulation_manifest_path": str(runs_dir / "latest_simulation_manifest.json"),
        "columns": list(SCORED_LEG_COLUMNS),
    }


def _simulation_manifest(*, run_id: str, scored_legs: list[ScoredLeg]) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "row_count": len(scored_legs),
        "kernel_contract": _kernel_contract(scored_legs),
        "simulation_kernel_versions": _counts(leg.simulation_kernel_version for leg in scored_legs),
        "parameter_model_versions": _counts(leg.parameter_model_version for leg in scored_legs),
        "calibration_versions": _calibration_version_counts(scored_legs),
        "opportunity_model_versions": _counts(leg.opportunity_model_version for leg in scored_legs),
        "opportunity_types": _counts(leg.opportunity_type for leg in scored_legs),
        "simulation_n": _counts(str(leg.simulation_n) for leg in scored_legs),
        "distribution_count": _counts(_flag_value(leg.flags, "distribution_") for leg in scored_legs),
        "seed_count": len({leg.simulation_seed for leg in scored_legs}),
        "volatility_mean": _mean(leg.volatility_score for leg in scored_legs),
        "fragility_mean": _mean(leg.fragility_score for leg in scored_legs),
        "stability_mean": _mean(leg.stability_score for leg in scored_legs),
        "projected_opportunity_mean": _mean(leg.projected_opportunity for leg in scored_legs),
        "opportunity_confidence_mean": _mean(leg.opportunity_confidence for leg in scored_legs),
        "opportunity_fragility_mean": _mean(leg.opportunity_fragility_score for leg in scored_legs),
    }


def _kernel_contract(scored_legs: list[ScoredLeg] | None = None) -> dict[str, Any]:
    calibration_versions = _calibration_version_counts(scored_legs or [])
    return {
        "kernel_version": KERNEL_VERSION,
        "simulation_kernel_version": SIMULATION_KERNEL_VERSION,
        "model_version": MODEL_VERSION,
        "method": METHOD,
        "calibration_version": _active_calibration_version(calibration_versions),
        "calibration_versions": calibration_versions,
    }


def _calibration_version_counts(scored_legs: list[ScoredLeg]) -> dict[str, int]:
    return _counts((leg.calibration_version or CALIBRATION_VERSION) for leg in scored_legs)


def _active_calibration_version(calibration_versions: dict[str, int]) -> str:
    versions = [version for version in calibration_versions if version]
    if not versions:
        return CALIBRATION_VERSION
    if len(versions) == 1:
        return versions[0]
    return "mixed"


def _write_csv(path: Path, scored_legs: list[ScoredLeg]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=SCORED_LEG_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for leg in scored_legs:
            row = leg.to_mapping()
            writer.writerow({column: _csv_value(row.get(column)) for column in SCORED_LEG_COLUMNS})


def _deduped_scored_legs(scored_legs: list[ScoredLeg]) -> list[ScoredLeg]:
    best_by_key: dict[tuple[str, str, str, str, str, str], ScoredLeg] = {}
    for leg in scored_legs:
        key = (
            leg.game_date,
            leg.player_id or leg.player_name.lower(),
            leg.market,
            f"{leg.line:.4f}",
            leg.side,
            leg.tier.upper(),
        )
        current = best_by_key.get(key)
        if current is None or leg.model_probability > current.model_probability:
            best_by_key[key] = leg
    return sorted(
        best_by_key.values(),
        key=lambda leg: (
            leg.game_date,
            leg.start_time_utc,
            leg.player_name,
            leg.market,
            leg.line,
            leg.side,
            leg.tier,
        ),
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_parameter_rows(path: Path | None) -> dict[tuple[str, str, str, str, str, str], dict[str, Any]]:
    if path is None:
        return {}
    payload = _load_json(path)
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        return {}
    parameters: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict):
            parameters[_parameter_key(row)] = row
    return parameters


def _load_feature_rows(
    path: Path | None,
    *,
    paths,
    run_ids: tuple[str, str],
) -> tuple[dict[tuple[str, str, str, str, str, str], dict[str, Any]], dict[str, dict[str, Any]], Path | None]:
    resolved_path = _resolve_feature_table_path(path, paths=paths, run_ids=run_ids)
    if resolved_path is None:
        return {}, {}, None
    if resolved_path.suffix.lower() == ".csv":
        with resolved_path.open("r", newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
    else:
        rows = [row for row in _load_json(resolved_path).get("rows", []) if isinstance(row, dict)]
    rows_by_key: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    rows_by_projection: dict[str, dict[str, Any]] = {}
    for row in rows:
        rows_by_key[_parameter_key(row)] = row
        projection_id = _field(row, "source_projection_id")
        if projection_id:
            rows_by_projection[projection_id] = row
    return rows_by_key, rows_by_projection, resolved_path


def _resolve_feature_table_path(path: Path | None, *, paths, run_ids: tuple[str, str]) -> Path | None:
    candidates: list[Path] = []
    if path is not None:
        candidates.append(path / "feature_table.json" if path.is_dir() else path)
    for run_id in run_ids:
        if run_id:
            candidates.extend(
                (
                    paths.features / "player_props" / run_id / "feature_table.json",
                    paths.features / "player_props" / run_id / "feature_table.csv",
                )
            )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def _feature_context_for_row(
    row: EngineBoardRow,
    rows_by_key: dict[tuple[str, str, str, str, str, str], dict[str, Any]],
    rows_by_projection: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    return rows_by_key.get(_parameter_key(row)) or rows_by_projection.get(row.source_projection_id)


def _bettingpros_context(feature_row: dict[str, Any] | None) -> dict[str, Any]:
    row = feature_row or {}
    return {
        "external_market_context_available": _to_bool(row.get("external_market_context_available")),
        "market_context_source_type": _field(row, "market_context_source_type") or (
            "external_bettingpros_mlb_props" if _to_bool(row.get("external_market_context_available")) else "prizepicks_line_only"
        ),
        "external_market_context_source": _field(row, "external_market_context_source")
        or ("bettingpros_mlb_props" if _to_bool(row.get("external_market_context_available")) else ""),
        "prizepicks_line_only_market_context": _to_bool(row.get("prizepicks_line_only_market_context"))
        or not _to_bool(row.get("external_market_context_available")),
        "bettingpros_recommended_side": _field(row, "bettingpros_recommended_side").lower(),
        "bettingpros_projection_value": _float_or_zero(row.get("bettingpros_projection_value")),
        "bettingpros_projection_probability": _float_or_zero(row.get("bettingpros_projection_probability")),
        "bettingpros_projection_expected_value": _float_or_zero(row.get("bettingpros_projection_expected_value")),
        "bettingpros_projection_diff": _float_or_zero(row.get("bettingpros_projection_diff")),
        "bettingpros_streak": _int_or_zero(row.get("bettingpros_streak")),
        "bettingpros_streak_type": _field(row, "bettingpros_streak_type").lower(),
        "bettingpros_last_5_over_rate": _float_or_zero(row.get("bettingpros_last_5_over_rate")),
        "bettingpros_last_5_under_rate": _float_or_zero(row.get("bettingpros_last_5_under_rate")),
        "bettingpros_last_10_over_rate": _float_or_zero(row.get("bettingpros_last_10_over_rate")),
        "bettingpros_last_10_under_rate": _float_or_zero(row.get("bettingpros_last_10_under_rate")),
        "bettingpros_last_20_over_rate": _float_or_zero(row.get("bettingpros_last_20_over_rate")),
        "bettingpros_last_20_under_rate": _float_or_zero(row.get("bettingpros_last_20_under_rate")),
        "bettingpros_season_over_rate": _float_or_zero(row.get("bettingpros_season_over_rate")),
        "bettingpros_season_under_rate": _float_or_zero(row.get("bettingpros_season_under_rate")),
        "bettingpros_prior_season_over_rate": _float_or_zero(row.get("bettingpros_prior_season_over_rate")),
        "bettingpros_prior_season_under_rate": _float_or_zero(row.get("bettingpros_prior_season_under_rate")),
    }


def _parameter_key(row: EngineBoardRow | dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        _field(row, "source_projection_id"),
        _field(row, "event_id"),
        _field(row, "player_id"),
        _field(row, "market"),
        _line_key(_field(row, "line")),
        _field(row, "tier").upper() or "STANDARD",
    )


def _field(row: EngineBoardRow | dict[str, Any], name: str) -> str:
    value = getattr(row, name) if isinstance(row, EngineBoardRow) else row.get(name)
    if value is None:
        return ""
    return str(value).strip()


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _float_or_zero(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if parsed == parsed and parsed not in (float("inf"), float("-inf")) else 0.0


def _int_or_zero(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _line_key(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def _copy_latest(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _mean(values) -> float | None:
    collected = [float(value) for value in values]
    if not collected:
        return None
    return round(sum(collected) / len(collected), 6)


def _flag_value(flags: tuple[str, ...], prefix: str) -> str:
    for flag in flags:
        if flag.startswith(prefix):
            return flag.removeprefix(prefix)
    return "unknown"


def _csv_value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True)
    return value
