"""PrizePicks MLB scoring helpers."""

from __future__ import annotations

from mlb.domain.markets import HITTER_FANTASY_WEIGHTS, PITCHER_FANTASY_WEIGHTS


def hitter_fantasy_score(
    *,
    singles: int = 0,
    doubles: int = 0,
    triples: int = 0,
    home_runs: int = 0,
    runs: int = 0,
    rbis: int = 0,
    walks: int = 0,
    hit_by_pitch: int = 0,
    stolen_bases: int = 0,
) -> int:
    return (
        singles * HITTER_FANTASY_WEIGHTS["single"]
        + doubles * HITTER_FANTASY_WEIGHTS["double"]
        + triples * HITTER_FANTASY_WEIGHTS["triple"]
        + home_runs * HITTER_FANTASY_WEIGHTS["home_run"]
        + runs * HITTER_FANTASY_WEIGHTS["run"]
        + rbis * HITTER_FANTASY_WEIGHTS["rbi"]
        + walks * HITTER_FANTASY_WEIGHTS["walk"]
        + hit_by_pitch * HITTER_FANTASY_WEIGHTS["hit_by_pitch"]
        + stolen_bases * HITTER_FANTASY_WEIGHTS["stolen_base"]
    )


def pitcher_fantasy_score(
    *,
    wins: int = 0,
    quality_starts: int = 0,
    earned_runs: int = 0,
    strikeouts: int = 0,
    outs: int = 0,
) -> int:
    return (
        wins * PITCHER_FANTASY_WEIGHTS["win"]
        + quality_starts * PITCHER_FANTASY_WEIGHTS["quality_start"]
        + earned_runs * PITCHER_FANTASY_WEIGHTS["earned_run"]
        + strikeouts * PITCHER_FANTASY_WEIGHTS["strikeout"]
        + outs * PITCHER_FANTASY_WEIGHTS["out"]
    )
