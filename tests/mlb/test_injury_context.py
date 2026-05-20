import json
from datetime import date
from pathlib import Path

from mlb.normalizers.cbs_injuries import (
    parse_cbs_mlb_injury_text,
    write_cbs_mlb_injury_backfill,
)
from mlb.runtime.injury_context import build_injury_context_artifacts


def test_injury_context_exact_matches_player_team_with_ascii_normalization(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    _write_injury_snapshot(tmp_path)

    manifest = build_injury_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="injury_context_run",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]

    assert manifest["coverage_rate"] == 1.0
    assert manifest["coverage_by_market"] == {"hits": 1.0}
    assert manifest["injury_status_counts"] == {"Day-To-Day": 1}
    assert row["injury_context_available"] is True
    assert row["injury_status"] == "Day-To-Day"
    assert row["injury_risk_score"] == 0.45
    assert row["injury_context_flags"] == [
        "exact_player_team_injury_match",
        "player_on_injury_report",
        "injury_status_uncertain",
    ]


def test_injury_context_uses_date_safe_snapshot_for_replay(tmp_path):
    engine_board_path = _write_engine_board_with_date(tmp_path, game_date="2026-05-11")
    _write_injury_snapshot(
        tmp_path,
        snapshot_id="espn_injuries_20260511T211042Z",
        report_date="2026-05-11",
        status="Out",
    )
    _write_injury_snapshot(
        tmp_path,
        snapshot_id="espn_injuries_20260516T190105Z",
        report_date="2026-05-16",
        status="Day-To-Day",
    )

    manifest = build_injury_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="injury_context_replay",
        game_date="2026-05-11",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]

    assert manifest["injury_source_selection"] == "date_matched_source"
    assert manifest["injury_source_dir"].endswith("espn_injuries_20260511T211042Z")
    assert row["injury_report_date"] == "2026-05-11"
    assert row["injury_status"] == "Out"


def test_cbs_injury_backfill_writes_date_safe_empty_snapshots(tmp_path):
    source = tmp_path / "MLB Injury.txt"
    source.write_text(
        "\n".join(
            [
                "MLB Injuries",
                "Friday, May 15, 2026",
                "Team\tPlayer\tPosition\tInjury\tInjury Status",
                "team logo",
                "CHW",
                "Austin Hays\tLF\tCalf\tExpected to be out until at least May 17",
                "Sunday, May 17, 2026",
                "Team\tPlayer\tPosition\tInjury\tInjury Status",
                "team logo",
                "BOS",
                "Carlos Narvaez\tC\tFinger\tProbable for May 18",
            ]
        ),
        encoding="utf-8",
    )

    parsed = parse_cbs_mlb_injury_text(source.read_text(encoding="utf-8"))
    assert next(iter(parsed.values()))[0].team == "CWS"
    assert next(iter(parsed.values()))[0].estimated_return == "2026-05-17"

    manifest = write_cbs_mlb_injury_backfill(
        source,
        root=tmp_path,
        start_date=date(2026, 5, 15),
        end_date=date(2026, 5, 17),
    )

    assert manifest["date_count"] == 3
    assert manifest["injury_count"] == 2
    assert manifest["empty_snapshot_count"] == 1
    empty_path = tmp_path / "data" / "mlb" / "staged" / "injuries" / "cbs_injuries_20260516" / "injuries.jsonl"
    assert empty_path.read_text(encoding="utf-8") == ""


def test_injury_context_matches_cbs_team_aliases(tmp_path):
    engine_board_path = _write_engine_board_row(
        tmp_path,
        player_name="Austin Hays",
        player_team="CWS",
        game_date="2026-05-15",
    )
    output_dir = tmp_path / "data" / "mlb" / "staged" / "injuries" / "cbs_injuries_20260515"
    output_dir.mkdir(parents=True)
    row = {
        "source": "cbs_mlb_injuries",
        "report_date": "2026-05-15",
        "team": "CHW",
        "player_id": "",
        "player_name": "Austin Hays",
        "position": "LF",
        "status": "Expected to be out until at least May 17",
        "comment": "Hamstring",
    }
    (output_dir / "injuries.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

    manifest = build_injury_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="cbs_injury_context",
        game_date="2026-05-15",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    assert payload["rows"][0]["injury_context_available"] is True
    assert payload["rows"][0]["injury_context_flags"][0] == "exact_player_team_injury_match"


def test_injury_context_prefers_cbs_snapshot_for_same_date_replay(tmp_path):
    engine_board_path = _write_engine_board_with_date(tmp_path, game_date="2026-05-16")
    _write_injury_snapshot(
        tmp_path,
        snapshot_id="espn_injuries_20260516T092131Z",
        report_date="2026-05-16",
        status="Day-To-Day",
    )
    _write_injury_snapshot(
        tmp_path,
        snapshot_id="cbs_injuries_20260516",
        report_date="2026-05-16",
        status="Expected to be out until at least May 17",
    )

    manifest = build_injury_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="preferred_cbs_injury_context",
        game_date="2026-05-16",
    )

    assert manifest["injury_source_dir"].endswith("cbs_injuries_20260516")
    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    assert payload["rows"][0]["injury_status"] == "Expected to be out until at least May 17"


def _write_engine_board(tmp_path: Path) -> Path:
    return _write_engine_board_with_date(tmp_path, game_date="2026-05-16")


def _write_engine_board_with_date(tmp_path: Path, *, game_date: str) -> Path:
    return _write_engine_board_row(
        tmp_path,
        player_name="Jose Ramirez",
        player_team="CLE",
        game_date=game_date,
    )


def _write_engine_board_row(tmp_path: Path, *, player_name: str, player_team: str, game_date: str) -> Path:
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
                        "player_name": player_name,
                        "player_team": player_team,
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


def _write_injury_snapshot(
    tmp_path: Path,
    *,
    snapshot_id: str = "espn_injuries_20260516",
    report_date: str = "2026-05-16",
    status: str = "Day-To-Day",
) -> Path:
    output_dir = tmp_path / "data" / "mlb" / "staged" / "injuries" / snapshot_id
    output_dir.mkdir(parents=True)
    row = {
        "source": "espn_injuries",
        "report_date": report_date,
        "team": "CLE",
        "player_id": "player1",
        "player_name": "José Ramírez",
        "position": "3B",
        "status": status,
        "description": "Test fixture",
    }
    (output_dir / "injuries.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return output_dir
