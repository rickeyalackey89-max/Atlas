from __future__ import annotations

import pandas as pd

from Atlas.core.under_visibility_gate import under_visibility_mask


def _cfg() -> dict:
    return {
        "slip_build": {
            "under_visibility": {
                "enabled": True,
                "standard_only": True,
                "require_exact_market": True,
                "min_market_prob": 0.515,
                "min_model_prob": 0.56,
                "max_model_prob": 0.68,
                "max_q_out_frac": 0.0,
                "max_minute_risk_score": 0.35,
                "excluded_stats": ["FTA"],
            }
        }
    }


def test_under_visibility_requires_exact_market_support_for_unders_only() -> None:
    rows = pd.DataFrame(
        [
            {
                "player": "Market Supported Under",
                "direction": "UNDER",
                "tier": "STANDARD",
                "stat": "REB",
                "p_cal": 0.61,
                "external_prior_sources": "bettingpros_market",
                "external_prior_market_prob": 0.53,
                "q_out_frac": 0.0,
                "minute_risk_score": 0.0,
            },
            {
                "player": "Atlas Only Under",
                "direction": "UNDER",
                "tier": "STANDARD",
                "stat": "REB",
                "p_cal": 0.64,
                "external_prior_sources": "",
                "external_prior_market_prob": None,
                "q_out_frac": 0.0,
                "minute_risk_score": 0.0,
            },
            {
                "player": "Over Always Visible",
                "direction": "OVER",
                "tier": "GOBLIN",
                "stat": "PTS",
                "p_cal": 0.50,
                "external_prior_sources": "",
                "external_prior_market_prob": None,
                "q_out_frac": 0.0,
                "minute_risk_score": 0.0,
            },
        ]
    )

    mask = under_visibility_mask(rows, _cfg(), section="slip_build", probability_col="p_cal")

    assert mask.tolist() == [True, False, True]


def test_under_visibility_blocks_noisy_unders_even_with_market_support() -> None:
    rows = pd.DataFrame(
        [
            {
                "player": "Too Injury Noisy",
                "direction": "UNDER",
                "tier": "STANDARD",
                "stat": "AST",
                "p_cal": 0.61,
                "external_prior_sources": "bettingpros_market",
                "external_prior_market_prob": 0.54,
                "q_out_frac": 0.5,
                "minute_risk_score": 0.0,
            },
            {
                "player": "Market Disagrees",
                "direction": "UNDER",
                "tier": "STANDARD",
                "stat": "PRA",
                "p_cal": 0.62,
                "external_prior_sources": "bettingpros_market",
                "external_prior_market_prob": 0.49,
                "q_out_frac": 0.0,
                "minute_risk_score": 0.0,
            },
            {
                "player": "Overconfident Tail",
                "direction": "UNDER",
                "tier": "STANDARD",
                "stat": "PR",
                "p_cal": 0.74,
                "external_prior_sources": "bettingpros_market",
                "external_prior_market_prob": 0.56,
                "q_out_frac": 0.0,
                "minute_risk_score": 0.0,
            },
        ]
    )

    mask = under_visibility_mask(rows, _cfg(), section="slip_build", probability_col="p_cal")

    assert mask.tolist() == [False, False, False]

