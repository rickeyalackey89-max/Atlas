import json
from pathlib import Path

from mlb.modeling.features import build_player_prop_feature_table


def test_feature_table_writes_source_completeness_contract(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)

    manifest = build_player_prop_feature_table(engine_board_path=engine_board_path, root=tmp_path, run_id="feature_run")

    assert manifest["row_count"] == 2
    assert manifest["feature_model_version"] == "baseline_player_prop_features_v1_market_source_type"
    assert manifest["source_completeness"]["lineup_context_available"] == 0.0
    assert manifest["opportunity_model_versions"] == {"baseline_opportunity_v0": 2}
    assert Path(manifest["csv_path"]).exists()
    assert Path(manifest["latest_manifest_path"]).exists()
    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    assert payload["rows"][0]["game_date"] == "2026-05-11"
    assert payload["rows"][0]["source_market"] == "Hits"
    assert payload["rows"][0]["market_context_source_type"] == "prizepicks_line_only"
    assert payload["rows"][0]["prizepicks_line_only_market_context"] is True


def test_feature_table_carries_report_only_injury_context(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    injury_context_path = _write_injury_context(tmp_path)

    manifest = build_player_prop_feature_table(
        engine_board_path=engine_board_path,
        injury_context_path=injury_context_path,
        root=tmp_path,
        run_id="feature_injury_run",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    injury_row = next(row for row in payload["rows"] if row["source_projection_id"] == "proj_hitter")
    clean_row = next(row for row in payload["rows"] if row["source_projection_id"] == "proj_pitcher")

    assert manifest["source_completeness"]["injury_context_available"] == 0.5
    assert manifest["injury_context_path"] == str(injury_context_path)
    assert injury_row["injury_context_available"] is True
    assert injury_row["injury_status"] == "Day-To-Day"
    assert injury_row["injury_risk_score"] == 0.45
    assert "injury_context_available" in injury_row["flags"]
    assert clean_row["injury_context_available"] is False
    assert clean_row["injury_context_flags"] == ["missing_injury_context_row"]


def test_feature_table_carries_report_only_statsapi_context(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    statsapi_context_path = _write_statsapi_context(tmp_path)

    manifest = build_player_prop_feature_table(
        engine_board_path=engine_board_path,
        statsapi_context_path=statsapi_context_path,
        root=tmp_path,
        run_id="feature_statsapi_run",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    statsapi_row = next(row for row in payload["rows"] if row["source_projection_id"] == "proj_hitter")
    clean_row = next(row for row in payload["rows"] if row["source_projection_id"] == "proj_pitcher")

    assert manifest["source_completeness"]["statsapi_context_available"] == 0.5
    assert manifest["statsapi_context_path"] == str(statsapi_context_path)
    assert statsapi_row["statsapi_context_available"] is True
    assert statsapi_row["statsapi_game_pk"] == 824278
    assert statsapi_row["statsapi_venue_name"] == "Comerica Park"
    assert "statsapi_context_available" in statsapi_row["flags"]
    assert clean_row["statsapi_context_available"] is False
    assert clean_row["statsapi_context_flags"] == ["missing_statsapi_context_row"]


def test_feature_table_carries_report_only_roster_context(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    roster_context_path = _write_roster_context(tmp_path)

    manifest = build_player_prop_feature_table(
        engine_board_path=engine_board_path,
        roster_context_path=roster_context_path,
        root=tmp_path,
        run_id="feature_roster_run",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    roster_row = next(row for row in payload["rows"] if row["source_projection_id"] == "proj_hitter")
    clean_row = next(row for row in payload["rows"] if row["source_projection_id"] == "proj_pitcher")

    assert manifest["source_completeness"]["roster_context_available"] == 0.5
    assert manifest["roster_context_path"] == str(roster_context_path)
    assert roster_row["roster_context_available"] is True
    assert roster_row["statsapi_person_id"] == 101
    assert roster_row["statsapi_player_position"] == "OF"
    assert roster_row["statsapi_bats"] == "L"
    assert "roster_context_available" in roster_row["flags"]
    assert clean_row["roster_context_available"] is False
    assert clean_row["roster_context_flags"] == ["missing_roster_context_row"]


def test_feature_table_carries_advanced_profile_context(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    advanced_context_path = _write_advanced_context(tmp_path)

    manifest = build_player_prop_feature_table(
        engine_board_path=engine_board_path,
        advanced_context_path=advanced_context_path,
        root=tmp_path,
        run_id="feature_advanced_run",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    advanced_row = next(row for row in payload["rows"] if row["source_projection_id"] == "proj_hitter")
    clean_row = next(row for row in payload["rows"] if row["source_projection_id"] == "proj_pitcher")

    assert manifest["source_completeness"]["advanced_context_available"] == 0.5
    assert manifest["advanced_context_path"] == str(advanced_context_path)
    assert advanced_row["advanced_context_available"] is True
    assert advanced_row["advanced_context_score"] == 0.32
    assert advanced_row["advanced_power_context_score"] == 0.41
    assert advanced_row["advanced_profile_source"] == "fixture"
    assert "advanced_context_available" in advanced_row["flags"]
    assert clean_row["advanced_context_available"] is False
    assert clean_row["advanced_context_flags"] == ["missing_advanced_context_row"]


def _write_engine_board(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "mlb" / "staged" / "engine_board" / "board_run" / "engine_board.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "board_run",
                "rows": [
                    _row("proj_hitter", "hits", "IF"),
                    _row("proj_pitcher", "pitcher_strikeouts", "P"),
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_advanced_context(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "mlb" / "features" / "advanced_context" / "advanced_run" / "advanced_context.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "advanced_run",
                "rows": [
                    {
                        "source_projection_id": "proj_hitter",
                        "market": "hits",
                        "line": 0.5,
                        "tier": "STANDARD",
                        "advanced_context_available": True,
                        "advanced_context_score": 0.32,
                        "advanced_hit_context_score": 0.52,
                        "advanced_power_context_score": 0.41,
                        "advanced_plate_discipline_score": 0.12,
                        "advanced_k_context_score": -0.08,
                        "advanced_contact_quality_score": 0.44,
                        "advanced_sample_confidence": 0.72,
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


def _write_roster_context(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "mlb" / "features" / "roster_context" / "roster_run" / "roster_context.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "roster_run",
                "rows": [
                    {
                        "source_projection_id": "proj_hitter",
                        "market": "hits",
                        "line": 0.5,
                        "tier": "STANDARD",
                        "roster_context_available": True,
                        "statsapi_person_id": 101,
                        "statsapi_roster_team_id": 111,
                        "statsapi_roster_team_abbreviation": "BOS",
                        "statsapi_player_position": "OF",
                        "statsapi_bats": "L",
                        "statsapi_throws": "R",
                        "statsapi_roster_status": "Active",
                        "roster_context_flags": ["player_name_team_abbreviation_match"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_statsapi_context(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "mlb" / "features" / "statsapi_context" / "statsapi_run" / "statsapi_context.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "statsapi_run",
                "rows": [
                    {
                        "source_projection_id": "proj_hitter",
                        "market": "hits",
                        "line": 0.5,
                        "tier": "STANDARD",
                        "statsapi_context_available": True,
                        "game_pk": 824278,
                        "statsapi_game_status": "Scheduled",
                        "venue_id": 2394,
                        "venue_name": "Comerica Park",
                        "team_id": 141,
                        "opponent_id": 116,
                        "is_home": False,
                        "statsapi_context_flags": ["date_team_opponent_statsapi_match"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_injury_context(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "mlb" / "features" / "injury_context" / "injury_run" / "injury_context.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "injury_run",
                "rows": [
                    {
                        "source_projection_id": "proj_hitter",
                        "market": "hits",
                        "line": 0.5,
                        "tier": "STANDARD",
                        "injury_context_available": True,
                        "injury_status": "Day-To-Day",
                        "injury_risk_score": 0.45,
                        "injury_context_flags": [
                            "exact_player_team_injury_match",
                            "player_on_injury_report",
                            "injury_status_uncertain",
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _row(projection_id: str, market: str, position: str) -> dict:
    return {
        "source_projection_id": projection_id,
        "event_id": "game",
        "player_id": projection_id.replace("proj_", ""),
        "player_name": "Sample Player",
        "player_team": "BOS",
        "opponent": "NYY",
        "game_date": "2026-05-11",
        "start_time_utc": "2026-05-11T22:10:00Z",
        "player_position": position,
        "market": market,
        "source_market": market.title().replace("_", " "),
        "line": 0.5,
        "tier": "STANDARD",
        "status": "pre_game",
        "is_live": False,
        "is_combo": False,
    }
