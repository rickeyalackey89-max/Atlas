"""Replay-safe MLB probability calibration artifacts.

The live scorer consumes parameter tables, so calibrated models must write back
to the same parameter-table contract instead of bypassing the normal engine.
"""

from __future__ import annotations

import csv
import json
import math
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor, Pool  # type: ignore[import-untyped]
from scipy.special import expit, logit  # type: ignore[import-untyped]

from mlb.modeling.qmc import default_distribution_for_market, projection_mean_for_target
from mlb.runtime.engine_inputs import _load_json
from mlb.runtime.paths import ensure_mlb_dirs

CALIBRATION_SCHEMA_VERSION = "mlb_parameter_cat_calibration_v1"


def apply_parameter_calibration(
    *,
    parameter_table_path: Path,
    feature_table_path: Path,
    calibration_artifact_path: Path,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Apply a trained CatBoost residual model to a parameter table.

    Returns a manifest for the calibrated JSON/CSV artifacts. The original
    parameter table is left untouched so replays can prove exactly which
    uncalibrated artifact fed the calibrated variant.
    """

    paths = ensure_mlb_dirs(root)
    parameter_payload = _load_json(parameter_table_path)
    feature_payload = _load_table_payload(feature_table_path)
    calibration_artifact_path = calibration_artifact_path.resolve()
    meta = _load_json(calibration_artifact_path)
    if str(meta.get("schema_version") or "") == "mlb_cat_probability_stacker_training_v1":
        return _apply_parameter_stacker_calibration(
            parameter_table_path=parameter_table_path,
            feature_table_path=feature_table_path,
            stacker_artifact_path=calibration_artifact_path,
            stacker_meta=meta,
            root=root,
            run_id=run_id,
        )
    model_path = _resolve_model_path(meta, calibration_artifact_path)
    model = CatBoostRegressor()
    model.load_model(str(model_path))

    resolved_run_id = run_id or str(parameter_payload.get("run_id") or parameter_table_path.parent.name)
    calibration_version = str(meta.get("calibration_version") or meta.get("version") or calibration_artifact_path.stem)
    output_run_id = f"{resolved_run_id}_{_slug(calibration_version)}"
    output_dir = paths.features / "parameters" / output_run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    features = [str(item) for item in meta.get("features", [])]
    cat_features = [str(item) for item in meta.get("cat_features", [])]
    residual_clip = _float(meta.get("residual_clip"), 0.20)
    residual_scale = _float(meta.get("residual_scale"), 0.50)
    p_lo = _float(meta.get("p_lo"), 0.03)
    p_hi = _float(meta.get("p_hi"), 0.97)

    feature_index = {
        _join_key(row): row
        for row in feature_payload.get("rows", [])
        if isinstance(row, dict)
    }
    source_rows = [row for row in parameter_payload.get("rows", []) if isinstance(row, dict)]
    merged_feature_rows = []
    for row in source_rows:
        merged_feature_rows.append(_training_feature_row(row, feature_index.get(_join_key(row))))
    frame = _prep_frame(merged_feature_rows, features=features, cat_features=cat_features)
    pool = Pool(frame, cat_features=[features.index(col) for col in cat_features if col in features])
    residuals = model.predict(pool) if len(frame) else []

    calibrated_rows: list[dict[str, Any]] = []
    adjusted_count = 0
    residual_values: list[float] = []
    shift_values: list[float] = []
    for row, merged_feature_row, residual in zip(source_rows, merged_feature_rows, residuals, strict=False):
        calibrated = dict(row)
        base = _clamp(_float(row.get("target_over_probability"), 0.50), p_lo, p_hi)
        clipped = _clamp(float(residual), -residual_clip, residual_clip)
        row_residual_scale = _residual_scale_for_row(meta, merged_feature_row, residual_scale)
        scaled = row_residual_scale * clipped
        adjusted = _clamp(base + scaled, p_lo, p_hi)
        calibrated["uncalibrated_target_over_probability"] = round(base, 6)
        calibrated["target_over_probability"] = round(adjusted, 6)
        calibrated["cat_residual_raw"] = round(float(residual), 8)
        calibrated["cat_residual_clipped"] = round(clipped, 8)
        calibrated["cat_residual_scale"] = round(row_residual_scale, 6)
        calibrated["cat_residual_scaled"] = round(scaled, 8)
        calibrated["calibration_version"] = calibration_version
        calibrated["calibration_model_path"] = str(model_path)
        calibrated["calibration_artifact_path"] = str(calibration_artifact_path)
        calibrated["flags"] = _calibrated_flags(row.get("flags"), "cat_probability_calibrated")
        adjusted_count += 1
        residual_values.append(float(residual))
        shift_values.append(adjusted - base)
        calibrated_rows.append(calibrated)

    csv_path = output_dir / "parameter_table.csv"
    json_path = output_dir / "parameter_table.json"
    manifest_path = output_dir / "parameter_calibration_manifest.json"
    _write_csv(csv_path, calibrated_rows)
    json_path.write_text(
        json.dumps({"run_id": resolved_run_id, "row_count": len(calibrated_rows), "rows": calibrated_rows}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": CALIBRATION_SCHEMA_VERSION,
        "run_id": resolved_run_id,
        "output_run_id": output_run_id,
        "parameter_table_path": str(parameter_table_path),
        "feature_table_path": str(feature_table_path),
        "calibration_artifact_path": str(calibration_artifact_path),
        "model_path": str(model_path),
        "calibration_version": calibration_version,
        "row_count": len(calibrated_rows),
        "adjusted_count": adjusted_count,
        "residual_scale": residual_scale,
        "residual_scale_strategy": str(meta.get("residual_scale_strategy") or "global"),
        "residual_scale_by_tier_count": len(meta.get("residual_scale_by_tier") or {}),
        "residual_scale_by_market_count": len(meta.get("residual_scale_by_market") or {}),
        "residual_scale_by_tier_market_count": len(meta.get("residual_scale_by_tier_market") or {}),
        "residual_scale_by_market_source_type_count": len(meta.get("residual_scale_by_market_source_type") or {}),
        "residual_scale_by_line_bucket_count": len(meta.get("residual_scale_by_line_bucket") or {}),
        "residual_scale_by_market_source_count": len(meta.get("residual_scale_by_market_source") or {}),
        "residual_scale_by_tier_market_source_count": len(meta.get("residual_scale_by_tier_market_source") or {}),
        "residual_clip": residual_clip,
        "p_lo": p_lo,
        "p_hi": p_hi,
        "target_shift_mean": _mean(shift_values),
        "target_shift_min": _min(shift_values),
        "target_shift_max": _max(shift_values),
        "raw_residual_mean": _mean(residual_values),
        "features": features,
        "cat_features": cat_features,
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
        "latest_csv_path": str(paths.features / "parameters" / "latest_calibrated.csv"),
        "latest_json_path": str(paths.features / "parameters" / "latest_calibrated.json"),
        "latest_manifest_path": str(paths.features / "parameters" / "latest_calibration_manifest.json"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _copy_latest(csv_path, paths.features / "parameters" / "latest_calibrated.csv")
    _copy_latest(json_path, paths.features / "parameters" / "latest_calibrated.json")
    _copy_latest(manifest_path, paths.features / "parameters" / "latest_calibration_manifest.json")
    return manifest


def _apply_parameter_stacker_calibration(
    *,
    parameter_table_path: Path,
    feature_table_path: Path,
    stacker_artifact_path: Path,
    stacker_meta: dict[str, Any],
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Apply a base CAT residual model plus a probability stacker blend."""

    paths = ensure_mlb_dirs(root)
    parameter_payload = _load_json(parameter_table_path)
    feature_payload = _load_table_payload(feature_table_path)

    base_artifact_path = _resolve_stacker_base_artifact(stacker_meta, stacker_artifact_path)
    base_meta = _load_json(base_artifact_path)
    base_model_path = _resolve_model_path(base_meta, base_artifact_path)
    stacker_model_path = _resolve_model_path(stacker_meta, stacker_artifact_path)

    base_model = CatBoostRegressor()
    base_model.load_model(str(base_model_path))
    stacker_model = CatBoostClassifier()
    stacker_model.load_model(str(stacker_model_path))

    resolved_run_id = run_id or str(parameter_payload.get("run_id") or parameter_table_path.parent.name)
    stacker_version = str(stacker_meta.get("version") or stacker_artifact_path.stem)
    base_version = str(base_meta.get("calibration_version") or base_meta.get("version") or base_artifact_path.stem)
    output_run_id = f"{resolved_run_id}_{_slug(stacker_version)}"
    output_dir = paths.features / "parameters" / output_run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    base_features = [str(item) for item in base_meta.get("features", [])]
    base_cat_features = [str(item) for item in base_meta.get("cat_features", [])]
    stacker_features = [str(item) for item in stacker_meta.get("features", [])]
    stacker_cat_features = [str(item) for item in stacker_meta.get("cat_features", [])]

    residual_clip = _float(base_meta.get("residual_clip"), 0.20)
    residual_scale = _float(base_meta.get("residual_scale"), 0.50)
    p_lo = _float(base_meta.get("p_lo"), 0.03)
    p_hi = _float(base_meta.get("p_hi"), 0.97)
    blend_weight = _float(stacker_meta.get("blend_weight"), 0.50)

    feature_index = {
        _join_key(row): row
        for row in feature_payload.get("rows", [])
        if isinstance(row, dict)
    }
    source_rows = [row for row in parameter_payload.get("rows", []) if isinstance(row, dict)]
    merged_feature_rows = [
        _training_feature_row(row, feature_index.get(_join_key(row)))
        for row in source_rows
    ]

    base_frame = _prep_frame(merged_feature_rows, features=base_features, cat_features=base_cat_features)
    stacker_frame = _prep_frame(merged_feature_rows, features=stacker_features, cat_features=stacker_cat_features)
    base_pool = Pool(base_frame, cat_features=[base_features.index(col) for col in base_cat_features if col in base_features])
    stacker_pool = Pool(stacker_frame, cat_features=[stacker_features.index(col) for col in stacker_cat_features if col in stacker_features])
    residuals = base_model.predict(base_pool) if len(base_frame) else []
    stacker_probabilities = stacker_model.predict_proba(stacker_pool)[:, 1] if len(stacker_frame) else []

    calibrated_rows: list[dict[str, Any]] = []
    residual_values: list[float] = []
    residual_shift_values: list[float] = []
    stacker_values: list[float] = []
    stacker_shift_values: list[float] = []
    for row, merged_feature_row, residual, stacker_probability in zip(
        source_rows,
        merged_feature_rows,
        residuals,
        stacker_probabilities,
        strict=False,
    ):
        calibrated = dict(row)
        base = _clamp(_float(row.get("target_over_probability"), 0.50), p_lo, p_hi)
        clipped = _clamp(float(residual), -residual_clip, residual_clip)
        row_residual_scale = _residual_scale_for_row(base_meta, merged_feature_row, residual_scale)
        scaled = row_residual_scale * clipped
        cat_adjusted = _clamp(base + scaled, p_lo, p_hi)
        stacker_p = _clamp(float(stacker_probability), p_lo, p_hi)
        stacked = _clamp(
            float(expit((1.0 - blend_weight) * logit(cat_adjusted) + blend_weight * logit(stacker_p))),
            p_lo,
            p_hi,
        )

        calibrated["uncalibrated_target_over_probability"] = round(base, 6)
        calibrated["cat_adjusted_target_over_probability"] = round(cat_adjusted, 6)
        calibrated["probability_stacker_probability"] = round(stacker_p, 6)
        calibrated["target_over_probability"] = round(stacked, 6)
        calibrated["cat_residual_raw"] = round(float(residual), 8)
        calibrated["cat_residual_clipped"] = round(clipped, 8)
        calibrated["cat_residual_scale"] = round(row_residual_scale, 6)
        calibrated["cat_residual_scaled"] = round(scaled, 8)
        calibrated["probability_stacker_blend_weight"] = round(blend_weight, 6)
        calibrated["calibration_version"] = stacker_version
        calibrated["base_calibration_version"] = base_version
        calibrated["calibration_model_path"] = str(stacker_model_path)
        calibrated["base_calibration_model_path"] = str(base_model_path)
        calibrated["calibration_artifact_path"] = str(stacker_artifact_path)
        calibrated["base_calibration_artifact_path"] = str(base_artifact_path)
        calibrated["flags"] = _calibrated_flags(
            row.get("flags"),
            "cat_probability_calibrated",
            "cat_probability_stacked",
        )
        residual_values.append(float(residual))
        residual_shift_values.append(cat_adjusted - base)
        stacker_values.append(stacker_p)
        stacker_shift_values.append(stacked - cat_adjusted)
        calibrated_rows.append(calibrated)

    csv_path = output_dir / "parameter_table.csv"
    json_path = output_dir / "parameter_table.json"
    manifest_path = output_dir / "parameter_calibration_manifest.json"
    _write_csv(csv_path, calibrated_rows)
    json_path.write_text(
        json.dumps({"run_id": resolved_run_id, "row_count": len(calibrated_rows), "rows": calibrated_rows}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": CALIBRATION_SCHEMA_VERSION,
        "calibration_type": "cat_residual_plus_probability_stacker",
        "run_id": resolved_run_id,
        "output_run_id": output_run_id,
        "parameter_table_path": str(parameter_table_path),
        "feature_table_path": str(feature_table_path),
        "calibration_artifact_path": str(stacker_artifact_path),
        "base_calibration_artifact_path": str(base_artifact_path),
        "model_path": str(stacker_model_path),
        "base_model_path": str(base_model_path),
        "calibration_version": stacker_version,
        "base_calibration_version": base_version,
        "row_count": len(calibrated_rows),
        "adjusted_count": len(calibrated_rows),
        "residual_scale": residual_scale,
        "residual_scale_strategy": str(base_meta.get("residual_scale_strategy") or "global"),
        "residual_scale_by_tier_count": len(base_meta.get("residual_scale_by_tier") or {}),
        "residual_scale_by_market_count": len(base_meta.get("residual_scale_by_market") or {}),
        "residual_scale_by_tier_market_count": len(base_meta.get("residual_scale_by_tier_market") or {}),
        "residual_scale_by_market_source_type_count": len(base_meta.get("residual_scale_by_market_source_type") or {}),
        "residual_scale_by_line_bucket_count": len(base_meta.get("residual_scale_by_line_bucket") or {}),
        "residual_scale_by_market_source_count": len(base_meta.get("residual_scale_by_market_source") or {}),
        "residual_scale_by_tier_market_source_count": len(base_meta.get("residual_scale_by_tier_market_source") or {}),
        "residual_clip": residual_clip,
        "blend_weight": blend_weight,
        "p_lo": p_lo,
        "p_hi": p_hi,
        "cat_target_shift_mean": _mean(residual_shift_values),
        "cat_target_shift_min": _min(residual_shift_values),
        "cat_target_shift_max": _max(residual_shift_values),
        "stacker_target_shift_mean": _mean(stacker_shift_values),
        "stacker_target_shift_min": _min(stacker_shift_values),
        "stacker_target_shift_max": _max(stacker_shift_values),
        "raw_residual_mean": _mean(residual_values),
        "stacker_probability_mean": _mean(stacker_values),
        "features": stacker_features,
        "cat_features": stacker_cat_features,
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
        "latest_csv_path": str(paths.features / "parameters" / "latest_calibrated.csv"),
        "latest_json_path": str(paths.features / "parameters" / "latest_calibrated.json"),
        "latest_manifest_path": str(paths.features / "parameters" / "latest_calibration_manifest.json"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _copy_latest(csv_path, paths.features / "parameters" / "latest_calibrated.csv")
    _copy_latest(json_path, paths.features / "parameters" / "latest_calibrated.json")
    _copy_latest(manifest_path, paths.features / "parameters" / "latest_calibration_manifest.json")
    return manifest


def training_feature_row(parameter_row: dict[str, Any], feature_row: dict[str, Any] | None = None) -> dict[str, Any]:
    """Public helper shared by trainers and runtime calibration."""

    return _training_feature_row(parameter_row, feature_row)


def prepare_calibration_frame(
    rows: list[dict[str, Any]],
    *,
    features: list[str],
    cat_features: list[str],
) -> pd.DataFrame:
    """Public helper shared by trainers and runtime calibration."""

    return _prep_frame(rows, features=features, cat_features=cat_features)


def join_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """Stable row key across engine board, parameter table, features, and eval rows."""

    return _join_key(row)


def _training_feature_row(parameter_row: dict[str, Any], feature_row: dict[str, Any] | None = None) -> dict[str, Any]:
    feature_row = feature_row or {}
    market_context_source_type = str(feature_row.get("market_context_source_type") or "").strip()
    external_market_context_source = str(feature_row.get("external_market_context_source") or "").strip()
    if not market_context_source_type:
        market_context_source_type = (
            f"external_{external_market_context_source}"
            if external_market_context_source
            else ("external_market" if _bool_number(feature_row.get("external_market_context_available")) else "prizepicks_line_only")
        )
    source_flags = _market_source_flags(market_context_source_type, external_market_context_source)
    line_value = _float(parameter_row.get("line"), _float(feature_row.get("line"), 0.0))
    market = str(parameter_row.get("market") or feature_row.get("market") or "")
    distribution = str(parameter_row.get("distribution") or default_distribution_for_market(market))
    base_probability = _float(
        parameter_row.get("uncalibrated_target_over_probability"),
        _float(parameter_row.get("target_over_probability"), 0.50),
    )
    projection_mean = _projection_mean(
        market=market,
        line=line_value,
        target_over_probability=base_probability,
        distribution=distribution,
    )
    projection_delta = projection_mean - line_value
    row: dict[str, Any] = {
        "market": market,
        "source_market": str(parameter_row.get("source_market") or feature_row.get("source_market") or ""),
        "tier": str(parameter_row.get("tier") or feature_row.get("tier") or "STANDARD").upper(),
        "player_team": str(parameter_row.get("player_team") or feature_row.get("player_team") or ""),
        "opponent": str(parameter_row.get("opponent") or feature_row.get("opponent") or ""),
        "player_position": str(feature_row.get("player_position") or ""),
        "market_group": str(parameter_row.get("market_group") or feature_row.get("market_group") or ""),
        "opportunity_type": str(parameter_row.get("opportunity_type") or feature_row.get("opportunity_type") or ""),
        "distribution": distribution,
        "injury_status": str(feature_row.get("injury_status") or ""),
        "statsapi_venue_name": str(feature_row.get("statsapi_venue_name") or ""),
        "statsapi_player_position": str(feature_row.get("statsapi_player_position") or ""),
        "statsapi_bats": str(feature_row.get("statsapi_bats") or ""),
        "statsapi_throws": str(feature_row.get("statsapi_throws") or ""),
        "batter_bats": str(feature_row.get("batter_bats") or ""),
        "starter_throws": str(feature_row.get("starter_throws") or ""),
        "handedness_matchup_type": str(feature_row.get("handedness_matchup_type") or ""),
        "pitcher_starter_throws": str(feature_row.get("pitcher_starter_throws") or ""),
        "statsapi_roster_status": str(feature_row.get("statsapi_roster_status") or ""),
        "home_plate_umpire": str(feature_row.get("home_plate_umpire") or ""),
        "umpire_rating": str(feature_row.get("umpire_rating") or ""),
        "bettingpros_recommended_side": str(feature_row.get("bettingpros_recommended_side") or ""),
        "bettingpros_streak_type": str(feature_row.get("bettingpros_streak_type") or ""),
        "advanced_profile_source": str(parameter_row.get("advanced_profile_source") or feature_row.get("advanced_profile_source") or ""),
        "advanced_profile_match_type": str(parameter_row.get("advanced_profile_match_type") or feature_row.get("advanced_profile_match_type") or ""),
        "market_line_match_type": str(parameter_row.get("market_line_match_type") or ""),
        "market_context_source_type": market_context_source_type,
        "external_market_context_source": external_market_context_source,
        "line_bucket": _line_bucket(line_value),
        "base_over_probability": base_probability,
        "line": line_value,
        "projection_mean_from_base": projection_mean,
        "projection_delta_from_line": projection_delta,
        "projection_abs_delta_from_line": abs(projection_delta),
        "projection_line_ratio": projection_mean / max(abs(line_value), 0.5),
        "is_live": _bool_number(feature_row.get("is_live")),
        "is_combo": _bool_number(feature_row.get("is_combo")),
        "feature_market_source_is_bettingpros": source_flags["bettingpros"],
        "feature_market_source_is_dk_pick6": source_flags["draftkings_pick6"],
        "feature_market_source_is_dk_sportsbook": source_flags["draftkings_sportsbook"],
        "feature_market_source_is_external": source_flags["external"],
        "feature_market_source_is_prizepicks_only": source_flags["prizepicks_line_only"],
    }
    numeric_columns = (
        "projected_opportunity",
        "opportunity_floor",
        "opportunity_ceiling",
        "opportunity_confidence",
        "opportunity_fragility_score",
        "player_history_context_available",
        "plate_appearance_projection",
        "market_context_available",
        "market_source_line",
        "market_line_delta",
        "market_over_probability",
        "market_under_probability",
        "market_n_books",
        "market_target_blend_weight",
        "market_target_shift",
        "lineup_score",
        "starter_matchup_score",
        "bullpen_matchup_score",
        "environment_score",
        "matchup_composite_score",
        "matchup_confidence",
        "matchup_context_available",
        "matchup_target_shift",
        "advanced_context_available",
        "advanced_context_score",
        "advanced_hit_context_score",
        "advanced_power_context_score",
        "advanced_plate_discipline_score",
        "advanced_k_context_score",
        "advanced_contact_quality_score",
        "advanced_sample_confidence",
        "advanced_target_shift",
    )
    for column in numeric_columns:
        row[column] = _number(parameter_row.get(column))

    feature_numeric_columns = (
        "lineup_context_available",
        "probable_pitcher_context_available",
        "batting_order_slot",
        "lineup_probability",
        "lineup_confirmed",
        "top_order_flag",
        "projected_plate_appearances",
        "pinch_hit_risk",
        "same_hand_matchup",
        "platoon_advantage",
        "handedness_context_available",
        "hitter_strikeout_pressure_score",
        "hitter_contact_context_score",
        "hitter_power_context_score",
        "hitter_walk_context_score",
        "hitter_late_game_run_score",
        "park_run_factor",
        "park_hr_factor",
        "park_hit_factor",
        "park_extra_base_factor",
        "park_factor_confidence",
        "umpire_era",
        "umpire_run_score",
        "umpire_confidence",
        "pitcher_prop_context_available",
        "pitcher_workload_context_score",
        "pitcher_strikeout_context_score",
        "pitcher_run_allow_context_score",
        "pitcher_walk_context_score",
        "pitcher_opponent_lineup_score",
        "pitcher_opponent_k_context_score",
        "pitcher_opponent_contact_context_score",
        "pitcher_opponent_power_context_score",
        "pitcher_opponent_walk_context_score",
        "pitcher_opponent_projected_pa",
        "pitcher_opponent_top_order_pa",
        "pitcher_opponent_confirmed_batters",
        "pitcher_opponent_lineup_confidence",
        "pitcher_history_k_score",
        "pitcher_history_hit_allow_score",
        "pitcher_history_walk_score",
        "pitcher_history_confidence",
        "pitcher_bullpen_support_score",
        "pitcher_prop_composite_score",
        "pitcher_prop_confidence",
        "injury_context_available",
        "injury_risk_score",
        "weather_context_available",
        "statsapi_context_available",
        "statsapi_is_home",
        "roster_context_available",
        "player_history_context_available",
        "history_games_season",
        "history_games_7d",
        "history_games_14d",
        "season_pa_per_game",
        "recent_pa_per_game_7d",
        "recent_pa_per_game_14d",
        "plate_appearance_projection",
        "history_context_confidence",
        "transaction_source_available",
        "transaction_context_available",
        "recent_transaction_count",
        "recent_callup_count",
        "recent_option_count",
        "recent_injury_status_count",
        "transaction_volatility_score",
        "external_market_context_available",
        "prizepicks_line_only_market_context",
        "bettingpros_projection_value",
        "bettingpros_projection_probability",
        "bettingpros_projection_expected_value",
        "bettingpros_projection_diff",
        "bettingpros_streak",
        "bettingpros_last_5_over_rate",
        "bettingpros_last_5_under_rate",
        "bettingpros_last_10_over_rate",
        "bettingpros_last_10_under_rate",
        "bettingpros_last_20_over_rate",
        "bettingpros_last_20_under_rate",
        "bettingpros_season_over_rate",
        "bettingpros_season_under_rate",
        "bettingpros_prior_season_over_rate",
        "bettingpros_prior_season_under_rate",
    )
    for column in feature_numeric_columns:
        row[f"feature_{column}"] = _number(feature_row.get(column))
    return row


def _projection_mean(*, market: str, line: float, target_over_probability: float, distribution: str) -> float:
    try:
        value = projection_mean_for_target(
            market=market,
            line=line,
            target_over_probability=target_over_probability,
            distribution=distribution,
        )
    except Exception:
        value = line
    if not math.isfinite(float(value)):
        return 0.0
    return round(float(value), 6)


def _market_source_flags(source_type: str, source: str) -> dict[str, float]:
    source_text = f"{source_type} {source}".lower()
    prizepicks_only = "prizepicks_line_only" in source_text
    return {
        "bettingpros": 1.0 if "bettingpros" in source_text else 0.0,
        "draftkings_pick6": 1.0 if "draftkings_mlb_pick6" in source_text or "pick6" in source_text else 0.0,
        "draftkings_sportsbook": 1.0 if "draftkings_mlb_sportsbook" in source_text or "sportsbook" in source_text else 0.0,
        "external": 0.0 if prizepicks_only else (1.0 if source_text.strip() else 0.0),
        "prizepicks_line_only": 1.0 if prizepicks_only else 0.0,
    }


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
    if value < 25.0:
        return "line_13_24.5"
    return "line_25_plus"


def _prep_frame(rows: list[dict[str, Any]], *, features: list[str], cat_features: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    for feature in features:
        if feature not in frame.columns:
            frame[feature] = "" if feature in cat_features else 0.0
    frame = frame[features].copy()
    for feature in features:
        if feature in cat_features:
            frame[feature] = frame[feature].fillna("").astype(str)
        else:
            frame[feature] = pd.to_numeric(frame[feature], errors="coerce").fillna(0.0).astype(float)
            frame[feature] = frame[feature].replace([math.inf, -math.inf], 0.0)
    return frame


def _load_table_payload(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".csv":
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            return {"rows": list(csv.DictReader(handle))}
    return _load_json(path)


def _resolve_stacker_base_artifact(stacker_meta: dict[str, Any], stacker_artifact_path: Path) -> Path:
    base_artifact_raw = str(stacker_meta.get("base_artifact_path") or "").strip()
    if base_artifact_raw:
        base_artifact = Path(base_artifact_raw)
        if base_artifact.is_absolute():
            return base_artifact
        candidate = (stacker_artifact_path.parent / base_artifact).resolve()
        if candidate.exists():
            return candidate

    base_model_dir_raw = str(stacker_meta.get("base_model_dir") or "").strip()
    if base_model_dir_raw:
        base_model_dir = Path(base_model_dir_raw)
        if not base_model_dir.is_absolute():
            base_model_dir = (stacker_artifact_path.parent / base_model_dir).resolve()
        candidate = base_model_dir / "best_config.json"
        if candidate.exists():
            return candidate

    raise FileNotFoundError("Stacker artifact does not resolve to a base CAT best_config.json")


def _resolve_model_path(meta: dict[str, Any], meta_path: Path) -> Path:
    model_path = Path(str(meta.get("model_path") or meta.get("model_out") or ""))
    if model_path.is_absolute():
        candidates = [
            model_path,
            meta_path.parent / model_path.name,
            meta_path.parent.parent / model_path.name,
        ]
    else:
        candidates = [
            (meta_path.parent / model_path).resolve(),
            meta_path.parent / model_path.name,
            meta_path.parent.parent / model_path.name,
        ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    columns = sorted({key for row in rows for key in row.keys()})
    preferred = [
        "run_id",
        "source_projection_id",
        "event_id",
        "player_id",
        "player_name",
        "player_team",
        "opponent",
        "game_date",
        "start_time_utc",
        "market",
        "source_market",
        "line",
        "tier",
        "uncalibrated_target_over_probability",
        "cat_adjusted_target_over_probability",
        "probability_stacker_probability",
        "target_over_probability",
        "calibration_version",
        "base_calibration_version",
        "cat_residual_raw",
        "cat_residual_clipped",
        "cat_residual_scale",
        "cat_residual_scaled",
        "probability_stacker_blend_weight",
    ]
    fieldnames = [column for column in preferred if column in columns] + [
        column for column in columns if column not in preferred
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in fieldnames})


def _join_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("source_projection_id") or "").strip(),
        str(row.get("market") or "").strip(),
        _line_key(row.get("line")),
        str(row.get("tier") or "STANDARD").strip().upper() or "STANDARD",
        str(row.get("event_id") or "").strip(),
    )


def _line_key(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def _copy_latest(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _slug(value: str) -> str:
    text = "".join(character if character.isalnum() else "_" for character in value.lower()).strip("_")
    return text or "calibrated"


def _tuple_flags(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("["):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return (value,)
            return _tuple_flags(decoded)
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),)


def _calibrated_flags(value: Any, *extra_flags: str) -> tuple[str, ...]:
    flags: list[str] = []
    seen: set[str] = set()
    for flag in (*_tuple_flags(value), *extra_flags):
        clean = str(flag).strip()
        if not clean or clean == "uncalibrated" or clean in seen:
            continue
        flags.append(clean)
        seen.add(clean)
    return tuple(flags)


def _number(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return 1.0 if value.strip().lower() == "true" else 0.0
    return _float(value, 0.0)


def _bool_number(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return 1.0 if str(value or "").strip().lower() in {"1", "true", "yes", "y"} else 0.0


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _residual_scale_for_row(meta: dict[str, Any], row: dict[str, Any], default: float) -> float:
    tier = str(row.get("tier") or "STANDARD").strip().upper() or "STANDARD"
    market = str(row.get("market") or row.get("source_market") or "").strip()
    source_type = str(row.get("market_context_source_type") or "").strip()
    line_bucket = str(row.get("line_bucket") or "").strip() or _line_bucket(_float(row.get("line"), 0.0))
    tier_market_key = f"{tier}|{market}"
    market_source_key = f"{market}|{source_type}" if source_type else ""
    tier_market_source_key = f"{tier}|{market}|{source_type}" if source_type else ""
    tier_market_source_map = meta.get("residual_scale_by_tier_market_source")
    if isinstance(tier_market_source_map, dict) and tier_market_source_key in tier_market_source_map:
        return _float(tier_market_source_map.get(tier_market_source_key), default)
    tier_market_map = meta.get("residual_scale_by_tier_market")
    if isinstance(tier_market_map, dict) and tier_market_key in tier_market_map:
        return _float(tier_market_map.get(tier_market_key), default)
    market_source_map = meta.get("residual_scale_by_market_source")
    if isinstance(market_source_map, dict) and market_source_key in market_source_map:
        return _float(market_source_map.get(market_source_key), default)
    market_map = meta.get("residual_scale_by_market")
    if isinstance(market_map, dict) and market in market_map:
        return _float(market_map.get(market), default)
    source_map = meta.get("residual_scale_by_market_source_type")
    if isinstance(source_map, dict) and source_type in source_map:
        return _float(source_map.get(source_type), default)
    line_bucket_map = meta.get("residual_scale_by_line_bucket")
    if isinstance(line_bucket_map, dict) and line_bucket in line_bucket_map:
        return _float(line_bucket_map.get(line_bucket), default)
    tier_map = meta.get("residual_scale_by_tier")
    if isinstance(tier_map, dict) and tier in tier_map:
        return _float(tier_map.get(tier), default)
    return default


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 8) if values else None


def _min(values: list[float]) -> float | None:
    return round(min(values), 8) if values else None


def _max(values: list[float]) -> float | None:
    return round(max(values), 8) if values else None


def _csv_value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True)
    return value
