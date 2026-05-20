import json
from pathlib import Path

import pytest

from mlb.runtime.replay_eval import evaluate_scored_run


def test_replay_eval_settles_scored_legs_and_writes_metrics(tmp_path):
    run_dir = tmp_path / "data" / "mlb" / "runs" / "eval_run"
    run_dir.mkdir(parents=True)
    scored_path = run_dir / "scored_legs.json"
    system_slip_dir = run_dir / "slips"
    system_slip_dir.mkdir()
    scored_path.write_text(
        json.dumps(
            {
                "run_id": "eval_run",
                "source_run_id": "board_run",
                "scored_legs": [
                    _scored_leg(
                        projection_id="hit_over",
                        player="Sample Hitter",
                        market="hits",
                        line=0.5,
                        side="over",
                        model_probability=0.7,
                    ),
                    _scored_leg(
                        projection_id="pitcher_under",
                        player="Sample Pitcher",
                        market="pitcher_strikeouts",
                        line=5.5,
                        side="under",
                        model_probability=0.6,
                    ),
                ],
            }
        ),
        encoding="utf-8",
    )
    (system_slip_dir / "system_2leg.json").write_text(
        json.dumps(
            {
                "family": "System",
                "target_leg_count": 2,
                "hit_prob": 0.42,
                "payout_mult": 3.0,
                "legs": [
                    _scored_leg(
                        projection_id="hit_over",
                        player="Sample Hitter",
                        market="hits",
                        line=0.5,
                        side="over",
                        model_probability=0.7,
                    ),
                    _scored_leg(
                        projection_id="pitcher_under",
                        player="Sample Pitcher",
                        market="pitcher_strikeouts",
                        line=5.5,
                        side="under",
                        model_probability=0.6,
                    ),
                ],
            }
        ),
        encoding="utf-8",
    )
    boxscore_dir = tmp_path / "data" / "mlb" / "staged" / "statsapi_boxscores_bulk" / "boxscores"
    boxscore_dir.mkdir(parents=True)
    (boxscore_dir / "statsapi_boxscores_bulk.jsonl").write_text(
        "\n".join(
            json.dumps(row, sort_keys=True)
            for row in [
                _boxscore_hitter("Sample Hitter", hits=1),
                _boxscore_pitcher("Sample Pitcher", strikeouts=7),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = evaluate_scored_run(run_id="eval_run", root=tmp_path)

    assert manifest["settled_count"] == 2
    assert manifest["metric_count"] == 2
    assert manifest["result_counts"] == {"loss": 1, "win": 1}
    assert manifest["brier"] == pytest.approx(0.225)
    assert manifest["logloss"] == pytest.approx(0.636483)
    assert manifest["slip_eval"]["slip_count"] == 1
    assert manifest["slip_eval"]["result_counts"] == {"loss": 1}
    assert Path(manifest["slip_eval"]["slip_eval_path"]).exists()
    eval_payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    eval_by_projection = {row["source_projection_id"]: row for row in eval_payload["rows"]}
    assert eval_by_projection["hit_over"]["external_market_context_available"] is True
    assert eval_by_projection["hit_over"]["bettingpros_recommended_side"] == "over"
    assert eval_by_projection["hit_over"]["bettingpros_streak"] == 2
    assert eval_by_projection["hit_over"]["bettingpros_last_5_over_rate"] == pytest.approx(0.6)
    slip_payload = json.loads(Path(manifest["slip_eval"]["slip_eval_path"]).read_text(encoding="utf-8"))
    assert slip_payload["slips"][0]["result"] == "loss"
    assert slip_payload["slips"][0]["loss_count"] == 1
    assert Path(manifest["csv_path"]).exists()
    assert Path(manifest["latest_manifest_path"]).exists()
    runtime_eval_dir = tmp_path / "data" / "mlb" / "runtime_state" / "eval"
    assert (runtime_eval_dir / "eval_legs_running.csv").exists()
    assert (runtime_eval_dir / "eval_slips_running.csv").exists()
    assert (runtime_eval_dir / "daily_eval_summary.jsonl").exists()


def test_replay_eval_marks_push_without_metric(tmp_path):
    run_dir = tmp_path / "data" / "mlb" / "runs" / "push_run"
    run_dir.mkdir(parents=True)
    (run_dir / "scored_legs.json").write_text(
        json.dumps(
            {
                "run_id": "push_run",
                "source_run_id": "board_run",
                "scored_legs": [
                    _scored_leg(
                        projection_id="push_hit",
                        player="Sample Hitter",
                        market="hits",
                        line=1.0,
                        side="over",
                        model_probability=0.7,
                    ),
                ],
            }
        ),
        encoding="utf-8",
    )
    boxscore_dir = tmp_path / "data" / "mlb" / "staged" / "statsapi_boxscores_bulk" / "boxscores"
    boxscore_dir.mkdir(parents=True)
    (boxscore_dir / "statsapi_boxscores_bulk.jsonl").write_text(
        json.dumps(_boxscore_hitter("Sample Hitter", hits=1), sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest = evaluate_scored_run(run_id="push_run", root=tmp_path)

    rows = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))["rows"]
    assert manifest["settled_count"] == 1
    assert manifest["metric_count"] == 0
    assert manifest["slip_eval"]["slip_count"] == 0
    assert Path(manifest["slip_eval"]["slip_eval_path"]).exists()
    assert rows[0]["result"] == "push"
    assert rows[0]["brier"] is None


def _scored_leg(
    *,
    projection_id: str,
    player: str,
    market: str,
    line: float,
    side: str,
    model_probability: float,
) -> dict:
    return {
        "run_id": "eval_run",
        "source_run_id": "board_run",
        "snapshot_id": "snap",
        "source_projection_id": projection_id,
        "event_id": "game1",
        "game_date": "2026-05-11",
        "player_id": "",
        "player_name": player,
        "player_team": "BOS",
        "opponent": "NYY",
        "market": market,
        "line": line,
        "side": side,
        "model_probability": model_probability,
        "over_probability": model_probability if side == "over" else 1.0 - model_probability,
        "under_probability": model_probability if side == "under" else 1.0 - model_probability,
        "push_probability": 0.0,
        "simulation_kernel_version": "mlb_sobol_qmc_market_prior_v0",
        "simulation_n": 2048,
        "simulation_seed": 123,
        "parameter_model_version": "market_prior_parameters_v0",
        "calibration_version": "uncalibrated_v0",
        "method": "market_prior_sobol_qmc_baseline",
        "kernel_version": "mlb_market_prior_sobol_qmc_v0",
        "model_version": "mlb-dev-baseline-0.1",
        "confidence_tier": "medium",
        "external_market_context_available": True,
        "bettingpros_recommended_side": side,
        "bettingpros_projection_value": 1.0,
        "bettingpros_projection_probability": 0.58,
        "bettingpros_projection_expected_value": 0.06,
        "bettingpros_projection_diff": 0.4,
        "bettingpros_streak": 2,
        "bettingpros_streak_type": side,
        "bettingpros_last_5_over_rate": 0.6,
        "bettingpros_last_5_under_rate": 0.4,
        "bettingpros_last_10_over_rate": 0.55,
        "bettingpros_last_10_under_rate": 0.45,
        "bettingpros_last_20_over_rate": 0.52,
        "bettingpros_last_20_under_rate": 0.48,
        "bettingpros_season_over_rate": 0.51,
        "bettingpros_season_under_rate": 0.49,
        "bettingpros_prior_season_over_rate": 0.5,
        "bettingpros_prior_season_under_rate": 0.5,
        "flags": ("sobol_qmc",),
    }


def _boxscore_hitter(player: str, *, hits: int) -> dict:
    return {
        "official_date": "2026-05-11",
        "game_pk": 1,
        "person_id": 11,
        "player_name": player,
        "team_name": "Boston Red Sox",
        "opponent_name": "New York Yankees",
        "batting_stats": {
            "hits": hits,
            "doubles": 0,
            "triples": 0,
            "homeRuns": 0,
            "runs": 0,
            "rbi": 0,
            "plateAppearances": 4,
            "baseOnBalls": 0,
            "stolenBases": 0,
            "strikeOuts": 1,
        },
        "pitching_stats": {},
    }


def _boxscore_pitcher(player: str, *, strikeouts: int) -> dict:
    return {
        "official_date": "2026-05-11",
        "game_pk": 1,
        "person_id": 22,
        "player_name": player,
        "team_name": "Boston Red Sox",
        "opponent_name": "New York Yankees",
        "batting_stats": {},
        "pitching_stats": {
            "strikeOuts": strikeouts,
            "outs": 18,
            "hits": 4,
            "earnedRuns": 2,
            "baseOnBalls": 1,
            "pitchesThrown": 91,
            "wins": 1,
        },
        "is_pitching_starter": True,
    }
