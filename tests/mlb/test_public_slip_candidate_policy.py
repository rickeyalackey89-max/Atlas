from mlb.runtime import slips


def _standard_under_row(**overrides):
    row = {
        "market": "runs",
        "side": "UNDER",
        "tier": "STANDARD",
        "status": "pre_game",
        "model_probability": 0.62,
        "edge": 0.12,
        "external_market_context_available": False,
        "market_context_source_type": "prizepicks_line_only",
    }
    row.update(overrides)
    return row


def test_marketed_standard_under_requires_probability_floor_or_strong_context():
    assert not slips._public_candidate(_standard_under_row(), family="Marketed")

    assert slips._public_candidate(
        _standard_under_row(model_probability=0.64),
        family="Marketed",
    )

    assert slips._public_candidate(
        _standard_under_row(
            model_probability=0.63,
            external_market_context_available=True,
            market_context_source_type="external_bettingpros_mlb_props",
            bettingpros_recommended_side="under",
        ),
        family="Marketed",
    )


def test_marketed_standard_under_rejects_weak_external_context():
    assert not slips._public_candidate(
        _standard_under_row(
            external_market_context_available=True,
            market_context_source_type="external_bettingpros_mlb_props",
        ),
        family="Marketed",
    )


def test_standard_under_guard_is_marketed_only():
    assert slips._public_candidate(_standard_under_row(model_probability=0.59), family="System")
