"""Baseball Reference MLB boxscore fetcher.

Baseball Reference boxscore pages expose a ``Starting Lineups`` table. The
table content is a pregame lineup artifact, but historical fetches are still
captured after the fact, so normalizers keep this source outside strict replay
inputs unless a run explicitly opts into reconstructed pregame context.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import requests

from mlb.contracts import RawSnapshot
from mlb.domain.teams import canonical_team_abbr
from mlb.fetchers.http import get_with_retries
from mlb.sources.snapshots import write_raw_snapshot


BREF_TEAM_CODES = {
    "ATL": "ATL",
    "ATH": "ATH",
    "AZ": "ARI",
    "BAL": "BAL",
    "BOS": "BOS",
    "CHC": "CHN",
    "CIN": "CIN",
    "CLE": "CLE",
    "COL": "COL",
    "CWS": "CHA",
    "DET": "DET",
    "HOU": "HOU",
    "KC": "KCA",
    "LAA": "ANA",
    "LAD": "LAN",
    "MIA": "MIA",
    "MIL": "MIL",
    "MIN": "MIN",
    "NYM": "NYN",
    "NYY": "NYA",
    "PHI": "PHI",
    "PIT": "PIT",
    "SD": "SDN",
    "SEA": "SEA",
    "SF": "SFN",
    "STL": "SLN",
    "TB": "TBA",
    "TEX": "TEX",
    "TOR": "TOR",
    "WSH": "WAS",
}


@dataclass(frozen=True)
class BaseballReferenceBoxscoreRequest:
    source: str
    url: str
    params: dict[str, Any]


def fetch_baseball_reference_boxscore(
    *,
    url: str,
    game_date: str | None = None,
    root: Path | None = None,
    timeout: int | None = None,
) -> RawSnapshot:
    """Fetch one Baseball Reference boxscore page and store the raw HTML body."""

    resolved_timeout = timeout or int(os.environ.get("BASEBALL_REFERENCE_TIMEOUT_S", "30"))
    request = BaseballReferenceBoxscoreRequest(
        source="baseball_reference_boxscore_context",
        url=url,
        params={},
    )
    session = requests.Session()
    session.headers.update(_headers())
    response = _get_boxscore_page(session, request.url, timeout=resolved_timeout)

    payload = {
        "source": "baseball_reference_boxscore_context",
        "sport": "MLB",
        "game_date": game_date or "",
        "data": [
            {
                "source": request.source,
                "page": "boxscore",
                "url": request.url,
                "resolved_url": response.url,
                "params": request.params,
                "status_code": response.status_code,
                "fetch_method": getattr(response, "fetch_method", "direct"),
                "origin_status_code": getattr(response, "origin_status_code", response.status_code),
                "content_type": response.headers.get("content-type", ""),
                "body": response.text,
            }
        ],
        "_atlas_fetch": {
            "source": "baseball_reference_boxscore_context",
            "game_date": game_date or "",
            "url": request.url,
            "status_code": response.status_code,
        },
    }
    return write_raw_snapshot(
        source="baseball_reference_boxscore_context",
        payload=payload,
        request={
            "url": request.url,
            "game_date": game_date or "",
            "status_code": response.status_code,
        },
        root=root,
    )


def fetch_baseball_reference_boxscores_bulk(
    *,
    games: list[dict[str, Any]],
    root: Path | None = None,
    timeout: int | None = None,
    delay_s: float | None = None,
    limit: int | None = None,
) -> RawSnapshot:
    """Fetch Baseball Reference boxscore pages for many scheduled games."""

    resolved_timeout = timeout or int(os.environ.get("BASEBALL_REFERENCE_TIMEOUT_S", "30"))
    resolved_delay = delay_s if delay_s is not None else float(os.environ.get("BASEBALL_REFERENCE_DELAY_S", "0.75"))
    selected_games = games[:limit] if limit else games
    session = requests.Session()
    session.headers.update(_headers())
    data: list[dict[str, Any]] = []
    status_codes: list[int] = []

    for index, game in enumerate(selected_games):
        url = baseball_reference_boxscore_url(
            game_date=str(game.get("official_date") or game.get("game_date") or ""),
            home_team=game.get("home_team_abbr") or game.get("home_team_name"),
            game_number=_int(game.get("game_number")) or 1,
        )
        if not url:
            data.append(
                {
                    "source": "baseball_reference_boxscore_context",
                    "page": "boxscore",
                    "url": "",
                    "resolved_url": "",
                    "params": {},
                    "status_code": 0,
                    "body": "",
                    "game_context": game,
                    "error": "unable_to_build_baseball_reference_url",
                }
            )
            continue
        try:
            response = _get_boxscore_page(session, url, timeout=resolved_timeout)
            status_codes.append(response.status_code)
            body = response.text if response.ok else ""
            error = "" if response.ok else f"http_status_{response.status_code}"
            resolved_url = response.url
        except requests.RequestException as exc:
            status_code = _response_status_code(exc)
            if status_code:
                status_codes.append(status_code)
            body = ""
            error = str(exc)
            resolved_url = url
            response = None

        data.append(
            {
                "source": "baseball_reference_boxscore_context",
                "page": "boxscore",
                "url": url,
                "resolved_url": resolved_url,
                "params": {},
                "status_code": getattr(response, "status_code", 0) if response is not None else 0,
                "fetch_method": getattr(response, "fetch_method", "direct") if response is not None else "",
                "origin_status_code": (
                    getattr(response, "origin_status_code", getattr(response, "status_code", 0))
                    if response is not None
                    else 0
                ),
                "content_type": getattr(response, "headers", {}).get("content-type", "") if response is not None else "",
                "body": body,
                "game_context": game,
                "error": error,
            }
        )
        if resolved_delay > 0 and index < len(selected_games) - 1:
            time.sleep(resolved_delay)

    dates = sorted({_date_key(game.get("official_date") or game.get("game_date")) for game in selected_games if _date_key(game.get("official_date") or game.get("game_date"))})
    payload = {
        "source": "baseball_reference_boxscore_context",
        "sport": "MLB",
        "game_date": dates[0] if len(dates) == 1 else "",
        "game_dates": dates,
        "data": data,
        "_atlas_fetch": {
            "source": "baseball_reference_boxscore_context",
            "mode": "bulk",
            "requested_game_count": len(games),
            "fetched_game_count": len([item for item in data if item.get("body")]),
            "game_dates": dates,
            "status_codes": status_codes,
        },
    }
    return write_raw_snapshot(
        source="baseball_reference_boxscore_context",
        payload=payload,
        request={
            "mode": "bulk",
            "requested_game_count": len(games),
            "selected_game_count": len(selected_games),
            "fetched_game_count": payload["_atlas_fetch"]["fetched_game_count"],
            "game_dates": dates,
            "status_codes": status_codes,
            "delay_s": resolved_delay,
        },
        root=root,
    )


def baseball_reference_boxscore_url(*, game_date: str, home_team: Any, game_number: int = 1) -> str:
    """Return the Baseball Reference boxscore URL for a scheduled game."""

    parsed_date = _parse_date(game_date)
    if parsed_date is None:
        return ""
    team = BREF_TEAM_CODES.get(canonical_team_abbr(home_team), "")
    if not team:
        return ""
    suffix = max(0, int(game_number or 1) - 1)
    return f"https://www.baseball-reference.com/boxes/{team}/{team}{parsed_date:%Y%m%d}{suffix}.shtml"


def _get_boxscore_page(session: requests.Session, url: str, *, timeout: int) -> requests.Response:
    response = get_with_retries(url, session=session, timeout=timeout)
    if response.ok:
        response.fetch_method = "direct"  # type: ignore[attr-defined]
        response.origin_status_code = response.status_code  # type: ignore[attr-defined]
        return response

    if _jina_fallback_enabled() and response.status_code in {403, 429, 500, 502, 503, 504}:
        fallback = get_with_retries(_jina_reader_url(url), session=session, timeout=timeout)
        fallback.fetch_method = "jina_reader_fallback"  # type: ignore[attr-defined]
        fallback.origin_status_code = response.status_code  # type: ignore[attr-defined]
        if fallback.ok:
            return fallback
        fallback.raise_for_status()

    response.raise_for_status()
    return response


def _jina_reader_url(url: str) -> str:
    return f"https://r.jina.ai/http://{url}"


def _jina_fallback_enabled() -> bool:
    return os.environ.get("BASEBALL_REFERENCE_JINA_FALLBACK", "1").strip().lower() not in {"0", "false", "no"}


def _headers() -> dict[str, str]:
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
    }


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _date_key(value: Any) -> str:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else ""


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _response_status_code(exc: requests.RequestException) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return _int(status)
