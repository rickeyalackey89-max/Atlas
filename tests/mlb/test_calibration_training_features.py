from mlb.modeling.calibration import training_feature_row


def test_training_feature_row_prefers_uncalibrated_probability_when_present():
    row = training_feature_row(
        {
            "market": "hits",
            "tier": "STANDARD",
            "target_over_probability": 0.61,
            "uncalibrated_target_over_probability": 0.54,
        }
    )

    assert row["base_over_probability"] == 0.54


def test_training_feature_row_falls_back_to_target_probability_without_overlay():
    row = training_feature_row(
        {
            "market": "hits",
            "tier": "STANDARD",
            "target_over_probability": 0.61,
        }
    )

    assert row["base_over_probability"] == 0.61


def test_training_feature_row_carries_market_source_features():
    row = training_feature_row(
        {
            "market": "hitter_fantasy_score",
            "tier": "STANDARD",
            "target_over_probability": 0.55,
            "line": 7.5,
        },
        {
            "market_context_source_type": "external_draftkings_mlb_pick6",
            "external_market_context_source": "draftkings_mlb_pick6",
            "external_market_context_available": True,
            "prizepicks_line_only_market_context": False,
        },
    )

    assert row["market_context_source_type"] == "external_draftkings_mlb_pick6"
    assert row["external_market_context_source"] == "draftkings_mlb_pick6"
    assert row["line_bucket"] == "line_5_7.5"
    assert row["feature_market_source_is_dk_pick6"] == 1.0
    assert row["feature_market_source_is_dk_sportsbook"] == 0.0
    assert row["feature_market_source_is_external"] == 1.0
    assert row["feature_market_source_is_prizepicks_only"] == 0.0
    assert row["feature_prizepicks_line_only_market_context"] == 0.0


def test_training_feature_row_carries_matchup_detail_features():
    row = training_feature_row(
        {
            "market": "hits",
            "tier": "STANDARD",
            "target_over_probability": 0.55,
            "line": 0.5,
        },
        {
            "batter_bats": "L",
            "starter_throws": "R",
            "handedness_matchup_type": "L_vs_R",
            "lineup_probability": 0.99,
            "batting_order_slot": 2,
            "top_order_flag": True,
            "platoon_advantage": 1.0,
            "park_hr_factor": 1.12,
            "home_plate_umpire": "Sample Ump",
            "umpire_rating": "hitter_friendly",
            "pitcher_prop_context_available": True,
            "pitcher_workload_context_score": -0.18,
            "pitcher_opponent_confirmed_batters": 7,
        },
    )

    assert row["batter_bats"] == "L"
    assert row["starter_throws"] == "R"
    assert row["handedness_matchup_type"] == "L_vs_R"
    assert row["home_plate_umpire"] == "Sample Ump"
    assert row["umpire_rating"] == "hitter_friendly"
    assert row["feature_lineup_probability"] == 0.99
    assert row["feature_batting_order_slot"] == 2.0
    assert row["feature_top_order_flag"] == 1.0
    assert row["feature_platoon_advantage"] == 1.0
    assert row["feature_park_hr_factor"] == 1.12
    assert row["feature_pitcher_prop_context_available"] == 1.0
    assert row["feature_pitcher_workload_context_score"] == -0.18
    assert row["feature_pitcher_opponent_confirmed_batters"] == 7.0
