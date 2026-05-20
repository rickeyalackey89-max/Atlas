"""Baseline parameter artifacts for the Atlas MLB simulator."""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from mlb.domain.markets import BATTER_MARKETS
from mlb.modeling.probability import (
    DEFAULT_SIMULATION_N,
    PARAMETER_MODEL_VERSION,
    MARKET_PRIOR_PROFILES,
)
from mlb.modeling.opportunity import estimate_opportunity
from mlb.modeling.qmc import default_distribution_for_market
from mlb.runtime.engine_inputs import _load_json
from mlb.runtime.paths import ensure_mlb_dirs

PARAMETER_COLUMNS = (
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
    "target_over_probability",
    "distribution",
    "simulation_n",
    "parameter_model_version",
    "opportunity_model_version",
    "market_group",
    "opportunity_type",
    "projected_opportunity",
    "opportunity_floor",
    "opportunity_ceiling",
    "opportunity_confidence",
    "opportunity_fragility_score",
    "player_history_context_available",
    "plate_appearance_projection",
    "player_history_context_flags",
    "market_context_available",
    "market_line_match_type",
    "market_source_line",
    "market_line_delta",
    "market_over_probability",
    "market_under_probability",
    "market_n_books",
    "market_target_blend_weight",
    "market_target_shift",
    "market_context_flags",
    "lineup_score",
    "starter_matchup_score",
    "bullpen_matchup_score",
    "environment_score",
    "matchup_composite_score",
    "matchup_confidence",
    "matchup_context_available",
    "matchup_target_shift",
    "matchup_context_flags",
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
    "advanced_target_shift",
    "advanced_context_flags",
    "flags",
)

PITCHER_PROP_MARKETS = {
    "pitcher_strikeouts",
    "pitching_outs",
    "hits_allowed",
    "earned_runs",
    "earned_runs_allowed",
    "walks_allowed",
    "pitches_thrown",
    "pitcher_fantasy_score",
    "first_inning_runs_allowed",
    "first_inning_walks_allowed",
    "pitcher_strikeouts_combo",
    "pitcher_strikeouts_plus_total_bases",
}


def build_parameter_table(
    *,
    engine_board_path: Path,
    matchup_context_path: Path | None = None,
    pitcher_prop_context_path: Path | None = None,
    market_context_path: Path | None = None,
    advanced_context_path: Path | None = None,
    player_history_context_path: Path | None = None,
    pitcher_prop_shift_scale: float = 0.055,
    pitcher_prop_shift_cap: float = 0.06,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Write the current simulation parameter table for an engine board."""

    paths = ensure_mlb_dirs(root)
    engine_board = _load_json(engine_board_path)
    resolved_run_id = run_id or str(engine_board.get("run_id") or engine_board_path.parent.name)
    matchup_rows = _load_matchup_rows(matchup_context_path)
    pitcher_prop_rows = _load_matchup_rows(pitcher_prop_context_path)
    market_rows = _load_matchup_rows(market_context_path)
    advanced_rows = _load_matchup_rows(advanced_context_path)
    player_history_rows = _load_matchup_rows(player_history_context_path)
    rows = [
        _parameter_row(
            row,
            run_id=resolved_run_id,
            matchup_row=matchup_rows.get(_matchup_key(row)),
            pitcher_prop_row=pitcher_prop_rows.get(_matchup_key(row)),
            market_row=market_rows.get(_matchup_key(row)),
            advanced_row=advanced_rows.get(_matchup_key(row)),
            player_history_row=player_history_rows.get(_matchup_key(row)),
            pitcher_prop_shift_scale=pitcher_prop_shift_scale,
            pitcher_prop_shift_cap=pitcher_prop_shift_cap,
        )
        for row in engine_board.get("rows", [])
        if isinstance(row, dict)
    ]
    output_dir = paths.features / "parameters" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "parameter_table.csv"
    json_path = output_dir / "parameter_table.json"
    manifest_path = output_dir / "parameter_manifest.json"
    _write_csv(csv_path, rows)
    json_path.write_text(
        json.dumps({"run_id": resolved_run_id, "row_count": len(rows), "rows": rows}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    manifest = {
        "run_id": resolved_run_id,
        "engine_board_path": str(engine_board_path),
        "matchup_context_path": str(matchup_context_path) if matchup_context_path else "",
        "pitcher_prop_context_path": str(pitcher_prop_context_path) if pitcher_prop_context_path else "",
        "market_context_path": str(market_context_path) if market_context_path else "",
        "advanced_context_path": str(advanced_context_path) if advanced_context_path else "",
        "player_history_context_path": str(player_history_context_path) if player_history_context_path else "",
        "pitcher_prop_shift_scale": round(float(pitcher_prop_shift_scale), 6),
        "pitcher_prop_shift_cap": round(float(pitcher_prop_shift_cap), 6),
        "row_count": len(rows),
        "parameter_model_version": PARAMETER_MODEL_VERSION,
        "opportunity_model_versions": _counts(row["opportunity_model_version"] for row in rows),
        "market_group_counts": _counts(row["market_group"] for row in rows),
        "opportunity_type_counts": _counts(row["opportunity_type"] for row in rows),
        "opportunity_confidence_mean": _mean(row["opportunity_confidence"] for row in rows),
        "player_history_context_available_rate": _true_rate(
            row["player_history_context_available"] for row in rows
        ),
        "market_context_available_rate": _true_rate(row["market_context_available"] for row in rows),
        "market_context_available_by_market_group": _true_rate_by_key(
            rows, key="market_group", value="market_context_available"
        ),
        "market_context_flag_counts": _flag_counts(row["market_context_flags"] for row in rows),
        "market_target_shift_mean": _mean(row["market_target_shift"] for row in rows),
        "market_target_shift_min": _min(row["market_target_shift"] for row in rows),
        "market_target_shift_max": _max(row["market_target_shift"] for row in rows),
        "market_target_blend_weight_mean": _mean(row["market_target_blend_weight"] for row in rows),
        "matchup_context_available_rate": _true_rate(row["matchup_context_available"] for row in rows),
        "matchup_context_available_by_market_group": _true_rate_by_key(
            rows, key="market_group", value="matchup_context_available"
        ),
        "matchup_context_flag_counts": _flag_counts(row["matchup_context_flags"] for row in rows),
        "matchup_target_shift_mean": _mean(row["matchup_target_shift"] for row in rows),
        "matchup_target_shift_min": _min(row["matchup_target_shift"] for row in rows),
        "matchup_target_shift_max": _max(row["matchup_target_shift"] for row in rows),
        "advanced_context_available_rate": _true_rate(row["advanced_context_available"] for row in rows),
        "advanced_context_available_by_market_group": _true_rate_by_key(
            rows, key="market_group", value="advanced_context_available"
        ),
        "advanced_context_flag_counts": _flag_counts(row["advanced_context_flags"] for row in rows),
        "advanced_target_shift_mean": _mean(row["advanced_target_shift"] for row in rows),
        "advanced_target_shift_min": _min(row["advanced_target_shift"] for row in rows),
        "advanced_target_shift_max": _max(row["advanced_target_shift"] for row in rows),
        "pitcher_prop_matchup_neutral_count": sum(
            1 for row in rows if "pitcher_prop_matchup_neutral" in row["flags"]
        ),
        "pitcher_prop_context_adjusted_count": sum(
            1 for row in rows if "pitcher_prop_context_target_adjusted" in row["flags"]
        ),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
        "latest_csv_path": str(paths.features / "parameters" / "latest.csv"),
        "latest_json_path": str(paths.features / "parameters" / "latest.json"),
        "latest_manifest_path": str(paths.features / "parameters" / "latest_manifest.json"),
        "columns": list(PARAMETER_COLUMNS),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _copy_latest(csv_path, paths.features / "parameters" / "latest.csv")
    _copy_latest(json_path, paths.features / "parameters" / "latest.json")
    _copy_latest(manifest_path, paths.features / "parameters" / "latest_manifest.json")
    return manifest


def _parameter_row(
    row: dict[str, Any],
    *,
    run_id: str,
    matchup_row: dict[str, Any] | None = None,
    pitcher_prop_row: dict[str, Any] | None = None,
    market_row: dict[str, Any] | None = None,
    advanced_row: dict[str, Any] | None = None,
    player_history_row: dict[str, Any] | None = None,
    pitcher_prop_shift_scale: float = 0.055,
    pitcher_prop_shift_cap: float = 0.06,
) -> dict[str, Any]:
    market = str(row.get("market") or "")
    line = _float(row.get("line"))
    profile = MARKET_PRIOR_PROFILES.get(market)
    opportunity = estimate_opportunity(row)
    player_history = _player_history_values(player_history_row)
    opportunity = _apply_player_history_opportunity(market, opportunity, player_history)
    flags = ["market_prior_parameters_v0"]
    flags.extend(opportunity.flags)
    if profile is None:
        target = 0.50
        flags.append("unknown_market_profile")
    else:
        target = profile.over_probability(line)
    market_context = _market_context_values(market_row)
    if market_context["available"]:
        market_target_before = target
        target = _blend_market_target(target, market, market_context)
        market_shift = round(target - market_target_before, 6)
        flags.append("market_context_target_blended")
    else:
        market_shift = 0.0
        flags.append("market_context_missing")
    matchup = _matchup_values(matchup_row)
    if market in PITCHER_PROP_MARKETS:
        pitcher_matchup = _pitcher_prop_values(pitcher_prop_row)
        if pitcher_matchup["available"]:
            matchup = pitcher_matchup
            target_shift = _pitcher_prop_target_shift(
                pitcher_matchup,
                scale=pitcher_prop_shift_scale,
                cap=pitcher_prop_shift_cap,
            )
            flags.append("pitcher_prop_context_target_adjusted")
        else:
            target_shift = 0.0
            matchup = pitcher_matchup
            matchup["flags"] = tuple(matchup["flags"]) + ("pitcher_prop_matchup_neutral_missing_source_context",)
            flags.append("pitcher_prop_matchup_neutral")
    else:
        target_shift = _target_shift_from_matchup(matchup)
    if matchup["available"]:
        target = _clamp(target + target_shift, 0.03, 0.97)
        flags.append("matchup_context_target_adjusted")
    else:
        flags.append("matchup_context_missing")
    advanced = _advanced_context_values(advanced_row)
    advanced_shift = _target_shift_from_advanced(market, advanced)
    if advanced["available"] and market not in PITCHER_PROP_MARKETS:
        target = _clamp(target + advanced_shift, 0.03, 0.97)
        flags.append("advanced_context_target_adjusted")
    elif advanced["available"] and market in PITCHER_PROP_MARKETS:
        flags.append("advanced_context_neutral_for_pitcher_prop")
        advanced["flags"] = tuple(advanced["flags"]) + ("advanced_context_neutral_for_pitcher_prop",)
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
        "market": market,
        "source_market": str(row.get("source_market") or ""),
        "line": line,
        "tier": str(row.get("tier") or "STANDARD"),
        "target_over_probability": round(target, 6),
        "distribution": default_distribution_for_market(market),
        "simulation_n": DEFAULT_SIMULATION_N,
        "parameter_model_version": PARAMETER_MODEL_VERSION,
        "opportunity_model_version": opportunity.opportunity_model_version,
        "market_group": opportunity.market_group,
        "opportunity_type": opportunity.opportunity_type,
        "projected_opportunity": opportunity.projected_opportunity,
        "opportunity_floor": opportunity.opportunity_floor,
        "opportunity_ceiling": opportunity.opportunity_ceiling,
        "opportunity_confidence": opportunity.opportunity_confidence,
        "opportunity_fragility_score": opportunity.opportunity_fragility_score,
        "player_history_context_available": player_history["available"],
        "plate_appearance_projection": player_history["plate_appearance_projection"],
        "player_history_context_flags": player_history["flags"],
        "market_context_available": market_context["available"],
        "market_line_match_type": market_context["line_match_type"],
        "market_source_line": market_context["source_line"],
        "market_line_delta": market_context["line_delta"],
        "market_over_probability": market_context["over_probability"],
        "market_under_probability": market_context["under_probability"],
        "market_n_books": market_context["n_books"],
        "market_target_blend_weight": market_context["blend_weight"],
        "market_target_shift": market_shift,
        "market_context_flags": market_context["flags"],
        "lineup_score": matchup["lineup_score"],
        "starter_matchup_score": matchup["starter_matchup_score"],
        "bullpen_matchup_score": matchup["bullpen_matchup_score"],
        "environment_score": matchup["environment_score"],
        "matchup_composite_score": matchup["matchup_composite_score"],
        "matchup_confidence": matchup["matchup_confidence"],
        "matchup_context_available": matchup["available"],
        "matchup_target_shift": round(target_shift, 6),
        "matchup_context_flags": matchup["flags"],
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
        "advanced_target_shift": round(advanced_shift, 6),
        "advanced_context_flags": advanced["flags"],
        "flags": flags,
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
    available = bool(confidence > 0.0 and len(flags) < 4)
    return {
        "lineup_score": _float(row.get("lineup_score")),
        "starter_matchup_score": _float(row.get("starter_matchup_score")),
        "bullpen_matchup_score": _float(row.get("bullpen_matchup_score")),
        "environment_score": _float(row.get("environment_score")),
        "matchup_composite_score": _float(row.get("matchup_composite_score")),
        "matchup_confidence": confidence,
        "available": available,
        "flags": flags,
    }


def _pitcher_prop_values(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        matchup = _empty_matchup()
        matchup["flags"] = ("missing_pitcher_prop_context_row",)
        return matchup
    flags = _tuple_flags(row.get("missing_context_flags"))
    confidence = _clamp(_float(row.get("pitcher_prop_confidence")), 0.0, 1.0)
    missing_source = "missing_pitcher_prop_context" in flags
    return {
        "lineup_score": 0.0,
        "starter_matchup_score": _float(row.get("starter_score")),
        "bullpen_matchup_score": _float(row.get("bullpen_support_score")),
        "environment_score": _float(row.get("environment_score")),
        "matchup_composite_score": _float(row.get("pitcher_prop_composite_score")),
        "matchup_confidence": confidence,
        "available": bool(confidence > 0.0 and not missing_source),
        "flags": flags,
    }


def _market_context_values(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row or not _bool(row.get("market_context_available")):
        return {
            "available": False,
            "over_probability": 0.0,
            "under_probability": 0.0,
            "n_books": 0,
            "blend_weight": 0.0,
            "line_match_type": "",
            "source_line": 0.0,
            "line_delta": 0.0,
            "flags": ("missing_market_context",),
        }
    n_books = _int(row.get("market_n_books"))
    line_delta = _clamp(_float(row.get("market_line_delta")), 0.0, 99.0)
    over_probability = _clamp(_float(row.get("market_over_probability")), 0.03, 0.97)
    under_probability = _clamp(_float(row.get("market_under_probability")), 0.03, 0.97)
    flags = _tuple_flags(row.get("market_context_flags"))
    values = {
        "available": True,
        "over_probability": over_probability,
        "under_probability": under_probability,
        "n_books": n_books,
        "line_match_type": str(row.get("market_line_match_type") or ""),
        "source_line": _float(row.get("market_source_line")),
        "line_delta": line_delta,
        "flags": flags,
    }
    values["blend_weight"] = _market_blend_weight(
        n_books=n_books,
        line_delta=line_delta,
        line_match_type=values["line_match_type"],
    )
    return values


def _advanced_context_values(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row or not _bool(row.get("advanced_context_available")):
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
            "flags": ("missing_advanced_context",),
        }
    return {
        "available": True,
        "context_score": _float(row.get("advanced_context_score")),
        "hit_score": _float(row.get("advanced_hit_context_score")),
        "power_score": _float(row.get("advanced_power_context_score")),
        "plate_discipline_score": _float(row.get("advanced_plate_discipline_score")),
        "k_context_score": _float(row.get("advanced_k_context_score")),
        "contact_quality_score": _float(row.get("advanced_contact_quality_score")),
        "sample_confidence": _clamp(_float(row.get("advanced_sample_confidence")), 0.0, 1.0),
        "profile_source": str(row.get("advanced_profile_source") or ""),
        "match_type": str(row.get("advanced_profile_match_type") or ""),
        "flags": _tuple_flags(row.get("advanced_context_flags")),
    }


def _player_history_values(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row or not _bool(row.get("player_history_context_available")):
        return {
            "available": False,
            "plate_appearance_projection": 0.0,
            "confidence": 0.0,
            "flags": ("missing_player_history_context",),
        }
    return {
        "available": True,
        "plate_appearance_projection": _float(row.get("plate_appearance_projection")),
        "confidence": _clamp(_float(row.get("history_context_confidence")), 0.0, 1.0),
        "flags": _tuple_flags(row.get("history_context_flags")),
    }


def _apply_player_history_opportunity(market: str, opportunity, player_history: dict[str, Any]):
    if market not in BATTER_MARKETS or not player_history["available"]:
        return opportunity
    projection = _clamp(_float(player_history["plate_appearance_projection"]), 0.0, 6.2)
    if projection <= 0.0:
        return opportunity
    confidence = _clamp(_float(player_history["confidence"]), 0.0, 1.0)
    blend_weight = _clamp(0.35 + 0.35 * confidence, 0.35, 0.70)
    projected = (1.0 - blend_weight) * float(opportunity.projected_opportunity) + blend_weight * projection
    floor = max(0.0, projected - 1.15)
    ceiling = min(6.5, projected + 1.15)
    return replace(
        opportunity,
        projected_opportunity=round(projected, 4),
        opportunity_floor=round(floor, 4),
        opportunity_ceiling=round(ceiling, 4),
        opportunity_confidence=round(_clamp(max(opportunity.opportunity_confidence, confidence), 0.0, 1.0), 4),
        opportunity_fragility_score=round(_clamp(opportunity.opportunity_fragility_score * 0.85, 0.0, 1.0), 4),
        opportunity_model_version=f"{opportunity.opportunity_model_version}+statsapi_pa_v0",
        flags=tuple(opportunity.flags) + ("statsapi_pa_projection_applied",),
    )


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


def _target_shift_from_matchup(matchup: dict[str, Any]) -> float:
    if not matchup["available"]:
        return 0.0
    composite = _clamp(float(matchup["matchup_composite_score"]), -1.0, 1.0)
    confidence = _clamp(float(matchup["matchup_confidence"]), 0.0, 1.0)
    return round(_clamp(0.08 * composite * confidence, -0.08, 0.08), 6)


def _pitcher_prop_target_shift(matchup: dict[str, Any], *, scale: float = 0.055, cap: float = 0.06) -> float:
    if not matchup["available"]:
        return 0.0
    composite = _clamp(float(matchup["matchup_composite_score"]), -1.0, 1.0)
    confidence = _clamp(float(matchup["matchup_confidence"]), 0.0, 1.0)
    resolved_scale = _clamp(float(scale), 0.0, 0.12)
    resolved_cap = _clamp(float(cap), 0.0, 0.12)
    return round(_clamp(resolved_scale * composite * confidence, -resolved_cap, resolved_cap), 6)


def _target_shift_from_advanced(market: str, advanced: dict[str, Any]) -> float:
    if not advanced["available"] or market in PITCHER_PROP_MARKETS:
        return 0.0
    confidence = _clamp(float(advanced["sample_confidence"]), 0.0, 1.0)
    if market in {"home_runs", "total_bases", "hits_runs_rbis", "hitter_fantasy_score"}:
        signal = 0.55 * float(advanced["power_score"]) + 0.45 * float(advanced["contact_quality_score"])
    elif market in {"hits", "singles"}:
        signal = 0.70 * float(advanced["hit_score"]) + 0.30 * float(advanced["contact_quality_score"])
    elif market == "walks":
        signal = float(advanced["plate_discipline_score"])
    elif market == "hitter_strikeouts":
        signal = float(advanced["k_context_score"])
    elif market == "stolen_bases":
        signal = 0.0
    else:
        signal = float(advanced["context_score"])
    return round(_clamp(0.035 * _clamp(signal, -1.0, 1.0) * confidence, -0.035, 0.035), 6)


def _blend_market_target(target: float, market_name: str, market: dict[str, Any]) -> float:
    weight = _clamp(float(market["blend_weight"]), 0.0, 0.30)
    match_type = str(market.get("line_match_type") or "")
    market_target = _market_target_for_board_line(target, market_name, market)
    if match_type == "wide_nearest":
        weight = min(weight, 0.08)
    return round(_clamp(target * (1.0 - weight) + market_target * weight, 0.03, 0.97), 6)


def _market_target_for_board_line(target: float, market_name: str, market: dict[str, Any]) -> float:
    market_probability = _clamp(float(market["over_probability"]), 0.03, 0.97)
    if str(market.get("line_match_type") or "") == "exact":
        return market_probability
    profile = MARKET_PRIOR_PROFILES.get(market_name)
    if profile is None:
        return market_probability
    source_line = _float(market.get("source_line"))
    source_prior = _clamp(profile.over_probability(source_line), 0.03, 0.97)
    line_delta = _clamp(float(market.get("line_delta") or 0.0), 0.0, 99.0)
    edge = market_probability - source_prior
    if str(market.get("line_match_type") or "") == "wide_nearest":
        edge_shrink = _clamp(0.70 - 0.10 * line_delta, 0.25, 0.60)
    else:
        edge_shrink = _clamp(1.00 - 0.18 * line_delta, 0.65, 1.00)
    return _clamp(target + edge * edge_shrink, 0.03, 0.97)


def _market_blend_weight(*, n_books: int, line_delta: float = 0.0, line_match_type: str = "") -> float:
    if n_books <= 0:
        return 0.0
    base = _clamp(0.10 + 0.035 * min(n_books, 6), 0.0, 0.30)
    if line_match_type == "wide_nearest":
        base *= max(0.08, 0.25 / max(line_delta, 1.0))
    elif line_delta > 0.0:
        base *= max(0.35, 1.0 - line_delta)
    return round(_clamp(base, 0.0, 0.30), 6)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=PARAMETER_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in PARAMETER_COLUMNS})


def _copy_latest(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


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


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _line_key(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


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


def _min(values) -> float | None:
    collected = [float(value) for value in values]
    return round(min(collected), 6) if collected else None


def _max(values) -> float | None:
    collected = [float(value) for value in values]
    return round(max(collected), 6) if collected else None


def _true_rate(values) -> float | None:
    collected = [bool(value) for value in values]
    if not collected:
        return None
    return round(sum(1 for value in collected if value) / len(collected), 6)


def _true_rate_by_key(rows: list[dict[str, Any]], *, key: str, value: str) -> dict[str, float]:
    grouped: dict[str, list[bool]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key) or ""), []).append(bool(row.get(value)))
    return {
        group: round(sum(1 for item in values if item) / len(values), 6)
        for group, values in sorted(grouped.items())
        if values
    }


def _flag_counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        for flag in _tuple_flags(value):
            counts[flag] = counts.get(flag, 0) + 1
    return dict(sorted(counts.items()))
