"""BigSwings independent Demon pick board policy."""

from __future__ import annotations

from .contracts import FamilyBuilderPolicy


POLICY = FamilyBuilderPolicy(
    name="BigSwings",
    purpose="independent_high_upside_demon_pick_board",
    probability_weight=0.40,
    prior_weight=0.22,
    bettingpros_weight=0.07,
    stability_weight=0.05,
    fragility_weight=0.03,
    edge_weight=0.13,
    prop_identifier_weight=0.02,
    tier_bonus={"DEMON": 0.20, "GOBLIN": -1.00, "STANDARD": -1.00},
    market_bonus={
        "total_bases": 0.10,
        "singles": 0.08,
        "runs": 0.07,
        "rbis": 0.06,
        "hits_runs_rbis": 0.05,
        "pitcher_strikeouts": 0.03,
    },
    market_penalty={
        "hitter_fantasy_score": 0.08,
        "pitcher_fantasy_score": 0.08,
        "pitches_thrown": 0.08,
        "hits_allowed": 0.06,
    },
    segment_bonus={
        ("DEMON", "total_bases"): 0.12,
        ("DEMON", "singles"): 0.10,
        ("DEMON", "runs"): 0.08,
        ("DEMON", "rbis"): 0.07,
    },
    segment_penalty={
        ("DEMON", "hitter_fantasy_score"): 0.08,
        ("DEMON", "pitcher_fantasy_score"): 0.08,
        ("DEMON", "pitcher_strikeouts"): 0.06,
        ("DEMON", "pitching_outs"): 0.06,
        ("DEMON", "walks_allowed"): 0.08,
    },
    min_probability_by_tier={"DEMON": 0.56},
    min_edge=0.0,
)
