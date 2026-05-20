"""ParlayAPI MLB historical closing-prop fetcher."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from mlb.contracts import RawSnapshot
from mlb.fetchers.http import get_with_retries
from mlb.sources.snapshots import write_raw_snapshot

PARLAYAPI_BASE_URL = "https://parlay-api.com/v1"
PARLAYAPI_MLB_SPORT_KEY = "baseball_mlb"
PARLAYAPI_HISTORICAL_CLOSING_PROPS_SOURCE = "parlayapi_mlb_historical_closing_props"

PARLAYAPI_MLB_MARKET_ALIASES = {
    "player_hits": "hits",
    "player_total_bases": "total_bases",
    "player_rbis": "rbis",
    "player_runs": "runs",
    "player_hits_runs_rbis": "hits_runs_rbis",
    "player_singles": "singles",
    "player_doubles": "doubles",
    "player_triples": "triples",
    "player_walks": "walks",
    "player_home_runs": "home_runs",
    "player_strikeouts": "pitcher_strikeouts",
    "player_pitcher_outs": "pitching_outs",
    "player_hits_allowed": "hits_allowed",
    "player_earned_runs": "earned_runs_allowed",
}

PARLAYAPI_MLB_MARKETS = tuple(PARLAYAPI_MLB_MARKET_ALIASES)
_CANONICAL_TO_PARLAYAPI = {value: key for key, value in PARLAYAPI_MLB_MARKET_ALIASES.items()}


@dataclass(frozen=True)
class ParlayApiHttpResponse:
    payload: Any
    status_code: int
    url: str
    quota: dict[str, str]

    def to_manifest_payload(self) -> dict[str, Any]:
        return {
            "payload": self.payload,
            "status_code": self.status_code,
            "url": _strip_api_key(self.url),
            "quota": self.quota,
        }


def parse_parlayapi_markets(value: str | tuple[str, ...] | None) -> tuple[str, ...]:
    if value is None or value == "default" or value == "all":
        return PARLAYAPI_MLB_MARKETS
    if isinstance(value, tuple):
        raw_markets = value
    else:
        raw_markets = tuple(part.strip() for part in value.split(",") if part.strip())

    markets: list[str] = []
    for market in raw_markets:
        resolved = _CANONICAL_TO_PARLAYAPI.get(market, market)
        if resolved not in markets:
            markets.append(resolved)
    return tuple(markets) or PARLAYAPI_MLB_MARKETS


def fetch_parlayapi_mlb_historical_closing_props(
    *,
    api_key: str,
    snapshot_date: date,
    root: Path | None = None,
    markets: tuple[str, ...] = PARLAYAPI_MLB_MARKETS,
    bookmakers: str | None = None,
    snapshot_time_utc: time = time(18, 0),
    timeout: int = 60,
) -> RawSnapshot:
    """Fetch one ParlayAPI historical MLB closing-prop snapshot by market."""

    snapshot_dt = datetime.combine(snapshot_date, snapshot_time_utc, tzinfo=timezone.utc)
    responses = []
    for market in markets:
        params = {
            "date": snapshot_date.isoformat(),
            "markets": market,
            "oddsFormat": "american",
        }
        if bookmakers:
            params["bookmakers"] = bookmakers
        responses.append(
            {
                "market": market,
                "response": _get_json(
                    f"{PARLAYAPI_BASE_URL}/historical/sports/{PARLAYAPI_MLB_SPORT_KEY}/closing-odds",
                    api_key=api_key,
                    params=params,
                    timeout=timeout,
                ).to_manifest_payload(),
            }
        )

    payload = {
        "_atlas_fetch": {
            "source": PARLAYAPI_HISTORICAL_CLOSING_PROPS_SOURCE,
            "sport_key": PARLAYAPI_MLB_SPORT_KEY,
            "snapshot_date": snapshot_date.isoformat(),
            "snapshot_time_utc": snapshot_time_utc.isoformat(),
            "snapshot_timestamp": snapshot_dt.isoformat().replace("+00:00", "Z"),
            "markets": markets,
            "bookmakers": bookmakers or "",
            "market_call_count": len(responses),
        },
        "responses": responses,
    }
    return write_raw_snapshot(
        source=PARLAYAPI_HISTORICAL_CLOSING_PROPS_SOURCE,
        payload=payload,
        request={
            "sport_key": PARLAYAPI_MLB_SPORT_KEY,
            "snapshot_date": snapshot_date.isoformat(),
            "snapshot_timestamp": snapshot_dt.isoformat().replace("+00:00", "Z"),
            "markets": ",".join(markets),
            "bookmakers": bookmakers or "",
            "odds_format": "american",
            "market_call_count": len(responses),
        },
        root=root,
        pulled_at=snapshot_dt,
    )


def _get_json(url: str, *, api_key: str, params: dict[str, Any], timeout: int) -> ParlayApiHttpResponse:
    response = get_with_retries(url, headers={"X-API-Key": api_key}, params=params, timeout=timeout)
    response.raise_for_status()
    return ParlayApiHttpResponse(
        payload=response.json(),
        status_code=response.status_code,
        url=response.url,
        quota={
            "x_requests_used": response.headers.get("x-requests-used", ""),
            "x_requests_remaining": response.headers.get("x-requests-remaining", ""),
            "x_requests_last": response.headers.get("x-requests-last", ""),
        },
    )


def _strip_api_key(url: str) -> str:
    parts = urlsplit(url)
    safe_query = urlencode([(key, value) for key, value in parse_qsl(parts.query) if key.lower() != "apikey"])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, safe_query, parts.fragment))
