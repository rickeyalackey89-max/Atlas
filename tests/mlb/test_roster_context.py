import json
from pathlib import Path

from mlb.runtime.roster_context import build_roster_context_artifacts


def test_roster_context_matches_player_and_statsapi_team_id(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    statsapi_context_path = _write_statsapi_context(tmp_path)
    _write_bulk_rosters(tmp_path)

    manifest = build_roster_context_artifacts(
        engine_board_path=engine_board_path,
        statsapi_context_path=statsapi_context_path,
        root=tmp_path,
        run_id="roster_context_run",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]

    assert manifest["row_count"] == 1
    assert manifest["coverage_rate"] == 1.0
    assert row["roster_context_available"] is True
    assert row["statsapi_person_id"] == 101
    assert row["statsapi_roster_team_id"] == 141
    assert row["statsapi_roster_team_abbreviation"] == "TOR"
    assert row["statsapi_player_position"] == "OF"
    assert row["statsapi_bats"] == "L"
    assert row["statsapi_throws"] == "R"
    assert row["roster_context_flags"] == ["player_name_statsapi_team_id_match"]


def test_roster_context_keeps_strict_replay_fidelity_when_date_safe_snapshot_is_thin(tmp_path):
    engine_board_path = _write_engine_board_with_date(tmp_path, game_date="2026-05-11")
    statsapi_context_path = _write_statsapi_context(tmp_path)
    _write_rosters(
        tmp_path,
        root_name="statsapi_rosters",
        file_name="statsapi_rosters.jsonl",
        snapshot_id="statsapi_rosters_20260511T213237Z",
        player_name="Sample Hitter",
        person_id=101,
    )
    _write_rosters(
        tmp_path,
        root_name="statsapi_rosters_bulk",
        file_name="statsapi_rosters_bulk.jsonl",
        snapshot_id="statsapi_rosters_bulk_20260516T190105Z",
        player_name="Sample Hitter",
        person_id=999,
        extra_count=220,
    )

    manifest = build_roster_context_artifacts(
        engine_board_path=engine_board_path,
        statsapi_context_path=statsapi_context_path,
        root=tmp_path,
        run_id="roster_context_replay",
        game_date="2026-05-11",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]

    assert manifest["roster_source_selection"] == "date_matched_source"
    assert manifest["roster_source_dir"].endswith("statsapi_rosters_20260511T213237Z")
    assert manifest["roster_source_is_post_date_identity_fallback"] is False
    assert row["statsapi_person_id"] == 101


def test_roster_context_prefers_date_safe_full_slate_snapshot_for_replay(tmp_path):
    engine_board_path = _write_engine_board_with_date(tmp_path, game_date="2026-05-11")
    statsapi_context_path = _write_statsapi_context(tmp_path)
    _write_rosters(
        tmp_path,
        root_name="statsapi_rosters_bulk",
        file_name="statsapi_rosters_bulk.jsonl",
        snapshot_id="statsapi_rosters_bulk_20260510T190105Z",
        player_name="Sample Hitter",
        person_id=101,
        extra_count=220,
    )
    _write_rosters(
        tmp_path,
        root_name="statsapi_rosters_bulk",
        file_name="statsapi_rosters_bulk.jsonl",
        snapshot_id="statsapi_rosters_bulk_20260516T190105Z",
        player_name="Sample Hitter",
        person_id=999,
        extra_count=220,
    )

    manifest = build_roster_context_artifacts(
        engine_board_path=engine_board_path,
        statsapi_context_path=statsapi_context_path,
        root=tmp_path,
        run_id="roster_context_replay",
        game_date="2026-05-11",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]

    assert manifest["roster_source_selection"] == "latest_on_or_before_date_source"
    assert manifest["roster_source_dir"].endswith("statsapi_rosters_bulk_20260510T190105Z")
    assert manifest["roster_source_is_post_date_identity_fallback"] is False
    assert row["statsapi_person_id"] == 101


def test_roster_context_does_not_use_post_date_roster_without_date_safe_source(tmp_path):
    engine_board_path = _write_engine_board_with_date(tmp_path, game_date="2026-05-11")
    statsapi_context_path = _write_statsapi_context(tmp_path)
    _write_rosters(
        tmp_path,
        root_name="statsapi_rosters_bulk",
        file_name="statsapi_rosters_bulk.jsonl",
        snapshot_id="statsapi_rosters_bulk_20260516T190105Z",
        player_name="Sample Hitter",
        person_id=999,
        extra_count=220,
    )

    manifest = build_roster_context_artifacts(
        engine_board_path=engine_board_path,
        statsapi_context_path=statsapi_context_path,
        root=tmp_path,
        run_id="roster_context_replay",
        game_date="2026-05-11",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]

    assert manifest["roster_source_selection"] == "missing_date_safe_source"
    assert manifest["roster_source_dir"] == ""
    assert manifest["coverage_rate"] == 0.0
    assert row["statsapi_person_id"] == 0


def test_roster_context_uses_prior_gamelog_identity_without_post_date_roster_leakage(tmp_path):
    engine_board_path = _write_engine_board_with_date(tmp_path, game_date="2026-05-11")
    statsapi_context_path = _write_statsapi_context(tmp_path)
    _write_rosters(
        tmp_path,
        root_name="statsapi_rosters_bulk",
        file_name="statsapi_rosters_bulk.jsonl",
        snapshot_id="statsapi_rosters_bulk_20260516T190105Z",
        player_name="Sample Hitter",
        person_id=999,
        extra_count=220,
    )
    _write_prior_gamelog_identity(tmp_path, game_date="2026-05-10", person_id=101)
    _write_prior_gamelog_identity(tmp_path, game_date="2026-05-11", person_id=999)

    manifest = build_roster_context_artifacts(
        engine_board_path=engine_board_path,
        statsapi_context_path=statsapi_context_path,
        root=tmp_path,
        run_id="roster_context_replay",
        game_date="2026-05-11",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]

    assert manifest["roster_source_selection"] == "missing_date_safe_source"
    assert manifest["roster_source_is_post_date_identity_fallback"] is False
    assert manifest["coverage_rate"] == 1.0
    assert row["statsapi_person_id"] == 101
    assert row["statsapi_roster_team_id"] == 141
    assert row["statsapi_player_position"] == "OF"
    assert "no_statsapi_roster_snapshot_available" in row["roster_context_flags"]
    assert "player_name_prior_history_team_id_match" in row["roster_context_flags"]


def _write_engine_board(tmp_path: Path) -> Path:
    return _write_engine_board_with_date(tmp_path, game_date="2026-05-16")


def _write_engine_board_with_date(tmp_path: Path, *, game_date: str) -> Path:
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
                        "game_date": game_date,
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


def _write_statsapi_context(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "mlb" / "features" / "statsapi_context" / "statsapi_run" / "statsapi_context.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "statsapi_run",
                "rows": [
                    {
                        "source_projection_id": "proj_hits",
                        "market": "hits",
                        "line": 1.5,
                        "tier": "STANDARD",
                        "team_id": 141,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_bulk_rosters(tmp_path: Path) -> None:
    _write_rosters(
        tmp_path,
        root_name="statsapi_rosters_bulk",
        file_name="statsapi_rosters_bulk.jsonl",
        snapshot_id="rosters_run",
        player_name="Sample Hitter",
        person_id=101,
    )


def _write_rosters(
    tmp_path: Path,
    *,
    root_name: str,
    file_name: str,
    snapshot_id: str,
    player_name: str,
    person_id: int,
    extra_count: int = 0,
) -> None:
    path = tmp_path / "data" / "mlb" / "staged" / root_name / snapshot_id / file_name
    path.parent.mkdir(parents=True)
    row = {
        "season": 2026,
        "team_id": 141,
        "team_name": "Toronto Blue Jays",
        "team_abbreviation": "TOR",
        "team_short_name": "Toronto",
        "club_name": "Blue Jays",
        "sport_id": 1,
        "level": "MLB",
        "person_id": person_id,
        "player_name": player_name,
        "primary_position": "OF",
        "status": "Active",
        "bats": "L",
        "throws": "R",
    }
    rows = [row]
    for index in range(extra_count):
        rows.append(
            {
                **row,
                "person_id": 100000 + index,
                "player_name": f"Depth Player {index}",
            }
        )
    path.write_text("".join(json.dumps(item) + "\n" for item in rows), encoding="utf-8")


def _write_prior_gamelog_identity(tmp_path: Path, *, game_date: str, person_id: int) -> None:
    path = (
        tmp_path
        / "data"
        / "mlb"
        / "staged"
        / "statsapi_player_gamelogs_bulk"
        / "statsapi_player_gamelogs_bulk_20260511T120000Z"
        / "statsapi_player_gamelogs_bulk.jsonl"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "game_date": game_date,
        "game_pk": int(game_date.replace("-", "")),
        "group": "hitting",
        "person_id": person_id,
        "player_name": "Sample Hitter",
        "player_position": "OF",
        "player_team": "TOR",
        "team_id": 141,
        "team_name": "Toronto Blue Jays",
        "stat": {"plateAppearances": 4},
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row) + "\n")
