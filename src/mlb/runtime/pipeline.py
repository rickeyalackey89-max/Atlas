"""Pipeline stage definitions for Atlas MLB.

This module is intentionally declarative. Runtime execution, preflight checks,
publishing controls, and bundle planning live under ``mlb.runtime``.
"""

LIVE_PIPELINE_STAGES = (
    "fetch_prizepicks_raw_snapshots",
    "normalize_prizepicks_board",
    "write_engine_board_inputs",
    "fetch_espn_injuries",
    "fetch_rotowire_context",
    "fetch_baseball_savant_context",
    "fetch_mlb_gamelogs",
    "fetch_minor_league_context",
    "fetch_statsapi_transactions",
    "fetch_statsapi_boxscore_history",
    "normalize_context_sources",
    "build_player_history_context",
    "build_transaction_context",
    "build_matchup_context_matrices",
    "build_share_matrix",
    "build_game_environment_features",
    "build_parameter_models",
    "run_sobol_qmc_simulation",
    "extract_market_probabilities",
    "calibrate_market_probabilities",
    "build_slip_families",
    "run_deterministic_anomaly_checks",
    "run_openai_operator_evaluation",
    "write_operator_report",
    "write_publish_decision",
    "write_live_run_manifest",
    "write_live_run_outputs",
    "publish_dashboard_payload",
)

SINGLE_REPLAY_PIPELINE_STAGES = (
    "load_replay_snapshot",
    "load_source_manifest",
    "normalize_prizepicks_board",
    "write_engine_board_inputs",
    "normalize_replay_context_sources",
    "build_share_matrix",
    "settle_replay_outcomes",
    "build_game_environment_features",
    "build_parameter_models",
    "run_sobol_qmc_simulation",
    "extract_market_probabilities",
    "calibrate_market_probabilities",
    "build_slip_families",
    "run_deterministic_anomaly_checks",
    "run_openai_operator_evaluation",
    "write_operator_report",
    "write_replay_manifest",
)

BUNDLE_REPLAY_PIPELINE_STAGES = (
    "load_bundle_manifest",
    "validate_bundle_members",
    "run_single_replays",
    "aggregate_replay_results",
    "run_bundle_anomaly_checks",
    "run_openai_bundle_evaluation",
    "write_bundle_operator_report",
    "write_corpus_cache",
    "write_loso_training_manifest",
    "write_bundle_eval_report",
)

CORPUS_REPLAY_PIPELINE_STAGES = BUNDLE_REPLAY_PIPELINE_STAGES

MLB_PIPELINE_STAGES = LIVE_PIPELINE_STAGES
