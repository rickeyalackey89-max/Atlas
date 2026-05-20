"""Typed contracts for MLB matchup matrix outputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

MATCHUP_MATRIX_VERSION = "mlb_matchup_matrix_v1"

HITTER_MATCHUP_CONTEXT_COLUMNS = (
    "run_id",
    "source_projection_id",
    "game_id",
    "game_date",
    "player_id",
    "player_name",
    "team",
    "opponent",
    "market",
    "line",
    "tier",
    "direction",
    "lineup_score",
    "starter_matchup_score",
    "bullpen_matchup_score",
    "environment_score",
    "matchup_composite_score",
    "matchup_confidence",
    "projected_plate_appearances",
    "batting_order_slot",
    "pinch_hit_risk",
    "strikeout_pressure_score",
    "contact_context_score",
    "power_context_score",
    "walk_context_score",
    "late_game_run_score",
    "park_run_factor",
    "park_hr_factor",
    "park_hit_factor",
    "park_extra_base_factor",
    "park_factor_confidence",
    "home_plate_umpire",
    "umpire_era",
    "umpire_rating",
    "umpire_run_score",
    "umpire_confidence",
    "matchup_matrix_version",
    "missing_context_flags",
)

PITCHER_PROP_CONTEXT_COLUMNS = (
    "run_id",
    "source_projection_id",
    "game_id",
    "game_date",
    "pitcher_id",
    "pitcher_name",
    "team",
    "opponent",
    "market",
    "line",
    "tier",
    "direction",
    "starter_pitcher_name",
    "starter_hand",
    "starter_era",
    "starter_score",
    "strikeout_context_score",
    "workload_context_score",
    "run_allow_context_score",
    "walk_context_score",
    "opponent_lineup_score",
    "opponent_k_context_score",
    "opponent_contact_context_score",
    "opponent_power_context_score",
    "opponent_walk_context_score",
    "opponent_projected_pa",
    "opponent_top_order_pa",
    "opponent_confirmed_batters",
    "opponent_lineup_confidence",
    "pitcher_history_k_score",
    "pitcher_history_hit_allow_score",
    "pitcher_history_walk_score",
    "pitcher_history_confidence",
    "bullpen_support_score",
    "environment_score",
    "pitcher_prop_composite_score",
    "pitcher_prop_confidence",
    "home_plate_umpire",
    "umpire_era",
    "umpire_rating",
    "umpire_run_score",
    "matchup_matrix_version",
    "missing_context_flags",
)


@dataclass(frozen=True)
class EnvironmentContext:
    game_id: str
    team: str
    opponent: str
    game_date: str = ""
    park_id: str = ""
    park_run_factor: float = 1.0
    park_hr_factor: float = 1.0
    park_hit_factor: float = 1.0
    park_extra_base_factor: float = 1.0
    park_factor_confidence: float = 0.0
    weather_run_score: float = 0.0
    wind_carry_score: float = 0.0
    home_plate_umpire: str = ""
    umpire_era: float = 0.0
    umpire_rating: str = ""
    umpire_run_score: float = 0.0
    umpire_confidence: float = 0.0
    environment_score: float = 0.0
    confidence: float = 0.0
    flags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LineupContext:
    game_id: str
    player_id: str
    player_name: str
    team: str
    opponent: str
    batting_order_slot: int | None = None
    lineup_probability: float = 0.0
    projected_plate_appearances: float = 0.0
    protection_score: float = 0.0
    run_context_score: float = 0.0
    rbi_context_score: float = 0.0
    pinch_hit_risk: float = 0.0
    lineup_score: float = 0.0
    confidence: float = 0.0
    flags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PitcherContext:
    game_id: str
    hitter_team: str
    opponent: str
    starter_pitcher_id: str = ""
    starter_pitcher_name: str = ""
    starter_hand: str = ""
    strikeout_pressure_score: float = 0.0
    contact_allow_score: float = 0.0
    power_allow_score: float = 0.0
    walk_allow_score: float = 0.0
    starter_matchup_score: float = 0.0
    confidence: float = 0.0
    flags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BullpenContext:
    game_id: str
    hitter_team: str
    opponent: str
    bullpen_fatigue_score: float = 0.0
    bullpen_quality_score: float = 0.0
    late_game_run_score: float = 0.0
    handedness_balance_score: float = 0.0
    bullpen_matchup_score: float = 0.0
    confidence: float = 0.0
    flags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UmpireProfile:
    umpire: str
    era: float
    rating: str
    rating_score: float
    era_score: float
    umpire_run_score: float
    confidence: float
    source: str = ""
    flags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BallparkProfile:
    park_id: str
    park_name: str
    team: str
    park_run_factor: float
    park_hr_factor: float
    park_hit_factor: float
    park_extra_base_factor: float
    park_context_score: float
    confidence: float
    source: str = ""
    flags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HitterMatchupContext:
    run_id: str
    source_projection_id: str
    game_id: str
    game_date: str
    player_id: str
    player_name: str
    team: str
    opponent: str
    market: str
    line: float
    tier: str
    direction: str
    lineup_score: float = 0.0
    starter_matchup_score: float = 0.0
    bullpen_matchup_score: float = 0.0
    environment_score: float = 0.0
    matchup_composite_score: float = 0.0
    matchup_confidence: float = 0.0
    projected_plate_appearances: float = 0.0
    batting_order_slot: int | None = None
    pinch_hit_risk: float = 0.0
    strikeout_pressure_score: float = 0.0
    contact_context_score: float = 0.0
    power_context_score: float = 0.0
    walk_context_score: float = 0.0
    late_game_run_score: float = 0.0
    park_run_factor: float = 1.0
    park_hr_factor: float = 1.0
    park_hit_factor: float = 1.0
    park_extra_base_factor: float = 1.0
    park_factor_confidence: float = 0.0
    home_plate_umpire: str = ""
    umpire_era: float = 0.0
    umpire_rating: str = ""
    umpire_run_score: float = 0.0
    umpire_confidence: float = 0.0
    matchup_matrix_version: str = MATCHUP_MATRIX_VERSION
    missing_context_flags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PitcherPropContext:
    run_id: str
    source_projection_id: str
    game_id: str
    game_date: str
    pitcher_id: str
    pitcher_name: str
    team: str
    opponent: str
    market: str
    line: float
    tier: str
    direction: str
    starter_pitcher_name: str = ""
    starter_hand: str = ""
    starter_era: float = 0.0
    starter_score: float = 0.0
    strikeout_context_score: float = 0.0
    workload_context_score: float = 0.0
    run_allow_context_score: float = 0.0
    walk_context_score: float = 0.0
    opponent_lineup_score: float = 0.0
    opponent_k_context_score: float = 0.0
    opponent_contact_context_score: float = 0.0
    opponent_power_context_score: float = 0.0
    opponent_walk_context_score: float = 0.0
    opponent_projected_pa: float = 0.0
    opponent_top_order_pa: float = 0.0
    opponent_confirmed_batters: int = 0
    opponent_lineup_confidence: float = 0.0
    pitcher_history_k_score: float = 0.0
    pitcher_history_hit_allow_score: float = 0.0
    pitcher_history_walk_score: float = 0.0
    pitcher_history_confidence: float = 0.0
    bullpen_support_score: float = 0.0
    environment_score: float = 0.0
    pitcher_prop_composite_score: float = 0.0
    pitcher_prop_confidence: float = 0.0
    home_plate_umpire: str = ""
    umpire_era: float = 0.0
    umpire_rating: str = ""
    umpire_run_score: float = 0.0
    matchup_matrix_version: str = MATCHUP_MATRIX_VERSION
    missing_context_flags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
