"""ESPN MLB game context fetcher.

This source is primarily useful for replay/backfill context. ESPN historical
summaries expose boxscore lineups and game officials after the game, so the
normalizer labels those rows as postgame backfill rather than live assumptions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import requests

from mlb.contracts import RawSnapshot
from mlb.fetchers.http import get_with_retries
from mlb.sources.catalog import ESPN_MLB_SCOREBOARD_URL, ESPN_MLB_SUMMARY_URL
from mlb.sources.snapshots import write_raw_snapshot


@dataclass(frozen=True)
class EspnGameContextRequest:
    source: str
    page: str
    url: str
    params: dict[str, Any]


def fetch_espn_game_context(
    *,
    game_date: str,
    root: Path | None = None,
    timeout: int | None = None,
) -> RawSnapshot:
    """Fetch ESPN scoreboard and per-event summaries for one MLB date."""

    resolved_timeout = timeout or int(os.environ.get("ESPN_MLB_TIMEOUT_S", "30"))
    requests_to_fetch = build_espn_game_context_requests(game_date=game_date)
    session = requests.Session()
    session.headers.update(_headers())

    scoreboard_request = requests_to_fetch[0]
    scoreboard_response = get_with_retries(
        scoreboard_request.url,
        session=session,
        params=scoreboard_request.params,
        timeout=resolved_timeout,
    )
    scoreboard_response.raise_for_status()
    scoreboard_payload = scoreboard_response.json()

    summaries: list[dict[str, Any]] = []
    status_codes = [scoreboard_response.status_code]
    event_ids = _event_ids(scoreboard_payload)
    for event_id in event_ids:
        summary_response = get_with_retries(
            ESPN_MLB_SUMMARY_URL,
            session=session,
            params={"event": event_id},
            timeout=resolved_timeout,
        )
        summary_response.raise_for_status()
        status_codes.append(summary_response.status_code)
        summaries.append(
            {
                "event_id": event_id,
                "url": ESPN_MLB_SUMMARY_URL,
                "resolved_url": summary_response.url,
                "params": {"event": event_id},
                "status_code": summary_response.status_code,
                "content_type": summary_response.headers.get("content-type", ""),
                "payload": summary_response.json(),
            }
        )

    payload = {
        "source": "espn_game_context",
        "sport": "MLB",
        "game_date": game_date,
        "scoreboard": {
            "url": scoreboard_request.url,
            "resolved_url": scoreboard_response.url,
            "params": scoreboard_request.params,
            "status_code": scoreboard_response.status_code,
            "content_type": scoreboard_response.headers.get("content-type", ""),
            "payload": scoreboard_payload,
        },
        "summaries": summaries,
        "_atlas_fetch": {
            "source": "espn_game_context",
            "game_date": game_date,
            "event_ids": event_ids,
            "status_codes": status_codes,
        },
    }
    return write_raw_snapshot(
        source="espn_game_context",
        payload=payload,
        request={
            "game_date": game_date,
            "event_ids": event_ids,
            "status_codes": status_codes,
        },
        root=root,
    )


def build_espn_game_context_requests(*, game_date: str) -> tuple[EspnGameContextRequest, ...]:
    """Build ESPN requests for one MLB game date."""

    dates = _espn_date(game_date)
    return (
        EspnGameContextRequest(
            source="espn_game_context",
            page="scoreboard",
            url=ESPN_MLB_SCOREBOARD_URL,
            params={"dates": dates},
        ),
    )


def _event_ids(payload: dict[str, Any]) -> list[str]:
    events = payload.get("events", [])
    if not isinstance(events, list):
        return []
    return [str(event.get("id")) for event in events if isinstance(event, dict) and event.get("id")]


def _espn_date(game_date: str) -> str:
    parsed = date.fromisoformat(game_date)
    return parsed.strftime("%Y%m%d")


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
    }
