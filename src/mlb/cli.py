"""Safe Atlas MLB development CLI.

This CLI parses commands and delegates to runtime modules. It should not become
the orchestration hub for fetch, replay, model, publishing, or bundle logic.
"""

from __future__ import annotations

import argparse
from datetime import date, time
from pathlib import Path

from mlb.runtime.advanced_context import build_advanced_context_result, prepare_advanced_profiles_result
from mlb.runtime.ballparks import prepare_ballparks_result
from mlb.runtime.context_audit import build_context_audit_result
from mlb.runtime.inspection import run_inspection_command
from mlb.runtime.engine_inputs import publish_engine_board_result
from mlb.runtime.injury_context import build_injury_context_result
from mlb.runtime.live_delegation import live_plan_result
from mlb.runtime.live_execution import run_live_model_result
from mlb.runtime.market_context import build_market_context_result
from mlb.runtime.matchups import build_matchups_result
from mlb.runtime.player_history_context import build_player_history_context_result
from mlb.runtime.pipeline_execution import run_board_pipeline_result
from mlb.runtime.replay_delegation import replay_plan_result, replay_summary_result
from mlb.runtime.results import render_runtime_result
from mlb.runtime.roster_context import build_roster_context_result
from mlb.runtime.scoring import score_board_result
from mlb.runtime.replay_eval import evaluate_scored_run_result
from mlb.runtime.season_gamelogs import refresh_season_gamelogs_result
from mlb.runtime.source_operations import (
    fetch_baseball_reference_boxscore_result,
    fetch_baseball_reference_boxscores_bulk_result,
    fetch_bettingpros_props_result,
    fetch_baseball_savant_result,
    fetch_draftkings_live_result,
    fetch_draftkings_pick6_result,
    fetch_espn_game_context_result,
    fetch_espn_gamelog_result,
    fetch_espn_gamelogs_bulk_result,
    fetch_injuries_result,
    fetch_oddsapi_historical_result,
    fetch_oddsapi_live_result,
    fetch_parlayapi_historical_result,
    fetch_prizepicks_result,
    fetch_rotowire_result,
    fetch_statsapi_boxscore_result,
    fetch_statsapi_boxscores_bulk_result,
    fetch_statsapi_gamelog_result,
    fetch_statsapi_gamelogs_bulk_result,
    fetch_statsapi_roster_result,
    fetch_statsapi_rosters_bulk_result,
    fetch_statsapi_schedule_result,
    fetch_statsapi_teams_result,
    fetch_statsapi_transactions_result,
    fetch_umpscorecards_result,
    fetch_wunderground_history_result,
    import_legacy_prizepicks_raw_result,
    import_prizepicks_csv_result,
    backfill_baseball_savant_result,
    backfill_cbs_injuries_result,
    backfill_oddsapi_result,
    backfill_parlayapi_result,
    backfill_bettingpros_result,
    normalize_board_result,
    normalize_baseball_savant_result,
    normalize_baseball_reference_boxscore_result,
    normalize_bettingpros_result,
    normalize_covers_weather_result,
    normalize_draftkings_pick6_result,
    normalize_espn_game_context_result,
    normalize_espn_gamelogs_result,
    normalize_injuries_result,
    normalize_oddsapi_result,
    normalize_parlayapi_result,
    normalize_rotowire_result,
    normalize_statsapi_result,
    normalize_wunderground_history_result,
)
from mlb.runtime.statsapi_context import build_statsapi_context_result
from mlb.runtime.transaction_context import build_transaction_context_result
from mlb.runtime.umpires import prepare_umpires_result
from mlb.runtime.wind_factors import prepare_wind_factors_result
from mlb.sources.catalog import MLB_STATSAPI_DEFAULT_SPORT_IDS, MLB_STATSAPI_MAJOR_SPORT_ID


def _emit_result(args: argparse.Namespace, result) -> int:
    print(render_runtime_result(result, as_json=args.json))
    return 0


def _cmd_inspection(args: argparse.Namespace) -> int:
    return _emit_result(args, run_inspection_command(args.inspection_command))


def _cmd_live(args: argparse.Namespace) -> int:
    if args.plan:
        return _emit_result(args, live_plan_result())
    root = Path(args.root) if args.root else None
    snapshot = Path(args.snapshot) if args.snapshot else None
    normalized_dir = Path(args.normalized_dir) if args.normalized_dir else None
    calibration_artifact = Path(args.calibration_artifact) if args.calibration_artifact else None
    progress = None if args.json else (lambda message: print(message, flush=True))
    return _emit_result(
        args,
        run_live_model_result(
            root=root,
            run_id=args.run_id,
            game_date=args.date,
            state_code=args.state_code,
            snapshot_path=snapshot,
            normalized_dir=normalized_dir,
            include_all_sports=not args.skip_all_sports,
            refresh_bettingpros_odds=not args.no_bettingpros_odds_refresh,
            calibration_artifact_path=calibration_artifact,
            emit_progress=progress,
            fetch_attempts=args.fetch_attempts,
        ),
    )


def _cmd_replay_summary(args: argparse.Namespace) -> int:
    return _emit_result(args, replay_summary_result())


def _cmd_replay_single(args: argparse.Namespace) -> int:
    return _emit_result(args, replay_plan_result("single"))


def _cmd_replay_corpus(args: argparse.Namespace) -> int:
    return _emit_result(args, replay_plan_result("corpus"))


def _cmd_replay_bundle(args: argparse.Namespace) -> int:
    return _emit_result(args, replay_plan_result("bundle"))


def _cmd_fetch_prizepicks(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_prizepicks_result(
            state_code=args.state_code,
            normalize=not args.no_normalize,
            include_all_sports=not args.skip_all_sports,
            publish_engine_input=not args.no_engine_input,
        ),
    )


def _cmd_fetch_injuries(args: argparse.Namespace) -> int:
    return _emit_result(args, fetch_injuries_result(normalize=not args.no_normalize))


def _cmd_fetch_rotowire(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_rotowire_result(
            game_date=args.date,
            pages=args.pages,
            normalize=not args.no_normalize,
        ),
    )


def _cmd_fetch_espn_game_context(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_espn_game_context_result(
            game_date=args.date,
            normalize=not args.no_normalize,
        ),
    )


def _cmd_fetch_espn_gamelog(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_espn_gamelog_result(
            athlete_id=args.athlete_id,
            season=args.season,
            normalize=not args.no_normalize,
        ),
    )


def _cmd_fetch_espn_gamelogs_bulk(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_espn_gamelogs_bulk_result(
            athlete_ids=_parse_strings(args.athlete_ids),
            season=args.season,
            limit=args.limit,
            normalize=not args.no_normalize,
        ),
    )


def _cmd_fetch_baseball_reference_boxscore(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_baseball_reference_boxscore_result(
            url=args.url,
            game_date=args.date,
            normalize=not args.no_normalize,
        ),
    )


def _cmd_fetch_baseball_reference_boxscores_bulk(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        fetch_baseball_reference_boxscores_bulk_result(
            start_date=date.fromisoformat(args.start_date),
            end_date=date.fromisoformat(args.end_date),
            root=root,
            normalize=not args.no_normalize,
            delay_s=args.delay_s,
            limit=args.limit,
        ),
    )


def _cmd_fetch_wunderground_history(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else None
    weather_url_source = Path(args.weather_url_source) if args.weather_url_source else None
    return _emit_result(
        args,
        fetch_wunderground_history_result(
            start_date=date.fromisoformat(args.start_date),
            end_date=date.fromisoformat(args.end_date),
            root=root,
            normalize=not args.no_normalize,
            api_key=args.api_key,
            weather_url_source=weather_url_source,
            delay_s=args.delay_s,
            limit=args.limit,
        ),
    )


def _cmd_fetch_baseball_savant(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_baseball_savant_result(
            game_date=args.date,
            season=args.season,
            pages=args.pages,
            normalize=not args.no_normalize,
        ),
    )


def _cmd_fetch_umpscorecards(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_umpscorecards_result(
            start_date=args.start_date,
            end_date=args.end_date,
            season_type=args.season_type,
            normalize=not args.no_normalize,
        ),
    )


def _cmd_fetch_oddsapi_live(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_oddsapi_live_result(
            regions=args.regions,
            bookmakers=args.bookmakers,
            markets=args.markets,
            normalize=not args.no_normalize,
        ),
    )


def _cmd_fetch_draftkings_live(args: argparse.Namespace) -> int:
    return _emit_result(args, fetch_draftkings_live_result(site=args.site))


def _cmd_fetch_draftkings_pick6(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_draftkings_pick6_result(
            sport_league_key=args.sport_league_key,
            normalize=not args.no_normalize,
        ),
    )


def _cmd_fetch_bettingpros_props(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_bettingpros_props_result(
            game_date=date.fromisoformat(args.date),
            include_offers=args.include_offers,
            markets=args.markets,
            book_ids=args.book_ids,
            offer_workers=args.offer_workers,
            max_offer_pages=args.max_offer_pages,
            normalize=not args.no_normalize,
        ),
    )


def _cmd_fetch_oddsapi_historical(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_oddsapi_historical_result(
            snapshot_date=date.fromisoformat(args.date),
            snapshot_time_utc=_parse_time(args.snapshot_time_utc),
            regions=args.regions,
            bookmakers=args.bookmakers,
            markets=args.markets,
            normalize=not args.no_normalize,
        ),
    )


def _cmd_fetch_parlayapi_historical(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_parlayapi_historical_result(
            snapshot_date=date.fromisoformat(args.date),
            snapshot_time_utc=_parse_time(args.snapshot_time_utc),
            bookmakers=args.bookmakers,
            markets=args.markets,
            normalize=not args.no_normalize,
        ),
    )


def _cmd_normalize_board(args: argparse.Namespace) -> int:
    snapshot = Path(args.snapshot) if args.snapshot else None
    return _emit_result(args, normalize_board_result(snapshot_path=snapshot, run_id=args.run_id))


def _cmd_prepare_engine_board(args: argparse.Namespace) -> int:
    normalized_dir = Path(args.normalized_dir) if args.normalized_dir else None
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        publish_engine_board_result(
            normalized_dir=normalized_dir,
            root=root,
            run_id=args.run_id,
            game_date=args.date,
            include_all_dates=args.all_dates,
        ),
    )


def _cmd_prepare_matchups(args: argparse.Namespace) -> int:
    engine_board = Path(args.engine_board) if args.engine_board else None
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        build_matchups_result(
            engine_board_path=engine_board,
            root=root,
            run_id=args.run_id,
            game_date=args.date,
            directions=_parse_directions(args.directions),
        ),
    )


def _cmd_prepare_market_context(args: argparse.Namespace) -> int:
    engine_board = Path(args.engine_board) if args.engine_board else None
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        build_market_context_result(
            engine_board_path=engine_board,
            root=root,
            run_id=args.run_id,
            game_date=args.date,
        ),
    )


def _cmd_prepare_injury_context(args: argparse.Namespace) -> int:
    engine_board = Path(args.engine_board) if args.engine_board else None
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        build_injury_context_result(
            engine_board_path=engine_board,
            root=root,
            run_id=args.run_id,
            game_date=args.date,
        ),
    )


def _cmd_prepare_statsapi_context(args: argparse.Namespace) -> int:
    engine_board = Path(args.engine_board) if args.engine_board else None
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        build_statsapi_context_result(
            engine_board_path=engine_board,
            root=root,
            run_id=args.run_id,
            game_date=args.date,
        ),
    )


def _cmd_prepare_roster_context(args: argparse.Namespace) -> int:
    engine_board = Path(args.engine_board) if args.engine_board else None
    statsapi_context = Path(args.statsapi_context) if args.statsapi_context else None
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        build_roster_context_result(
            engine_board_path=engine_board,
            statsapi_context_path=statsapi_context,
            root=root,
            run_id=args.run_id,
            game_date=args.date,
        ),
    )


def _cmd_prepare_player_history_context(args: argparse.Namespace) -> int:
    engine_board = Path(args.engine_board) if args.engine_board else None
    roster_context = Path(args.roster_context) if args.roster_context else None
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        build_player_history_context_result(
            engine_board_path=engine_board,
            roster_context_path=roster_context,
            root=root,
            run_id=args.run_id,
            game_date=args.date,
        ),
    )


def _cmd_prepare_transaction_context(args: argparse.Namespace) -> int:
    engine_board = Path(args.engine_board) if args.engine_board else None
    roster_context = Path(args.roster_context) if args.roster_context else None
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        build_transaction_context_result(
            engine_board_path=engine_board,
            roster_context_path=roster_context,
            root=root,
            run_id=args.run_id,
            game_date=args.date,
            lookback_days=args.lookback_days,
        ),
    )


def _cmd_prepare_umpires(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        prepare_umpires_result(source_path=Path(args.source), root=root, run_id=args.run_id),
    )


def _cmd_prepare_ballparks(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        prepare_ballparks_result(source_path=Path(args.source), root=root, run_id=args.run_id),
    )


def _cmd_prepare_wind_factors(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        prepare_wind_factors_result(source_path=Path(args.source), root=root, run_id=args.run_id),
    )


def _cmd_prepare_advanced_profiles(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        prepare_advanced_profiles_result(source_path=Path(args.source), root=root, run_id=args.run_id),
    )


def _cmd_prepare_advanced_context(args: argparse.Namespace) -> int:
    engine_board = Path(args.engine_board) if args.engine_board else None
    source = Path(args.source) if args.source else None
    profiles = Path(args.profiles) if args.profiles else None
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        build_advanced_context_result(
            engine_board_path=engine_board,
            source_path=source,
            profiles_path=profiles,
            root=root,
            run_id=args.run_id,
            game_date=args.date,
        ),
    )


def _cmd_score_board(args: argparse.Namespace) -> int:
    engine_board = Path(args.engine_board) if args.engine_board else None
    parameter_table = Path(args.parameter_table) if args.parameter_table else None
    feature_table = Path(args.feature_table) if args.feature_table else None
    return _emit_result(
        args,
        score_board_result(
            engine_board_path=engine_board,
            parameter_table_path=parameter_table,
            feature_table_path=feature_table,
            run_id=args.run_id,
        ),
    )


def _cmd_run_board(args: argparse.Namespace) -> int:
    snapshot = Path(args.snapshot) if args.snapshot else None
    normalized_dir = Path(args.normalized_dir) if args.normalized_dir else None
    root = Path(args.root) if args.root else None
    calibration_artifact = Path(args.calibration_artifact) if args.calibration_artifact else None
    return _emit_result(
        args,
        run_board_pipeline_result(
            snapshot_path=snapshot,
            normalized_dir=normalized_dir,
            root=root,
            run_id=args.run_id,
            run_mode=args.run_mode,
            game_date=args.date,
            include_all_dates=args.all_dates,
            refresh_context_sources=args.refresh_context_sources,
            rotowire_pages=args.rotowire_pages,
            baseball_savant_pages=args.baseball_savant_pages,
            baseball_savant_season=args.baseball_savant_season,
            refresh_bettingpros_odds=not args.no_bettingpros_odds_refresh,
            calibration_artifact_path=calibration_artifact,
        ),
    )


def _cmd_audit_context(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        build_context_audit_result(
            run_id=args.run_id,
            root=root,
            write_artifacts=not args.no_write,
        ),
    )


def _cmd_audit_eval(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else None
    scored_legs = Path(args.scored_legs) if args.scored_legs else None
    return _emit_result(
        args,
        evaluate_scored_run_result(
            run_id=args.run_id,
            scored_legs_path=scored_legs,
            root=root,
        ),
    )


def _cmd_prepare_season_gamelogs(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        refresh_season_gamelogs_result(season=args.season, through_date=args.through_date, root=root),
    )


def _cmd_normalize_injuries(args: argparse.Namespace) -> int:
    snapshot = Path(args.snapshot) if args.snapshot else None
    return _emit_result(args, normalize_injuries_result(snapshot_path=snapshot, run_id=args.run_id))


def _cmd_fetch_statsapi_teams(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_statsapi_teams_result(
            season=args.season,
            sport_ids=_parse_sport_ids(args.sport_ids),
            normalize=not args.no_normalize,
        ),
    )


def _cmd_fetch_statsapi_roster(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_statsapi_roster_result(team_id=args.team_id, season=args.season, normalize=not args.no_normalize),
    )


def _cmd_fetch_statsapi_rosters_bulk(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_statsapi_rosters_bulk_result(
            season=args.season,
            sport_ids=_parse_sport_ids(args.sport_ids),
            normalize=not args.no_normalize,
        ),
    )


def _cmd_fetch_statsapi_schedule(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_statsapi_schedule_result(
            sport_id=args.sport_id,
            start_date=args.start_date,
            end_date=args.end_date,
            normalize=not args.no_normalize,
        ),
    )


def _cmd_fetch_statsapi_boxscore(args: argparse.Namespace) -> int:
    return _emit_result(args, fetch_statsapi_boxscore_result(game_pk=args.game_pk, normalize=not args.no_normalize))


def _cmd_fetch_statsapi_boxscores_bulk(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_statsapi_boxscores_bulk_result(
            sport_id=args.sport_id,
            start_date=args.start_date,
            end_date=args.end_date,
            game_pks=_parse_ints(args.game_pks),
            normalize=not args.no_normalize,
        ),
    )


def _cmd_fetch_statsapi_gamelog(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_statsapi_gamelog_result(
            person_id=args.person_id,
            group=args.group,
            season=args.season,
            normalize=not args.no_normalize,
        ),
    )


def _cmd_fetch_statsapi_gamelogs_bulk(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_statsapi_gamelogs_bulk_result(
            person_ids=_parse_ints(args.person_ids),
            group=args.group,
            season=args.season,
            limit=args.limit,
            normalize=not args.no_normalize,
        ),
    )


def _cmd_fetch_statsapi_transactions(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        fetch_statsapi_transactions_result(
            sport_id=args.sport_id,
            start_date=args.start_date,
            end_date=args.end_date,
            normalize=not args.no_normalize,
        ),
    )


def _cmd_normalize_statsapi(args: argparse.Namespace) -> int:
    snapshot = Path(args.snapshot) if args.snapshot else None
    return _emit_result(args, normalize_statsapi_result(kind=args.kind, snapshot_path=snapshot, run_id=args.run_id))


def _cmd_normalize_espn_gamelogs(args: argparse.Namespace) -> int:
    snapshot = Path(args.snapshot) if args.snapshot else None
    return _emit_result(args, normalize_espn_gamelogs_result(kind=args.kind, snapshot_path=snapshot, run_id=args.run_id))


def _cmd_normalize_oddsapi(args: argparse.Namespace) -> int:
    snapshot = Path(args.snapshot) if args.snapshot else None
    return _emit_result(
        args,
        normalize_oddsapi_result(source=args.source, snapshot_path=snapshot, run_id=args.run_id),
    )


def _cmd_normalize_parlayapi(args: argparse.Namespace) -> int:
    snapshot = Path(args.snapshot) if args.snapshot else None
    return _emit_result(args, normalize_parlayapi_result(snapshot_path=snapshot, run_id=args.run_id))


def _cmd_normalize_draftkings_pick6(args: argparse.Namespace) -> int:
    snapshot = Path(args.snapshot) if args.snapshot else None
    return _emit_result(args, normalize_draftkings_pick6_result(snapshot_path=snapshot, run_id=args.run_id))


def _cmd_normalize_bettingpros(args: argparse.Namespace) -> int:
    snapshot = Path(args.snapshot) if args.snapshot else None
    return _emit_result(args, normalize_bettingpros_result(snapshot_path=snapshot, run_id=args.run_id))


def _cmd_normalize_rotowire(args: argparse.Namespace) -> int:
    snapshot = Path(args.snapshot) if args.snapshot else None
    return _emit_result(args, normalize_rotowire_result(snapshot_path=snapshot, run_id=args.run_id))


def _cmd_normalize_covers_weather(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        normalize_covers_weather_result(source_path=Path(args.source), root=root, run_id=args.run_id),
    )


def _cmd_normalize_espn_game_context(args: argparse.Namespace) -> int:
    snapshot = Path(args.snapshot) if args.snapshot else None
    return _emit_result(args, normalize_espn_game_context_result(snapshot_path=snapshot, run_id=args.run_id))


def _cmd_normalize_baseball_reference_boxscore(args: argparse.Namespace) -> int:
    snapshot = Path(args.snapshot) if args.snapshot else None
    return _emit_result(args, normalize_baseball_reference_boxscore_result(snapshot_path=snapshot, run_id=args.run_id))


def _cmd_normalize_wunderground_history(args: argparse.Namespace) -> int:
    snapshot = Path(args.snapshot) if args.snapshot else None
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        normalize_wunderground_history_result(snapshot_path=snapshot, root=root, run_id=args.run_id),
    )


def _cmd_normalize_baseball_savant(args: argparse.Namespace) -> int:
    snapshot = Path(args.snapshot) if args.snapshot else None
    return _emit_result(args, normalize_baseball_savant_result(snapshot_path=snapshot, run_id=args.run_id))


def _cmd_import_legacy_prizepicks(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        import_legacy_prizepicks_raw_result(
            source_dir=Path(args.source_dir),
            start_date=date.fromisoformat(args.start_date),
            end_date=date.fromisoformat(args.end_date),
            source_name=args.source_name,
        ),
    )


def _cmd_import_prizepicks_csv(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        import_prizepicks_csv_result(
            source_dir=Path(args.source_dir),
            start_date=date.fromisoformat(args.start_date),
            end_date=date.fromisoformat(args.end_date),
            root=root,
            publish_engine_input=not args.no_engine_input,
        ),
    )


def _cmd_backfill_oddsapi(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        backfill_oddsapi_result(
            start_date=date.fromisoformat(args.start_date),
            end_date=date.fromisoformat(args.end_date),
            snapshot_time_utc=_parse_time(args.snapshot_time_utc),
            regions=args.regions,
            bookmakers=args.bookmakers,
            markets=args.markets,
            dry_run=args.dry_run,
            force=args.force,
            assumed_games_per_day=args.assumed_games_per_day,
        ),
    )


def _cmd_backfill_parlayapi(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        backfill_parlayapi_result(
            start_date=date.fromisoformat(args.start_date),
            end_date=date.fromisoformat(args.end_date),
            snapshot_time_utc=_parse_time(args.snapshot_time_utc),
            bookmakers=args.bookmakers,
            markets=args.markets,
            dry_run=args.dry_run,
            force=args.force,
        ),
    )


def _cmd_backfill_bettingpros(args: argparse.Namespace) -> int:
    return _emit_result(
        args,
        backfill_bettingpros_result(
            start_date=date.fromisoformat(args.start_date),
            end_date=date.fromisoformat(args.end_date),
            include_offers=args.include_offers,
            markets=args.markets,
            book_ids=args.book_ids,
            offer_workers=args.offer_workers,
            max_offer_pages=args.max_offer_pages,
            dry_run=args.dry_run,
            force=args.force,
            normalize=not args.no_normalize,
        ),
    )


def _cmd_backfill_baseball_savant(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        backfill_baseball_savant_result(
            start_date=date.fromisoformat(args.start_date),
            end_date=date.fromisoformat(args.end_date),
            root=root,
            season=args.season,
            pages=args.pages,
            dry_run=args.dry_run,
            force=args.force,
        ),
    )


def _cmd_backfill_cbs_injuries(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else None
    return _emit_result(
        args,
        backfill_cbs_injuries_result(
            source_path=Path(args.source),
            start_date=date.fromisoformat(args.start_date) if args.start_date else None,
            end_date=date.fromisoformat(args.end_date) if args.end_date else None,
            root=root,
            run_id_prefix=args.run_id_prefix,
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlas-mlb", description="Atlas MLB development skeleton CLI")
    subparsers = parser.add_subparsers(dest="command")

    doctor = subparsers.add_parser("doctor", help="Verify MLB-dev skeleton paths and safety state")
    doctor.add_argument("--text", action="store_true", help="Render the doctor report as text instead of JSON")
    doctor.set_defaults(func=_cmd_inspection, inspection_command="doctor", json=True)

    live = subparsers.add_parser("live", help="Fetch the current PrizePicks MLB board and run the live model")
    live.add_argument("--json", action="store_true", help="Render command output as JSON")
    live.add_argument("--plan", action="store_true", help="Show live-run plan and guardrails without executing")
    live.add_argument("--root", help="Override repo root for test/dev execution")
    live.add_argument("--run-id", help="Override live run id")
    live.add_argument("--date", help="Only run props for this YYYY-MM-DD game date; defaults to snapshot-local date")
    live.add_argument("--state-code", default="MO", help="PrizePicks state code")
    live.add_argument("--snapshot", help="Use an existing raw PrizePicks snapshot instead of fetching")
    live.add_argument("--normalized-dir", help="Use an existing normalized PrizePicks board directory instead of fetching")
    live.add_argument(
        "--skip-all-sports",
        action="store_true",
        help="Fetch only the MLB-scoped PrizePicks board",
    )
    live.add_argument(
        "--no-bettingpros-odds-refresh",
        action="store_true",
        help="Do not auto-fetch/stage BettingPros odds before market context",
    )
    live.add_argument("--calibration-artifact", help="Optional calibration metadata JSON")
    live.add_argument("--fetch-attempts", type=int, default=3, help="PrizePicks fetch retry attempts")
    live.set_defaults(func=_cmd_live)

    replay = subparsers.add_parser("replay", help="Show replay modes or a replay plan")
    replay.add_argument("--json", action="store_true", help="Render replay mode summary as JSON")
    replay.set_defaults(func=_cmd_replay_summary)
    replay_subparsers = replay.add_subparsers(dest="replay_mode")

    replay_single = replay_subparsers.add_parser("single", help="Plan one targeted replay run")
    replay_single.add_argument("--json", action="store_true", help="Render command output as JSON")
    replay_single.set_defaults(func=_cmd_replay_single)

    replay_corpus = replay_subparsers.add_parser("corpus", help="Plan a corpus replay for corpus/cache/training")
    replay_corpus.add_argument("--json", action="store_true", help="Render command output as JSON")
    replay_corpus.set_defaults(func=_cmd_replay_corpus)

    replay_bundle = replay_subparsers.add_parser("bundle", help="Compatibility alias for replay corpus")
    replay_bundle.add_argument("--json", action="store_true", help="Render command output as JSON")
    replay_bundle.set_defaults(func=_cmd_replay_bundle)

    markets = subparsers.add_parser("markets", help="List canonical MLB market names")
    markets.add_argument("--json", action="store_true", help="Render command output as JSON")
    markets.set_defaults(func=_cmd_inspection, inspection_command="markets")

    paths = subparsers.add_parser("paths", help="Print MLB development paths")
    paths.add_argument("--json", action="store_true", help="Render command output as JSON")
    paths.set_defaults(func=_cmd_inspection, inspection_command="paths")

    sources = subparsers.add_parser("sources", help="List configured MLB data sources")
    sources.add_argument("--json", action="store_true", help="Render command output as JSON")
    sources.set_defaults(func=_cmd_inspection, inspection_command="sources")

    fetch = subparsers.add_parser("fetch", help="Fetch raw MLB source snapshots")
    fetch_subparsers = fetch.add_subparsers(dest="fetch_source", required=True)

    fetch_prizepicks = fetch_subparsers.add_parser("prizepicks", help="Fetch PrizePicks MLB board")
    fetch_prizepicks.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_prizepicks.add_argument("--state-code", default="MO", help="PrizePicks state code")
    fetch_prizepicks.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_prizepicks.add_argument(
        "--skip-all-sports",
        action="store_true",
        help="Fetch only the MLB-scoped PrizePicks board",
    )
    fetch_prizepicks.add_argument(
        "--no-engine-input",
        action="store_true",
        help="Do not publish engine-ready board CSV/JSON after normalization",
    )
    fetch_prizepicks.set_defaults(func=_cmd_fetch_prizepicks)

    fetch_injuries = fetch_subparsers.add_parser("injuries", help="Fetch ESPN MLB injuries")
    fetch_injuries.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_injuries.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_injuries.set_defaults(func=_cmd_fetch_injuries)

    fetch_rotowire = fetch_subparsers.add_parser("rotowire", help="Fetch Rotowire MLB context pages")
    fetch_rotowire.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_rotowire.add_argument("--date", help="Rotowire context date, YYYY-MM-DD")
    fetch_rotowire.add_argument(
        "--pages",
        default="default",
        help=(
            "Comma-separated page keys or 'default'. Default captures daily_lineups, batting_orders, "
            "projected_starters, bullpen_usage, reliever_usage, lineup_card, weather, umpires, and odds."
        ),
    )
    fetch_rotowire.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_rotowire.set_defaults(func=_cmd_fetch_rotowire)

    fetch_espn_game_context = fetch_subparsers.add_parser(
        "espn-game-context",
        help="Fetch ESPN MLB scoreboard, summaries, lineups, starters, venue, and umpire context",
    )
    fetch_espn_game_context.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_espn_game_context.add_argument("--date", required=True, help="ESPN context date, YYYY-MM-DD")
    fetch_espn_game_context.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_espn_game_context.set_defaults(func=_cmd_fetch_espn_game_context)

    fetch_espn_gamelog = fetch_subparsers.add_parser("espn-gamelog", help="Fetch one ESPN MLB athlete game log")
    fetch_espn_gamelog.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_espn_gamelog.add_argument("--athlete-id", required=True, help="ESPN athlete ID")
    fetch_espn_gamelog.add_argument("--season", type=int, default=2026)
    fetch_espn_gamelog.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_espn_gamelog.set_defaults(func=_cmd_fetch_espn_gamelog)

    fetch_espn_gamelogs_bulk = fetch_subparsers.add_parser(
        "espn-gamelogs-bulk",
        help="Fetch ESPN MLB athlete game logs for IDs or normalized ESPN game context players",
    )
    fetch_espn_gamelogs_bulk.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_espn_gamelogs_bulk.add_argument(
        "--athlete-ids",
        default="",
        help="Optional comma-separated ESPN athlete IDs; when omitted staged ESPN game context is used",
    )
    fetch_espn_gamelogs_bulk.add_argument("--season", type=int, default=2026)
    fetch_espn_gamelogs_bulk.add_argument("--limit", type=int, default=0, help="Optional max player count for staged pulls")
    fetch_espn_gamelogs_bulk.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_espn_gamelogs_bulk.set_defaults(func=_cmd_fetch_espn_gamelogs_bulk)

    fetch_baseball_reference_boxscore = fetch_subparsers.add_parser(
        "baseball-reference-boxscore",
        help="Fetch one Baseball Reference boxscore starting-lineup page",
    )
    fetch_baseball_reference_boxscore.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_baseball_reference_boxscore.add_argument("--url", required=True, help="Baseball Reference boxscore URL")
    fetch_baseball_reference_boxscore.add_argument("--date", help="Optional game date, YYYY-MM-DD")
    fetch_baseball_reference_boxscore.add_argument(
        "--no-normalize",
        action="store_true",
        help="Only write the raw snapshot",
    )
    fetch_baseball_reference_boxscore.set_defaults(func=_cmd_fetch_baseball_reference_boxscore)

    fetch_baseball_reference_boxscores_bulk = fetch_subparsers.add_parser(
        "baseball-reference-boxscores-bulk",
        help="Fetch Baseball Reference starting-lineup pages for a StatsAPI schedule date range",
    )
    fetch_baseball_reference_boxscores_bulk.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_baseball_reference_boxscores_bulk.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    fetch_baseball_reference_boxscores_bulk.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    fetch_baseball_reference_boxscores_bulk.add_argument("--root", help="Override repo root for test/dev execution")
    fetch_baseball_reference_boxscores_bulk.add_argument("--delay-s", type=float, default=None, help="Delay between page fetches")
    fetch_baseball_reference_boxscores_bulk.add_argument("--limit", type=int, default=0, help="Optional max games to fetch")
    fetch_baseball_reference_boxscores_bulk.add_argument(
        "--no-normalize",
        action="store_true",
        help="Only write the raw snapshot",
    )
    fetch_baseball_reference_boxscores_bulk.set_defaults(func=_cmd_fetch_baseball_reference_boxscores_bulk)

    fetch_wunderground_history = fetch_subparsers.add_parser(
        "wunderground-history",
        help="Fetch Weather Underground historical observed weather for a StatsAPI schedule date range",
    )
    fetch_wunderground_history.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_wunderground_history.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    fetch_wunderground_history.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    fetch_wunderground_history.add_argument("--root", help="Override repo root for test/dev execution")
    fetch_wunderground_history.add_argument("--weather-url-source", help="Captured Wunderground network URL text file")
    fetch_wunderground_history.add_argument("--api-key", help="Weather.com API key override; prefer env vars")
    fetch_wunderground_history.add_argument("--delay-s", type=float, default=None, help="Delay between API fetches")
    fetch_wunderground_history.add_argument("--limit", type=int, default=0, help="Optional max games to fetch")
    fetch_wunderground_history.add_argument(
        "--no-normalize",
        action="store_true",
        help="Only write the raw snapshot",
    )
    fetch_wunderground_history.set_defaults(func=_cmd_fetch_wunderground_history)

    fetch_baseball_savant = fetch_subparsers.add_parser(
        "baseball-savant",
        help="Fetch Baseball Savant MLB context pages",
    )
    fetch_baseball_savant.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_baseball_savant.add_argument("--date", help="Schedule date, YYYY-MM-DD")
    fetch_baseball_savant.add_argument("--season", type=int, default=2026)
    fetch_baseball_savant.add_argument(
        "--pages",
        default="default",
        help=(
            "Comma-separated page keys or 'default'. Default captures custom_batter, custom_pitcher, "
            "park_factors, schedule, and trending_players."
        ),
    )
    fetch_baseball_savant.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_baseball_savant.set_defaults(func=_cmd_fetch_baseball_savant)

    fetch_umpscorecards = fetch_subparsers.add_parser(
        "umpscorecards",
        help="Fetch UmpScorecards MLB game scorecards and stage umpire profiles",
    )
    fetch_umpscorecards.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_umpscorecards.add_argument("--start-date", required=True, help="First scorecard date, YYYY-MM-DD")
    fetch_umpscorecards.add_argument("--end-date", required=True, help="Last scorecard date, YYYY-MM-DD")
    fetch_umpscorecards.add_argument("--season-type", default="R", help="UmpScorecards season type, default R")
    fetch_umpscorecards.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_umpscorecards.set_defaults(func=_cmd_fetch_umpscorecards)

    fetch_oddsapi_live = fetch_subparsers.add_parser("oddsapi-live", help="Fetch live OddsAPI MLB props")
    fetch_oddsapi_live.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_oddsapi_live.add_argument("--regions", default="us", help="Comma-separated OddsAPI regions")
    fetch_oddsapi_live.add_argument(
        "--bookmakers",
        default="default",
        help="Comma-separated bookmaker keys, 'default' for PrizePicks/DraftKings/FanDuel, or 'all'",
    )
    fetch_oddsapi_live.add_argument("--markets", default="default", help="Comma-separated market keys or 'default'")
    fetch_oddsapi_live.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_oddsapi_live.set_defaults(func=_cmd_fetch_oddsapi_live)

    fetch_draftkings_live = fetch_subparsers.add_parser(
        "draftkings-live",
        help="Fetch DraftKings Sportsbook MLB live odds probe",
    )
    fetch_draftkings_live.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_draftkings_live.add_argument("--site", default="dkusnj", help="DraftKings site key, default dkusnj")
    fetch_draftkings_live.set_defaults(func=_cmd_fetch_draftkings_live)

    fetch_draftkings_pick6 = fetch_subparsers.add_parser(
        "draftkings-pick6",
        help="Fetch DraftKings Pick6 MLB player-prop lines",
    )
    fetch_draftkings_pick6.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_draftkings_pick6.add_argument(
        "--sport-league-key",
        default="2-2",
        help="DraftKings Pick6 sportLeagueKey; default 2-2 for MLB",
    )
    fetch_draftkings_pick6.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_draftkings_pick6.set_defaults(func=_cmd_fetch_draftkings_pick6)

    fetch_bettingpros = fetch_subparsers.add_parser(
        "bettingpros-props",
        help="Fetch BettingPros MLB player-prop consensus and optional sportsbook offers",
    )
    fetch_bettingpros.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_bettingpros.add_argument("--date", required=True, help="Props date, YYYY-MM-DD")
    fetch_bettingpros.add_argument(
        "--include-offers",
        action="store_true",
        help="Also fetch full BettingPros sportsbook offer pages for every event/market",
    )
    fetch_bettingpros.add_argument(
        "--markets",
        default="default",
        help="Comma-separated BettingPros market IDs or Atlas market keys, or 'default'",
    )
    fetch_bettingpros.add_argument(
        "--book-ids",
        default="",
        help="Optional comma-separated BettingPros book IDs, 'major', or blank for all available offer books",
    )
    fetch_bettingpros.add_argument(
        "--max-offer-pages",
        type=int,
        default=0,
        help="Optional cap for offer pages; 0 means fetch all available offer pages",
    )
    fetch_bettingpros.add_argument(
        "--offer-workers",
        type=int,
        default=4,
        help="Parallel offer page workers when --include-offers is used",
    )
    fetch_bettingpros.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_bettingpros.set_defaults(func=_cmd_fetch_bettingpros_props)

    fetch_oddsapi_historical = fetch_subparsers.add_parser(
        "oddsapi-historical",
        help="Fetch one historical OddsAPI MLB prop date",
    )
    fetch_oddsapi_historical.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_oddsapi_historical.add_argument("--date", required=True, help="Historical date, YYYY-MM-DD")
    fetch_oddsapi_historical.add_argument("--snapshot-time-utc", default="18:00:00", help="Historical snapshot time")
    fetch_oddsapi_historical.add_argument("--regions", default="us", help="Comma-separated OddsAPI regions")
    fetch_oddsapi_historical.add_argument(
        "--bookmakers",
        default="default",
        help="Comma-separated bookmaker keys, 'default' for PrizePicks/DraftKings/FanDuel, or 'all'",
    )
    fetch_oddsapi_historical.add_argument("--markets", default="default", help="Comma-separated market keys or 'default'")
    fetch_oddsapi_historical.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_oddsapi_historical.set_defaults(func=_cmd_fetch_oddsapi_historical)

    fetch_parlayapi_historical = fetch_subparsers.add_parser(
        "parlayapi-historical",
        help="Fetch one historical ParlayAPI MLB closing-prop date",
    )
    fetch_parlayapi_historical.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_parlayapi_historical.add_argument("--date", required=True, help="Historical date, YYYY-MM-DD")
    fetch_parlayapi_historical.add_argument("--snapshot-time-utc", default="18:00:00", help="Historical snapshot time")
    fetch_parlayapi_historical.add_argument(
        "--bookmakers",
        default="",
        help="Optional comma-separated ParlayAPI bookmaker filter; blank means provider default",
    )
    fetch_parlayapi_historical.add_argument(
        "--markets",
        default="default",
        help="Comma-separated ParlayAPI or Atlas market keys, or 'default'",
    )
    fetch_parlayapi_historical.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_parlayapi_historical.set_defaults(func=_cmd_fetch_parlayapi_historical)

    fetch_teams = fetch_subparsers.add_parser("statsapi-teams", help="Fetch MLB StatsAPI teams")
    fetch_teams.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_teams.add_argument("--season", type=int, default=2026)
    fetch_teams.add_argument(
        "--sport-ids",
        default=",".join(str(sport_id) for sport_id in MLB_STATSAPI_DEFAULT_SPORT_IDS),
        help="Comma-separated sport IDs; default includes MLB and configured MiLB levels",
    )
    fetch_teams.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_teams.set_defaults(func=_cmd_fetch_statsapi_teams)

    fetch_roster = fetch_subparsers.add_parser("statsapi-roster", help="Fetch one MLB StatsAPI roster")
    fetch_roster.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_roster.add_argument("--team-id", type=int, required=True)
    fetch_roster.add_argument("--season", type=int, default=2026)
    fetch_roster.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_roster.set_defaults(func=_cmd_fetch_statsapi_roster)

    fetch_rosters_bulk = fetch_subparsers.add_parser(
        "statsapi-rosters-bulk",
        help="Fetch one combined StatsAPI roster snapshot for staged teams",
    )
    fetch_rosters_bulk.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_rosters_bulk.add_argument("--season", type=int, default=2026)
    fetch_rosters_bulk.add_argument(
        "--sport-ids",
        default=str(MLB_STATSAPI_MAJOR_SPORT_ID),
        help="Comma-separated sport IDs to include; default MLB only",
    )
    fetch_rosters_bulk.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_rosters_bulk.set_defaults(func=_cmd_fetch_statsapi_rosters_bulk)

    fetch_schedule = fetch_subparsers.add_parser("statsapi-schedule", help="Fetch MLB StatsAPI schedule/game IDs")
    fetch_schedule.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_schedule.add_argument("--sport-id", type=int, required=True)
    fetch_schedule.add_argument("--start-date", required=True)
    fetch_schedule.add_argument("--end-date", required=True)
    fetch_schedule.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_schedule.set_defaults(func=_cmd_fetch_statsapi_schedule)

    fetch_boxscore = fetch_subparsers.add_parser("statsapi-boxscore", help="Fetch one MLB StatsAPI boxscore")
    fetch_boxscore.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_boxscore.add_argument("--game-pk", type=int, required=True)
    fetch_boxscore.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_boxscore.set_defaults(func=_cmd_fetch_statsapi_boxscore)

    fetch_boxscores_bulk = fetch_subparsers.add_parser(
        "statsapi-boxscores-bulk",
        help="Fetch MLB StatsAPI boxscores for game IDs or a schedule date range",
    )
    fetch_boxscores_bulk.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_boxscores_bulk.add_argument("--sport-id", type=int, default=MLB_STATSAPI_MAJOR_SPORT_ID)
    fetch_boxscores_bulk.add_argument("--start-date", required=True)
    fetch_boxscores_bulk.add_argument("--end-date", required=True)
    fetch_boxscores_bulk.add_argument(
        "--game-pks",
        default="",
        help="Optional comma-separated gamePk list; when omitted the schedule range is used",
    )
    fetch_boxscores_bulk.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_boxscores_bulk.set_defaults(func=_cmd_fetch_statsapi_boxscores_bulk)

    fetch_gamelog = fetch_subparsers.add_parser("statsapi-gamelog", help="Fetch one MLB StatsAPI player game log")
    fetch_gamelog.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_gamelog.add_argument("--person-id", type=int, required=True)
    fetch_gamelog.add_argument("--group", choices=("hitting", "pitching", "fielding"), required=True)
    fetch_gamelog.add_argument("--season", type=int, default=2026)
    fetch_gamelog.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_gamelog.set_defaults(func=_cmd_fetch_statsapi_gamelog)

    fetch_gamelogs_bulk = fetch_subparsers.add_parser(
        "statsapi-gamelogs-bulk",
        help="Fetch MLB StatsAPI player game logs for IDs or latest roster context",
    )
    fetch_gamelogs_bulk.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_gamelogs_bulk.add_argument(
        "--person-ids",
        default="",
        help="Optional comma-separated StatsAPI person IDs; when omitted latest roster context is used",
    )
    fetch_gamelogs_bulk.add_argument("--group", choices=("hitting", "pitching", "fielding"), default="hitting")
    fetch_gamelogs_bulk.add_argument("--season", type=int, default=2026)
    fetch_gamelogs_bulk.add_argument("--limit", type=int, default=0, help="Optional max player count for staged pulls")
    fetch_gamelogs_bulk.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_gamelogs_bulk.set_defaults(func=_cmd_fetch_statsapi_gamelogs_bulk)

    fetch_transactions = fetch_subparsers.add_parser(
        "statsapi-transactions",
        help="Fetch MLB StatsAPI roster transactions/call-ups",
    )
    fetch_transactions.add_argument("--json", action="store_true", help="Render command output as JSON")
    fetch_transactions.add_argument("--sport-id", type=int, default=MLB_STATSAPI_MAJOR_SPORT_ID)
    fetch_transactions.add_argument("--start-date", required=True)
    fetch_transactions.add_argument("--end-date", required=True)
    fetch_transactions.add_argument("--no-normalize", action="store_true", help="Only write the raw snapshot")
    fetch_transactions.set_defaults(func=_cmd_fetch_statsapi_transactions)

    normalize = subparsers.add_parser("normalize", help="Normalize saved MLB source snapshots")
    normalize_subparsers = normalize.add_subparsers(dest="normalize_target", required=True)

    normalize_board = normalize_subparsers.add_parser("board", help="Normalize a PrizePicks board snapshot")
    normalize_board.add_argument("--json", action="store_true", help="Render command output as JSON")
    normalize_board.add_argument("--snapshot", help="Payload path, manifest path, or snapshot directory")
    normalize_board.add_argument("--run-id", help="Override staged output run id")
    normalize_board.set_defaults(func=_cmd_normalize_board)

    normalize_injuries = normalize_subparsers.add_parser("injuries", help="Normalize an ESPN injuries snapshot")
    normalize_injuries.add_argument("--json", action="store_true", help="Render command output as JSON")
    normalize_injuries.add_argument("--snapshot", help="Payload path, manifest path, or snapshot directory")
    normalize_injuries.add_argument("--run-id", help="Override staged output run id")
    normalize_injuries.set_defaults(func=_cmd_normalize_injuries)

    normalize_statsapi = normalize_subparsers.add_parser("statsapi", help="Normalize a saved MLB StatsAPI snapshot")
    normalize_statsapi.add_argument("--json", action="store_true", help="Render command output as JSON")
    normalize_statsapi.add_argument(
        "--kind",
        choices=(
            "statsapi_teams",
            "statsapi_rosters",
            "statsapi_rosters_bulk",
            "statsapi_schedule",
            "statsapi_boxscore",
            "statsapi_boxscores_bulk",
            "statsapi_player_gamelog",
            "statsapi_player_gamelogs_bulk",
            "statsapi_transactions",
        ),
        required=True,
    )
    normalize_statsapi.add_argument("--snapshot", help="Payload path, manifest path, or snapshot directory")
    normalize_statsapi.add_argument("--run-id", help="Override staged output run id")
    normalize_statsapi.set_defaults(func=_cmd_normalize_statsapi)

    normalize_oddsapi = normalize_subparsers.add_parser("oddsapi", help="Normalize a saved OddsAPI MLB snapshot")
    normalize_oddsapi.add_argument("--json", action="store_true", help="Render command output as JSON")
    normalize_oddsapi.add_argument(
        "--source",
        choices=("oddsapi_mlb_live", "oddsapi_mlb_historical"),
        default="oddsapi_mlb_live",
    )
    normalize_oddsapi.add_argument("--snapshot", help="Payload path, manifest path, or snapshot directory")
    normalize_oddsapi.add_argument("--run-id", help="Override staged output run id")
    normalize_oddsapi.set_defaults(func=_cmd_normalize_oddsapi)

    normalize_parlayapi = normalize_subparsers.add_parser(
        "parlayapi",
        help="Normalize a saved ParlayAPI MLB historical closing-prop snapshot",
    )
    normalize_parlayapi.add_argument("--json", action="store_true", help="Render command output as JSON")
    normalize_parlayapi.add_argument("--snapshot", help="Payload path, manifest path, or snapshot directory")
    normalize_parlayapi.add_argument("--run-id", help="Override staged output run id")
    normalize_parlayapi.set_defaults(func=_cmd_normalize_parlayapi)

    normalize_draftkings_pick6 = normalize_subparsers.add_parser(
        "draftkings-pick6",
        help="Normalize a saved DraftKings Pick6 MLB snapshot",
    )
    normalize_draftkings_pick6.add_argument("--json", action="store_true", help="Render command output as JSON")
    normalize_draftkings_pick6.add_argument("--snapshot", help="Payload path, manifest path, or snapshot directory")
    normalize_draftkings_pick6.add_argument("--run-id", help="Override staged output run id")
    normalize_draftkings_pick6.set_defaults(func=_cmd_normalize_draftkings_pick6)

    normalize_bettingpros = normalize_subparsers.add_parser(
        "bettingpros",
        help="Normalize a saved BettingPros MLB props snapshot",
    )
    normalize_bettingpros.add_argument("--json", action="store_true", help="Render command output as JSON")
    normalize_bettingpros.add_argument("--snapshot", help="Payload path, manifest path, or snapshot directory")
    normalize_bettingpros.add_argument("--run-id", help="Override staged output run id")
    normalize_bettingpros.set_defaults(func=_cmd_normalize_bettingpros)

    normalize_rotowire = normalize_subparsers.add_parser("rotowire", help="Normalize a saved Rotowire MLB context snapshot")
    normalize_rotowire.add_argument("--json", action="store_true", help="Render command output as JSON")
    normalize_rotowire.add_argument("--snapshot", help="Payload path, manifest path, or snapshot directory")
    normalize_rotowire.add_argument("--run-id", help="Override staged output run id")
    normalize_rotowire.set_defaults(func=_cmd_normalize_rotowire)

    normalize_covers_weather = normalize_subparsers.add_parser(
        "covers-weather",
        help="Normalize a captured Covers MLB weather page",
    )
    normalize_covers_weather.add_argument("--json", action="store_true", help="Render command output as JSON")
    normalize_covers_weather.add_argument("--source", required=True, help="Captured Covers weather HTML/text path")
    normalize_covers_weather.add_argument("--root", help="Override repo root for test/dev execution")
    normalize_covers_weather.add_argument("--run-id", help="Override staged output run id")
    normalize_covers_weather.set_defaults(func=_cmd_normalize_covers_weather)

    normalize_espn_game_context = normalize_subparsers.add_parser(
        "espn-game-context",
        help="Normalize a saved ESPN MLB game context snapshot",
    )
    normalize_espn_game_context.add_argument("--json", action="store_true", help="Render command output as JSON")
    normalize_espn_game_context.add_argument("--snapshot", help="Payload path, manifest path, or snapshot directory")
    normalize_espn_game_context.add_argument("--run-id", help="Override staged output run id")
    normalize_espn_game_context.set_defaults(func=_cmd_normalize_espn_game_context)

    normalize_espn_gamelogs = normalize_subparsers.add_parser(
        "espn-gamelogs",
        help="Normalize saved ESPN MLB athlete game-log snapshots",
    )
    normalize_espn_gamelogs.add_argument("--json", action="store_true", help="Render command output as JSON")
    normalize_espn_gamelogs.add_argument(
        "--kind",
        choices=("espn_player_gamelog", "espn_player_gamelogs_bulk"),
        default="espn_player_gamelogs_bulk",
    )
    normalize_espn_gamelogs.add_argument("--snapshot", help="Payload path, manifest path, or snapshot directory")
    normalize_espn_gamelogs.add_argument("--run-id", help="Override staged output run id")
    normalize_espn_gamelogs.set_defaults(func=_cmd_normalize_espn_gamelogs)

    normalize_baseball_reference_boxscore = normalize_subparsers.add_parser(
        "baseball-reference-boxscore",
        help="Normalize a saved Baseball Reference boxscore starting-lineup snapshot",
    )
    normalize_baseball_reference_boxscore.add_argument("--json", action="store_true", help="Render command output as JSON")
    normalize_baseball_reference_boxscore.add_argument(
        "--snapshot",
        help="Payload path, manifest path, or snapshot directory",
    )
    normalize_baseball_reference_boxscore.add_argument("--run-id", help="Override staged output run id")
    normalize_baseball_reference_boxscore.set_defaults(func=_cmd_normalize_baseball_reference_boxscore)

    normalize_wunderground_history = normalize_subparsers.add_parser(
        "wunderground-history",
        help="Normalize a saved Wunderground historical weather snapshot",
    )
    normalize_wunderground_history.add_argument("--json", action="store_true", help="Render command output as JSON")
    normalize_wunderground_history.add_argument("--snapshot", help="Payload path, manifest path, or snapshot directory")
    normalize_wunderground_history.add_argument("--root", help="Override repo root for test/dev execution")
    normalize_wunderground_history.add_argument("--run-id", help="Override staged output run id")
    normalize_wunderground_history.set_defaults(func=_cmd_normalize_wunderground_history)

    normalize_baseball_savant = normalize_subparsers.add_parser(
        "baseball-savant",
        help="Normalize a saved Baseball Savant MLB context snapshot",
    )
    normalize_baseball_savant.add_argument("--json", action="store_true", help="Render command output as JSON")
    normalize_baseball_savant.add_argument("--snapshot", help="Payload path, manifest path, or snapshot directory")
    normalize_baseball_savant.add_argument("--run-id", help="Override staged output run id")
    normalize_baseball_savant.set_defaults(func=_cmd_normalize_baseball_savant)

    import_cmd = subparsers.add_parser("import", help="Import existing raw source files into MLB-dev snapshot storage")
    import_subparsers = import_cmd.add_subparsers(dest="import_source", required=True)

    import_legacy_pp = import_subparsers.add_parser(
        "legacy-prizepicks",
        help="Import Atlas production PrizePicks raw JSON files as isolated legacy fixtures",
    )
    import_legacy_pp.add_argument("--json", action="store_true", help="Render command output as JSON")
    import_legacy_pp.add_argument("--source-dir", required=True, help="Directory containing prizepicks_YYYYMMDD_HHMMSS.json")
    import_legacy_pp.add_argument("--start-date", required=True, help="First filename date to import, YYYY-MM-DD")
    import_legacy_pp.add_argument("--end-date", required=True, help="Last filename date to import, YYYY-MM-DD")
    import_legacy_pp.add_argument(
        "--source-name",
        default="legacy_prizepicks_nba",
        help="Raw snapshot source bucket for imported files",
    )
    import_legacy_pp.set_defaults(func=_cmd_import_legacy_prizepicks)

    import_pp_csv = import_subparsers.add_parser(
        "prizepicks-csv",
        help="Import GitHub-exported PrizePicks CSV files into normalized MLB board artifacts",
    )
    import_pp_csv.add_argument("--json", action="store_true", help="Render command output as JSON")
    import_pp_csv.add_argument("--source-dir", required=True, help="Directory containing prizepicks_*.csv files")
    import_pp_csv.add_argument("--start-date", required=True, help="First filename date to import, YYYY-MM-DD")
    import_pp_csv.add_argument("--end-date", required=True, help="Last filename date to import, YYYY-MM-DD")
    import_pp_csv.add_argument("--root", help="Override repo root for test/dev execution")
    import_pp_csv.add_argument(
        "--no-engine-input",
        action="store_true",
        help="Do not publish engine-ready board CSV/JSON after normalization",
    )
    import_pp_csv.set_defaults(func=_cmd_import_prizepicks_csv)

    backfill = subparsers.add_parser("backfill", help="Backfill paid historical source snapshots")
    backfill_subparsers = backfill.add_subparsers(dest="backfill_source", required=True)

    backfill_oddsapi = backfill_subparsers.add_parser("oddsapi", help="Backfill OddsAPI MLB historical props")
    backfill_oddsapi.add_argument("--json", action="store_true", help="Render command output as JSON")
    backfill_oddsapi.add_argument("--start-date", required=True, help="Start date, YYYY-MM-DD")
    backfill_oddsapi.add_argument("--end-date", required=True, help="End date, YYYY-MM-DD")
    backfill_oddsapi.add_argument("--snapshot-time-utc", default="18:00:00", help="Historical snapshot time")
    backfill_oddsapi.add_argument("--regions", default="us", help="Comma-separated OddsAPI regions")
    backfill_oddsapi.add_argument(
        "--bookmakers",
        default="default",
        help="Comma-separated bookmaker keys, 'default' for PrizePicks/DraftKings/FanDuel, or 'all'",
    )
    backfill_oddsapi.add_argument("--markets", default="default", help="Comma-separated market keys or 'default'")
    backfill_oddsapi.add_argument("--assumed-games-per-day", type=int, default=15)
    backfill_oddsapi.add_argument("--dry-run", action="store_true", help="Estimate cost without fetching")
    backfill_oddsapi.add_argument("--force", action="store_true", help="Fetch dates even when a snapshot exists")
    backfill_oddsapi.set_defaults(func=_cmd_backfill_oddsapi)

    backfill_parlayapi = backfill_subparsers.add_parser(
        "parlayapi",
        help="Backfill ParlayAPI MLB historical closing props",
    )
    backfill_parlayapi.add_argument("--json", action="store_true", help="Render command output as JSON")
    backfill_parlayapi.add_argument("--start-date", required=True, help="Start date, YYYY-MM-DD")
    backfill_parlayapi.add_argument("--end-date", required=True, help="End date, YYYY-MM-DD")
    backfill_parlayapi.add_argument("--snapshot-time-utc", default="18:00:00", help="Historical snapshot time")
    backfill_parlayapi.add_argument(
        "--bookmakers",
        default="",
        help="Optional comma-separated ParlayAPI bookmaker filter; blank means provider default",
    )
    backfill_parlayapi.add_argument(
        "--markets",
        default="default",
        help="Comma-separated ParlayAPI or Atlas market keys, or 'default'",
    )
    backfill_parlayapi.add_argument("--dry-run", action="store_true", help="Estimate cost without fetching")
    backfill_parlayapi.add_argument("--force", action="store_true", help="Fetch dates even when a snapshot exists")
    backfill_parlayapi.set_defaults(func=_cmd_backfill_parlayapi)

    backfill_bettingpros = backfill_subparsers.add_parser(
        "bettingpros",
        help="Backfill BettingPros MLB player-prop consensus and optional offer snapshots",
    )
    backfill_bettingpros.add_argument("--json", action="store_true", help="Render command output as JSON")
    backfill_bettingpros.add_argument("--start-date", required=True, help="Start date, YYYY-MM-DD")
    backfill_bettingpros.add_argument("--end-date", required=True, help="End date, YYYY-MM-DD")
    backfill_bettingpros.add_argument(
        "--include-offers",
        action="store_true",
        help="Also fetch full sportsbook offer pages for each date",
    )
    backfill_bettingpros.add_argument(
        "--markets",
        default="default",
        help="Comma-separated BettingPros market IDs or Atlas market keys, or 'default'",
    )
    backfill_bettingpros.add_argument(
        "--book-ids",
        default="",
        help="Optional comma-separated BettingPros book IDs, 'major', or blank for all available offer books",
    )
    backfill_bettingpros.add_argument(
        "--max-offer-pages",
        type=int,
        default=0,
        help="Optional cap for offer pages per date; 0 means all available offer pages",
    )
    backfill_bettingpros.add_argument(
        "--offer-workers",
        type=int,
        default=4,
        help="Parallel offer page workers when --include-offers is used",
    )
    backfill_bettingpros.add_argument("--no-normalize", action="store_true", help="Only write raw snapshots")
    backfill_bettingpros.add_argument("--dry-run", action="store_true", help="Plan without fetching")
    backfill_bettingpros.add_argument("--force", action="store_true", help="Fetch dates even when staged rows exist")
    backfill_bettingpros.set_defaults(func=_cmd_backfill_bettingpros)

    backfill_baseball_savant = backfill_subparsers.add_parser(
        "baseball-savant",
        help="Backfill date-safe season-to-date Baseball Savant advanced profile snapshots",
    )
    backfill_baseball_savant.add_argument("--json", action="store_true", help="Render command output as JSON")
    backfill_baseball_savant.add_argument("--start-date", required=True, help="Start date, YYYY-MM-DD")
    backfill_baseball_savant.add_argument("--end-date", required=True, help="End date, YYYY-MM-DD")
    backfill_baseball_savant.add_argument("--season", type=int, default=2026)
    backfill_baseball_savant.add_argument(
        "--pages",
        default="statcast_search_batter,statcast_search_pitcher",
        help="Comma-separated Baseball Savant page keys to fetch for each as-of date",
    )
    backfill_baseball_savant.add_argument("--root", help="Override repo root for test/dev execution")
    backfill_baseball_savant.add_argument("--dry-run", action="store_true", help="Plan without fetching")
    backfill_baseball_savant.add_argument("--force", action="store_true", help="Fetch dates even when staged rows exist")
    backfill_baseball_savant.set_defaults(func=_cmd_backfill_baseball_savant)

    backfill_cbs_injuries = backfill_subparsers.add_parser(
        "cbs-injuries",
        help="Parse a copied CBS MLB injury report text file into date-safe staged injury snapshots",
    )
    backfill_cbs_injuries.add_argument("--json", action="store_true", help="Render command output as JSON")
    backfill_cbs_injuries.add_argument("--source", required=True, help="Copied CBS injury report text file")
    backfill_cbs_injuries.add_argument("--start-date", help="Optional start date, YYYY-MM-DD")
    backfill_cbs_injuries.add_argument("--end-date", help="Optional end date, YYYY-MM-DD")
    backfill_cbs_injuries.add_argument("--run-id-prefix", default="cbs_injuries")
    backfill_cbs_injuries.add_argument("--root", help="Override repo root for test/dev execution")
    backfill_cbs_injuries.set_defaults(func=_cmd_backfill_cbs_injuries)

    prepare = subparsers.add_parser("prepare", help="Prepare internal engine-read artifacts")
    prepare_subparsers = prepare.add_subparsers(dest="prepare_target", required=True)

    prepare_engine_board = prepare_subparsers.add_parser(
        "engine-board",
        help="Publish CSV/JSON engine board inputs from a normalized PrizePicks board",
    )
    prepare_engine_board.add_argument("--json", action="store_true", help="Render command output as JSON")
    prepare_engine_board.add_argument("--normalized-dir", help="Normalized board directory; defaults to latest")
    prepare_engine_board.add_argument("--root", help="Override repo root for test/dev execution")
    prepare_engine_board.add_argument("--run-id", help="Override engine board output run id")
    prepare_engine_board.add_argument(
        "--date",
        help="Only publish props for this YYYY-MM-DD game date; defaults to snapshot-local date",
    )
    prepare_engine_board.add_argument(
        "--all-dates",
        action="store_true",
        help="Keep all dates from the normalized board; replay/debug only",
    )
    prepare_engine_board.set_defaults(func=_cmd_prepare_engine_board)

    prepare_matchups = prepare_subparsers.add_parser(
        "matchups",
        help="Build hitter matchup context artifacts from an engine board",
    )
    prepare_matchups.add_argument("--json", action="store_true", help="Render command output as JSON")
    prepare_matchups.add_argument("--engine-board", help="Engine board JSON; defaults to latest")
    prepare_matchups.add_argument("--root", help="Override repo root for test/dev execution")
    prepare_matchups.add_argument("--run-id", help="Override matchup artifact run id")
    prepare_matchups.add_argument("--date", help="Only build rows for this game date, YYYY-MM-DD")
    prepare_matchups.add_argument(
        "--directions",
        default="over,under",
        help="Comma-separated directions to emit; default over,under",
    )
    prepare_matchups.set_defaults(func=_cmd_prepare_matchups)

    prepare_season_gamelogs = prepare_subparsers.add_parser(
        "season-gamelogs",
        help="Refresh the running MLB season gamelog file from staged postgame sources",
    )
    prepare_season_gamelogs.add_argument("--json", action="store_true", help="Render command output as JSON")
    prepare_season_gamelogs.add_argument("--season", type=int, default=2026)
    prepare_season_gamelogs.add_argument(
        "--through-date",
        help="Optional latest game date to include, YYYY-MM-DD. Use for prior-day locked rebuilds.",
    )
    prepare_season_gamelogs.add_argument("--root", help="Override repo root for test/dev execution")
    prepare_season_gamelogs.set_defaults(func=_cmd_prepare_season_gamelogs)

    prepare_market_context = prepare_subparsers.add_parser(
        "market-context",
        help="Build external market context artifacts from an engine board and normalized OddsAPI snapshots",
    )
    prepare_market_context.add_argument("--json", action="store_true", help="Render command output as JSON")
    prepare_market_context.add_argument("--engine-board", help="Engine board JSON; defaults to latest")
    prepare_market_context.add_argument("--root", help="Override repo root for test/dev execution")
    prepare_market_context.add_argument("--run-id", help="Override market context artifact run id")
    prepare_market_context.add_argument("--date", help="Only build rows for this game date, YYYY-MM-DD")
    prepare_market_context.set_defaults(func=_cmd_prepare_market_context)

    prepare_injury_context = prepare_subparsers.add_parser(
        "injury-context",
        help="Build injury context artifacts from an engine board and normalized ESPN injury snapshot",
    )
    prepare_injury_context.add_argument("--json", action="store_true", help="Render command output as JSON")
    prepare_injury_context.add_argument("--engine-board", help="Engine board JSON; defaults to latest")
    prepare_injury_context.add_argument("--root", help="Override repo root for test/dev execution")
    prepare_injury_context.add_argument("--run-id", help="Override injury context artifact run id")
    prepare_injury_context.add_argument("--date", help="Only build rows for this game date, YYYY-MM-DD")
    prepare_injury_context.set_defaults(func=_cmd_prepare_injury_context)

    prepare_statsapi_context = prepare_subparsers.add_parser(
        "statsapi-context",
        help="Build StatsAPI schedule/team context artifacts from an engine board",
    )
    prepare_statsapi_context.add_argument("--json", action="store_true", help="Render command output as JSON")
    prepare_statsapi_context.add_argument("--engine-board", help="Engine board JSON; defaults to latest")
    prepare_statsapi_context.add_argument("--root", help="Override repo root for test/dev execution")
    prepare_statsapi_context.add_argument("--run-id", help="Override StatsAPI context artifact run id")
    prepare_statsapi_context.add_argument("--date", help="Only build rows for this game date, YYYY-MM-DD")
    prepare_statsapi_context.set_defaults(func=_cmd_prepare_statsapi_context)

    prepare_roster_context = prepare_subparsers.add_parser(
        "roster-context",
        help="Build StatsAPI roster identity context artifacts from an engine board",
    )
    prepare_roster_context.add_argument("--json", action="store_true", help="Render command output as JSON")
    prepare_roster_context.add_argument("--engine-board", help="Engine board JSON; defaults to latest")
    prepare_roster_context.add_argument("--statsapi-context", help="StatsAPI context JSON; helps exact team-id joins")
    prepare_roster_context.add_argument("--root", help="Override repo root for test/dev execution")
    prepare_roster_context.add_argument("--run-id", help="Override roster context artifact run id")
    prepare_roster_context.add_argument("--date", help="Only build rows for this game date, YYYY-MM-DD")
    prepare_roster_context.set_defaults(func=_cmd_prepare_roster_context)

    prepare_player_history_context = prepare_subparsers.add_parser(
        "player-history-context",
        help="Build StatsAPI game-log history and PA projection context artifacts",
    )
    prepare_player_history_context.add_argument("--json", action="store_true", help="Render command output as JSON")
    prepare_player_history_context.add_argument("--engine-board", help="Engine board JSON; defaults to latest")
    prepare_player_history_context.add_argument("--roster-context", help="Roster context JSON; helps exact person-id joins")
    prepare_player_history_context.add_argument("--root", help="Override repo root for test/dev execution")
    prepare_player_history_context.add_argument("--run-id", help="Override player-history context artifact run id")
    prepare_player_history_context.add_argument("--date", help="Only build rows for this game date, YYYY-MM-DD")
    prepare_player_history_context.set_defaults(func=_cmd_prepare_player_history_context)

    prepare_transaction_context = prepare_subparsers.add_parser(
        "transaction-context",
        help="Build StatsAPI transaction/call-up context artifacts from an engine board",
    )
    prepare_transaction_context.add_argument("--json", action="store_true", help="Render command output as JSON")
    prepare_transaction_context.add_argument("--engine-board", help="Engine board JSON; defaults to latest")
    prepare_transaction_context.add_argument("--roster-context", help="Roster context JSON; helps exact person-id joins")
    prepare_transaction_context.add_argument("--root", help="Override repo root for test/dev execution")
    prepare_transaction_context.add_argument("--run-id", help="Override transaction context artifact run id")
    prepare_transaction_context.add_argument("--date", help="Only build rows for this game date, YYYY-MM-DD")
    prepare_transaction_context.add_argument("--lookback-days", type=int, default=14)
    prepare_transaction_context.set_defaults(func=_cmd_prepare_transaction_context)

    prepare_umpires = prepare_subparsers.add_parser(
        "umpires",
        help="Normalize a captured umpire table into staged umpire profile artifacts",
    )
    prepare_umpires.add_argument("--json", action="store_true", help="Render command output as JSON")
    prepare_umpires.add_argument("--source", required=True, help="Captured umpire JSON table path")
    prepare_umpires.add_argument("--root", help="Override repo root for test/dev execution")
    prepare_umpires.add_argument("--run-id", help="Override umpire artifact run id")
    prepare_umpires.set_defaults(func=_cmd_prepare_umpires)

    prepare_ballparks = prepare_subparsers.add_parser(
        "ballparks",
        help="Normalize captured Baseball Savant ballpark factors into staged artifacts",
    )
    prepare_ballparks.add_argument("--json", action="store_true", help="Render command output as JSON")
    prepare_ballparks.add_argument("--source", required=True, help="Captured ballpark factor CSV/JSON path")
    prepare_ballparks.add_argument("--root", help="Override repo root for test/dev execution")
    prepare_ballparks.add_argument("--run-id", help="Override ballpark artifact run id")
    prepare_ballparks.set_defaults(func=_cmd_prepare_ballparks)

    prepare_wind_factors = prepare_subparsers.add_parser(
        "wind-factors",
        help="Normalize MLB stadium wind-factor workbook into staged artifacts",
    )
    prepare_wind_factors.add_argument("--json", action="store_true", help="Render command output as JSON")
    prepare_wind_factors.add_argument("--source", required=True, help="Wind-factor workbook path")
    prepare_wind_factors.add_argument("--root", help="Override repo root for test/dev execution")
    prepare_wind_factors.add_argument("--run-id", help="Override wind-factor artifact run id")
    prepare_wind_factors.set_defaults(func=_cmd_prepare_wind_factors)

    prepare_advanced_profiles = prepare_subparsers.add_parser(
        "advanced-profiles",
        help="Normalize captured advanced player profile CSV/JSON into staged artifacts",
    )
    prepare_advanced_profiles.add_argument("--json", action="store_true", help="Render command output as JSON")
    prepare_advanced_profiles.add_argument("--source", required=True, help="Captured advanced player profile CSV/JSON path")
    prepare_advanced_profiles.add_argument("--root", help="Override repo root for test/dev execution")
    prepare_advanced_profiles.add_argument("--run-id", help="Override advanced profile artifact run id")
    prepare_advanced_profiles.set_defaults(func=_cmd_prepare_advanced_profiles)

    prepare_advanced_context = prepare_subparsers.add_parser(
        "advanced-context",
        help="Build advanced player profile context artifacts for an engine board",
    )
    prepare_advanced_context.add_argument("--json", action="store_true", help="Render command output as JSON")
    prepare_advanced_context.add_argument("--engine-board", help="Engine board JSON; defaults to latest")
    prepare_advanced_context.add_argument("--source", help="Raw profile CSV/JSON to stage before context build")
    prepare_advanced_context.add_argument("--profiles", help="Staged advanced_profiles JSON; defaults to latest")
    prepare_advanced_context.add_argument("--root", help="Override repo root for test/dev execution")
    prepare_advanced_context.add_argument("--run-id", help="Override advanced context artifact run id")
    prepare_advanced_context.add_argument("--date", help="Only build rows for this game date, YYYY-MM-DD")
    prepare_advanced_context.set_defaults(func=_cmd_prepare_advanced_context)

    score = subparsers.add_parser("score", help="Score prepared MLB engine artifacts")
    score_subparsers = score.add_subparsers(dest="score_target", required=True)

    score_board = score_subparsers.add_parser(
        "board",
        help="Score an engine-board JSON artifact into scored legs",
    )
    score_board.add_argument("--json", action="store_true", help="Render command output as JSON")
    score_board.add_argument("--engine-board", help="Engine board JSON, manifest, or directory; defaults to latest")
    score_board.add_argument("--parameter-table", help="Parameter table JSON to lock scoring to generated parameters")
    score_board.add_argument("--feature-table", help="Feature table JSON/CSV carrying replay-safe context diagnostics")
    score_board.add_argument("--run-id", help="Override scored run id")
    score_board.set_defaults(func=_cmd_score_board)

    run = subparsers.add_parser("run", help="Execute internal MLB pipeline stages")
    run_subparsers = run.add_subparsers(dest="run_target", required=True)

    run_board = run_subparsers.add_parser(
        "board",
        help="Normalize a PrizePicks snapshot, publish engine inputs, run QMC scoring, build slips, and write operator artifacts",
    )
    run_board.add_argument("--json", action="store_true", help="Render command output as JSON")
    run_board.add_argument("--snapshot", help="Payload path, manifest path, or snapshot directory; defaults to latest")
    run_board.add_argument(
        "--normalized-dir",
        help="Use an existing normalized PrizePicks board directory instead of normalizing a raw snapshot",
    )
    run_board.add_argument("--root", help="Override repo root for test/dev execution")
    run_board.add_argument("--run-id", help="Override run id")
    run_board.add_argument(
        "--run-mode",
        choices=("live", "replay", "replay_single", "replay_corpus", "replay_bundle"),
        default="replay_single",
        help="'replay' is kept as a compatibility alias for replay_single; replay_bundle maps to replay_corpus",
    )
    run_board.add_argument(
        "--date",
        help="Only run props for this YYYY-MM-DD game date; defaults to snapshot-local date",
    )
    run_board.add_argument(
        "--all-dates",
        action="store_true",
        help="Keep all dates from the board; replay/debug only",
    )
    run_board.add_argument(
        "--refresh-context-sources",
        action="store_true",
        help="Fetch and normalize Rotowire/Baseball Savant context before building matchup artifacts",
    )
    run_board.add_argument(
        "--rotowire-pages",
        default="default",
        help="Rotowire pages for --refresh-context-sources; use 'default' for live context",
    )
    run_board.add_argument(
        "--baseball-savant-pages",
        default="default",
        help="Baseball Savant pages for --refresh-context-sources; use 'default' for Statcast/park context",
    )
    run_board.add_argument("--baseball-savant-season", type=int, default=2026)
    run_board.add_argument(
        "--no-bettingpros-odds-refresh",
        action="store_true",
        help="Do not auto-fetch/stage BettingPros odds before market context",
    )
    run_board.add_argument(
        "--calibration-artifact",
        help="Optional calibration metadata JSON; writes a calibrated parameter table before scoring",
    )
    run_board.set_defaults(func=_cmd_run_board)

    audit = subparsers.add_parser("audit", help="Audit completed MLB run artifacts")
    audit_subparsers = audit.add_subparsers(dest="audit_target", required=True)

    audit_context = audit_subparsers.add_parser(
        "context",
        help="Audit context coverage feeding a completed MLB probability run",
    )
    audit_context.add_argument("--json", action="store_true", help="Render command output as JSON")
    audit_context.add_argument("--run-id", help="Run id under data/mlb/test_runs or data/mlb/live_runs; defaults to latest run manifest")
    audit_context.add_argument("--root", help="Override repo root for test/dev execution")
    audit_context.add_argument("--no-write", action="store_true", help="Do not write audit artifacts")
    audit_context.set_defaults(func=_cmd_audit_context)

    audit_eval = audit_subparsers.add_parser(
        "eval",
        help="Settle a scored replay run from StatsAPI boxscores and write Brier/logloss diagnostics",
    )
    audit_eval.add_argument("--json", action="store_true", help="Render command output as JSON")
    audit_eval.add_argument("--run-id", help="Run id under data/mlb/test_runs or data/mlb/live_runs; defaults to latest scored legs")
    audit_eval.add_argument("--scored-legs", help="Path to scored_legs.json or a run directory")
    audit_eval.add_argument("--root", help="Override repo root for test/dev execution")
    audit_eval.set_defaults(func=_cmd_audit_eval)

    pipeline = subparsers.add_parser("pipeline", help="List MLB development pipeline stages")
    pipeline.add_argument("--json", action="store_true", help="Render command output as JSON")
    pipeline.set_defaults(func=_cmd_inspection, inspection_command="pipeline")

    bundles = subparsers.add_parser("bundles", help="List expected MLB run bundle artifacts")
    bundles.add_argument("--json", action="store_true", help="Render command output as JSON")
    bundles.set_defaults(func=_cmd_inspection, inspection_command="bundles")

    operator = subparsers.add_parser("operator", help="Show AI/operator evaluation plan and guardrails")
    operator.add_argument("--json", action="store_true", help="Render command output as JSON")
    operator.set_defaults(func=_cmd_inspection, inspection_command="operator")

    publishing = subparsers.add_parser("publishing", help="Show MLB-dev publishing guardrails")
    publishing.add_argument("--json", action="store_true", help="Render command output as JSON")
    publishing.set_defaults(func=_cmd_inspection, inspection_command="publishing")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        args = parser.parse_args(["doctor"])
    if getattr(args, "text", False):
        args.json = False
    return int(args.func(args))


def _parse_sport_ids(value: str) -> tuple[int, ...]:
    return tuple(int(part.strip()) for part in value.split(",") if part.strip())


def _parse_ints(value: str) -> tuple[int, ...]:
    return tuple(int(part.strip()) for part in str(value or "").split(",") if part.strip())


def _parse_strings(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value or "").split(",") if part.strip())


def _parse_time(value: str) -> time:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        return time(parts[0], parts[1])
    if len(parts) == 3:
        return time(parts[0], parts[1], parts[2])
    raise ValueError("time must be HH:MM or HH:MM:SS")


def _parse_directions(value: str) -> tuple[str, ...]:
    directions = tuple(part.strip().lower() for part in value.split(",") if part.strip())
    invalid = [direction for direction in directions if direction not in {"over", "under"}]
    if invalid:
        raise ValueError(f"unsupported direction(s): {', '.join(invalid)}")
    return directions or ("over", "under")


if __name__ == "__main__":
    raise SystemExit(main())
