"""ESPN MLB player game-log fetchers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from mlb.contracts import RawSnapshot
from mlb.fetchers.http import get_with_retries
from mlb.sources.snapshots import write_raw_snapshot

ESPN_MLB_ATHLETE_GAMELOG_URL = (
    "https://site.web.api.espn.com/apis/common/v3/sports/baseball/mlb/athletes/{athlete_id}/gamelog"
)


@dataclass(frozen=True)
class EspnMlbGameLogRequest:
    season: int
    athlete_id: str
    team_id: str | None = None
    source: str = "espn_gamelogs"

    @property
    def url(self) -> str:
        return ESPN_MLB_ATHLETE_GAMELOG_URL.format(athlete_id=self.athlete_id)

    @property
    def params(self) -> dict[str, Any]:
        return {"season": self.season}


def fetch_espn_player_gamelog(
    *,
    athlete_id: str,
    season: int,
    player_context: dict[str, Any] | None = None,
    root: Path | None = None,
    timeout: int | None = None,
) -> RawSnapshot:
    """Fetch one ESPN MLB athlete game-log page payload."""

    request = EspnMlbGameLogRequest(season=season, athlete_id=str(athlete_id).strip())
    resolved_timeout = timeout or int(os.environ.get("ESPN_MLB_TIMEOUT_S", "30"))
    session = requests.Session()
    session.headers.update(_headers())
    response = get_with_retries(request.url, session=session, params=request.params, timeout=resolved_timeout)
    response.raise_for_status()
    payload = response.json()
    payload["_atlas_fetch"] = {
        "source": "espn_player_gamelog",
        "athlete_id": request.athlete_id,
        "season": season,
        "player_context": player_context or {},
        "status_code": response.status_code,
    }
    return write_raw_snapshot(
        source="espn_player_gamelog",
        payload=payload,
        request={
            "athlete_id": request.athlete_id,
            "season": season,
            "status_code": response.status_code,
        },
        root=root,
    )


def fetch_espn_player_gamelogs_bulk(
    *,
    players: list[dict[str, Any]],
    season: int,
    root: Path | None = None,
    timeout: int | None = None,
) -> RawSnapshot:
    """Fetch ESPN game logs for a set of athlete IDs as one raw snapshot."""

    resolved_timeout = timeout or int(os.environ.get("ESPN_MLB_TIMEOUT_S", "30"))
    session = requests.Session()
    session.headers.update(_headers())
    payloads: list[dict[str, Any]] = []
    status_codes: list[int] = []
    seen: set[str] = set()

    for player in players:
        athlete_id = str(player.get("espn_player_id") or player.get("athlete_id") or "").strip()
        if not athlete_id or athlete_id in seen:
            continue
        seen.add(athlete_id)
        request = EspnMlbGameLogRequest(season=season, athlete_id=athlete_id)
        try:
            response = get_with_retries(request.url, session=session, params=request.params, timeout=resolved_timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            payloads.append(
                {
                    "athlete_id": athlete_id,
                    "player_context": _player_context(player),
                    "payload": {},
                    "status_code": _response_status_code(exc),
                    "error": str(exc),
                }
            )
            continue
        status_codes.append(response.status_code)
        gamelog_payload = response.json()
        gamelog_payload["_atlas_fetch"] = {
            "source": "espn_player_gamelog",
            "athlete_id": athlete_id,
            "season": season,
            "player_context": _player_context(player),
            "status_code": response.status_code,
        }
        payloads.append(
            {
                "athlete_id": athlete_id,
                "player_context": _player_context(player),
                "payload": gamelog_payload,
                "status_code": response.status_code,
            }
        )

    combined_payload = {
        "source": "espn_player_gamelogs_bulk",
        "season": season,
        "player_count": len(payloads),
        "payloads": payloads,
        "_atlas_fetch": {
            "source": "espn_player_gamelogs_bulk",
            "season": season,
            "requested_player_count": len(players),
            "fetched_player_count": len([item for item in payloads if not item.get("error")]),
            "status_codes": status_codes,
        },
    }
    return write_raw_snapshot(
        source="espn_player_gamelogs_bulk",
        payload=combined_payload,
        request={
            "season": season,
            "requested_player_count": len(players),
            "fetched_player_count": combined_payload["_atlas_fetch"]["fetched_player_count"],
            "status_codes": status_codes,
        },
        root=root,
    )


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
    }


def _player_context(player: dict[str, Any]) -> dict[str, Any]:
    return {
        "espn_player_id": str(player.get("espn_player_id") or player.get("athlete_id") or "").strip(),
        "player_name": str(player.get("player_name") or "").strip(),
        "team_abbreviation": str(player.get("team_abbreviation") or player.get("team_abbr") or "").strip(),
        "position": str(player.get("position") or "").strip(),
    }


def _response_status_code(exc: requests.RequestException) -> int | None:
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
