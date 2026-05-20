"""Minor-league player context fetcher skeleton."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MinorLeagueContextRequest:
    season: int
    source: str
    mlb_org: str | None = None
    level: str | None = None
