import json
from pathlib import Path

from mlb.runtime.player_history_context import build_player_history_context_artifacts


def test_player_history_context_projects_pa_from_statsapi_gamelogs(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    roster_context_path = _write_roster_context(tmp_path)
    staged_dir = tmp_path / "data" / "mlb" / "staged" / "statsapi_player_gamelogs_bulk" / "history_run"
    staged_dir.mkdir(parents=True)
    (staged_dir / "statsapi_player_gamelogs_bulk.jsonl").write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                _gamelog_row("2026-05-08", 5),
                _gamelog_row("2026-05-09", 4),
                _gamelog_row("2026-05-10", 5),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = build_player_history_context_artifacts(
        engine_board_path=engine_board_path,
        roster_context_path=roster_context_path,
        root=tmp_path,
        run_id="history_context_run",
        game_date="2026-05-11",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]
    assert manifest["coverage_rate"] == 1.0
    assert row["player_history_context_available"] is True
    assert row["history_games_7d"] == 3
    assert row["plate_appearance_projection"] > 4.0
    assert "statsapi_player_gamelog_history_match" in row["history_context_flags"]


def _write_engine_board(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "mlb" / "staged" / "engine_board" / "board_run" / "engine_board.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "board_run",
                "rows": [
                    {
                        "source_projection_id": "proj_hitter",
                        "event_id": "game1",
                        "player_id": "player1",
                        "player_name": "Sample Hitter",
                        "player_team": "BOS",
                        "opponent": "NYY",
                        "game_date": "2026-05-11",
                        "market": "hits",
                        "line": 0.5,
                        "tier": "STANDARD",
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
                        "statsapi_person_id": 101,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _gamelog_row(game_date: str, pa: int) -> dict:
    return {
        "season": 2026,
        "person_id": 101,
        "player_name": "Sample Hitter",
        "group": "hitting",
        "game_pk": int(game_date.replace("-", "")),
        "game_date": game_date,
        "stat": {"plateAppearances": pa, "hits": 1, "totalBases": 1, "strikeOuts": 1, "baseOnBalls": 1},
    }
