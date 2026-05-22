import json
from pathlib import Path

import pytest

from mlb.cli import main
from mlb.contracts.engine import EngineBoardRow
from mlb.modeling.engine import score_engine_board, score_engine_board_row
from mlb.modeling.probability import score_probability


def test_probability_kernel_scores_market_specific_sides():
    hits = EngineBoardRow.from_mapping(_engine_row(market="hits", line=0.5), run_id="board_run")
    home_runs = EngineBoardRow.from_mapping(_engine_row(market="home_runs", line=0.5), run_id="board_run")

    hits_probability = score_probability(hits)
    home_run_probability = score_probability(home_runs)

    assert hits_probability.recommended_side == "over"
    assert home_run_probability.recommended_side == "under"
    assert 0.0 <= hits_probability.model_probability <= 1.0
    assert "context_free_baseline" in hits_probability.flags
    assert hits_probability.simulation_kernel_version.startswith("mlb_sobol_qmc")
    assert hits_probability.simulation_n == 2048
    assert hits_probability.p10 <= hits_probability.median_projection <= hits_probability.p90
    assert hits_probability.opportunity_model_version == "baseline_opportunity_v0"
    assert hits_probability.opportunity_type == "plate_appearances_proxy"


def test_probability_kernel_preserves_push_probability_for_integer_lines():
    row = EngineBoardRow.from_mapping(_engine_row(market="hits", line=1.0), run_id="board_run")

    probability = score_probability(row)

    assert probability.push_probability > 0
    assert probability.over_probability + probability.under_probability + probability.push_probability == pytest.approx(
        1.0,
        abs=0.01,
    )


def test_probability_kernel_never_recommends_nonstandard_under():
    row = EngineBoardRow.from_mapping(
        _engine_row(market="home_runs", line=0.5, tier="DEMON"),
        run_id="board_run",
    )

    probability = score_probability(row)

    assert probability.recommended_side == "over"
    assert probability.model_probability == probability.over_probability
    assert probability.under_probability > probability.over_probability
    assert "playable_side_over_only" in probability.flags


def test_engine_scores_board_and_writes_contract_outputs(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)

    manifest = score_engine_board(engine_board_path=engine_board_path, root=tmp_path, run_id="score_run")

    assert manifest["run_id"] == "score_run"
    assert manifest["source_run_id"] == "board_run"
    assert manifest["row_count"] == 2
    assert manifest["kernel_contract"]["kernel_version"] == "mlb_market_prior_sobol_qmc_v0"
    assert manifest["kernel_contract"]["simulation_kernel_version"] == "mlb_sobol_qmc_market_prior_v0"
    assert 0.5 <= manifest["model_probability_min"] <= manifest["model_probability_max"] <= 1.0
    assert Path(manifest["csv_path"]).exists()
    assert Path(manifest["json_path"]).exists()
    assert Path(manifest["latest_json_path"]).exists()

    scored = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    simulation_manifest = json.loads(
        (tmp_path / "data" / "mlb" / "replay_runs" / "score_run" / "simulation_manifest.json").read_text(encoding="utf-8")
    )
    assert Path(manifest["deduped_csv_path"]).exists()
    assert scored["scored_legs"][0]["kernel_version"]
    assert simulation_manifest["kernel_contract"]["calibration_version"] == "uncalibrated_v0"
    assert scored["scored_legs"][0]["model_version"]
    assert scored["scored_legs"][0]["simulation_kernel_version"]
    assert scored["scored_legs"][0]["simulation_seed"]
    assert scored["scored_legs"][0]["opportunity_model_version"] == "baseline_opportunity_v0"
    assert scored["scored_legs"][0]["projected_opportunity"] > 0
    assert set(manifest["side_counts"]) <= {"over", "under"}


def test_engine_scores_from_parameter_table_when_supplied(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    parameter_table_path = _write_parameter_table(tmp_path)
    feature_table_path = _write_feature_table(tmp_path)

    manifest = score_engine_board(
        engine_board_path=engine_board_path,
        parameter_table_path=parameter_table_path,
        feature_table_path=feature_table_path,
        root=tmp_path,
        run_id="parameter_score_run",
    )

    scored = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    by_projection = {row["source_projection_id"]: row for row in scored["scored_legs"]}

    assert manifest["parameter_row_match_count"] == 2
    assert manifest["parameter_row_missing_count"] == 0
    assert by_projection["proj2"]["side"] == "over"
    assert by_projection["proj2"]["over_probability"] == pytest.approx(0.80, abs=0.03)
    assert "parameter_table_target" in by_projection["proj2"]["flags"]
    assert manifest["feature_row_match_count"] == 2
    assert by_projection["proj2"]["external_market_context_available"] is True
    assert by_projection["proj2"]["bettingpros_recommended_side"] == "over"
    assert by_projection["proj2"]["bettingpros_streak"] == 3
    assert by_projection["proj2"]["bettingpros_last_5_over_rate"] == pytest.approx(0.8)


def test_engine_manifest_reports_active_calibration_from_parameter_table(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    parameter_table_path = _write_parameter_table(
        tmp_path,
        calibration_version="mlb_cat_over_residual_test_v1",
        flags=["market_prior_parameters_v0", "cat_probability_calibrated"],
    )

    manifest = score_engine_board(
        engine_board_path=engine_board_path,
        parameter_table_path=parameter_table_path,
        root=tmp_path,
        run_id="calibrated_score_run",
    )

    scored = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    simulation_manifest = json.loads(
        (tmp_path / "data" / "mlb" / "replay_runs" / "calibrated_score_run" / "simulation_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["kernel_contract"]["calibration_version"] == "mlb_cat_over_residual_test_v1"
    assert manifest["calibration_versions"] == {"mlb_cat_over_residual_test_v1": 2}
    assert simulation_manifest["kernel_contract"]["calibration_version"] == "mlb_cat_over_residual_test_v1"
    assert simulation_manifest["calibration_versions"] == {"mlb_cat_over_residual_test_v1": 2}
    assert "cat_probability_calibrated" in scored["scored_legs"][0]["flags"]
    assert "uncalibrated" not in scored["scored_legs"][0]["flags"]


def test_cli_score_board_delegates_to_runtime(tmp_path, capsys):
    engine_board_path = _write_engine_board(tmp_path)

    exit_code = main(["score", "board", "--engine-board", str(engine_board_path), "--run-id", "cli_score_run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Scored MLB engine board:" in captured.out
    assert (tmp_path / "data" / "mlb" / "replay_runs" / "cli_score_run" / "scored_legs.json").exists()


def test_engine_board_row_score_preserves_source_identity():
    row = EngineBoardRow.from_mapping(_engine_row(market="total_bases", line=1.5), run_id="board_run")

    scored = score_engine_board_row(row, run_id="score_run")

    assert scored.run_id == "score_run"
    assert scored.source_run_id == "board_run"
    assert scored.source_projection_id == "proj1"
    assert scored.snapshot_id == "snap1"


def _write_engine_board(tmp_path: Path) -> Path:
    engine_board_dir = tmp_path / "data" / "mlb" / "staged" / "engine_board" / "board_run"
    engine_board_dir.mkdir(parents=True)
    engine_board_path = engine_board_dir / "engine_board.json"
    engine_board_path.write_text(
        json.dumps(
            {
                "run_id": "board_run",
                "source": "prizepicks",
                "snapshot_id": "snap1",
                "row_count": 2,
                "rows": [
                    _engine_row(market="hits", line=0.5),
                    _engine_row(market="home_runs", line=0.5, projection_id="proj2"),
                ],
            }
        ),
        encoding="utf-8",
    )
    return engine_board_path


def _write_parameter_table(
    tmp_path: Path,
    *,
    calibration_version: str = "",
    flags: list[str] | None = None,
) -> Path:
    parameter_path = tmp_path / "data" / "mlb" / "features" / "parameters" / "parameter_run" / "parameter_table.json"
    parameter_path.parent.mkdir(parents=True)
    parameter_path.write_text(
        json.dumps(
            {
                "run_id": "parameter_run",
                "row_count": 2,
                "rows": [
                    _parameter_row(
                        projection_id="proj1",
                        market="hits",
                        line=0.5,
                        target=0.61,
                        calibration_version=calibration_version,
                        flags=flags,
                    ),
                    _parameter_row(
                        projection_id="proj2",
                        market="home_runs",
                        line=0.5,
                        target=0.80,
                        calibration_version=calibration_version,
                        flags=flags,
                    ),
                ],
            }
        ),
        encoding="utf-8",
    )
    return parameter_path


def _write_feature_table(tmp_path: Path) -> Path:
    feature_path = tmp_path / "data" / "mlb" / "features" / "player_props" / "parameter_score_run" / "feature_table.json"
    feature_path.parent.mkdir(parents=True)
    feature_path.write_text(
        json.dumps(
            {
                "run_id": "parameter_score_run",
                "row_count": 2,
                "rows": [
                    _feature_row(projection_id="proj1", market="hits", line=0.5, recommended_side="under"),
                    _feature_row(projection_id="proj2", market="home_runs", line=0.5, recommended_side="over"),
                ],
            }
        ),
        encoding="utf-8",
    )
    return feature_path


def _engine_row(*, market: str, line: float, projection_id: str = "proj1", tier: str = "STANDARD") -> dict:
    return {
        "snapshot_id": "snap1",
        "source_projection_id": projection_id,
        "event_id": "game1",
        "league": "MLB",
        "game_date": "2026-05-11",
        "start_time_utc": "2026-05-11T23:10:00Z",
        "player_id": "player1",
        "player_name": "Sample Player",
        "player_team": "BOS",
        "opponent": "NYY",
        "market": market,
        "source_market": market.replace("_", " ").title(),
        "line": line,
        "tier": tier,
        "status": "pre_game",
        "player_position": "IF",
        "is_live": False,
        "is_combo": False,
        "updated_at": "2026-05-11T20:00:00Z",
        "pulled_at_utc": "2026-05-11T20:00:00Z",
    }


def _parameter_row(
    *,
    projection_id: str,
    market: str,
    line: float,
    target: float,
    calibration_version: str = "",
    flags: list[str] | None = None,
) -> dict:
    row = _engine_row(market=market, line=line, projection_id=projection_id)
    payload = {
        "source_projection_id": row["source_projection_id"],
        "event_id": row["event_id"],
        "player_id": row["player_id"],
        "market": row["market"],
        "line": row["line"],
        "tier": row["tier"],
        "target_over_probability": target,
        "distribution": "poisson",
        "simulation_n": 2048,
        "parameter_model_version": "test_parameter_table_v0",
    }
    if calibration_version:
        payload["calibration_version"] = calibration_version
    if flags is not None:
        payload["flags"] = flags
    return payload


def _feature_row(*, projection_id: str, market: str, line: float, recommended_side: str) -> dict:
    row = _engine_row(market=market, line=line, projection_id=projection_id)
    return {
        **row,
        "external_market_context_available": True,
        "bettingpros_recommended_side": recommended_side,
        "bettingpros_projection_value": 1.0,
        "bettingpros_projection_probability": 0.58,
        "bettingpros_projection_expected_value": 0.07,
        "bettingpros_projection_diff": 0.5,
        "bettingpros_streak": 3,
        "bettingpros_streak_type": recommended_side,
        "bettingpros_last_5_over_rate": 0.8,
        "bettingpros_last_5_under_rate": 0.2,
        "bettingpros_last_10_over_rate": 0.7,
        "bettingpros_last_10_under_rate": 0.3,
        "bettingpros_last_20_over_rate": 0.6,
        "bettingpros_last_20_under_rate": 0.4,
        "bettingpros_season_over_rate": 0.55,
        "bettingpros_season_under_rate": 0.45,
        "bettingpros_prior_season_over_rate": 0.52,
        "bettingpros_prior_season_under_rate": 0.48,
    }
