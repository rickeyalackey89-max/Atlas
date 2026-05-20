"""Typed contracts for the MLB development pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mlb.contracts.engine import EngineBoardRow, ScoredLeg
from mlb.contracts.probability import ProbabilityInput, ProbabilityResult

__all__ = (
    "BoardProjection",
    "EngineBoardRow",
    "InjuryStatus",
    "MinorLeaguePlayer",
    "ProbabilityInput",
    "ProbabilityResult",
    "RawSnapshot",
    "ScoredLeg",
)


@dataclass(frozen=True)
class RawSnapshot:
    source: str
    pulled_at_utc: str
    path: str
    checksum: str
    request: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BoardProjection:
    snapshot_id: str
    source: str
    event_id: str
    game_date: str
    start_time_utc: str
    player_name: str
    player_team: str
    opponent: str
    market: str
    source_market: str
    line: float
    side: str | None = None
    player_id: str | None = None
    player_position: str | None = None
    odds: float | None = None
    book: str | None = None
    platform: str = "PrizePicks"
    is_live: bool = False
    is_combo: bool = False
    combo_player_ids: tuple[str, ...] = ()
    status: str = "active"


@dataclass(frozen=True)
class InjuryStatus:
    source: str
    pulled_at_utc: str
    player_name: str
    team: str
    status: str
    estimated_return: str | None = None
    comment: str | None = None
    player_id: str | None = None
    position: str | None = None
    report_date: str | None = None


@dataclass(frozen=True)
class MinorLeaguePlayer:
    source: str
    player_name: str
    milb_team: str
    mlb_org: str
    level: str
    season: int
    player_id: str | None = None
    position: str | None = None
    bats: str | None = None
    throws: str | None = None
    games: int | None = None
    stat_scope: str = "season"
    stats: dict[str, Any] = field(default_factory=dict)
