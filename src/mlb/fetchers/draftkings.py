"""DraftKings Sportsbook live MLB source probe/fetcher."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from mlb.contracts import RawSnapshot
from mlb.fetchers.http import get_with_retries
from mlb.sources.snapshots import write_raw_snapshot

DRAFTKINGS_MLB_LIVE_SOURCE = "draftkings_mlb_live"
DRAFTKINGS_MLB_PICK6_SOURCE = "draftkings_mlb_pick6"
DRAFTKINGS_MLB_SPORTSBOOK_SOURCE = "draftkings_mlb_sportsbook"
DRAFTKINGS_SPORTS_CONTENT_VIEWS_BFF = "https://sportsbook-nash.draftkings.com/api/sportscontent/views/{site}"
DRAFTKINGS_SPORTSBOOK_LEAGUE_SUBCATEGORY_URL = (
    "https://sportsbook-nash.draftkings.com/sites/{site}/api/sportscontent/controldata/"
    "league/leagueSubcategory/v1/markets"
)
DRAFTKINGS_API_BASE_URL = "https://api.draftkings.com"
DRAFTKINGS_DEFAULT_SITE = "dkusnj"
DRAFTKINGS_DEFAULT_SPORTSBOOK_SITE = "US-MO-SB"
DRAFTKINGS_BASEBALL_DISPLAY_GROUP_ID = 7
DRAFTKINGS_MLB_EVENT_GROUP_ID = 84240
DRAFTKINGS_MLB_PICK6_SPORT_LEAGUE_KEY = "2-2"
DRAFTKINGS_MLB_SPORTSBOOK_SUBCATEGORIES = {
    "home_runs": "17319",
    "hits": "17320",
    "total_bases": "17321",
    "rbis": "17322",
    "stolen_bases": "17408",
    "walks": "17411",
    "hits_runs_rbis": "17843",
    "hitter_strikeouts": "17849",
    "pitcher_strikeouts": "17323",
    "pitching_outs": "17413",
    "earned_runs_allowed": "19458",
    "hits_allowed": "19457",
    "walks_allowed": "19456",
}


@dataclass(frozen=True)
class DraftKingsRequest:
    source: str
    url: str
    site: str
    display_group_id: int
    event_group_id: int


def build_draftkings_mlb_live_request(*, site: str = DRAFTKINGS_DEFAULT_SITE) -> DraftKingsRequest:
    base = DRAFTKINGS_SPORTS_CONTENT_VIEWS_BFF.format(site=site)
    url = f"{base}/v1/sports/{DRAFTKINGS_BASEBALL_DISPLAY_GROUP_ID}/live"
    return DraftKingsRequest(
        source=DRAFTKINGS_MLB_LIVE_SOURCE,
        url=url,
        site=site,
        display_group_id=DRAFTKINGS_BASEBALL_DISPLAY_GROUP_ID,
        event_group_id=DRAFTKINGS_MLB_EVENT_GROUP_ID,
    )


def fetch_draftkings_mlb_live(
    *,
    root: Path | None = None,
    site: str = DRAFTKINGS_DEFAULT_SITE,
    timeout: int = 60,
) -> RawSnapshot:
    request = build_draftkings_mlb_live_request(site=site)
    response = get_with_retries(
        request.url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://sportsbook.draftkings.com",
            "Referer": "https://sportsbook.draftkings.com/leagues/baseball/mlb",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
            ),
            "x-client-feature": "league-page",
            "x-client-name": "web",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    counts = count_draftkings_live_offers(payload)
    return write_raw_snapshot(
        source=DRAFTKINGS_MLB_LIVE_SOURCE,
        payload={
            "_atlas_fetch": {
                "source": DRAFTKINGS_MLB_LIVE_SOURCE,
                "site": request.site,
                "display_group_id": request.display_group_id,
                "event_group_id": request.event_group_id,
                "url": request.url,
                **counts,
            },
            "response": payload,
        },
        request={
            "url": request.url,
            "site": request.site,
            "display_group_id": request.display_group_id,
            "event_group_id": request.event_group_id,
            **counts,
        },
        root=root,
    )


def fetch_draftkings_mlb_pick6(
    *,
    root: Path | None = None,
    sport_league_key: str = DRAFTKINGS_MLB_PICK6_SPORT_LEAGUE_KEY,
    timeout: int = 60,
) -> RawSnapshot:
    """Fetch DraftKings Pick6 MLB pick groups and category pickcards."""

    headers = _pick6_headers()
    main = _get_json(f"{DRAFTKINGS_API_BASE_URL}/pick6/v1/pickgroups/main", headers=headers, timeout=timeout)
    league_payload = _get_json(
        f"{DRAFTKINGS_API_BASE_URL}/pick6/v1/pickgroups/{sport_league_key}",
        headers=headers,
        timeout=timeout,
    )
    pick_groups = [
        group
        for group in league_payload.get("pickGroups", []) or []
        if isinstance(group, dict) and group.get("pickGroupId")
    ]
    category_responses = []
    for group in pick_groups:
        pick_group_id = int(group["pickGroupId"])
        base_category = _get_json(
            f"{DRAFTKINGS_API_BASE_URL}/pick6/v1/pickgroups/{pick_group_id}/category/pickcards",
            headers=headers,
            timeout=timeout,
        )
        category_ids = sorted(_category_ids(base_category))
        category_payloads = [{"category_id": int(base_category.get("pickCategoryId") or 0), "payload": base_category}]
        for category_id in category_ids:
            if category_id == int(base_category.get("pickCategoryId") or 0):
                continue
            category_payloads.append(
                {
                    "category_id": category_id,
                    "payload": _get_json(
                        f"{DRAFTKINGS_API_BASE_URL}/pick6/v1/pickgroups/{pick_group_id}/category/{category_id}/pickcards",
                        headers=headers,
                        timeout=timeout,
                    ),
                }
            )
        category_responses.append(
            {
                "pick_group_id": pick_group_id,
                "pick_group_state": str(group.get("pickGroupState") or ""),
                "min_start_time": str(group.get("minStartTime") or ""),
                "max_start_time": str(group.get("maxStartTime") or ""),
                "categories": category_payloads,
            }
        )

    counts = count_draftkings_pick6_rows(category_responses)
    payload = {
        "_atlas_fetch": {
            "source": DRAFTKINGS_MLB_PICK6_SOURCE,
            "base_url": DRAFTKINGS_API_BASE_URL,
            "sport_league_key": sport_league_key,
            "pick_group_count": len(pick_groups),
            **counts,
        },
        "main": main,
        "league": league_payload,
        "category_responses": category_responses,
    }
    return write_raw_snapshot(
        source=DRAFTKINGS_MLB_PICK6_SOURCE,
        payload=payload,
        request={
            "base_url": DRAFTKINGS_API_BASE_URL,
            "sport_league_key": sport_league_key,
            "pick_group_count": len(pick_groups),
            **counts,
        },
        root=root,
    )


def fetch_draftkings_mlb_sportsbook_props(
    *,
    root: Path | None = None,
    site: str = DRAFTKINGS_DEFAULT_SPORTSBOOK_SITE,
    subcategories: dict[str, str] | None = None,
    timeout: int = 60,
) -> RawSnapshot:
    """Fetch DraftKings Sportsbook MLB player-prop subcategory markets."""

    selected = subcategories or DRAFTKINGS_MLB_SPORTSBOOK_SUBCATEGORIES
    headers = _sportsbook_headers()
    responses: list[dict[str, Any]] = []
    for market, subcategory_id in selected.items():
        url = _sportsbook_subcategory_url(site=site, subcategory_id=str(subcategory_id))
        payload = _get_json(url, headers=headers, timeout=timeout)
        responses.append(
            {
                "market": market,
                "subcategory_id": str(subcategory_id),
                "url": url,
                "response": payload,
                "event_count": len(payload.get("events", []) or []),
                "market_count": len(payload.get("markets", []) or []),
                "selection_count": len(payload.get("selections", []) or []),
            }
        )

    counts = {
        "subcategory_count": len(responses),
        "event_count": sum(int(item.get("event_count") or 0) for item in responses),
        "market_count": sum(int(item.get("market_count") or 0) for item in responses),
        "selection_count": sum(int(item.get("selection_count") or 0) for item in responses),
    }
    payload = {
        "_atlas_fetch": {
            "source": DRAFTKINGS_MLB_SPORTSBOOK_SOURCE,
            "site": site,
            "event_group_id": DRAFTKINGS_MLB_EVENT_GROUP_ID,
            **counts,
        },
        "responses": responses,
    }
    return write_raw_snapshot(
        source=DRAFTKINGS_MLB_SPORTSBOOK_SOURCE,
        payload=payload,
        request={
            "site": site,
            "event_group_id": DRAFTKINGS_MLB_EVENT_GROUP_ID,
            "subcategories": selected,
            **counts,
        },
        root=root,
    )


def count_draftkings_live_offers(payload: dict[str, Any]) -> dict[str, int]:
    subcategory_count = 0
    event_group_count = 0
    offer_count = 0
    outcome_count = 0
    display_group = payload.get("featuredDisplayGroup") if isinstance(payload, dict) else {}
    for subcategory in (display_group or {}).get("featuredSubcategories", []) or []:
        if not isinstance(subcategory, dict):
            continue
        subcategory_count += 1
        groups = subcategory.get("featuredEventGroupSubcategories", []) or []
        event_group_count += len(groups)
        for group in groups:
            if not isinstance(group, dict):
                continue
            for offer_block in group.get("offers", []) or []:
                offers = offer_block if isinstance(offer_block, list) else [offer_block]
                for offer in offers:
                    if not isinstance(offer, dict):
                        continue
                    offer_count += 1
                    outcome_count += len(offer.get("outcomes", []) or [])
    return {
        "subcategory_count": subcategory_count,
        "event_group_count": event_group_count,
        "offer_count": offer_count,
        "outcome_count": outcome_count,
    }


def count_draftkings_pick6_rows(category_responses: list[dict[str, Any]]) -> dict[str, int]:
    category_count = 0
    pickcard_count = 0
    active_market_count = 0
    for group in category_responses:
        for category in group.get("categories", []) or []:
            category_count += 1
            cards = ((category.get("payload") or {}).get("pickCardByPickableId") or {})
            pickcard_count += len(cards)
            for card in cards.values():
                if isinstance(card, dict):
                    active_market_count += len(card.get("activePickableMarkets", []) or [])
    return {
        "category_count": category_count,
        "pickcard_count": pickcard_count,
        "active_market_count": active_market_count,
    }


def _category_ids(payload: dict[str, Any]) -> set[int]:
    ids: set[int] = set()
    for value in (payload.get("pickCategoryById") or {}).keys():
        try:
            ids.add(int(value))
        except (TypeError, ValueError):
            continue
    for value in payload.get("orderedPickCategoryIds", []) or []:
        try:
            ids.add(int(value))
        except (TypeError, ValueError):
            continue
    return ids


def _get_json(url: str, *, headers: dict[str, str], timeout: int) -> dict[str, Any]:
    response = get_with_retries(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {"data": payload}


def _sportsbook_subcategory_url(*, site: str, subcategory_id: str) -> str:
    from urllib.parse import urlencode

    base = DRAFTKINGS_SPORTSBOOK_LEAGUE_SUBCATEGORY_URL.format(site=site)
    params = {
        "isBatchable": "false",
        "templateVars": str(DRAFTKINGS_MLB_EVENT_GROUP_ID),
        "eventsQuery": (
            f"$filter=leagueId eq '{DRAFTKINGS_MLB_EVENT_GROUP_ID}' "
            f"AND clientMetadata/Subcategories/any(s: s/Id eq '{subcategory_id}')"
        ),
        "marketsQuery": (
            f"$filter=clientMetadata/subCategoryId eq '{subcategory_id}' "
            "AND tags/all(t: t ne 'SportcastBetBuilder')"
        ),
        "include": "Events",
        "entity": "events",
    }
    query = urlencode(params, safe="$',() /:")
    return f"{base}?{query}"


def _sportsbook_headers() -> dict[str, str]:
    return {
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://sportsbook.draftkings.com",
        "Referer": "https://sportsbook.draftkings.com/leagues/baseball/mlb?category=games&subcategory=player-props",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
        ),
        "x-client-feature": "league-page",
        "x-client-name": "web",
    }


def _pick6_headers() -> dict[str, str]:
    return {
        "Accept": "application/json,text/plain,*/*",
        "Origin": "https://pick6.draftkings.com",
        "Referer": "https://pick6.draftkings.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
        ),
    }
