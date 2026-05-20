"""Sobol / Quasi-Monte Carlo probability helpers for Atlas MLB.

This module is the first narrow simulation shell. It intentionally uses simple
market-prior parameters; future parameter models should feed richer inputs into
this same deterministic simulation boundary.
"""

from __future__ import annotations

import hashlib
from math import log2

import numpy as np
from scipy import optimize
from scipy.stats import norm, poisson, qmc

from mlb.contracts.simulation import MarketSimulationInput, MarketSimulationResult

SIMULATION_KERNEL_VERSION = "mlb_sobol_qmc_market_prior_v0"

COUNT_DISTRIBUTIONS = {
    "hits",
    "singles",
    "doubles",
    "triples",
    "total_bases",
    "hits_runs_rbis",
    "runs",
    "rbis",
    "home_runs",
    "plate_appearances",
    "walks",
    "stolen_bases",
    "hitter_strikeouts",
    "pitcher_strikeouts",
    "pitching_outs",
    "hits_allowed",
    "earned_runs_allowed",
    "walks_allowed",
    "pitches_thrown",
    "first_inning_runs_allowed",
    "first_inning_walks_allowed",
    "pitcher_strikeouts_combo",
    "pitcher_strikeouts_plus_total_bases",
}

NORMAL_DISTRIBUTIONS = {
    "hitter_fantasy_score",
    "pitcher_fantasy_score",
}


def default_distribution_for_market(market: str) -> str:
    if market in NORMAL_DISTRIBUTIONS:
        return "normal"
    return "poisson" if market in COUNT_DISTRIBUTIONS else "normal"


def simulate_market(input_value: MarketSimulationInput) -> MarketSimulationResult:
    """Simulate one market using a deterministic Sobol sequence."""

    simulation_n = _validate_power_of_two(input_value.simulation_n)
    seed = input_value.seed if input_value.seed is not None else _stable_seed(input_value.seed_key or _seed_key(input_value))
    target = _clamp(input_value.target_over_probability, 0.001, 0.999)
    units = _sobol_unit_interval(simulation_n, seed)
    flags = ["sobol_qmc", f"distribution_{input_value.distribution}"]

    if input_value.distribution == "poisson":
        mean = _solve_poisson_mean(line=input_value.line, target_over_probability=target)
        samples = poisson.ppf(units, mu=mean)
    elif input_value.distribution == "normal":
        sigma = _normal_sigma(input_value.market, input_value.line)
        mean = input_value.line + sigma * norm.ppf(target)
        samples = np.maximum(norm.ppf(units, loc=mean, scale=sigma), 0.0)
    else:
        raise ValueError(f"Unsupported simulation distribution: {input_value.distribution!r}")

    p_over = float(np.mean(samples > input_value.line))
    p_push = float(np.mean(samples == input_value.line))
    p_under = float(np.mean(samples < input_value.line))
    p10, p25, median, p75, p90 = np.percentile(samples, [10, 25, 50, 75, 90])
    mean_projection = float(np.mean(samples))
    volatility = _volatility_score(p10=float(p10), p90=float(p90), line=input_value.line)
    fragility = _fragility_score(target=target, volatility=volatility, line=input_value.line)
    stability = _clamp(1.0 - fragility, 0.0, 1.0)

    return MarketSimulationResult(
        p_over=round(p_over, 6),
        p_under=round(p_under, 6),
        p_push=round(p_push, 6),
        mean_projection=round(mean_projection, 6),
        median_projection=round(float(median), 6),
        p10=round(float(p10), 6),
        p25=round(float(p25), 6),
        p75=round(float(p75), 6),
        p90=round(float(p90), 6),
        volatility_score=round(volatility, 6),
        fragility_score=round(fragility, 6),
        stability_score=round(stability, 6),
        simulation_n=simulation_n,
        simulation_seed=seed,
        simulation_kernel_version=SIMULATION_KERNEL_VERSION,
        distribution=input_value.distribution,
        flags=tuple(flags),
    )


def _sobol_unit_interval(simulation_n: int, seed: int) -> np.ndarray:
    engine = qmc.Sobol(d=1, scramble=True, seed=seed)
    values = engine.random_base2(m=int(log2(simulation_n))).reshape(-1)
    return np.clip(values, 1e-9, 1.0 - 1e-9)


def _solve_poisson_mean(*, line: float, target_over_probability: float) -> float:
    def objective(mu: float) -> float:
        return float(1.0 - poisson.cdf(line, mu=mu) - target_over_probability)

    try:
        return float(optimize.brentq(objective, 1e-6, 100.0, maxiter=100))
    except ValueError:
        return max(0.001, line)


def _normal_sigma(market: str, line: float) -> float:
    if market in {"pitches_thrown"}:
        return max(8.0, abs(line) * 0.12)
    if market in {"pitcher_fantasy_score", "hitter_fantasy_score"}:
        return max(4.0, abs(line) * 0.25)
    return max(1.0, abs(line) * 0.30)


def _volatility_score(*, p10: float, p90: float, line: float) -> float:
    denominator = max(abs(line), 1.0)
    return _clamp((p90 - p10) / denominator, 0.0, 1.0)


def _fragility_score(*, target: float, volatility: float, line: float) -> float:
    low_line_pressure = 0.10 if line <= 0.5 else 0.0
    probability_balance = 1.0 - abs(target - 0.5) * 2.0
    return _clamp(0.55 * volatility + 0.35 * probability_balance + low_line_pressure, 0.0, 1.0)


def _validate_power_of_two(value: int) -> int:
    if value < 2 or value & (value - 1):
        raise ValueError(f"simulation_n must be a power of two for Sobol base-2 sampling: {value}")
    return value


def _stable_seed(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _seed_key(input_value: MarketSimulationInput) -> str:
    return f"{input_value.market}|{input_value.line}|{input_value.target_over_probability:.6f}|{input_value.distribution}"


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
