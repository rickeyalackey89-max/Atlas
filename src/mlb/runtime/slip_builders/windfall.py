"""Windfall flex slip builder policy."""

from __future__ import annotations

from .contracts import FamilyBuilderPolicy


POLICY = FamilyBuilderPolicy(
    name="Windfall",
    purpose="flex_upside_best_of_both_worlds",
    # Strict-fidelity 2026-05-16..20 baseball-context trainer selected the
    # family_best_context_combo profile: Windfall should lean harder into
    # calibrated probability once weak Demon segments are blocked.
    probability_weight=0.48,
    prior_weight=0.27,
    bettingpros_weight=0.01,
    stability_weight=0.08,
    fragility_weight=0.05,
    edge_weight=0.17,
    prop_identifier_weight=0.02,
    tier_bonus={"DEMON": 0.08, "GOBLIN": 0.04, "STANDARD": 0.02},
    market_bonus={
        "total_bases": 0.04,
        "singles": 0.05,
        "hitter_fantasy_score": 0.02,
        "runs": 0.04,
        "pitcher_strikeouts": 0.04,
        "earned_runs_allowed": 0.03,
    },
    market_penalty={
        "pitches_thrown": 0.04,
        "pitcher_fantasy_score": 0.03,
        "hits_allowed": 0.02,
    },
    segment_bonus={
        ("DEMON", "runs"): 0.10,
        ("DEMON", "total_bases"): 0.05,
        ("DEMON", "singles"): 0.06,
        ("DEMON", "hits_runs_rbis"): 0.02,
        ("STANDARD", "pitcher_strikeouts"): 0.05,
        ("STANDARD", "earned_runs_allowed"): 0.04,
        ("STANDARD", "hitter_fantasy_score"): 0.01,
    },
    segment_penalty={
        ("STANDARD", "singles"): 0.08,
        ("DEMON", "pitcher_strikeouts"): 0.12,
        ("DEMON", "pitching_outs"): 0.10,
        ("DEMON", "pitcher_fantasy_score"): 0.12,
    },
    min_probability_by_tier={"GOBLIN": 0.62, "STANDARD": 0.57, "DEMON": 0.58},
    min_edge=0.0,
)
