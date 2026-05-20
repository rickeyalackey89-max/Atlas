"""ESPN MLB injury fetcher."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from mlb.contracts import InjuryStatus, RawSnapshot
from mlb.fetchers.http import get_with_retries
from mlb.sources.catalog import ESPN_MLB_INJURIES_PAGE_URL, ESPN_MLB_INJURIES_URL
from mlb.sources.snapshots import write_raw_snapshot


@dataclass(frozen=True)
class EspnMlbInjuryRequest:
    url: str = ESPN_MLB_INJURIES_URL
    page_url: str = ESPN_MLB_INJURIES_PAGE_URL
    source: str = "espn_injuries"


def build_espn_mlb_injury_request() -> EspnMlbInjuryRequest:
    return EspnMlbInjuryRequest()


def fetch_espn_mlb_injuries(
    *,
    root: Path | None = None,
    timeout: int = 30,
) -> RawSnapshot:
    """Fetch and persist the ESPN MLB injuries raw snapshot."""

    request = build_espn_mlb_injury_request()
    response = get_with_retries(
        request.url,
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    payload["_atlas_fetch"] = {
        "source": request.source,
        "page_url": request.page_url,
        "status_code": response.status_code,
    }
    return write_raw_snapshot(
        source=request.source,
        payload=payload,
        request={
            "url": request.url,
            "page_url": request.page_url,
            "status_code": response.status_code,
        },
        root=root,
    )


def normalize_espn_injury_payload(payload: dict[str, Any]) -> list[InjuryStatus]:
    """Convert ESPN's team-grouped injury payload into row contracts."""

    pulled_at = str(payload.get("timestamp") or "")
    rows: list[InjuryStatus] = []
    for team_block in payload.get("injuries", []) or []:
        team_name = str(team_block.get("displayName") or "")
        for injury in team_block.get("injuries", []) or []:
            athlete = injury.get("athlete") or {}
            team = athlete.get("team") or {}
            position = athlete.get("position") or {}
            rows.append(
                InjuryStatus(
                    source="espn_injuries",
                    pulled_at_utc=pulled_at,
                    player_name=str(athlete.get("displayName") or ""),
                    team=str(team.get("abbreviation") or team_name),
                    status=str(injury.get("status") or ""),
                    estimated_return=None,
                    comment=str(injury.get("shortComment") or injury.get("longComment") or ""),
                    player_id=str(athlete.get("id") or injury.get("id") or ""),
                    position=str(position.get("abbreviation") or position.get("displayName") or ""),
                    report_date=str(injury.get("date") or ""),
                )
            )
    return rows
