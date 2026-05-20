import csv
import json
from pathlib import Path

from mlb.cli import main
from mlb.matchups.ballpark_matrix import build_ballpark_profiles, ballpark_profiles_by_key
from mlb.matchups.bullpen_matrix import build_bullpen_context
from mlb.matchups.environment_matrix import build_environment_context
from mlb.matchups.hitter_context import build_hitter_matchup_context
from mlb.matchups.pitcher_prop_context import build_pitcher_prop_context
from mlb.matchups.lineup_matrix import build_lineup_context
from mlb.matchups.pitcher_matrix import build_pitcher_context
from mlb.matchups.schemas import HITTER_MATCHUP_CONTEXT_COLUMNS, MATCHUP_MATRIX_VERSION
from mlb.matchups.umpire_matrix import (
    build_umpire_profiles,
    build_umpire_profiles_from_scorecards,
    umpire_profiles_by_name,
)
from mlb.runtime.matchups import _weather_scores, build_matchup_context_artifacts
from mlb.runtime.ballparks import prepare_ballpark_profile_artifacts
from mlb.runtime.umpires import prepare_umpire_profile_artifacts


def test_hitter_matchup_context_joins_component_matrices():
    prop_rows = [
        {
            "run_id": "run-1",
            "source_projection_id": "pp-1",
            "game_id": "game-1",
            "game_date": "2026-05-15",
            "player_id": "batter-1",
            "player_name": "Test Hitter",
            "team": "DET",
            "opponent": "CLE",
            "market": "total_bases",
            "line": 1.5,
            "tier": "STANDARD",
            "direction": "over",
        }
    ]
    lineups = build_lineup_context(
        [
            {
                "game_id": "game-1",
                "player_id": "batter-1",
                "player_name": "Test Hitter",
                "team": "DET",
                "opponent": "CLE",
                "batting_order_slot": 2,
                "lineup_probability": 1.0,
                "projected_plate_appearances": 4.7,
                "protection_score": 0.2,
            }
        ]
    )
    pitchers = build_pitcher_context(
        [
            {
                "game_id": "game-1",
                "hitter_team": "DET",
                "opponent": "CLE",
                "starter_pitcher_id": "pitcher-1",
                "starter_hand": "R",
                "strikeout_pressure_score": -0.2,
                "contact_allow_score": 0.3,
                "power_allow_score": 0.4,
            }
        ]
    )
    bullpens = build_bullpen_context(
        [
            {
                "game_id": "game-1",
                "hitter_team": "DET",
                "opponent": "CLE",
                "bullpen_fatigue_score": 0.3,
                "bullpen_quality_score": -0.1,
                "late_game_run_score": 0.2,
            }
        ]
    )
    environments = build_environment_context(
        [
            {
                "game_id": "game-1",
                "game_date": "2026-05-15",
                "team": "DET",
                "opponent": "CLE",
                "park_run_factor": 1.05,
                "park_hr_factor": 1.10,
                "park_hit_factor": 1.04,
                "park_extra_base_factor": 1.08,
                "park_factor_confidence": 1.0,
                "weather_run_score": 0.05,
                "home_plate_umpire": "Scott Barry",
                "umpire_era": 4.17,
                "umpire_rating": "Extreme Hitters",
                "umpire_run_score": 0.10,
                "umpire_confidence": 1.0,
            }
        ]
    )

    rows = build_hitter_matchup_context(
        prop_rows,
        lineup_contexts=lineups,
        pitcher_contexts=pitchers,
        bullpen_contexts=bullpens,
        environment_contexts=environments,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.matchup_matrix_version == MATCHUP_MATRIX_VERSION
    assert row.missing_context_flags == ()
    assert row.batting_order_slot == 2
    assert row.matchup_confidence > 0.0
    assert row.matchup_composite_score > 0.0
    assert row.home_plate_umpire == "Scott Barry"
    assert row.umpire_run_score == 0.10
    assert row.park_hit_factor == 1.04
    assert row.park_extra_base_factor == 1.08


def test_umpire_profile_matrix_normalizes_rating_and_era():
    profiles = build_umpire_profiles(
        [
            {"Umpire": "Mike Estabrook", "ERA": "3.93", "Rating": "EXTREME PITCHERS"},
            {"Umpire": "Scott Barry", "ERA": "4.17", "Rating": "EXTREME HITTERS"},
            {"Umpire": "Neutral Ump", "ERA": "4.05", "Rating": "NEUTRAL"},
        ],
        source="test",
    )
    by_name = umpire_profiles_by_name(profiles)

    assert by_name["mike estabrook"].umpire_run_score < 0.0
    assert by_name["scott barry"].umpire_run_score > 0.0
    assert by_name["neutral ump"].confidence == 1.0
    assert by_name["scott barry"].source == "test"


def test_umpire_profile_matrix_aggregates_umpscorecards_rows():
    profiles = build_umpire_profiles_from_scorecards(
        [
            {
                "umpire": "Hitter Ump",
                "called_pitches": 150,
                "fully_valid": True,
                "failed": False,
                "has_basic_game_data": True,
                "home_batter_impact": 0.62,
                "away_batter_impact": 0.46,
                "total_run_impact": 1.85,
                "accuracy_above_x": -0.5,
            },
            {
                "umpire": "Hitter Ump",
                "called_pitches": 160,
                "fully_valid": True,
                "failed": False,
                "has_basic_game_data": True,
                "home_batter_impact": 0.50,
                "away_batter_impact": 0.30,
                "total_run_impact": 1.70,
                "accuracy_above_x": 0.3,
            },
            {
                "umpire": "Pitcher Ump",
                "called_pitches": 170,
                "fully_valid": True,
                "failed": False,
                "has_basic_game_data": True,
                "home_batter_impact": -0.80,
                "away_batter_impact": -0.60,
                "total_run_impact": 1.65,
                "accuracy_above_x": 1.1,
            },
        ],
        source="umpscorecards_test",
    )
    by_name = umpire_profiles_by_name(profiles)

    assert by_name["hitter ump"].umpire_run_score > 0.0
    assert by_name["pitcher ump"].umpire_run_score < 0.0
    assert by_name["hitter ump"].source == "umpscorecards_test"
    assert "umpscorecards_profile" in by_name["hitter ump"].flags
    assert "thin_umpire_scorecard_sample" in by_name["pitcher ump"].flags


def test_ballpark_profile_matrix_normalizes_100_scale_factors():
    profiles = build_ballpark_profiles(
        [
            {
                "venue_id": "10",
                "venue_name": "Example Park",
                "team": "DET",
                "Runs": "106",
                "HR": "112",
                "Hits": "103",
                "2B": "108",
                "3B": "96",
            }
        ],
        source="test",
    )
    by_key = ballpark_profiles_by_key(profiles)

    assert by_key["10"].park_run_factor == 1.06
    assert by_key["example_park"].park_hr_factor == 1.12
    assert by_key["det"].park_hit_factor == 1.03
    assert by_key["det"].park_extra_base_factor == 1.05
    assert by_key["det"].park_context_score > 0.0


def test_hitter_matchup_context_marks_missing_context():
    rows = build_hitter_matchup_context(
        [
            {
                "game_id": "game-1",
                "player_id": "batter-1",
                "team": "DET",
                "market": "hits",
                "line": 0.5,
            }
        ]
    )

    assert rows[0].missing_context_flags == (
        "missing_lineup_context",
        "missing_pitcher_context",
        "missing_bullpen_context",
        "missing_environment_context",
    )
    assert rows[0].matchup_confidence == 0.0


def test_hitter_matchup_context_does_not_treat_enrichment_gap_as_missing_pitcher():
    pitchers = build_pitcher_context(
        [
            {
                "game_id": "game-1",
                "hitter_team": "DET",
                "opponent": "CLE",
                "starter_pitcher_id": "pitcher-1",
                "starter_pitcher_name": "Example Starter",
                "strikeout_pressure_score": 0.1,
                "flags": ["advanced_pitcher_profile_applied", "missing_player_team"],
            }
        ]
    )

    rows = build_hitter_matchup_context(
        [
            {
                "game_id": "game-1",
                "player_id": "batter-1",
                "team": "DET",
                "opponent": "CLE",
                "market": "hits",
                "line": 0.5,
            }
        ],
        pitcher_contexts=pitchers,
    )

    assert "missing_pitcher_context" not in rows[0].missing_context_flags
    assert "missing_lineup_context" in rows[0].missing_context_flags


def test_pitcher_prop_context_uses_rotowire_starter_and_environment():
    rows = build_pitcher_prop_context(
        [
            {
                "source_projection_id": "pitcher-proj-1",
                "game_date": "2026-05-15",
                "player_id": "pp-pitcher-1",
                "player_name": "Example Starter",
                "player_team": "CLE",
                "opponent": "DET",
                "market": "pitcher_strikeouts",
                "line": 5.5,
                "tier": "STANDARD",
                "direction": "over",
            }
        ],
        pitcher_rows=[
            {
                "game_date": "2026-05-15",
                "team_abbr": "CLE",
                "opponent_abbr": "DET",
                "rotowire_player_id": "starter-1",
                "pitcher_name": "Example Starter",
                "throws": "R",
                "pitcher_stats": "2-3 3.20 ERA",
            }
        ],
        bullpen_rows=[
            {
                "team_abbr": "CLE",
                "bullpen_fatigue_score": 0.25,
            }
        ],
        environment_rows=[
            {
                "game_id": "2026-05-15|CLE|DET",
                "game_date": "2026-05-15",
                "team": "CLE",
                "opponent": "DET",
                "environment_score": -0.04,
                "home_plate_umpire": "Mike Estabrook",
                "umpire_era": 3.93,
                "umpire_rating": "Extreme Pitchers",
                "umpire_run_score": -0.10,
                "confidence": 0.75,
            }
        ],
        run_id="pitcher_context_test",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.starter_pitcher_name == "Example Starter"
    assert row.starter_hand == "R"
    assert row.starter_era == 3.2
    assert row.pitcher_prop_confidence > 0.0
    assert row.pitcher_prop_composite_score > 0.0
    assert "pitcher_prop_era_only_context" in row.missing_context_flags
    assert row.home_plate_umpire == "Mike Estabrook"


def test_pitcher_prop_context_uses_advanced_pitcher_scores():
    rows = build_pitcher_prop_context(
        [
            {
                "source_projection_id": "pitcher-proj-advanced",
                "game_date": "2026-05-15",
                "player_id": "pp-pitcher-1",
                "player_name": "Example Starter",
                "player_team": "CLE",
                "opponent": "DET",
                "market": "pitcher_strikeouts",
                "line": 5.5,
                "tier": "STANDARD",
                "direction": "over",
            }
        ],
        pitcher_rows=[
            {
                "game_date": "2026-05-15",
                "team_abbr": "CLE",
                "opponent_abbr": "DET",
                "starter_pitcher_id": "starter-1",
                "starter_pitcher_name": "Example Starter",
                "pitcher_name": "Example Starter",
                "throws": "R",
                "starter_era": 3.2,
                "strikeout_pressure_score": 0.44,
                "contact_allow_score": -0.30,
                "power_allow_score": -0.22,
                "walk_allow_score": -0.08,
                "confidence": 0.76,
                "flags": ["advanced_pitcher_profile_applied"],
            }
        ],
        run_id="pitcher_context_advanced_test",
    )

    row = rows[0]
    assert row.pitcher_prop_confidence > 0.6
    assert row.pitcher_prop_composite_score > 0.2
    assert "advanced_pitcher_prop_context" in row.missing_context_flags
    assert "pitcher_prop_era_only_context" not in row.missing_context_flags


def test_pitcher_prop_context_uses_opponent_lineup_and_history():
    rows = build_pitcher_prop_context(
        [
            {
                "source_projection_id": "pitcher-proj-v1",
                "game_date": "2026-05-15",
                "player_id": "pp-pitcher-1",
                "player_name": "Example Starter",
                "player_team": "CLE",
                "opponent": "DET",
                "market": "pitcher_strikeouts",
                "line": 5.5,
                "tier": "STANDARD",
                "direction": "over",
            }
        ],
        pitcher_rows=[
            {
                "game_date": "2026-05-15",
                "team_abbr": "CLE",
                "opponent_abbr": "DET",
                "pitcher_name": "Example Starter",
                "throws": "R",
                "starter_era": 3.2,
                "strikeout_pressure_score": 0.25,
                "contact_allow_score": -0.12,
                "power_allow_score": -0.10,
                "walk_allow_score": -0.03,
                "confidence": 0.72,
                "flags": ["advanced_pitcher_profile_applied"],
            }
        ],
        lineup_rows=[
            {
                "game_id": "2026-05-15|DET|CLE",
                "game_date": "2026-05-15",
                "player_name": "Whiff Leadoff",
                "team": "DET",
                "opponent": "CLE",
                "batting_order_slot": 1,
                "lineup_probability": 1.0,
                "projected_plate_appearances": 4.8,
            },
            {
                "game_id": "2026-05-15|DET|CLE",
                "game_date": "2026-05-15",
                "player_name": "Power Cleanup",
                "team": "DET",
                "opponent": "CLE",
                "batting_order_slot": 4,
                "lineup_probability": 1.0,
                "projected_plate_appearances": 4.4,
            },
        ],
        player_history_rows=[
            {
                "source_projection_id": "pitcher-proj-v1",
                "game_date": "2026-05-15",
                "player_name": "Example Starter",
                "player_team": "CLE",
                "market": "pitcher_strikeouts",
                "line": 5.5,
                "tier": "STANDARD",
                "player_history_context_available": True,
                "history_strikeouts_per_pa_14d": 0.32,
                "history_hits_per_pa_14d": 0.20,
                "history_walks_per_pa_14d": 0.05,
                "history_context_confidence": 0.70,
            },
            {
                "game_date": "2026-05-15",
                "player_name": "Whiff Leadoff",
                "player_team": "DET",
                "market": "hits",
                "player_history_context_available": True,
                "history_strikeouts_per_pa_14d": 0.34,
                "history_hits_per_pa_14d": 0.20,
                "history_total_bases_per_pa_14d": 0.35,
                "history_walks_per_pa_14d": 0.08,
            },
        ],
        advanced_profile_rows=[
            {
                "player_name": "Power Cleanup",
                "player_team": "DET",
                "profile_role": "hitter",
                "k_rate": 0.31,
                "whiff_rate": 0.34,
                "contact_rate": 0.70,
                "xwoba": 0.350,
                "xba": 0.255,
                "xslg": 0.490,
                "barrel_rate": 0.11,
                "hard_hit_rate": 0.44,
                "bb_rate": 0.11,
            }
        ],
        run_id="pitcher_context_v1_test",
    )

    row = rows[0]
    assert row.opponent_lineup_confidence > 0.0
    assert row.opponent_confirmed_batters == 2
    assert row.opponent_k_context_score > 0.0
    assert row.pitcher_history_k_score > 0.0
    assert row.strikeout_context_score > 0.25
    assert "pitcher_prop_opponent_lineup_context" in row.missing_context_flags
    assert "pitcher_prop_history_context" in row.missing_context_flags


def test_pitcher_prop_context_canonicalizes_team_aliases():
    rows = build_pitcher_prop_context(
        [
            {
                "source_projection_id": "pitcher-proj-az",
                "game_date": "2026-05-16",
                "player_id": "pp-pitcher-az",
                "player_name": "Alias Starter",
                "player_team": "AZ",
                "opponent": "COL",
                "market": "pitching_outs",
                "line": 17.5,
                "tier": "STANDARD",
                "direction": "over",
            }
        ],
        pitcher_rows=[
            {
                "game_date": "2026-05-16",
                "team_abbr": "ARI",
                "opponent_abbr": "COL",
                "rotowire_player_id": "starter-az",
                "pitcher_name": "Alias Starter",
                "throws": "R",
                "pitcher_stats": "3-1 3.40 ERA",
            }
        ],
        run_id="pitcher_alias_test",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.team == "AZ"
    assert row.starter_pitcher_name == "Alias Starter"
    assert "missing_pitcher_prop_context" not in row.missing_context_flags


def test_matchup_artifact_writer_emits_contract_outputs(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)

    manifest = build_matchup_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="matchup_run",
        game_date="2026-05-15",
    )

    assert manifest["run_id"] == "matchup_run"
    assert manifest["source_run_id"] == "board_run"
    assert manifest["source_row_count"] == 1
    assert manifest["row_count"] == 2
    assert manifest["directions"] == ["over", "under"]
    assert manifest["columns"] == list(HITTER_MATCHUP_CONTEXT_COLUMNS)
    assert Path(manifest["csv_path"]).exists()
    assert Path(manifest["json_path"]).exists()
    assert Path(manifest["latest_manifest_path"]).exists()

    with Path(manifest["csv_path"]).open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    assert [row["direction"] for row in rows] == ["over", "under"]
    assert rows[0]["team"] == "DET"
    assert json.loads(rows[0]["missing_context_flags"]) == [
        "missing_lineup_context",
        "missing_pitcher_context",
        "missing_bullpen_context",
        "missing_environment_context",
    ]


def test_matchup_artifact_writer_joins_latest_rotowire_context(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    _write_rotowire_context(tmp_path)
    _write_umpire_profiles(tmp_path)
    _write_ballpark_profiles(tmp_path)

    manifest = build_matchup_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="rotowire_matchup_run",
        game_date="2026-05-15",
    )

    with Path(manifest["json_path"]).open(encoding="utf-8") as file:
        payload = json.load(file)
    by_projection = {row["source_projection_id"]: row for row in payload["rows"]}

    row = by_projection["proj1"]
    assert row["batting_order_slot"] == 2
    assert row["lineup_score"] > 0.0
    assert row["starter_matchup_score"] > 0.0
    assert row["environment_score"] > 0.0
    assert row["matchup_composite_score"] > 0.0
    assert row["matchup_confidence"] > 0.0
    assert row["home_plate_umpire"] == "Scott Barry"
    assert row["park_run_factor"] == 1.06
    assert row["missing_context_flags"] == ["missing_bullpen_context"]
    assert manifest["component_sources"]["lineup"].endswith("batting_orders.jsonl")
    assert manifest["missing_context_counts"] == {"missing_bullpen_context": 2}


def test_matchup_artifact_writer_uses_rotowire_bullpen_context(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    rotowire_dir = _write_rotowire_context(tmp_path)
    (rotowire_dir / "bullpens.jsonl").write_text(
        json.dumps(
            {
                "game_date": "2026-05-15",
                "team_abbr": "CLE",
                "bullpen_fatigue_score": 0.40,
                "bullpen_quality_score": -0.10,
                "late_game_run_score": 0.20,
                "handedness_balance_score": 0.0,
                "confidence": 0.65,
                "flags": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = build_matchup_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="rotowire_bullpen_matchup_run",
        game_date="2026-05-15",
    )

    with Path(manifest["json_path"]).open(encoding="utf-8") as file:
        payload = json.load(file)

    row = payload["rows"][0]
    assert row["bullpen_matchup_score"] > 0.0
    assert "missing_bullpen_context" not in row["missing_context_flags"]
    assert manifest["component_sources"]["bullpen"].endswith("bullpens.jsonl")
    assert manifest["missing_context_counts"] == {}


def test_matchup_artifact_writer_applies_staged_wind_factors(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    _write_rotowire_context(tmp_path)
    _write_wind_factors(tmp_path)

    manifest = build_matchup_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="wind_factor_matchup_run",
        game_date="2026-05-15",
    )

    with Path(manifest["json_path"]).open(encoding="utf-8") as file:
        payload = json.load(file)

    row = payload["rows"][0]
    assert row["environment_score"] > 0.12
    assert manifest["component_sources"]["wind_factors"].replace("\\", "/").endswith("wind_factors/latest.json")


def test_matchup_artifact_writer_does_not_use_future_ballpark_profiles_for_replay(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    _write_rotowire_context(tmp_path)
    _write_ballpark_profiles(tmp_path, run_id="ballparks_20260518")

    manifest = build_matchup_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="future_ballpark_guard_matchup_run",
        game_date="2026-05-15",
    )

    assert manifest["component_sources"]["ballpark"] == "missing"


def test_matchup_artifact_writer_blocks_espn_postgame_backfill_context(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    _write_espn_game_context(tmp_path)

    manifest = build_matchup_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="espn_backfill_matchup_run",
        game_date="2026-05-15",
    )

    with Path(manifest["json_path"]).open(encoding="utf-8") as file:
        payload = json.load(file)

    row = payload["rows"][0]
    assert manifest["component_sources"]["lineup"] == "missing_rotowire_context"
    assert manifest["component_sources"]["pitcher"] == "missing_rotowire_context"
    assert manifest["component_sources"]["environment"] == "missing_rotowire_context"
    assert row["batting_order_slot"] is None
    assert row["starter_matchup_score"] == 0.0
    assert row["home_plate_umpire"] == ""
    assert "missing_lineup_context" in row["missing_context_flags"]
    assert "missing_pitcher_context" in row["missing_context_flags"]


def test_matchup_artifact_writer_uses_baseball_reference_reconstructed_pregame_lineup(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    _write_baseball_reference_context(tmp_path)

    manifest = build_matchup_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="baseball_reference_reconstructed_matchup_run",
        game_date="2026-05-15",
    )

    with Path(manifest["json_path"]).open(encoding="utf-8") as file:
        payload = json.load(file)

    row = payload["rows"][0]
    assert "baseball_reference_boxscore_context" in manifest["component_sources"]["lineup"]
    assert "baseball_reference_boxscore_context" in manifest["component_sources"]["pitcher"]
    assert manifest["component_sources"]["context_source"] == "baseball_reference_boxscore_context"
    assert manifest["component_sources"]["reconstructed_pregame_lineup"] == "baseball_reference_boxscore_context"
    assert manifest["reconstructed_pregame_lineup_context"] is True
    assert row["batting_order_slot"] == 2
    assert row["starter_matchup_score"] > 0.0
    assert row["contact_context_score"] > 0.0
    assert "missing_lineup_context" not in row["missing_context_flags"]
    assert "missing_pitcher_context" not in row["missing_context_flags"]


def test_matchup_artifact_writer_uses_covers_weather_for_environment(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    _write_covers_weather_context(tmp_path)

    manifest = build_matchup_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="covers_weather_matchup_run",
        game_date="2026-05-15",
    )

    with Path(manifest["json_path"]).open(encoding="utf-8") as file:
        payload = json.load(file)

    row = payload["rows"][0]
    assert "covers_weather" in manifest["component_sources"]["environment"]
    assert row["environment_score"] > 0.0
    assert "missing_environment_context" not in row["missing_context_flags"]
    assert "missing_lineup_context" in row["missing_context_flags"]
    assert manifest["component_sources"]["context_source"] == "covers_weather"


def test_matchup_artifact_writer_maps_compass_wind_through_park_orientation(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    _write_covers_weather_context(tmp_path, wind_direction="S")
    _write_wind_factors(tmp_path)

    manifest = build_matchup_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="covers_weather_orientation_run",
        game_date="2026-05-15",
    )

    with Path(manifest["json_path"]).open(encoding="utf-8") as file:
        payload = json.load(file)

    row = payload["rows"][0]
    wind_factors = json.loads((tmp_path / "data" / "mlb" / "staged" / "wind_factors" / "latest.json").read_text())
    weather = _weather_scores("Weather: clear day 82° Wind 14 mph S", home_team="CLE", wind_factors=wind_factors)
    assert row["environment_score"] > 0.12
    assert "park_orientation_wind_direction_applied" in weather["flags"]
    assert "park_wind_factor_applied" in weather["flags"]


def test_matchup_artifact_writer_canonicalizes_cross_source_team_aliases(tmp_path):
    engine_board_dir = tmp_path / "data" / "mlb" / "staged" / "engine_board" / "alias_board"
    engine_board_dir.mkdir(parents=True)
    engine_board_path = engine_board_dir / "engine_board.json"
    engine_board_path.write_text(
        json.dumps(
            {
                "run_id": "alias_board",
                "source": "prizepicks",
                "snapshot_id": "snap-alias",
                "row_count": 1,
                "rows": [
                    {
                        **_engine_row(projection_id="proj-az", game_date="2026-05-16"),
                        "player_team": "AZ",
                        "opponent": "COL",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "data" / "mlb" / "staged" / "rotowire_context" / "rotowire_mlb_context_20260516T120000Z"
    output_dir.mkdir(parents=True)
    (output_dir / "normalize_manifest.json").write_text(
        json.dumps({"source": "rotowire_mlb_context", "game_date": "2026-05-16"}),
        encoding="utf-8",
    )
    (output_dir / "batting_orders.jsonl").write_text(
        json.dumps(
            {
                "game_date": "2026-05-16",
                "team_abbr": "ARI",
                "opponent_abbr": "COL",
                "batting_order": 2,
                "player_name": "Sample Player",
                "rotowire_player_id": "rotowire-sample",
                "lineup_status": "confirmed",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "pitchers.jsonl").write_text(
        json.dumps(
            {
                "game_date": "2026-05-16",
                "team_abbr": "COL",
                "opponent_abbr": "ARI",
                "rotowire_player_id": "starter-col",
                "pitcher_name": "Colorado Starter",
                "throws": "R",
                "pitcher_stats": "2-3 5.40 ERA",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "environment.jsonl").write_text(
        json.dumps(
            {
                "game_date": "2026-05-16",
                "away_team_abbr": "ARI",
                "home_team_abbr": "COL",
                "weather_text": "Weather: 82° Wind 14 mph OUT",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = build_matchup_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="alias_matchup_run",
        game_date="2026-05-16",
    )

    with Path(manifest["json_path"]).open(encoding="utf-8") as file:
        payload = json.load(file)

    row = payload["rows"][0]
    assert row["team"] == "AZ"
    assert row["opponent"] == "COL"
    assert row["batting_order_slot"] == 2
    assert row["starter_matchup_score"] > 0.0
    assert row["environment_score"] > 0.0
    assert row["missing_context_flags"] == ["missing_bullpen_context"]


def test_matchup_artifact_writer_uses_savant_pitcher_profiles_when_available(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    _write_rotowire_context(tmp_path)
    _write_advanced_pitcher_profiles(tmp_path)

    manifest = build_matchup_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="advanced_pitcher_matchup_run",
        game_date="2026-05-15",
    )

    with Path(manifest["json_path"]).open(encoding="utf-8") as file:
        payload = json.load(file)

    row = payload["rows"][0]
    assert row["starter_matchup_score"] < 0.0
    assert row["contact_context_score"] < 0.0
    assert row["power_context_score"] < 0.0
    assert "advanced_profiles_20260515" in manifest["component_sources"]["advanced_pitcher"]


def test_matchup_artifact_writer_does_not_use_wrong_date_rotowire_context(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    _write_rotowire_context(tmp_path)

    manifest = build_matchup_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="date_mismatch_matchup_run",
        game_date="2026-05-16",
    )

    with Path(manifest["json_path"]).open(encoding="utf-8") as file:
        payload = json.load(file)

    assert manifest["component_sources"]["lineup"] == "missing_rotowire_context"
    assert manifest["source_row_count"] == 1
    assert payload["rows"][0]["source_projection_id"] == "proj2"
    assert payload["rows"][0]["missing_context_flags"] == [
        "missing_lineup_context",
        "missing_pitcher_context",
        "missing_bullpen_context",
        "missing_environment_context",
    ]


def test_matchup_artifact_writer_uses_only_matching_rotowire_dates_for_mixed_board(tmp_path):
    engine_board_path = _write_engine_board(tmp_path)
    _write_rotowire_context(tmp_path)
    _write_umpire_profiles(tmp_path)
    _write_ballpark_profiles(tmp_path)

    manifest = build_matchup_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="mixed_date_matchup_run",
    )

    with Path(manifest["json_path"]).open(encoding="utf-8") as file:
        payload = json.load(file)

    rows = {row["source_projection_id"]: row for row in payload["rows"] if row["direction"] == "over"}
    assert rows["proj1"]["lineup_score"] > 0.0
    assert rows["proj1"]["starter_matchup_score"] > 0.0
    assert rows["proj1"]["environment_score"] > 0.0
    assert rows["proj2"]["missing_context_flags"] == [
        "missing_lineup_context",
        "missing_pitcher_context",
        "missing_bullpen_context",
        "missing_environment_context",
    ]


def test_matchup_artifact_writer_allows_after_midnight_context_before_first_pitch(tmp_path):
    engine_board_path = _write_engine_board_with_row(
        tmp_path,
        {
            **_engine_row(projection_id="proj_late", game_date="2026-05-15"),
            "start_time_utc": "2026-05-16T02:10:00Z",
        },
    )
    _write_rotowire_context_snapshot(
        tmp_path,
        run_id="rotowire_mlb_context_20260516T010000Z",
        snapshot_id="rotowire_mlb_context_20260516T010000Z",
        game_started=False,
    )

    manifest = build_matchup_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="after_midnight_context_run",
        game_date="2026-05-15",
    )

    with Path(manifest["json_path"]).open(encoding="utf-8") as file:
        payload = json.load(file)

    row = payload["rows"][0]
    assert "rotowire_mlb_context_20260516T010000Z" in manifest["component_sources"]["lineup"]
    assert row["batting_order_slot"] == 2
    assert row["starter_matchup_score"] > 0.0
    assert "missing_lineup_context" not in row["missing_context_flags"]


def test_matchup_artifact_writer_blocks_started_context_rows_even_if_source_is_selected(tmp_path):
    engine_board_path = _write_engine_board_with_row(
        tmp_path,
        {
            **_engine_row(projection_id="proj_started", game_date="2026-05-15"),
            "start_time_utc": "2026-05-16T02:10:00Z",
        },
    )
    _write_rotowire_context_snapshot(
        tmp_path,
        run_id="rotowire_mlb_context_20260516T010000Z",
        snapshot_id="rotowire_mlb_context_20260516T030000Z",
        game_started=True,
    )

    manifest = build_matchup_context_artifacts(
        engine_board_path=engine_board_path,
        root=tmp_path,
        run_id="post_start_row_context_run",
        game_date="2026-05-15",
    )

    with Path(manifest["json_path"]).open(encoding="utf-8") as file:
        payload = json.load(file)

    row = payload["rows"][0]
    assert manifest["component_sources"]["lineup"] == "missing_rotowire_context"
    assert row["batting_order_slot"] is None
    assert row["starter_matchup_score"] == 0.0
    assert "missing_lineup_context" in row["missing_context_flags"]


def test_cli_prepare_matchups_delegates_to_runtime(tmp_path, capsys):
    engine_board_path = _write_engine_board(tmp_path)

    exit_code = main(
        [
            "prepare",
            "matchups",
            "--engine-board",
            str(engine_board_path),
            "--root",
            str(tmp_path),
            "--run-id",
            "cli_matchups",
            "--date",
            "2026-05-15",
            "--directions",
            "over",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Built MLB matchup context artifacts:" in captured.out
    assert (tmp_path / "data" / "mlb" / "features" / "matchups" / "cli_matchups" / "hitter_matchup_context.json").exists()


def test_prepare_umpire_profile_artifacts_writes_staged_outputs(tmp_path):
    source_path = tmp_path / "Umps.txt"
    source_path.write_text(
        json.dumps(
            {
                "rowCount": 2,
                "dataRows": [
                    {"columns": {"Umpire": "MIKE ESTABROOK", "ERA": "3.93", "Rating": "EXTREME PITCHERS"}},
                    {"columns": {"Umpire": "SCOTT BARRY", "ERA": "4.17", "Rating": "EXTREME HITTERS"}},
                ],
            }
        ),
        encoding="utf-8",
    )

    manifest = prepare_umpire_profile_artifacts(source_path=source_path, root=tmp_path, run_id="umpires_test")

    assert manifest["profile_count"] == 2
    assert Path(manifest["csv_path"]).exists()
    assert Path(manifest["latest_json_path"]).exists()

    with Path(manifest["csv_path"]).open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    assert rows[0]["umpire"] == "Mike Estabrook"
    assert float(rows[0]["umpire_run_score"]) < 0.0
    assert float(rows[1]["umpire_run_score"]) > 0.0


def test_prepare_umpire_profile_artifacts_accepts_umpscorecards_payload(tmp_path):
    source_path = tmp_path / "umpscorecards_payload.json"
    source_path.write_text(
        json.dumps(
            {
                "source": "umpscorecards_games",
                "rows": [
                    {
                        "umpire": "Hitter Ump",
                        "called_pitches": 150,
                        "fully_valid": True,
                        "failed": False,
                        "has_basic_game_data": True,
                        "home_batter_impact": 0.62,
                        "away_batter_impact": 0.46,
                        "total_run_impact": 1.85,
                        "accuracy_above_x": -0.5,
                    },
                    {
                        "umpire": "Pitcher Ump",
                        "called_pitches": 170,
                        "fully_valid": True,
                        "failed": False,
                        "has_basic_game_data": True,
                        "home_batter_impact": -0.80,
                        "away_batter_impact": -0.60,
                        "total_run_impact": 1.65,
                        "accuracy_above_x": 1.1,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    manifest = prepare_umpire_profile_artifacts(source_path=source_path, root=tmp_path, run_id="scorecards_test")

    assert manifest["profile_count"] == 2
    with Path(manifest["json_path"]).open(encoding="utf-8") as file:
        rows = {row["umpire"]: row for row in json.load(file)["rows"]}

    assert rows["Hitter Ump"]["umpire_run_score"] > 0.0
    assert rows["Pitcher Ump"]["umpire_run_score"] < 0.0
    assert "umpscorecards_profile" in rows["Hitter Ump"]["flags"]


def test_prepare_ballpark_profile_artifacts_writes_staged_outputs(tmp_path):
    source_path = tmp_path / "ballparks.csv"
    source_path.write_text(
        "venue_id,venue_name,team,Runs,HR,Hits,2B,3B\n"
        "10,Example Park,DET,106,112,103,108,96\n",
        encoding="utf-8",
    )

    manifest = prepare_ballpark_profile_artifacts(source_path=source_path, root=tmp_path, run_id="parks_test")

    assert manifest["profile_count"] == 1
    assert Path(manifest["csv_path"]).exists()
    assert Path(manifest["latest_json_path"]).exists()

    with Path(manifest["csv_path"]).open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    assert rows[0]["park_name"] == "Example Park"
    assert float(rows[0]["park_run_factor"]) == 1.06
    assert float(rows[0]["park_context_score"]) > 0.0


def test_cli_prepare_umpires_delegates_to_runtime(tmp_path, capsys):
    source_path = tmp_path / "Umps.txt"
    source_path.write_text(
        json.dumps(
            {
                "rowCount": 1,
                "dataRows": [
                    {"columns": {"Umpire": "SCOTT BARRY", "ERA": "4.17", "Rating": "EXTREME HITTERS"}},
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "prepare",
            "umpires",
            "--source",
            str(source_path),
            "--root",
            str(tmp_path),
            "--run-id",
            "cli_umpires",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Prepared MLB umpire profile artifacts:" in captured.out
    assert (tmp_path / "data" / "mlb" / "staged" / "umpires" / "cli_umpires" / "umpire_profiles.json").exists()


def test_cli_prepare_ballparks_delegates_to_runtime(tmp_path, capsys):
    source_path = tmp_path / "ballparks.csv"
    source_path.write_text(
        "venue_id,venue_name,team,Runs,HR,Hits,2B,3B\n"
        "10,Example Park,DET,106,112,103,108,96\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "prepare",
            "ballparks",
            "--source",
            str(source_path),
            "--root",
            str(tmp_path),
            "--run-id",
            "cli_ballparks",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Prepared MLB ballpark factor artifacts:" in captured.out
    assert (tmp_path / "data" / "mlb" / "staged" / "ballparks" / "cli_ballparks" / "ballpark_profiles.json").exists()


def _write_engine_board(tmp_path: Path) -> Path:
    engine_board_dir = tmp_path / "data" / "mlb" / "staged" / "engine_board" / "board_run"
    engine_board_dir.mkdir(parents=True)
    engine_board_path = engine_board_dir / "engine_board.json"
    engine_board_path.write_text(
        json.dumps(
            {
                "run_id": "board_run",
                "source": "prizepicks",
                "snapshot_id": "snap1",
                "row_count": 2,
                "rows": [
                    _engine_row(projection_id="proj1", game_date="2026-05-15"),
                    _engine_row(projection_id="proj2", game_date="2026-05-16"),
                ],
            }
        ),
        encoding="utf-8",
    )
    return engine_board_path


def _write_engine_board_with_row(tmp_path: Path, row: dict) -> Path:
    engine_board_dir = tmp_path / "data" / "mlb" / "staged" / "engine_board" / "single_board"
    engine_board_dir.mkdir(parents=True)
    engine_board_path = engine_board_dir / "engine_board.json"
    engine_board_path.write_text(
        json.dumps(
            {
                "run_id": "single_board",
                "source": "prizepicks",
                "snapshot_id": "snap-single",
                "row_count": 1,
                "rows": [row],
            }
        ),
        encoding="utf-8",
    )
    return engine_board_path


def _write_rotowire_context(tmp_path: Path) -> Path:
    output_dir = tmp_path / "data" / "mlb" / "staged" / "rotowire_context" / "rotowire_mlb_context_20260515T120000Z"
    output_dir.mkdir(parents=True)
    (output_dir / "normalize_manifest.json").write_text(
        json.dumps({"source": "rotowire_mlb_context", "game_date": "2026-05-15"}),
        encoding="utf-8",
    )
    (output_dir / "batting_orders.jsonl").write_text(
        json.dumps(
            {
                "game_date": "2026-05-15",
                "team_abbr": "DET",
                "opponent_abbr": "CLE",
                "batting_order": 2,
                "player_name": "Sample Player",
                "rotowire_player_id": "rotowire-sample",
                "lineup_status": "confirmed",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "pitchers.jsonl").write_text(
        json.dumps(
            {
                "game_date": "2026-05-15",
                "team_abbr": "CLE",
                "opponent_abbr": "DET",
                "rotowire_player_id": "starter-1",
                "pitcher_name": "Example Starter",
                "throws": "R",
                "pitcher_stats": "2-3 5.40 ERA",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "environment.jsonl").write_text(
        json.dumps(
            {
                "game_date": "2026-05-15",
                "away_team_abbr": "DET",
                "home_team_abbr": "CLE",
                "weather_text": "Weather: 82° Wind 14 mph OUT",
                "umpire_text": "Umpire: Scott Barry 9.8 R/G 16.2 K/G",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return output_dir


def _write_rotowire_context_snapshot(
    tmp_path: Path,
    *,
    run_id: str,
    snapshot_id: str,
    game_started: bool,
) -> Path:
    output_dir = tmp_path / "data" / "mlb" / "staged" / "rotowire_context" / run_id
    output_dir.mkdir(parents=True)
    slate_status = "is-mlb has-started not-in-slate" if game_started else "is-mlb not-started in-slate"
    (output_dir / "normalize_manifest.json").write_text(
        json.dumps(
            {
                "source": "rotowire_mlb_context",
                "game_date": "2026-05-15",
                "run_id": run_id,
                "snapshot_id": run_id,
            }
        ),
        encoding="utf-8",
    )
    base_row = {
        "game_date": "2026-05-15",
        "game_started": game_started,
        "slate_status": slate_status,
        "snapshot_id": snapshot_id,
    }
    (output_dir / "batting_orders.jsonl").write_text(
        json.dumps(
            {
                **base_row,
                "team_abbr": "DET",
                "opponent_abbr": "CLE",
                "batting_order": 2,
                "player_name": "Sample Player",
                "rotowire_player_id": "rotowire-sample",
                "lineup_status": "confirmed",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "pitchers.jsonl").write_text(
        json.dumps(
            {
                **base_row,
                "team_abbr": "CLE",
                "opponent_abbr": "DET",
                "rotowire_player_id": "starter-1",
                "pitcher_name": "Example Starter",
                "throws": "R",
                "pitcher_stats": "2-3 5.40 ERA",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "environment.jsonl").write_text(
        json.dumps(
            {
                **base_row,
                "away_team_abbr": "DET",
                "home_team_abbr": "CLE",
                "weather_text": "Weather: clear 82 Wind 14 mph OUT",
                "umpire_text": "",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return output_dir


def _write_wind_factors(tmp_path: Path) -> Path:
    output_dir = tmp_path / "data" / "mlb" / "staged" / "wind_factors"
    output_dir.mkdir(parents=True)
    path = output_dir / "latest.json"
    path.write_text(
        json.dumps(
            {
                "run_id": "wind_run",
                "league_wind_effects": [
                    {
                        "metric": "runs_per_game",
                        "wind_class": "out",
                        "wind_bucket": "11 to 15 mph",
                        "direction_key": "to_center",
                        "value": 5.05,
                        "baseline": 4.55,
                        "delta": 0.50,
                    },
                    {
                        "metric": "hr_per_game",
                        "wind_class": "out",
                        "wind_bucket": "11 to 15 mph",
                        "direction_key": "to_center",
                        "value": 1.30,
                        "baseline": 1.05,
                        "delta": 0.25,
                    },
                ],
                "park_wind_effects": [
                    {
                        "team": "CLE",
                        "net_hr_wind": 45,
                        "center_field_direction": "N",
                        "home_plate_direction": "S",
                        "wind_out_from_direction": "S",
                        "wind_in_from_direction": "N",
                        "crosswind_lf_to_rf_from_direction": "NW",
                        "crosswind_rf_to_lf_from_direction": "NE",
                        "source": "fixture",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_espn_game_context(tmp_path: Path) -> Path:
    output_dir = tmp_path / "data" / "mlb" / "staged" / "espn_game_context" / "espn_game_context_20260515T120000Z"
    output_dir.mkdir(parents=True)
    (output_dir / "normalize_manifest.json").write_text(
        json.dumps({"source": "espn_game_context", "game_date": "2026-05-15", "context_timing": "postgame_backfill"}),
        encoding="utf-8",
    )
    (output_dir / "batting_orders.jsonl").write_text(
        json.dumps(
            {
                "source": "espn_game_context",
                "context_timing": "postgame_backfill",
                "game_date": "2026-05-15",
                "team_abbr": "DET",
                "opponent_abbr": "CLE",
                "batting_order": 3,
                "player_name": "Sample Player",
                "rotowire_player_id": "player1",
                "lineup_status_key": "confirmed_postgame_backfill",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "pitchers.jsonl").write_text(
        json.dumps(
            {
                "source": "espn_game_context",
                "context_timing": "postgame_backfill",
                "game_date": "2026-05-15",
                "team_abbr": "CLE",
                "opponent_abbr": "DET",
                "rotowire_player_id": "starter-espn",
                "pitcher_name": "ESPN Starter",
                "throws": "R",
                "pitcher_stats": "5.40 ERA",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "environment.jsonl").write_text(
        json.dumps(
            {
                "source": "espn_game_context",
                "context_timing": "postgame_backfill",
                "game_date": "2026-05-15",
                "away_team_abbr": "DET",
                "home_team_abbr": "CLE",
                "weather_text": "",
                "umpire_text": "Umpire: Sample Umpire",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "bullpens.jsonl").write_text("", encoding="utf-8")
    return output_dir


def _write_baseball_reference_context(tmp_path: Path) -> Path:
    output_dir = (
        tmp_path
        / "data"
        / "mlb"
        / "staged"
        / "baseball_reference_boxscore_context"
        / "baseball_reference_boxscore_context_20260517T173437Z"
    )
    output_dir.mkdir(parents=True)
    base_row = {
        "source": "baseball_reference_boxscore_context",
        "snapshot_id": "baseball_reference_boxscore_context_20260517T173437Z",
        "context_timing": "historical_pregame_lineup_backfill",
        "lineup_content_timing": "pregame_starting_lineup",
        "game_date": "2026-05-15",
        "game_id": "CLE202605150",
        "team_name": "Detroit Tigers",
        "opponent_name": "Cleveland Guardians",
        "boxscore_url": "https://www.baseball-reference.com/boxes/CLE/CLE202605150.shtml",
    }
    (output_dir / "normalize_manifest.json").write_text(
        json.dumps(
            {
                "source": "baseball_reference_boxscore_context",
                "run_id": "baseball_reference_boxscore_context_20260517T173437Z",
                "snapshot_id": "baseball_reference_boxscore_context_20260517T173437Z",
                "context_timing": "historical_pregame_lineup_backfill",
                "lineup_content_timing": "pregame_starting_lineup",
                "game_date": "2026-05-15",
                "game_dates": ["2026-05-15"],
                "row_counts": {"batting_orders": 1, "pitchers": 1},
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "batting_orders.jsonl").write_text(
        json.dumps(
            {
                **base_row,
                "team_abbr": "DET",
                "opponent_abbr": "CLE",
                "batting_order": 2,
                "player_name": "Sample Player",
                "display_name": "Sample Player",
                "bref_player_id": "sample01",
                "rotowire_player_id": "bref:sample01",
                "position": "OF",
                "lineup_status": "Confirmed Starting Lineup",
                "lineup_status_key": "confirmed_starting_lineup",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "pitchers.jsonl").write_text(
        json.dumps(
            {
                **base_row,
                "team_abbr": "CLE",
                "opponent_abbr": "DET",
                "team_name": "Cleveland Guardians",
                "opponent_name": "Detroit Tigers",
                "pitcher_name": "Example Starter",
                "bref_player_id": "starter01",
                "rotowire_player_id": "bref:starter01",
                "position": "P",
                "throws": "R",
                "pitcher_stats": "2-3 5.40 ERA",
                "is_probable_starter": True,
                "lineup_status": "Confirmed Starting Pitcher",
                "lineup_status_key": "confirmed_starting_pitcher",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return output_dir


def _write_covers_weather_context(tmp_path: Path, *, wind_direction: str = "WSW") -> Path:
    output_dir = tmp_path / "data" / "mlb" / "staged" / "covers_weather" / "covers_weather_20260515T120000Z"
    output_dir.mkdir(parents=True)
    (output_dir / "normalize_manifest.json").write_text(
        json.dumps({"source": "covers_mlb_weather", "game_dates": ["2026-05-15"]}),
        encoding="utf-8",
    )
    (output_dir / "environment.jsonl").write_text(
        json.dumps(
            {
                "source": "covers_mlb_weather",
                "game_date": "2026-05-15",
                "away_team_abbr": "DET",
                "home_team_abbr": "CLE",
                "venue_name": "Progressive Field",
                "weather_text": f"Weather: clear day 82° Wind 14 mph {wind_direction}",
                "umpire_text": "",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return output_dir


def _write_umpire_profiles(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "mlb" / "staged" / "umpires" / "latest.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "umpire": "Scott Barry",
                        "era": 4.17,
                        "rating": "Extreme Hitters",
                        "umpire_run_score": 0.10,
                        "confidence": 1.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_ballpark_profiles(tmp_path: Path, *, run_id: str = "ballparks_20260515") -> Path:
    payload = {
        "rows": [
            {
                "park_id": "cle",
                "park_name": "Cleveland Park",
                "team": "CLE",
                "park_run_factor": 1.06,
                "park_hr_factor": 1.11,
                "park_hit_factor": 1.03,
                "park_extra_base_factor": 1.04,
                "confidence": 1.0,
            }
        ]
    }
    latest_path = tmp_path / "data" / "mlb" / "staged" / "ballparks" / "latest.json"
    dated_path = tmp_path / "data" / "mlb" / "staged" / "ballparks" / run_id / "ballpark_profiles.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    dated_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(payload), encoding="utf-8")
    dated_path.write_text(json.dumps(payload), encoding="utf-8")
    return dated_path


def _write_advanced_pitcher_profiles(tmp_path: Path) -> Path:
    path = (
        tmp_path
        / "data"
        / "mlb"
        / "staged"
        / "advanced_profiles"
        / "advanced_profiles_20260515"
        / "advanced_profiles.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "statsapi_person_id": 12345,
                        "player_id": "12345",
                        "player_name": "Example Starter",
                        "player_name_key": "examplestarter",
                        "player_team": "",
                        "profile_role": "pitcher",
                        "sample_bf": 320,
                        "xwoba": 0.260,
                        "xba": 0.200,
                        "xslg": 0.330,
                        "barrel_rate": 0.040,
                        "hard_hit_rate": 0.300,
                        "k_rate": 0.320,
                        "bb_rate": 0.060,
                        "whiff_rate": 0.340,
                        "contact_rate": 0.680,
                        "avg_exit_velocity": 86.0,
                        "flags": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _engine_row(*, projection_id: str, game_date: str) -> dict:
    return {
        "snapshot_id": "snap1",
        "source_projection_id": projection_id,
        "event_id": "game1",
        "league": "MLB",
        "game_date": game_date,
        "start_time_utc": f"{game_date}T23:10:00Z",
        "player_id": "player1",
        "player_name": "Sample Player",
        "player_team": "DET",
        "opponent": "CLE",
        "market": "hits",
        "source_market": "Hits",
        "line": 0.5,
        "tier": "STANDARD",
        "status": "pre_game",
        "player_position": "OF",
        "is_live": False,
        "is_combo": False,
        "updated_at": f"{game_date}T20:00:00Z",
        "pulled_at_utc": f"{game_date}T20:00:00Z",
    }
