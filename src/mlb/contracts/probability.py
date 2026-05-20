"""Probability kernel contracts for Atlas MLB."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProbabilityInput:
    """Probability input consumed by the simulation kernel.

    The first MLB implementation can still fall back to market priors, but the
    preferred path is to pass explicit parameter-table values into this
    contract. That keeps scoring tied to the replayable parameter artifact.
    """

    market: str
    line: float
    tier: str = "STANDARD"
    status: str = "active"
    is_live: bool = False
    is_combo: bool = False
    seed_key: str = ""
    target_over_probability: Optional[float] = None
    distribution: str = ""
    simulation_n: int = 0
    parameter_model_version: str = ""
    calibration_version: str = ""
    opportunity_model_version: str = ""
    opportunity_type: str = ""
    projected_opportunity: float = 0.0
    opportunity_confidence: float = 0.0
    opportunity_fragility_score: float = 0.0
    lineup_score: float = 0.0
    starter_matchup_score: float = 0.0
    bullpen_matchup_score: float = 0.0
    environment_score: float = 0.0
    matchup_composite_score: float = 0.0
    matchup_confidence: float = 0.0
    matchup_target_shift: float = 0.0
    matchup_context_available: bool = False


@dataclass(frozen=True)
class ProbabilityResult:
    """Probability output consumed by the scoring engine."""

    over_probability: float
    under_probability: float
    push_probability: float
    recommended_side: str
    model_probability: float
    mean_projection: float
    median_projection: float
    p10: float
    p25: float
    p75: float
    p90: float
    volatility_score: float
    fragility_score: float
    stability_score: float
    opportunity_model_version: str
    opportunity_type: str
    projected_opportunity: float
    opportunity_confidence: float
    opportunity_fragility_score: float
    lineup_score: float
    starter_matchup_score: float
    bullpen_matchup_score: float
    environment_score: float
    matchup_composite_score: float
    matchup_confidence: float
    matchup_target_shift: float
    matchup_context_available: bool
    simulation_n: int
    simulation_seed: int
    simulation_kernel_version: str
    parameter_model_version: str
    calibration_version: str
    fair_decimal: float
    fair_american: int
    edge: float
    confidence_tier: str
    kernel_version: str
    model_version: str
    method: str
    flags: tuple[str, ...]
