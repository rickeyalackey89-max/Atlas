"""System Atlas Value/EV slip builder policy."""

from __future__ import annotations

from .contracts import FamilyBuilderPolicy


POLICY = FamilyBuilderPolicy(
    name="System",
    purpose="atlas_value_ev",
    probability_weight=0.35,
    prior_weight=0.42,
    bettingpros_weight=0.03,
    stability_weight=0.09,
    fragility_weight=0.06,
    edge_weight=0.11,
    prop_identifier_weight=0.02,
    tier_bonus={"GOBLIN": 0.04, "STANDARD": 0.02, "DEMON": -0.10},
    market_bonus={
        "hitter_fantasy_score": 0.02,
        "pitching_outs": 0.01,
        "pitcher_strikeouts": 0.03,
        "total_bases": 0.01,
        "hits_runs_rbis": 0.03,
        "plate_appearances": 0.02,
    },
    market_penalty={
        "pitches_thrown": 0.08,
        "pitcher_fantasy_score": 0.04,
        "hits_allowed": 0.03,
    },
    segment_bonus={
        ("GOBLIN", "pitching_outs"): 0.01,
    },
    segment_penalty={
        ("STANDARD", "plate_appearances"): 0.05,
        ("STANDARD", "hits"): 0.04,
        ("STANDARD", "hits_allowed"): 0.06,
        ("STANDARD", "hitter_fantasy_score"): 0.04,
        ("STANDARD", "total_bases"): 0.04,
        ("STANDARD", "pitching_outs"): 0.03,
    },
    min_probability_by_tier={"GOBLIN": 0.63, "STANDARD": 0.58, "DEMON": 0.61},
    min_edge=0.01,
)
