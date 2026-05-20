"""PrizePicks MLB board fetcher."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from mlb.contracts import RawSnapshot
from mlb.fetchers.http import get_with_retries
from mlb.sources.catalog import PRIZEPICKS_MLB_LEAGUE_ID, PRIZEPICKS_PROJECTIONS_URL
from mlb.sources.snapshots import write_raw_snapshot


@dataclass(frozen=True)
class PrizePicksRequest:
    source: str
    league: str
    url: str = PRIZEPICKS_PROJECTIONS_URL
    league_id: int | None = None
    state_code: str = "MO"
    per_page: int = 250
    single_stat: bool = False
    in_game: bool = False
    game_mode: str = "prizepools"

    def params(self, page: int = 1) -> dict[str, Any]:
        params = {
            "per_page": self.per_page,
            "single_stat": str(self.single_stat).lower(),
            "in_game": str(self.in_game).lower(),
            "state_code": self.state_code,
            "game_mode": self.game_mode,
            "page": page,
        }
        if self.league_id is not None:
            params["league_id"] = self.league_id
        return params


DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": "https://app.prizepicks.com/",
    "User-Agent": "Mozilla/5.0",
}


def build_prizepicks_mlb_request(*, state_code: str = "MO", per_page: int = 250) -> PrizePicksRequest:
    return PrizePicksRequest(
        source="prizepicks",
        league="MLB",
        league_id=PRIZEPICKS_MLB_LEAGUE_ID,
        state_code=state_code,
        per_page=per_page,
    )


def build_prizepicks_all_sports_request(*, state_code: str = "MO", per_page: int = 250) -> PrizePicksRequest:
    return PrizePicksRequest(
        source="prizepicks_all_sports",
        league="ALL",
        league_id=None,
        state_code=state_code,
        per_page=per_page,
    )


def fetch_prizepicks_all_sports_board(
    *,
    root: Path | None = None,
    state_code: str = "MO",
    per_page: int = 250,
    timeout: int = 30,
    max_pages: int = 25,
    pulled_at: datetime | None = None,
    fetch_group_id: str | None = None,
) -> RawSnapshot:
    """Fetch and persist the current full PrizePicks board raw snapshot."""

    request = build_prizepicks_all_sports_request(state_code=state_code, per_page=per_page)
    return _fetch_prizepicks_board(
        request=request,
        root=root,
        timeout=timeout,
        max_pages=max_pages,
        pulled_at=pulled_at,
        fetch_group_id=fetch_group_id,
    )


def fetch_prizepicks_mlb_board(
    *,
    root: Path | None = None,
    state_code: str = "MO",
    per_page: int = 250,
    timeout: int = 30,
    max_pages: int = 25,
    pulled_at: datetime | None = None,
    fetch_group_id: str | None = None,
) -> RawSnapshot:
    """Fetch and persist the current PrizePicks MLB board raw snapshot."""

    request = build_prizepicks_mlb_request(state_code=state_code, per_page=per_page)
    return _fetch_prizepicks_board(
        request=request,
        root=root,
        timeout=timeout,
        max_pages=max_pages,
        pulled_at=pulled_at,
        fetch_group_id=fetch_group_id,
    )


def _fetch_prizepicks_board(
    *,
    request: PrizePicksRequest,
    root: Path | None = None,
    timeout: int = 30,
    max_pages: int = 25,
    pulled_at: datetime | None = None,
    fetch_group_id: str | None = None,
) -> RawSnapshot:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    pages: list[dict[str, Any]] = []
    statuses: list[int] = []
    total_pages = 1

    page = 1
    while page <= min(total_pages, max_pages):
        response = get_with_retries(request.url, session=session, params=request.params(page), timeout=timeout)
        statuses.append(response.status_code)
        response.raise_for_status()
        payload = response.json()
        pages.append(payload)
        meta = payload.get("meta") or {}
        total_pages = int(meta.get("total_pages") or total_pages or 1)
        page += 1

    combined_payload = _combine_pages(pages)
    combined_payload["_atlas_fetch"] = {
        "source": request.source,
        "league": request.league,
        "league_id": request.league_id,
        "page_count": len(pages),
        "status_codes": statuses,
        "max_pages": max_pages,
        "fetch_group_id": fetch_group_id,
    }
    return write_raw_snapshot(
        source=request.source,
        payload=combined_payload,
        request={
            "url": request.url,
            "params": request.params(1),
            "page_count": len(pages),
            "status_codes": statuses,
            "fetch_group_id": fetch_group_id,
        },
        root=root,
        pulled_at=pulled_at,
    )


def _combine_pages(pages: list[dict[str, Any]]) -> dict[str, Any]:
    data: list[dict[str, Any]] = []
    included_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    links: dict[str, Any] = {}
    page_meta: list[dict[str, Any]] = []

    for payload in pages:
        data.extend(payload.get("data", []) or [])
        for item in payload.get("included", []) or []:
            key = (str(item.get("type") or ""), str(item.get("id") or ""))
            included_by_key[key] = item
        if payload.get("links"):
            links.update(payload["links"])
        if payload.get("meta"):
            page_meta.append(payload["meta"])

    return {
        "data": data,
        "included": list(included_by_key.values()),
        "links": links,
        "meta": {
            "combined": True,
            "page_count": len(pages),
            "page_meta": page_meta,
            "projection_count": len(data),
            "included_count": len(included_by_key),
        },
    }
