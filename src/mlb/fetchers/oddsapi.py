"""The Odds API MLB raw snapshot fetchers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from mlb.contracts import RawSnapshot
from mlb.fetchers.http import get_with_retries
from mlb.sources.catalog import (
    ODDSAPI_BASE_URL,
    ODDSAPI_MLB_BOOKMAKERS,
    ODDSAPI_MLB_ALL_MARKETS,
    ODDSAPI_MLB_MARKETS,
    ODDSAPI_MLB_SPORT_KEY,
)
from mlb.sources.snapshots import write_raw_snapshot


@dataclass(frozen=True)
class OddsApiRequestConfig:
    regions: str = "us"
    bookmakers: tuple[str, ...] = ODDSAPI_MLB_BOOKMAKERS
    markets: tuple[str, ...] = ODDSAPI_MLB_MARKETS
    odds_format: str = "american"
    date_format: str = "iso"

    @property
    def markets_csv(self) -> str:
        return ",".join(self.markets)

    @property
    def bookmakers_csv(self) -> str:
        return ",".join(self.bookmakers)


def parse_markets(value: str | tuple[str, ...] | None) -> tuple[str, ...]:
    if value is None or value == "default":
        return ODDSAPI_MLB_MARKETS
    if value == "all":
        return ODDSAPI_MLB_ALL_MARKETS
    if isinstance(value, tuple):
        return value
    markets = tuple(part.strip() for part in value.split(",") if part.strip())
    return markets or ODDSAPI_MLB_MARKETS


def parse_bookmakers(value: str | tuple[str, ...] | None) -> tuple[str, ...]:
    if value is None or value == "default":
        return ODDSAPI_MLB_BOOKMAKERS
    if value == "all":
        return ()
    if isinstance(value, tuple):
        return value
    bookmakers = tuple(part.strip() for part in value.split(",") if part.strip())
    return bookmakers or ODDSAPI_MLB_BOOKMAKERS


def fetch_oddsapi_mlb_live_props(
    *,
    api_key: str,
    root: Path | None = None,
    regions: str = "us",
    bookmakers: tuple[str, ...] = ODDSAPI_MLB_BOOKMAKERS,
    markets: tuple[str, ...] = ODDSAPI_MLB_MARKETS,
    timeout: int = 30,
) -> RawSnapshot:
    """Fetch live MLB event IDs and per-event player prop odds."""

    config = OddsApiRequestConfig(regions=regions, bookmakers=bookmakers, markets=markets)
    events_response = _get_json(
        f"{ODDSAPI_BASE_URL}/sports/{ODDSAPI_MLB_SPORT_KEY}/events",
        {"apiKey": api_key, "dateFormat": config.date_format},
        timeout=timeout,
    )
    events = events_response.payload if isinstance(events_response.payload, list) else []
    event_odds = []

    for event in events:
        event_id = str(event.get("id") or "")
        if not event_id:
            continue
        event_odds.append(
            {
                "event_id": event_id,
                "response": _get_json(
                    f"{ODDSAPI_BASE_URL}/sports/{ODDSAPI_MLB_SPORT_KEY}/events/{event_id}/odds",
                    _event_odds_params({
                        "apiKey": api_key,
                        "regions": config.regions,
                        "bookmakers": config.bookmakers_csv,
                        "markets": config.markets_csv,
                        "oddsFormat": config.odds_format,
                        "dateFormat": config.date_format,
                    }),
                    timeout=timeout,
                ).to_manifest_payload(),
            }
        )

    payload = {
        "_atlas_fetch": {
            "source": "oddsapi_mlb_live",
            "sport_key": ODDSAPI_MLB_SPORT_KEY,
            "regions": config.regions,
            "bookmakers": config.bookmakers,
            "markets": config.markets,
            "event_count": len(events),
            "event_odds_count": len(event_odds),
        },
        "events": events_response.to_manifest_payload(),
        "event_odds": event_odds,
    }
    return write_raw_snapshot(
        source="oddsapi_mlb_live",
        payload=payload,
        request={
            "sport_key": ODDSAPI_MLB_SPORT_KEY,
            "regions": config.regions,
            "bookmakers": config.bookmakers_csv,
            "markets": config.markets_csv,
            "odds_format": config.odds_format,
            "date_format": config.date_format,
            "event_count": len(events),
            "event_odds_count": len(event_odds),
        },
        root=root,
    )


def fetch_oddsapi_mlb_historical_props(
    *,
    api_key: str,
    snapshot_date: date,
    root: Path | None = None,
    snapshot_time_utc: time = time(18, 0),
    regions: str = "us",
    bookmakers: tuple[str, ...] = ODDSAPI_MLB_BOOKMAKERS,
    markets: tuple[str, ...] = ODDSAPI_MLB_MARKETS,
    timeout: int = 30,
) -> RawSnapshot:
    """Fetch one historical MLB player-prop date from The Odds API."""

    config = OddsApiRequestConfig(regions=regions, bookmakers=bookmakers, markets=markets)
    snapshot_dt = datetime.combine(snapshot_date, snapshot_time_utc, tzinfo=timezone.utc)
    snapshot_iso = snapshot_dt.isoformat().replace("+00:00", "Z")
    events_response = _get_json(
        f"{ODDSAPI_BASE_URL}/historical/sports/{ODDSAPI_MLB_SPORT_KEY}/events",
        {"apiKey": api_key, "date": snapshot_iso, "dateFormat": config.date_format},
        timeout=timeout,
    )
    events_payload = events_response.payload if isinstance(events_response.payload, dict) else {}
    events = events_payload.get("data", []) or []
    event_odds = []

    for event in events:
        event_id = str(event.get("id") or "")
        if not event_id:
            continue
        event_odds_response = _get_json(
            f"{ODDSAPI_BASE_URL}/historical/sports/{ODDSAPI_MLB_SPORT_KEY}/events/{event_id}/odds",
            _event_odds_params({
                "apiKey": api_key,
                "date": snapshot_iso,
                "regions": config.regions,
                "bookmakers": config.bookmakers_csv,
                "markets": config.markets_csv,
                "oddsFormat": config.odds_format,
                "dateFormat": config.date_format,
            }),
            timeout=timeout,
        )
        event_odds.append({"event_id": event_id, "response": event_odds_response.to_manifest_payload()})

    payload = {
        "_atlas_fetch": {
            "source": "oddsapi_mlb_historical",
            "sport_key": ODDSAPI_MLB_SPORT_KEY,
            "snapshot_date": snapshot_date.isoformat(),
            "snapshot_time_utc": snapshot_time_utc.isoformat(),
            "snapshot_timestamp": snapshot_iso,
            "regions": config.regions,
            "bookmakers": config.bookmakers,
            "markets": config.markets,
            "event_count": len(events),
            "event_odds_count": len(event_odds),
        },
        "events": events_response.to_manifest_payload(),
        "event_odds": event_odds,
    }
    return write_raw_snapshot(
        source="oddsapi_mlb_historical",
        payload=payload,
        request={
            "sport_key": ODDSAPI_MLB_SPORT_KEY,
            "snapshot_date": snapshot_date.isoformat(),
            "snapshot_timestamp": snapshot_iso,
            "regions": config.regions,
            "bookmakers": config.bookmakers_csv,
            "markets": config.markets_csv,
            "odds_format": config.odds_format,
            "date_format": config.date_format,
            "event_count": len(events),
            "event_odds_count": len(event_odds),
        },
        root=root,
        pulled_at=snapshot_dt,
    )


@dataclass(frozen=True)
class OddsApiHttpResponse:
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


def _get_json(url: str, params: dict[str, Any], *, timeout: int) -> OddsApiHttpResponse:
    response = get_with_retries(url, params=params, timeout=timeout)
    response.raise_for_status()
    return OddsApiHttpResponse(
        payload=response.json(),
        status_code=response.status_code,
        url=response.url,
        quota={
            "x_requests_used": response.headers.get("x-requests-used", ""),
            "x_requests_remaining": response.headers.get("x-requests-remaining", ""),
            "x_requests_last": response.headers.get("x-requests-last", ""),
        },
    )


def _event_odds_params(params: dict[str, Any]) -> dict[str, Any]:
    if params.get("bookmakers"):
        params.pop("regions", None)
    else:
        params.pop("bookmakers", None)
    return params


def _strip_api_key(url: str) -> str:
    parts = urlsplit(url)
    safe_query = urlencode([(key, value) for key, value in parse_qsl(parts.query) if key.lower() != "apikey"])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, safe_query, parts.fragment))
