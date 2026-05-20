import json
from pathlib import Path

from mlb.runtime.statsapi_context import build_statsapi_context_artifacts


def test_statsapi_context_matches_date_team_and_opponent(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    _write_teams(tmp_path)
    _write_schedule(tmp_path)

    manifest = build_statsapi_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="statsapi_context_run",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]

    assert manifest["row_count"] == 1
    assert manifest["coverage_rate"] == 1.0
    assert row["statsapi_context_available"] is True
    assert row["game_pk"] == 824278
    assert row["venue_name"] == "Comerica Park"
    assert row["team_id"] == 141
    assert row["opponent_id"] == 116
    assert row["is_home"] is False
    assert row["statsapi_context_flags"] == ["date_team_opponent_statsapi_match"]


def _write_engine_board(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "mlb" / "staged" / "engine_board" / "board_run" / "engine_board.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "board_run",
                "rows": [
                    {
                        "source_projection_id": "proj_hits",
                        "event_id": "game1",
                        "player_id": "player1",
                        "player_name": "Sample Hitter",
                        "player_team": "TOR",
                        "opponent": "DET",
                        "game_date": "2026-05-16",
                        "market": "hits",
                        "line": 1.5,
                        "tier": "STANDARD",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_teams(tmp_path: Path) -> None:
    path = tmp_path / "data" / "mlb" / "staged" / "statsapi_teams" / "teams_run" / "statsapi_teams.jsonl"
    path.parent.mkdir(parents=True)
    rows = [
        {
            "level": "MLB",
            "team_id": 141,
            "team_abbreviation": "TOR",
            "team_name": "Toronto Blue Jays",
            "team_short_name": "Toronto",
            "club_name": "Blue Jays",
        },
        {
            "level": "MLB",
            "team_id": 116,
            "team_abbreviation": "DET",
            "team_name": "Detroit Tigers",
            "team_short_name": "Detroit",
            "club_name": "Tigers",
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _write_schedule(tmp_path: Path) -> None:
    path = tmp_path / "data" / "mlb" / "staged" / "statsapi_schedule" / "schedule_run" / "statsapi_schedule.jsonl"
    path.parent.mkdir(parents=True)
    row = {
        "game_pk": 824278,
        "game_date": "2026-05-16T17:10:00Z",
        "official_date": "2026-05-16",
        "status": "Scheduled",
        "away_team_id": 141,
        "away_team_name": "Toronto Blue Jays",
        "home_team_id": 116,
        "home_team_name": "Detroit Tigers",
        "venue_id": 2394,
        "venue_name": "Comerica Park",
        "series_description": "Regular Season",
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
