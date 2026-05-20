from pathlib import Path

import pytest

from mlb.cli import main
from mlb.normalizers.prizepicks import write_prizepicks_board_normalization
from mlb.runtime.live_execution import run_live_model_result
from mlb.runtime.pipeline_execution import (
    _draftkings_timing_policy,
    _live_market_source_dirs,
    _market_source_dirs_for_run,
    run_board_pipeline,
)
from mlb.runtime.results import RuntimeCommandResult
from mlb.sources.snapshots import write_raw_snapshot


@pytest.fixture(autouse=True)
def _stub_primary_market_source(monkeypatch):
    def fake_primary_market_source(**kwargs):
        return {
            "enabled": kwargs.get("enabled", True),
            "source": "bettingpros_mlb_props",
            "game_date": kwargs.get("game_date", ""),
            "run_mode": kwargs.get("run_mode", ""),
            "status": "existing" if kwargs.get("enabled", True) else "disabled",
            "snapshot_id": "",
            "payload_path": "",
            "normalized_output_dir": "",
            "row_count": 0,
            "rejected_count": 0,
            "errors": [],
        }

    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution._ensure_primary_market_source",
        fake_primary_market_source,
    )


def test_board_pipeline_writes_qmc_runtime_artifacts(tmp_path):
    snapshot = write_raw_snapshot(source="prizepicks", payload=_sample_prizepicks_payload(), request={}, root=tmp_path)

    manifest = run_board_pipeline(
        snapshot_path=Path(snapshot.path),
        root=tmp_path,
        run_id="pipeline_run",
        game_date="2026-05-11",
    )

    run_dir = tmp_path / "data" / "mlb" / "test_runs" / "pipeline_run"
    assert manifest["run_id"] == "pipeline_run"
    assert manifest["run_mode"] == "replay_single"
    assert manifest["fidelity_policy"]["strict_replay_fidelity"] is True
    assert manifest["fidelity_policy"]["post_date_context_allowed"] is False
    assert manifest["mlb_config"]["schema_version"] == "atlas_mlb_operational_config_v1"
    assert manifest["features"]["row_count"] == 2
    assert manifest["source_selection"]["source_selection_version"] == "mlb_replay_live_source_contract_v1"
    assert (run_dir / "source_selection_manifest.json").exists()
    assert manifest["features"]["feature_model_version"] == "baseline_player_prop_features_v1_market_source_type"
    assert manifest["matchups"]["game_date"] == "2026-05-11"
    assert manifest["market_context"]["game_date"] == "2026-05-11"
    assert manifest["injury_context"]["row_count"] == 2
    assert manifest["injury_context"]["game_date"] == "2026-05-11"
    assert manifest["injury_context"]["json_path"] == manifest["features"]["injury_context_path"]
    assert manifest["statsapi_context"]["row_count"] == 2
    assert manifest["statsapi_context"]["game_date"] == "2026-05-11"
    assert manifest["statsapi_context"]["json_path"] == manifest["features"]["statsapi_context_path"]
    assert manifest["roster_context"]["row_count"] == 2
    assert manifest["roster_context"]["game_date"] == "2026-05-11"
    assert manifest["roster_context"]["json_path"] == manifest["features"]["roster_context_path"]
    assert manifest["advanced_context"]["game_date"] == "2026-05-11"
    assert manifest["parameters"]["row_count"] == 2
    assert manifest["parameters"]["opportunity_model_versions"] == {"baseline_opportunity_v0": 2}
    assert manifest["score"]["row_count"] == 2
    assert manifest["score"]["parameter_row_match_count"] == 2
    assert manifest["score"]["parameter_row_missing_count"] == 0
    assert manifest["score"]["parameter_table_path"] == manifest["parameters"]["json_path"]
    assert manifest["slips"]["family_count"] > 0
    assert manifest["eval"]["slip_eval"]["slip_eval_path"].endswith("slip_eval.json")
    assert (run_dir / "simulation_manifest.json").exists()
    assert (run_dir / "System" / "recommended_2leg.csv").exists()
    assert (run_dir / "Windfall" / "recommended_2leg.csv").exists()
    assert (run_dir / "marketed_slips.csv").exists()
    assert (tmp_path / "data" / "mlb" / "eval" / "pipeline_run" / "eval_legs.csv").exists()
    assert (tmp_path / "data" / "mlb" / "eval" / "pipeline_run" / "eval_slips.csv").exists()
    assert (tmp_path / "data" / "mlb" / "eval" / "pipeline_run" / "slip_eval.json").exists()
    assert (run_dir / "operator" / "operator_input.json").exists()
    assert (run_dir / "operator" / "ai_evaluation.json").exists()
    assert (run_dir / "operator" / "publish_decision.json").exists()
    assert (run_dir / "run_manifest.json").exists()


def test_cli_run_board_pipeline_delegates_to_runtime(tmp_path, capsys):
    snapshot = write_raw_snapshot(source="prizepicks", payload=_sample_prizepicks_payload(), request={}, root=tmp_path)

    exit_code = main(
        [
            "run",
            "board",
            "--snapshot",
            snapshot.path,
            "--root",
            str(tmp_path),
            "--run-id",
            "cli_pipeline_run",
            "--date",
            "2026-05-11",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Executed MLB board pipeline:" in captured.out
    assert (tmp_path / "data" / "mlb" / "test_runs" / "cli_pipeline_run" / "run_manifest.json").exists()


def test_cli_live_runs_live_model(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_live_model_result(**kwargs):
        calls.append(kwargs)
        return RuntimeCommandResult(
            name="live_model",
            payload={"run_id": "live_cli_run"},
            lines=("Executed Atlas MLB live model:", "  run_id: live_cli_run"),
        )

    monkeypatch.setattr("mlb.cli.run_live_model_result", fake_live_model_result)

    exit_code = main(
        [
            "live",
            "--root",
            str(tmp_path),
            "--run-id",
            "live_cli_run",
            "--date",
            "2026-05-19",
            "--state-code",
            "MO",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Executed Atlas MLB live model:" in captured.out
    assert calls[0]["root"] == tmp_path
    assert calls[0]["run_id"] == "live_cli_run"
    assert calls[0]["game_date"] == "2026-05-19"
    assert calls[0]["state_code"] == "MO"
    assert calls[0]["snapshot_path"] is None
    assert calls[0]["normalized_dir"] is None


def test_live_model_applies_configured_calibration_by_default(monkeypatch, tmp_path):
    calls = []

    def fake_config_manifest(root):
        assert root == tmp_path
        return {
            "config_version": "mlb_test_config",
            "active_probability_kernel": "qmc",
            "active_calibration_version": "mlb_cat_test_v1",
            "active_calibration_artifact": "data/mlb/model/cat_test.json",
            "active_market_source": "bettingpros_mlb_props",
            "active_slip_builder_version": "slip_test",
        }

    def fake_pipeline_result(**kwargs):
        calls.append(kwargs)
        return RuntimeCommandResult(
            name="run_board_pipeline",
            payload={
                "run_id": kwargs["run_id"],
                "run_mode": "live",
                "game_date_filter": "2026-05-19",
                "engine_board": {
                    "row_count": 1,
                    "dropped_by_date_filter_count": 0,
                    "dropped_started_or_live_count": 0,
                },
                "features": {"source_completeness": {}},
                "context_source_refresh": {"enabled": True, "errors": []},
                "primary_market_source": {"status": "existing", "row_count": 0, "snapshot_id": ""},
                "score": {"row_count": 1},
                "slips": {
                    "slip_count": 0,
                    "payout_quote_manifest": {
                        "exact_quote_count": 0,
                        "quote_count": 0,
                    },
                },
                "operator": {
                    "severity": "none",
                    "publish_allowed": True,
                    "anomaly_count": 0,
                },
                "manifest_path": str(tmp_path / "run_manifest.json"),
            },
            lines=(),
        )

    monkeypatch.setattr("mlb.runtime.live_execution.active_mlb_config_manifest", fake_config_manifest)
    monkeypatch.setattr("mlb.runtime.live_execution.run_board_pipeline_result", fake_pipeline_result)

    result = run_live_model_result(
        root=tmp_path,
        run_id="live_default_cat",
        normalized_dir=tmp_path / "normalized",
        emit_progress=lambda _message: None,
    )

    assert result.payload["run_id"] == "live_default_cat"
    assert calls[0]["calibration_artifact_path"] == tmp_path / "data/mlb/model/cat_test.json"
    assert calls[0]["run_mode"] == "live"


def test_board_pipeline_can_run_from_existing_normalized_dir(tmp_path):
    snapshot = write_raw_snapshot(source="prizepicks", payload=_sample_prizepicks_payload(), request={}, root=tmp_path)
    normalized = write_prizepicks_board_normalization(Path(snapshot.path), root=tmp_path)

    manifest = run_board_pipeline(
        normalized_dir=normalized.output_dir,
        root=tmp_path,
        run_id="normalized_pipeline_run",
        game_date="2026-05-11",
    )

    assert manifest["normalized_source_type"] == "normalized_dir"
    assert manifest["normalized"]["normalized_count"] == 2
    assert manifest["engine_board"]["row_count"] == 2
    assert (tmp_path / "data" / "mlb" / "test_runs" / "normalized_pipeline_run" / "run_manifest.json").exists()


def test_board_pipeline_can_refresh_context_sources(tmp_path, monkeypatch):
    snapshot = write_raw_snapshot(source="prizepicks", payload=_sample_prizepicks_payload(), request={}, root=tmp_path)

    calls = []

    def fake_rotowire_result(**kwargs):
        calls.append(("rotowire", kwargs))
        return RuntimeCommandResult(
            name="fetch_rotowire",
            payload={"source": "rotowire_mlb_context", "normalized": {"row_counts": {"pitchers": 1}}},
            lines=(),
        )

    def fake_savant_result(**kwargs):
        calls.append(("baseball_savant", kwargs))
        return RuntimeCommandResult(
            name="fetch_baseball_savant",
            payload={"source": "baseball_savant_context", "normalized": {"row_counts": {"ballparks": 1}}},
            lines=(),
        )

    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_rotowire_result",
        fake_rotowire_result,
    )
    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_baseball_savant_result",
        fake_savant_result,
    )
    manifest = run_board_pipeline(
        snapshot_path=Path(snapshot.path),
        root=tmp_path,
        run_id="refresh_context_run",
        game_date="2026-05-11",
        refresh_context_sources=True,
        rotowire_pages="daily_lineups,projected_starters",
        baseball_savant_pages="park_factors",
    )

    assert manifest["context_source_refresh"]["enabled"] is True
    assert manifest["primary_market_source"]["source"] == "bettingpros_mlb_props"
    assert manifest["context_source_refresh"]["espn_backfill_enabled"] is False
    assert manifest["context_source_refresh"]["espn_game_context"] is None
    assert manifest["context_source_refresh"]["errors"] == []
    assert calls[0][0] == "rotowire"
    assert calls[0][1]["game_date"] == "2026-05-11"
    assert calls[0][1]["pages"] == "daily_lineups,projected_starters"
    assert calls[1][0] == "baseball_savant"
    assert calls[1][1]["pages"] == "park_factors"
    assert [call[0] for call in calls] == ["rotowire", "baseball_savant"]


def test_board_pipeline_rejects_postgame_backfill_for_fidelity(tmp_path):
    snapshot = write_raw_snapshot(source="prizepicks", payload=_sample_prizepicks_payload(), request={}, root=tmp_path)

    try:
        run_board_pipeline(
            snapshot_path=Path(snapshot.path),
            root=tmp_path,
            run_id="postgame_backfill_run",
            game_date="2026-05-11",
            include_espn_backfill=True,
        )
    except ValueError as exc:
        assert "postgame backfill" in str(exc)
    else:  # pragma: no cover - failure branch
        raise AssertionError("Expected postgame backfill to be rejected")


def test_live_context_refresh_does_not_fetch_espn_postgame_context(tmp_path, monkeypatch):
    snapshot = write_raw_snapshot(source="prizepicks", payload=_sample_prizepicks_payload(), request={}, root=tmp_path)

    calls = []

    def fake_rotowire_result(**kwargs):
        calls.append(("rotowire", kwargs))
        return RuntimeCommandResult(name="fetch_rotowire", payload={"source": "rotowire"}, lines=())

    def fake_savant_result(**kwargs):
        calls.append(("baseball_savant", kwargs))
        return RuntimeCommandResult(name="fetch_baseball_savant", payload={"source": "baseball_savant"}, lines=())

    def fake_espn_result(**kwargs):
        calls.append(("espn_game_context", kwargs))
        return RuntimeCommandResult(name="fetch_espn_game_context", payload={"source": "espn_game_context"}, lines=())

    def fake_injuries_result(**kwargs):
        calls.append(("injuries", kwargs))
        return RuntimeCommandResult(name="fetch_injuries", payload={"source": "espn_injuries"}, lines=())

    def fake_statsapi_teams_result(**kwargs):
        calls.append(("statsapi_teams", kwargs))
        return RuntimeCommandResult(name="fetch_statsapi_teams", payload={"source": "statsapi_teams"}, lines=())

    def fake_statsapi_schedule_result(**kwargs):
        calls.append(("statsapi_schedule", kwargs))
        return RuntimeCommandResult(name="fetch_statsapi_schedule", payload={"source": "statsapi_schedule"}, lines=())

    def fake_statsapi_rosters_bulk_result(**kwargs):
        calls.append(("statsapi_rosters_bulk", kwargs))
        return RuntimeCommandResult(
            name="fetch_statsapi_rosters_bulk",
            payload={"source": "statsapi_rosters_bulk"},
            lines=(),
        )

    def fake_statsapi_transactions_result(**kwargs):
        calls.append(("statsapi_transactions", kwargs))
        return RuntimeCommandResult(
            name="fetch_statsapi_transactions",
            payload={"source": "statsapi_transactions"},
            lines=(),
        )

    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_rotowire_result",
        fake_rotowire_result,
    )
    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_baseball_savant_result",
        fake_savant_result,
    )
    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_espn_game_context_result",
        fake_espn_result,
    )
    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_injuries_result",
        fake_injuries_result,
    )
    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_statsapi_teams_result",
        fake_statsapi_teams_result,
    )
    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_statsapi_schedule_result",
        fake_statsapi_schedule_result,
    )
    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_statsapi_rosters_bulk_result",
        fake_statsapi_rosters_bulk_result,
    )
    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_statsapi_transactions_result",
        fake_statsapi_transactions_result,
    )

    manifest = run_board_pipeline(
        snapshot_path=Path(snapshot.path),
        root=tmp_path,
        run_id="live_refresh_context_run",
        run_mode="live",
        game_date="2026-05-11",
        refresh_context_sources=True,
    )

    assert manifest["context_source_refresh"]["enabled"] is True
    assert manifest["context_source_refresh"]["espn_backfill_enabled"] is False
    assert manifest["context_source_refresh"]["live_identity_sources_enabled"] is True
    assert [call[0] for call in calls] == [
        "rotowire",
        "baseball_savant",
        "injuries",
        "statsapi_teams",
        "statsapi_schedule",
        "statsapi_rosters_bulk",
        "statsapi_transactions",
    ]


def test_live_market_source_dirs_use_current_primary_source():
    dirs = _live_market_source_dirs(
        primary_market_source={"normalized_output_dir": r"C:\tmp\fresh_bettingpros"},
        run_mode="live",
    )

    assert dirs == [Path(r"C:\tmp\fresh_bettingpros")]
    assert _live_market_source_dirs(
        primary_market_source={"normalized_output_dir": r"C:\tmp\fresh_bettingpros"},
        run_mode="replay_single",
    ) is None


def test_replay_market_source_dirs_explicitly_include_date_safe_sources(tmp_path):
    oddsapi_dir = tmp_path / "data" / "mlb" / "staged" / "oddsapi" / "bettingpros_20990511"
    oddsapi_dir.mkdir(parents=True)
    (oddsapi_dir / "oddsapi_props.jsonl").write_text(
        '{"source":"bettingpros_mlb_props","game_date":"2099-05-11"}\n',
        encoding="utf-8",
    )
    (oddsapi_dir / "normalize_manifest.json").write_text(
        '{"source":"bettingpros_mlb_props","row_count":1}',
        encoding="utf-8",
    )
    dk_dir = tmp_path / "data" / "mlb" / "staged" / "draftkings_mlb_pick6" / "dk_20990511"
    dk_dir.mkdir(parents=True)
    (dk_dir / "oddsapi_props.jsonl").write_text(
        '{"source":"draftkings_mlb_pick6","game_date":"2099-05-11"}\n',
        encoding="utf-8",
    )
    (dk_dir / "normalize_manifest.json").write_text(
        '{"source":"draftkings_mlb_pick6","row_count":1}',
        encoding="utf-8",
    )

    dirs = _market_source_dirs_for_run(
        root=tmp_path,
        game_date="2099-05-11",
        primary_market_source={"normalized_output_dir": str(oddsapi_dir)},
        supplemental_market_sources=[{"normalized_output_dir": str(dk_dir)}],
        run_mode="replay_single",
    )

    assert dirs == [oddsapi_dir, dk_dir]


def test_draftkings_timing_policy_tracks_each_game_window_on_normal_days():
    policy = _draftkings_timing_policy(
        {
            "rows": [
                {
                    "event_id": "early",
                    "player_team": "CIN",
                    "opponent": "PHI",
                    "game_date": "2026-05-18",
                    "start_time_utc": "2026-05-18T18:10:00Z",
                    "pulled_at_utc": "2026-05-18T19:30:00Z",
                },
                {
                    "event_id": "late",
                    "player_team": "LAD",
                    "opponent": "SD",
                    "game_date": "2026-05-18",
                    "start_time_utc": "2026-05-19T00:40:00Z",
                    "pulled_at_utc": "2026-05-18T19:30:00Z",
                },
            ]
        },
        game_date="2026-05-18",
    )

    assert policy["ready_game_count"] == 1
    assert policy["pending_game_count"] == 1
    assert policy["missing_dk_is_timing_valid"] is False
    assert policy["timing_status"] == "partial_ready_window"
    assert policy["game_windows"][0]["target_capture_utc"] == "2026-05-18T17:10:00Z"
    assert policy["game_windows"][0]["timing_status"] == "ready"
    assert policy["game_windows"][1]["target_capture_utc"] == "2026-05-18T23:40:00Z"
    assert policy["game_windows"][1]["timing_status"] == "pending"


def test_draftkings_timing_policy_all_pending_before_game_windows():
    policy = _draftkings_timing_policy(
        {
            "rows": [
                {
                    "game_date": "2026-05-17",
                    "start_time_utc": "2026-05-17T16:00:00Z",
                    "pulled_at_utc": "2026-05-17T14:30:00Z",
                }
            ]
        },
        game_date="2026-05-17",
    )

    assert policy["game_windows"][0]["target_capture_local"].startswith("2026-05-17T10:00:00")
    assert policy["missing_dk_is_timing_valid"] is True
    assert policy["timing_status"] == "all_games_before_dk_target_window"


def test_board_pipeline_normalizes_legacy_replay_mode_alias(tmp_path):
    snapshot = write_raw_snapshot(source="prizepicks", payload=_sample_prizepicks_payload(), request={}, root=tmp_path)

    manifest = run_board_pipeline(
        snapshot_path=Path(snapshot.path),
        root=tmp_path,
        run_id="replay_alias_run",
        run_mode="replay",
        game_date="2026-05-11",
    )

    assert manifest["run_mode"] == "replay_single"
    assert manifest["replay_type"] == "single"


def test_live_board_pipeline_blocks_missing_pitcher_context(tmp_path, monkeypatch):
    snapshot = write_raw_snapshot(
        source="prizepicks",
        payload=_sample_prizepicks_payload(
            game_date="2099-05-11",
            start_time="2099-05-11T18:10:00.000-04:00",
        ),
        request={},
        root=tmp_path,
    )
    _stub_live_context_refresh(monkeypatch)

    manifest = run_board_pipeline(
        snapshot_path=Path(snapshot.path),
        root=tmp_path,
        run_id="live_context_run",
        run_mode="live",
        game_date="2099-05-11",
    )

    assert manifest["operator"]["publish_allowed"] is False
    assert manifest["operator"]["severity"] == "hard_stop"
    anomalies = (tmp_path / "data" / "mlb" / "live_runs" / "live_context_run" / "operator" / "anomalies.jsonl").read_text(
        encoding="utf-8"
    )
    assert "missing_pitcher_context" in anomalies


def _stub_live_context_refresh(monkeypatch):
    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_rotowire_result",
        lambda **kwargs: RuntimeCommandResult(name="fetch_rotowire", payload={"source": "rotowire"}, lines=()),
    )
    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_baseball_savant_result",
        lambda **kwargs: RuntimeCommandResult(
            name="fetch_baseball_savant",
            payload={"source": "baseball_savant"},
            lines=(),
        ),
    )
    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_injuries_result",
        lambda **kwargs: RuntimeCommandResult(name="fetch_injuries", payload={"source": "espn_injuries"}, lines=()),
    )
    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_statsapi_teams_result",
        lambda **kwargs: RuntimeCommandResult(
            name="fetch_statsapi_teams",
            payload={"source": "statsapi_teams"},
            lines=(),
        ),
    )
    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_statsapi_schedule_result",
        lambda **kwargs: RuntimeCommandResult(
            name="fetch_statsapi_schedule",
            payload={"source": "statsapi_schedule"},
            lines=(),
        ),
    )
    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_statsapi_rosters_bulk_result",
        lambda **kwargs: RuntimeCommandResult(
            name="fetch_statsapi_rosters_bulk",
            payload={"source": "statsapi_rosters_bulk"},
            lines=(),
        ),
    )
    monkeypatch.setattr(
        "mlb.runtime.pipeline_execution.fetch_statsapi_transactions_result",
        lambda **kwargs: RuntimeCommandResult(
            name="fetch_statsapi_transactions",
            payload={"source": "statsapi_transactions"},
            lines=(),
        ),
    )


def _sample_prizepicks_payload(
    *,
    game_date: str = "2026-05-11",
    start_time: str = "2026-05-11T18:10:00.000-04:00",
):
    return {
        "data": [
            {
                "type": "projection",
                "id": "proj_hits",
                "attributes": {
                    "line_score": 1.5,
                    "stat_type": "Hits",
                    "start_time": start_time,
                    "status": "pre_game",
                    "odds_type": "standard",
                },
                "relationships": {
                    "new_player": {"data": {"type": "new_player", "id": "player1"}},
                    "game": {"data": {"type": "game", "id": "game1"}},
                },
            },
            {
                "type": "projection",
                "id": "proj_ks",
                "attributes": {
                    "line_score": 5.5,
                    "stat_type": "Pitcher Strikeouts",
                    "start_time": start_time,
                    "status": "pre_game",
                    "odds_type": "standard",
                },
                "relationships": {
                    "new_player": {"data": {"type": "new_player", "id": "player2"}},
                    "game": {"data": {"type": "game", "id": "game1"}},
                },
            },
        ],
        "included": [
            {
                "type": "new_player",
                "id": "player1",
                "attributes": {
                    "display_name": "Sample Hitter",
                    "team": "BOS",
                    "position": "IF",
                },
            },
            {
                "type": "new_player",
                "id": "player2",
                "attributes": {
                    "display_name": "Sample Pitcher",
                    "team": "BOS",
                    "position": "P",
                },
            },
            {
                "type": "game",
                "id": "game1",
                "attributes": {
                    "start_time": start_time,
                    "metadata": {
                        "game_info": {
                            "teams": {
                                "home": {"abbreviation": "BOS"},
                                "away": {"abbreviation": "NYY"},
                            }
                        }
                    },
                },
            },
        ],
    }
