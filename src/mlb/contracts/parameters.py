"""Parameter contracts for MLB simulation inputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class OpportunityEstimate:
    """Baseline opportunity estimate attached before probability scoring."""

    market_group: str
    opportunity_type: str
    projected_opportunity: float
    opportunity_floor: float
    opportunity_ceiling: float
    opportunity_confidence: float
    opportunity_fragility_score: float
    opportunity_model_version: str
    flags: tuple[str, ...]

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)
