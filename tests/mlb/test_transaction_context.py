import json
from pathlib import Path

from mlb.runtime.transaction_context import build_transaction_context_artifacts


def test_transaction_context_matches_recent_callup_by_statsapi_person_id(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    roster_context_path = _write_roster_context(tmp_path)
    staged_dir = tmp_path / "data" / "mlb" / "staged" / "statsapi_transactions" / "transaction_run"
    staged_dir.mkdir(parents=True)
    (staged_dir / "statsapi_transactions.jsonl").write_text(
        json.dumps(
            {
                "transaction_id": 1,
                "person_id": 101,
                "player_name": "Sample Hitter",
                "date": "2026-05-10",
                "type_code": "CU",
                "type_desc": "Recalled",
                "description": "Boston Red Sox recalled Sample Hitter from Worcester Red Sox.",
                "is_callup": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = build_transaction_context_artifacts(
        engine_board_path=engine_board_path,
        roster_context_path=roster_context_path,
        root=tmp_path,
        run_id="transaction_context_run",
        game_date="2026-05-11",
    )

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]
    assert manifest["source_available_rate"] == 1.0
    assert manifest["recent_transaction_rate"] == 1.0
    assert row["transaction_context_available"] is True
    assert row["recent_callup_count"] == 1
    assert row["last_transaction_type_code"] == "CU"
    assert "recent_callup_or_contract_selected" in row["transaction_context_flags"]


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
