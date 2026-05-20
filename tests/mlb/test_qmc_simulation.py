import pytest

from mlb.contracts.simulation import MarketSimulationInput
from mlb.modeling.qmc import default_distribution_for_market, simulate_market


def test_sobol_market_simulation_is_deterministic():
    simulation_input = MarketSimulationInput(
        market="hits",
        line=0.5,
        target_over_probability=0.61,
        distribution="poisson",
        simulation_n=1024,
        seed_key="hits|0.5|standard",
    )

    first = simulate_market(simulation_input)
    second = simulate_market(simulation_input)

    assert first == second
    assert first.simulation_kernel_version.startswith("mlb_sobol_qmc")
    assert first.p_over == pytest.approx(0.61, abs=0.025)
    assert first.p_under + first.p_over + first.p_push == pytest.approx(1.0, abs=0.01)


def test_sobol_market_simulation_exposes_distribution_shape():
    result = simulate_market(
        MarketSimulationInput(
            market="hitter_fantasy_score",
            line=7.5,
            target_over_probability=0.55,
            distribution=default_distribution_for_market("hitter_fantasy_score"),
            simulation_n=1024,
            seed_key="fantasy|7.5|standard",
        )
    )

    assert result.distribution == "normal"
    assert result.p10 <= result.p25 <= result.median_projection <= result.p75 <= result.p90
    assert 0.0 <= result.volatility_score <= 1.0
    assert 0.0 <= result.fragility_score <= 1.0
    assert 0.0 <= result.stability_score <= 1.0


def test_sobol_requires_power_of_two_sample_count():
    with pytest.raises(ValueError, match="power of two"):
        simulate_market(
            MarketSimulationInput(
                market="hits",
                line=0.5,
                target_over_probability=0.61,
                distribution="poisson",
                simulation_n=1000,
            )
        )
