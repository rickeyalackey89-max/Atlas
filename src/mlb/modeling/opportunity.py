"""Baseline opportunity estimates for the MLB simulation layer."""

from __future__ import annotations

from typing import Any

from mlb.contracts.engine import EngineBoardRow
from mlb.contracts.parameters import OpportunityEstimate
from mlb.domain.markets import BATTER_MARKETS, COMBO_MARKETS, GAME_MARKETS, PITCHER_MARKETS

OPPORTUNITY_MODEL_VERSION = "baseline_opportunity_v0"


def estimate_opportunity(value: EngineBoardRow | dict[str, Any]) -> OpportunityEstimate:
    """Estimate player opportunity before simulation.

    This v0 model intentionally uses conservative defaults. It creates the
    contract for later lineup slot, batting order, pitcher leash, injury, and
    weather models without pretending those sources are available yet.
    """

    market = _field(value, "market")
    line = _float(_field(value, "line"))
    status = _field(value, "status").lower()
    tier = _field(value, "tier").upper()
    group = market_group_for_market(market)
    flags = ["baseline_opportunity_defaults"]

    if group == "batter":
        estimate = _batter_opportunity(market, line)
    elif group == "pitcher":
        estimate = _pitcher_opportunity(market, line)
    elif group == "game":
        estimate = ("inning_exposure", 1.0, 1.0, 1.0, 0.45, 0.30)
        flags.append("game_market_single_inning")
    elif group == "combo":
        estimate = ("combo_component_exposure", 1.0, 0.0, 2.0, 0.20, 0.65)
        flags.append("combo_market_low_context")
    else:
        estimate = ("unknown_market_exposure", 1.0, 0.0, 2.0, 0.10, 0.80)
        flags.append("unknown_market_group")

    opportunity_type, projected, floor, ceiling, confidence, fragility = estimate

    if status not in {"", "active", "available", "pre_game"}:
        confidence *= 0.70
        fragility = min(1.0, fragility + 0.15)
        flags.append(f"status_{status}")
    if tier and tier != "STANDARD":
        confidence *= 0.90
        fragility = min(1.0, fragility + 0.05)
        flags.append(f"tier_{tier.lower()}")

    return OpportunityEstimate(
        market_group=group,
        opportunity_type=opportunity_type,
        projected_opportunity=round(projected, 4),
        opportunity_floor=round(floor, 4),
        opportunity_ceiling=round(ceiling, 4),
        opportunity_confidence=round(_clamp(confidence, 0.0, 1.0), 4),
        opportunity_fragility_score=round(_clamp(fragility, 0.0, 1.0), 4),
        opportunity_model_version=OPPORTUNITY_MODEL_VERSION,
        flags=tuple(flags),
    )


def market_group_for_market(market: str) -> str:
    if market in BATTER_MARKETS:
        return "batter"
    if market in PITCHER_MARKETS:
        return "pitcher"
    if market in GAME_MARKETS:
        return "game"
    if market in COMBO_MARKETS:
        return "combo"
    return "unknown"


def _batter_opportunity(market: str, line: float) -> tuple[str, float, float, float, float, float]:
    if market == "plate_appearances" and line > 0:
        return ("plate_appearances", line, max(0.0, line - 1.0), line + 1.0, 0.55, 0.25)
    return ("plate_appearances_proxy", 4.20, 3.00, 5.30, 0.35, 0.42)


def _pitcher_opportunity(market: str, line: float) -> tuple[str, float, float, float, float, float]:
    if market == "pitches_thrown" and line > 0:
        return ("pitch_count", line, max(0.0, line - 15.0), line + 15.0, 0.50, 0.35)
    if market == "pitching_outs" and line > 0:
        return ("pitching_outs", line, max(0.0, line - 3.0), line + 3.0, 0.48, 0.38)
    return ("pitching_outs_proxy", 17.00, 12.00, 21.00, 0.30, 0.55)


def _field(value: EngineBoardRow | dict[str, Any], name: str) -> str:
    raw = getattr(value, name) if isinstance(value, EngineBoardRow) else value.get(name)
    if raw is None:
        return ""
    return str(raw).strip()


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
