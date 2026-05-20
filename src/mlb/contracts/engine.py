"""Engine input and scored-leg contracts for Atlas MLB."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

BETTINGPROS_CONTEXT_FIELDS = (
    "external_market_context_available",
    "market_context_source_type",
    "external_market_context_source",
    "prizepicks_line_only_market_context",
    "bettingpros_recommended_side",
    "bettingpros_projection_value",
    "bettingpros_projection_probability",
    "bettingpros_projection_expected_value",
    "bettingpros_projection_diff",
    "bettingpros_streak",
    "bettingpros_streak_type",
    "bettingpros_last_5_over_rate",
    "bettingpros_last_5_under_rate",
    "bettingpros_last_10_over_rate",
    "bettingpros_last_10_under_rate",
    "bettingpros_last_20_over_rate",
    "bettingpros_last_20_under_rate",
    "bettingpros_season_over_rate",
    "bettingpros_season_under_rate",
    "bettingpros_prior_season_over_rate",
    "bettingpros_prior_season_under_rate",
)


@dataclass(frozen=True)
class EngineBoardRow:
    """One PrizePicks projection after normalization and engine-board publishing."""

    run_id: str
    snapshot_id: str
    source_projection_id: str
    event_id: str
    league: str
    game_date: str
    start_time_utc: str
    player_id: str
    player_name: str
    player_team: str
    opponent: str
    market: str
    source_market: str
    line: float
    tier: str = "STANDARD"
    status: str = "active"
    player_position: str = ""
    is_live: bool = False
    is_combo: bool = False
    updated_at: str = ""
    pulled_at_utc: str = ""

    @classmethod
    def from_mapping(cls, row: dict[str, Any], *, run_id: str) -> "EngineBoardRow":
        return cls(
            run_id=run_id,
            snapshot_id=_clean_str(row.get("snapshot_id")),
            source_projection_id=_clean_str(row.get("source_projection_id")),
            event_id=_clean_str(row.get("event_id")),
            league=_clean_str(row.get("league") or "MLB"),
            game_date=_clean_str(row.get("game_date")),
            start_time_utc=_clean_str(row.get("start_time_utc")),
            player_id=_clean_str(row.get("player_id")),
            player_name=_clean_str(row.get("player_name")),
            player_team=_clean_str(row.get("player_team")),
            opponent=_clean_str(row.get("opponent")),
            market=_clean_str(row.get("market")),
            source_market=_clean_str(row.get("source_market")),
            line=_to_float(row.get("line")),
            tier=_clean_str(row.get("tier") or "STANDARD").upper(),
            status=_clean_str(row.get("status") or "active"),
            player_position=_clean_str(row.get("player_position")),
            is_live=_to_bool(row.get("is_live")),
            is_combo=_to_bool(row.get("is_combo")),
            updated_at=_clean_str(row.get("updated_at")),
            pulled_at_utc=_clean_str(row.get("pulled_at_utc")),
        )


@dataclass(frozen=True)
class ScoredLeg:
    """One model-scored candidate leg."""

    run_id: str
    source_run_id: str
    snapshot_id: str
    source_projection_id: str
    event_id: str
    game_date: str
    start_time_utc: str
    player_id: str
    player_name: str
    player_team: str
    opponent: str
    market: str
    source_market: str
    line: float
    side: str
    over_probability: float
    under_probability: float
    push_probability: float
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
    fair_price: int
    fair_decimal: float
    market_price: float | None
    edge: float
    confidence_tier: str
    kernel_version: str
    model_version: str
    method: str
    flags: tuple[str, ...]
    external_market_context_available: bool
    market_context_source_type: str
    external_market_context_source: str
    prizepicks_line_only_market_context: bool
    bettingpros_recommended_side: str
    bettingpros_projection_value: float
    bettingpros_projection_probability: float
    bettingpros_projection_expected_value: float
    bettingpros_projection_diff: float
    bettingpros_streak: int
    bettingpros_streak_type: str
    bettingpros_last_5_over_rate: float
    bettingpros_last_5_under_rate: float
    bettingpros_last_10_over_rate: float
    bettingpros_last_10_under_rate: float
    bettingpros_last_20_over_rate: float
    bettingpros_last_20_under_rate: float
    bettingpros_season_over_rate: float
    bettingpros_season_under_rate: float
    bettingpros_prior_season_over_rate: float
    bettingpros_prior_season_under_rate: float
    tier: str
    status: str
    is_live: bool
    is_combo: bool
    pulled_at_utc: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "source_run_id": self.source_run_id,
            "snapshot_id": self.snapshot_id,
            "source_projection_id": self.source_projection_id,
            "event_id": self.event_id,
            "game_date": self.game_date,
            "start_time_utc": self.start_time_utc,
            "player_id": self.player_id,
            "player_name": self.player_name,
            "player_team": self.player_team,
            "opponent": self.opponent,
            "market": self.market,
            "source_market": self.source_market,
            "line": self.line,
            "side": self.side,
            "over_probability": self.over_probability,
            "under_probability": self.under_probability,
            "push_probability": self.push_probability,
            "model_probability": self.model_probability,
            "mean_projection": self.mean_projection,
            "median_projection": self.median_projection,
            "p10": self.p10,
            "p25": self.p25,
            "p75": self.p75,
            "p90": self.p90,
            "volatility_score": self.volatility_score,
            "fragility_score": self.fragility_score,
            "stability_score": self.stability_score,
            "opportunity_model_version": self.opportunity_model_version,
            "opportunity_type": self.opportunity_type,
            "projected_opportunity": self.projected_opportunity,
            "opportunity_confidence": self.opportunity_confidence,
            "opportunity_fragility_score": self.opportunity_fragility_score,
            "lineup_score": self.lineup_score,
            "starter_matchup_score": self.starter_matchup_score,
            "bullpen_matchup_score": self.bullpen_matchup_score,
            "environment_score": self.environment_score,
            "matchup_composite_score": self.matchup_composite_score,
            "matchup_confidence": self.matchup_confidence,
            "matchup_target_shift": self.matchup_target_shift,
            "matchup_context_available": self.matchup_context_available,
            "simulation_n": self.simulation_n,
            "simulation_seed": self.simulation_seed,
            "simulation_kernel_version": self.simulation_kernel_version,
            "parameter_model_version": self.parameter_model_version,
            "calibration_version": self.calibration_version,
            "fair_price": self.fair_price,
            "fair_decimal": self.fair_decimal,
            "market_price": self.market_price,
            "edge": self.edge,
            "confidence_tier": self.confidence_tier,
            "kernel_version": self.kernel_version,
            "model_version": self.model_version,
            "method": self.method,
            "flags": self.flags,
            "external_market_context_available": self.external_market_context_available,
            "market_context_source_type": self.market_context_source_type,
            "external_market_context_source": self.external_market_context_source,
            "prizepicks_line_only_market_context": self.prizepicks_line_only_market_context,
            "bettingpros_recommended_side": self.bettingpros_recommended_side,
            "bettingpros_projection_value": self.bettingpros_projection_value,
            "bettingpros_projection_probability": self.bettingpros_projection_probability,
            "bettingpros_projection_expected_value": self.bettingpros_projection_expected_value,
            "bettingpros_projection_diff": self.bettingpros_projection_diff,
            "bettingpros_streak": self.bettingpros_streak,
            "bettingpros_streak_type": self.bettingpros_streak_type,
            "bettingpros_last_5_over_rate": self.bettingpros_last_5_over_rate,
            "bettingpros_last_5_under_rate": self.bettingpros_last_5_under_rate,
            "bettingpros_last_10_over_rate": self.bettingpros_last_10_over_rate,
            "bettingpros_last_10_under_rate": self.bettingpros_last_10_under_rate,
            "bettingpros_last_20_over_rate": self.bettingpros_last_20_over_rate,
            "bettingpros_last_20_under_rate": self.bettingpros_last_20_under_rate,
            "bettingpros_season_over_rate": self.bettingpros_season_over_rate,
            "bettingpros_season_under_rate": self.bettingpros_season_under_rate,
            "bettingpros_prior_season_over_rate": self.bettingpros_prior_season_over_rate,
            "bettingpros_prior_season_under_rate": self.bettingpros_prior_season_under_rate,
            "tier": self.tier,
            "status": self.status,
            "is_live": self.is_live,
            "is_combo": self.is_combo,
            "pulled_at_utc": self.pulled_at_utc,
        }


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Engine board row has invalid line value: {value!r}") from exc
