import json
from pathlib import Path

from mlb.runtime.market_context import build_market_context_artifacts


def test_market_context_exact_matches_player_market_line_with_ascii_normalization(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    _write_oddsapi_context(tmp_path)

    manifest = build_market_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="market_context_run",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]

    assert manifest["coverage_rate"] == 1.0
    assert manifest["coverage_by_market"] == {"hits": 1.0}
    assert row["market_context_available"] is True
    assert row["market_line_match_type"] == "exact"
    assert row["market_source_line"] == 1.5
    assert row["market_line_delta"] == 0.0
    assert row["market_over_probability"] == 0.62
    assert row["market_n_books"] == 5
    assert row["market_context_flags"] == ["exact_player_market_line_match"]


def test_market_context_uses_nearest_line_when_exact_line_is_missing(tmp_path):
    engine_board_path = _write_engine_board(tmp_path, line=1.0)
    _write_oddsapi_context(tmp_path, line=1.5)

    manifest = build_market_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="market_context_nearest_run",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]

    assert manifest["coverage_rate"] == 1.0
    assert row["market_context_available"] is True
    assert row["market_line_match_type"] == "nearest"
    assert row["market_source_line"] == 1.5
    assert row["market_line_delta"] == 0.5
    assert row["market_context_flags"] == [
        "nearest_player_market_line_match",
        "nearest_line_delta_within_threshold",
    ]


def test_market_context_uses_wide_nearest_line_for_playable_alt_lines(tmp_path):
    engine_board_path = _write_engine_board(tmp_path, line=0.5)
    _write_oddsapi_context(tmp_path, line=1.5)

    manifest = build_market_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="market_context_wide_nearest_run",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]

    assert manifest["coverage_rate"] == 1.0
    assert row["market_context_available"] is True
    assert row["market_line_match_type"] == "wide_nearest"
    assert row["market_source_line"] == 1.5
    assert row["market_line_delta"] == 1.0
    assert row["market_context_flags"] == [
        "wide_nearest_player_market_line_match",
        "wide_line_delta_reference_context",
    ]


def test_market_context_exact_match_must_match_team_context(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    _write_oddsapi_context(tmp_path, home_team="Boston Red Sox", away_team="New York Yankees", n_books=9)
    _write_oddsapi_context(tmp_path, home_team="Cleveland Guardians", away_team="Detroit Tigers", n_books=3, append=True)

    manifest = build_market_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="market_context_same_game_run",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]

    assert manifest["coverage_rate"] == 1.0
    assert row["market_context_available"] is True
    assert row["market_line_match_type"] == "exact"
    assert row["market_home_team"] == "Cleveland Guardians"
    assert row["market_away_team"] == "Detroit Tigers"
    assert row["market_n_books"] == 3


def test_market_context_rejects_nearest_line_outside_threshold(tmp_path):
    engine_board_path = _write_engine_board(tmp_path, line=0.5)
    _write_oddsapi_context(tmp_path, line=3.5)

    manifest = build_market_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="market_context_reject_run",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]

    assert manifest["coverage_rate"] == 0.0
    assert row["market_context_available"] is False
    assert row["market_line_match_type"] == ""
    assert row["market_context_flags"] == ["missing_market_context"]


def test_market_context_selects_sources_by_row_game_date_not_folder_timestamp(tmp_path):
    engine_board_path = _write_engine_board(tmp_path, game_date="2026-05-18")
    stale_dir = _write_oddsapi_context(
        tmp_path,
        game_date="2026-05-11",
        output_run_id="bettingpros_mlb_props_20260518T010000Z_20260511",
        n_books=9,
    )
    current_dir = _write_oddsapi_context(
        tmp_path,
        game_date="2026-05-18",
        output_run_id="bettingpros_mlb_props_20260518T164213Z",
        n_books=5,
    )

    manifest = build_market_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="market_context_source_date_run",
        game_date="2026-05-18",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]

    assert manifest["coverage_rate"] == 1.0
    assert manifest["market_source_dirs_by_date"]["2026-05-18"] == [str(current_dir)]
    assert str(stale_dir) not in manifest["market_source_dirs_by_date"]["2026-05-18"]
    assert row["market_context_available"] is True
    assert row["market_n_books"] == 5


def test_market_context_can_lock_to_explicit_live_source_dir(tmp_path):
    engine_board_path = _write_engine_board(tmp_path, game_date="2026-05-18")
    stale_dir = _write_oddsapi_context(
        tmp_path,
        game_date="2026-05-18",
        output_run_id="bettingpros_mlb_props_20260517T230000Z",
        n_books=9,
    )
    live_dir = _write_oddsapi_context(
        tmp_path,
        game_date="2026-05-18",
        output_run_id="bettingpros_mlb_props_20260518T164213Z",
        n_books=4,
    )

    manifest = build_market_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="market_context_explicit_live_source_run",
        game_date="2026-05-18",
        market_source_dirs=[live_dir],
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]

    assert manifest["coverage_rate"] == 1.0
    assert manifest["market_source_dirs_by_date"]["2026-05-18"] == [str(live_dir)]
    assert str(stale_dir) not in manifest["market_source_dirs_by_date"]["2026-05-18"]
    assert row["market_context_available"] is True
    assert row["market_n_books"] == 4


def _write_engine_board(tmp_path: Path, *, line: float = 1.5, game_date: str = "2026-05-11") -> Path:
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
                        "player_name": "Jose Ramirez",
                        "player_team": "CLE",
                        "opponent": "DET",
                        "game_date": game_date,
                        "market": "hits",
                        "line": line,
                        "tier": "STANDARD",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_oddsapi_context(
    tmp_path: Path,
    *,
    line: float = 1.5,
    game_date: str = "2026-05-11",
    output_run_id: str = "oddsapi_mlb_historical_20260511T180000Z",
    home_team: str = "Cleveland Guardians",
    away_team: str = "Detroit Tigers",
    n_books: int = 5,
    append: bool = False,
) -> Path:
    output_dir = tmp_path / "data" / "mlb" / "staged" / "oddsapi" / output_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "normalize_manifest.json").write_text("{}", encoding="utf-8")
    row = {
        "snapshot_id": "odds_1",
        "source": "oddsapi_mlb_historical",
        "event_id": "mlb_game_1",
        "game_date": game_date,
        "home_team": home_team,
        "away_team": away_team,
        "player_name": "José Ramírez",
        "market": "hits",
        "line": line,
        "over_prob": 0.62,
        "under_prob": 0.38,
        "n_books": n_books,
        "snapshot_timestamp": "2026-05-11T18:00:00Z",
        "pulled_at_utc": "2026-05-11T18:01:00Z",
    }
    mode = "a" if append else "w"
    with (output_dir / "oddsapi_props.jsonl").open(mode, encoding="utf-8") as file:
        file.write(json.dumps(row) + "\n")
    return output_dir
