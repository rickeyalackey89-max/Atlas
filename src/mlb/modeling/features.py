"""Baseline feature-table writer for MLB player props."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

from mlb.modeling.opportunity import estimate_opportunity
from mlb.runtime.engine_inputs import _load_json
from mlb.runtime.paths import ensure_mlb_dirs

FEATURE_MODEL_VERSION = "baseline_player_prop_features_v1_market_source_type"

FEATURE_COLUMNS = (
    "run_id",
    "source_projection_id",
    "event_id",
    "player_id",
    "player_name",
    "player_team",
    "opponent",
    "game_date",
    "start_time_utc",
    "player_position",
    "market",
    "source_market",
    "line",
    "tier",
    "status",
    "is_live",
    "is_combo",
    "market_group",
    "opportunity_model_version",
    "opportunity_type",
    "projected_opportunity",
    "opportunity_floor",
    "opportunity_ceiling",
    "opportunity_confidence",
    "opportunity_fragility_score",
    "lineup_score",
    "starter_matchup_score",
    "bullpen_matchup_score",
    "environment_score",
    "matchup_composite_score",
    "matchup_confidence",
    "matchup_context_available",
    "matchup_context_flags",
    "lineup_context_available",
    "probable_pitcher_context_available",
    "injury_context_available",
    "injury_status",
    "injury_risk_score",
    "injury_context_flags",
    "weather_context_available",
    "statsapi_context_available",
    "statsapi_game_pk",
    "statsapi_game_status",
    "statsapi_venue_id",
    "statsapi_venue_name",
    "statsapi_team_id",
    "statsapi_opponent_id",
    "statsapi_is_home",
    "statsapi_context_flags",
    "roster_context_available",
    "statsapi_person_id",
    "statsapi_roster_team_id",
    "statsapi_roster_team_abbreviation",
    "statsapi_player_position",
    "statsapi_bats",
    "statsapi_throws",
    "statsapi_roster_status",
    "roster_context_flags",
    "player_history_context_available",
    "history_games_season",
    "history_games_7d",
    "history_games_14d",
    "season_pa_per_game",
    "recent_pa_per_game_7d",
    "recent_pa_per_game_14d",
    "plate_appearance_projection",
    "history_context_confidence",
    "history_context_flags",
    "transaction_source_available",
    "transaction_context_available",
    "recent_transaction_count",
    "recent_callup_count",
    "recent_option_count",
    "recent_injury_status_count",
    "last_transaction_date",
    "last_transaction_type_code",
    "last_transaction_type_desc",
    "transaction_volatility_score",
    "transaction_context_flags",
    "external_market_context_available",
    "market_context_source_type",
    "external_market_context_source",
    "prizepicks_line_only_market_context",
    "bettingpros_recommended_side",
    "bettingpros_projection_value",
    "bettingpros_projection_probability",
    "bettingpros_projection_expected_value",
    "bettingpros_projection_diff",
    "bettingpros_streak",
    "bettingpros_streak_type",
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
    "advanced_context_available",
    "advanced_context_score",
    "advanced_hit_context_score",
    "advanced_power_context_score",
    "advanced_plate_discipline_score",
    "advanced_k_context_score",
    "advanced_contact_quality_score",
    "advanced_sample_confidence",
    "advanced_profile_source",
    "advanced_profile_match_type",
    "advanced_context_flags",
    "feature_model_version",
    "flags",
)


def build_player_prop_feature_table(
    *,
    engine_board_path: Path,
    matchup_context_path: Path | None = None,
    market_context_path: Path | None = None,
    injury_context_path: Path | None = None,
    statsapi_context_path: Path | None = None,
    roster_context_path: Path | None = None,
    player_history_context_path: Path | None = None,
    transaction_context_path: Path | None = None,
    advanced_context_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Write a replayable baseline feature table from an engine board."""

    paths = ensure_mlb_dirs(root)
    engine_board = _load_json(engine_board_path)
    resolved_run_id = run_id or str(engine_board.get("run_id") or engine_board_path.parent.name)
    matchup_rows = _load_matchup_rows(matchup_context_path)
    market_rows = _load_matchup_rows(market_context_path)
    injury_rows = _load_matchup_rows(injury_context_path)
    statsapi_rows = _load_matchup_rows(statsapi_context_path)
    roster_rows = _load_matchup_rows(roster_context_path)
    player_history_rows = _load_matchup_rows(player_history_context_path)
    transaction_rows = _load_matchup_rows(transaction_context_path)
    advanced_rows = _load_matchup_rows(advanced_context_path)
    rows = [
        _feature_row(
            row,
            run_id=resolved_run_id,
            matchup_row=matchup_rows.get(_matchup_key(row)),
            market_row=market_rows.get(_matchup_key(row)),
            injury_row=injury_rows.get(_matchup_key(row)),
            statsapi_row=statsapi_rows.get(_matchup_key(row)),
            roster_row=roster_rows.get(_matchup_key(row)),
            player_history_row=player_history_rows.get(_matchup_key(row)),
            transaction_row=transaction_rows.get(_matchup_key(row)),
            advanced_row=advanced_rows.get(_matchup_key(row)),
        )
        for row in engine_board.get("rows", [])
        if isinstance(row, dict)
    ]
    output_dir = paths.features / "player_props" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "feature_table.csv"
    json_path = output_dir / "feature_table.json"
    manifest_path = output_dir / "feature_manifest.json"
    _write_csv(csv_path, rows)
    json_path.write_text(
        json.dumps({"run_id": resolved_run_id, "row_count": len(rows), "rows": rows}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    manifest = {
        "run_id": resolved_run_id,
        "engine_board_path": str(engine_board_path),
        "matchup_context_path": str(matchup_context_path) if matchup_context_path else "",
        "market_context_path": str(market_context_path) if market_context_path else "",
        "injury_context_path": str(injury_context_path) if injury_context_path else "",
        "statsapi_context_path": str(statsapi_context_path) if statsapi_context_path else "",
        "roster_context_path": str(roster_context_path) if roster_context_path else "",
        "player_history_context_path": str(player_history_context_path) if player_history_context_path else "",
        "transaction_context_path": str(transaction_context_path) if transaction_context_path else "",
        "advanced_context_path": str(advanced_context_path) if advanced_context_path else "",
        "row_count": len(rows),
        "feature_model_version": FEATURE_MODEL_VERSION,
        "market_group_counts": _counts(row["market_group"] for row in rows),
        "opportunity_model_versions": _counts(row["opportunity_model_version"] for row in rows),
        "opportunity_type_counts": _counts(row["opportunity_type"] for row in rows),
        "source_completeness": _source_completeness(rows),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
        "latest_csv_path": str(paths.features / "player_props" / "latest.csv"),
        "latest_json_path": str(paths.features / "player_props" / "latest.json"),
        "latest_manifest_path": str(paths.features / "player_props" / "latest_manifest.json"),
        "columns": list(FEATURE_COLUMNS),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _copy_latest(csv_path, paths.features / "player_props" / "latest.csv")
    _copy_latest(json_path, paths.features / "player_props" / "latest.json")
    _copy_latest(manifest_path, paths.features / "player_props" / "latest_manifest.json")
    return manifest


def _feature_row(
    row: dict[str, Any],
    *,
    run_id: str,
    matchup_row: dict[str, Any] | None = None,
    market_row: dict[str, Any] | None = None,
    injury_row: dict[str, Any] | None = None,
    statsapi_row: dict[str, Any] | None = None,
    roster_row: dict[str, Any] | None = None,
    player_history_row: dict[str, Any] | None = None,
    transaction_row: dict[str, Any] | None = None,
    advanced_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    opportunity = estimate_opportunity(row)
    matchup = _matchup_values(matchup_row)
    market_context_available = bool(market_row and _bool(market_row.get("market_context_available")))
    injury = _injury_values(injury_row)
    statsapi = _statsapi_values(statsapi_row)
    roster = _roster_values(roster_row)
    player_history = _player_history_values(player_history_row)
    transaction = _transaction_values(transaction_row)
    advanced = _advanced_values(advanced_row)
    bettingpros = _bettingpros_values(market_row)
    flags = ["baseline_feature_contract"]
    flags.extend(opportunity.flags)
    if matchup["available"]:
        flags.append("matchup_context_available")
    else:
        flags.append("matchup_context_missing")
    if market_context_available:
        flags.append("external_market_context_available")
    else:
        flags.append("external_market_context_missing")
        flags.append("prizepicks_line_only_market_context")
    if injury["available"]:
        flags.append("injury_context_available")
    else:
        flags.append("injury_context_missing")
    if statsapi["available"]:
        flags.append("statsapi_context_available")
    else:
        flags.append("statsapi_context_missing")
    if roster["available"]:
        flags.append("roster_context_available")
    else:
        flags.append("roster_context_missing")
    if player_history["available"]:
        flags.append("player_history_context_available")
    else:
        flags.append("player_history_context_missing")
    if transaction["source_available"]:
        flags.append("transaction_source_available")
    else:
        flags.append("transaction_source_missing")
    if transaction["available"]:
        flags.append("recent_transaction_context_available")
    if advanced["available"]:
        flags.append("advanced_context_available")
    else:
        flags.append("advanced_context_missing")
    return {
        "run_id": run_id,
        "source_projection_id": str(row.get("source_projection_id") or ""),
        "event_id": str(row.get("event_id") or ""),
        "player_id": str(row.get("player_id") or ""),
        "player_name": str(row.get("player_name") or ""),
        "player_team": str(row.get("player_team") or ""),
        "opponent": str(row.get("opponent") or ""),
        "game_date": str(row.get("game_date") or ""),
        "start_time_utc": str(row.get("start_time_utc") or ""),
        "player_position": str(row.get("player_position") or ""),
        "market": str(row.get("market") or ""),
        "source_market": str(row.get("source_market") or ""),
        "line": _float(row.get("line")),
        "tier": str(row.get("tier") or "STANDARD"),
        "status": str(row.get("status") or "active"),
        "is_live": _bool(row.get("is_live")),
        "is_combo": _bool(row.get("is_combo")),
        "market_group": opportunity.market_group,
        "opportunity_model_version": opportunity.opportunity_model_version,
        "opportunity_type": opportunity.opportunity_type,
        "projected_opportunity": opportunity.projected_opportunity,
        "opportunity_floor": opportunity.opportunity_floor,
        "opportunity_ceiling": opportunity.opportunity_ceiling,
        "opportunity_confidence": opportunity.opportunity_confidence,
        "opportunity_fragility_score": opportunity.opportunity_fragility_score,
        "lineup_score": matchup["lineup_score"],
        "starter_matchup_score": matchup["starter_matchup_score"],
        "bullpen_matchup_score": matchup["bullpen_matchup_score"],
        "environment_score": matchup["environment_score"],
        "matchup_composite_score": matchup["matchup_composite_score"],
        "matchup_confidence": matchup["matchup_confidence"],
        "matchup_context_available": matchup["available"],
        "matchup_context_flags": matchup["flags"],
        "lineup_context_available": "missing_lineup_context" not in matchup["flags"] and matchup["available"],
        "probable_pitcher_context_available": "missing_pitcher_context" not in matchup["flags"] and matchup["available"],
        "injury_context_available": injury["available"],
        "injury_status": injury["status"],
        "injury_risk_score": injury["risk_score"],
        "injury_context_flags": injury["flags"],
        "weather_context_available": "missing_environment_context" not in matchup["flags"] and matchup["available"],
        "statsapi_context_available": statsapi["available"],
        "statsapi_game_pk": statsapi["game_pk"],
        "statsapi_game_status": statsapi["game_status"],
        "statsapi_venue_id": statsapi["venue_id"],
        "statsapi_venue_name": statsapi["venue_name"],
        "statsapi_team_id": statsapi["team_id"],
        "statsapi_opponent_id": statsapi["opponent_id"],
        "statsapi_is_home": statsapi["is_home"],
        "statsapi_context_flags": statsapi["flags"],
        "roster_context_available": roster["available"],
        "statsapi_person_id": roster["person_id"],
        "statsapi_roster_team_id": roster["team_id"],
        "statsapi_roster_team_abbreviation": roster["team_abbreviation"],
        "statsapi_player_position": roster["player_position"],
        "statsapi_bats": roster["bats"],
        "statsapi_throws": roster["throws"],
        "statsapi_roster_status": roster["status"],
        "roster_context_flags": roster["flags"],
        "player_history_context_available": player_history["available"],
        "history_games_season": player_history["games_season"],
        "history_games_7d": player_history["games_7d"],
        "history_games_14d": player_history["games_14d"],
        "season_pa_per_game": player_history["season_pa_per_game"],
        "recent_pa_per_game_7d": player_history["recent_pa_per_game_7d"],
        "recent_pa_per_game_14d": player_history["recent_pa_per_game_14d"],
        "plate_appearance_projection": player_history["plate_appearance_projection"],
        "history_context_confidence": player_history["confidence"],
        "history_context_flags": player_history["flags"],
        "transaction_source_available": transaction["source_available"],
        "transaction_context_available": transaction["available"],
        "recent_transaction_count": transaction["recent_transaction_count"],
        "recent_callup_count": transaction["recent_callup_count"],
        "recent_option_count": transaction["recent_option_count"],
        "recent_injury_status_count": transaction["recent_injury_status_count"],
        "last_transaction_date": transaction["last_transaction_date"],
        "last_transaction_type_code": transaction["last_transaction_type_code"],
        "last_transaction_type_desc": transaction["last_transaction_type_desc"],
        "transaction_volatility_score": transaction["volatility_score"],
        "transaction_context_flags": transaction["flags"],
        "external_market_context_available": market_context_available,
        "market_context_source_type": _market_context_source_type(market_row, market_context_available=market_context_available),
        "external_market_context_source": _external_market_context_source(market_row, market_context_available=market_context_available),
        "prizepicks_line_only_market_context": not market_context_available,
        "bettingpros_recommended_side": bettingpros["recommended_side"],
        "bettingpros_projection_value": bettingpros["projection_value"],
        "bettingpros_projection_probability": bettingpros["projection_probability"],
        "bettingpros_projection_expected_value": bettingpros["projection_expected_value"],
        "bettingpros_projection_diff": bettingpros["projection_diff"],
        "bettingpros_streak": bettingpros["streak"],
        "bettingpros_streak_type": bettingpros["streak_type"],
        "bettingpros_last_5_over_rate": bettingpros["last_5_over_rate"],
        "bettingpros_last_5_under_rate": bettingpros["last_5_under_rate"],
        "bettingpros_last_10_over_rate": bettingpros["last_10_over_rate"],
        "bettingpros_last_10_under_rate": bettingpros["last_10_under_rate"],
        "bettingpros_last_20_over_rate": bettingpros["last_20_over_rate"],
        "bettingpros_last_20_under_rate": bettingpros["last_20_under_rate"],
        "bettingpros_season_over_rate": bettingpros["season_over_rate"],
        "bettingpros_season_under_rate": bettingpros["season_under_rate"],
        "bettingpros_prior_season_over_rate": bettingpros["prior_season_over_rate"],
        "bettingpros_prior_season_under_rate": bettingpros["prior_season_under_rate"],
        "advanced_context_available": advanced["available"],
        "advanced_context_score": advanced["context_score"],
        "advanced_hit_context_score": advanced["hit_score"],
        "advanced_power_context_score": advanced["power_score"],
        "advanced_plate_discipline_score": advanced["plate_discipline_score"],
        "advanced_k_context_score": advanced["k_context_score"],
        "advanced_contact_quality_score": advanced["contact_quality_score"],
        "advanced_sample_confidence": advanced["sample_confidence"],
        "advanced_profile_source": advanced["profile_source"],
        "advanced_profile_match_type": advanced["match_type"],
        "advanced_context_flags": advanced["flags"],
        "feature_model_version": FEATURE_MODEL_VERSION,
        "flags": flags,
    }


def _source_completeness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    fields = (
        "lineup_context_available",
        "probable_pitcher_context_available",
        "injury_context_available",
        "weather_context_available",
        "statsapi_context_available",
        "roster_context_available",
        "player_history_context_available",
        "transaction_source_available",
        "external_market_context_available",
        "prizepicks_line_only_market_context",
        "advanced_context_available",
    )
    return {field: _true_rate(row[field] for row in rows) for field in fields}


def _market_context_source_type(row: dict[str, Any] | None, *, market_context_available: bool) -> str:
    if market_context_available:
        source = _external_market_context_source(row, market_context_available=True)
        return f"external_{source}" if source else "external_market"
    return "prizepicks_line_only"


def _external_market_context_source(row: dict[str, Any] | None, *, market_context_available: bool) -> str:
    if not market_context_available or not row:
        return ""
    return str(row.get("market_source") or "external_market").strip()


def _bettingpros_values(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row or str(row.get("market_source") or "") != "bettingpros_mlb_props":
        return {
            "recommended_side": "",
            "projection_value": 0.0,
            "projection_probability": 0.0,
            "projection_expected_value": 0.0,
            "projection_diff": 0.0,
            "streak": 0,
            "streak_type": "",
            "last_5_over_rate": 0.0,
            "last_5_under_rate": 0.0,
            "last_10_over_rate": 0.0,
            "last_10_under_rate": 0.0,
            "last_20_over_rate": 0.0,
            "last_20_under_rate": 0.0,
            "season_over_rate": 0.0,
            "season_under_rate": 0.0,
            "prior_season_over_rate": 0.0,
            "prior_season_under_rate": 0.0,
        }
    return {
        "recommended_side": str(row.get("bettingpros_recommended_side") or ""),
        "projection_value": _float(row.get("bettingpros_projection_value")),
        "projection_probability": _float(row.get("bettingpros_projection_probability")),
        "projection_expected_value": _float(row.get("bettingpros_projection_expected_value")),
        "projection_diff": _float(row.get("bettingpros_projection_diff")),
        "streak": _int(row.get("bettingpros_streak")),
        "streak_type": str(row.get("bettingpros_streak_type") or ""),
        "last_5_over_rate": _float(row.get("bettingpros_last_5_over_rate")),
        "last_5_under_rate": _float(row.get("bettingpros_last_5_under_rate")),
        "last_10_over_rate": _float(row.get("bettingpros_last_10_over_rate")),
        "last_10_under_rate": _float(row.get("bettingpros_last_10_under_rate")),
        "last_20_over_rate": _float(row.get("bettingpros_last_20_over_rate")),
        "last_20_under_rate": _float(row.get("bettingpros_last_20_under_rate")),
        "season_over_rate": _float(row.get("bettingpros_season_over_rate")),
        "season_under_rate": _float(row.get("bettingpros_season_under_rate")),
        "prior_season_over_rate": _float(row.get("bettingpros_prior_season_over_rate")),
        "prior_season_under_rate": _float(row.get("bettingpros_prior_season_under_rate")),
    }


def _load_matchup_rows(path: Path | None) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    payload = _load_json(path)
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        return {}
    contexts: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("direction") or "over").lower() != "over":
            continue
        contexts[_matchup_key(row)] = row
    return contexts


def _matchup_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("source_projection_id") or "").strip(),
        str(row.get("market") or "").strip(),
        _line_key(row.get("line")),
        str(row.get("tier") or "STANDARD").strip().upper() or "STANDARD",
    )


def _matchup_values(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return _empty_matchup()
    flags = _tuple_flags(row.get("missing_context_flags"))
    confidence = _clamp(_float(row.get("matchup_confidence")), 0.0, 1.0)
    return {
        "lineup_score": _float(row.get("lineup_score")),
        "starter_matchup_score": _float(row.get("starter_matchup_score")),
        "bullpen_matchup_score": _float(row.get("bullpen_matchup_score")),
        "environment_score": _float(row.get("environment_score")),
        "matchup_composite_score": _float(row.get("matchup_composite_score")),
        "matchup_confidence": confidence,
        "available": bool(confidence > 0.0 and len(flags) < 4),
        "flags": flags,
    }


def _empty_matchup() -> dict[str, Any]:
    return {
        "lineup_score": 0.0,
        "starter_matchup_score": 0.0,
        "bullpen_matchup_score": 0.0,
        "environment_score": 0.0,
        "matchup_composite_score": 0.0,
        "matchup_confidence": 0.0,
        "available": False,
        "flags": ("missing_matchup_context_row",),
    }


def _injury_values(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {
            "available": False,
            "status": "",
            "risk_score": 0.0,
            "flags": ("missing_injury_context_row",),
        }
    return {
        "available": _bool(row.get("injury_context_available")),
        "status": str(row.get("injury_status") or ""),
        "risk_score": _float(row.get("injury_risk_score")),
        "flags": _tuple_flags(row.get("injury_context_flags")),
    }


def _statsapi_values(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {
            "available": False,
            "game_pk": 0,
            "game_status": "",
            "venue_id": 0,
            "venue_name": "",
            "team_id": 0,
            "opponent_id": 0,
            "is_home": False,
            "flags": ("missing_statsapi_context_row",),
        }
    return {
        "available": _bool(row.get("statsapi_context_available")),
        "game_pk": _int(row.get("game_pk")),
        "game_status": str(row.get("statsapi_game_status") or ""),
        "venue_id": _int(row.get("venue_id")),
        "venue_name": str(row.get("venue_name") or ""),
        "team_id": _int(row.get("team_id")),
        "opponent_id": _int(row.get("opponent_id")),
        "is_home": _bool(row.get("is_home")),
        "flags": _tuple_flags(row.get("statsapi_context_flags")),
    }


def _roster_values(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {
            "available": False,
            "person_id": 0,
            "team_id": 0,
            "team_abbreviation": "",
            "player_position": "",
            "bats": "",
            "throws": "",
            "status": "",
            "flags": ("missing_roster_context_row",),
        }
    return {
        "available": _bool(row.get("roster_context_available")),
        "person_id": _int(row.get("statsapi_person_id")),
        "team_id": _int(row.get("statsapi_roster_team_id")),
        "team_abbreviation": str(row.get("statsapi_roster_team_abbreviation") or ""),
        "player_position": str(row.get("statsapi_player_position") or ""),
        "bats": str(row.get("statsapi_bats") or ""),
        "throws": str(row.get("statsapi_throws") or ""),
        "status": str(row.get("statsapi_roster_status") or ""),
        "flags": _tuple_flags(row.get("roster_context_flags")),
    }


def _player_history_values(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {
            "available": False,
            "games_season": 0,
            "games_7d": 0,
            "games_14d": 0,
            "season_pa_per_game": 0.0,
            "recent_pa_per_game_7d": 0.0,
            "recent_pa_per_game_14d": 0.0,
            "plate_appearance_projection": 0.0,
            "confidence": 0.0,
            "flags": ("missing_player_history_context_row",),
        }
    return {
        "available": _bool(row.get("player_history_context_available")),
        "games_season": _int(row.get("history_games_season")),
        "games_7d": _int(row.get("history_games_7d")),
        "games_14d": _int(row.get("history_games_14d")),
        "season_pa_per_game": _float(row.get("season_pa_per_game")),
        "recent_pa_per_game_7d": _float(row.get("recent_pa_per_game_7d")),
        "recent_pa_per_game_14d": _float(row.get("recent_pa_per_game_14d")),
        "plate_appearance_projection": _float(row.get("plate_appearance_projection")),
        "confidence": _float(row.get("history_context_confidence")),
        "flags": _tuple_flags(row.get("history_context_flags")),
    }


def _transaction_values(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {
            "source_available": False,
            "available": False,
            "recent_transaction_count": 0,
            "recent_callup_count": 0,
            "recent_option_count": 0,
            "recent_injury_status_count": 0,
            "last_transaction_date": "",
            "last_transaction_type_code": "",
            "last_transaction_type_desc": "",
            "volatility_score": 0.0,
            "flags": ("missing_transaction_context_row",),
        }
    return {
        "source_available": _bool(row.get("transaction_source_available")),
        "available": _bool(row.get("transaction_context_available")),
        "recent_transaction_count": _int(row.get("recent_transaction_count")),
        "recent_callup_count": _int(row.get("recent_callup_count")),
        "recent_option_count": _int(row.get("recent_option_count")),
        "recent_injury_status_count": _int(row.get("recent_injury_status_count")),
        "last_transaction_date": str(row.get("last_transaction_date") or ""),
        "last_transaction_type_code": str(row.get("last_transaction_type_code") or ""),
        "last_transaction_type_desc": str(row.get("last_transaction_type_desc") or ""),
        "volatility_score": _float(row.get("transaction_volatility_score")),
        "flags": _tuple_flags(row.get("transaction_context_flags")),
    }


def _advanced_values(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {
            "available": False,
            "context_score": 0.0,
            "hit_score": 0.0,
            "power_score": 0.0,
            "plate_discipline_score": 0.0,
            "k_context_score": 0.0,
            "contact_quality_score": 0.0,
            "sample_confidence": 0.0,
            "profile_source": "",
            "match_type": "",
            "flags": ("missing_advanced_context_row",),
        }
    return {
        "available": _bool(row.get("advanced_context_available")),
        "context_score": _float(row.get("advanced_context_score")),
        "hit_score": _float(row.get("advanced_hit_context_score")),
        "power_score": _float(row.get("advanced_power_context_score")),
        "plate_discipline_score": _float(row.get("advanced_plate_discipline_score")),
        "k_context_score": _float(row.get("advanced_k_context_score")),
        "contact_quality_score": _float(row.get("advanced_contact_quality_score")),
        "sample_confidence": _float(row.get("advanced_sample_confidence")),
        "profile_source": str(row.get("advanced_profile_source") or ""),
        "match_type": str(row.get("advanced_profile_match_type") or ""),
        "flags": _tuple_flags(row.get("advanced_context_flags")),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FEATURE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in FEATURE_COLUMNS})


def _copy_latest(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _true_rate(values) -> float | None:
    collected = [bool(value) for value in values]
    if not collected:
        return None
    return round(sum(1 for value in collected if value) / len(collected), 6)


def _csv_value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True)
    return value


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _line_key(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


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


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
