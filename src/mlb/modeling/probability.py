"""Starter probability kernel for Atlas MLB.

This is a context-free baseline. It exists to lock the scoring contract and
runtime shape before the feature table, CAT/GBM models, and calibrated kernels
exist. It should be replaced by trained market kernels without changing the
``ProbabilityResult`` contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, log
from typing import Any

from mlb.contracts.engine import EngineBoardRow
from mlb.contracts.probability import ProbabilityInput, ProbabilityResult
from mlb.contracts.simulation import MarketSimulationInput
from mlb.domain.playability import is_over_only_tier, normalize_tier
from mlb.modeling.opportunity import estimate_opportunity
from mlb.modeling.qmc import default_distribution_for_market, simulate_market

KERNEL_VERSION = "mlb_market_prior_sobol_qmc_v0"
MODEL_VERSION = "mlb-dev-baseline-0.1"
METHOD = "market_prior_sobol_qmc_baseline"
PARAMETER_MODEL_VERSION = "market_prior_parameters_v0"
CALIBRATION_VERSION = "uncalibrated_v0"
DEFAULT_SIMULATION_N = 2048


@dataclass(frozen=True)
class MarketPriorProfile:
    anchor_line: float
    anchor_over_probability: float
    slope: float
    lower_bound: float = 0.03
    upper_bound: float = 0.97

    def over_probability(self, line: float) -> float:
        logit_value = _logit(self.anchor_over_probability) - self.slope * (line - self.anchor_line)
        return _clamp(_sigmoid(logit_value), self.lower_bound, self.upper_bound)


MARKET_PRIOR_PROFILES: dict[str, MarketPriorProfile] = {
    "hits": MarketPriorProfile(anchor_line=0.5, anchor_over_probability=0.61, slope=1.10),
    "singles": MarketPriorProfile(anchor_line=0.5, anchor_over_probability=0.43, slope=1.15),
    "doubles": MarketPriorProfile(anchor_line=0.5, anchor_over_probability=0.18, slope=1.35),
    "triples": MarketPriorProfile(anchor_line=0.5, anchor_over_probability=0.035, slope=1.70, lower_bound=0.01),
    "total_bases": MarketPriorProfile(anchor_line=1.5, anchor_over_probability=0.42, slope=0.55),
    "hits_runs_rbis": MarketPriorProfile(anchor_line=1.5, anchor_over_probability=0.52, slope=0.48),
    "runs": MarketPriorProfile(anchor_line=0.5, anchor_over_probability=0.38, slope=0.95),
    "rbis": MarketPriorProfile(anchor_line=0.5, anchor_over_probability=0.34, slope=0.95),
    "home_runs": MarketPriorProfile(anchor_line=0.5, anchor_over_probability=0.11, slope=1.35),
    "plate_appearances": MarketPriorProfile(anchor_line=4.5, anchor_over_probability=0.44, slope=0.55),
    "walks": MarketPriorProfile(anchor_line=0.5, anchor_over_probability=0.31, slope=1.00),
    "stolen_bases": MarketPriorProfile(anchor_line=0.5, anchor_over_probability=0.075, slope=1.45, lower_bound=0.01),
    "hitter_strikeouts": MarketPriorProfile(anchor_line=0.5, anchor_over_probability=0.60, slope=0.82),
    "hitter_fantasy_score": MarketPriorProfile(anchor_line=7.5, anchor_over_probability=0.50, slope=0.18),
    "pitcher_strikeouts": MarketPriorProfile(anchor_line=5.5, anchor_over_probability=0.50, slope=0.24),
    "pitching_outs": MarketPriorProfile(anchor_line=17.5, anchor_over_probability=0.50, slope=0.20),
    "hits_allowed": MarketPriorProfile(anchor_line=5.5, anchor_over_probability=0.49, slope=0.26),
    "earned_runs_allowed": MarketPriorProfile(anchor_line=2.5, anchor_over_probability=0.45, slope=0.40),
    "walks_allowed": MarketPriorProfile(anchor_line=1.5, anchor_over_probability=0.47, slope=0.55),
    "pitches_thrown": MarketPriorProfile(anchor_line=85.5, anchor_over_probability=0.50, slope=0.035),
    "pitcher_fantasy_score": MarketPriorProfile(anchor_line=32.5, anchor_over_probability=0.50, slope=0.055),
    "first_inning_runs_allowed": MarketPriorProfile(anchor_line=0.5, anchor_over_probability=0.26, slope=1.05),
    "first_inning_walks_allowed": MarketPriorProfile(anchor_line=0.5, anchor_over_probability=0.15, slope=1.25),
    "pitcher_strikeouts_combo": MarketPriorProfile(anchor_line=5.5, anchor_over_probability=0.50, slope=0.20),
    "pitcher_strikeouts_plus_total_bases": MarketPriorProfile(anchor_line=7.5, anchor_over_probability=0.50, slope=0.18),
}


def probability_input_from_engine_row(row: EngineBoardRow, parameter_row: dict[str, Any] | None = None) -> ProbabilityInput:
    opportunity = estimate_opportunity(row)
    parameter_row = parameter_row or {}
    return ProbabilityInput(
        market=row.market,
        line=row.line,
        tier=row.tier,
        status=row.status,
        is_live=row.is_live,
        is_combo=row.is_combo,
        seed_key="|".join(
            [
                row.snapshot_id,
                row.source_projection_id,
                row.event_id,
                row.player_id,
                row.market,
                str(row.line),
                row.tier,
            ]
        ),
        target_over_probability=_optional_float(parameter_row.get("target_over_probability")),
        distribution=str(parameter_row.get("distribution") or ""),
        simulation_n=_int(parameter_row.get("simulation_n")),
        parameter_model_version=str(parameter_row.get("parameter_model_version") or ""),
        calibration_version=str(parameter_row.get("calibration_version") or ""),
        opportunity_model_version=opportunity.opportunity_model_version,
        opportunity_type=opportunity.opportunity_type,
        projected_opportunity=opportunity.projected_opportunity,
        opportunity_confidence=opportunity.opportunity_confidence,
        opportunity_fragility_score=opportunity.opportunity_fragility_score,
        lineup_score=_optional_float(parameter_row.get("lineup_score")) or 0.0,
        starter_matchup_score=_optional_float(parameter_row.get("starter_matchup_score")) or 0.0,
        bullpen_matchup_score=_optional_float(parameter_row.get("bullpen_matchup_score")) or 0.0,
        environment_score=_optional_float(parameter_row.get("environment_score")) or 0.0,
        matchup_composite_score=_optional_float(parameter_row.get("matchup_composite_score")) or 0.0,
        matchup_confidence=_optional_float(parameter_row.get("matchup_confidence")) or 0.0,
        matchup_target_shift=_optional_float(parameter_row.get("matchup_target_shift")) or 0.0,
        matchup_context_available=_bool(parameter_row.get("matchup_context_available")),
    )


def score_probability(value: ProbabilityInput | EngineBoardRow) -> ProbabilityResult:
    """Score one candidate with the current context-free prior kernel."""

    probability_input = probability_input_from_engine_row(value) if isinstance(value, EngineBoardRow) else value
    profile = MARKET_PRIOR_PROFILES.get(probability_input.market)
    flags = ["context_free_baseline", "sobol_qmc_baseline"]

    if profile is None:
        profile = MarketPriorProfile(anchor_line=probability_input.line, anchor_over_probability=0.50, slope=0.20)
        flags.append("unknown_market_profile")

    tier = normalize_tier(probability_input.tier)
    if tier != "STANDARD":
        flags.append(f"tier_{tier.lower()}")
    if probability_input.is_live:
        flags.append("live_projection")
    if probability_input.is_combo:
        flags.append("combo_projection")
    if probability_input.status.lower() not in {"", "active", "available", "pre_game"}:
        flags.append(f"status_{probability_input.status.lower()}")
    if probability_input.opportunity_model_version:
        flags.append(f"opportunity_{probability_input.opportunity_model_version}")
    if probability_input.opportunity_type:
        flags.append(f"opportunity_type_{probability_input.opportunity_type}")
    if probability_input.matchup_context_available:
        flags.append("matchup_context_applied")
    else:
        flags.append("matchup_context_unavailable")

    if probability_input.target_over_probability is None:
        target_over_probability = profile.over_probability(probability_input.line)
        flags.append("parameter_fallback_market_prior")
    else:
        target_over_probability = _clamp(float(probability_input.target_over_probability), 0.001, 0.999)
        flags.append("parameter_table_target")
    distribution = probability_input.distribution or default_distribution_for_market(probability_input.market)
    simulation_n = probability_input.simulation_n or DEFAULT_SIMULATION_N
    parameter_model_version = probability_input.parameter_model_version or PARAMETER_MODEL_VERSION
    calibration_version = probability_input.calibration_version or CALIBRATION_VERSION
    if calibration_version == CALIBRATION_VERSION:
        flags.append("uncalibrated")
    else:
        flags.append("calibrated_parameter_table")
        if "cat" in calibration_version.lower() or "residual" in calibration_version.lower():
            flags.append("cat_probability_calibrated")
    simulation = simulate_market(
        MarketSimulationInput(
            market=probability_input.market,
            line=probability_input.line,
            target_over_probability=target_over_probability,
            distribution=distribution,
            simulation_n=simulation_n,
            seed_key=probability_input.seed_key
            or f"{probability_input.market}|{probability_input.line}|{probability_input.tier}|{distribution}",
        )
    )
    flags.extend(simulation.flags)

    over_probability = simulation.p_over
    under_probability = simulation.p_under
    push_probability = simulation.p_push
    if is_over_only_tier(tier):
        recommended_side = "over"
        model_probability = over_probability
        flags.append("playable_side_over_only")
    else:
        recommended_side = "over" if over_probability >= under_probability else "under"
        model_probability = max(over_probability, under_probability)
    fair_decimal = round(1.0 / model_probability, 4)
    fair_american = _american_price(model_probability)
    edge = round(model_probability - 0.5, 6)

    return ProbabilityResult(
        over_probability=round(over_probability, 6),
        under_probability=round(under_probability, 6),
        push_probability=round(push_probability, 6),
        recommended_side=recommended_side,
        model_probability=round(model_probability, 6),
        mean_projection=simulation.mean_projection,
        median_projection=simulation.median_projection,
        p10=simulation.p10,
        p25=simulation.p25,
        p75=simulation.p75,
        p90=simulation.p90,
        volatility_score=simulation.volatility_score,
        fragility_score=simulation.fragility_score,
        stability_score=simulation.stability_score,
        opportunity_model_version=probability_input.opportunity_model_version,
        opportunity_type=probability_input.opportunity_type,
        projected_opportunity=round(probability_input.projected_opportunity, 4),
        opportunity_confidence=round(probability_input.opportunity_confidence, 4),
        opportunity_fragility_score=round(probability_input.opportunity_fragility_score, 4),
        lineup_score=round(probability_input.lineup_score, 6),
        starter_matchup_score=round(probability_input.starter_matchup_score, 6),
        bullpen_matchup_score=round(probability_input.bullpen_matchup_score, 6),
        environment_score=round(probability_input.environment_score, 6),
        matchup_composite_score=round(probability_input.matchup_composite_score, 6),
        matchup_confidence=round(probability_input.matchup_confidence, 6),
        matchup_target_shift=round(probability_input.matchup_target_shift, 6),
        matchup_context_available=probability_input.matchup_context_available,
        simulation_n=simulation.simulation_n,
        simulation_seed=simulation.simulation_seed,
        simulation_kernel_version=simulation.simulation_kernel_version,
        parameter_model_version=parameter_model_version,
        calibration_version=calibration_version,
        fair_decimal=fair_decimal,
        fair_american=fair_american,
        edge=edge,
        confidence_tier=_confidence_tier(edge),
        kernel_version=KERNEL_VERSION,
        model_version=MODEL_VERSION,
        method=METHOD,
        flags=tuple(flags),
    )


def _confidence_tier(edge: float) -> str:
    if edge >= 0.18:
        return "high"
    if edge >= 0.10:
        return "medium"
    return "low"


def _american_price(probability: float) -> int:
    probability = _clamp(probability, 0.001, 0.999)
    if probability >= 0.5:
        return int(round(-100 * probability / (1.0 - probability)))
    return int(round(100 * (1.0 - probability) / probability))


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + exp(-value))


def _logit(probability: float) -> float:
    probability = _clamp(probability, 0.001, 0.999)
    return log(probability / (1.0 - probability))


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)
