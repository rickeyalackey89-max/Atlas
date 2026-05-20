import json
from pathlib import Path

from mlb.runtime.replay_eval import evaluate_scored_run
from mlb.runtime.season_gamelogs import refresh_season_gamelogs


def test_refresh_season_gamelogs_merges_staged_statsapi_rows(tmp_path):
    staged = tmp_path / "data" / "mlb" / "staged" / "statsapi_player_gamelogs_bulk" / "history"
    staged.mkdir(parents=True)
    (staged / "statsapi_player_gamelogs_bulk.jsonl").write_text(
        json.dumps(
            {
                "source": "statsapi_player_gamelogs_bulk",
                "season": 2026,
                "person_id": 11,
                "player_name": "Sample Hitter",
                "group": "hitting",
                "game_pk": 100,
                "game_date": "2026-05-11",
                "team_name": "Boston Red Sox",
                "opponent_name": "New York Yankees",
                "stat": {"atBats": 4, "hits": 2, "plateAppearances": 5},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = refresh_season_gamelogs(season=2026, root=tmp_path)

    assert manifest["row_count"] == 1
    assert manifest["source_counts"] == {"statsapi_player_gamelogs_bulk": 1}
    rows = [json.loads(line) for line in Path(manifest["jsonl_path"]).read_text(encoding="utf-8").splitlines()]
    assert rows[0]["player_name"] == "Sample Hitter"
    assert rows[0]["batting_stats"]["hits"] == 2
    assert Path(manifest["latest_jsonl_path"]).exists()


def test_replay_eval_can_settle_from_running_season_gamelogs(tmp_path):
    season_dir = tmp_path / "data" / "mlb" / "season_gamelogs"
    season_dir.mkdir(parents=True)
    (season_dir / "mlb_2026_gamelogs.jsonl").write_text(
        json.dumps(
            {
                "source": "statsapi_boxscores_bulk",
                "season": 2026,
                "group": "hitting",
                "game_date": "2026-05-11",
                "game_pk": 100,
                "person_id": 11,
                "player_name": "Sample Hitter",
                "team_name": "Boston Red Sox",
                "team_abbreviation": "BOS",
                "opponent_name": "New York Yankees",
                "opponent_abbreviation": "NYY",
                "stat": {"hits": 1, "plateAppearances": 4},
                "batting_stats": {"hits": 1, "plateAppearances": 4},
                "pitching_stats": {},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    run_dir = tmp_path / "data" / "mlb" / "runs" / "season_eval_run"
    run_dir.mkdir(parents=True)
    (run_dir / "scored_legs.json").write_text(
        json.dumps(
            {
                "run_id": "season_eval_run",
                "scored_legs": [
                    {
                        "run_id": "season_eval_run",
                        "source_projection_id": "p1",
                        "game_date": "2026-05-11",
                        "player_name": "Sample Hitter",
                        "player_team": "BOS",
                        "opponent": "NYY",
                        "market": "hits",
                        "line": 0.5,
                        "side": "over",
                        "model_probability": 0.7,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manifest = evaluate_scored_run(run_id="season_eval_run", root=tmp_path)

    assert manifest["staged_boxscore_row_count"] == 0
    assert manifest["season_gamelog_row_count"] == 1
    assert manifest["settled_count"] == 1
    rows = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))["rows"]
    assert rows[0]["result"] == "win"
    assert rows[0]["settlement_source"] == "statsapi_boxscores_bulk"
