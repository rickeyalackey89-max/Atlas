"""Simulation contracts for the Atlas MLB probability engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketSimulationInput:
    """Inputs required by a market-level simulation kernel."""

    market: str
    line: float
    target_over_probability: float
    distribution: str
    simulation_n: int = 2048
    seed: int | None = None
    seed_key: str = ""


@dataclass(frozen=True)
class MarketSimulationResult:
    """Distribution output from a deterministic market simulation."""

    p_over: float
    p_under: float
    p_push: float
    mean_projection: float
    median_projection: float
    p10: float
    p25: float
    p75: float
    p90: float
    volatility_score: float
    fragility_score: float
    stability_score: float
    simulation_n: int
    simulation_seed: int
    simulation_kernel_version: str
    distribution: str
    flags: tuple[str, ...]
