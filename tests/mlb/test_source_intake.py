import json
from datetime import date
from pathlib import Path

from mlb.fetchers.espn_injuries import normalize_espn_injury_payload
from mlb.fetchers.historical_backfill.espn_game_context import build_espn_game_context_requests
from mlb.fetchers.draftkings import (
    build_draftkings_mlb_live_request,
    count_draftkings_live_offers,
    count_draftkings_pick6_rows,
)
from mlb.fetchers.bettingpros import parse_bettingpros_book_ids, parse_bettingpros_market_ids
from mlb.fetchers.oddsapi import parse_bookmakers, parse_markets
from mlb.fetchers.historical_backfill.parlayapi import parse_parlayapi_markets
from mlb.fetchers.prizepicks import (
    build_prizepicks_all_sports_request,
    build_prizepicks_mlb_request,
)
from mlb.fetchers.rotowire import build_rotowire_mlb_context_requests
from mlb.fetchers.historical_backfill.baseball_reference import baseball_reference_boxscore_url
from mlb.fetchers.historical_backfill.wunderground_history import extract_wunderground_history_urls
from mlb.normalizers.oddsapi import normalize_oddsapi_mlb_props, write_oddsapi_mlb_normalization
from mlb.normalizers.parlayapi import normalize_parlayapi_mlb_closing_props
from mlb.normalizers.covers_weather import (
    normalize_covers_mlb_weather_html,
    write_covers_mlb_weather_normalization,
)
from mlb.normalizers.draftkings_pick6 import normalize_draftkings_pick6, write_draftkings_pick6_normalization
from mlb.normalizers.draftkings_sportsbook import normalize_draftkings_sportsbook_props
from mlb.normalizers.bettingpros import normalize_bettingpros_mlb_props, write_bettingpros_mlb_normalization
from mlb.normalizers.baseball_reference import (
    normalize_baseball_reference_boxscore,
    write_baseball_reference_boxscore_normalization,
)
from mlb.normalizers.espn_game_context import (
    normalize_espn_game_context,
    write_espn_game_context_normalization,
)
from mlb.normalizers.espn_gamelogs import normalize_espn_player_gamelog
from mlb.normalizers.wunderground_history import normalize_wunderground_history_weather
from mlb.normalizers.prizepicks import (
    normalize_prizepicks_board,
    normalize_prizepicks_csv_file,
    write_prizepicks_board_normalization,
    write_prizepicks_csv_normalization,
)
from mlb.normalizers.rotowire import normalize_rotowire_mlb_context, write_rotowire_mlb_normalization
from mlb.runtime.engine_inputs import publish_engine_board
from mlb.runtime.source_operations import (
    backfill_bettingpros_result,
    backfill_oddsapi_result,
    import_prizepicks_csv_result,
    import_legacy_prizepicks_raw_result,
    normalize_injuries_snapshot,
    source_catalog_result,
)
from mlb.sources.snapshots import load_snapshot_manifest, load_snapshot_payload, write_raw_snapshot


def test_raw_snapshot_writer_and_loader(tmp_path):
    payload = {"data": [{"id": "p1"}], "included": []}
    snapshot = write_raw_snapshot(
        source="prizepicks",
        payload=payload,
        request={"url": "https://example.test"},
        root=tmp_path,
    )
    payload_path = Path(snapshot.path)
    manifest = load_snapshot_manifest(payload_path)
    assert payload_path.exists()
    assert manifest["source"] == "prizepicks"
    assert manifest["record_count"] == 1
    assert load_snapshot_payload(payload_path) == payload


def test_prizepicks_board_normalization_supports_rows_and_rejects(tmp_path):
    payload = _sample_prizepicks_payload()
    result = normalize_prizepicks_board(payload, snapshot_id="snap_1", pulled_at_utc="2026-05-11T00:00:00Z")
    assert len(result.rows) == 1
    assert len(result.rejects) == 1
    row = result.rows[0]
    assert row["market"] == "hits"
    assert row["player_name"] == "Sample Hitter"
    assert row["opponent"] == "NYY"
    assert result.rejects[0]["reason"] == "unsupported_market"

    snapshot = write_raw_snapshot(source="prizepicks", payload=payload, request={}, root=tmp_path)
    written = write_prizepicks_board_normalization(Path(snapshot.path), root=tmp_path, run_id="test_run")
    assert written.output_dir is not None
    assert (written.output_dir / "normalized_board.jsonl").exists()
    assert (written.output_dir / "rejected_board.jsonl").exists()

    engine_board = publish_engine_board(normalized_dir=written.output_dir, root=tmp_path, game_date="2026-05-11")
    assert engine_board["row_count"] == 1
    assert Path(engine_board["csv_path"]).exists()
    assert Path(engine_board["json_path"]).exists()
    assert Path(engine_board["latest_csv_path"]).exists()


def test_prizepicks_board_uses_local_slate_date_for_late_utc_starts():
    payload = _sample_prizepicks_payload()
    payload["data"][0]["attributes"]["start_time"] = "2026-05-20T00:40:00Z"
    payload["included"][1]["attributes"]["start_time"] = "2026-05-20T00:40:00Z"

    result = normalize_prizepicks_board(payload, snapshot_id="snap_late_utc", pulled_at_utc="2026-05-19T23:55:00Z")

    assert result.rows[0]["start_time_utc"] == "2026-05-20T00:40:00Z"
    assert result.rows[0]["game_date"] == "2026-05-19"


def test_prizepicks_csv_import_dedupes_and_publishes_engine_board(tmp_path):
    csv_path = tmp_path / "imports" / "prizepicks_2026-05-11T18-04-18Z.csv"
    csv_path.parent.mkdir()
    csv_path.write_text(
        "\n".join(
            [
                "scraped_at,projection_id,league,sport,player,team,position,description,stat_type,line,start_time,odds_type",
                "2026-05-11T18:03:28Z,100,MLB,,Sample Hitter,NYY,OF,BOS,Hits,1.5,2026-05-11T19:05:00.000-04:00,standard",
                "2026-05-11T18:03:28Z,100,MLB,,Sample Hitter,NYY,OF,BOS,Hits,1.5,2026-05-11T19:05:00.000-04:00,standard",
                "2026-05-11T18:03:28Z,101,MLB,,Unsupported Player,NYY,OF,BOS,Shots,2.5,2026-05-11T19:05:00.000-04:00,standard",
                "2026-05-11T18:03:28Z,200,NBA,,Other Player,BOS,G,NYY,Points,20.5,2026-05-11T19:05:00.000-04:00,standard",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    normalized = normalize_prizepicks_csv_file(csv_path)

    assert normalized.snapshot_id == "github_prizepicks_csv_20260511T180328Z"
    assert len(normalized.rows) == 1
    assert len(normalized.rejects) == 1
    assert normalized.rows[0]["snapshot_id"] == normalized.snapshot_id
    assert normalized.rows[0]["event_id"] == "csv:2026-05-11:BOS-NYY:2026-05-11T23:05:00Z"
    assert normalized.metadata["source_row_count"] == 4
    assert normalized.metadata["mlb_row_count"] == 3
    assert normalized.metadata["duplicate_projection_count"] == 1
    assert normalized.metadata["skipped_non_mlb_count"] == 1

    written = write_prizepicks_csv_normalization(csv_path, root=tmp_path)
    engine_board = publish_engine_board(normalized_dir=written.output_dir, root=tmp_path, game_date="2026-05-11")
    assert engine_board["row_count"] == 1


def test_import_prizepicks_csv_directory_imports_date_range(tmp_path):
    source_dir = tmp_path / "raw_imports" / "mlb_github_imports"
    source_dir.mkdir(parents=True)
    (source_dir / "prizepicks_2026-05-11T18-04-18Z.csv").write_text(
        "\n".join(
            [
                "scraped_at,projection_id,league,sport,player,team,position,description,stat_type,line,start_time,odds_type",
                "2026-05-11T18:03:28Z,100,MLB,,Sample Hitter,NYY,OF,BOS,Hits,1.5,2026-05-11T19:05:00.000-04:00,standard",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (source_dir / "prizepicks_2026-05-12T18-04-18Z.csv").write_text(
        "\n".join(
            [
                "scraped_at,projection_id,league,sport,player,team,position,description,stat_type,line,start_time,odds_type",
                "2026-05-12T18:03:28Z,101,MLB,,Sample Hitter,NYY,OF,BOS,Hits,1.5,2026-05-12T19:05:00.000-04:00,standard",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = import_prizepicks_csv_result(
        source_dir=source_dir,
        start_date=date(2026, 5, 11),
        end_date=date(2026, 5, 11),
        root=tmp_path,
    )

    assert result.payload["imported_count"] == 1
    assert result.payload["total_normalized"] == 1
    assert result.payload["total_engine_rows"] == 1
    assert Path(result.payload["imported"][0]["engine_input"]["json_path"]).exists()


def test_engine_board_filters_non_target_game_dates(tmp_path):
    normalized_dir = tmp_path / "data" / "mlb" / "staged" / "board" / "mixed_date_run"
    normalized_dir.mkdir(parents=True)
    (normalized_dir / "normalize_manifest.json").write_text(
        json.dumps({"run_id": "mixed_date_run", "snapshot_id": "prizepicks_20260516T065109Z"}),
        encoding="utf-8",
    )
    rows = [
        _normalized_row("proj_today", "2026-05-16"),
        _normalized_row("proj_tomorrow", "2026-05-17"),
    ]
    (normalized_dir / "normalized_board.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    engine_board = publish_engine_board(normalized_dir=normalized_dir, root=tmp_path, game_date="2026-05-16")
    payload = json.loads(Path(engine_board["json_path"]).read_text(encoding="utf-8"))

    assert engine_board["source_row_count"] == 2
    assert engine_board["row_count"] == 1
    assert engine_board["dropped_by_date_filter_count"] == 1
    assert engine_board["date_counts_before_filter"] == {"2026-05-16": 1, "2026-05-17": 1}
    assert engine_board["date_counts_after_filter"] == {"2026-05-16": 1}
    assert payload["rows"][0]["source_projection_id"] == "proj_today"


def test_espn_injury_normalization_and_writer(tmp_path):
    payload = {
        "timestamp": "2026-05-11T21:05:14Z",
        "injuries": [
            {
                "displayName": "Boston Red Sox",
                "injuries": [
                    {
                        "id": "inj1",
                        "status": "10-Day-IL",
                        "shortComment": "Hamstring strain.",
                        "date": "2026-05-10T12:45Z",
                        "athlete": {
                            "id": "100",
                            "displayName": "Sample Player",
                            "position": {"abbreviation": "OF"},
                            "team": {"abbreviation": "BOS"},
                        },
                    }
                ],
            }
        ],
    }
    injuries = normalize_espn_injury_payload(payload)
    assert len(injuries) == 1
    assert injuries[0].player_name == "Sample Player"
    assert injuries[0].team == "BOS"

    snapshot = write_raw_snapshot(source="espn_injuries", payload=payload, request={}, root=tmp_path)
    normalized = normalize_injuries_snapshot(Path(snapshot.path), root=tmp_path, run_id="injury_run")
    assert normalized["injury_count"] == 1
    assert Path(normalized["injuries_path"]).exists()


def test_source_catalog_includes_prizepicks_and_injuries():
    result = source_catalog_result()
    keys = {item["key"] for item in result.payload["sources"]}
    assert "prizepicks" in keys
    assert "prizepicks_all_sports" in keys
    assert "legacy_prizepicks_nba" in keys
    assert "espn_injuries" in keys
    assert "oddsapi_mlb_live" in keys
    assert "oddsapi_mlb_historical" in keys
    assert "parlayapi_mlb_historical_closing_props" in keys
    assert "bettingpros_mlb_props" in keys
    assert "draftkings_mlb_live" in keys
    assert "draftkings_mlb_pick6" in keys
    assert "rotowire_mlb_context" in keys
    assert "covers_mlb_weather" in keys


def test_prizepicks_requests_keep_all_sports_and_mlb_separate():
    all_sports = build_prizepicks_all_sports_request()
    mlb = build_prizepicks_mlb_request()

    assert all_sports.source == "prizepicks_all_sports"
    assert "league_id" not in all_sports.params()
    assert mlb.source == "prizepicks"
    assert mlb.params()["league_id"] == 2


def test_draftkings_live_request_and_offer_counts():
    request = build_draftkings_mlb_live_request()
    assert request.source == "draftkings_mlb_live"
    assert request.url.endswith("/v1/sports/7/live")
    assert request.event_group_id == 84240

    counts = count_draftkings_live_offers(
        {
            "featuredDisplayGroup": {
                "featuredSubcategories": [
                    {
                        "featuredEventGroupSubcategories": [
                            {
                                "offers": [
                                    [
                                        {
                                            "label": "Run Line",
                                            "outcomes": [{"label": "Away"}, {"label": "Home"}],
                                        }
                                    ]
                                ]
                            }
                        ]
                    }
                ]
            }
        }
    )
    assert counts == {
        "subcategory_count": 1,
        "event_group_count": 1,
        "offer_count": 1,
        "outcome_count": 2,
    }


def test_draftkings_pick6_counts_and_normalization(tmp_path):
    category_responses = [
        {
            "pick_group_id": 147574,
            "pick_group_state": "Upcoming",
            "categories": [
                {
                    "category_id": 37,
                    "payload": {
                        "pickCategoryId": 37,
                        "pickCategoryById": {"37": {"categoryName": "Batters"}},
                        "pickSixMarketById": {
                            "349": {"name": "Batter Fantasy Points"},
                            "350": {"name": "Pitcher Fantasy Points"},
                            "304": {"name": "Hits + Runs + RBIs"},
                            "321": {"name": "Stolen Bases"},
                            "687": {"name": "Runs + RBIs"},
                        },
                        "entityInfoByDkId": {"123": {"fullName": "Sample Hitter"}},
                        "displayTeamById": {
                            "1": {"name": "Boston Red Sox"},
                            "2": {"name": "New York Yankees"},
                        },
                        "competitionById": {
                            "game1": {
                                "startTime": "2026-05-20T00:40:00Z",
                                "homeTeamId": 1,
                                "awayTeamId": 2,
                                "entityCompByDkId": {"123": {"teamId": 1, "position": "OF"}},
                            }
                        },
                        "pickCardByPickableId": {
                            "pc1": {
                                "pickableId": "pc1",
                                "entities": [{"dkId": "123", "compIds": ["game1"]}],
                                "activePickableMarkets": [
                                    {
                                        "pickableMarketId": "pm0",
                                        "pickSixMarketId": 349,
                                        "targetValue": 7.5,
                                        "isLive": False,
                                        "isPaused": False,
                                    },
                                    {
                                        "pickableMarketId": "pm00",
                                        "pickSixMarketId": 350,
                                        "targetValue": 34.5,
                                        "isLive": False,
                                        "isPaused": False,
                                    },
                                    {
                                        "pickableMarketId": "pm1",
                                        "pickSixMarketId": 304,
                                        "targetValue": 1.5,
                                        "isLive": False,
                                        "isPaused": False,
                                        "activeSelections": [
                                            {
                                                "statLinePropositionId": 1,
                                                "formattedStandingsMultiplier": "1x",
                                            }
                                        ],
                                    },
                                    {
                                        "pickableMarketId": "pm2",
                                        "pickSixMarketId": 321,
                                        "targetValue": 0.5,
                                        "isLive": False,
                                        "isPaused": False,
                                    },
                                    {
                                        "pickableMarketId": "pm3",
                                        "pickSixMarketId": 687,
                                        "targetValue": 0.5,
                                        "isLive": False,
                                        "isPaused": False,
                                    },
                                ],
                            }
                        },
                    },
                }
            ],
        }
    ]
    payload = {"category_responses": category_responses}

    assert count_draftkings_pick6_rows(category_responses) == {
        "category_count": 1,
        "pickcard_count": 1,
        "active_market_count": 5,
    }

    normalized = normalize_draftkings_pick6(payload, snapshot_id="dk_pick6_snap")
    assert normalized["row_count"] == 4
    assert normalized["rejected_count"] == 1
    row = normalized["rows"][0]
    assert row["source"] == "draftkings_mlb_pick6"
    assert row["market"] == "hitter_fantasy_score"
    assert row["line"] == 7.5
    assert row["game_date"] == "2026-05-19"
    assert row["player_name"] == "Sample Hitter"
    assert row["player_team"] == "Boston Red Sox"
    assert row["opponent"] == "New York Yankees"
    assert {item["market"] for item in normalized["rows"]} == {
        "hitter_fantasy_score",
        "pitcher_fantasy_score",
        "hits_runs_rbis",
        "stolen_bases",
    }
    assert normalized["rejects"][0]["reason"] == "unsupported_market"

    snapshot = write_raw_snapshot(source="draftkings_mlb_pick6", payload=payload, request={}, root=tmp_path)
    written = write_draftkings_pick6_normalization(Path(snapshot.path), root=tmp_path, run_id="dk_pick6_run")
    assert written["compatible_artifact"] == "oddsapi_props.jsonl"
    assert written["compatible_row_count"] == 4
    compatible_rows = [
        json.loads(line)
        for line in Path(written["compatible_rows_path"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert compatible_rows[0]["source"] == "draftkings_mlb_pick6"
    assert compatible_rows[0]["over_prob"] == 0.5


def test_draftkings_sportsbook_milestone_normalization():
    payload = {
        "_atlas_fetch": {"source": "draftkings_mlb_sportsbook"},
        "responses": [
            {
                "market": "hits",
                "subcategory_id": "17320",
                "response": {
                    "events": [
                        {
                            "id": "game1",
                            "startEventDate": "2026-05-20T00:40:00.0000000Z",
                            "participants": [
                                {"id": "home", "name": "New York Yankees", "venueRole": "Home"},
                                {"id": "away", "name": "Toronto Blue Jays", "venueRole": "Away"},
                            ],
                        }
                    ],
                    "markets": [
                        {
                            "id": "market1",
                            "eventId": "game1",
                            "name": "Aaron Judge Hits",
                            "subcategoryId": "17320",
                        }
                    ],
                    "selections": [
                        {
                            "id": "selection1",
                            "marketId": "market1",
                            "label": "1+",
                            "milestoneValue": 1,
                            "displayOdds": {"american": "-150"},
                            "participants": [
                                {"id": "player1", "name": "Aaron Judge", "type": "Player", "venueRole": "HomePlayer"}
                            ],
                        }
                    ],
                },
            }
        ],
    }
    normalized = normalize_draftkings_sportsbook_props(payload, snapshot_id="dk_sb_snap")
    assert normalized["row_count"] == 1
    row = normalized["rows"][0]
    assert row["source"] == "draftkings_mlb_sportsbook"
    assert row["market"] == "hits"
    assert row["line"] == 0.5
    assert row["game_date"] == "2026-05-19"
    assert row["player_name"] == "Aaron Judge"
    assert row["player_team"] == "New York Yankees"
    assert row["opponent"] == "Toronto Blue Jays"
    assert row["over_prob"] == 0.6
    assert row["draftkings_sportsbook"]["one_sided_milestone"] is True


def test_bettingpros_market_aliases_and_normalization(tmp_path):
    assert parse_bettingpros_market_ids("hits,total_bases,pitcher_strikeouts,stolen_bases") == (287, 293, 285, 294)
    assert parse_bettingpros_book_ids("major") == (10, 12, 19, 24, 14)

    payload = {
        "_atlas_fetch": {"source": "bettingpros_mlb_props", "game_date": "2026-05-19"},
        "books": [
            {"id": 0, "slug": "bettingpros", "display_name": "Consensus"},
            {"id": 10, "slug": "fanduel", "display_name": "FanDuel"},
            {"id": 12, "slug": "draftkings", "display_name": "DraftKings"},
        ],
        "markets": [{"id": 287, "slug": "hits"}],
        "events": [
            {
                "id": 98644,
                "scheduled": "2026-05-20 00:40:00",
                "home": "BOS",
                "visitor": "NYY",
            }
        ],
        "props": [
            {
                "sport": "MLB",
                "market_id": 287,
                "event_id": 98644,
                "participant": {
                    "id": "123",
                    "name": "Sample Hitter",
                    "player": {"team": "BOS"},
                },
                "over": {
                    "line": 1.5,
                    "odds": -115,
                    "consensus_line": 1.5,
                    "consensus_odds": -120,
                    "probability": 0.8,
                },
                "under": {
                    "line": 1.5,
                    "odds": 105,
                    "consensus_line": 1.5,
                    "consensus_odds": 100,
                    "probability": 0.2,
                },
                "projection": {"value": 2.2, "recommended_side": "over", "probability": 0.8},
            }
        ],
        "offers": [
            {
                "event_id": 98644,
                "market_id": 287,
                "player_id": 123,
                "selections": [
                    {
                        "selection": "over",
                        "books": [
                            {"id": 10, "lines": [{"active": True, "is_off": False, "line": 1.5, "cost": -120}]},
                            {"id": 12, "lines": [{"active": True, "is_off": False, "line": 1.5, "cost": -115}]},
                        ],
                    },
                    {
                        "selection": "under",
                        "books": [
                            {"id": 10, "lines": [{"active": True, "is_off": False, "line": 1.5, "cost": 110}]},
                            {"id": 12, "lines": [{"active": True, "is_off": False, "line": 1.5, "cost": 105}]},
                        ],
                    },
                ],
            }
        ],
    }

    normalized = normalize_bettingpros_mlb_props(payload, snapshot_id="bp_snap")
    assert normalized["row_count"] == 1
    row = normalized["rows"][0]
    assert row["source"] == "bettingpros_mlb_props"
    assert row["market"] == "hits"
    assert row["line"] == 1.5
    assert row["game_date"] == "2026-05-19"
    assert row["n_books"] == 2
    assert row["home_team"] == "BOS"
    assert row["away_team"] == "NYY"
    assert 0.52 < row["over_prob"] < 0.54
    assert row["bettingpros_projection"]["projection_probability"] == 0.8

    snapshot = write_raw_snapshot(source="bettingpros_mlb_props", payload=payload, request={}, root=tmp_path)
    written = write_bettingpros_mlb_normalization(Path(snapshot.path), root=tmp_path, run_id="bettingpros_20260518_run")
    assert written["row_count"] == 1
    assert written["compatible_artifact"] == "oddsapi_props.jsonl"
    assert Path(written["rows_path"]).exists()


def test_bettingpros_backfill_dry_run_is_credit_free():
    result = backfill_bettingpros_result(
        start_date=date(2026, 5, 11),
        end_date=date(2026, 5, 12),
        markets="hits,pitcher_strikeouts",
        dry_run=True,
    )
    assert result.payload["date_count"] == 2
    assert result.payload["market_count"] == 2
    assert result.payload["include_offers"] is False
    assert result.payload["imported"] == []


def test_oddsapi_market_defaults_and_normalization(tmp_path):
    assert "batter_hits" in parse_markets("default")
    assert parse_bookmakers("default") == ("prizepicks", "draftkings", "fanduel")
    assert parse_bookmakers("all") == ()

    payload = _sample_oddsapi_payload()
    normalized = normalize_oddsapi_mlb_props(
        payload,
        snapshot_id="odds_snap",
        source="oddsapi_mlb_live",
        pulled_at_utc="2026-05-11T00:00:00Z",
    )
    assert normalized["row_count"] == 1
    row = normalized["rows"][0]
    assert row["player_name"] == "Sample Hitter"
    assert row["market"] == "hits"
    assert row["line"] == 1.5
    assert row["n_books"] == 2
    assert row["game_date"] == "2026-05-11"
    assert 0.0 < row["over_prob"] < 1.0

    snapshot = write_raw_snapshot(source="oddsapi_mlb_live", payload=payload, request={}, root=tmp_path)
    written = write_oddsapi_mlb_normalization(Path(snapshot.path), root=tmp_path, run_id="oddsapi_run")
    assert written["row_count"] == 1
    assert Path(written["rows_path"]).exists()


def test_oddsapi_backfill_dry_run_estimates_without_key():
    result = backfill_oddsapi_result(
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 2),
        markets="batter_hits,pitcher_strikeouts",
        dry_run=True,
    )
    assert result.payload["date_count"] == 2
    assert result.payload["estimated_credits_upper_bound"] == 602


def test_parlayapi_market_aliases_and_normalization():
    assert parse_parlayapi_markets("hits,total_bases,pitcher_strikeouts") == (
        "player_hits",
        "player_total_bases",
        "player_strikeouts",
    )
    payload = {
        "_atlas_fetch": {
            "source": "parlayapi_mlb_historical_closing_props",
            "sport_key": "baseball_mlb",
            "snapshot_timestamp": "2026-05-12T18:00:00Z",
        },
        "responses": [
            {
                "market": "player_total_bases",
                "response": {
                    "payload": [
                        {
                            "game_date": "2026-05-12",
                            "sport_key": "baseball_mlb",
                            "home_team": "Cleveland Guardians",
                            "away_team": "Los Angeles Angels",
                            "commence_time": "2026-05-12T22:10:00.000Z",
                            "bookmaker": "draftkings",
                            "bookmaker_title": "DraftKings",
                            "player": "Sample Hitter",
                            "market_key": "player_total_bases",
                            "market_label": "Total Bases",
                            "line": 1.5,
                            "over_odds": 120,
                            "under_odds": -150,
                        },
                        {
                            "game_date": "2026-05-12",
                            "sport_key": "baseball_mlb",
                            "home_team": "Cleveland Guardians",
                            "away_team": "Los Angeles Angels",
                            "commence_time": "2026-05-12T22:10:00.000Z",
                            "bookmaker": "betmgm",
                            "bookmaker_title": "BetMGM",
                            "player": "Sample Hitter",
                            "market_key": "player_total_bases",
                            "market_label": "Total Bases",
                            "line": 1.5,
                            "over_odds": 125,
                            "under_odds": -155,
                        },
                        {
                            "game_date": "2026-05-12",
                            "home_team": "Cleveland Guardians",
                            "away_team": "Los Angeles Angels",
                            "bookmaker": "bet365",
                            "player": "{optionTypeAbbr}{value} Total Bases",
                            "market_key": "player_total_bases",
                            "line": 1.5,
                            "over_odds": 135,
                            "under_odds": -180,
                        },
                    ]
                },
            }
        ],
    }
    normalized = normalize_parlayapi_mlb_closing_props(payload, snapshot_id="parlay_snap")
    assert normalized["row_count"] == 1
    assert normalized["rejected_count"] == 1
    row = normalized["rows"][0]
    assert row["source"] == "parlayapi_mlb_historical_closing_props"
    assert row["market"] == "total_bases"
    assert row["player_name"] == "Sample Hitter"
    assert row["line"] == 1.5
    assert row["n_books"] == 2
    assert row["home_team"] == "Cleveland Guardians"
    assert row["away_team"] == "Los Angeles Angels"


def test_rotowire_context_requests_and_normalization(tmp_path):
    requests = build_rotowire_mlb_context_requests(
        game_date="2026-05-15",
        pages=("daily_lineups", "bullpen_usage"),
    )
    assert [request.page for request in requests] == ["daily_lineups", "bullpen_usage", "bullpen_usage_table"]
    assert requests[0].params["date"] == "2026-05-15"
    assert requests[0].url.endswith("/baseball/daily-lineups.php")

    payload = {
        "source": "rotowire_mlb_context",
        "sport": "MLB",
        "game_date": "2026-05-15",
        "data": [
            {
                "page": "daily_lineups",
                "url": "https://www.rotowire.com/baseball/daily-lineups.php",
                "resolved_url": "https://www.rotowire.com/baseball/daily-lineups.php?date=2026-05-15",
                "status_code": 200,
                "content_type": "text/html",
                "body": _sample_rotowire_daily_lineups_html(),
            },
            {
                "page": "bullpen_usage",
                "url": "https://www.rotowire.com/baseball/bullpen-usage.php",
                "resolved_url": "https://www.rotowire.com/baseball/bullpen-usage.php?date=2026-05-15",
                "status_code": 200,
                "content_type": "text/html",
                "body": "<html><body>raw bullpen page</body></html>",
            },
            {
                "page": "bullpen_usage_table",
                "url": "https://www.rotowire.com/baseball/tables/bullpen-usage.php",
                "resolved_url": "https://www.rotowire.com/baseball/tables/bullpen-usage.php?date=2026-05-15",
                "status_code": 200,
                "content_type": "application/json",
                "body": _sample_rotowire_bullpen_usage_table_json(),
            },
        ],
    }
    normalized = normalize_rotowire_mlb_context(payload, snapshot_id="rotowire_snap")
    assert len(normalized["daily_lineups"]) == 4
    assert len(normalized["pitchers"]) == 2
    assert len(normalized["batting_orders"]) == 4
    assert len(normalized["bullpens"]) == 1
    assert len(normalized["environment"]) == 1
    assert normalized["daily_lineups"][0]["player_name"] == "Sample Leadoff"
    assert normalized["pitchers"][0]["pitcher_name"] == "Sample Away Pitcher"
    assert normalized["bullpens"][0]["team_abbr"] == "NYY"
    assert normalized["bullpens"][0]["bullpen_fatigue_score"] > 0.0
    assert normalized["environment"][0]["umpire_text"].startswith("Umpire: Sample Umpire")

    snapshot = write_raw_snapshot(source="rotowire_mlb_context", payload=payload, request={}, root=tmp_path)
    written = write_rotowire_mlb_normalization(Path(snapshot.path), root=tmp_path, run_id="rotowire_run")
    assert written["row_counts"]["daily_lineups"] == 4
    assert written["row_counts"]["pitchers"] == 2
    assert written["row_counts"]["bullpens"] == 1
    assert Path(written["artifacts"]["daily_lineups"]).exists()


def test_covers_weather_normalization_writes_environment_context(tmp_path):
    html = _sample_covers_weather_html()
    normalized = normalize_covers_mlb_weather_html(html, snapshot_id="covers_snap")

    assert normalized["source"] == "covers_mlb_weather"
    assert normalized["game_dates"] == ["2026-05-16"]
    assert len(normalized["environment"]) == 1
    row = normalized["environment"][0]
    assert row["away_team_abbr"] == "TOR"
    assert row["home_team_abbr"] == "DET"
    assert row["venue_name"] == "Comerica Park"
    assert row["temperature_f"] == 64.8
    assert row["wind_speed_mph"] == 10.6
    assert row["wind_direction"] == "NW"
    assert row["weather_text"] == "Weather: cloudy 64.8° Wind 10.6 mph NW"

    source_path = tmp_path / "MLBweather.txt"
    source_path.write_text(html, encoding="utf-8")
    written = write_covers_mlb_weather_normalization(source_path, root=tmp_path, run_id="covers_run")
    assert written["row_counts"]["environment"] == 1
    assert Path(written["artifacts"]["environment"]).exists()


def test_wunderground_url_capture_and_history_normalization():
    text = (
        "https://cm.g.doubleclick.net/partnerpixels?url="
        "https%3A%2F%2Fwww.wunderground.com%2Fhistory%2Fdaily%2Fus%2Fmo%2Fst.-louis%2FKCPS%2Fdate%2F2026-4-17"
    )
    urls = extract_wunderground_history_urls(text)

    assert urls == [
        {
            "url": "https://www.wunderground.com/history/daily/us/mo/st.-louis/KCPS/date/2026-4-17",
            "path": "us/mo/st.-louis",
            "station_id": "KCPS",
            "game_date": "2026-04-17",
        }
    ]

    payload = _sample_wunderground_history_payload()
    normalized = normalize_wunderground_history_weather(payload, snapshot_id="wu_snap")

    assert normalized["source"] == "wunderground_history_weather"
    assert normalized["context_timing"] == "historical_observed_weather_backfill"
    assert normalized["weather_content_timing"] == "observed_game_time_weather"
    assert normalized["game_dates"] == ["2026-04-17"]
    row = normalized["environment"][0]
    assert row["home_team_abbr"] == "STL"
    assert row["away_team_abbr"] == "NYM"
    assert row["temperature_f"] == 72.0
    assert row["wind_speed_mph"] == 11.0
    assert row["wind_direction"] == "SSE"
    assert row["weather_text"] == "Weather: Fair 72° Wind 11 mph SSE"
    assert "historical_observed_weather_backfill" in row["flags"]


def test_baseball_reference_url_builder_maps_statsapi_team_codes():
    assert (
        baseball_reference_boxscore_url(game_date="2026-04-01", home_team="Arizona Diamondbacks")
        == "https://www.baseball-reference.com/boxes/ARI/ARI202604010.shtml"
    )
    assert (
        baseball_reference_boxscore_url(game_date="2026-05-01", home_team="Chicago Cubs", game_number=2)
        == "https://www.baseball-reference.com/boxes/CHN/CHN202605011.shtml"
    )


def test_espn_game_context_requests_and_normalization(tmp_path):
    requests = build_espn_game_context_requests(game_date="2026-05-11")
    assert len(requests) == 1
    assert requests[0].params["dates"] == "20260511"

    payload = _sample_espn_game_context_payload()
    normalized = normalize_espn_game_context(payload, snapshot_id="espn_snap")

    assert normalized["source"] == "espn_game_context"
    assert normalized["context_timing"] == "postgame_backfill"
    assert len(normalized["batting_orders"]) == 2
    assert len(normalized["pitchers"]) == 2
    assert len(normalized["environment"]) == 1
    assert normalized["batting_orders"][0]["lineup_status_key"] == "confirmed_postgame_backfill"
    assert normalized["environment"][0]["umpire_text"] == "Umpire: Sample Umpire"

    snapshot = write_raw_snapshot(source="espn_game_context", payload=payload, request={}, root=tmp_path)
    written = write_espn_game_context_normalization(Path(snapshot.path), root=tmp_path, run_id="espn_run")
    assert written["row_counts"]["batting_orders"] == 2
    assert written["row_counts"]["pitchers"] == 2
    assert written["context_timing"] == "postgame_backfill"
    assert Path(written["artifacts"]["batting_orders"]).exists()


def test_baseball_reference_boxscore_normalization_extracts_pregame_lineups(tmp_path):
    payload = _sample_baseball_reference_boxscore_payload()
    normalized = normalize_baseball_reference_boxscore(payload, snapshot_id="bref_snap")

    assert normalized["source"] == "baseball_reference_boxscore_context"
    assert normalized["context_timing"] == "historical_pregame_lineup_backfill"
    assert normalized["lineup_content_timing"] == "pregame_starting_lineup"
    assert normalized["game_dates"] == ["2026-04-01"]
    assert len(normalized["batting_orders"]) == 18
    assert len(normalized["pitchers"]) == 2

    first = normalized["batting_orders"][0]
    assert first["team_abbr"] == "DET"
    assert first["opponent_abbr"] == "AZ"
    assert first["batting_order"] == 1
    assert first["player_name"] == "Colt Keith"
    assert first["bref_player_id"] == "keithco01"
    assert first["lineup_status_key"] == "confirmed_starting_lineup"

    pitcher = normalized["pitchers"][0]
    assert pitcher["team_abbr"] == "DET"
    assert pitcher["pitcher_name"] == "Tarik Skubal"
    assert pitcher["lineup_status_key"] == "confirmed_starting_pitcher"

    snapshot = write_raw_snapshot(
        source="baseball_reference_boxscore_context",
        payload=payload,
        request={"url": "https://www.baseball-reference.com/boxes/ARI/ARI202604010.shtml"},
        root=tmp_path,
    )
    written = write_baseball_reference_boxscore_normalization(Path(snapshot.path), root=tmp_path, run_id="bref_run")
    assert written["row_counts"]["batting_orders"] == 18
    assert written["row_counts"]["pitchers"] == 2
    assert written["context_timing"] == "historical_pregame_lineup_backfill"
    assert written["lineup_content_timing"] == "pregame_starting_lineup"
    assert Path(written["artifacts"]["batting_orders"]).exists()


def test_espn_player_gamelog_normalization_builds_statsapi_like_rows():
    rows = normalize_espn_player_gamelog(
        {
            "_atlas_fetch": {
                "source": "espn_player_gamelog",
                "athlete_id": "4666100",
                "season": 2026,
                "player_context": {"player_name": "Zach Neto", "team_abbreviation": "LAA", "position": "SS"},
            },
            "names": [
                "atBats",
                "runs",
                "hits",
                "doubles",
                "triples",
                "homeRuns",
                "RBIs",
                "walks",
                "hitByPitch",
                "strikeouts",
                "stolenBases",
                "caughtStealing",
            ],
            "events": {
                "401815372": {
                    "id": "401815372",
                    "gameDate": "2026-05-17T20:07:00.000+00:00",
                    "atVs": "vs",
                    "team": {"id": "3", "displayName": "Los Angeles Angels", "abbreviation": "LAA"},
                    "opponent": {"id": "19", "displayName": "Los Angeles Dodgers", "abbreviation": "LAD"},
                }
            },
            "seasonTypes": [
                {
                    "categories": [
                        {
                            "events": [
                                {
                                    "eventId": "401815372",
                                    "stats": ["5", "1", "2", "1", "0", "1", "3", "1", "0", "2", "0", "0"],
                                }
                            ]
                        }
                    ]
                }
            ],
        }
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "espn_player_gamelog"
    assert row["group"] == "hitting"
    assert row["espn_player_id"] == "4666100"
    assert row["game_date"] == "2026-05-17"
    assert row["player_team"] == "LAA"
    assert row["opponent_abbreviation"] == "LAD"
    assert row["stat"]["plateAppearances"] == 6
    assert row["stat"]["totalBases"] == 6


def test_legacy_prizepicks_import_keeps_files_in_separate_source_bucket(tmp_path):
    source_dir = tmp_path / "atlas_raw"
    source_dir.mkdir()
    in_range = source_dir / "prizepicks_20260501_120000.json"
    out_of_range = source_dir / "prizepicks_20260429_120000.json"
    in_range.write_text(json.dumps({"data": [{"id": "proj1"}], "included": []}), encoding="utf-8")
    out_of_range.write_text(json.dumps({"data": [{"id": "proj2"}], "included": []}), encoding="utf-8")

    result = import_legacy_prizepicks_raw_result(
        source_dir=source_dir,
        start_date=date(2026, 4, 30),
        end_date=date(2026, 5, 11),
        root=tmp_path / "mlb_dev",
    )

    assert result.payload["source_name"] == "legacy_prizepicks_nba"
    assert result.payload["imported_count"] == 1
    assert result.payload["total_records"] == 1

    imported_path = Path(result.payload["imported"][0]["payload_path"])
    manifest = load_snapshot_manifest(imported_path)
    assert "legacy_prizepicks_nba" in imported_path.parts
    assert manifest["source"] == "legacy_prizepicks_nba"
    assert manifest["request"]["legacy_filename"] == "prizepicks_20260501_120000.json"


def _sample_prizepicks_payload():
    return {
        "data": [
            {
                "type": "projection",
                "id": "proj1",
                "attributes": {
                    "line_score": 1.5,
                    "stat_type": "Hits",
                    "start_time": "2026-05-11T18:10:00.000-04:00",
                    "status": "pre_game",
                    "odds_type": "standard",
                },
                "relationships": {
                    "new_player": {"data": {"type": "new_player", "id": "player1"}},
                    "game": {"data": {"type": "game", "id": "game1"}},
                },
            },
            {
                "type": "projection",
                "id": "proj2",
                "attributes": {
                    "line_score": 10.0,
                    "stat_type": "Unsupported Widget",
                },
                "relationships": {
                    "new_player": {"data": {"type": "new_player", "id": "player1"}},
                    "game": {"data": {"type": "game", "id": "game1"}},
                },
            },
        ],
        "included": [
            {
                "type": "new_player",
                "id": "player1",
                "attributes": {
                    "display_name": "Sample Hitter",
                    "team": "BOS",
                    "position": "IF",
                },
            },
            {
                "type": "game",
                "id": "game1",
                "attributes": {
                    "start_time": "2026-05-11T18:10:00.000-04:00",
                    "metadata": {
                        "game_info": {
                            "teams": {
                                "home": {"abbreviation": "BOS"},
                                "away": {"abbreviation": "NYY"},
                            }
                        }
                    },
                },
            },
        ],
    }


def _normalized_row(projection_id: str, game_date: str) -> dict:
    return {
        "snapshot_id": "prizepicks_20260516T065109Z",
        "source_projection_id": projection_id,
        "event_id": "game1",
        "league": "MLB",
        "game_date": game_date,
        "start_time_utc": f"{game_date}T23:10:00Z",
        "player_id": projection_id.replace("proj_", ""),
        "player_name": "Sample Hitter",
        "player_team": "BOS",
        "opponent": "NYY",
        "market": "hits",
        "source_market": "Hits",
        "line": 1.5,
        "tier": "STANDARD",
        "status": "pre_game",
        "player_position": "IF",
        "is_live": False,
        "is_combo": False,
        "updated_at": "",
        "pulled_at_utc": "2026-05-16T06:51:09Z",
    }


def _sample_oddsapi_payload():
    event_payload = {
        "id": "event1",
        "sport_key": "baseball_mlb",
        "commence_time": "2026-05-12T00:40:00Z",
        "home_team": "Boston Red Sox",
        "away_team": "New York Yankees",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "last_update": "2026-05-11T20:00:00Z",
                "markets": [
                    {
                        "key": "batter_hits",
                        "outcomes": [
                            {"name": "Over", "description": "Sample Hitter", "point": 1.5, "price": 120},
                            {"name": "Under", "description": "Sample Hitter", "point": 1.5, "price": -150},
                        ],
                    }
                ],
            },
            {
                "key": "fanduel",
                "title": "FanDuel",
                "last_update": "2026-05-11T20:01:00Z",
                "markets": [
                    {
                        "key": "batter_hits",
                        "outcomes": [
                            {"name": "Over", "description": "Sample Hitter", "point": 1.5, "price": 115},
                            {"name": "Under", "description": "Sample Hitter", "point": 1.5, "price": -145},
                        ],
                    }
                ],
            },
            {
                "key": "betmgm",
                "title": "BetMGM",
                "last_update": "2026-05-11T20:02:00Z",
                "markets": [
                    {
                        "key": "batter_hits",
                        "outcomes": [
                            {"name": "Over", "description": "Sample Hitter", "point": 1.5, "price": 100},
                            {"name": "Under", "description": "Sample Hitter", "point": 1.5, "price": -130},
                        ],
                    }
                ],
            },
        ],
    }
    return {
        "_atlas_fetch": {
            "source": "oddsapi_mlb_live",
            "sport_key": "baseball_mlb",
            "regions": "us",
            "markets": ["batter_hits"],
        },
        "events": {"payload": [{"id": "event1"}], "status_code": 200, "url": "https://example.test", "quota": {}},
        "event_odds": [
            {
                "event_id": "event1",
                "response": {
                    "payload": event_payload,
                    "status_code": 200,
                    "url": "https://example.test",
                    "quota": {},
                },
            }
        ],
    }


def _sample_espn_game_context_payload():
    competition = {
        "id": "event1",
        "date": "2026-05-11T23:10Z",
        "venue": {"fullName": "Sample Park"},
        "competitors": [
            {
                "homeAway": "away",
                "team": {"abbreviation": "NYY", "displayName": "New York Yankees"},
                "probables": [{"athlete": {"id": "sp1", "displayName": "Sample Away Pitcher"}}],
            },
            {
                "homeAway": "home",
                "team": {"abbreviation": "BOS", "displayName": "Boston Red Sox"},
                "probables": [{"athlete": {"id": "sp2", "displayName": "Sample Home Pitcher"}}],
            },
        ],
    }
    return {
        "source": "espn_game_context",
        "sport": "MLB",
        "game_date": "2026-05-11",
        "scoreboard": {"payload": {"events": [{"id": "event1", "date": "2026-05-11T23:10Z", "competitions": [competition]}]}},
        "summaries": [
            {
                "event_id": "event1",
                "payload": {
                    "id": "event1",
                    "header": {"competitions": [competition]},
                    "gameInfo": {
                        "venue": {"fullName": "Sample Park"},
                        "officials": [
                            {
                                "displayName": "Sample Umpire",
                                "position": {"name": "Home Plate Umpire", "displayName": "Home Plate Umpire"},
                            }
                        ],
                    },
                    "boxscore": {
                        "players": [
                            {
                                "team": {"abbreviation": "NYY", "displayName": "New York Yankees"},
                                "statistics": [
                                    {
                                        "type": "batting",
                                        "athletes": [
                                            {
                                                "starter": True,
                                                "batOrder": 1,
                                                "athlete": {"id": "h1", "displayName": "Sample Hitter"},
                                                "position": {"abbreviation": "CF"},
                                            }
                                        ],
                                    },
                                    {
                                        "type": "pitching",
                                        "labels": ["IP", "ERA"],
                                        "athletes": [
                                            {
                                                "starter": True,
                                                "athlete": {
                                                    "id": "sp1",
                                                    "displayName": "Sample Away Pitcher",
                                                    "throws": "RHP",
                                                },
                                                "stats": ["6.0", "3.25"],
                                            }
                                        ],
                                    },
                                ],
                            },
                            {
                                "team": {"abbreviation": "BOS", "displayName": "Boston Red Sox"},
                                "statistics": [
                                    {
                                        "type": "batting",
                                        "athletes": [
                                            {
                                                "starter": True,
                                                "batOrder": 2,
                                                "athlete": {"id": "h2", "displayName": "Home Hitter"},
                                                "position": {"abbreviation": "SS"},
                                            }
                                        ],
                                    },
                                    {
                                        "type": "pitching",
                                        "labels": ["IP", "ERA"],
                                        "athletes": [
                                            {
                                                "starter": True,
                                                "athlete": {
                                                    "id": "sp2",
                                                    "displayName": "Sample Home Pitcher",
                                                    "throws": "LHP",
                                                },
                                                "stats": ["5.0", "4.10"],
                                            }
                                        ],
                                    },
                                ],
                            },
                        ]
                    },
                },
            }
        ],
    }


def _sample_baseball_reference_boxscore_payload():
    return {
        "source": "baseball_reference_boxscore_context",
        "sport": "MLB",
        "game_date": "",
        "data": [
            {
                "source": "baseball_reference_boxscore_context",
                "page": "boxscore",
                "url": "https://www.baseball-reference.com/boxes/ARI/ARI202604010.shtml",
                "resolved_url": "https://www.baseball-reference.com/boxes/ARI/ARI202604010.shtml",
                "status_code": 200,
                "content_type": "text/html",
                "body": """
<html>
<body>
<h1>Detroit Tigers vs Arizona Diamondbacks Box Score: April  1, 2026</h1>
<div class="grid_wrapper commented" id="all_lineups">
<div class="section_heading assoc_lineups" id="lineups_sh">
<span class="section_anchor" id="lineups_link" data-label="Starting Lineups"></span><h2>Starting Lineups</h2>
</div><!-- <div data-no-overall-control class="data_grid " id="div_lineups">
<div class="data_grid_group solo">
<div id="lineups_1" class="data_grid_box">
<table>
<caption>Tigers</caption>
<tr><td>1</td><td><a href="/players/k/keithco01.shtml">Colt Keith</a></td><td>1B</td></tr>
<tr><td>2</td><td><a href="/players/m/mcgonke01.shtml">Kevin McGonigle</a></td><td>3B</td></tr>
<tr><td>3</td><td><a href="/players/t/torregl01.shtml">Gleyber Torres</a></td><td>2B</td></tr>
<tr><td>4</td><td><a href="/players/g/greenri03.shtml">Riley Greene</a></td><td>DH</td></tr>
<tr><td>5</td><td><a href="/players/d/dingldi01.shtml">Dillon Dingler</a></td><td>C</td></tr>
<tr><td>6</td><td><a href="/players/c/carpeke01.shtml">Kerry Carpenter</a></td><td>RF</td></tr>
<tr><td>7</td><td><a href="/players/v/vierlma01.shtml">Matt Vierling</a></td><td>LF</td></tr>
<tr><td>8</td><td><a href="/players/m/meadopa01.shtml">Parker Meadows</a></td><td>CF</td></tr>
<tr><td>9</td><td><a href="/players/b/baezja01.shtml">Javier Baez</a></td><td>SS</td></tr>
<tr><td></td><td><a href="/players/s/skubata01.shtml">Tarik Skubal</a></td><td>P</td></tr>
</table>
</div><div id="lineups_2" class="data_grid_box">
<table>
<caption>Diamondbacks</caption>
<tr><td>1</td><td><a href="/players/m/marteke01.shtml">Ketel Marte</a></td><td>DH</td></tr>
<tr><td>2</td><td><a href="/players/c/carroco02.shtml">Corbin Carroll</a></td><td>RF</td></tr>
<tr><td>3</td><td><a href="/players/p/perdoge01.shtml">Geraldo Perdomo</a></td><td>SS</td></tr>
<tr><td>4</td><td><a href="/players/m/morenga01.shtml">Gabriel Moreno</a></td><td>C</td></tr>
<tr><td>5</td><td><a href="/players/v/vargail01.shtml">Ildemaro Vargas</a></td><td>2B</td></tr>
<tr><td>6</td><td><a href="/players/a/arenano01.shtml">Nolan Arenado</a></td><td>3B</td></tr>
<tr><td>7</td><td><a href="/players/f/fernajo06.shtml">Jose Fernandez</a></td><td>1B</td></tr>
<tr><td>8</td><td><a href="/players/t/tawati01.shtml">Tim Tawa</a></td><td>LF</td></tr>
<tr><td>9</td><td><a href="/players/l/lawlajo01.shtml">Jordan Lawlar</a></td><td>CF</td></tr>
<tr><td></td><td><a href="/players/g/galleza01.shtml">Zac Gallen</a></td><td>P</td></tr>
</table>
</div>
</div>
</div>--></div>
</body>
</html>
""",
            }
        ],
    }


def _sample_rotowire_daily_lineups_html():
    return """
    <div class="lineup is-mlb">
      <div class="lineup__meta"><div class="lineup__time">7:05 PM ET</div></div>
      <div class="lineup__box">
        <div class="lineup__top">
          <div class="lineup__teams">
            <div class="lineup__team is-visit">
              <img class="lineup__logo" src="away.png" alt="BOS">
              <div class="lineup__abbr">BOS</div>
            </div>
            <div class="lineup__team is-home">
              <img class="lineup__logo" src="home.png" alt="NYY">
              <div class="lineup__abbr">NYY</div>
            </div>
          </div>
        </div>
        <a href="/baseball/box-score/yankees-vs-red-sox-2026-05-15-1" class="lineup__matchup">
          <div class="lineup__mteam is-visit">Red Sox <span class="lineup__wl">(1-0)</span></div>
          <div class="lineup__mteam is-home">Yankees <span class="lineup__wl">(0-1)</span></div>
        </a>
        <div class="lineup__main">
          <ul class="lineup__list is-visit">
            <li class="lineup__player-highlight mb-0">
              <div class="lineup__player-highlight-name">
                <a href="/baseball/player/sample-away-pitcher-1001">Sample Away Pitcher</a>
                <span class="lineup__throws">R</span>
              </div>
              <div class="lineup__player-highlight-stats">2-1&nbsp;3.20 ERA</div>
            </li>
            <li class="lineup__status is-confirmed"><div></div>Confirmed Lineup</li>
            <li class="lineup__player">
              <div class="lineup__pos">CF</div>
              <a title="Sample Leadoff" href="/baseball/player/sample-leadoff-2001">S. Leadoff</a>
              <span class="lineup__bats">L</span>
            </li>
            <li class="lineup__player">
              <div class="lineup__pos">SS</div>
              <a title="Sample Two" href="/baseball/player/sample-two-2002">Sample Two</a>
              <span class="lineup__bats">R</span>
            </li>
            <li>
              <button class="see-pitcher-intel" data-pid="1001" data-gid="game123" data-team="BOS">
                Starting Pitcher Intel
              </button>
            </li>
          </ul>
          <ul class="lineup__list is-home">
            <li class="lineup__player-highlight mb-0">
              <div class="lineup__player-highlight-name">
                <a href="/baseball/player/sample-home-pitcher-1002">Sample Home Pitcher</a>
                <span class="lineup__throws">L</span>
              </div>
              <div class="lineup__player-highlight-stats">4-0&nbsp;2.10 ERA</div>
            </li>
            <li class="lineup__status is-expected"><div></div>Expected Lineup</li>
            <li class="lineup__player">
              <div class="lineup__pos">RF</div>
              <a title="Home One" href="/baseball/player/home-one-3001">Home One</a>
              <span class="lineup__bats">S</span>
            </li>
            <li class="lineup__player">
              <div class="lineup__pos">1B</div>
              <a title="Home Two" href="/baseball/player/home-two-3002">Home Two</a>
              <span class="lineup__bats">R</span>
            </li>
          </ul>
        </div>
        <div class="lineup__bottom">
          <div class="lineup__umpire"><b>Umpire:</b>&nbsp;<a>Sample Umpire</a> &nbsp;9.1 R/G &nbsp;17.7 K/G</div>
          <div class="lineup__weather-text"><b>0% </b>65&deg;&nbsp;&nbsp;Wind 7 mph R-L</div>
          <div class="lineup__odds-item"><b>LINE</b>&nbsp;<span class="composite hide">NYY -135</span></div>
          <div class="lineup__odds-item"><b>O/U</b>&nbsp;<span class="composite hide">9.0 Runs</span></div>
        </div>
      </div>
    </div>
    """


def _sample_covers_weather_html():
    return """
    <div class="col-xs-12 covers-CoversWeather-dateHeader">May 16, 2026</div>
    <div class="col-md-6 col-xs-12 covers-CoversWeather-brick">
      <div class="col-md-12 col-xs-12 covers-CoversWeather-brickHeader">
        <img class="covers-CoversWeather-teamLogoLeft" alt="Toronto" src="tor.svg">
        <span class="covers-CoversWeather-TeamsMobile">
          TOR <span class="covers-coversweather-line">-104</span>
          @ DET <span class="covers-coversweather-line">-104</span>
        </span>
        <img class="covers-CoversWeather-teamLogoRight" alt="Detroit" src="det.svg">
        <span class="covers-coversweather-line">O/U 8</span>
        <span class="covers-CoversWeatherPage-time">1:10 PM ET</span>
      </div>
      <div class="covers-coversweather-fieldContainer covers-coversweather-fieldMLB">
        <img class="covers-coversweather-windDirectionIcon" src="https://img.covers.com/covers/data/wind_icons/nw.png">
      </div>
      <div class="covers-coversweatherPage-fieldBrickDetails">
        <div class="covers-coversweatherPage-fieldName">Comerica Park</div>
        Wind: 10.6 mph
      </div>
      <div class="col-md-4 col-xs-12 covers-CoversWeatherPage-conditionsContainer">
        <img alt="Weather Icon" class="covers-CoversWeatherPage-weatherImg" src="https://img.covers.com/weather/dark_sky/cloudy.png">
        <div>
          <div class="covers-coversweatherPage-Temp"><span>64.8 °F</span></div>
          <div>Humidity: 79.10 %</div>
          <div>P.O.P.: 0 %</div>
        </div>
      </div>
      <a class="covers-CoversWeatherPage-matchup" href="https://www.covers.com/sport/baseball/mlb/matchup/369618">Matchup</a>
    </div>
    """


def _sample_wunderground_history_payload():
    return {
        "source": "wunderground_history_weather",
        "data": [
            {
                "game_context": {
                    "game_pk": 1,
                    "official_date": "2026-04-17",
                    "game_date": "2026-04-17T18:15:00Z",
                    "away_team_name": "New York Mets",
                    "home_team_name": "St. Louis Cardinals",
                    "venue_name": "Busch Stadium",
                },
                "station": {"station_id": "KCPS", "country": "US", "location_id": "KCPS:9:US"},
                "status_code": 200,
                "payload": {
                    "observations": [
                        {
                            "obs_id": "KCPS",
                            "obs_name": "Cahokia/St. Louis",
                            "valid_time_gmt": 1776438000,
                            "temp": 65,
                            "wx_phrase": "Fair",
                            "rh": 70,
                            "wdir": 140,
                            "wdir_cardinal": "SE",
                            "wspd": 6,
                            "precip_hrly": 0,
                        },
                        {
                            "obs_id": "KCPS",
                            "obs_name": "Cahokia/St. Louis",
                            "valid_time_gmt": 1776449700,
                            "temp": 72,
                            "wx_phrase": "Fair",
                            "rh": 55,
                            "wdir": 150,
                            "wdir_cardinal": "SSE",
                            "wspd": 11,
                            "precip_hrly": 0,
                        },
                    ]
                },
            }
        ],
    }


def _sample_rotowire_bullpen_usage_table_json():
    return json.dumps(
        {
            "NYY": [
                {
                    "playerID": "4001",
                    "player": "Reliever One",
                    "team": "NYY",
                    "inj": "",
                    "last2": 15,
                    "last3": 42,
                    "last5": 55,
                    "day5": 13,
                    "day4": 0,
                    "day3": 27,
                    "day2": 15,
                    "day1": 0,
                },
                {
                    "playerID": "4002",
                    "player": "Reliever Two",
                    "team": "NYY",
                    "inj": "",
                    "last2": 0,
                    "last3": 31,
                    "last5": 31,
                    "day5": 0,
                    "day4": 0,
                    "day3": 31,
                    "day2": 0,
                    "day1": 0,
                },
            ]
        }
    )
