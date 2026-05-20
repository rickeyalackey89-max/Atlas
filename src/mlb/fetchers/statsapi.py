"""MLB StatsAPI fetchers for MLB and MiLB source snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from mlb.contracts import RawSnapshot
from mlb.fetchers.http import get_with_retries
from mlb.sources.catalog import MLB_STATSAPI_BASE_URL, MLB_STATSAPI_DEFAULT_SPORT_IDS
from mlb.sources.snapshots import write_raw_snapshot


@dataclass(frozen=True)
class StatsApiRequest:
    source: str
    url: str
    params: dict[str, Any]


def fetch_statsapi_teams(
    *,
    season: int,
    sport_ids: tuple[int, ...] = MLB_STATSAPI_DEFAULT_SPORT_IDS,
    root: Path | None = None,
    timeout: int = 30,
) -> RawSnapshot:
    payloads: list[dict[str, Any]] = []
    status_codes: list[int] = []
    for sport_id in sport_ids:
        request = build_teams_request(sport_id=sport_id, season=season)
        response = _get_json(request, timeout=timeout)
        status_codes.append(response["status_code"])
        payloads.append(response["payload"])

    combined_payload = {
        "source": "statsapi_teams",
        "season": season,
        "sport_ids": list(sport_ids),
        "payloads": payloads,
        "_atlas_fetch": {
            "source": "statsapi_teams",
            "status_codes": status_codes,
        },
    }
    return write_raw_snapshot(
        source="statsapi_teams",
        payload=combined_payload,
        request={"season": season, "sport_ids": list(sport_ids), "status_codes": status_codes},
        root=root,
    )


def fetch_statsapi_roster(
    *,
    team_id: int,
    season: int,
    root: Path | None = None,
    timeout: int = 30,
) -> RawSnapshot:
    request = build_roster_request(team_id=team_id, season=season)
    response = _get_json(request, timeout=timeout)
    payload = response["payload"]
    payload["_atlas_fetch"] = {"source": "statsapi_rosters", "team_id": team_id, "season": season}
    return write_raw_snapshot(
        source="statsapi_rosters",
        payload=payload,
        request={**request.params, "url": request.url, "status_code": response["status_code"]},
        root=root,
    )


def fetch_statsapi_rosters_bulk(
    *,
    teams: list[dict[str, Any]],
    season: int,
    root: Path | None = None,
    timeout: int = 30,
) -> RawSnapshot:
    """Fetch one combined roster snapshot for a team list.

    The single-team fetcher remains useful for targeted debugging. This bulk
    snapshot is the runtime-friendly form because it preserves one atomic roster
    view for the board date and keeps team context next to each roster payload.
    """

    payloads: list[dict[str, Any]] = []
    status_codes: list[int] = []
    for team in teams:
        team_id = _to_int(team.get("team_id"))
        if team_id is None:
            continue
        request = build_roster_request(team_id=team_id, season=season)
        response = _get_json(request, timeout=timeout)
        status_codes.append(response["status_code"])
        roster_payload = response["payload"]
        roster_payload["_atlas_fetch"] = {
            "source": "statsapi_rosters",
            "team_id": team_id,
            "season": season,
        }
        payloads.append(
            {
                "team_context": {
                    "season": season,
                    "sport_id": _to_int(team.get("sport_id")),
                    "level": str(team.get("level") or ""),
                    "team_id": team_id,
                    "team_name": str(team.get("team_name") or ""),
                    "team_abbreviation": str(team.get("team_abbreviation") or ""),
                    "team_short_name": str(team.get("team_short_name") or ""),
                    "club_name": str(team.get("club_name") or ""),
                    "parent_org_id": _to_int(team.get("parent_org_id")),
                    "parent_org_name": str(team.get("parent_org_name") or ""),
                },
                "payload": roster_payload,
                "status_code": response["status_code"],
            }
        )

    combined_payload = {
        "source": "statsapi_rosters_bulk",
        "season": season,
        "team_count": len(payloads),
        "payloads": payloads,
        "_atlas_fetch": {
            "source": "statsapi_rosters_bulk",
            "season": season,
            "requested_team_count": len(teams),
            "fetched_team_count": len(payloads),
            "status_codes": status_codes,
        },
    }
    return write_raw_snapshot(
        source="statsapi_rosters_bulk",
        payload=combined_payload,
        request={
            "season": season,
            "requested_team_count": len(teams),
            "fetched_team_count": len(payloads),
            "status_codes": status_codes,
        },
        root=root,
    )


def fetch_statsapi_schedule(
    *,
    sport_id: int,
    start_date: str,
    end_date: str,
    root: Path | None = None,
    timeout: int = 30,
) -> RawSnapshot:
    request = build_schedule_request(sport_id=sport_id, start_date=start_date, end_date=end_date)
    response = _get_json(request, timeout=timeout)
    payload = response["payload"]
    payload["_atlas_fetch"] = {"source": "statsapi_schedule", **request.params}
    return write_raw_snapshot(
        source="statsapi_schedule",
        payload=payload,
        request={**request.params, "url": request.url, "status_code": response["status_code"]},
        root=root,
    )


def fetch_statsapi_boxscore(
    *,
    game_pk: int,
    root: Path | None = None,
    timeout: int = 30,
) -> RawSnapshot:
    request = build_boxscore_request(game_pk=game_pk)
    response = _get_json(request, timeout=timeout)
    payload = response["payload"]
    payload["_atlas_fetch"] = {"source": "statsapi_boxscore", "game_pk": game_pk}
    return write_raw_snapshot(
        source="statsapi_boxscore",
        payload=payload,
        request={**request.params, "url": request.url, "status_code": response["status_code"]},
        root=root,
    )


def fetch_statsapi_boxscores_bulk(
    *,
    game_pks: list[int],
    game_contexts: dict[int, dict[str, Any]] | None = None,
    root: Path | None = None,
    timeout: int = 30,
) -> RawSnapshot:
    """Fetch one combined StatsAPI boxscore snapshot for a game list."""

    payloads: list[dict[str, Any]] = []
    status_codes: list[int] = []
    for game_pk in _unique_ints(game_pks):
        game_context = _game_context((game_contexts or {}).get(game_pk, {}))
        request = build_boxscore_request(game_pk=game_pk)
        try:
            response = _get_json(request, timeout=timeout)
        except requests.RequestException as exc:
            status_code = _response_status_code(exc)
            if status_code:
                status_codes.append(status_code)
            payloads.append(
                {
                    "game_pk": game_pk,
                    "game_context": game_context,
                    "payload": {},
                    "status_code": status_code,
                    "error": str(exc),
                }
            )
            continue
        status_codes.append(response["status_code"])
        boxscore_payload = response["payload"]
        boxscore_payload["_atlas_fetch"] = {"source": "statsapi_boxscore", "game_pk": game_pk}
        payloads.append(
            {
                "game_pk": game_pk,
                "game_context": game_context,
                "payload": boxscore_payload,
                "status_code": response["status_code"],
            }
        )

    combined_payload = {
        "source": "statsapi_boxscores_bulk",
        "game_count": len(payloads),
        "payloads": payloads,
        "_atlas_fetch": {
            "source": "statsapi_boxscores_bulk",
            "requested_game_count": len(game_pks),
            "fetched_game_count": len([item for item in payloads if not item.get("error")]),
            "status_codes": status_codes,
        },
    }
    return write_raw_snapshot(
        source="statsapi_boxscores_bulk",
        payload=combined_payload,
        request={
            "requested_game_count": len(game_pks),
            "fetched_game_count": combined_payload["_atlas_fetch"]["fetched_game_count"],
            "game_pks": _unique_ints(game_pks),
            "status_codes": status_codes,
        },
        root=root,
    )


def fetch_statsapi_player_gamelog(
    *,
    person_id: int,
    group: str,
    season: int,
    root: Path | None = None,
    timeout: int = 30,
) -> RawSnapshot:
    request = build_player_gamelog_request(person_id=person_id, group=group, season=season)
    response = _get_json(request, timeout=timeout)
    payload = response["payload"]
    payload["_atlas_fetch"] = {"source": "statsapi_player_gamelog", "person_id": person_id, **request.params}
    return write_raw_snapshot(
        source="statsapi_player_gamelog",
        payload=payload,
        request={**request.params, "person_id": person_id, "url": request.url, "status_code": response["status_code"]},
        root=root,
    )


def fetch_statsapi_player_gamelogs_bulk(
    *,
    players: list[dict[str, Any]],
    group: str,
    season: int,
    root: Path | None = None,
    timeout: int = 30,
) -> RawSnapshot:
    """Fetch one combined StatsAPI player game-log snapshot for a player list."""

    payloads: list[dict[str, Any]] = []
    status_codes: list[int] = []
    seen: set[int] = set()
    for player in players:
        person_id = _to_int(player.get("person_id") or player.get("statsapi_person_id"))
        if person_id is None or person_id in seen:
            continue
        seen.add(person_id)
        request = build_player_gamelog_request(person_id=person_id, group=group, season=season)
        try:
            response = _get_json(request, timeout=timeout)
        except requests.RequestException as exc:
            status_code = _response_status_code(exc)
            if status_code:
                status_codes.append(status_code)
            payloads.append(
                {
                    "person_id": person_id,
                    "player_context": _player_context(player),
                    "payload": {},
                    "status_code": status_code,
                    "error": str(exc),
                }
            )
            continue
        status_codes.append(response["status_code"])
        gamelog_payload = response["payload"]
        gamelog_payload["_atlas_fetch"] = {
            "source": "statsapi_player_gamelog",
            "person_id": person_id,
            **request.params,
        }
        payloads.append(
            {
                "person_id": person_id,
                "player_context": _player_context(player),
                "payload": gamelog_payload,
                "status_code": response["status_code"],
            }
        )

    combined_payload = {
        "source": "statsapi_player_gamelogs_bulk",
        "season": season,
        "group": group,
        "player_count": len(payloads),
        "payloads": payloads,
        "_atlas_fetch": {
            "source": "statsapi_player_gamelogs_bulk",
            "season": season,
            "group": group,
            "requested_player_count": len(players),
            "fetched_player_count": len([item for item in payloads if not item.get("error")]),
            "status_codes": status_codes,
        },
    }
    return write_raw_snapshot(
        source="statsapi_player_gamelogs_bulk",
        payload=combined_payload,
        request={
            "season": season,
            "group": group,
            "requested_player_count": len(players),
            "fetched_player_count": combined_payload["_atlas_fetch"]["fetched_player_count"],
            "status_codes": status_codes,
        },
        root=root,
    )


def fetch_statsapi_transactions(
    *,
    sport_id: int,
    start_date: str,
    end_date: str,
    root: Path | None = None,
    timeout: int = 30,
) -> RawSnapshot:
    request = build_transactions_request(sport_id=sport_id, start_date=start_date, end_date=end_date)
    response = _get_json(request, timeout=timeout)
    payload = response["payload"]
    payload["_atlas_fetch"] = {"source": "statsapi_transactions", **request.params}
    return write_raw_snapshot(
        source="statsapi_transactions",
        payload=payload,
        request={**request.params, "url": request.url, "status_code": response["status_code"]},
        root=root,
    )


def build_teams_request(*, sport_id: int, season: int) -> StatsApiRequest:
    return StatsApiRequest(
        source="statsapi_teams",
        url=f"{MLB_STATSAPI_BASE_URL}/teams",
        params={"sportId": sport_id, "season": season},
    )


def build_roster_request(*, team_id: int, season: int) -> StatsApiRequest:
    return StatsApiRequest(
        source="statsapi_rosters",
        url=f"{MLB_STATSAPI_BASE_URL}/teams/{team_id}/roster",
        params={"season": season, "hydrate": "person"},
    )


def build_schedule_request(*, sport_id: int, start_date: str, end_date: str) -> StatsApiRequest:
    return StatsApiRequest(
        source="statsapi_schedule",
        url=f"{MLB_STATSAPI_BASE_URL}/schedule",
        params={"sportId": sport_id, "startDate": start_date, "endDate": end_date},
    )


def build_boxscore_request(*, game_pk: int) -> StatsApiRequest:
    return StatsApiRequest(
        source="statsapi_boxscore",
        url=f"{MLB_STATSAPI_BASE_URL}/game/{game_pk}/boxscore",
        params={"gamePk": game_pk},
    )


def build_player_gamelog_request(*, person_id: int, group: str, season: int) -> StatsApiRequest:
    return StatsApiRequest(
        source="statsapi_player_gamelog",
        url=f"{MLB_STATSAPI_BASE_URL}/people/{person_id}/stats",
        params={"stats": "gameLog", "group": group, "season": season},
    )


def build_transactions_request(*, sport_id: int, start_date: str, end_date: str) -> StatsApiRequest:
    return StatsApiRequest(
        source="statsapi_transactions",
        url=f"{MLB_STATSAPI_BASE_URL}/transactions",
        params={"sportId": sport_id, "startDate": start_date, "endDate": end_date},
    )


def _get_json(request: StatsApiRequest, *, timeout: int) -> dict[str, Any]:
    response = get_with_retries(
        request.url,
        params=request.params,
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        timeout=timeout,
    )
    response.raise_for_status()
    return {"payload": response.json(), "status_code": response.status_code}


def _unique_ints(values: list[int]) -> list[int]:
    resolved: list[int] = []
    seen: set[int] = set()
    for value in values:
        parsed = _to_int(value)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        resolved.append(parsed)
    return resolved


def _player_context(player: dict[str, Any]) -> dict[str, Any]:
    return {
        "person_id": _to_int(player.get("person_id") or player.get("statsapi_person_id")),
        "player_name": str(player.get("player_name") or "").strip(),
        "team_id": _to_int(player.get("team_id") or player.get("statsapi_roster_team_id")),
        "team_abbreviation": str(
            player.get("team_abbreviation")
            or player.get("statsapi_roster_team_abbreviation")
            or player.get("player_team")
            or ""
        ).strip(),
        "position": str(player.get("primary_position") or player.get("statsapi_player_position") or "").strip(),
    }


def _game_context(game: dict[str, Any]) -> dict[str, Any]:
    return {
        "game_pk": _to_int(game.get("game_pk") or game.get("gamePk")),
        "official_date": str(game.get("official_date") or game.get("officialDate") or "").strip(),
        "game_date": str(game.get("game_date") or game.get("gameDate") or "").strip(),
        "away_team_id": _to_int(game.get("away_team_id")),
        "away_team_name": str(game.get("away_team_name") or "").strip(),
        "home_team_id": _to_int(game.get("home_team_id")),
        "home_team_name": str(game.get("home_team_name") or "").strip(),
    }


def _response_status_code(exc: requests.RequestException) -> int | None:
    response = getattr(exc, "response", None)
    return _to_int(getattr(response, "status_code", None))


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
