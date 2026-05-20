"""Operator input packets for deterministic and AI-assisted review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mlb.evaluation.schemas import Anomaly

OPERATOR_PACKET_SCHEMA_VERSION = "atlas_mlb_operator_input_v0"


def write_operator_input_packet(
    *,
    run_dir: Path,
    run_packet: dict[str, Any],
    score_manifest: dict[str, Any],
    feature_manifest: dict[str, Any],
    parameter_manifest: dict[str, Any],
    slips_manifest: dict[str, Any],
    anomalies: tuple[Anomaly, ...],
) -> dict[str, Any]:
    """Write the compact packet future OpenAI review should consume."""

    operator_dir = run_dir / "operator"
    operator_dir.mkdir(parents=True, exist_ok=True)
    scored_payload = _load_json(run_dir / "scored_legs.json")
    simulation_manifest = _load_json(run_dir / "simulation_manifest.json")
    top_legs = _top_legs(scored_payload.get("scored_legs", []))
    packet_path = operator_dir / "operator_input.json"
    packet = {
        "schema_version": OPERATOR_PACKET_SCHEMA_VERSION,
        "run_id": run_packet["run_id"],
        "run_mode": run_packet["run_mode"],
        "ai_role": "review_only_no_probability_mutation",
        "guardrails": [
            "OpenAI may summarize, detect anomalies, and recommend operator actions.",
            "OpenAI must not overwrite model_probability, side, simulation output, or publish decisions without deterministic validation.",
            "Probability changes must enter through versioned parameters, calibration, or simulator code.",
        ],
        "counts": {
            "board_count": run_packet.get("board_count"),
            "scored_candidate_count": run_packet.get("scored_candidate_count"),
            "slip_count": run_packet.get("slip_count"),
            "unsupported_market_count": run_packet.get("unsupported_market_count"),
        },
        "score_summary": {
            "model_probability_min": score_manifest.get("model_probability_min"),
            "model_probability_max": score_manifest.get("model_probability_max"),
            "side_counts": score_manifest.get("side_counts"),
            "confidence_tier_counts": score_manifest.get("confidence_tier_counts"),
            "market_counts": score_manifest.get("market_counts"),
        },
        "simulation_summary": simulation_manifest,
        "feature_summary": {
            "feature_model_version": feature_manifest.get("feature_model_version"),
            "market_group_counts": feature_manifest.get("market_group_counts"),
            "opportunity_model_versions": feature_manifest.get("opportunity_model_versions"),
            "opportunity_type_counts": feature_manifest.get("opportunity_type_counts"),
            "source_completeness": feature_manifest.get("source_completeness"),
        },
        "parameter_summary": {
            "parameter_model_version": parameter_manifest.get("parameter_model_version"),
            "opportunity_model_versions": parameter_manifest.get("opportunity_model_versions"),
            "market_group_counts": parameter_manifest.get("market_group_counts"),
            "opportunity_type_counts": parameter_manifest.get("opportunity_type_counts"),
            "opportunity_confidence_mean": parameter_manifest.get("opportunity_confidence_mean"),
            "matchup_context_available_rate": parameter_manifest.get("matchup_context_available_rate"),
            "matchup_context_available_by_market_group": parameter_manifest.get(
                "matchup_context_available_by_market_group"
            ),
            "matchup_context_flag_counts": parameter_manifest.get("matchup_context_flag_counts"),
            "matchup_target_shift_mean": parameter_manifest.get("matchup_target_shift_mean"),
            "matchup_target_shift_min": parameter_manifest.get("matchup_target_shift_min"),
            "matchup_target_shift_max": parameter_manifest.get("matchup_target_shift_max"),
            "market_context_available_rate": parameter_manifest.get("market_context_available_rate"),
            "market_context_available_by_market_group": parameter_manifest.get(
                "market_context_available_by_market_group"
            ),
            "market_context_flag_counts": parameter_manifest.get("market_context_flag_counts"),
            "market_target_shift_mean": parameter_manifest.get("market_target_shift_mean"),
            "market_target_shift_min": parameter_manifest.get("market_target_shift_min"),
            "market_target_shift_max": parameter_manifest.get("market_target_shift_max"),
            "market_target_blend_weight_mean": parameter_manifest.get("market_target_blend_weight_mean"),
            "pitcher_prop_matchup_neutral_count": parameter_manifest.get("pitcher_prop_matchup_neutral_count"),
        },
        "slip_summary": _slip_summary(slips_manifest),
        "top_legs": top_legs,
        "anomalies": [anomaly.to_dict() for anomaly in anomalies],
        "artifacts": {
            "scored_legs_json": str(run_dir / "scored_legs.json"),
            "scored_legs_csv": score_manifest.get("csv_path"),
            "scored_legs_deduped_csv": score_manifest.get("deduped_csv_path"),
            "score_manifest": score_manifest.get("manifest_path"),
            "simulation_manifest": score_manifest.get("simulation_manifest_path"),
            "feature_manifest": feature_manifest.get("manifest_path"),
            "parameter_manifest": parameter_manifest.get("manifest_path"),
            "slips_manifest": slips_manifest.get("manifest_path"),
            "operator_input": str(packet_path),
        },
    }
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "schema_version": OPERATOR_PACKET_SCHEMA_VERSION,
        "path": str(packet_path),
        "top_leg_count": len(top_legs),
    }


def _top_legs(rows: list[Any], *, limit: int = 25) -> list[dict[str, Any]]:
    typed_rows = [row for row in rows if isinstance(row, dict)]
    ranked = sorted(
        typed_rows,
        key=lambda row: (
            float(row.get("model_probability") or 0.0),
            float(row.get("stability_score") or 0.0),
            -float(row.get("opportunity_fragility_score") or 0.0),
        ),
        reverse=True,
    )
    keys = (
        "player_name",
        "player_team",
        "opponent",
        "market",
        "line",
        "side",
        "model_probability",
        "over_probability",
        "under_probability",
        "mean_projection",
        "p25",
        "p75",
        "opportunity_type",
        "projected_opportunity",
        "opportunity_confidence",
        "opportunity_fragility_score",
        "fragility_score",
        "stability_score",
        "confidence_tier",
        "flags",
    )
    return [{key: row.get(key) for key in keys} for row in ranked[:limit]]


def _slip_summary(slips_manifest: dict[str, Any]) -> dict[str, Any]:
    families = slips_manifest.get("families") if isinstance(slips_manifest.get("families"), dict) else {}
    return {
        "family_count": slips_manifest.get("family_count"),
        "slip_count": slips_manifest.get("slip_count"),
        "single_game_slate": slips_manifest.get("single_game_slate"),
        "tier_mix_contract": slips_manifest.get("tier_mix_contract"),
        "tier_direction_filters": slips_manifest.get("tier_direction_filters"),
        "portfolio_policy": slips_manifest.get("portfolio_policy"),
        "families": {
            family: {
                "slip_count": value.get("slip_count"),
                "target_leg_counts": value.get("target_leg_counts"),
                "tier_mixes": value.get("tier_mixes"),
                "tier_templates": value.get("tier_templates"),
                "csv_path": value.get("csv_path"),
                "json_path": value.get("json_path"),
                "csv_paths": value.get("csv_paths"),
                "json_paths": value.get("json_paths"),
            }
            for family, value in families.items()
            if isinstance(value, dict)
        },
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
