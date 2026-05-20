"""Rotowire MLB context fetchers.

Rotowire is a context source, not a probability source. The fetcher stores raw
HTML pages so parsers can evolve without losing source fidelity.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from mlb.contracts import RawSnapshot
from mlb.fetchers.http import get_with_retries
from mlb.sources.catalog import (
    ROTOWIRE_MLB_BATTING_ORDERS_URL,
    ROTOWIRE_MLB_BULLPEN_USAGE_TABLE_URL,
    ROTOWIRE_MLB_BULLPEN_USAGE_URL,
    ROTOWIRE_MLB_DAILY_LINEUPS_URL,
    ROTOWIRE_MLB_LINEUP_CARD_URL,
    ROTOWIRE_MLB_ODDS_URL,
    ROTOWIRE_MLB_PROJECTED_STARTERS_URL,
    ROTOWIRE_MLB_RELIEVER_USAGE_TABLE_URL,
    ROTOWIRE_MLB_RELIEVER_USAGE_URL,
    ROTOWIRE_MLB_UMPIRES_URL,
    ROTOWIRE_MLB_WEATHER_URL,
)
from mlb.sources.snapshots import write_raw_snapshot

DEFAULT_ROTOWIRE_MLB_PAGES = (
    "daily_lineups",
    "batting_orders",
    "projected_starters",
    "bullpen_usage",
    "bullpen_usage_table",
    "reliever_usage",
    "reliever_usage_table",
    "lineup_card",
    "weather",
    "umpires",
    "odds",
)

ROTOWIRE_MLB_PAGE_URLS = {
    "daily_lineups": ROTOWIRE_MLB_DAILY_LINEUPS_URL,
    "batting_orders": ROTOWIRE_MLB_BATTING_ORDERS_URL,
    "projected_starters": ROTOWIRE_MLB_PROJECTED_STARTERS_URL,
    "bullpen_usage": ROTOWIRE_MLB_BULLPEN_USAGE_URL,
    "bullpen_usage_table": ROTOWIRE_MLB_BULLPEN_USAGE_TABLE_URL,
    "reliever_usage": ROTOWIRE_MLB_RELIEVER_USAGE_URL,
    "reliever_usage_table": ROTOWIRE_MLB_RELIEVER_USAGE_TABLE_URL,
    "lineup_card": ROTOWIRE_MLB_LINEUP_CARD_URL,
    "weather": ROTOWIRE_MLB_WEATHER_URL,
    "umpires": ROTOWIRE_MLB_UMPIRES_URL,
    "odds": ROTOWIRE_MLB_ODDS_URL,
}


@dataclass(frozen=True)
class RotowirePageRequest:
    source: str
    page: str
    url: str
    params: dict[str, Any]


def fetch_rotowire_mlb_context(
    *,
    game_date: str | None = None,
    pages: tuple[str, ...] | None = None,
    root: Path | None = None,
    timeout: int | None = None,
) -> RawSnapshot:
    """Fetch configured Rotowire MLB context pages and write one raw snapshot."""

    resolved_timeout = timeout or int(os.environ.get("ROTOWIRE_TIMEOUT_S", "30"))
    resolved_date = game_date or os.environ.get("ROTOWIRE_MLB_DATE")
    requests_to_fetch = build_rotowire_mlb_context_requests(game_date=resolved_date, pages=pages)
    session = _build_session()
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
        "source": "rotowire_mlb_context",
        "sport": "MLB",
        "game_date": resolved_date,
        "data": payloads,
        "_atlas_fetch": {
            "source": "rotowire_mlb_context",
            "game_date": resolved_date,
            "pages": [request.page for request in requests_to_fetch],
            "status_codes": status_codes,
        },
    }
    return write_raw_snapshot(
        source="rotowire_mlb_context",
        payload=payload,
        request={
            "game_date": resolved_date,
            "pages": [request.page for request in requests_to_fetch],
            "status_codes": status_codes,
        },
        root=root,
    )


def build_rotowire_mlb_context_requests(
    *,
    game_date: str | None = None,
    pages: tuple[str, ...] | None = None,
) -> tuple[RotowirePageRequest, ...]:
    """Build page requests for Rotowire MLB context capture."""

    resolved_pages = _expand_pages_with_table_dependencies(pages or DEFAULT_ROTOWIRE_MLB_PAGES)
    unknown = [page for page in resolved_pages if page not in ROTOWIRE_MLB_PAGE_URLS]
    if unknown:
        raise ValueError(f"unsupported Rotowire MLB page(s): {', '.join(unknown)}")

    requests_out: list[RotowirePageRequest] = []
    for page in resolved_pages:
        params = {"date": game_date} if game_date else {}
        requests_out.append(
            RotowirePageRequest(
                source="rotowire_mlb_context",
                page=page,
                url=ROTOWIRE_MLB_PAGE_URLS[page],
                params=params,
            )
        )
    return tuple(requests_out)


def _expand_pages_with_table_dependencies(pages: tuple[str, ...]) -> tuple[str, ...]:
    """Add Rotowire JSON table pages required to parse browser-shell pages."""

    expanded: list[str] = []
    for page in pages:
        if page not in expanded:
            expanded.append(page)
        dependency = {
            "bullpen_usage": "bullpen_usage_table",
            "reliever_usage": "reliever_usage_table",
        }.get(page)
        if dependency and dependency not in expanded:
            expanded.append(dependency)
    return tuple(expanded)


def parse_rotowire_pages(value: str | tuple[str, ...] | None) -> tuple[str, ...] | None:
    """Parse CLI/env page selection."""

    if value is None or value == "" or value == "default":
        return None
    if isinstance(value, tuple):
        return value
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(_headers())
    php_session = os.environ.get("ROTOWIRE_PHPSESSID", "").strip()
    if php_session:
        session.cookies.set("PHPSESSID", php_session, domain="www.rotowire.com")
    bootstrap_url = os.environ.get("ROTOWIRE_MLB_BOOTSTRAP_URL", "").strip()
    if bootstrap_url:
        get_with_retries(bootstrap_url, session=session, timeout=int(os.environ.get("ROTOWIRE_TIMEOUT_S", "30")))
    return session


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": ROTOWIRE_MLB_DAILY_LINEUPS_URL,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
    }
    extra = os.environ.get("ROTOWIRE_HEADERS_JSON", "").strip()
    if extra:
        parsed = json.loads(extra)
        if not isinstance(parsed, dict):
            raise ValueError("ROTOWIRE_HEADERS_JSON must decode to an object")
        headers.update({str(key): str(value) for key, value in parsed.items()})
    return headers
