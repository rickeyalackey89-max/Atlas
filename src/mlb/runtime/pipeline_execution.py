"""Executable MLB pipeline boundaries.

The CLI calls this module; orchestration details stay out of ``cli.py``.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - defensive fallback for stripped Python installs
    ZoneInfo = None  # type: ignore[assignment]

from mlb.evaluation.anomaly_checks import run_deterministic_anomaly_checks
from mlb.evaluation.artifacts import write_operator_artifacts
from mlb.evaluation.openai_evaluator import evaluate_with_openai, openai_evaluator_enabled
from mlb.evaluation.publish_decision import build_publish_decision
from mlb.modeling.calibration import apply_parameter_calibration
from mlb.modeling.engine import score_engine_board
from mlb.modeling.features import build_player_prop_feature_table
from mlb.modeling.parameters import build_parameter_table
from mlb.fetchers.bettingpros import (
    BETTINGPROS_MLB_PROPS_SOURCE,
    fetch_bettingpros_mlb_props,
    parse_bettingpros_book_ids,
)
from mlb.fetchers.draftkings import (
    DRAFTKINGS_MLB_PICK6_SOURCE,
    DRAFTKINGS_MLB_SPORTSBOOK_SOURCE,
    fetch_draftkings_mlb_pick6,
    fetch_draftkings_mlb_sportsbook_props,
)
from mlb.normalizers.bettingpros import write_bettingpros_mlb_normalization
from mlb.normalizers.draftkings_pick6 import write_draftkings_pick6_normalization
from mlb.normalizers.draftkings_sportsbook import write_draftkings_sportsbook_normalization
from mlb.normalizers.prizepicks import BoardNormalizationResult, write_prizepicks_board_normalization
from mlb.runtime.advanced_context import build_advanced_context_artifacts
from mlb.runtime.config import active_mlb_config_manifest, load_active_mlb_config
from mlb.runtime.engine_inputs import publish_engine_board
from mlb.runtime.fidelity import fidelity_policy, normalize_run_mode
from mlb.runtime.injury_context import build_injury_context_artifacts
from mlb.runtime.market_context import build_market_context_artifacts
from mlb.runtime.matchups import build_matchup_context_artifacts
from mlb.runtime.operator_packet import write_operator_input_packet
from mlb.runtime.paths import ensure_mlb_dirs, output_runs_dir
from mlb.runtime.player_history_context import build_player_history_context_artifacts
from mlb.runtime.replay_eval import evaluate_scored_run
from mlb.runtime.results import RuntimeCommandResult
from mlb.runtime.roster_context import build_roster_context_artifacts
from mlb.runtime.runtime_state import publish_run_runtime_state
from mlb.runtime.slips import build_slip_families_from_scored_run
from mlb.runtime.source_contract import enforce_replay_source_contract
from mlb.runtime.source_operations import (
    fetch_baseball_savant_result,
    fetch_espn_game_context_result,
    fetch_injuries_result,
    fetch_rotowire_result,
    fetch_statsapi_rosters_bulk_result,
    fetch_statsapi_schedule_result,
    fetch_statsapi_teams_result,
    fetch_statsapi_transactions_result,
    latest_snapshot_path,
)
from mlb.runtime.statsapi_context import build_statsapi_context_artifacts
from mlb.runtime.transaction_context import build_transaction_context_artifacts
from mlb.sources.catalog import MLB_STATSAPI_MAJOR_SPORT_ID

DK_GAP_FILL_MARKETS = {
    "hitter_fantasy_score": {
        "availability": "limited_featured_hitters",
        "expected_sources": (DRAFTKINGS_MLB_PICK6_SOURCE,),
        "notes": "DraftKings Pick6 usually exposes only a few hitter fantasy rows per game.",
    },
    "pitcher_fantasy_score": {
        "availability": "not_currently_offered",
        "expected_sources": (),
        "notes": "No confirmed DraftKings pitcher fantasy feed; do not treat as a source failure.",
    },
    "hitter_strikeouts": {
        "availability": "sportsbook_milestone",
        "expected_sources": (DRAFTKINGS_MLB_SPORTSBOOK_SOURCE,),
        "notes": "DraftKings Sportsbook exposes batter strikeout milestone prices when posted.",
    },
    "walks": {
        "availability": "sportsbook_ou_and_milestone",
        "expected_sources": (DRAFTKINGS_MLB_SPORTSBOOK_SOURCE,),
        "notes": "DraftKings Sportsbook exposes batter walks O/U for a player subset.",
    },
    "stolen_bases": {
        "availability": "sportsbook_ou_pick6_milestone",
        "expected_sources": (DRAFTKINGS_MLB_SPORTSBOOK_SOURCE, DRAFTKINGS_MLB_PICK6_SOURCE),
        "notes": "DraftKings Sportsbook exposes stolen bases O/U for a player subset.",
    },
    "pitches_thrown": {
        "availability": "not_confirmed_in_current_feed",
        "expected_sources": (),
        "notes": "Keep monitored, but do not fail live runs until a stable DK category is confirmed.",
    },
}

DK_REPLAY_SOURCE_START_DATES = {
    DRAFTKINGS_MLB_PICK6_SOURCE: "2026-05-18",
    DRAFTKINGS_MLB_SPORTSBOOK_SOURCE: "2026-05-19",
}


def run_board_pipeline_result(
    *,
    snapshot_path: Path | None = None,
    normalized_dir: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    run_mode: str = "replay",
    game_date: str | None = None,
    include_all_dates: bool = False,
    refresh_context_sources: bool = False,
    rotowire_pages: str | tuple[str, ...] | None = None,
    baseball_savant_pages: str | tuple[str, ...] | None = None,
    baseball_savant_season: int = 2026,
    include_espn_backfill: bool | None = None,
    refresh_bettingpros_odds: bool = True,
    calibration_artifact_path: Path | None = None,
    emit_progress: Callable[[str], None] | None = None,
) -> RuntimeCommandResult:
    manifest = run_board_pipeline(
        snapshot_path=snapshot_path,
        normalized_dir=normalized_dir,
        root=root,
        run_id=run_id,
        run_mode=run_mode,
        game_date=game_date,
        include_all_dates=include_all_dates,
        refresh_context_sources=refresh_context_sources,
        rotowire_pages=rotowire_pages,
        baseball_savant_pages=baseball_savant_pages,
        baseball_savant_season=baseball_savant_season,
        include_espn_backfill=include_espn_backfill,
        refresh_bettingpros_odds=refresh_bettingpros_odds,
        calibration_artifact_path=calibration_artifact_path,
        emit_progress=emit_progress,
    )
    lines = [
        "Executed MLB board pipeline:",
        f"  run_id: {manifest['run_id']}",
        f"  run_mode: {manifest['run_mode']}",
        f"  game_date_filter: {manifest['game_date_filter'] or 'all'}",
        f"  normalized_count: {manifest['normalized']['normalized_count']}",
        f"  engine_board_rows: {manifest['engine_board']['row_count']}",
        f"  dropped_by_date_filter: {manifest['engine_board'].get('dropped_by_date_filter_count', 0)}",
        f"  context_sources_refreshed: {manifest['context_source_refresh']['enabled']}",
        f"  primary_market_source: {manifest['primary_market_source'].get('status')}",
        f"  scored_legs: {manifest['score']['row_count']}",
        f"  slip_count: {manifest['slips']['slip_count']}",
        f"  publish_allowed: {manifest['operator']['publish_allowed']}",
        f"  run_manifest: {manifest['manifest_path']}",
    ]
    return RuntimeCommandResult(name="run_board_pipeline", payload=manifest, lines=tuple(lines))


def run_board_pipeline(
    *,
    snapshot_path: Path | None = None,
    normalized_dir: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    run_mode: str = "replay",
    game_date: str | None = None,
    include_all_dates: bool = False,
    refresh_context_sources: bool = False,
    rotowire_pages: str | tuple[str, ...] | None = None,
    baseball_savant_pages: str | tuple[str, ...] | None = None,
    baseball_savant_season: int = 2026,
    include_espn_backfill: bool | None = None,
    refresh_bettingpros_odds: bool = True,
    calibration_artifact_path: Path | None = None,
    emit_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    paths = ensure_mlb_dirs(root)
    config_payload = load_active_mlb_config(paths.repo_root)
    config_manifest = active_mlb_config_manifest(paths.repo_root)
    if snapshot_path and normalized_dir:
        raise ValueError("Pass either snapshot_path or normalized_dir, not both")
    canonical_run_mode = normalize_run_mode(run_mode)
    run_fidelity_policy = fidelity_policy(canonical_run_mode)
    if include_espn_backfill:
        raise ValueError("ESPN postgame backfill cannot feed a live-fidelity board pipeline run")
    _progress(emit_progress, _progress_banner("LOAD/NORMALIZE PRIZEPICKS BOARD", str(snapshot_path or normalized_dir or "latest")))
    normalized_source = _resolve_normalized_source(
        snapshot_path=snapshot_path,
        normalized_dir=normalized_dir,
        root=root,
        run_id=run_id,
    )
    resolved_snapshot = normalized_source["source_path"]
    normalized = normalized_source["normalized"]
    resolved_run_id = run_id or normalized.run_id
    replay_source_as_of_utc = None if canonical_run_mode == "live" else _normalized_source_as_of(normalized)
    _progress(
        emit_progress,
        f"[BOARD NORMALIZED] source_type={normalized_source['source_type']} "
        f"normalized_count={len(normalized.rows)} rejected_count={len(normalized.rejects)} "
        f"output_dir={normalized.output_dir}",
    )
    _progress(emit_progress, _progress_banner("PUBLISH ENGINE BOARD", resolved_run_id))
    engine_board = publish_engine_board(
        normalized_dir=normalized.output_dir,
        root=root,
        run_id=resolved_run_id,
        game_date=game_date,
        include_all_dates=include_all_dates,
        exclude_started_games=canonical_run_mode == "live",
    )
    _progress(
        emit_progress,
        f"[ENGINE BOARD] rows={engine_board.get('row_count', 0)} "
        f"game_date_filter={engine_board.get('game_date_filter', '')} "
        f"dropped_by_date_filter={engine_board.get('dropped_by_date_filter_count', 0)} "
        f"json={engine_board.get('json_path', '')}",
    )
    resolved_game_date = str(engine_board.get("game_date_filter") or game_date or "")
    context_source_refresh = _refresh_context_sources(
        enabled=refresh_context_sources or canonical_run_mode == "live",
        root=root,
        game_date=resolved_game_date,
        include_espn_backfill=False if include_espn_backfill is None else bool(include_espn_backfill),
        rotowire_pages=rotowire_pages,
        baseball_savant_pages=baseball_savant_pages,
        baseball_savant_season=baseball_savant_season,
        include_live_identity_sources=canonical_run_mode == "live",
        emit_progress=emit_progress,
    )
    _progress(emit_progress, _progress_banner("FETCH BETTINGPROS PRIMARY MARKET ODDS", resolved_game_date))
    primary_market_source = _ensure_primary_market_source(
        enabled=refresh_bettingpros_odds,
        root=root,
        game_date=resolved_game_date,
        run_mode=canonical_run_mode,
    )
    _progress(
        emit_progress,
        f"[BETTINGPROS] status={primary_market_source.get('status')} "
        f"rows={primary_market_source.get('row_count', 0)} "
        f"snapshot={primary_market_source.get('snapshot_id', '')} "
        f"errors={len(primary_market_source.get('errors') or [])}",
    )
    for error in primary_market_source.get("errors") or []:
        _progress(emit_progress, f"[BETTINGPROS ERROR] {error.get('reason', error)}")
    _progress(emit_progress, _progress_banner("FETCH DRAFTKINGS PICK6 SUPPLEMENTAL MARKET LINES", resolved_game_date))
    draftkings_pick6_source = _ensure_draftkings_pick6_source(
        enabled=_market_source_feature_enabled(config_payload, "draftkings_pick6_alignment_enabled", default=False),
        root=root,
        game_date=resolved_game_date,
        run_mode=canonical_run_mode,
        source_as_of_utc=replay_source_as_of_utc,
    )
    _progress(
        emit_progress,
        f"[DRAFTKINGS PICK6] status={draftkings_pick6_source.get('status')} "
        f"rows={draftkings_pick6_source.get('row_count', 0)} "
        f"compatible_rows={draftkings_pick6_source.get('compatible_row_count', 0)} "
        f"snapshot={draftkings_pick6_source.get('snapshot_id', '')} "
        f"errors={len(draftkings_pick6_source.get('errors') or [])}",
    )
    for error in draftkings_pick6_source.get("errors") or []:
        _progress(emit_progress, f"[DRAFTKINGS PICK6 ERROR] {error.get('reason', error)}")
    _progress(emit_progress, _progress_banner("FETCH DRAFTKINGS SPORTSBOOK SUPPLEMENTAL MARKET ODDS", resolved_game_date))
    draftkings_sportsbook_source = _ensure_draftkings_sportsbook_source(
        enabled=_market_source_feature_enabled(
            config_payload,
            "draftkings_sportsbook_alignment_enabled",
            default=False,
        ),
        root=root,
        game_date=resolved_game_date,
        run_mode=canonical_run_mode,
        source_as_of_utc=replay_source_as_of_utc,
    )
    _progress(
        emit_progress,
        f"[DRAFTKINGS SPORTSBOOK] status={draftkings_sportsbook_source.get('status')} "
        f"rows={draftkings_sportsbook_source.get('row_count', 0)} "
        f"snapshot={draftkings_sportsbook_source.get('snapshot_id', '')} "
        f"errors={len(draftkings_sportsbook_source.get('errors') or [])}",
    )
    for error in draftkings_sportsbook_source.get("errors") or []:
        _progress(emit_progress, f"[DRAFTKINGS SPORTSBOOK ERROR] {error.get('reason', error)}")
    market_source_dirs = _market_source_dirs_for_run(
        root=root,
        game_date=resolved_game_date,
        primary_market_source=primary_market_source,
        supplemental_market_sources=[draftkings_pick6_source, draftkings_sportsbook_source],
        run_mode=canonical_run_mode,
    )
    _progress(
        emit_progress,
        f"[MARKET SOURCE CONTRACT] selected_dirs={len(market_source_dirs)} "
        f"run_mode={canonical_run_mode}",
    )
    _progress(emit_progress, _progress_banner("BUILD MARKET CONTEXT", resolved_run_id))
    market_context_manifest = build_market_context_artifacts(
        engine_board_path=Path(engine_board["json_path"]),
        root=root,
        run_id=resolved_run_id,
        game_date=resolved_game_date,
        market_source_dirs=market_source_dirs,
    )
    _progress(emit_progress, _context_line("MARKET_CONTEXT", market_context_manifest))
    _progress(emit_progress, _progress_banner("BUILD INJURY CONTEXT", resolved_run_id))
    injury_context_manifest = build_injury_context_artifacts(
        engine_board_path=Path(engine_board["json_path"]),
        root=root,
        run_id=resolved_run_id,
        game_date=resolved_game_date,
    )
    _progress(emit_progress, _context_line("INJURY_CONTEXT", injury_context_manifest))
    _progress(emit_progress, _progress_banner("BUILD STATSAPI CONTEXT", resolved_run_id))
    statsapi_context_manifest = build_statsapi_context_artifacts(
        engine_board_path=Path(engine_board["json_path"]),
        root=root,
        run_id=resolved_run_id,
        game_date=resolved_game_date,
    )
    _progress(emit_progress, _context_line("STATSAPI_CONTEXT", statsapi_context_manifest))
    _progress(emit_progress, _progress_banner("BUILD ROSTER CONTEXT", resolved_run_id))
    roster_context_manifest = build_roster_context_artifacts(
        engine_board_path=Path(engine_board["json_path"]),
        statsapi_context_path=Path(statsapi_context_manifest["json_path"]),
        root=root,
        run_id=resolved_run_id,
        game_date=resolved_game_date,
    )
    _progress(emit_progress, _context_line("ROSTER_CONTEXT", roster_context_manifest))
    _progress(emit_progress, _progress_banner("BUILD PLAYER HISTORY CONTEXT", resolved_run_id))
    player_history_context_manifest = build_player_history_context_artifacts(
        engine_board_path=Path(engine_board["json_path"]),
        roster_context_path=Path(roster_context_manifest["json_path"]),
        root=root,
        run_id=resolved_run_id,
        game_date=resolved_game_date,
    )
    _progress(emit_progress, _context_line("PLAYER_HISTORY_CONTEXT", player_history_context_manifest))
    _progress(emit_progress, _progress_banner("BUILD TRANSACTION CONTEXT", resolved_run_id))
    transaction_context_manifest = build_transaction_context_artifacts(
        engine_board_path=Path(engine_board["json_path"]),
        roster_context_path=Path(roster_context_manifest["json_path"]),
        root=root,
        run_id=resolved_run_id,
        game_date=resolved_game_date,
    )
    _progress(emit_progress, _context_line("TRANSACTION_CONTEXT", transaction_context_manifest))
    _progress(emit_progress, _progress_banner("BUILD MATCHUP / WEATHER CONTEXT", resolved_run_id))
    matchup_manifest = build_matchup_context_artifacts(
        engine_board_path=Path(engine_board["json_path"]),
        player_history_context_path=Path(player_history_context_manifest["json_path"]),
        root=root,
        run_id=resolved_run_id,
        game_date=resolved_game_date,
    )
    _progress(emit_progress, _context_line("MATCHUP_CONTEXT", matchup_manifest))
    _progress(emit_progress, _progress_banner("BUILD ADVANCED CONTEXT", resolved_run_id))
    advanced_context_manifest = build_advanced_context_artifacts(
        engine_board_path=Path(engine_board["json_path"]),
        roster_context_path=Path(roster_context_manifest["json_path"]),
        root=root,
        run_id=resolved_run_id,
        game_date=resolved_game_date,
    )
    _progress(emit_progress, _context_line("ADVANCED_CONTEXT", advanced_context_manifest))
    _progress(emit_progress, _progress_banner("BUILD FEATURE TABLE", resolved_run_id))
    feature_manifest = build_player_prop_feature_table(
        engine_board_path=Path(engine_board["json_path"]),
        matchup_context_path=Path(matchup_manifest["json_path"]),
        market_context_path=Path(market_context_manifest["json_path"]),
        injury_context_path=Path(injury_context_manifest["json_path"]),
        statsapi_context_path=Path(statsapi_context_manifest["json_path"]),
        roster_context_path=Path(roster_context_manifest["json_path"]),
        player_history_context_path=Path(player_history_context_manifest["json_path"]),
        transaction_context_path=Path(transaction_context_manifest["json_path"]),
        advanced_context_path=Path(advanced_context_manifest["json_path"]),
        pitcher_prop_context_path=Path(matchup_manifest["pitcher_prop_json_path"]),
        root=root,
        run_id=resolved_run_id,
    )
    _progress(emit_progress, _feature_line(feature_manifest))
    run_dir = output_runs_dir(paths, canonical_run_mode) / resolved_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    feature_completeness = feature_manifest.get("source_completeness", {})
    source_selection_manifest = _write_source_selection_manifest(
        run_dir=run_dir,
        run_id=resolved_run_id,
        run_mode=canonical_run_mode,
        game_date=resolved_game_date,
        config_payload=config_payload,
        selected_market_source_dirs=market_source_dirs,
        primary_market_source=primary_market_source,
        supplemental_market_sources=[draftkings_pick6_source, draftkings_sportsbook_source],
        context_source_refresh=context_source_refresh,
        engine_board=engine_board,
        market_context_manifest=market_context_manifest,
        injury_context_manifest=injury_context_manifest,
        statsapi_context_manifest=statsapi_context_manifest,
        roster_context_manifest=roster_context_manifest,
        player_history_context_manifest=player_history_context_manifest,
        transaction_context_manifest=transaction_context_manifest,
        matchup_manifest=matchup_manifest,
        advanced_context_manifest=advanced_context_manifest,
        feature_manifest=feature_manifest,
    )
    _progress(
        emit_progress,
        f"[SOURCE CONTRACT] status={source_selection_manifest.get('contract_status')} "
        f"failures={source_selection_manifest.get('failure_count', 0)} "
        f"warnings={source_selection_manifest.get('warning_count', 0)} "
        f"manifest={source_selection_manifest.get('manifest_path')}",
    )
    enforce_replay_source_contract(source_selection_manifest, context="run_board_pipeline")
    _progress(emit_progress, _progress_banner("BUILD PARAMETER TABLE", resolved_run_id))
    parameter_manifest = build_parameter_table(
        engine_board_path=Path(engine_board["json_path"]),
        matchup_context_path=Path(matchup_manifest["json_path"]),
        pitcher_prop_context_path=Path(matchup_manifest["pitcher_prop_json_path"]),
        market_context_path=Path(market_context_manifest["json_path"]),
        advanced_context_path=Path(advanced_context_manifest["json_path"]),
        player_history_context_path=Path(player_history_context_manifest["json_path"]),
        pitcher_prop_shift_scale=_config_float(
            config_payload,
            ("matchup_matrix", "pitcher_prop", "target_shift_scale"),
            default=0.055,
        ),
        pitcher_prop_shift_cap=_config_float(
            config_payload,
            ("matchup_matrix", "pitcher_prop", "target_shift_cap"),
            default=0.06,
        ),
        root=root,
        run_id=resolved_run_id,
    )
    _progress(emit_progress, _parameter_line(parameter_manifest))
    raw_parameter_manifest = parameter_manifest
    calibration_manifest = None
    scoring_parameter_path = Path(parameter_manifest["json_path"])
    if calibration_artifact_path is not None:
        _progress(emit_progress, _progress_banner("APPLY CALIBRATION ARTIFACT", str(calibration_artifact_path)))
        calibration_manifest = apply_parameter_calibration(
            parameter_table_path=scoring_parameter_path,
            feature_table_path=Path(feature_manifest["json_path"]),
            calibration_artifact_path=calibration_artifact_path,
            root=root,
            run_id=resolved_run_id,
        )
        scoring_parameter_path = Path(calibration_manifest["json_path"])
        _progress(
            emit_progress,
            f"[CALIBRATION] version={calibration_manifest.get('calibration_version', '')} "
            f"rows={calibration_manifest.get('row_count', '')} json={calibration_manifest.get('json_path', '')}",
        )
    _progress(emit_progress, _progress_banner("SCORE LEGS", resolved_run_id))
    score_manifest = score_engine_board(
        engine_board_path=Path(engine_board["json_path"]),
        parameter_table_path=scoring_parameter_path,
        feature_table_path=Path(feature_manifest["json_path"]),
        root=root,
        run_id=resolved_run_id,
        run_mode=canonical_run_mode,
    )
    _progress(
        emit_progress,
        f"[SCORE] rows={score_manifest.get('row_count', 0)} "
        f"p_min={score_manifest.get('model_probability_min', '')} "
        f"p_max={score_manifest.get('model_probability_max', '')} "
        f"csv={score_manifest.get('csv_path', '')}",
    )
    _progress(emit_progress, _progress_banner("BUILD SLIPS AND QUOTE PAYOUTS", str(run_dir)))
    slips_manifest = build_slip_families_from_scored_run(run_dir)
    _progress(
        emit_progress,
        f"[SLIPS] count={slips_manifest.get('slip_count', 0)} families={list((slips_manifest.get('families') or {}).keys())} "
        f"payout={_payout_line(slips_manifest)}",
    )
    pitcher_prop_count = int(feature_manifest.get("market_group_counts", {}).get("pitcher", 0))
    run_packet = {
        "run_id": resolved_run_id,
        "run_mode": canonical_run_mode,
        "replay_type": run_fidelity_policy["replay_type"],
        "fidelity_policy": run_fidelity_policy,
        "mlb_config": config_manifest,
        "readiness_gates": config_manifest.get("readiness_gates", {}),
        "mlb_config_version": config_manifest["config_version"],
        "mlb_config_hash": config_manifest["sha256"],
        "game_date_filter": engine_board.get("game_date_filter", ""),
        "board_count": engine_board["row_count"],
        "normalized_candidate_count": engine_board["row_count"],
        "normalized_source_count": len(normalized.rows),
        "dropped_by_date_filter_count": engine_board.get("dropped_by_date_filter_count", 0),
        "unsupported_market_count": len(normalized.rejects),
        "scored_candidate_count": score_manifest["row_count"],
        "score_count": score_manifest["row_count"],
        "slip_count": slips_manifest["slip_count"],
        "model_probability_min": score_manifest["model_probability_min"],
        "model_probability_max": score_manifest["model_probability_max"],
        "source_completeness": feature_completeness,
        "source_refresh_error_count": len(context_source_refresh.get("errors") or []),
        "source_refresh_errors": context_source_refresh.get("errors") or [],
        "source_contract_status": source_selection_manifest.get("contract_status"),
        "source_contract_warning_count": source_selection_manifest.get("warning_count", 0),
        "source_contract_warnings": source_selection_manifest.get("warnings", []),
        "primary_market_source_status": primary_market_source.get("status"),
        "primary_market_source_errors": primary_market_source.get("errors") or [],
        "supplemental_market_sources": [draftkings_pick6_source, draftkings_sportsbook_source],
        "matchup_context_available_by_market_group": parameter_manifest.get(
            "matchup_context_available_by_market_group", {}
        ),
        "matchup_context_flag_counts": parameter_manifest.get("matchup_context_flag_counts", {}),
        "matchup_target_shift_mean": parameter_manifest.get("matchup_target_shift_mean"),
        "matchup_target_shift_min": parameter_manifest.get("matchup_target_shift_min"),
        "matchup_target_shift_max": parameter_manifest.get("matchup_target_shift_max"),
        "advanced_context_available_rate": parameter_manifest.get("advanced_context_available_rate"),
        "advanced_context_available_by_market_group": parameter_manifest.get(
            "advanced_context_available_by_market_group", {}
        ),
        "advanced_context_flag_counts": parameter_manifest.get("advanced_context_flag_counts", {}),
        "advanced_target_shift_mean": parameter_manifest.get("advanced_target_shift_mean"),
        "advanced_target_shift_min": parameter_manifest.get("advanced_target_shift_min"),
        "advanced_target_shift_max": parameter_manifest.get("advanced_target_shift_max"),
        "market_context_available_rate": parameter_manifest.get("market_context_available_rate"),
        "market_context_available_by_market_group": parameter_manifest.get(
            "market_context_available_by_market_group", {}
        ),
        "market_context_flag_counts": parameter_manifest.get("market_context_flag_counts", {}),
        "market_target_shift_mean": parameter_manifest.get("market_target_shift_mean"),
        "market_target_shift_min": parameter_manifest.get("market_target_shift_min"),
        "market_target_shift_max": parameter_manifest.get("market_target_shift_max"),
        "calibration_artifact_path": str(calibration_artifact_path) if calibration_artifact_path else "",
        "calibration_version": (calibration_manifest or {}).get("calibration_version", ""),
        "pitcher_prop_matchup_neutral_count": parameter_manifest.get("pitcher_prop_matchup_neutral_count", 0),
        "pitcher_prop_count": pitcher_prop_count,
        "missing_pitcher_context_count": _missing_live_context_count(
            run_mode=canonical_run_mode,
            total_count=pitcher_prop_count,
            completeness=feature_completeness.get("probable_pitcher_context_available"),
        ),
        "ai_status": "not_requested",
    }
    _progress(emit_progress, _progress_banner("RUN OPERATOR CHECKS", resolved_run_id))
    anomalies = run_deterministic_anomaly_checks(run_packet)
    _progress(emit_progress, f"[OPERATOR CHECKS] anomalies={len(anomalies)}")
    operator_input = write_operator_input_packet(
        run_dir=run_dir,
        run_packet=run_packet,
        score_manifest=score_manifest,
        feature_manifest=feature_manifest,
        parameter_manifest=parameter_manifest,
        slips_manifest=slips_manifest,
        anomalies=anomalies,
    )
    ai_evaluation = None
    if openai_evaluator_enabled():
        _progress(emit_progress, "[OPENAI EVAL] enabled; requesting operator evaluation")
        ai_evaluation = evaluate_with_openai(json.loads(Path(operator_input["path"]).read_text(encoding="utf-8")))
        run_packet["ai_status"] = ai_evaluation.get("ai_status", "error")
        run_packet["ai_model"] = ai_evaluation.get("ai_model")
        _progress(
            emit_progress,
            f"[OPENAI EVAL] status={ai_evaluation.get('ai_status', '')} model={ai_evaluation.get('ai_model', '')}",
        )

    decision = build_publish_decision(run_packet, anomalies, ai_decision=ai_evaluation)
    operator_dir = run_dir / "operator"
    operator_paths = write_operator_artifacts(
        operator_dir,
        run_packet=run_packet,
        anomalies=decision.anomalies,
        decision=decision,
        ai_evaluation=ai_evaluation,
    )
    _progress(
        emit_progress,
        f"[PUBLISH DECISION] severity={decision.severity} publish_allowed={decision.publish_allowed} "
        f"operator_report={operator_paths['operator_report']}",
    )
    replay_eval_manifest = None
    if canonical_run_mode != "live":
        _progress(emit_progress, _progress_banner("SETTLE REPLAY OUTCOMES", resolved_run_id))
        replay_eval_manifest = evaluate_scored_run(run_id=resolved_run_id, root=root)
        _progress(emit_progress, _context_line("REPLAY_EVAL", replay_eval_manifest))

    manifest_path = run_dir / "run_manifest.json"
    manifest = {
        "run_id": resolved_run_id,
        "run_mode": canonical_run_mode,
        "replay_type": run_fidelity_policy["replay_type"],
        "fidelity_policy": run_fidelity_policy,
        "mlb_config": config_manifest,
        "game_date_filter": engine_board.get("game_date_filter", ""),
        "date_filter_policy": engine_board.get("date_filter_policy", ""),
        "snapshot_path": str(resolved_snapshot),
        "normalized_source_type": normalized_source["source_type"],
        "context_source_refresh": context_source_refresh,
        "source_selection": source_selection_manifest,
        "primary_market_source": primary_market_source,
        "supplemental_market_sources": [draftkings_pick6_source, draftkings_sportsbook_source],
        "normalized": {
            "output_dir": str(normalized.output_dir),
            "normalized_count": len(normalized.rows),
            "rejected_count": len(normalized.rejects),
        },
        "engine_board": engine_board,
        "matchups": matchup_manifest,
        "market_context": market_context_manifest,
        "injury_context": injury_context_manifest,
        "statsapi_context": statsapi_context_manifest,
        "roster_context": roster_context_manifest,
        "player_history_context": player_history_context_manifest,
        "transaction_context": transaction_context_manifest,
        "advanced_context": advanced_context_manifest,
        "features": feature_manifest,
        "parameters": parameter_manifest,
        "raw_parameters": raw_parameter_manifest,
        "parameter_calibration": calibration_manifest,
        "score": score_manifest,
        "slips": slips_manifest,
        "operator": {
            "anomaly_count": len(anomalies),
            "severity": decision.severity,
            "publish_allowed": decision.publish_allowed,
            "operator_input": operator_input,
            "ai_evaluation_path": str(operator_paths["ai_evaluation"]),
            "anomalies_path": str(operator_paths["anomalies"]),
            "publish_decision_path": str(operator_paths["publish_decision"]),
            "operator_report_path": str(operator_paths["operator_report"]),
        },
        "eval": replay_eval_manifest,
        "manifest_path": str(manifest_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    runtime_state_manifest = publish_run_runtime_state(run_manifest=manifest, root=root)
    manifest["runtime_state"] = runtime_state_manifest
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _progress(emit_progress, f"[RUN MANIFEST] {manifest_path}")
    _progress(
        emit_progress,
        f"[RUNTIME STATE] manifest={runtime_state_manifest.get('manifest_path', '')} "
        f"version={runtime_state_manifest.get('runtime_state_version', '')}",
    )
    return manifest


def _write_source_selection_manifest(
    *,
    run_dir: Path,
    run_id: str,
    run_mode: str,
    game_date: str,
    config_payload: dict[str, Any],
    selected_market_source_dirs: list[Path],
    primary_market_source: dict[str, Any],
    supplemental_market_sources: list[dict[str, Any]],
    context_source_refresh: dict[str, Any],
    engine_board: dict[str, Any],
    market_context_manifest: dict[str, Any],
    injury_context_manifest: dict[str, Any],
    statsapi_context_manifest: dict[str, Any],
    roster_context_manifest: dict[str, Any],
    player_history_context_manifest: dict[str, Any],
    transaction_context_manifest: dict[str, Any],
    matchup_manifest: dict[str, Any],
    advanced_context_manifest: dict[str, Any],
    feature_manifest: dict[str, Any],
) -> dict[str, Any]:
    source_manifest_path = run_dir / "source_selection_manifest.json"
    configured_sources = {
        "primary_market_source": BETTINGPROS_MLB_PROPS_SOURCE,
        "draftkings_pick6_alignment_enabled": _market_source_feature_enabled(
            config_payload,
            "draftkings_pick6_alignment_enabled",
            default=False,
        ),
        "draftkings_sportsbook_alignment_enabled": _market_source_feature_enabled(
            config_payload,
            "draftkings_sportsbook_alignment_enabled",
            default=False,
        ),
    }
    market_sources = [primary_market_source, *supplemental_market_sources]
    selected_market_details = [
        _market_source_dir_detail(path, game_date=game_date)
        for path in selected_market_source_dirs
    ]
    component_sources = matchup_manifest.get("component_sources") if isinstance(matchup_manifest, dict) else {}
    component_sources = component_sources if isinstance(component_sources, dict) else {}
    source_completeness = feature_manifest.get("source_completeness")
    source_completeness = source_completeness if isinstance(source_completeness, dict) else {}
    dk_timing_policy = _draftkings_timing_policy(engine_board, game_date=game_date)
    dk_gap_fill_monitor = _draftkings_gap_fill_monitor(
        market_context_manifest,
        draftkings_timing_policy=dk_timing_policy,
    )
    warnings = _source_contract_warnings(
        run_mode=run_mode,
        configured_sources=configured_sources,
        market_sources=market_sources,
        selected_market_details=selected_market_details,
        draftkings_timing_policy=dk_timing_policy,
        context_source_refresh=context_source_refresh,
        component_sources=component_sources,
        source_completeness=source_completeness,
    )
    failure_count = _source_contract_failure_count(warnings)
    timing_warning_count = sum(1 for warning in warnings if warning.get("severity") == "timing_warning")
    manifest = {
        "run_id": run_id,
        "run_mode": run_mode,
        "game_date": game_date,
        "source_selection_version": "mlb_replay_live_source_contract_v1",
        "configured_sources": configured_sources,
        "contract_status": "fail" if failure_count else ("timing_pending" if timing_warning_count else "pass"),
        "warning_count": len(warnings),
        "failure_count": failure_count,
        "timing_warning_count": timing_warning_count,
        "warnings": warnings,
        "market_sources": {
            "primary": primary_market_source,
            "supplemental": supplemental_market_sources,
            "draftkings_timing_policy": dk_timing_policy,
            "draftkings_gap_fill_monitor": dk_gap_fill_monitor,
            "selected_dirs": [str(path) for path in selected_market_source_dirs],
            "selected_details": selected_market_details,
            "context_manifest_dirs_by_date": market_context_manifest.get("market_source_dirs_by_date", {}),
            "context_market_source_row_count": market_context_manifest.get("market_source_row_count", 0),
            "context_coverage_rate": market_context_manifest.get("coverage_rate", 0.0),
        },
        "context_sources": {
            "lineup": component_sources.get("lineup", ""),
            "weather": component_sources.get("environment", ""),
            "probable_pitcher": component_sources.get("pitcher", ""),
            "ballpark": component_sources.get("ballpark", ""),
            "wind_factors": component_sources.get("wind_factors", ""),
            "injury": injury_context_manifest.get("json_path", ""),
            "statsapi": statsapi_context_manifest.get("json_path", ""),
            "roster": roster_context_manifest.get("json_path", ""),
            "player_history": player_history_context_manifest.get("json_path", ""),
            "transactions": transaction_context_manifest.get("json_path", ""),
            "advanced": advanced_context_manifest.get("json_path", ""),
        },
        "context_manifests": {
            "market": market_context_manifest.get("manifest_path", ""),
            "injury": injury_context_manifest.get("manifest_path", ""),
            "statsapi": statsapi_context_manifest.get("manifest_path", ""),
            "roster": roster_context_manifest.get("manifest_path", ""),
            "player_history": player_history_context_manifest.get("manifest_path", ""),
            "transactions": transaction_context_manifest.get("manifest_path", ""),
            "matchups": matchup_manifest.get("manifest_path", ""),
            "advanced": advanced_context_manifest.get("manifest_path", ""),
        },
        "source_completeness": source_completeness,
        "context_source_refresh": context_source_refresh,
        "manifest_path": str(source_manifest_path),
    }
    source_manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _draftkings_gap_fill_monitor(
    market_context_manifest: dict[str, Any],
    *,
    draftkings_timing_policy: dict[str, Any],
) -> dict[str, Any]:
    historical_unavailable_sources = {
        str(source)
        for source in draftkings_timing_policy.get("historical_unavailable_sources") or []
    }
    source_counts = market_context_manifest.get("market_source_counts_by_market")
    source_counts = source_counts if isinstance(source_counts, dict) else {}
    board_counts = market_context_manifest.get("board_rows_by_market")
    board_counts = board_counts if isinstance(board_counts, dict) else {}
    matched_counts = market_context_manifest.get("matched_rows_by_market")
    matched_counts = matched_counts if isinstance(matched_counts, dict) else {}
    rows: list[dict[str, Any]] = []
    for market, config in DK_GAP_FILL_MARKETS.items():
        expected_sources = tuple(config.get("expected_sources") or ())
        counts_by_source = {
            source: int((source_counts.get(source) or {}).get(market) or 0)
            for source in expected_sources
        }
        total_source_rows = sum(counts_by_source.values())
        board_rows = int(board_counts.get(market) or 0)
        matched_rows = int(matched_counts.get(market) or 0)
        if not expected_sources:
            status = "not_expected"
        elif total_source_rows > 0:
            status = "loaded"
        elif all(source in historical_unavailable_sources for source in expected_sources):
            status = "historical_unavailable"
        elif board_rows > 0 and draftkings_timing_policy.get("missing_dk_is_timing_valid"):
            status = "timing_pending"
        elif board_rows > 0:
            status = "missing"
        else:
            status = "no_board_rows"
        rows.append(
            {
                "market": market,
                "status": status,
                "availability": config.get("availability", ""),
                "expected_sources": list(expected_sources),
                "source_rows": counts_by_source,
                "total_source_rows": total_source_rows,
                "board_rows": board_rows,
                "matched_rows": matched_rows,
                "matched_rate": round(matched_rows / board_rows, 6) if board_rows else None,
                "notes": config.get("notes", ""),
            }
        )
    return {
        "monitor_version": "draftkings_gap_fill_monitor_v1",
        "timing_status": draftkings_timing_policy.get("timing_status", ""),
        "ready_game_count": draftkings_timing_policy.get("ready_game_count", 0),
        "pending_game_count": draftkings_timing_policy.get("pending_game_count", 0),
        "historical_unavailable_sources": sorted(historical_unavailable_sources),
        "markets": rows,
    }


def _source_contract_warnings(
    *,
    run_mode: str,
    configured_sources: dict[str, Any],
    market_sources: list[dict[str, Any]],
    selected_market_details: list[dict[str, Any]],
    draftkings_timing_policy: dict[str, Any],
    context_source_refresh: dict[str, Any],
    component_sources: dict[str, Any],
    source_completeness: dict[str, Any],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    timing_valid_missing_dk = bool(draftkings_timing_policy.get("missing_dk_is_timing_valid"))
    for source in market_sources:
        if not source.get("enabled"):
            continue
        status = str(source.get("status") or "")
        if status not in {"fetched", "existing"}:
            warning_code = "enabled_market_source_missing"
            severity = "failure"
            source_name = str(source.get("source") or "")
            if source_name in {DRAFTKINGS_MLB_PICK6_SOURCE, DRAFTKINGS_MLB_SPORTSBOOK_SOURCE}:
                if _draftkings_historical_source_unavailable(
                    source=source_name,
                    run_mode=run_mode,
                    game_date=str(draftkings_timing_policy.get("game_date") or ""),
                    reason=source.get("missing_reason") or source.get("errors"),
                ):
                    warning_code = "draftkings_source_historical_unavailable"
                    severity = "timing_warning"
                elif timing_valid_missing_dk:
                    warning_code = "draftkings_source_timing_pending"
                    severity = "timing_warning"
            warnings.append(
                {
                    "code": warning_code,
                    "severity": severity,
                    "source": source.get("source", ""),
                    "status": status,
                    "reason": source.get("missing_reason") or source.get("errors") or "no_selected_source",
                    "first_available_date": DK_REPLAY_SOURCE_START_DATES.get(source_name, ""),
                    "draftkings_timing_policy": draftkings_timing_policy,
                }
            )
    selected_sources = {str(detail.get("source") or "") for detail in selected_market_details}
    if configured_sources.get("draftkings_pick6_alignment_enabled") and DRAFTKINGS_MLB_PICK6_SOURCE not in selected_sources:
        if _draftkings_historical_source_unavailable(
            source=DRAFTKINGS_MLB_PICK6_SOURCE,
            run_mode=run_mode,
            game_date=str(draftkings_timing_policy.get("game_date") or ""),
            reason="no_same_date_existing_source",
        ):
            warnings.append(
                {
                    "code": "draftkings_source_historical_unavailable",
                    "severity": "timing_warning",
                    "source": DRAFTKINGS_MLB_PICK6_SOURCE,
                    "run_mode": run_mode,
                    "first_available_date": DK_REPLAY_SOURCE_START_DATES.get(DRAFTKINGS_MLB_PICK6_SOURCE, ""),
                    "draftkings_timing_policy": draftkings_timing_policy,
                }
            )
        elif timing_valid_missing_dk:
            warnings.append(
                {
                    "code": "draftkings_source_timing_pending",
                    "severity": "timing_warning",
                    "source": DRAFTKINGS_MLB_PICK6_SOURCE,
                    "run_mode": run_mode,
                    "draftkings_timing_policy": draftkings_timing_policy,
                }
            )
        else:
            warnings.append(
                {
                    "code": "live_enabled_source_not_selected_for_run",
                    "severity": "failure",
                    "source": DRAFTKINGS_MLB_PICK6_SOURCE,
                    "run_mode": run_mode,
                    "draftkings_timing_policy": draftkings_timing_policy,
                }
            )
    if (
        configured_sources.get("draftkings_sportsbook_alignment_enabled")
        and DRAFTKINGS_MLB_SPORTSBOOK_SOURCE not in selected_sources
    ):
        if _draftkings_historical_source_unavailable(
            source=DRAFTKINGS_MLB_SPORTSBOOK_SOURCE,
            run_mode=run_mode,
            game_date=str(draftkings_timing_policy.get("game_date") or ""),
            reason="no_same_date_existing_source",
        ):
            warnings.append(
                {
                    "code": "draftkings_source_historical_unavailable",
                    "severity": "timing_warning",
                    "source": DRAFTKINGS_MLB_SPORTSBOOK_SOURCE,
                    "run_mode": run_mode,
                    "first_available_date": DK_REPLAY_SOURCE_START_DATES.get(DRAFTKINGS_MLB_SPORTSBOOK_SOURCE, ""),
                    "draftkings_timing_policy": draftkings_timing_policy,
                }
            )
        elif timing_valid_missing_dk:
            warnings.append(
                {
                    "code": "draftkings_source_timing_pending",
                    "severity": "timing_warning",
                    "source": DRAFTKINGS_MLB_SPORTSBOOK_SOURCE,
                    "run_mode": run_mode,
                    "draftkings_timing_policy": draftkings_timing_policy,
                }
            )
        else:
            warnings.append(
                {
                    "code": "live_enabled_source_not_selected_for_run",
                    "severity": "failure",
                    "source": DRAFTKINGS_MLB_SPORTSBOOK_SOURCE,
                    "run_mode": run_mode,
                    "draftkings_timing_policy": draftkings_timing_policy,
                }
            )
    for source_key in ("lineup", "environment", "pitcher", "ballpark", "wind_factors"):
        value = str(component_sources.get(source_key) or "").strip().lower()
        if not value or value == "missing":
            warnings.append({"code": "missing_context_component_source", "source": source_key})
    for key in (
        "external_market_context_available",
        "lineup_context_available",
        "roster_context_available",
        "player_history_context_available",
        "advanced_context_available",
        "weather_context_available",
    ):
        try:
            value = float(source_completeness.get(key))
        except (TypeError, ValueError):
            value = 0.0
        if value <= 0:
            warnings.append({"code": "zero_context_completeness", "source": key})
    for error in context_source_refresh.get("errors") or []:
        warnings.append({"code": "source_refresh_error", "source": error.get("source", ""), "error": error})
    return warnings


def _draftkings_historical_source_unavailable(
    *,
    source: str,
    run_mode: str,
    game_date: str,
    reason: Any,
) -> bool:
    if normalize_run_mode(run_mode) == "live":
        return False
    first_available = DK_REPLAY_SOURCE_START_DATES.get(source)
    if not first_available or not game_date:
        return False
    if str(game_date)[:10] >= first_available:
        return False
    reason_text = str(reason or "")
    return reason_text.startswith("no_same_date_existing_source")


def _source_contract_failure_count(warnings: list[dict[str, Any]]) -> int:
    return sum(1 for warning in warnings if warning.get("severity") != "timing_warning")


def _draftkings_timing_policy(engine_board: dict[str, Any], *, game_date: str) -> dict[str, Any]:
    rows = engine_board.get("rows") if isinstance(engine_board, dict) else []
    if not isinstance(rows, list):
        rows = _engine_board_rows_from_json_path(engine_board)
    rows = [row for row in rows if isinstance(row, dict)]
    if game_date:
        rows = [row for row in rows if str(row.get("game_date") or "") == game_date]
    capture_times = [
        parsed
        for parsed in (
            _parse_utc_datetime(row.get("pulled_at_utc") or row.get("updated_at"))
            for row in rows
        )
        if parsed is not None
    ]
    if not capture_times:
        fallback_capture = _parse_utc_datetime(engine_board.get("as_of_utc") if isinstance(engine_board, dict) else None)
        if fallback_capture:
            capture_times.append(fallback_capture)
    capture_utc = max(capture_times) if capture_times else None
    game_windows = _draftkings_game_windows(rows, capture_utc=capture_utc)
    ready_games = [game for game in game_windows if game.get("timing_status") == "ready"]
    pending_games = [game for game in game_windows if game.get("timing_status") == "pending"]
    unknown_games = [game for game in game_windows if game.get("timing_status") == "unknown"]
    first_pitch_utc = min((_parse_utc_datetime(game.get("start_time_utc")) for game in game_windows), default=None)
    next_target_utc = min(
        (
            parsed
            for parsed in (_parse_utc_datetime(game.get("target_capture_utc")) for game in pending_games)
            if parsed is not None
        ),
        default=None,
    )
    missing_is_timing_valid = bool(game_windows and pending_games and not ready_games and not unknown_games)
    historical_unavailable_sources = [
        source
        for source, first_available in DK_REPLAY_SOURCE_START_DATES.items()
        if game_date and str(game_date)[:10] < first_available
    ]
    return {
        "policy_version": "draftkings_mlb_late_market_timing_v2_per_game",
        "late_market_sources": [DRAFTKINGS_MLB_PICK6_SOURCE, DRAFTKINGS_MLB_SPORTSBOOK_SOURCE],
        "historical_source_start_dates": DK_REPLAY_SOURCE_START_DATES,
        "historical_unavailable_sources": historical_unavailable_sources,
        "late_market_examples": ["hitter_strikeouts", "walks", "pitches_thrown"],
        "normal_day_rule": "target capture is one hour before each game's first pitch",
        "sunday_rule": "same per-game one-hour rule; schedule the first daily live pull at 10:00 America/Chicago for 11:00 starts",
        "recommended_live_pull_windows_local": ["11:00", "14:30", "17:00", "19:00"],
        "game_date": game_date,
        "game_count": len(game_windows),
        "ready_game_count": len(ready_games),
        "pending_game_count": len(pending_games),
        "unknown_game_count": len(unknown_games),
        "first_pitch_utc": _iso_utc(first_pitch_utc),
        "first_pitch_local": _iso_local(first_pitch_utc),
        "source_capture_utc": _iso_utc(capture_utc),
        "source_capture_local": _iso_local(capture_utc),
        "next_pending_target_capture_utc": _iso_utc(next_target_utc),
        "next_pending_target_capture_local": _iso_local(next_target_utc),
        "game_windows": game_windows,
        "missing_dk_is_timing_valid": missing_is_timing_valid,
        "timing_status": (
            "all_games_before_dk_target_window"
            if missing_is_timing_valid
            else "partial_ready_window"
            if ready_games and pending_games
            else "all_games_at_or_after_dk_target_window"
            if ready_games and not pending_games
            else "unknown"
        ),
    }


def _draftkings_game_windows(rows: list[dict[str, Any]], *, capture_utc: datetime | None) -> list[dict[str, Any]]:
    games: dict[str, dict[str, Any]] = {}
    for row in rows:
        start_utc = _parse_utc_datetime(
            row.get("start_time_utc")
            or row.get("game_start_utc")
            or row.get("commence_time")
            or row.get("start_time")
        )
        if start_utc is None:
            continue
        event_id = str(row.get("event_id") or "").strip()
        player_team = str(row.get("player_team") or "").strip()
        opponent = str(row.get("opponent") or "").strip()
        key = event_id or "|".join([_iso_utc(start_utc), player_team, opponent])
        existing = games.get(key)
        if existing:
            existing["row_count"] = int(existing.get("row_count") or 0) + 1
            if player_team and player_team not in str(existing.get("teams") or ""):
                existing["teams"] = _join_unique(existing.get("teams"), player_team)
            if opponent and opponent not in str(existing.get("teams") or ""):
                existing["teams"] = _join_unique(existing.get("teams"), opponent)
            continue
        target_utc = _draftkings_target_capture_utc(start_utc)
        if not capture_utc or not target_utc:
            timing_status = "unknown"
        elif capture_utc < target_utc:
            timing_status = "pending"
        else:
            timing_status = "ready"
        games[key] = {
            "event_id": event_id,
            "teams": _join_unique(player_team, opponent),
            "start_time_utc": _iso_utc(start_utc),
            "start_time_local": _iso_local(start_utc),
            "target_capture_utc": _iso_utc(target_utc),
            "target_capture_local": _iso_local(target_utc),
            "timing_status": timing_status,
            "row_count": 1,
        }
    return sorted(games.values(), key=lambda item: (str(item.get("start_time_utc") or ""), str(item.get("event_id") or "")))


def _engine_board_rows_from_json_path(engine_board: dict[str, Any]) -> list[dict[str, Any]]:
    path = Path(str(engine_board.get("json_path") or ""))
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("rows") if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _draftkings_target_capture_utc(first_pitch_utc: datetime | None) -> datetime | None:
    if first_pitch_utc is None:
        return None
    return first_pitch_utc - timedelta(hours=1)


def _parse_utc_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    compact = re.search(r"(20\d{2})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", text)
    if compact:
        try:
            return datetime(
                int(compact.group(1)),
                int(compact.group(2)),
                int(compact.group(3)),
                int(compact.group(4)),
                int(compact.group(5)),
                int(compact.group(6)),
                tzinfo=timezone.utc,
            )
        except ValueError:
            pass
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _iso_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalized_source_as_of(normalized: BoardNormalizationResult) -> datetime | None:
    candidates: list[datetime] = []
    metadata = normalized.metadata if isinstance(normalized.metadata, dict) else {}
    for key in ("pulled_at_utc", "snapshot_timestamp", "snapshot_id", "run_id"):
        parsed = _parse_utc_datetime(metadata.get(key))
        if parsed:
            candidates.append(parsed)
    for key in ("snapshot_id", "run_id"):
        parsed = _parse_utc_datetime(getattr(normalized, key, ""))
        if parsed:
            candidates.append(parsed)
    for row in normalized.rows:
        if not isinstance(row, dict):
            continue
        for key in ("pulled_at_utc", "snapshot_timestamp"):
            parsed = _parse_utc_datetime(row.get(key))
            if parsed:
                candidates.append(parsed)
                break
    return max(candidates) if candidates else None


def _market_manifest_as_of(manifest: dict[str, Any], source_dir: Path) -> datetime | None:
    for key in (
        "pulled_at_utc",
        "snapshot_timestamp",
        "fetched_at_utc",
        "created_at_utc",
        "snapshot_id",
        "run_id",
    ):
        parsed = _parse_utc_datetime(manifest.get(key))
        if parsed:
            return parsed
    return _parse_utc_datetime(source_dir.name)


def _iso_local(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(_central_tz()).isoformat()


def _central_tz():
    if ZoneInfo is not None:
        return ZoneInfo("America/Chicago")
    return timezone(timedelta(hours=-6))


def _join_unique(*values: Any) -> str:
    seen: list[str] = []
    for value in values:
        if isinstance(value, str):
            parts = value.split("/")
        else:
            parts = []
        for part in parts:
            text = str(part or "").strip()
            if text and text not in seen:
                seen.append(text)
    return "/".join(seen)


def _market_source_dir_detail(path: Path, *, game_date: str) -> dict[str, Any]:
    manifest = _market_source_normalization_manifest(path)
    rows_path = Path(path) / "oddsapi_props.jsonl"
    row_dates = sorted(_game_dates_in_jsonl(rows_path))
    snapshot_id = str(manifest.get("snapshot_id") or "")
    pulled_at = str(manifest.get("pulled_at_utc") or manifest.get("snapshot_timestamp") or "")
    source_date = _extract_source_date(pulled_at) or _extract_source_date(snapshot_id)
    timing = "unknown"
    if source_date and game_date:
        try:
            timing = "same_day_or_before" if source_date <= date.fromisoformat(game_date[:10]) else "historical_backfill"
        except ValueError:
            timing = "unknown"
    return {
        "path": str(path),
        "source": str(manifest.get("source") or ""),
        "snapshot_id": snapshot_id,
        "pulled_at_utc": pulled_at,
        "source_date": source_date.isoformat() if source_date else "",
        "game_date": game_date,
        "timing_classification": timing,
        "row_count": int(manifest.get("compatible_row_count") or manifest.get("row_count") or 0),
        "row_dates": row_dates,
        "has_requested_game_date": game_date in row_dates,
    }


def _game_dates_in_jsonl(path: Path) -> set[str]:
    dates: set[str] = set()
    if not path.exists():
        return dates
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        for key in ("game_date", "official_date", "date"):
            value = str(row.get(key) or "").strip()
            if value:
                dates.add(value[:10])
                break
    return dates


def _extract_source_date(value: str) -> date | None:
    text = str(value or "")
    iso_match = re.search(r"(20\d{2})-(\d{2})-(\d{2})", text)
    compact_match = re.search(r"(20\d{2})(\d{2})(\d{2})", text)
    match = iso_match or compact_match
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _resolve_normalized_source(
    *,
    snapshot_path: Path | None,
    normalized_dir: Path | None,
    root: Path | None,
    run_id: str | None,
) -> dict[str, Any]:
    if normalized_dir is not None:
        manifest = json.loads((normalized_dir / "normalize_manifest.json").read_text(encoding="utf-8"))
        rows = _load_jsonl(normalized_dir / "normalized_board.jsonl")
        rejects = _load_jsonl(normalized_dir / "rejected_board.jsonl")
        normalized = BoardNormalizationResult(
            run_id=run_id or str(manifest.get("run_id") or normalized_dir.name),
            snapshot_id=str(manifest.get("snapshot_id") or ""),
            rows=tuple(rows),
            rejects=tuple(rejects),
            output_dir=normalized_dir,
            metadata=manifest,
        )
        return {"source_type": "normalized_dir", "source_path": normalized_dir, "normalized": normalized}

    resolved_snapshot = snapshot_path or latest_snapshot_path("prizepicks", root=root)
    normalized = write_prizepicks_board_normalization(resolved_snapshot, root=root, run_id=run_id)
    return {"source_type": "snapshot", "source_path": resolved_snapshot, "normalized": normalized}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _jsonl_has_game_date(path: Path, game_date: str) -> bool:
    expected = str(game_date or "").strip()[:10]
    if not expected or not path.exists():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        for key in ("game_date", "official_date", "date"):
            value = str(row.get(key) or "").strip()
            if value[:10] == expected:
                return True
    return False


def _ensure_primary_market_source(
    *,
    enabled: bool,
    root: Path | None,
    game_date: str,
    run_mode: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "enabled": enabled,
        "source": BETTINGPROS_MLB_PROPS_SOURCE,
        "game_date": game_date,
        "run_mode": run_mode,
        "status": "disabled" if not enabled else "pending",
        "snapshot_id": "",
        "payload_path": "",
        "normalized_output_dir": "",
        "row_count": 0,
        "rejected_count": 0,
        "errors": [],
    }
    if not enabled and normalize_run_mode(run_mode) == "live":
        return payload
    if not game_date:
        payload["status"] = "error"
        payload["errors"].append({"source": BETTINGPROS_MLB_PROPS_SOURCE, "reason": "missing_game_date"})
        return payload

    try:
        parsed_date = date.fromisoformat(game_date)
    except ValueError as exc:
        payload["status"] = "error"
        payload["errors"].append({"source": BETTINGPROS_MLB_PROPS_SOURCE, "reason": str(exc)})
        return payload

    paths = ensure_mlb_dirs(root)
    existing = _existing_bettingpros_normalization(paths, parsed_date)
    if existing and (not enabled or normalize_run_mode(run_mode) != "live"):
        _apply_existing_market_selection(payload, existing)
        payload["refresh_enabled"] = bool(enabled)
        payload["selection_mode"] = "date_safe_existing"
        return payload
    if not enabled:
        payload["status"] = "missing"
        payload["missing_reason"] = "no_same_date_existing_source"
        payload["refresh_enabled"] = False
        return payload

    try:
        include_offers = run_mode == "live" and _env_bool("ATLAS_MLB_BETTINGPROS_INCLUDE_OFFERS", True)
        book_ids = parse_bettingpros_book_ids(os.environ.get("ATLAS_MLB_BETTINGPROS_BOOK_IDS", "major"))
        snapshot = fetch_bettingpros_mlb_props(
            game_date=parsed_date,
            root=root,
            include_offers=include_offers,
            book_ids=book_ids,
        )
        normalized = write_bettingpros_mlb_normalization(Path(snapshot.path), root=root)
        payload.update(
            {
                "status": "fetched",
                "snapshot_id": str(snapshot.request.get("snapshot_id") or ""),
                "payload_path": snapshot.path,
                "normalized_output_dir": str(normalized["output_dir"]),
                "row_count": int(normalized["row_count"]),
                "rejected_count": int(normalized["rejected_count"]),
            }
        )
    except Exception as exc:  # pragma: no cover - defensive market-source boundary
        error = {"source": BETTINGPROS_MLB_PROPS_SOURCE, "reason": str(exc)}
        payload["status"] = "error"
        payload["errors"].append(error)
        if existing:
            existing_manifest = _market_source_normalization_manifest(existing)
            payload.update(
                {
                    "status": "existing",
                    "fallback_used": True,
                    "fresh_fetch_status": "error",
                    "fresh_fetch_errors": [error],
                    "snapshot_id": str(existing_manifest.get("snapshot_id") or ""),
                    "normalized_output_dir": str(existing),
                    "row_count": int(existing_manifest.get("row_count") or 0),
                    "rejected_count": int(existing_manifest.get("rejected_count") or 0),
                    "errors": [],
                }
            )
            payload["fallback_output_dir"] = str(existing)
    return payload


def _ensure_draftkings_pick6_source(
    *,
    enabled: bool,
    root: Path | None,
    game_date: str,
    run_mode: str,
    source_as_of_utc: datetime | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "enabled": enabled,
        "source": DRAFTKINGS_MLB_PICK6_SOURCE,
        "game_date": game_date,
        "run_mode": run_mode,
        "status": "disabled" if not enabled else "pending",
        "snapshot_id": "",
        "payload_path": "",
        "normalized_output_dir": "",
        "row_count": 0,
        "compatible_row_count": 0,
        "rejected_count": 0,
        "errors": [],
    }
    if not enabled:
        return payload
    paths = ensure_mlb_dirs(root)
    existing = _existing_market_normalization(
        paths,
        staged_subdir=DRAFTKINGS_MLB_PICK6_SOURCE,
        source=DRAFTKINGS_MLB_PICK6_SOURCE,
        required_file="oddsapi_props.jsonl",
        game_date=game_date,
        as_of_utc=source_as_of_utc if normalize_run_mode(run_mode) != "live" else None,
    )
    if normalize_run_mode(run_mode) != "live":
        if existing:
            _apply_existing_market_selection(payload, existing)
            payload["refresh_enabled"] = False
            payload["selection_mode"] = "date_safe_existing_asof" if source_as_of_utc else "date_safe_existing"
            payload["source_as_of_utc"] = _iso_utc(source_as_of_utc)
        else:
            payload["status"] = "missing"
            payload["missing_reason"] = (
                "no_same_date_existing_source_at_or_before_replay_snapshot"
                if source_as_of_utc
                else "no_same_date_existing_source"
            )
            payload["refresh_enabled"] = False
            payload["source_as_of_utc"] = _iso_utc(source_as_of_utc)
        return payload
    try:
        snapshot = fetch_draftkings_mlb_pick6(root=root)
        normalized = write_draftkings_pick6_normalization(Path(snapshot.path), root=root)
        payload.update(
            {
                "status": "fetched",
                "snapshot_id": str(snapshot.request.get("snapshot_id") or ""),
                "payload_path": snapshot.path,
                "normalized_output_dir": str(normalized["output_dir"]),
                "row_count": int(normalized["row_count"]),
                "compatible_row_count": int(normalized.get("compatible_row_count") or 0),
                "rejected_count": int(normalized["rejected_count"]),
            }
        )
    except Exception as exc:  # pragma: no cover - defensive supplemental source boundary
        error = {"source": DRAFTKINGS_MLB_PICK6_SOURCE, "reason": str(exc)}
        payload["status"] = "error"
        payload["errors"].append(error)
        if existing:
            _apply_market_fallback(payload, existing, error)
    return payload


def _ensure_draftkings_sportsbook_source(
    *,
    enabled: bool,
    root: Path | None,
    game_date: str,
    run_mode: str,
    source_as_of_utc: datetime | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "enabled": enabled,
        "source": DRAFTKINGS_MLB_SPORTSBOOK_SOURCE,
        "game_date": game_date,
        "run_mode": run_mode,
        "status": "disabled" if not enabled else "pending",
        "snapshot_id": "",
        "payload_path": "",
        "normalized_output_dir": "",
        "row_count": 0,
        "compatible_row_count": 0,
        "rejected_count": 0,
        "errors": [],
    }
    if not enabled:
        return payload
    paths = ensure_mlb_dirs(root)
    existing = _existing_market_normalization(
        paths,
        staged_subdir="draftkings_mlb_sportsbook",
        source=DRAFTKINGS_MLB_SPORTSBOOK_SOURCE,
        required_file="oddsapi_props.jsonl",
        game_date=game_date,
        as_of_utc=source_as_of_utc if normalize_run_mode(run_mode) != "live" else None,
    )
    if normalize_run_mode(run_mode) != "live":
        if existing:
            _apply_existing_market_selection(payload, existing)
            payload["refresh_enabled"] = False
            payload["selection_mode"] = "date_safe_existing_asof" if source_as_of_utc else "date_safe_existing"
            payload["source_as_of_utc"] = _iso_utc(source_as_of_utc)
        else:
            payload["status"] = "missing"
            payload["missing_reason"] = (
                "no_same_date_existing_source_at_or_before_replay_snapshot"
                if source_as_of_utc
                else "no_same_date_existing_source"
            )
            payload["refresh_enabled"] = False
            payload["source_as_of_utc"] = _iso_utc(source_as_of_utc)
        return payload
    try:
        snapshot = fetch_draftkings_mlb_sportsbook_props(root=root)
        normalized = write_draftkings_sportsbook_normalization(Path(snapshot.path), root=root)
        payload.update(
            {
                "status": "fetched",
                "snapshot_id": str(snapshot.request.get("snapshot_id") or ""),
                "payload_path": snapshot.path,
                "normalized_output_dir": str(normalized["output_dir"]),
                "row_count": int(normalized["row_count"]),
                "compatible_row_count": int(normalized.get("compatible_row_count") or 0),
                "rejected_count": int(normalized["rejected_count"]),
            }
        )
    except Exception as exc:  # pragma: no cover - defensive supplemental source boundary
        error = {"source": DRAFTKINGS_MLB_SPORTSBOOK_SOURCE, "reason": str(exc)}
        payload["status"] = "error"
        payload["errors"].append(error)
        if existing:
            _apply_market_fallback(payload, existing, error)
    return payload


def _market_source_dirs_for_run(
    *,
    root: Path | None,
    game_date: str,
    primary_market_source: dict[str, Any],
    supplemental_market_sources: list[dict[str, Any]] | None = None,
    run_mode: str,
) -> list[Path]:
    dirs: list[Path] = []
    for source in [primary_market_source, *(supplemental_market_sources or [])]:
        normalized_output_dir = str(source.get("normalized_output_dir") or "").strip()
        if normalized_output_dir:
            dirs.append(Path(normalized_output_dir))
    selected = _dedupe_existing_paths(dirs)
    if normalize_run_mode(run_mode) != "live" and game_date:
        # Historical replay can use an older market source than live, but it
        # still needs normalized, date-scoped rows. If the configured primary
        # source is unavailable for that date, fall back to any date-matching
        # normalized odds source instead of producing a zero-market replay.
        repo_paths = ensure_mlb_dirs(root)
        selected = _dedupe_existing_paths(
            [*selected, *_existing_oddsapi_market_dirs_for_date(repo_paths, game_date)]
        )
    return selected


def _live_market_source_dirs(
    *,
    primary_market_source: dict[str, Any],
    supplemental_market_sources: list[dict[str, Any]] | None = None,
    run_mode: str,
) -> list[Path] | None:
    """Backward-compatible helper for older tests/imports.

    The pipeline uses ``_market_source_dirs_for_run`` now so replay and live both
    pass explicit source dirs into market context.
    """

    if normalize_run_mode(run_mode) != "live":
        return None
    dirs = [
        Path(str(source.get("normalized_output_dir") or "").strip())
        for source in [primary_market_source, *(supplemental_market_sources or [])]
        if str(source.get("normalized_output_dir") or "").strip()
    ]
    return dirs or None


def _market_source_feature_enabled(config: dict[str, Any], key: str, *, default: bool) -> bool:
    market_sources = config.get("market_sources") if isinstance(config.get("market_sources"), dict) else {}
    external_features = (
        market_sources.get("external_features") if isinstance(market_sources.get("external_features"), dict) else {}
    )
    value = external_features.get(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


def _config_float(config: dict[str, Any], path: tuple[str, ...], *, default: float) -> float:
    value: Any = config
    for key in path:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _existing_bettingpros_normalization(paths, game_date: date) -> Path | None:
    staged_root = paths.staged / "oddsapi"
    if not staged_root.exists():
        return None
    date_key = game_date.strftime("%Y%m%d")
    candidates = sorted(staged_root.glob(f"*{date_key}*/normalize_manifest.json"))
    for manifest_path in reversed(candidates):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("source") == BETTINGPROS_MLB_PROPS_SOURCE and (manifest_path.parent / "oddsapi_props.jsonl").exists():
            return manifest_path.parent
    return None


def _existing_market_normalization(
    paths,
    *,
    staged_subdir: str,
    source: str,
    required_file: str,
    game_date: str | None = None,
    as_of_utc: datetime | None = None,
) -> Path | None:
    staged_root = paths.staged / staged_subdir
    if not staged_root.exists():
        return None
    candidates = sorted(staged_root.glob("*/normalize_manifest.json"), key=lambda path: (path.stat().st_mtime, path.parent.name))
    for manifest_path in reversed(candidates):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if source and manifest.get("source") != source:
            continue
        if as_of_utc is not None:
            manifest_as_of = _market_manifest_as_of(manifest, manifest_path.parent)
            if manifest_as_of is None or manifest_as_of > as_of_utc:
                continue
        rows_path = manifest_path.parent / required_file
        if not rows_path.exists():
            continue
        if game_date and not _jsonl_has_game_date(rows_path, game_date):
            continue
        return manifest_path.parent
    return None


def _existing_oddsapi_market_dirs_for_date(paths, game_date: str) -> list[Path]:
    staged_root = paths.staged / "oddsapi"
    if not staged_root.exists() or not game_date:
        return []
    selected: list[Path] = []
    for manifest_path in sorted(staged_root.glob("*/normalize_manifest.json"), key=lambda path: path.parent.name):
        rows_path = manifest_path.parent / "oddsapi_props.jsonl"
        if not rows_path.exists() or not _jsonl_has_game_date(rows_path, game_date):
            continue
        selected.append(manifest_path.parent)
    return selected


def _dedupe_existing_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        if not path:
            continue
        resolved = str(Path(path))
        if resolved in seen:
            continue
        if not Path(path).exists():
            continue
        seen.add(resolved)
        deduped.append(Path(path))
    return deduped


def _apply_existing_market_selection(payload: dict[str, Any], normalized_dir: Path) -> None:
    existing_manifest = _market_source_normalization_manifest(normalized_dir)
    payload.update(
        {
            "status": "existing",
            "snapshot_id": str(existing_manifest.get("snapshot_id") or ""),
            "normalized_output_dir": str(normalized_dir),
            "row_count": int(existing_manifest.get("row_count") or 0),
            "compatible_row_count": int(
                existing_manifest.get("compatible_row_count") or existing_manifest.get("row_count") or 0
            ),
            "rejected_count": int(existing_manifest.get("rejected_count") or 0),
            "errors": [],
        }
    )


def _apply_market_fallback(payload: dict[str, Any], normalized_dir: Path, error: dict[str, Any]) -> None:
    existing_manifest = _market_source_normalization_manifest(normalized_dir)
    payload.update(
        {
            "status": "existing",
            "fallback_used": True,
            "fresh_fetch_status": "error",
            "fresh_fetch_errors": [error],
            "snapshot_id": str(existing_manifest.get("snapshot_id") or ""),
            "normalized_output_dir": str(normalized_dir),
            "row_count": int(existing_manifest.get("row_count") or 0),
            "compatible_row_count": int(
                existing_manifest.get("compatible_row_count") or existing_manifest.get("row_count") or 0
            ),
            "rejected_count": int(existing_manifest.get("rejected_count") or 0),
            "errors": [],
            "fallback_output_dir": str(normalized_dir),
        }
    )


def _market_source_normalization_manifest(normalized_dir: Path) -> dict[str, Any]:
    manifest_path = normalized_dir / "normalize_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return manifest if isinstance(manifest, dict) else {}


def _missing_live_context_count(*, run_mode: str, total_count: int, completeness: Any) -> int:
    if run_mode != "live" or total_count <= 0:
        return 0
    try:
        completeness_rate = float(completeness)
    except (TypeError, ValueError):
        completeness_rate = 0.0
    missing_rate = max(0.0, min(1.0, 1.0 - completeness_rate))
    return int(round(total_count * missing_rate))


def _refresh_context_sources(
    *,
    enabled: bool,
    root: Path | None,
    game_date: str,
    rotowire_pages: str | tuple[str, ...] | None,
    baseball_savant_pages: str | tuple[str, ...] | None,
    baseball_savant_season: int,
    include_espn_backfill: bool,
    include_live_identity_sources: bool,
    emit_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "enabled": enabled,
        "game_date": game_date,
        "rotowire": None,
        "baseball_savant": None,
        "espn_game_context": None,
        "espn_backfill_enabled": include_espn_backfill,
        "live_identity_sources_enabled": include_live_identity_sources,
        "injuries": None,
        "statsapi_teams": None,
        "statsapi_schedule": None,
        "statsapi_rosters_bulk": None,
        "statsapi_transactions": None,
        "fallbacks": [],
        "warnings": [],
        "errors": [],
    }
    if not enabled:
        _progress(emit_progress, "[CONTEXT REFRESH] disabled")
        return payload
    if not game_date:
        payload["errors"].append({"source": "context_refresh", "reason": "missing_game_date"})
        _progress(emit_progress, "[CONTEXT REFRESH ERROR] missing_game_date")
        return payload

    _progress(emit_progress, _progress_banner("REFRESH ROTOWIRE CONTEXT", game_date))
    try:
        rotowire = fetch_rotowire_result(
            root=root,
            game_date=game_date,
            pages=rotowire_pages,
            normalize=True,
        )
        payload["rotowire"] = rotowire.payload
        _progress(emit_progress, _source_refresh_line("ROTOWIRE", rotowire.payload))
    except Exception as exc:  # pragma: no cover - defensive live-source boundary
        _record_context_error_or_fallback(
            payload,
            key="rotowire",
            source="rotowire_mlb_context",
            staged_subdir="rotowire_context",
            required_file="daily_lineups.jsonl",
            reason=str(exc),
            root=root,
            game_date=game_date,
            require_game_date=True,
            emit_progress=emit_progress,
            label="ROTOWIRE",
        )

    _progress(emit_progress, _progress_banner("REFRESH BASEBALL SAVANT CONTEXT", game_date))
    try:
        savant = fetch_baseball_savant_result(
            root=root,
            game_date=game_date,
            season=baseball_savant_season,
            pages=baseball_savant_pages,
            normalize=True,
        )
        payload["baseball_savant"] = savant.payload
        _progress(emit_progress, _source_refresh_line("BASEBALL_SAVANT", savant.payload))
    except Exception as exc:  # pragma: no cover - defensive live-source boundary
        _record_context_error_or_fallback(
            payload,
            key="baseball_savant",
            source="baseball_savant_context",
            staged_subdir="baseball_savant",
            required_file="schedule.jsonl",
            reason=str(exc),
            root=root,
            game_date=game_date,
            require_game_date=True,
            emit_progress=emit_progress,
            label="BASEBALL_SAVANT",
        )

    if include_espn_backfill:
        _progress(emit_progress, _progress_banner("REFRESH ESPN GAME CONTEXT BACKFILL", game_date))
        try:
            espn = fetch_espn_game_context_result(root=root, game_date=game_date, normalize=True)
            payload["espn_game_context"] = espn.payload
            _progress(emit_progress, _source_refresh_line("ESPN_GAME_CONTEXT", espn.payload))
        except Exception as exc:  # pragma: no cover - defensive replay-source boundary
            _record_context_error_or_fallback(
                payload,
                key="espn_game_context",
                source="espn_game_context",
                staged_subdir="espn_game_context",
                required_file="batting_orders.jsonl",
                reason=str(exc),
                root=root,
                game_date=game_date,
                require_game_date=True,
                emit_progress=emit_progress,
                label="ESPN_GAME_CONTEXT",
            )

    if include_live_identity_sources:
        _progress(emit_progress, _progress_banner("REFRESH ESPN INJURIES", game_date))
        try:
            injuries = fetch_injuries_result(root=root, normalize=True)
            payload["injuries"] = injuries.payload
            _progress(emit_progress, _source_refresh_line("ESPN_INJURIES", injuries.payload))
        except Exception as exc:  # pragma: no cover - defensive live-source boundary
            _record_context_error_or_fallback(
                payload,
                key="injuries",
                source="espn_injuries",
                staged_subdir="injuries",
                required_file="injuries.jsonl",
                reason=str(exc),
                root=root,
                game_date=game_date,
                require_game_date=False,
                emit_progress=emit_progress,
                label="ESPN_INJURIES",
            )

        _progress(emit_progress, _progress_banner("REFRESH STATSAPI TEAMS", str(baseball_savant_season)))
        try:
            teams = fetch_statsapi_teams_result(
                season=baseball_savant_season,
                sport_ids=(MLB_STATSAPI_MAJOR_SPORT_ID,),
                root=root,
                normalize=True,
            )
            payload["statsapi_teams"] = teams.payload
            _progress(emit_progress, _source_refresh_line("STATSAPI_TEAMS", teams.payload))
        except Exception as exc:  # pragma: no cover - defensive live-source boundary
            _record_context_error_or_fallback(
                payload,
                key="statsapi_teams",
                source="statsapi_teams",
                staged_subdir="statsapi_teams",
                required_file="statsapi_teams.jsonl",
                reason=str(exc),
                root=root,
                game_date=game_date,
                require_game_date=False,
                emit_progress=emit_progress,
                label="STATSAPI_TEAMS",
            )

        _progress(emit_progress, _progress_banner("REFRESH STATSAPI SCHEDULE", game_date))
        try:
            schedule = fetch_statsapi_schedule_result(
                sport_id=MLB_STATSAPI_MAJOR_SPORT_ID,
                start_date=game_date,
                end_date=game_date,
                root=root,
                normalize=True,
            )
            payload["statsapi_schedule"] = schedule.payload
            _progress(emit_progress, _source_refresh_line("STATSAPI_SCHEDULE", schedule.payload))
        except Exception as exc:  # pragma: no cover - defensive live-source boundary
            _record_context_error_or_fallback(
                payload,
                key="statsapi_schedule",
                source="statsapi_schedule",
                staged_subdir="statsapi_schedule",
                required_file="statsapi_schedule.jsonl",
                reason=str(exc),
                root=root,
                game_date=game_date,
                require_game_date=True,
                emit_progress=emit_progress,
                label="STATSAPI_SCHEDULE",
            )

        _progress(emit_progress, _progress_banner("REFRESH STATSAPI ROSTERS BULK", str(baseball_savant_season)))
        try:
            rosters = fetch_statsapi_rosters_bulk_result(
                season=baseball_savant_season,
                sport_ids=(MLB_STATSAPI_MAJOR_SPORT_ID,),
                root=root,
                normalize=True,
            )
            payload["statsapi_rosters_bulk"] = rosters.payload
            _progress(emit_progress, _source_refresh_line("STATSAPI_ROSTERS_BULK", rosters.payload))
        except Exception as exc:  # pragma: no cover - defensive live-source boundary
            _record_context_error_or_fallback(
                payload,
                key="statsapi_rosters_bulk",
                source="statsapi_rosters_bulk",
                staged_subdir="statsapi_rosters_bulk",
                required_file="statsapi_rosters_bulk.jsonl",
                reason=str(exc),
                root=root,
                game_date=game_date,
                require_game_date=False,
                emit_progress=emit_progress,
                label="STATSAPI_ROSTERS_BULK",
            )

        _progress(emit_progress, _progress_banner("REFRESH STATSAPI TRANSACTIONS", game_date))
        try:
            parsed_game_date = date.fromisoformat(game_date)
            transaction_start = (parsed_game_date - timedelta(days=14)).isoformat()
            transactions = fetch_statsapi_transactions_result(
                sport_id=MLB_STATSAPI_MAJOR_SPORT_ID,
                start_date=transaction_start,
                end_date=game_date,
                root=root,
                normalize=True,
            )
            payload["statsapi_transactions"] = transactions.payload
            _progress(emit_progress, _source_refresh_line("STATSAPI_TRANSACTIONS", transactions.payload))
        except Exception as exc:  # pragma: no cover - defensive live-source boundary
            _record_context_error_or_fallback(
                payload,
                key="statsapi_transactions",
                source="statsapi_transactions",
                staged_subdir="statsapi_transactions",
                required_file="statsapi_transactions.jsonl",
                reason=str(exc),
                root=root,
                game_date=game_date,
                require_game_date=False,
                emit_progress=emit_progress,
                label="STATSAPI_TRANSACTIONS",
            )

    return payload


def _record_context_error_or_fallback(
    payload: dict[str, Any],
    *,
    key: str,
    source: str,
    staged_subdir: str,
    required_file: str,
    reason: str,
    root: Path | None,
    game_date: str,
    require_game_date: bool,
    emit_progress: Callable[[str], None] | None,
    label: str,
) -> None:
    error = {"source": source, "reason": reason}
    paths = ensure_mlb_dirs(root)
    fallback = _existing_context_normalization(
        paths,
        staged_subdir=staged_subdir,
        source=source,
        required_file=required_file,
        game_date=game_date if require_game_date else None,
    )
    if fallback:
        fallback_payload = _context_fallback_payload(
            normalized_dir=fallback,
            error=error,
            game_date=game_date,
            required_file=required_file,
        )
        payload[key] = fallback_payload
        payload["fallbacks"].append(
            {
                "source": source,
                "reason": reason,
                "fallback_output_dir": str(fallback),
                "game_date_required": require_game_date,
            }
        )
        payload["warnings"].append(
            {
                "source": source,
                "reason": "fresh_fetch_failed_used_existing_context",
                "fresh_fetch_error": reason,
                "fallback_output_dir": str(fallback),
            }
        )
        _progress(
            emit_progress,
            f"[{label} FALLBACK] fresh fetch failed; using existing staged context "
            f"{fallback} ({reason})",
        )
        return
    payload["errors"].append(error)
    _progress(emit_progress, f"[{label} ERROR] {reason}")


def _existing_context_normalization(
    paths,
    *,
    staged_subdir: str,
    source: str,
    required_file: str,
    game_date: str | None = None,
) -> Path | None:
    staged_root = paths.staged / staged_subdir
    if not staged_root.exists():
        return None
    candidates = sorted(staged_root.glob("*/normalize_manifest.json"), key=lambda path: (path.stat().st_mtime, path.parent.name))
    for manifest_path in reversed(candidates):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if source and manifest.get("source") != source:
            continue
        rows_path = manifest_path.parent / required_file
        if not rows_path.exists():
            continue
        if game_date:
            manifest_game_date = str(manifest.get("game_date") or "").strip()[:10]
            if manifest_game_date:
                if manifest_game_date != game_date[:10]:
                    continue
            elif not _jsonl_has_game_date(rows_path, game_date):
                continue
        return manifest_path.parent
    return None


def _context_fallback_payload(
    *,
    normalized_dir: Path,
    error: dict[str, Any],
    game_date: str,
    required_file: str,
) -> dict[str, Any]:
    manifest = _market_source_normalization_manifest(normalized_dir)
    source = str(manifest.get("source") or error.get("source") or "")
    normalized = dict(manifest)
    normalized.update(
        {
            "fallback_used": True,
            "fallback_output_dir": str(normalized_dir),
            "fresh_fetch_status": "error",
            "fresh_fetch_errors": [error],
        }
    )
    return {
        "source": source,
        "snapshot_id": str(manifest.get("snapshot_id") or manifest.get("run_id") or normalized_dir.name),
        "payload_path": "",
        "manifest_path": "",
        "checksum": "",
        "record_count": manifest.get("record_count"),
        "request": {
            "fallback_used": True,
            "required_file": required_file,
            "game_date": game_date,
        },
        "normalized": normalized,
        "fallback_used": True,
        "fresh_fetch_status": "error",
        "fresh_fetch_errors": [error],
    }


def _progress(emit_progress: Callable[[str], None] | None, message: str) -> None:
    if emit_progress is not None:
        emit_progress(message)


def _progress_banner(title: str, detail: str = "") -> str:
    line = "=" * 72
    suffix = f" {detail}" if detail else ""
    return f"\n{line}\n[{title}]{suffix}\n{line}"


def _context_line(label: str, manifest: dict[str, Any] | None) -> str:
    payload = manifest or {}
    parts = [f"[{label}]"]
    for key in (
        "row_count",
        "source_row_count",
        "market_source_row_count",
        "injury_source_row_count",
        "schedule_source_row_count",
        "roster_source_row_count",
        "gamelog_source_row_count",
        "transaction_source_row_count",
        "profile_source_row_count",
    ):
        if key in payload:
            parts.append(f"{key}={payload.get(key)}")
    if "coverage_rate" in payload:
        parts.append(f"coverage={_pct(payload.get('coverage_rate'))}")
    for key in (
        "market_context_available_rate",
        "player_history_context_available_rate",
        "matchup_context_available_rate",
        "advanced_context_available_rate",
    ):
        if key in payload:
            parts.append(f"{key}={_pct(payload.get(key))}")
    if "json_path" in payload:
        parts.append(f"json={payload.get('json_path')}")
    if "manifest_path" in payload and "json_path" not in payload:
        parts.append(f"manifest={payload.get('manifest_path')}")
    return " ".join(str(part) for part in parts)


def _feature_line(manifest: dict[str, Any]) -> str:
    completeness = manifest.get("source_completeness") or {}
    return (
        f"[FEATURES] rows={manifest.get('row_count', 0)} "
        f"market={_pct(completeness.get('external_market_context_available'))} "
        f"lineup={_pct(completeness.get('lineup_context_available'))} "
        f"statsapi={_pct(completeness.get('statsapi_context_available'))} "
        f"roster={_pct(completeness.get('roster_context_available'))} "
        f"history={_pct(completeness.get('player_history_context_available'))} "
        f"transactions={_pct(completeness.get('transaction_source_available'))} "
        f"advanced={_pct(completeness.get('advanced_context_available'))} "
        f"weather={_pct(completeness.get('weather_context_available'))} "
        f"csv={manifest.get('csv_path', '')}"
    )


def _parameter_line(manifest: dict[str, Any]) -> str:
    return (
        f"[PARAMETERS] rows={manifest.get('row_count', 0)} "
        f"market={_pct(manifest.get('market_context_available_rate'))} "
        f"history={_pct(manifest.get('player_history_context_available_rate'))} "
        f"matchup={_pct(manifest.get('matchup_context_available_rate'))} "
        f"advanced={_pct(manifest.get('advanced_context_available_rate'))} "
        f"market_shift_mean={_fmt_float(manifest.get('market_target_shift_mean'))} "
        f"matchup_shift_mean={_fmt_float(manifest.get('matchup_target_shift_mean'))} "
        f"advanced_shift_mean={_fmt_float(manifest.get('advanced_target_shift_mean'))} "
        f"csv={manifest.get('csv_path', '')}"
    )


def _payout_line(slips_manifest: dict[str, Any]) -> str:
    payout = slips_manifest.get("payout_quote_manifest") or {}
    quote_count = payout.get("quote_count", 0)
    exact_count = payout.get("exact_quote_count", 0)
    fallback_count = payout.get("fallback_quote_count", 0)
    tool_version = payout.get("tool_version", "")
    return f"{exact_count}/{quote_count} exact fallback={fallback_count} tool={tool_version}"


def _source_refresh_line(label: str, payload: dict[str, Any] | None) -> str:
    source_payload = payload or {}
    normalized = source_payload.get("normalized") or {}
    row_detail = _row_detail(normalized) or _row_detail(source_payload)
    status_codes = ((source_payload.get("request") or {}).get("status_codes") or [])
    status_detail = f" status_codes={status_codes}" if status_codes else ""
    return (
        f"[{label}] ok snapshot={source_payload.get('snapshot_id', '')} "
        f"{row_detail}{status_detail} "
        f"payload={source_payload.get('payload_path', '')} "
        f"normalized_dir={normalized.get('output_dir', '')}"
    ).strip()


def _row_detail(payload: dict[str, Any]) -> str:
    if not payload:
        return ""
    if "row_count" in payload:
        return f"rows={payload.get('row_count')}"
    if "record_count" in payload:
        return f"records={payload.get('record_count')}"
    if "injury_count" in payload:
        return f"injuries={payload.get('injury_count')}"
    row_counts = payload.get("row_counts")
    if isinstance(row_counts, dict):
        detail = ",".join(f"{key}={value}" for key, value in sorted(row_counts.items()))
        return f"rows[{detail}]"
    return ""


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_float(value: Any) -> str:
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return "n/a"
