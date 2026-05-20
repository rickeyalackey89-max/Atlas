import json
from pathlib import Path

from mlb.runtime.context_audit import build_context_audit_artifacts


def test_context_audit_reports_source_coverage_and_warnings(tmp_path):
    _write_run_artifacts(tmp_path)

    payload = build_context_audit_artifacts(root=tmp_path, run_id="audit_run")

    assert payload["run_id"] == "audit_run"
    assert payload["row_count"] == 2
    assert payload["coverage_summary"]["external_market_context_available"] == 0.0
    assert payload["coverage_summary"]["lineup_context_available"] == 0.5
    assert payload["coverage_summary"]["advanced_context_available"] == 0.5
    assert payload["coverage_summary"]["roster_context_available"] == 1.0
    assert payload["coverage_by_game_date"]["2026-05-16"]["row_count"] == 2
    assert payload["coverage_by_team"]["CLE"]["lineup_context_available"] == 0.0
    assert payload["coverage_by_team_game"]["2026-05-16 CLE vs unknown"]["row_count"] == 1
    assert payload["missing_drivers"]["lineup_context_available"]["teams"] == [
        {"player_team": "CLE", "missing_rows": 1}
    ]
    assert payload["missing_drivers"]["advanced_context_available"]["markets"] == [
        {"market_group": "batter", "market": "total_bases", "missing_rows": 1}
    ]
    assert payload["manifest_metrics"]["engine_board"]["dropped_by_date_filter_count"] == 4
    assert payload["manifest_metrics"]["advanced_context"]["coverage_rate"] == 0.5
    assert any(warning["code"] == "external_market_context_zero" for warning in payload["warnings"])
    assert any(warning["code"] == "advanced_profile_context_thin" for warning in payload["warnings"])
    assert any(warning["code"] == "ballpark_context_missing" for warning in payload["warnings"])
    assert any(warning["code"] == "future_date_props_filtered" for warning in payload["warnings"])

    audit_path = tmp_path / "data" / "mlb" / "features" / "context_audit" / "audit_run" / "context_audit.json"
    audit_md_path = tmp_path / "data" / "mlb" / "features" / "context_audit" / "audit_run" / "context_audit.md"
    assert audit_path.exists()
    assert audit_md_path.exists()


def _write_run_artifacts(root: Path) -> None:
    feature_path = root / "data" / "mlb" / "features" / "player_props" / "audit_run" / "feature_table.json"
    parameter_path = root / "data" / "mlb" / "features" / "parameters" / "audit_run" / "parameter_table.json"
    run_manifest_path = root / "data" / "mlb" / "runs" / "audit_run" / "run_manifest.json"

    feature_path.parent.mkdir(parents=True)
    parameter_path.parent.mkdir(parents=True)
    run_manifest_path.parent.mkdir(parents=True)

    feature_rows = [
        {
            "player_name": "Hitter One",
            "player_team": "DET",
            "market": "hits",
            "line": 1.5,
            "tier": "STANDARD",
            "game_date": "2026-05-16",
            "market_group": "batter",
            "external_market_context_available": False,
            "matchup_context_available": True,
            "lineup_context_available": True,
            "probable_pitcher_context_available": True,
            "weather_context_available": True,
            "statsapi_context_available": True,
            "roster_context_available": True,
            "advanced_context_available": True,
        },
        {
            "player_name": "Hitter Two",
            "player_team": "CLE",
            "market": "total_bases",
            "line": 2.5,
            "tier": "GOBLIN",
            "game_date": "2026-05-16",
            "market_group": "batter",
            "external_market_context_available": False,
            "matchup_context_available": False,
            "lineup_context_available": False,
            "probable_pitcher_context_available": False,
            "weather_context_available": False,
            "statsapi_context_available": True,
            "roster_context_available": True,
            "advanced_context_available": False,
        },
    ]
    parameter_rows = [
        {
            "market_context_available": False,
            "matchup_context_available": True,
            "advanced_context_available": True,
            "market_target_shift": 0.0,
            "matchup_target_shift": 0.02,
            "advanced_target_shift": 0.01,
            "market_target_blend_weight": 0.0,
            "advanced_context_flags": ["advanced_profile_context_available"],
            "flags": ["market_context_missing"],
        },
        {
            "market_context_available": False,
            "matchup_context_available": False,
            "advanced_context_available": False,
            "market_target_shift": 0.0,
            "matchup_target_shift": 0.0,
            "advanced_target_shift": 0.0,
            "market_target_blend_weight": 0.0,
            "advanced_context_flags": ["missing_advanced_context"],
            "flags": ["market_context_missing", "missing_lineup_context"],
        },
    ]
    feature_path.write_text(json.dumps({"run_id": "audit_run", "rows": feature_rows}), encoding="utf-8")
    parameter_path.write_text(json.dumps({"run_id": "audit_run", "rows": parameter_rows}), encoding="utf-8")

    manifest = {
        "run_id": "audit_run",
        "engine_board": {
            "row_count": 2,
            "source_row_count": 6,
            "game_date_filter": "2026-05-16",
            "date_filter_policy": "target_game_date",
            "date_counts_before_filter": {"2026-05-16": 2, "2026-05-17": 4},
            "date_counts_after_filter": {"2026-05-16": 2},
            "dropped_by_date_filter_count": 4,
        },
        "features": {"json_path": "data/mlb/features/player_props/audit_run/feature_table.json"},
        "parameters": {"json_path": "data/mlb/features/parameters/audit_run/parameter_table.json"},
        "market_context": {"market_source_row_count": 0},
        "matchups": {
            "component_sources": {"ballpark": "missing"},
            "pitcher_prop_missing_context_rate": 0.0,
            "pitcher_prop_thin_context_count": 0,
        },
        "roster_context": {"roster_source_row_count": 30},
        "statsapi_context": {"coverage_rate": 1.0},
        "advanced_context": {
            "coverage_rate": 0.5,
            "profile_source_row_count": 1,
            "advanced_context_flag_counts": {
                "advanced_profile_context_available": 1,
                "missing_advanced_context": 1,
            },
            "advanced_context_score_mean": 0.15,
            "advanced_sample_confidence_mean": 0.5,
        },
    }
    run_manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
