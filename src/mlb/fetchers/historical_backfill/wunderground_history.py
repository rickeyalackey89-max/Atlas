"""Weather Underground historical weather fetcher for MLB replay context."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlparse

import requests

from mlb.contracts import RawSnapshot
from mlb.domain.teams import canonical_team_abbr
from mlb.fetchers.http import get_with_retries
from mlb.sources.snapshots import write_raw_snapshot

SOURCE = "wunderground_history_weather"
API_URL = "https://api.weather.com/v1/location/{location}/observations/historical.json"
DEFAULT_KEY_PAGE_URL = "https://www.wunderground.com/history/daily/us/mo/st.-louis/KCPS/date/2026-4-17"


@dataclass(frozen=True)
class WundergroundStation:
    station_id: str
    country: str = "US"

    @property
    def location_id(self) -> str:
        return f"{self.station_id}:9:{self.country}"


WUNDERGROUND_STATIONS_BY_TEAM = {
    "ATL": WundergroundStation("KATL"),
    "ATH": WundergroundStation("KSAC"),
    "AZ": WundergroundStation("KPHX"),
    "BAL": WundergroundStation("KBWI"),
    "BOS": WundergroundStation("KBOS"),
    "CHC": WundergroundStation("KMDW"),
    "CIN": WundergroundStation("KLUK"),
    "CLE": WundergroundStation("KBKL"),
    "COL": WundergroundStation("KBJC"),
    "CWS": WundergroundStation("KMDW"),
    "DET": WundergroundStation("KDET"),
    "HOU": WundergroundStation("KHOU"),
    "KC": WundergroundStation("KMKC"),
    "LAA": WundergroundStation("KSNA"),
    "LAD": WundergroundStation("KCQT"),
    "MIA": WundergroundStation("KMIA"),
    "MIL": WundergroundStation("KMKE"),
    "MIN": WundergroundStation("KMSP"),
    "NYM": WundergroundStation("KLGA"),
    "NYY": WundergroundStation("KLGA"),
    "PHI": WundergroundStation("KPHL"),
    "PIT": WundergroundStation("KAGC"),
    "SD": WundergroundStation("KSAN"),
    "SEA": WundergroundStation("KBFI"),
    "SF": WundergroundStation("KSFO"),
    "STL": WundergroundStation("KCPS"),
    "TB": WundergroundStation("KPIE"),
    "TEX": WundergroundStation("KGKY"),
    "TOR": WundergroundStation("CYTZ", country="CA"),
    "WSH": WundergroundStation("KDCA"),
}


def fetch_wunderground_history_weather(
    *,
    games: list[dict[str, Any]],
    api_key: str | None = None,
    weather_url_source: Path | None = None,
    root: Path | None = None,
    timeout: int = 30,
    delay_s: float | None = None,
    limit: int | None = None,
) -> RawSnapshot:
    """Fetch historical observed weather for scheduled MLB games."""

    selected_games = games[:limit] if limit else games
    key = api_key or discover_wunderground_api_key(weather_url_source=weather_url_source, timeout=timeout)
    if not key:
        raise ValueError("Unable to discover Weather.com API key from env, URL capture, or Wunderground page")

    resolved_delay = delay_s if delay_s is not None else float(os.environ.get("WUNDERGROUND_DELAY_S", "0.25"))
    session = requests.Session()
    session.headers.update(_headers())
    cache: dict[tuple[str, str], dict[str, Any]] = {}
    data: list[dict[str, Any]] = []
    status_codes: list[int] = []

    for index, game in enumerate(selected_games):
        home = canonical_team_abbr(game.get("home_team_abbr") or game.get("home_team_name"))
        station = WUNDERGROUND_STATIONS_BY_TEAM.get(home)
        game_date = _date_key(game.get("official_date") or game.get("game_date"))
        if not (station and game_date):
            data.append(
                {
                    "source": SOURCE,
                    "game_context": game,
                    "station": None,
                    "status_code": 0,
                    "payload": {},
                    "error": "missing_wunderground_station_or_game_date",
                }
            )
            continue

        cache_key = (station.location_id, game_date)
        if cache_key not in cache:
            response_payload: dict[str, Any]
            status_code = 0
            error = ""
            try:
                response = get_with_retries(
                    API_URL.format(location=station.location_id),
                    session=session,
                    params={
                        "apiKey": key,
                        "units": "e",
                        "startDate": game_date.replace("-", ""),
                        "endDate": game_date.replace("-", ""),
                    },
                    timeout=timeout,
                )
                status_code = response.status_code
                status_codes.append(status_code)
                response.raise_for_status()
                response_payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                error = str(exc)
                response_payload = {}
            cache[cache_key] = {
                "station_id": station.station_id,
                "country": station.country,
                "location_id": station.location_id,
                "game_date": game_date,
                "status_code": status_code,
                "payload": response_payload,
                "error": error,
            }
            if resolved_delay > 0 and index < len(selected_games) - 1:
                time.sleep(resolved_delay)

        cached = cache[cache_key]
        data.append(
            {
                "source": SOURCE,
                "game_context": game,
                "station": {
                    "station_id": cached["station_id"],
                    "country": cached["country"],
                    "location_id": cached["location_id"],
                },
                "status_code": cached["status_code"],
                "payload": cached["payload"],
                "error": cached["error"],
            }
        )

    dates = sorted({_date_key(game.get("official_date") or game.get("game_date")) for game in selected_games if _date_key(game.get("official_date") or game.get("game_date"))})
    payload = {
        "source": SOURCE,
        "sport": "MLB",
        "game_date": dates[0] if len(dates) == 1 else "",
        "game_dates": dates,
        "data": data,
        "_atlas_fetch": {
            "source": SOURCE,
            "mode": "bulk",
            "requested_game_count": len(games),
            "selected_game_count": len(selected_games),
            "fetched_game_count": len([item for item in data if item.get("payload")]),
            "api_request_count": len(cache),
            "game_dates": dates,
            "status_codes": status_codes,
        },
    }
    return write_raw_snapshot(
        source=SOURCE,
        payload=payload,
        request={
            "mode": "bulk",
            "requested_game_count": len(games),
            "selected_game_count": len(selected_games),
            "fetched_game_count": payload["_atlas_fetch"]["fetched_game_count"],
            "api_request_count": len(cache),
            "game_dates": dates,
            "status_codes": status_codes,
            "weather_url_source": str(weather_url_source) if weather_url_source else "",
            "api_key_present": bool(key),
        },
        root=root,
    )


def discover_wunderground_api_key(*, weather_url_source: Path | None = None, timeout: int = 30) -> str:
    """Find the public Weather.com key used by Wunderground history pages."""

    for env_name in ("WEATHER_COM_API_KEY", "WUNDERGROUND_API_KEY"):
        value = os.environ.get(env_name, "").strip()
        if value:
            return value

    if weather_url_source and weather_url_source.exists():
        text = weather_url_source.read_text(encoding="utf-8", errors="ignore")
        key = _api_key_from_text(text)
        if key:
            return key
        for url in extract_wunderground_history_urls(text):
            key = _api_key_from_page(url["url"], timeout=timeout)
            if key:
                return key

    return _api_key_from_page(DEFAULT_KEY_PAGE_URL, timeout=timeout)


def extract_wunderground_history_urls(text: str) -> list[dict[str, str]]:
    """Extract Wunderground history page URLs from a network URL capture."""

    urls: list[str] = []
    for line in text.splitlines():
        for candidate in _decoded_url_candidates(line):
            if "wunderground.com/history/daily/" in candidate:
                urls.append(candidate)

    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for url in urls:
        parsed = _parse_history_url(url)
        if not parsed:
            continue
        key = (parsed["station_id"], parsed["game_date"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(parsed)
    return rows


def _api_key_from_page(url: str, *, timeout: int) -> str:
    try:
        response = get_with_retries(url, headers=_headers(), timeout=timeout)
        response.raise_for_status()
    except requests.RequestException:
        return ""
    return _api_key_from_text(response.text)


def _api_key_from_text(text: str) -> str:
    match = re.search(r"apiKey=([A-Za-z0-9]{16,64})", text)
    return match.group(1) if match else ""


def _decoded_url_candidates(line: str) -> list[str]:
    values = [line.strip()]
    parsed = urlparse(line.strip())
    values.extend(value for _, value in parse_qsl(parsed.query, keep_blank_values=True) if value)
    decoded: list[str] = []
    for value in values:
        current = value
        for _ in range(3):
            current = unquote(current)
        decoded.append(current)
    return decoded


def _parse_history_url(url: str) -> dict[str, str] | None:
    match = re.search(
        r"https?://(?:www\.)?wunderground\.com/history/daily/(?P<path>.*?)/(?P<station>[A-Z0-9]+)/date/"
        r"(?P<year>20\d{2})-(?P<month>\d{1,2})-(?P<day>\d{1,2})",
        url,
        flags=re.I,
    )
    if not match:
        return None
    try:
        game_date = date(int(match.group("year")), int(match.group("month")), int(match.group("day"))).isoformat()
    except ValueError:
        return None
    return {
        "url": match.group(0),
        "path": match.group("path"),
        "station_id": match.group("station").upper(),
        "game_date": game_date,
    }


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
    }


def _date_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return ""
