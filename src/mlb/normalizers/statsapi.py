"""Normalization for MLB StatsAPI major/minor source payloads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mlb.runtime.paths import ensure_mlb_dirs
from mlb.sources.catalog import MLB_STATSAPI_SPORT_LABELS
from mlb.sources.snapshots import load_snapshot_manifest, load_snapshot_payload


def normalize_statsapi_teams(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize MLB StatsAPI teams payloads across MLB and MiLB sport IDs."""

    rows: list[dict[str, Any]] = []
    payloads = payload.get("payloads") if isinstance(payload.get("payloads"), list) else [payload]
    for source_payload in payloads:
        default_season = payload.get("season") or source_payload.get("season")
        for team in source_payload.get("teams", []) or []:
            sport_id = _nested_int(team, "sport", "id") or _to_int(team.get("sportId"))
            parent_org_id = _nested_int(team, "parentOrg", "id") or _to_int(team.get("parentOrgId"))
            rows.append(
                {
                    "season": _to_int(default_season),
                    "sport_id": sport_id,
                    "level": MLB_STATSAPI_SPORT_LABELS.get(sport_id or -1, ""),
                    "team_id": _to_int(team.get("id")),
                    "team_name": _clean_str(team.get("name")),
                    "team_abbreviation": _clean_str(team.get("abbreviation")),
                    "team_short_name": _clean_str(team.get("shortName") or team.get("teamName")),
                    "club_name": _clean_str(team.get("clubName")),
                    "league_id": _nested_int(team, "league", "id"),
                    "league_name": _nested_str(team, "league", "name"),
                    "division_id": _nested_int(team, "division", "id"),
                    "division_name": _nested_str(team, "division", "name"),
                    "parent_org_id": parent_org_id,
                    "parent_org_name": _clean_str(team.get("parentOrgName")),
                    "venue_id": _nested_int(team, "venue", "id"),
                    "venue_name": _nested_str(team, "venue", "name"),
                    "active": bool(team.get("active", True)),
                }
            )
    return rows


def normalize_statsapi_roster(payload: dict[str, Any], *, team_context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Normalize one MLB StatsAPI team roster payload."""

    context = team_context or {}
    fetch = payload.get("_atlas_fetch") or {}
    team_id = _to_int(fetch.get("team_id") or context.get("team_id"))
    season = _to_int(fetch.get("season") or context.get("season"))
    target_date = _clean_str(fetch.get("target_date") or context.get("target_date"))
    rows: list[dict[str, Any]] = []
    for item in payload.get("roster", []) or []:
        person = item.get("person") or {}
        position = item.get("position") or person.get("primaryPosition") or {}
        rows.append(
            {
                "season": season,
                "target_date": target_date,
                "team_id": team_id,
                "team_name": _clean_str(context.get("team_name")),
                "team_abbreviation": _clean_str(context.get("team_abbreviation")),
                "team_short_name": _clean_str(context.get("team_short_name")),
                "club_name": _clean_str(context.get("club_name")),
                "sport_id": _to_int(context.get("sport_id")),
                "level": MLB_STATSAPI_SPORT_LABELS.get(_to_int(context.get("sport_id")) or -1, ""),
                "parent_org_id": _to_int(context.get("parent_org_id")),
                "parent_org_name": _clean_str(context.get("parent_org_name")),
                "person_id": _to_int(person.get("id")),
                "player_name": _clean_str(person.get("fullName")),
                "first_name": _clean_str(person.get("firstName")),
                "last_name": _clean_str(person.get("lastName")),
                "primary_position": _clean_str(position.get("abbreviation") or position.get("name")),
                "jersey_number": _clean_str(item.get("jerseyNumber")),
                "status": _nested_str(item, "status", "description"),
                "roster_type": _clean_str(item.get("rosterType")),
                "bats": _nested_str(person, "batSide", "code"),
                "throws": _nested_str(person, "pitchHand", "code"),
                "birth_date": _clean_str(person.get("birthDate")),
                "height": _clean_str(person.get("height")),
                "weight": _to_int(person.get("weight")),
            }
        )
    return rows


def normalize_statsapi_rosters_bulk(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize a combined StatsAPI roster snapshot into one player table."""

    rows: list[dict[str, Any]] = []
    for item in payload.get("payloads", []) or []:
        if not isinstance(item, dict):
            continue
        roster_payload = item.get("payload") or {}
        team_context = item.get("team_context") or {}
        if not isinstance(roster_payload, dict) or not isinstance(team_context, dict):
            continue
        rows.extend(normalize_statsapi_roster(roster_payload, team_context=team_context))
    return rows


def normalize_statsapi_schedule(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize schedule payload into one row per game."""

    fetch = payload.get("_atlas_fetch") or {}
    sport_id = _to_int(fetch.get("sportId") or fetch.get("sport_id"))
    rows: list[dict[str, Any]] = []
    for date_block in payload.get("dates", []) or []:
        for game in date_block.get("games", []) or []:
            teams = game.get("teams") or {}
            away = teams.get("away") or {}
            home = teams.get("home") or {}
            rows.append(
                {
                    "sport_id": sport_id,
                    "level": MLB_STATSAPI_SPORT_LABELS.get(sport_id or -1, ""),
                    "game_pk": _to_int(game.get("gamePk")),
                    "game_date": _clean_str(game.get("gameDate")),
                    "official_date": _clean_str(game.get("officialDate") or date_block.get("date")),
                    "status": _nested_str(game, "status", "detailedState") or _nested_str(game, "status", "abstractGameState"),
                    "away_team_id": _nested_int(away, "team", "id"),
                    "away_team_name": _nested_str(away, "team", "name"),
                    "home_team_id": _nested_int(home, "team", "id"),
                    "home_team_name": _nested_str(home, "team", "name"),
                    "venue_id": _nested_int(game, "venue", "id"),
                    "venue_name": _nested_str(game, "venue", "name"),
                    "double_header": _clean_str(game.get("doubleHeader")),
                    "game_number": _to_int(game.get("gameNumber")),
                    "series_description": _clean_str(game.get("seriesDescription")),
                }
            )
    return rows


def normalize_statsapi_boxscore(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize a game boxscore into one row per player/team side."""

    fetch = payload.get("_atlas_fetch") or {}
    game_pk = _to_int(fetch.get("game_pk") or fetch.get("gamePk"))
    rows: list[dict[str, Any]] = []
    for side in ("away", "home"):
        side_payload = ((payload.get("teams") or {}).get(side) or {})
        team = side_payload.get("team") or {}
        opponent = ((payload.get("teams") or {}).get("home" if side == "away" else "away") or {}).get("team") or {}
        batting_order = {str(person_id): index + 1 for index, person_id in enumerate(side_payload.get("battingOrder", []) or [])}
        pitcher_order = {
            str(person_id): index + 1 for index, person_id in enumerate(side_payload.get("pitchers", []) or [])
        }
        for player_key, player_payload in (side_payload.get("players") or {}).items():
            person = player_payload.get("person") or {}
            person_id = _to_int(person.get("id") or str(player_key).replace("ID", ""))
            position = player_payload.get("position") or {}
            stats = player_payload.get("stats") or {}
            rows.append(
                {
                    "game_pk": game_pk,
                    "team_side": side,
                    "team_id": _to_int(team.get("id")),
                    "team_name": _clean_str(team.get("name")),
                    "opponent_id": _to_int(opponent.get("id")),
                    "opponent_name": _clean_str(opponent.get("name")),
                    "person_id": person_id,
                    "player_name": _clean_str(person.get("fullName")),
                    "position": _clean_str(position.get("abbreviation") or position.get("name")),
                    "batting_order": batting_order.get(str(person_id)),
                    "is_starter": str(person_id) in batting_order,
                    "pitching_order": pitcher_order.get(str(person_id)),
                    "is_pitching_starter": pitcher_order.get(str(person_id)) == 1,
                    "batting_stats": stats.get("batting") or {},
                    "pitching_stats": stats.get("pitching") or {},
                    "fielding_stats": stats.get("fielding") or {},
                }
            )
    return rows


def normalize_statsapi_boxscores_bulk(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize a combined StatsAPI boxscore snapshot into player rows."""

    rows: list[dict[str, Any]] = []
    for item in payload.get("payloads", []) or []:
        if not isinstance(item, dict) or item.get("error"):
            continue
        boxscore_payload = item.get("payload") or {}
        if not isinstance(boxscore_payload, dict):
            continue
        if "_atlas_fetch" not in boxscore_payload:
            boxscore_payload["_atlas_fetch"] = {
                "source": "statsapi_boxscore",
                "game_pk": _to_int(item.get("game_pk")),
            }
        game_context = item.get("game_context") if isinstance(item.get("game_context"), dict) else {}
        for row in normalize_statsapi_boxscore(boxscore_payload):
            row["official_date"] = _clean_str(game_context.get("official_date"))
            row["game_date"] = _clean_str(game_context.get("game_date"))
            row["home_team_id"] = _to_int(game_context.get("home_team_id"))
            row["home_team_name"] = _clean_str(game_context.get("home_team_name"))
            row["away_team_id"] = _to_int(game_context.get("away_team_id"))
            row["away_team_name"] = _clean_str(game_context.get("away_team_name"))
            rows.append(row)
    return rows


def normalize_statsapi_player_gamelog(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize one person game-log payload into one row per split."""

    fetch = payload.get("_atlas_fetch") or {}
    person_id = _to_int(fetch.get("person_id") or fetch.get("personId"))
    group = _clean_str(fetch.get("group"))
    season = _to_int(fetch.get("season"))
    rows: list[dict[str, Any]] = []
    for stat_block in payload.get("stats", []) or []:
        block_group = _nested_str(stat_block, "group", "displayName") or group
        for split in stat_block.get("splits", []) or []:
            team = split.get("team") or {}
            opponent = split.get("opponent") or {}
            game = split.get("game") or {}
            rows.append(
                {
                    "season": season,
                    "person_id": person_id,
                    "player_name": _nested_str(split, "player", "fullName"),
                    "group": block_group.lower() if block_group else group,
                    "game_pk": _to_int(game.get("gamePk") or split.get("gamePk")),
                    "game_date": _clean_str(split.get("date")),
                    "team_id": _to_int(team.get("id")),
                    "team_name": _clean_str(team.get("name")),
                    "opponent_id": _to_int(opponent.get("id")),
                    "opponent_name": _clean_str(opponent.get("name")),
                    "is_home": bool(split.get("isHome")),
                    "stat": split.get("stat") or {},
                }
            )
    return rows


def normalize_statsapi_player_gamelogs_bulk(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize a combined StatsAPI player game-log snapshot into split rows."""

    rows: list[dict[str, Any]] = []
    for item in payload.get("payloads", []) or []:
        if not isinstance(item, dict) or item.get("error"):
            continue
        gamelog_payload = item.get("payload") or {}
        if not isinstance(gamelog_payload, dict):
            continue
        player_context = item.get("player_context") if isinstance(item.get("player_context"), dict) else {}
        if "_atlas_fetch" not in gamelog_payload:
            gamelog_payload["_atlas_fetch"] = {
                "source": "statsapi_player_gamelog",
                "person_id": _to_int(item.get("person_id") or player_context.get("person_id")),
                "group": payload.get("group"),
                "season": _to_int(payload.get("season")),
            }
        for row in normalize_statsapi_player_gamelog(gamelog_payload):
            if player_context:
                row["player_name"] = row.get("player_name") or _clean_str(player_context.get("player_name"))
                row["player_team"] = _clean_str(player_context.get("team_abbreviation"))
                row["player_position"] = _clean_str(player_context.get("position"))
            rows.append(row)
    return rows


def normalize_statsapi_transactions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize StatsAPI transaction payloads into player-movement rows."""

    fetch = payload.get("_atlas_fetch") or {}
    sport_id = _to_int(fetch.get("sportId") or fetch.get("sport_id"))
    rows: list[dict[str, Any]] = []
    for item in payload.get("transactions", []) or []:
        person = item.get("person") or {}
        from_team = item.get("fromTeam") or {}
        to_team = item.get("toTeam") or {}
        type_code = _clean_str(item.get("typeCode")).upper()
        type_desc = _clean_str(item.get("typeDesc"))
        description = _clean_str(item.get("description"))
        movement = _transaction_movement(type_code=type_code, type_desc=type_desc, description=description)
        rows.append(
            {
                "sport_id": sport_id,
                "level": MLB_STATSAPI_SPORT_LABELS.get(sport_id or -1, ""),
                "transaction_id": _to_int(item.get("id")),
                "person_id": _to_int(person.get("id")),
                "player_name": _clean_str(person.get("fullName")),
                "from_team_id": _to_int(from_team.get("id")),
                "from_team_name": _clean_str(from_team.get("name")),
                "to_team_id": _to_int(to_team.get("id")),
                "to_team_name": _clean_str(to_team.get("name")),
                "date": _clean_str(item.get("date")),
                "effective_date": _clean_str(item.get("effectiveDate")),
                "resolution_date": _clean_str(item.get("resolutionDate")),
                "type_code": type_code,
                "type_desc": type_desc,
                "description": description,
                "movement_direction": movement,
                "is_callup": movement == "to_mlb",
                "is_optioned": type_code == "OPT" or "optioned" in description.lower(),
                "is_minor_league_assignment": movement == "to_minors",
                "is_injury_status": _is_injury_transaction(type_code=type_code, type_desc=type_desc, description=description),
            }
        )
    return rows


def write_statsapi_normalization(
    snapshot_path: Path,
    *,
    kind: str,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Normalize a saved StatsAPI snapshot and write JSONL artifacts."""

    payload = load_snapshot_payload(snapshot_path)
    manifest = load_snapshot_manifest(snapshot_path)
    target_date = _target_date_from_statsapi_payload(payload, manifest)
    resolved_run_id = run_id or _statsapi_run_id(kind=kind, snapshot_id=str(manifest.get("snapshot_id") or kind), target_date=target_date)
    rows = normalize_statsapi_payload(kind=kind, payload=payload)
    paths = ensure_mlb_dirs(root)
    output_dir = paths.staged / kind / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    rows_path = output_dir / f"{kind}.jsonl"
    manifest_path = output_dir / "normalize_manifest.json"
    rows_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    out = {
        "run_id": resolved_run_id,
        "snapshot_id": manifest.get("snapshot_id", ""),
        "source": kind,
        "target_date": target_date,
        "date": target_date,
        "row_count": len(rows),
        "rows_path": str(rows_path),
        "output_dir": str(output_dir),
    }
    manifest_path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    return out


def _target_date_from_statsapi_payload(payload: dict[str, Any], manifest: dict[str, Any]) -> str:
    fetch = payload.get("_atlas_fetch") if isinstance(payload.get("_atlas_fetch"), dict) else {}
    request = manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
    for value in (
        payload.get("target_date"),
        fetch.get("target_date"),
        request.get("target_date"),
    ):
        text = _clean_str(value)
        if text:
            return text
    return ""


def _statsapi_run_id(*, kind: str, snapshot_id: str, target_date: str) -> str:
    if not target_date:
        return snapshot_id
    compact = target_date.replace("-", "")
    if compact in snapshot_id or target_date in snapshot_id:
        return snapshot_id
    return f"{kind}_{compact}_{snapshot_id}"


def normalize_statsapi_payload(*, kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if kind == "statsapi_teams":
        return normalize_statsapi_teams(payload)
    if kind == "statsapi_rosters":
        return normalize_statsapi_roster(payload)
    if kind == "statsapi_rosters_bulk":
        return normalize_statsapi_rosters_bulk(payload)
    if kind == "statsapi_schedule":
        return normalize_statsapi_schedule(payload)
    if kind == "statsapi_boxscore":
        return normalize_statsapi_boxscore(payload)
    if kind == "statsapi_boxscores_bulk":
        return normalize_statsapi_boxscores_bulk(payload)
    if kind == "statsapi_player_gamelog":
        return normalize_statsapi_player_gamelog(payload)
    if kind == "statsapi_player_gamelogs_bulk":
        return normalize_statsapi_player_gamelogs_bulk(payload)
    if kind == "statsapi_transactions":
        return normalize_statsapi_transactions(payload)
    raise ValueError(f"Unsupported StatsAPI normalization kind: {kind}")


def _nested_str(payload: dict[str, Any], *keys: str) -> str:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return _clean_str(value)


def _nested_int(payload: dict[str, Any], *keys: str) -> int | None:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return _to_int(value)


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _transaction_movement(*, type_code: str, type_desc: str, description: str) -> str:
    text = f"{type_code} {type_desc} {description}".lower()
    if type_code in {"CU", "SE"} or "recalled" in text or "selected the contract" in text:
        return "to_mlb"
    if type_code in {"OPT", "ASG"} or "optioned" in text or "assigned to" in text or "rehab assignment" in text:
        return "to_minors"
    if _is_injury_transaction(type_code=type_code, type_desc=type_desc, description=description):
        return "injury_status"
    return "other"


def _is_injury_transaction(*, type_code: str, type_desc: str, description: str) -> bool:
    text = f"{type_code} {type_desc} {description}".lower()
    return any(token in text for token in ("injured", "il", "10-day", "15-day", "60-day", "activated"))
