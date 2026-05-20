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
