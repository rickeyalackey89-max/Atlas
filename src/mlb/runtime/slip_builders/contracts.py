"""Shared contracts for MLB slip family builders."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FamilyBuilderPolicy:
    name: str
    purpose: str
    probability_weight: float
    prior_weight: float
    bettingpros_weight: float
    stability_weight: float
    fragility_weight: float
    edge_weight: float
    prop_identifier_weight: float
    tier_bonus: dict[str, float]
    market_bonus: dict[str, float]
    market_penalty: dict[str, float]
    segment_bonus: dict[tuple[str, str], float]
    segment_penalty: dict[tuple[str, str], float]
    min_probability_by_tier: dict[str, float]
    min_edge: float = 0.0


def policy_to_manifest(policy: FamilyBuilderPolicy) -> dict[str, object]:
    return {
        "purpose": policy.purpose,
        "signal_weights": {
            "model_probability": policy.probability_weight,
            "tier_market_side_prior": policy.prior_weight,
            "bettingpros_context_score": policy.bettingpros_weight,
            "stability_score": policy.stability_weight,
            "inverse_fragility_score": policy.fragility_weight,
            "edge_score": policy.edge_weight,
            "prop_market_identifier": policy.prop_identifier_weight,
        },
        "tier_bonus": dict(policy.tier_bonus),
        "market_bonus": dict(policy.market_bonus),
        "market_penalty": dict(policy.market_penalty),
        "segment_bonus": _stringify_segment_adjustments(policy.segment_bonus),
        "segment_penalty": _stringify_segment_adjustments(policy.segment_penalty),
        "min_probability_by_tier": dict(policy.min_probability_by_tier),
        "min_edge": policy.min_edge,
    }


def _stringify_segment_adjustments(values: dict[tuple[str, str], float]) -> dict[str, float]:
    return {f"{tier}:{market}": value for (tier, market), value in sorted(values.items())}
