"""Baseball Savant context fetchers for MLB-dev."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from mlb.contracts import RawSnapshot
from mlb.fetchers.http import get_with_retries
from mlb.sources.catalog import (
    BASEBALL_SAVANT_CUSTOM_LEADERBOARD_URL,
    BASEBALL_SAVANT_EXPECTED_STATS_URL,
    BASEBALL_SAVANT_PARK_FACTORS_URL,
    BASEBALL_SAVANT_SCHEDULE_URL,
    BASEBALL_SAVANT_STATCAST_SEARCH_CSV_URL,
    BASEBALL_SAVANT_TRENDING_PLAYERS_URL,
)
from mlb.sources.snapshots import write_raw_snapshot

DEFAULT_BASEBALL_SAVANT_PAGES = (
    "expected_batter",
    "expected_pitcher",
    "custom_batter",
    "custom_pitcher",
    "statcast_search_batter",
    "statcast_search_pitcher",
    "park_factors",
    "schedule",
    "trending_players",
)

BASEBALL_SAVANT_CUSTOM_SELECTIONS = (
    "pa",
    "xba",
    "xslg",
    "xwoba",
    "woba",
    "ba",
    "slg_percent",
    "isolated_power",
    "exit_velocity_avg",
    "launch_angle_avg",
    "barrel_batted_rate",
    "hard_hit_percent",
    "k_percent",
    "bb_percent",
    "whiff_percent",
    "oz_swing_percent",
    "iz_contact_percent",
    "sweet_spot_percent",
    "avg_best_speed",
)


@dataclass(frozen=True)
class BaseballSavantPageRequest:
    source: str
    page: str
    url: str
    params: dict[str, Any]


def fetch_baseball_savant_context(
    *,
    game_date: str | None = None,
    season: int = 2026,
    pages: tuple[str, ...] | None = None,
    root: Path | None = None,
    timeout: int | None = None,
) -> RawSnapshot:
    """Fetch configured Baseball Savant context pages and write one raw snapshot."""

    resolved_timeout = timeout or int(os.environ.get("BASEBALL_SAVANT_TIMEOUT_S", "30"))
    requests_to_fetch = build_baseball_savant_context_requests(
        game_date=game_date,
        season=season,
        pages=pages,
    )
    session = requests.Session()
    session.headers.update(_headers())
    payloads = []
    status_codes = []

    for request in requests_to_fetch:
        response = get_with_retries(request.url, session=session, params=request.params, timeout=resolved_timeout)
        response.raise_for_status()
        status_codes.append(response.status_code)
        payloads.append(
            {
                "source": request.source,
                "page": request.page,
                "url": request.url,
                "resolved_url": response.url,
                "params": request.params,
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type", ""),
                "body": response.text,
            }
        )

    payload = {
        "source": "baseball_savant_context",
        "sport": "MLB",
        "game_date": game_date,
        "season": season,
        "data": payloads,
        "_atlas_fetch": {
            "source": "baseball_savant_context",
            "game_date": game_date,
            "season": season,
            "pages": [request.page for request in requests_to_fetch],
            "status_codes": status_codes,
        },
    }
    return write_raw_snapshot(
        source="baseball_savant_context",
        payload=payload,
        request={
            "game_date": game_date,
            "season": season,
            "pages": [request.page for request in requests_to_fetch],
            "status_codes": status_codes,
        },
        root=root,
    )


def build_baseball_savant_context_requests(
    *,
    game_date: str | None = None,
    season: int = 2026,
    pages: tuple[str, ...] | None = None,
) -> tuple[BaseballSavantPageRequest, ...]:
    """Build page requests for Baseball Savant context capture."""

    resolved_pages = pages or DEFAULT_BASEBALL_SAVANT_PAGES
    unknown = [page for page in resolved_pages if page not in _page_factories()]
    if unknown:
        raise ValueError(f"unsupported Baseball Savant page(s): {', '.join(unknown)}")
    return tuple(_page_factories()[page](game_date=game_date, season=season) for page in resolved_pages)


def parse_baseball_savant_pages(value: str | tuple[str, ...] | None) -> tuple[str, ...] | None:
    """Parse CLI/env page selection."""

    if value is None or value == "" or value == "default":
        return None
    if isinstance(value, tuple):
        return value
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _page_factories():
    return {
        "expected_batter": _expected_batter_request,
        "expected_pitcher": _expected_pitcher_request,
        "custom_batter": _custom_batter_request,
        "custom_pitcher": _custom_pitcher_request,
        "statcast_search_batter": _statcast_search_batter_request,
        "statcast_search_pitcher": _statcast_search_pitcher_request,
        "park_factors": _park_factors_request,
        "schedule": _schedule_request,
        "trending_players": _trending_players_request,
    }


def _expected_batter_request(*, game_date: str | None, season: int) -> BaseballSavantPageRequest:
    return BaseballSavantPageRequest(
        source="baseball_savant_context",
        page="expected_batter",
        url=BASEBALL_SAVANT_EXPECTED_STATS_URL,
        params={"year": season, "type": "batter", "csv": "true"},
    )


def _expected_pitcher_request(*, game_date: str | None, season: int) -> BaseballSavantPageRequest:
    return BaseballSavantPageRequest(
        source="baseball_savant_context",
        page="expected_pitcher",
        url=BASEBALL_SAVANT_EXPECTED_STATS_URL,
        params={"year": season, "type": "pitcher", "csv": "true"},
    )


def _custom_batter_request(*, game_date: str | None, season: int) -> BaseballSavantPageRequest:
    return BaseballSavantPageRequest(
        source="baseball_savant_context",
        page="custom_batter",
        url=BASEBALL_SAVANT_CUSTOM_LEADERBOARD_URL,
        params={
            "year": season,
            "type": "batter",
            "min": "q",
            "selections": ",".join(BASEBALL_SAVANT_CUSTOM_SELECTIONS),
            "csv": "true",
        },
    )


def _custom_pitcher_request(*, game_date: str | None, season: int) -> BaseballSavantPageRequest:
    return BaseballSavantPageRequest(
        source="baseball_savant_context",
        page="custom_pitcher",
        url=BASEBALL_SAVANT_CUSTOM_LEADERBOARD_URL,
        params={
            "year": season,
            "type": "pitcher",
            "min": "q",
            "selections": ",".join(BASEBALL_SAVANT_CUSTOM_SELECTIONS),
            "csv": "true",
        },
    )


def _statcast_search_batter_request(*, game_date: str | None, season: int) -> BaseballSavantPageRequest:
    return BaseballSavantPageRequest(
        source="baseball_savant_context",
        page="statcast_search_batter",
        url=BASEBALL_SAVANT_STATCAST_SEARCH_CSV_URL,
        params=_statcast_search_params(game_date=game_date, season=season, player_type="batter"),
    )


def _statcast_search_pitcher_request(*, game_date: str | None, season: int) -> BaseballSavantPageRequest:
    return BaseballSavantPageRequest(
        source="baseball_savant_context",
        page="statcast_search_pitcher",
        url=BASEBALL_SAVANT_STATCAST_SEARCH_CSV_URL,
        params=_statcast_search_params(game_date=game_date, season=season, player_type="pitcher"),
    )


def _statcast_search_params(*, game_date: str | None, season: int, player_type: str) -> dict[str, Any]:
    params: dict[str, Any] = {
        "all": "true",
        "hfGT": "R|",
        "hfSea": f"{season}|",
        "player_type": player_type,
        "game_date_gt": f"{season}-03-01",
        "group_by": "name",
        "sort_col": "pitches",
        "sort_order": "desc",
        "min_pitches": "0",
        "min_results": "0",
        "min_pas": "0",
    }
    if game_date:
        params["game_date_lt"] = game_date
    return params


def _park_factors_request(*, game_date: str | None, season: int) -> BaseballSavantPageRequest:
    return BaseballSavantPageRequest(
        source="baseball_savant_context",
        page="park_factors",
        url=BASEBALL_SAVANT_PARK_FACTORS_URL,
        params={},
    )


def _schedule_request(*, game_date: str | None, season: int) -> BaseballSavantPageRequest:
    return BaseballSavantPageRequest(
        source="baseball_savant_context",
        page="schedule",
        url=BASEBALL_SAVANT_SCHEDULE_URL,
        params={"date": game_date} if game_date else {},
    )


def _trending_players_request(*, game_date: str | None, season: int) -> BaseballSavantPageRequest:
    return BaseballSavantPageRequest(
        source="baseball_savant_context",
        page="trending_players",
        url=BASEBALL_SAVANT_TRENDING_PLAYERS_URL,
        params={},
    )


def _headers() -> dict[str, str]:
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://baseballsavant.mlb.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
    }
