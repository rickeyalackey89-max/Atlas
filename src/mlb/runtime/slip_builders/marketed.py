"""Marketed premium slip builder policy."""

from __future__ import annotations

from .contracts import FamilyBuilderPolicy


POLICY = FamilyBuilderPolicy(
    name="Marketed",
    purpose="premium_public_picks",
    # Strict-fidelity 2026-04-26..05-20 baseball-context v12 + CAT v11 overlay
    # selected marketed_prob_edge_plus. Marketed is customer-facing, so it now
    # leans harder into calibrated probability/edge and requires stronger tier
    # floors instead of allowing broad prior-heavy shapes.
    probability_weight=0.59,
    prior_weight=0.08,
    bettingpros_weight=0.15,
    stability_weight=0.10,
    fragility_weight=0.07,
    edge_weight=0.17,
    prop_identifier_weight=0.02,
    tier_bonus={"GOBLIN": 0.06, "STANDARD": 0.03, "DEMON": -0.02},
    market_bonus={
        "hitter_fantasy_score": 0.03,
        "total_bases": 0.02,
        "singles": 0.03,
        "runs": 0.02,
        "pitcher_strikeouts": 0.02,
        "plate_appearances": 0.02,
        "hits": 0.02,
    },
    market_penalty={
        "pitches_thrown": 0.12,
        "pitcher_fantasy_score": 0.08,
        "hits_allowed": 0.07,
        "walks_allowed": 0.03,
    },
    segment_bonus={
        ("STANDARD", "pitcher_strikeouts"): 0.05,
        ("STANDARD", "pitching_outs"): 0.02,
        ("DEMON", "singles"): 0.04,
        ("DEMON", "hits_runs_rbis"): 0.01,
    },
    segment_penalty={
        ("DEMON", "pitcher_strikeouts"): 0.10,
        ("DEMON", "pitching_outs"): 0.10,
        ("DEMON", "pitcher_fantasy_score"): 0.12,
        ("STANDARD", "hitter_fantasy_score"): 0.03,
        ("STANDARD", "total_bases"): 0.03,
    },
    min_probability_by_tier={"GOBLIN": 0.71, "STANDARD": 0.67, "DEMON": 0.64},
    min_edge=0.03,
)
