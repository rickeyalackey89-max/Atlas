"""BettingPros MLB player-prop market fetcher."""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

import requests

from mlb.contracts import RawSnapshot
from mlb.fetchers.http import get_with_retries
from mlb.sources.snapshots import write_raw_snapshot

BETTINGPROS_BASE_URL = "https://api.bettingpros.com/v3"
BETTINGPROS_PUBLIC_API_ASSET_URL = "https://www.bettingpros.com/dist/assets/api-Bit-jfrj.js"
BETTINGPROS_MLB_PROPS_SOURCE = "bettingpros_mlb_props"

BETTINGPROS_MLB_MARKET_ALIASES = {
    285: "pitcher_strikeouts",
    287: "hits",
    288: "runs",
    289: "rbis",
    290: "earned_runs_allowed",
    291: "doubles",
    292: "triples",
    293: "total_bases",
    294: "stolen_bases",
    295: "singles",
    299: "home_runs",
    403: "hits_runs_rbis",
    404: "hits_allowed",
    405: "pitching_outs",
    408: "walks_allowed",
}
BETTINGPROS_MLB_MARKET_IDS = tuple(BETTINGPROS_MLB_MARKET_ALIASES)
_CANONICAL_TO_BETTINGPROS = {
    market: market_id for market_id, market in BETTINGPROS_MLB_MARKET_ALIASES.items()
}


def parse_bettingpros_market_ids(value: str | tuple[int, ...] | tuple[str, ...] | None) -> tuple[int, ...]:
    if value is None or value in {"", "default", "all"}:
        return BETTINGPROS_MLB_MARKET_IDS
    if isinstance(value, tuple):
        raw_values = value
    else:
        raw_values = tuple(part.strip() for part in value.split(",") if part.strip())

    resolved: list[int] = []
    for item in raw_values:
        market_id = _market_id(item)
        if market_id is not None and market_id not in resolved:
            resolved.append(market_id)
    return tuple(resolved) or BETTINGPROS_MLB_MARKET_IDS


def parse_bettingpros_book_ids(value: str | tuple[int, ...] | tuple[str, ...] | None) -> tuple[int, ...]:
    if value is None or value in {"", "default", "all"}:
        return ()
    if value == "major":
        return (10, 12, 19, 24, 14)
    if isinstance(value, tuple):
        raw_values = value
    else:
        raw_values = tuple(part.strip() for part in value.split(",") if part.strip())

    resolved: list[int] = []
    for item in raw_values:
        try:
            book_id = int(item)
        except (TypeError, ValueError):
            continue
        if book_id not in resolved:
            resolved.append(book_id)
    return tuple(resolved)


def fetch_bettingpros_mlb_props(
    *,
    game_date: date,
    root: Path | None = None,
    include_offers: bool = False,
    market_ids: tuple[int, ...] = BETTINGPROS_MLB_MARKET_IDS,
    book_ids: tuple[int, ...] = (),
    api_key: str | None = None,
    discover_public_key: bool = True,
    props_limit: int = 200,
    offer_limit: int = 10,
    offer_workers: int = 4,
    max_offer_pages: int = 0,
    timeout: int = 60,
) -> RawSnapshot:
    """Fetch BettingPros MLB props and, optionally, all sportsbook offer rows."""

    session = requests.Session()
    props_pages = _fetch_props_pages(session=session, game_date=game_date, limit=props_limit, timeout=timeout)
    props, books, markets, events = _merge_props_pages(props_pages)

    offers: list[dict[str, Any]] = []
    offers_complete = False
    offers_total_pages = 0
    offers_total_items = 0
    key_source = ""
    if include_offers and events:
        resolved_key, key_source = resolve_bettingpros_api_key(
            api_key=api_key,
            discover_public_key=discover_public_key,
            timeout=timeout,
        )
        if not resolved_key:
            raise RuntimeError("BETTINGPROS_API_KEY is required for BettingPros offers when public-key discovery fails")
        offer_pages = _fetch_offer_pages(
            session=session,
            game_date=game_date,
            event_ids=tuple(_id(event) for event in events if _id(event)),
            market_ids=market_ids,
            book_ids=book_ids,
            api_key=resolved_key,
            limit=offer_limit,
            workers=offer_workers,
            max_pages=max_offer_pages,
            timeout=timeout,
        )
        offers = [offer for page in offer_pages for offer in page.get("offers", []) or [] if isinstance(offer, dict)]
        pagination = (offer_pages[-1].get("_pagination") or {}) if offer_pages else {}
        offers_total_pages = int(pagination.get("total_pages") or 0)
        offers_total_items = int(pagination.get("total_items") or 0)
        offers_complete = bool(offer_pages) and (not max_offer_pages or len(offer_pages) >= offers_total_pages)

    request = {
        "base_url": BETTINGPROS_BASE_URL,
        "source": BETTINGPROS_MLB_PROPS_SOURCE,
        "sport": "MLB",
        "game_date": game_date.isoformat(),
        "include_offers": include_offers,
        "market_ids": ",".join(str(market_id) for market_id in market_ids),
        "book_ids": ",".join(str(book_id) for book_id in book_ids),
        "props_limit": props_limit,
        "offer_limit": offer_limit,
        "offer_workers": offer_workers,
        "max_offer_pages": max_offer_pages,
        "props_page_count": len(props_pages),
        "prop_count": len(props),
        "event_count": len(events),
        "market_count": len(markets),
        "book_count": len(books),
        "offer_count": len(offers),
        "offers_total_pages": offers_total_pages,
        "offers_total_items": offers_total_items,
        "offers_complete": offers_complete,
        "api_key_source": key_source,
    }
    payload = {
        "_atlas_fetch": request,
        "props": props,
        "books": books,
        "markets": markets,
        "events": events,
        "offers": offers,
        "props_pagination": [page.get("_pagination") or {} for page in props_pages],
    }
    return write_raw_snapshot(
        source=BETTINGPROS_MLB_PROPS_SOURCE,
        payload=payload,
        request=request,
        root=root,
    )


def resolve_bettingpros_api_key(
    *,
    api_key: str | None = None,
    discover_public_key: bool = True,
    timeout: int = 30,
) -> tuple[str, str]:
    explicit = (api_key or "").strip()
    if explicit:
        return explicit, "argument"
    for env_name in ("BETTINGPROS_API_KEY", "BETTING_PROS_API_KEY"):
        value = os.environ.get(env_name, "").strip()
        if value:
            return value, env_name
    if not discover_public_key:
        return "", ""

    response = get_with_retries(BETTINGPROS_PUBLIC_API_ASSET_URL, headers=_headers(), timeout=timeout)
    response.raise_for_status()
    match = re.search(
        r"[\"'`]x-api-key[\"'`]\s*:\s*[\"'`]([^\"'`]+)[\"'`]",
        response.text,
    )
    if not match:
        return "", ""
    return match.group(1), "public_asset"


def _fetch_props_pages(
    *,
    session: requests.Session,
    game_date: date,
    limit: int,
    timeout: int,
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = _get_json(
            session,
            f"{BETTINGPROS_BASE_URL}/props",
            params={
                "sport": "MLB",
                "date": game_date.isoformat(),
                "limit": max(1, min(limit, 200)),
                "page": page,
                "include_markets": "true",
                "include_books": "true",
                "include_events": "true",
            },
            headers=_headers(),
            timeout=timeout,
        )
        pages.append(payload)
        pagination = payload.get("_pagination") or {}
        total_pages = int(pagination.get("total_pages") or page)
        if page >= total_pages:
            break
        page += 1
    return pages


def _fetch_offer_pages(
    *,
    session: requests.Session,
    game_date: date,
    event_ids: tuple[str, ...],
    market_ids: tuple[int, ...],
    book_ids: tuple[int, ...],
    api_key: str,
    limit: int,
    workers: int,
    max_pages: int,
    timeout: int,
) -> list[dict[str, Any]]:
    if not event_ids or not market_ids:
        return []
    page_limit = max(1, min(limit, 10))

    def fetch_page(page_number: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "sport": "MLB",
            "date": game_date.isoformat(),
            "event_id": ":".join(event_ids),
            "market_id": ":".join(str(market_id) for market_id in market_ids),
            "limit": page_limit,
            "page": page_number,
            "include_markets": "true",
            "include_books": "true",
        }
        if book_ids:
            params["book_id"] = ":".join(str(book_id) for book_id in book_ids)
        return _get_json(
            session,
            f"{BETTINGPROS_BASE_URL}/offers",
            params=params,
            headers={**_headers(), "x-api-key": api_key},
            timeout=timeout,
        )

    first = fetch_page(1)
    pagination = first.get("_pagination") or {}
    total_pages = int(pagination.get("total_pages") or 1)
    last_page = min(total_pages, max_pages) if max_pages else total_pages
    if last_page <= 1:
        return [first]

    pages_by_number: dict[int, dict[str, Any]] = {1: first}
    max_workers = max(1, min(int(workers or 1), last_page - 1))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_page, page_number): page_number for page_number in range(2, last_page + 1)}
        for future in as_completed(futures):
            page_number = futures[future]
            pages_by_number[page_number] = future.result()
    return [pages_by_number[page_number] for page_number in sorted(pages_by_number)]


def _merge_props_pages(
    pages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    props: list[dict[str, Any]] = []
    books_by_id: dict[str, dict[str, Any]] = {}
    markets_by_id: dict[str, dict[str, Any]] = {}
    events_by_id: dict[str, dict[str, Any]] = {}
    for page in pages:
        props.extend(prop for prop in page.get("props", []) or [] if isinstance(prop, dict))
        for book in page.get("books", []) or []:
            if isinstance(book, dict) and _id(book):
                books_by_id[_id(book)] = book
        for market in page.get("markets", []) or []:
            if isinstance(market, dict) and _id(market):
                markets_by_id[_id(market)] = market
        for event in page.get("events", []) or []:
            if isinstance(event, dict) and _id(event):
                events_by_id[_id(event)] = event
    return (
        props,
        sorted(books_by_id.values(), key=lambda item: int(item.get("id") or 0)),
        sorted(markets_by_id.values(), key=lambda item: int(item.get("id") or 0)),
        sorted(events_by_id.values(), key=lambda item: int(item.get("id") or 0)),
    )


def _get_json(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any],
    headers: dict[str, str],
    timeout: int,
) -> dict[str, Any]:
    response = get_with_retries(url, session=session, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {"data": payload}


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json,text/plain,*/*",
        "Origin": "https://www.bettingpros.com",
        "Referer": "https://www.bettingpros.com/mlb/odds/player-props/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
        ),
    }


def _market_id(value: int | str) -> int | None:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = _CANONICAL_TO_BETTINGPROS.get(str(value))
    if numeric in BETTINGPROS_MLB_MARKET_ALIASES:
        return numeric
    return None


def _id(value: dict[str, Any]) -> str:
    raw = value.get("id")
    return str(raw) if raw not in (None, "") else ""
