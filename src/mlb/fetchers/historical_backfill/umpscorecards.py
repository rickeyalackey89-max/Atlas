"""UmpScorecards fetcher for MLB plate umpire game scorecards."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from mlb.contracts import RawSnapshot
from mlb.fetchers.http import get_with_retries
from mlb.sources.catalog import UMPSCORECARDS_GAMES_URL
from mlb.sources.snapshots import write_raw_snapshot


@dataclass(frozen=True)
class UmpScorecardsGamesRequest:
    source: str
    url: str
    params: dict[str, Any]


def fetch_umpscorecards_games(
    *,
    start_date: str,
    end_date: str,
    season_type: str = "R",
    root: Path | None = None,
    timeout: int | None = None,
) -> RawSnapshot:
    """Fetch UmpScorecards game rows and write one raw snapshot."""

    request = build_umpscorecards_games_request(
        start_date=start_date,
        end_date=end_date,
        season_type=season_type,
    )
    resolved_timeout = timeout or int(os.environ.get("UMPSCORECARDS_TIMEOUT_S", "30"))
    response = get_with_retries(request.url, params=request.params, headers=_headers(), timeout=resolved_timeout)
    response.raise_for_status()
    response_payload = response.json()
    if not isinstance(response_payload, dict):
        raise ValueError("UmpScorecards response must decode to a JSON object")
    rows = response_payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("UmpScorecards response missing rows list")

    payload = {
        **response_payload,
        "source": "umpscorecards_games",
        "sport": "MLB",
        "start_date": start_date,
        "end_date": end_date,
        "season_type": season_type,
        "_atlas_fetch": {
            "source": "umpscorecards_games",
            "start_date": start_date,
            "end_date": end_date,
            "season_type": season_type,
            "status_code": response.status_code,
            "resolved_url": response.url,
            "row_count": len(rows),
        },
    }
    return write_raw_snapshot(
        source="umpscorecards_games",
        payload=payload,
        request={
            "url": request.url,
            "params": request.params,
            "start_date": start_date,
            "end_date": end_date,
            "season_type": season_type,
            "status_code": response.status_code,
            "row_count": len(rows),
        },
        root=root,
    )


def build_umpscorecards_games_request(
    *,
    start_date: str,
    end_date: str,
    season_type: str = "R",
) -> UmpScorecardsGamesRequest:
    return UmpScorecardsGamesRequest(
        source="umpscorecards_games",
        url=UMPSCORECARDS_GAMES_URL,
        params={
            "startDate": start_date,
            "endDate": end_date,
            "seasonType": season_type,
        },
    )


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://umpscorecards.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
    }
