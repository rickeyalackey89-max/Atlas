import csv
import json
from pathlib import Path

from mlb.runtime.advanced_context import (
    build_advanced_context_artifacts,
    prepare_advanced_profile_artifacts,
)


def test_advanced_profiles_and_context_cover_matching_props(tmp_path):
    source_path = _write_profile_source(tmp_path)
    engine_board_path = _write_engine_board(tmp_path)

    profile_manifest = prepare_advanced_profile_artifacts(
        source_path=source_path,
        root=tmp_path,
        run_id="profiles_run",
    )
    context_manifest = build_advanced_context_artifacts(
        engine_board_path=engine_board_path,
        profiles_path=Path(profile_manifest["json_path"]),
        root=tmp_path,
        run_id="context_run",
    )

    assert profile_manifest["row_count"] == 1
    assert context_manifest["row_count"] == 2
    assert context_manifest["coverage_rate"] == 0.5
    assert context_manifest["profile_source_row_count"] == 1

    payload = json.loads(Path(context_manifest["json_path"]).read_text(encoding="utf-8"))
    matched = next(row for row in payload["rows"] if row["source_projection_id"] == "proj_hitter")
    missing = next(row for row in payload["rows"] if row["source_projection_id"] == "proj_missing")

    assert matched["advanced_context_available"] is True
    assert matched["advanced_profile_match_type"] == "exact_player_team_profile_match"
    assert matched["advanced_hit_context_score"] > 0.0
    assert matched["advanced_power_context_score"] > 0.0
    assert matched["advanced_sample_confidence"] > 0.0
    assert "advanced_profile_context_available" in matched["advanced_context_flags"]
    assert missing["advanced_context_available"] is False
    assert missing["advanced_context_score"] == 0.0
    assert missing["advanced_context_flags"] == ["missing_advanced_profile"]


def test_advanced_context_matches_accented_profile_names(tmp_path):
    profiles_path = tmp_path / "data" / "mlb" / "staged" / "advanced_profiles" / "stale_key_profiles" / "advanced_profiles.json"
    profiles_path.parent.mkdir(parents=True)
    profiles_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "player_name": "Jose Ramirez",
                        "player_name_key": "stalelegacykey",
                        "player_team": "CLE",
                        "profile_role": "hitter",
                        "sample_pa": 180,
                        "xwoba": 0.390,
                        "xba": 0.290,
                        "xslg": 0.520,
                        "iso": 0.230,
                        "barrel_rate": 0.125,
                        "hard_hit_rate": 0.480,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    engine_board_path = _write_engine_board_with_rows(
        tmp_path,
        [
            _row("proj_accented", "José Ramírez Jr.", "CLE"),
        ],
    )

    context_manifest = build_advanced_context_artifacts(
        engine_board_path=engine_board_path,
        profiles_path=profiles_path,
        root=tmp_path,
        run_id="accent_context_run",
    )

    payload = json.loads(Path(context_manifest["json_path"]).read_text(encoding="utf-8"))
    row = payload["rows"][0]

    assert context_manifest["coverage_rate"] == 1.0
    assert row["advanced_context_available"] is True
    assert row["advanced_profile_match_type"] == "exact_player_team_profile_match"


def test_advanced_context_missing_profiles_remains_neutral(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)

    manifest = build_advanced_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="missing_profiles_context",
    )

    assert manifest["coverage_rate"] == 0.0
    assert manifest["profile_source_row_count"] == 0
    assert manifest["advanced_context_flag_counts"] == {"missing_advanced_profile": 2}

    payload = json.loads(Path(manifest["json_path"]).read_text(encoding="utf-8"))
    assert all(row["advanced_context_available"] is False for row in payload["rows"])
    assert all(row["advanced_target_shift"] == 0.0 for row in payload["rows"] if "advanced_target_shift" in row)


def test_advanced_context_does_not_use_future_profile_snapshot_for_replay(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    future_dir = tmp_path / "data" / "mlb" / "staged" / "advanced_profiles" / "advanced_profiles_20260516"
    future_dir.mkdir(parents=True)
    future_profile = {
        "rows": [
            {
                "player_name": "Sample Hitter",
                "player_name_key": "samplehitter",
                "player_team": "DET",
                "profile_role": "hitter",
                "sample_pa": 180,
                "xwoba": 0.390,
            }
        ]
    }
    (future_dir / "advanced_profiles.json").write_text(json.dumps(future_profile), encoding="utf-8")

    manifest = build_advanced_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="future_profiles_context",
        game_date="2026-05-11",
    )

    assert manifest["profiles_path"] == ""
    assert manifest["coverage_rate"] == 0.0


def test_advanced_context_prefers_asof_profile_snapshot_for_same_date_replay(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    live_dir = tmp_path / "data" / "mlb" / "staged" / "advanced_profiles" / "baseball_savant_context_20260516T234440Z_advanced_profiles"
    live_dir.mkdir(parents=True)
    (live_dir / "advanced_profiles.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "player_name": "Sample Hitter",
                        "player_name_key": "samplehitter",
                        "player_team": "DET",
                        "profile_role": "hitter",
                        "sample_pa": 180,
                        "xwoba": 0.100,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    asof_dir = tmp_path / "data" / "mlb" / "staged" / "advanced_profiles" / "baseball_savant_asof_20260516_advanced_profiles"
    asof_dir.mkdir(parents=True)
    (asof_dir / "advanced_profiles.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "player_name": "Sample Hitter",
                        "player_name_key": "samplehitter",
                        "player_team": "DET",
                        "profile_role": "hitter",
                        "sample_pa": 180,
                        "xwoba": 0.390,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    manifest = build_advanced_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="asof_profiles_context",
        game_date="2026-05-16",
    )

    assert manifest["profiles_path"].endswith(
        "baseball_savant_asof_20260516_advanced_profiles\\advanced_profiles.json"
    ) or manifest["profiles_path"].endswith(
        "baseball_savant_asof_20260516_advanced_profiles/advanced_profiles.json"
    )


def _write_profile_source(tmp_path: Path, *, player_name: str = "Sample Hitter", team: str = "DET") -> Path:
    path = tmp_path / "source" / "advanced_profiles.csv"
    path.parent.mkdir(parents=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "player_name",
                "team",
                "sample_pa",
                "xwoba",
                "xba",
                "xslg",
                "iso",
                "barrel_rate",
                "hard_hit_rate",
                "k_rate",
                "bb_rate",
                "whiff_rate",
                "chase_rate",
                "contact_rate",
                "source",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "player_name": player_name,
                "team": team,
                "sample_pa": "180",
                "xwoba": "0.390",
                "xba": "0.290",
                "xslg": "0.520",
                "iso": "0.230",
                "barrel_rate": "12.5",
                "hard_hit_rate": "48.0",
                "k_rate": "18.0",
                "bb_rate": "10.5",
                "whiff_rate": "20.0",
                "chase_rate": "26.0",
                "contact_rate": "80.0",
                "source": "fixture",
            }
        )
    return path


def _write_engine_board(tmp_path: Path) -> Path:
    return _write_engine_board_with_rows(
        tmp_path,
        [
            _row("proj_hitter", "Sample Hitter", "DET"),
            _row("proj_missing", "Missing Hitter", "CLE"),
        ],
    )


def _write_engine_board_with_rows(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "data" / "mlb" / "staged" / "engine_board" / "board_run" / "engine_board.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "board_run",
                "rows": rows,
            }
        ),
        encoding="utf-8",
    )
    return path


def _row(projection_id: str, player_name: str, player_team: str) -> dict:
    return {
        "source_projection_id": projection_id,
        "event_id": "game1",
        "player_id": projection_id,
        "player_name": player_name,
        "player_team": player_team,
        "opponent": "BOS",
        "game_date": "2026-05-16",
        "start_time_utc": "2026-05-16T22:10:00Z",
        "player_position": "OF",
        "market": "hits",
        "source_market": "Hits",
        "line": 0.5,
        "tier": "STANDARD",
        "status": "pre_game",
    }
