import json
from pathlib import Path

from mlb.modeling.parameters import build_parameter_table


def test_parameter_table_applies_matchup_context_shift(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    matchup_path = _write_matchup_context(tmp_path)

    baseline = build_parameter_table(engine_board_path=engine_board_path, root=tmp_path, run_id="baseline_parameters")
    adjusted = build_parameter_table(
        engine_board_path=engine_board_path,
        matchup_context_path=matchup_path,
        root=tmp_path,
        run_id="adjusted_parameters",
    )

    baseline_row = json.loads(Path(baseline["json_path"]).read_text(encoding="utf-8"))["rows"][0]
    adjusted_row = json.loads(Path(adjusted["json_path"]).read_text(encoding="utf-8"))["rows"][0]

    assert adjusted["matchup_context_available_rate"] == 1.0
    assert adjusted["matchup_context_available_by_market_group"] == {"batter": 1.0}
    assert adjusted["matchup_context_flag_counts"] == {"missing_bullpen_context": 1}
    assert adjusted["matchup_target_shift_min"] == adjusted["matchup_target_shift_max"]
    assert adjusted["pitcher_prop_matchup_neutral_count"] == 0
    assert adjusted_row["matchup_context_available"] is True
    assert adjusted_row["matchup_target_shift"] > 0.0
    assert adjusted_row["target_over_probability"] > baseline_row["target_over_probability"]
    assert "matchup_context_target_adjusted" in adjusted_row["flags"]


def test_parameter_table_blends_external_market_context_before_matchup_shift(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    market_path = _write_market_context(tmp_path)

    baseline = build_parameter_table(engine_board_path=engine_board_path, root=tmp_path, run_id="baseline_market")
    adjusted = build_parameter_table(
        engine_board_path=engine_board_path,
        market_context_path=market_path,
        root=tmp_path,
        run_id="adjusted_market",
    )

    baseline_row = json.loads(Path(baseline["json_path"]).read_text(encoding="utf-8"))["rows"][0]
    adjusted_row = json.loads(Path(adjusted["json_path"]).read_text(encoding="utf-8"))["rows"][0]

    assert adjusted["market_context_available_rate"] == 1.0
    assert adjusted["market_context_available_by_market_group"] == {"batter": 1.0}
    assert adjusted["market_context_flag_counts"] == {"exact_player_market_line_match": 1}
    assert adjusted["market_target_shift_min"] == adjusted["market_target_shift_max"]
    assert adjusted_row["market_context_available"] is True
    assert adjusted_row["market_n_books"] == 4
    assert adjusted_row["market_target_blend_weight"] > 0.0
    assert adjusted_row["market_target_shift"] > 0.0
    assert adjusted_row["target_over_probability"] > baseline_row["target_over_probability"]
    assert adjusted_row["game_date"] == "2026-05-11"
    assert adjusted_row["source_market"] == "Hits"
    assert "market_context_target_blended" in adjusted_row["flags"]


def test_parameter_table_shrinks_wide_nearest_market_context(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    exact_market_path = _write_market_context(tmp_path, run_id="exact_market")
    wide_market_path = _write_market_context(
        tmp_path,
        run_id="wide_market",
        line_match_type="wide_nearest",
        market_source_line=1.5,
        market_line_delta=1.0,
        market_over_probability=0.62,
        flags=["wide_nearest_player_market_line_match", "wide_line_delta_reference_context"],
    )

    exact = build_parameter_table(
        engine_board_path=engine_board_path,
        market_context_path=exact_market_path,
        root=tmp_path,
        run_id="adjusted_exact_market",
    )
    wide = build_parameter_table(
        engine_board_path=engine_board_path,
        market_context_path=wide_market_path,
        root=tmp_path,
        run_id="adjusted_wide_market",
    )

    exact_row = json.loads(Path(exact["json_path"]).read_text(encoding="utf-8"))["rows"][0]
    wide_row = json.loads(Path(wide["json_path"]).read_text(encoding="utf-8"))["rows"][0]

    assert wide_row["market_context_available"] is True
    assert wide_row["market_line_match_type"] == "wide_nearest"
    assert 0.0 < wide_row["market_target_blend_weight"] <= 0.08
    assert wide_row["market_target_blend_weight"] < exact_row["market_target_blend_weight"]
    assert wide_row["target_over_probability"] > 0.61
    assert "market_context_target_blended" in wide_row["flags"]


def test_parameter_table_applies_advanced_profile_context_shift(tmp_path):
    engine_board_path = _write_engine_board(tmp_path, market="total_bases")
    advanced_context_path = _write_advanced_context(tmp_path, market="total_bases")

    baseline = build_parameter_table(engine_board_path=engine_board_path, root=tmp_path, run_id="baseline_advanced")
    adjusted = build_parameter_table(
        engine_board_path=engine_board_path,
        advanced_context_path=advanced_context_path,
        root=tmp_path,
        run_id="adjusted_advanced",
    )

    baseline_row = json.loads(Path(baseline["json_path"]).read_text(encoding="utf-8"))["rows"][0]
    adjusted_row = json.loads(Path(adjusted["json_path"]).read_text(encoding="utf-8"))["rows"][0]

    assert adjusted["advanced_context_available_rate"] == 1.0
    assert adjusted["advanced_context_available_by_market_group"] == {"batter": 1.0}
    assert adjusted["advanced_target_shift_min"] == adjusted["advanced_target_shift_max"]
    assert adjusted_row["advanced_context_available"] is True
    assert adjusted_row["advanced_target_shift"] > 0.0
    assert adjusted_row["target_over_probability"] > baseline_row["target_over_probability"]
    assert "advanced_context_target_adjusted" in adjusted_row["flags"]


def test_parameter_table_applies_statsapi_pa_projection_to_batter_opportunity(tmp_path):
    engine_board_path = _write_engine_board(tmp_path, market="hits")
    player_history_path = _write_player_history_context(tmp_path)

    baseline = build_parameter_table(engine_board_path=engine_board_path, root=tmp_path, run_id="baseline_history")
    adjusted = build_parameter_table(
        engine_board_path=engine_board_path,
        player_history_context_path=player_history_path,
        root=tmp_path,
        run_id="adjusted_history",
    )

    baseline_row = json.loads(Path(baseline["json_path"]).read_text(encoding="utf-8"))["rows"][0]
    adjusted_row = json.loads(Path(adjusted["json_path"]).read_text(encoding="utf-8"))["rows"][0]

    assert adjusted["player_history_context_available_rate"] == 1.0
    assert adjusted_row["player_history_context_available"] is True
    assert adjusted_row["plate_appearance_projection"] == 5.1
    assert adjusted_row["projected_opportunity"] > baseline_row["projected_opportunity"]
    assert "statsapi_pa_projection_applied" in adjusted_row["flags"]


def test_parameter_table_does_not_apply_hitter_context_to_pitcher_props(tmp_path):
    engine_board_path = _write_engine_board(tmp_path, market="pitcher_strikeouts")
    matchup_path = _write_matchup_context(tmp_path, market="pitcher_strikeouts")

    baseline = build_parameter_table(engine_board_path=engine_board_path, root=tmp_path, run_id="baseline_pitcher")
    adjusted = build_parameter_table(
        engine_board_path=engine_board_path,
        matchup_context_path=matchup_path,
        root=tmp_path,
        run_id="adjusted_pitcher",
    )

    baseline_row = json.loads(Path(baseline["json_path"]).read_text(encoding="utf-8"))["rows"][0]
    adjusted_row = json.loads(Path(adjusted["json_path"]).read_text(encoding="utf-8"))["rows"][0]

    assert adjusted_row["matchup_context_available"] is False
    assert adjusted["pitcher_prop_matchup_neutral_count"] == 1
    assert adjusted["matchup_context_available_by_market_group"] == {"pitcher": 0.0}
    assert adjusted_row["matchup_target_shift"] == 0.0
    assert adjusted_row["target_over_probability"] == baseline_row["target_over_probability"]
    assert "pitcher_prop_matchup_neutral" in adjusted_row["flags"]
    assert "pitcher_prop_matchup_neutral_missing_source_context" in adjusted_row["matchup_context_flags"]


def test_parameter_table_applies_dedicated_pitcher_prop_context(tmp_path):
    engine_board_path = _write_engine_board(tmp_path, market="pitcher_strikeouts")
    hitter_matchup_path = _write_matchup_context(tmp_path, market="pitcher_strikeouts")
    pitcher_matchup_path = _write_pitcher_prop_context(tmp_path)

    baseline = build_parameter_table(engine_board_path=engine_board_path, root=tmp_path, run_id="baseline_pitcher")
    adjusted = build_parameter_table(
        engine_board_path=engine_board_path,
        matchup_context_path=hitter_matchup_path,
        pitcher_prop_context_path=pitcher_matchup_path,
        root=tmp_path,
        run_id="adjusted_pitcher_context",
    )

    baseline_row = json.loads(Path(baseline["json_path"]).read_text(encoding="utf-8"))["rows"][0]
    adjusted_row = json.loads(Path(adjusted["json_path"]).read_text(encoding="utf-8"))["rows"][0]

    assert adjusted["pitcher_prop_matchup_neutral_count"] == 0
    assert adjusted["pitcher_prop_context_adjusted_count"] == 1
    assert adjusted["matchup_context_available_by_market_group"] == {"pitcher": 1.0}
    assert adjusted_row["matchup_context_available"] is True
    assert adjusted_row["matchup_target_shift"] > 0.0
    assert adjusted_row["target_over_probability"] > baseline_row["target_over_probability"]
    assert "pitcher_prop_context_target_adjusted" in adjusted_row["flags"]
    assert "pitcher_prop_matchup_neutral" not in adjusted_row["flags"]


def _write_engine_board(tmp_path: Path, *, market: str = "hits") -> Path:
    path = tmp_path / "data" / "mlb" / "staged" / "engine_board" / "board_run" / "engine_board.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "board_run",
                "rows": [
                    {
                        "source_projection_id": "proj1",
                        "event_id": "game1",
                        "player_id": "player1",
                        "player_name": "Sample Player",
                        "player_team": "DET",
                        "opponent": "CLE",
                        "game_date": "2026-05-11",
                        "start_time_utc": "2026-05-11T22:10:00Z",
                        "market": market,
                        "source_market": market.title().replace("_", " "),
                        "line": 0.5,
                        "tier": "STANDARD",
                        "status": "pre_game",
                        "player_position": "OF",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_pitcher_prop_context(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "mlb" / "features" / "matchups" / "matchup_run" / "pitcher_prop_context.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "matchup_run",
                "rows": [
                    {
                        "source_projection_id": "proj1",
                        "market": "pitcher_strikeouts",
                        "line": 0.5,
                        "tier": "STANDARD",
                        "direction": "over",
                        "starter_score": 0.30,
                        "strikeout_context_score": 0.35,
                        "workload_context_score": 0.20,
                        "run_allow_context_score": -0.10,
                        "walk_context_score": -0.04,
                        "bullpen_support_score": 0.10,
                        "environment_score": 0.05,
                        "pitcher_prop_composite_score": 0.35,
                        "pitcher_prop_confidence": 0.52,
                        "missing_context_flags": ["pitcher_prop_era_only_context"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_market_context(
    tmp_path: Path,
    *,
    run_id: str = "market_run",
    line_match_type: str = "exact",
    market_source_line: float = 0.5,
    market_line_delta: float = 0.0,
    market_over_probability: float = 0.85,
    flags: list[str] | None = None,
) -> Path:
    path = tmp_path / "data" / "mlb" / "features" / "market_context" / run_id / "market_context.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_flags = flags or ["exact_player_market_line_match"]
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "rows": [
                    {
                        "source_projection_id": "proj1",
                        "market": "hits",
                        "line": 0.5,
                        "tier": "STANDARD",
                        "market_context_available": True,
                        "market_line_match_type": line_match_type,
                        "market_source_line": market_source_line,
                        "market_line_delta": market_line_delta,
                        "market_over_probability": market_over_probability,
                        "market_under_probability": 1.0 - market_over_probability,
                        "market_n_books": 4,
                        "market_context_flags": resolved_flags,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_advanced_context(tmp_path: Path, *, market: str = "hits") -> Path:
    path = tmp_path / "data" / "mlb" / "features" / "advanced_context" / "advanced_run" / "advanced_context.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "advanced_run",
                "rows": [
                    {
                        "source_projection_id": "proj1",
                        "market": market,
                        "line": 0.5,
                        "tier": "STANDARD",
                        "direction": "over",
                        "advanced_context_available": True,
                        "advanced_context_score": 0.25,
                        "advanced_hit_context_score": 0.35,
                        "advanced_power_context_score": 0.65,
                        "advanced_plate_discipline_score": 0.10,
                        "advanced_k_context_score": -0.05,
                        "advanced_contact_quality_score": 0.50,
                        "advanced_sample_confidence": 0.80,
                        "advanced_profile_source": "fixture",
                        "advanced_profile_match_type": "exact_player_team_profile_match",
                        "advanced_context_flags": ["advanced_profile_context_available"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_player_history_context(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "mlb" / "features" / "player_history_context" / "history_run" / "player_history_context.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "history_run",
                "rows": [
                    {
                        "source_projection_id": "proj1",
                        "market": "hits",
                        "line": 0.5,
                        "tier": "STANDARD",
                        "direction": "over",
                        "player_history_context_available": True,
                        "plate_appearance_projection": 5.1,
                        "history_context_confidence": 0.80,
                        "history_context_flags": ["statsapi_player_gamelog_history_match"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_matchup_context(tmp_path: Path, *, market: str = "hits") -> Path:
    path = tmp_path / "data" / "mlb" / "features" / "matchups" / "matchup_run" / "hitter_matchup_context.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "matchup_run",
                "rows": [
                    {
                        "source_projection_id": "proj1",
                        "market": market,
                        "line": 0.5,
                        "tier": "STANDARD",
                        "direction": "over",
                        "lineup_score": 0.40,
                        "starter_matchup_score": 0.35,
                        "bullpen_matchup_score": 0.0,
                        "environment_score": 0.20,
                        "matchup_composite_score": 0.30,
                        "matchup_confidence": 0.80,
                        "missing_context_flags": ["missing_bullpen_context"],
                    },
                    {
                        "source_projection_id": "proj1",
                        "market": market,
                        "line": 0.5,
                        "tier": "STANDARD",
                        "direction": "under",
                        "lineup_score": 0.40,
                        "starter_matchup_score": 0.35,
                        "bullpen_matchup_score": 0.0,
                        "environment_score": 0.20,
                        "matchup_composite_score": 0.30,
                        "matchup_confidence": 0.80,
                        "missing_context_flags": ["missing_bullpen_context"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path
