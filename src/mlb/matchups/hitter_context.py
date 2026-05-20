"""Join MLB matchup matrix outputs into hitter probability context rows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from mlb.matchups.schemas import (
    BullpenContext,
    EnvironmentContext,
    HitterMatchupContext,
    LineupContext,
    PitcherContext,
)
from mlb.domain.teams import canonical_team_abbr

POWER_MARKETS = {"home_runs", "total_bases", "doubles", "hitter_fantasy_score"}
CONTACT_MARKETS = {"hits", "singles", "hits_runs_rbis"}
OPPORTUNITY_MARKETS = {"runs", "rbis", "plate_appearances", "walks", "stolen_bases"}
STRIKEOUT_MARKETS = {"hitter_strikeouts"}
CRITICAL_SOURCE_MISSING_FLAGS = {
    "missing_game_id",
    "missing_player_id",
    "missing_team",
    "missing_hitter_team",
    "missing_opponent",
}


def build_hitter_matchup_context(
    prop_rows: Iterable[Mapping[str, Any]],
    *,
    lineup_contexts: Iterable[LineupContext] = (),
    pitcher_contexts: Iterable[PitcherContext] = (),
    bullpen_contexts: Iterable[BullpenContext] = (),
    environment_contexts: Iterable[EnvironmentContext] = (),
    run_id: str = "",
) -> list[HitterMatchupContext]:
    """Join matrix outputs into one context row per hitter prop."""

    lineups = {(item.game_id, item.player_id): item for item in lineup_contexts}
    lineups_by_name = {
        (item.game_id, _team_key(item.team), _name_key(item.player_name)): item
        for item in lineup_contexts
        if item.player_name
    }
    pitchers = {(item.game_id, item.hitter_team): item for item in pitcher_contexts}
    bullpens = {(item.game_id, item.hitter_team): item for item in bullpen_contexts}
    environments = {(item.game_id, item.team): item for item in environment_contexts}

    contexts: list[HitterMatchupContext] = []
    for row in prop_rows:
        game_id = _str(row.get("game_id") or row.get("event_id"))
        player_id = _str(row.get("player_id"))
        team = canonical_team_abbr(row.get("team") or row.get("player_team"))
        market = _str(row.get("market"))
        player_name = _str(row.get("player_name") or row.get("player"))
        lineup = lineups.get((game_id, player_id)) or lineups_by_name.get((game_id, _team_key(team), _name_key(player_name)))
        pitcher = pitchers.get((game_id, team))
        bullpen = bullpens.get((game_id, team))
        environment = environments.get((game_id, team))
        missing_context_flags = _missing_context_flags(
            lineup=lineup,
            pitcher=pitcher,
            bullpen=bullpen,
            environment=environment,
        )
        composite = _composite_score(
            market=market,
            lineup_score=lineup.lineup_score if lineup else 0.0,
            starter_matchup_score=pitcher.starter_matchup_score if pitcher else 0.0,
            bullpen_matchup_score=bullpen.bullpen_matchup_score if bullpen else 0.0,
            environment_score=environment.environment_score if environment else 0.0,
        )
        confidence = _component_confidence(
            lineup=lineup,
            pitcher=pitcher,
            bullpen=bullpen,
            environment=environment,
        )
        contexts.append(
            HitterMatchupContext(
                run_id=run_id or _str(row.get("run_id")),
                source_projection_id=_str(row.get("source_projection_id") or row.get("projection_id")),
                game_id=game_id,
                game_date=_str(row.get("game_date")),
                player_id=player_id,
                player_name=player_name,
                team=team,
                opponent=canonical_team_abbr(row.get("opponent") or row.get("opp")),
                market=market,
                line=_float(row.get("line"), 0.0),
                tier=_str(row.get("tier") or "STANDARD"),
                direction=_str(row.get("direction") or "over").lower(),
                lineup_score=lineup.lineup_score if lineup else 0.0,
                starter_matchup_score=pitcher.starter_matchup_score if pitcher else 0.0,
                bullpen_matchup_score=bullpen.bullpen_matchup_score if bullpen else 0.0,
                environment_score=environment.environment_score if environment else 0.0,
                matchup_composite_score=round(composite, 6),
                matchup_confidence=round(confidence, 6),
                projected_plate_appearances=lineup.projected_plate_appearances if lineup else 0.0,
                batting_order_slot=lineup.batting_order_slot if lineup else None,
                pinch_hit_risk=lineup.pinch_hit_risk if lineup else 0.0,
                strikeout_pressure_score=pitcher.strikeout_pressure_score if pitcher else 0.0,
                contact_context_score=pitcher.contact_allow_score if pitcher else 0.0,
                power_context_score=pitcher.power_allow_score if pitcher else 0.0,
                walk_context_score=pitcher.walk_allow_score if pitcher else 0.0,
                late_game_run_score=bullpen.late_game_run_score if bullpen else 0.0,
                park_run_factor=environment.park_run_factor if environment else 1.0,
                park_hr_factor=environment.park_hr_factor if environment else 1.0,
                park_hit_factor=environment.park_hit_factor if environment else 1.0,
                park_extra_base_factor=environment.park_extra_base_factor if environment else 1.0,
                park_factor_confidence=environment.park_factor_confidence if environment else 0.0,
                home_plate_umpire=environment.home_plate_umpire if environment else "",
                umpire_era=environment.umpire_era if environment else 0.0,
                umpire_rating=environment.umpire_rating if environment else "",
                umpire_run_score=environment.umpire_run_score if environment else 0.0,
                umpire_confidence=environment.umpire_confidence if environment else 0.0,
                missing_context_flags=missing_context_flags,
            )
        )
    return contexts


def _composite_score(
    *,
    market: str,
    lineup_score: float,
    starter_matchup_score: float,
    bullpen_matchup_score: float,
    environment_score: float,
) -> float:
    if market in POWER_MARKETS:
        weights = (0.25, 0.35, 0.15, 0.25)
    elif market in CONTACT_MARKETS:
        weights = (0.35, 0.35, 0.15, 0.15)
    elif market in OPPORTUNITY_MARKETS:
        weights = (0.45, 0.20, 0.20, 0.15)
    elif market in STRIKEOUT_MARKETS:
        weights = (0.20, 0.60, 0.05, 0.15)
    else:
        weights = (0.35, 0.30, 0.15, 0.20)
    value = (
        weights[0] * lineup_score
        + weights[1] * starter_matchup_score
        + weights[2] * bullpen_matchup_score
        + weights[3] * environment_score
    )
    return _clamp(value, -1.0, 1.0)


def _missing_context_flags(
    *,
    lineup: LineupContext | None,
    pitcher: PitcherContext | None,
    bullpen: BullpenContext | None,
    environment: EnvironmentContext | None,
) -> tuple[str, ...]:
    flags: list[str] = []
    if lineup is None or _has_missing_source_flag(lineup.flags):
        flags.append("missing_lineup_context")
    if pitcher is None or _has_missing_source_flag(pitcher.flags):
        flags.append("missing_pitcher_context")
    if bullpen is None or _has_missing_source_flag(bullpen.flags):
        flags.append("missing_bullpen_context")
    if environment is None or _has_missing_source_flag(environment.flags):
        flags.append("missing_environment_context")
    return tuple(flags)


def _component_confidence(
    *,
    lineup: LineupContext | None,
    pitcher: PitcherContext | None,
    bullpen: BullpenContext | None,
    environment: EnvironmentContext | None,
) -> float:
    values = [item.confidence for item in (lineup, pitcher, bullpen, environment) if item is not None]
    if not values:
        return 0.0
    return sum(values) / len(values)


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _str(value: Any) -> str:
    return str(value or "").strip()


def _team_key(value: Any) -> str:
    return canonical_team_abbr(value)


def _name_key(value: Any) -> str:
    return " ".join(_str(value).casefold().replace(".", "").split())


def _has_missing_source_flag(flags: tuple[str, ...]) -> bool:
    return any("missing_source" in flag or flag in CRITICAL_SOURCE_MISSING_FLAGS for flag in flags)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
