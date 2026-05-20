import json
from pathlib import Path

from mlb.fetchers.baseball_savant import (
    build_baseball_savant_context_requests,
    parse_baseball_savant_pages,
)
from mlb.normalizers.baseball_savant import normalize_baseball_savant_context
from mlb.runtime.source_operations import normalize_baseball_savant_result
from mlb.sources.snapshots import write_raw_snapshot


def test_baseball_savant_requests_cover_advanced_and_park_sources():
    requests = build_baseball_savant_context_requests(
        game_date="2026-05-16",
        season=2026,
        pages=parse_baseball_savant_pages("custom_batter,custom_pitcher,park_factors,schedule"),
    )

    assert [request.page for request in requests] == [
        "custom_batter",
        "custom_pitcher",
        "park_factors",
        "schedule",
    ]
    assert requests[0].params["year"] == 2026
    assert requests[0].params["type"] == "batter"
    assert requests[0].params["csv"] == "true"
    assert "whiff_percent" in requests[0].params["selections"]
    assert requests[1].params["year"] == 2026
    assert requests[1].params["type"] == "pitcher"
    assert requests[1].params["csv"] == "true"
    assert "barrel_batted_rate" in requests[1].params["selections"]
    assert requests[3].params == {"date": "2026-05-16"}


def test_baseball_savant_statcast_search_requests_are_date_bounded():
    requests = build_baseball_savant_context_requests(
        game_date="2026-05-15",
        season=2026,
        pages=parse_baseball_savant_pages("statcast_search_batter,statcast_search_pitcher"),
    )

    assert [request.page for request in requests] == ["statcast_search_batter", "statcast_search_pitcher"]
    assert requests[0].params["player_type"] == "batter"
    assert requests[0].params["game_date_gt"] == "2026-03-01"
    assert requests[0].params["game_date_lt"] == "2026-05-15"
    assert "type" not in requests[0].params
    assert requests[1].params["player_type"] == "pitcher"


def test_baseball_savant_expected_stats_csv_normalization():
    normalized = normalize_baseball_savant_context(
        {
            "source": "baseball_savant_context",
            "sport": "MLB",
            "game_date": "2026-05-16",
            "season": 2026,
            "data": [
                {
                    "page": "expected_batter",
                    "status_code": 200,
                    "content_type": "text/csv; charset=utf-8",
                    "body": (
                        '"last_name, first_name","player_id","year","pa","ba","est_ba","slg",'
                        '"est_slg","woba","est_woba"\n'
                        '"Smith, Will","669257","2026","144","0.276","0.282","0.480","0.502","0.360","0.388"\n'
                    ),
                },
                {
                    "page": "expected_pitcher",
                    "status_code": 200,
                    "content_type": "text/csv; charset=utf-8",
                    "body": (
                        '"last_name, first_name","player_id","year","pa","ba","est_ba","slg",'
                        '"est_slg","woba","est_woba","era","xera"\n'
                        '"Leiter, Jack","683004","2026","214","0.230","0.220","0.380","0.365",'
                        '"0.318","0.301","3.92","3.45"\n'
                    ),
                },
                {
                    "page": "park_factors",
                    "status_code": 200,
                    "content_type": "text/html",
                    "body": "<script>var data = [];</script>",
                },
            ],
        },
        snapshot_id="savant_csv",
    )

    hitter = normalized["advanced_profiles"][0]
    pitcher = normalized["advanced_profiles"][1]

    assert hitter["source"] == "baseball_savant_expected_statistics_hitter"
    assert hitter["player_name"] == "Will Smith"
    assert hitter["xba"] == 0.282
    assert hitter["xslg"] == 0.502
    assert hitter["xwoba"] == 0.388
    assert pitcher["source"] == "baseball_savant_expected_statistics_pitcher"
    assert pitcher["sample_bf"] == 214
    assert pitcher["xera"] == 3.45


def test_baseball_savant_statcast_search_csv_normalization():
    normalized = normalize_baseball_savant_context(
        {
            "source": "baseball_savant_context",
            "sport": "MLB",
            "game_date": "2026-05-15",
            "season": 2026,
            "data": [
                {
                    "page": "statcast_search_batter",
                    "status_code": 200,
                    "content_type": "application/download; charset=utf-8",
                    "body": (
                        '"pitches","player_id","player_name","ba","iso","slg","woba","xwoba","xba",'
                        '"xslg","pa","k_percent","bb_percent","hardhit_percent","barrels_per_bbe_percent",'
                        '"launch_speed","launch_angle","swing_miss_percent","hyper_speed"\n'
                        '"120","621493","Ward, Taylor","0.265","0.110","0.374","0.372","0.367",'
                        '"0.259","0.402","186","19.1","12.3","44.6","8.1","88.5","11.2","21.5","95.8"\n'
                    ),
                },
                {
                    "page": "statcast_search_pitcher",
                    "status_code": 200,
                    "content_type": "application/download; charset=utf-8",
                    "body": (
                        '"pitches","player_id","player_name","ba","slg","woba","xwoba","xba","xslg",'
                        '"pa","k_percent","bb_percent","hardhit_percent","barrels_per_bbe_percent"\n'
                        '"220","608331","Fried, Max","0.199","0.255","0.244","0.254","0.205",'
                        '"0.292","216","23.2","5.4","34.0","5.5"\n'
                    ),
                },
            ],
        },
        snapshot_id="savant_asof_20260515",
    )

    hitter = normalized["advanced_profiles"][0]
    pitcher = normalized["advanced_profiles"][1]

    assert hitter["player_name"] == "Taylor Ward"
    assert hitter["sample_pa"] == 186
    assert hitter["xwoba"] == 0.367
    assert hitter["hard_hit_rate"] == 44.6
    assert hitter["barrel_rate"] == 8.1
    assert hitter["avg_exit_velocity"] == 88.5
    assert hitter["whiff_rate"] == 21.5
    assert pitcher["player_name"] == "Max Fried"
    assert pitcher["sample_bf"] == 216
    assert pitcher["profile_role"] == "pitcher"


def test_baseball_savant_merges_expected_and_custom_rows_by_player_id():
    normalized = normalize_baseball_savant_context(
        {
            "source": "baseball_savant_context",
            "sport": "MLB",
            "game_date": "2026-05-16",
            "season": 2026,
            "data": [
                {
                    "page": "expected_batter",
                    "status_code": 200,
                    "content_type": "text/csv; charset=utf-8",
                    "body": (
                        '"last_name, first_name","player_id","year","pa","est_ba","est_slg","est_woba"\n'
                        '"Smith, Will","669257","2026","144","0.282","0.502","0.388"\n'
                    ),
                },
                {
                    "page": "custom_batter",
                    "status_code": 200,
                    "content_type": "text/csv; charset=utf-8",
                    "body": (
                        '"last_name, first_name","player_id","year","pa","xwoba","whiff_percent",'
                        '"barrel_batted_rate","avg_best_speed"\n'
                        '"Smith, Will","669257","2026","144",".370","17.9","14.3","99.92"\n'
                    ),
                },
            ],
        },
        snapshot_id="savant_merge",
    )

    assert len(normalized["advanced_profiles"]) == 1
    hitter = normalized["advanced_profiles"][0]
    assert hitter["player_name"] == "Will Smith"
    assert hitter["xba"] == 0.282
    assert hitter["xwoba"] == 0.37
    assert hitter["whiff_rate"] == 17.9
    assert hitter["barrel_rate"] == 14.3
    assert hitter["avg_best_speed"] == 99.92


def test_baseball_savant_normalization_builds_contract_source_rows():
    normalized = normalize_baseball_savant_context(_sample_payload(), snapshot_id="savant_snap")

    assert len(normalized["advanced_profiles"]) == 2
    hitter = normalized["advanced_profiles"][0]
    pitcher = normalized["advanced_profiles"][1]
    park = normalized["ballparks"][0]

    assert hitter["player_name"] == "Will Smith"
    assert hitter["statsapi_person_id"] == "669257"
    assert hitter["profile_role"] == "hitter"
    assert hitter["sample_pa"] == 144
    assert hitter["iso"] == 0.223
    assert pitcher["player_name"] == "Jack Leiter"
    assert pitcher["profile_role"] == "pitcher"
    assert pitcher["sample_bf"] == 214
    assert pitcher["throws"] == "R"
    assert park["park_name"] == "Chase Field"
    assert park["team"] == "ARI"
    assert park["park_run_factor"] == 1.08
    assert park["park_hr_factor"] == 0.92
    assert park["park_extra_base_factor"] == 1.2525


def test_baseball_savant_runtime_normalization_prepares_latest_artifacts(tmp_path):
    snapshot = write_raw_snapshot(
        source="baseball_savant_context",
        payload=_sample_payload(),
        request={"pages": ["custom_batter", "custom_pitcher", "park_factors"]},
        root=tmp_path,
    )

    result = normalize_baseball_savant_result(
        snapshot_path=Path(snapshot.path),
        root=tmp_path,
        run_id="savant_run",
    )

    assert result.payload["row_counts"]["advanced_profiles"] == 2
    assert result.payload["row_counts"]["ballparks"] == 1
    assert Path(result.payload["artifacts"]["advanced_profiles_json"]).exists()
    assert (tmp_path / "data" / "mlb" / "staged" / "advanced_profiles" / "latest.json").exists()
    assert (tmp_path / "data" / "mlb" / "staged" / "ballparks" / "latest.json").exists()


def _sample_payload() -> dict:
    return {
        "source": "baseball_savant_context",
        "sport": "MLB",
        "game_date": "2026-05-16",
        "season": 2026,
        "data": [
            {
                "page": "custom_batter",
                "status_code": 200,
                "content_type": "text/html",
                "body": "<script>var data = "
                + json.dumps(
                    [
                        {
                            "player_id": 669257,
                            "player_name": "Smith, Will",
                            "pa": 144,
                            "xwoba": 0.388,
                            "xba": 0.282,
                            "xslg": 0.502,
                            "woba": 0.360,
                            "isolated_power": 0.223,
                            "barrel_batted_rate": 11.5,
                            "hard_hit_percent": 45.0,
                            "k_percent": 18.0,
                            "bb_percent": 10.2,
                            "whiff_percent": 20.0,
                            "oz_swing_percent": 25.0,
                            "iz_contact_percent": 84.0,
                            "exit_velocity_avg": 91.1,
                            "launch_angle_avg": 14.2,
                        }
                    ]
                )
                + ";</script>",
            },
            {
                "page": "custom_pitcher",
                "status_code": 200,
                "content_type": "text/html",
                "body": "<script>var data = "
                + json.dumps(
                    [
                        {
                            "player_id": 683004,
                            "player_name": "Leiter, Jack",
                            "p_total_pa": 214,
                            "pitch_hand": "R",
                            "xwoba": 0.301,
                            "xba": 0.220,
                            "xslg": 0.365,
                            "woba": 0.318,
                            "barrel_batted_rate": 7.0,
                            "hard_hit_percent": 38.0,
                            "k_percent": 28.0,
                            "bb_percent": 8.5,
                            "whiff_percent": 29.0,
                            "oz_swing_percent": 31.0,
                            "iz_contact_percent": 76.0,
                            "exit_velocity_avg": 88.0,
                            "launch_angle_avg": 11.0,
                        }
                    ]
                )
                + ";</script>",
            },
            {
                "page": "park_factors",
                "status_code": 200,
                "content_type": "text/html",
                "body": "<script>var data = "
                + json.dumps(
                    [
                        {
                            "venue_id": "15",
                            "venue_name": "Chase Field",
                            "main_team_id": "109",
                            "n_pa": "41581",
                            "index_runs": "108",
                            "index_hits": "105",
                            "index_2b": "117",
                            "index_3b": "206",
                            "index_hr": "92",
                            "year_range": "2024-2026",
                        }
                    ]
                )
                + ";</script>",
            },
        ],
    }
