from pathlib import Path

from mlb.runtime.source_operations import normalize_statsapi_result
from mlb.normalizers.statsapi import (
    normalize_statsapi_boxscore,
    normalize_statsapi_boxscores_bulk,
    normalize_statsapi_player_gamelog,
    normalize_statsapi_player_gamelogs_bulk,
    normalize_statsapi_roster,
    normalize_statsapi_rosters_bulk,
    normalize_statsapi_schedule,
    normalize_statsapi_teams,
    normalize_statsapi_transactions,
    write_statsapi_normalization,
)
from mlb.sources.snapshots import write_raw_snapshot


def test_statsapi_team_normalization_handles_major_and_minor_payloads():
    rows = normalize_statsapi_teams(
        {
            "season": 2026,
            "payloads": [
                {
                    "teams": [
                        {
                            "id": 133,
                            "name": "Athletics",
                            "abbreviation": "ATH",
                            "shortName": "Athletics",
                            "clubName": "Athletics",
                            "sport": {"id": 1},
                            "league": {"id": 103, "name": "American League"},
                            "division": {"id": 200, "name": "AL West"},
                            "venue": {"id": 10, "name": "Example Park"},
                            "active": True,
                        }
                    ]
                },
                {
                    "teams": [
                        {
                            "id": 5000,
                            "name": "Sample Triple-A",
                            "abbreviation": "SMP",
                            "sport": {"id": 11},
                            "parentOrgId": 133,
                            "parentOrgName": "Athletics",
                        }
                    ]
                },
            ],
        }
    )
    assert rows[0]["sport_id"] == 1
    assert rows[0]["level"] == "MLB"
    assert rows[1]["sport_id"] == 11
    assert rows[1]["parent_org_id"] == 133


def test_statsapi_roster_normalization_extracts_hydrated_person():
    rows = normalize_statsapi_roster(
        {
            "_atlas_fetch": {"team_id": 5000, "season": 2026},
            "roster": [
                {
                    "person": {
                        "id": 101,
                        "fullName": "Sample Player",
                        "firstName": "Sample",
                        "lastName": "Player",
                        "batSide": {"code": "L"},
                        "pitchHand": {"code": "R"},
                        "birthDate": "2000-01-01",
                        "height": "6' 1\"",
                        "weight": 200,
                    },
                    "position": {"abbreviation": "OF"},
                    "jerseyNumber": "7",
                    "status": {"description": "Active"},
                    "rosterType": "active",
                }
            ],
        },
        team_context={"sport_id": 11, "team_name": "Sample Triple-A", "parent_org_id": 133},
    )
    assert rows[0]["person_id"] == 101
    assert rows[0]["player_name"] == "Sample Player"
    assert rows[0]["level"] == "Triple-A"
    assert rows[0]["bats"] == "L"
    assert rows[0]["team_name"] == "Sample Triple-A"


def test_statsapi_rosters_bulk_normalization_preserves_team_context():
    rows = normalize_statsapi_rosters_bulk(
        {
            "payloads": [
                {
                    "team_context": {
                        "team_id": 141,
                        "team_name": "Toronto Blue Jays",
                        "team_abbreviation": "TOR",
                        "sport_id": 1,
                    },
                    "payload": {
                        "_atlas_fetch": {"team_id": 141, "season": 2026},
                        "roster": [
                            {
                                "person": {
                                    "id": 101,
                                    "fullName": "Sample Hitter",
                                    "batSide": {"code": "L"},
                                    "pitchHand": {"code": "R"},
                                },
                                "position": {"abbreviation": "OF"},
                                "status": {"description": "Active"},
                            }
                        ],
                    },
                }
            ]
        }
    )

    assert rows[0]["person_id"] == 101
    assert rows[0]["team_id"] == 141
    assert rows[0]["team_abbreviation"] == "TOR"
    assert rows[0]["level"] == "MLB"


def test_statsapi_schedule_normalization_extracts_game_ids():
    rows = normalize_statsapi_schedule(
        {
            "_atlas_fetch": {"sportId": 1},
            "dates": [
                {
                    "date": "2026-04-01",
                    "games": [
                        {
                            "gamePk": 123,
                            "gameDate": "2026-04-01T18:10:00Z",
                            "officialDate": "2026-04-01",
                            "status": {"detailedState": "Scheduled"},
                            "teams": {
                                "away": {"team": {"id": 1, "name": "Away"}},
                                "home": {"team": {"id": 2, "name": "Home"}},
                            },
                            "venue": {"id": 9, "name": "Park"},
                            "doubleHeader": "N",
                            "gameNumber": 1,
                            "seriesDescription": "Regular Season",
                        }
                    ],
                }
            ],
        }
    )
    assert rows[0]["game_pk"] == 123
    assert rows[0]["away_team_id"] == 1
    assert rows[0]["home_team_id"] == 2


def test_statsapi_boxscore_normalization_extracts_player_stats():
    rows = normalize_statsapi_boxscore(
        {
            "_atlas_fetch": {"game_pk": 123},
            "teams": {
                "away": {
                    "team": {"id": 1, "name": "Away"},
                    "battingOrder": [101],
                    "players": {
                        "ID101": {
                            "person": {"id": 101, "fullName": "Sample Hitter"},
                            "position": {"abbreviation": "CF"},
                            "stats": {"batting": {"atBats": 4, "hits": 2}, "fielding": {"putOuts": 1}},
                        }
                    },
                },
                "home": {"team": {"id": 2, "name": "Home"}, "players": {}},
            },
        }
    )
    assert rows[0]["game_pk"] == 123
    assert rows[0]["person_id"] == 101
    assert rows[0]["is_starter"] is True
    assert rows[0]["batting_stats"]["hits"] == 2


def test_statsapi_player_gamelog_normalization_extracts_splits():
    rows = normalize_statsapi_player_gamelog(
        {
            "_atlas_fetch": {"person_id": 101, "group": "hitting", "season": 2026},
            "stats": [
                {
                    "group": {"displayName": "hitting"},
                    "splits": [
                        {
                            "date": "2026-04-01",
                            "player": {"fullName": "Sample Hitter"},
                            "team": {"id": 1, "name": "Away"},
                            "opponent": {"id": 2, "name": "Home"},
                            "game": {"gamePk": 123},
                            "isHome": False,
                            "stat": {"atBats": 4, "hits": 2},
                        }
                    ],
                }
            ],
        }
    )
    assert rows[0]["person_id"] == 101
    assert rows[0]["group"] == "hitting"
    assert rows[0]["game_pk"] == 123
    assert rows[0]["stat"]["hits"] == 2


def test_statsapi_bulk_boxscore_normalization_reuses_boxscore_contract():
    rows = normalize_statsapi_boxscores_bulk(
        {
            "payloads": [
                {
                    "game_pk": 123,
                    "payload": {
                        "teams": {
                            "away": {
                                "team": {"id": 1, "name": "Away"},
                                "battingOrder": [101],
                                "players": {
                                    "ID101": {
                                        "person": {"id": 101, "fullName": "Sample Hitter"},
                                        "position": {"abbreviation": "CF"},
                                        "stats": {"batting": {"plateAppearances": 5}},
                                    }
                                },
                            },
                            "home": {"team": {"id": 2, "name": "Home"}, "players": {}},
                        }
                    },
                }
            ]
        }
    )
    assert rows[0]["game_pk"] == 123
    assert rows[0]["batting_stats"]["plateAppearances"] == 5


def test_statsapi_bulk_gamelog_normalization_preserves_player_context():
    rows = normalize_statsapi_player_gamelogs_bulk(
        {
            "season": 2026,
            "group": "hitting",
            "payloads": [
                {
                    "person_id": 101,
                    "player_context": {"player_name": "Sample Hitter", "team_abbreviation": "BOS", "position": "OF"},
                    "payload": {
                        "stats": [
                            {
                                "group": {"displayName": "hitting"},
                                "splits": [
                                    {
                                        "date": "2026-04-01",
                                        "team": {"id": 1, "name": "Away"},
                                        "opponent": {"id": 2, "name": "Home"},
                                        "game": {"gamePk": 123},
                                        "stat": {"plateAppearances": 4},
                                    }
                                ],
                            }
                        ]
                    },
                }
            ],
        }
    )
    assert rows[0]["person_id"] == 101
    assert rows[0]["player_name"] == "Sample Hitter"
    assert rows[0]["player_team"] == "BOS"
    assert rows[0]["stat"]["plateAppearances"] == 4


def test_statsapi_transactions_normalization_classifies_callups():
    rows = normalize_statsapi_transactions(
        {
            "_atlas_fetch": {"sportId": 1},
            "transactions": [
                {
                    "id": 7,
                    "person": {"id": 101, "fullName": "Sample Pitcher"},
                    "fromTeam": {"id": 500, "name": "Sample Triple-A"},
                    "toTeam": {"id": 111, "name": "Boston Red Sox"},
                    "date": "2026-05-12",
                    "effectiveDate": "2026-05-12",
                    "typeCode": "CU",
                    "typeDesc": "Recalled",
                    "description": "Boston Red Sox recalled RHP Sample Pitcher from Worcester Red Sox.",
                }
            ],
        }
    )
    assert rows[0]["person_id"] == 101
    assert rows[0]["movement_direction"] == "to_mlb"
    assert rows[0]["is_callup"] is True
    assert rows[0]["from_team_name"] == "Sample Triple-A"


def test_statsapi_normalization_writer(tmp_path):
    snapshot = write_raw_snapshot(
        source="statsapi_schedule",
        payload={"_atlas_fetch": {"sportId": 1}, "dates": []},
        request={},
        root=tmp_path,
    )
    out = write_statsapi_normalization(Path(snapshot.path), kind="statsapi_schedule", root=tmp_path)
    assert out["row_count"] == 0
    assert Path(out["rows_path"]).exists()

    result = normalize_statsapi_result(kind="statsapi_schedule", snapshot_path=Path(snapshot.path), root=tmp_path)
    assert result.payload["source"] == "statsapi_schedule"
