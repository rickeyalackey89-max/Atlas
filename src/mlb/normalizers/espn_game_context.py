"""Normalize ESPN MLB game context snapshots into matchup-ready artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mlb.domain.teams import canonical_team_abbr
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.sources.snapshots import load_snapshot_manifest, load_snapshot_payload

CONTEXT_TIMING = "postgame_backfill"


def normalize_espn_game_context(payload: dict[str, Any], *, snapshot_id: str = "") -> dict[str, Any]:
    """Normalize ESPN scoreboard and summary payloads into Rotowire-compatible row groups."""

    game_date = _clean_str(payload.get("game_date"))
    scoreboard = payload.get("scoreboard", {})
    scoreboard_payload = scoreboard.get("payload", {}) if isinstance(scoreboard, dict) else {}
    events_by_id = _scoreboard_events_by_id(scoreboard_payload)

    raw_events: list[dict[str, Any]] = []
    batting_orders: list[dict[str, Any]] = []
    pitchers: list[dict[str, Any]] = []
    environments: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    summaries = payload.get("summaries", [])
    if not isinstance(summaries, list):
        summaries = []

    for summary_record in summaries:
        if not isinstance(summary_record, dict):
            continue
        event_id = _clean_str(summary_record.get("event_id"))
        summary = summary_record.get("payload", {})
        if not isinstance(summary, dict):
            warnings.append({"event_id": event_id, "warning": "missing_summary_payload"})
            continue

        scoreboard_event = events_by_id.get(event_id, {})
        event_context = _event_context(summary, scoreboard_event=scoreboard_event, fallback_date=game_date)
        raw_events.append(event_context["raw_event"])
        batting_orders.extend(_lineup_rows(summary, event_context=event_context, snapshot_id=snapshot_id))
        pitcher_rows = _pitcher_rows(summary, event_context=event_context, snapshot_id=snapshot_id)
        if not pitcher_rows:
            warnings.append({"event_id": event_id, "warning": "missing_pitcher_rows"})
        pitchers.extend(pitcher_rows)
        env_row = _environment_row(summary, event_context=event_context, snapshot_id=snapshot_id)
        if env_row:
            environments.append(env_row)
        else:
            warnings.append({"event_id": event_id, "warning": "missing_environment_row"})

    parser_status = {
        "scoreboard": "parsed" if events_by_id else "empty",
        "summaries": "parsed" if summaries else "empty",
        "batting_orders": "parsed_from_boxscore" if batting_orders else "empty",
        "pitchers": "parsed_from_boxscore_or_probables" if pitchers else "empty",
        "environment": "parsed_from_game_info" if environments else "empty",
        "bullpens": "neutral_missing_source",
    }
    return {
        "snapshot_id": snapshot_id,
        "source": "espn_game_context",
        "context_timing": CONTEXT_TIMING,
        "game_date": game_date,
        "raw_events": raw_events,
        "daily_lineups": batting_orders,
        "batting_orders": batting_orders,
        "pitchers": pitchers,
        "bullpens": [],
        "hitter_context": [],
        "environment": environments,
        "parse_warnings": warnings,
        "parser_status": parser_status,
    }


def write_espn_game_context_normalization(
    snapshot_path: Path,
    *,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Normalize a saved ESPN game context snapshot and write JSONL artifacts."""

    payload = load_snapshot_payload(snapshot_path)
    manifest = load_snapshot_manifest(snapshot_path)
    resolved_run_id = run_id or str(manifest.get("snapshot_id") or "espn_game_context")
    normalized = normalize_espn_game_context(payload, snapshot_id=str(manifest.get("snapshot_id") or resolved_run_id))

    paths = ensure_mlb_dirs(root)
    output_dir = paths.staged / "espn_game_context" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts = {
        "raw_events": _write_jsonl(output_dir / "raw_events.jsonl", normalized["raw_events"]),
        "daily_lineups": _write_jsonl(output_dir / "daily_lineups.jsonl", normalized["daily_lineups"]),
        "pitchers": _write_jsonl(output_dir / "pitchers.jsonl", normalized["pitchers"]),
        "batting_orders": _write_jsonl(output_dir / "batting_orders.jsonl", normalized["batting_orders"]),
        "bullpens": _write_jsonl(output_dir / "bullpens.jsonl", normalized["bullpens"]),
        "hitter_context": _write_jsonl(output_dir / "hitter_context.jsonl", normalized["hitter_context"]),
        "environment": _write_jsonl(output_dir / "environment.jsonl", normalized["environment"]),
    }
    out = {
        "run_id": resolved_run_id,
        "snapshot_id": normalized["snapshot_id"],
        "source": "espn_game_context",
        "context_timing": normalized["context_timing"],
        "game_date": normalized["game_date"],
        "output_dir": str(output_dir),
        "row_counts": {key: _count_jsonl(Path(path)) for key, path in artifacts.items()},
        "artifacts": artifacts,
        "parser_status": normalized["parser_status"],
        "parse_warnings": normalized["parse_warnings"],
    }
    (output_dir / "normalize_manifest.json").write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    return out


def _scoreboard_events_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    events = payload.get("events", [])
    if not isinstance(events, list):
        return {}
    return {
        _clean_str(event.get("id")): event
        for event in events
        if isinstance(event, dict) and _clean_str(event.get("id"))
    }


def _event_context(
    summary: dict[str, Any],
    *,
    scoreboard_event: dict[str, Any],
    fallback_date: str,
) -> dict[str, Any]:
    header = summary.get("header", {})
    competition = _first_competition(header) or _first_competition(scoreboard_event)
    event_id = _clean_str(summary.get("id") or header.get("id") or scoreboard_event.get("id"))
    if not event_id:
        event_id = _clean_str(competition.get("id"))
    event_date = _date_only(competition.get("date") or scoreboard_event.get("date")) or fallback_date
    teams = _competition_teams(competition)
    raw_event = {
        "source": "espn_game_context",
        "context_timing": CONTEXT_TIMING,
        "event_id": event_id,
        "game_date": event_date,
        "away_team_abbr": teams.get("away", {}).get("abbr", ""),
        "home_team_abbr": teams.get("home", {}).get("abbr", ""),
        "venue_name": _venue_name(summary, competition=competition),
        "status": _status_text(competition),
    }
    return {
        "event_id": event_id,
        "game_date": event_date,
        "teams": teams,
        "competition": competition,
        "scoreboard_event": scoreboard_event,
        "raw_event": raw_event,
    }


def _lineup_rows(
    summary: dict[str, Any],
    *,
    event_context: dict[str, Any],
    snapshot_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    game_date = event_context["game_date"]
    event_id = event_context["event_id"]
    teams_by_abbr = _teams_by_abbr(event_context["teams"])
    for team_block in _boxscore_player_blocks(summary):
        team = _team(team_block.get("team", {}).get("abbreviation"))
        opponent = _opponent_for_team(team, teams_by_abbr)
        if not (team and opponent):
            continue
        batting = _stat_group(team_block, "batting")
        if not batting:
            continue
        athletes = batting.get("athletes", [])
        if not isinstance(athletes, list):
            continue
        starters = [athlete for athlete in athletes if isinstance(athlete, dict) and athlete.get("starter") is True]
        source_athletes = starters or [athlete for athlete in athletes if isinstance(athlete, dict)]
        for order, athlete_row in enumerate(source_athletes, start=1):
            athlete = athlete_row.get("athlete", {})
            player_name = _clean_str(athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName"))
            if not player_name:
                continue
            batting_order = _int(athlete_row.get("batOrder")) or order
            rows.append(
                {
                    "source": "espn_game_context",
                    "context_timing": CONTEXT_TIMING,
                    "snapshot_id": snapshot_id,
                    "game_date": game_date,
                    "game_id": event_id,
                    "event_id": event_id,
                    "team_abbr": team,
                    "team_name": _clean_str(team_block.get("team", {}).get("displayName")),
                    "opponent_abbr": opponent,
                    "opponent_name": teams_by_abbr.get(opponent, {}).get("display_name", ""),
                    "batting_order": batting_order,
                    "player_name": player_name,
                    "display_name": player_name,
                    "rotowire_player_id": _clean_str(athlete.get("id")),
                    "espn_player_id": _clean_str(athlete.get("id")),
                    "position": _position_abbr(athlete_row.get("position") or athlete.get("position")),
                    "bats": "",
                    "opposing_pitcher": "",
                    "opposing_pitcher_throws": "",
                    "lineup_status": "confirmed postgame backfill",
                    "lineup_status_key": "confirmed_postgame_backfill",
                    "game_time_et": "",
                    "game_started": True,
                    "slate_status": "postgame_backfill",
                    "flags": ["postgame_backfill_lineup"],
                }
            )
    return rows


def _pitcher_rows(
    summary: dict[str, Any],
    *,
    event_context: dict[str, Any],
    snapshot_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    game_date = event_context["game_date"]
    event_id = event_context["event_id"]
    teams_by_abbr = _teams_by_abbr(event_context["teams"])

    for team_block in _boxscore_player_blocks(summary):
        team = _team(team_block.get("team", {}).get("abbreviation"))
        opponent = _opponent_for_team(team, teams_by_abbr)
        if not (team and opponent):
            continue
        pitching = _stat_group(team_block, "pitching")
        if not pitching:
            continue
        labels = [str(label) for label in pitching.get("labels", []) if label is not None]
        athletes = pitching.get("athletes", [])
        if not isinstance(athletes, list):
            continue
        starter = next((row for row in athletes if isinstance(row, dict) and row.get("starter") is True), None)
        if not starter and athletes:
            starter = next((row for row in athletes if isinstance(row, dict)), None)
        if not starter:
            continue
        athlete = starter.get("athlete", {})
        stats = _stats_by_label(labels, starter.get("stats"))
        pitcher_name = _clean_str(athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName"))
        if not pitcher_name:
            continue
        rows.append(
            {
                "source": "espn_game_context",
                "context_timing": CONTEXT_TIMING,
                "snapshot_id": snapshot_id,
                "game_date": game_date,
                "game_id": event_id,
                "event_id": event_id,
                "team_abbr": team,
                "team_name": teams_by_abbr.get(team, {}).get("display_name", ""),
                "opponent_abbr": opponent,
                "opponent_name": teams_by_abbr.get(opponent, {}).get("display_name", ""),
                "pitcher_name": pitcher_name,
                "rotowire_player_id": _clean_str(athlete.get("id")),
                "espn_player_id": _clean_str(athlete.get("id")),
                "throws": _throws_abbr(athlete.get("throws")),
                "pitcher_stats": _pitcher_stats_text(stats),
                "lineup_status": "confirmed postgame starter",
                "lineup_status_key": "confirmed_postgame_starter",
                "game_time_et": "",
                "game_started": True,
                "slate_status": "postgame_backfill",
                "flags": ["postgame_backfill_actual_starter"],
            }
        )

    if rows:
        return rows
    return _probable_pitcher_rows(event_context=event_context, snapshot_id=snapshot_id)


def _probable_pitcher_rows(*, event_context: dict[str, Any], snapshot_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    game_date = event_context["game_date"]
    event_id = event_context["event_id"]
    teams_by_abbr = _teams_by_abbr(event_context["teams"])
    competition = event_context["scoreboard_event"].get("competitions", [{}])[0]
    competitors = competition.get("competitors", []) if isinstance(competition, dict) else []
    for competitor in (competitors if isinstance(competitors, list) else ()):
        team = _team(competitor.get("team", {}).get("abbreviation"))
        opponent = _opponent_for_team(team, teams_by_abbr)
        probables = competitor.get("probables", [])
        if not (team and opponent and isinstance(probables, list) and probables):
            continue
        probable = probables[0]
        athlete = probable.get("athlete", {}) if isinstance(probable, dict) else {}
        name = _clean_str(athlete.get("displayName") or athlete.get("fullName") or probable.get("displayName"))
        if not name:
            continue
        rows.append(
            {
                "source": "espn_game_context",
                "context_timing": CONTEXT_TIMING,
                "snapshot_id": snapshot_id,
                "game_date": game_date,
                "game_id": event_id,
                "event_id": event_id,
                "team_abbr": team,
                "team_name": teams_by_abbr.get(team, {}).get("display_name", ""),
                "opponent_abbr": opponent,
                "opponent_name": teams_by_abbr.get(opponent, {}).get("display_name", ""),
                "pitcher_name": name,
                "rotowire_player_id": _clean_str(athlete.get("id") or probable.get("playerId")),
                "espn_player_id": _clean_str(athlete.get("id") or probable.get("playerId")),
                "throws": _throws_abbr(athlete.get("throws")),
                "pitcher_stats": _probable_stats_text(probable),
                "lineup_status": "probable starter postgame backfill",
                "lineup_status_key": "probable_postgame_backfill",
                "game_time_et": "",
                "game_started": True,
                "slate_status": "postgame_backfill",
                "flags": ["postgame_backfill_probable_starter"],
            }
        )
    return rows


def _environment_row(
    summary: dict[str, Any],
    *,
    event_context: dict[str, Any],
    snapshot_id: str,
) -> dict[str, Any] | None:
    teams = event_context["teams"]
    away = teams.get("away", {}).get("abbr", "")
    home = teams.get("home", {}).get("abbr", "")
    if not (away and home):
        return None
    return {
        "source": "espn_game_context",
        "context_timing": CONTEXT_TIMING,
        "snapshot_id": snapshot_id,
        "game_date": event_context["game_date"],
        "game_id": event_context["event_id"],
        "event_id": event_context["event_id"],
        "away_team_abbr": away,
        "home_team_abbr": home,
        "away_team_name": teams.get("away", {}).get("display_name", ""),
        "home_team_name": teams.get("home", {}).get("display_name", ""),
        "venue_name": _venue_name(summary, competition=event_context["competition"]),
        "weather_text": _weather_text(summary),
        "umpire_text": _umpire_text(summary),
        "game_started": True,
        "slate_status": "postgame_backfill",
        "flags": ["postgame_backfill_environment"],
    }


def _first_competition(payload: dict[str, Any]) -> dict[str, Any]:
    competitions = payload.get("competitions", [])
    if isinstance(competitions, list) and competitions and isinstance(competitions[0], dict):
        return competitions[0]
    return {}


def _competition_teams(competition: dict[str, Any]) -> dict[str, dict[str, str]]:
    teams: dict[str, dict[str, str]] = {}
    competitors = competition.get("competitors", [])
    if not isinstance(competitors, list):
        return teams
    for competitor in competitors:
        if not isinstance(competitor, dict):
            continue
        side = _clean_str(competitor.get("homeAway")).lower()
        team = competitor.get("team", {})
        if side not in {"home", "away"} or not isinstance(team, dict):
            continue
        abbr = _team(team.get("abbreviation"))
        if not abbr:
            continue
        teams[side] = {
            "abbr": abbr,
            "display_name": _clean_str(team.get("displayName") or team.get("name") or abbr),
        }
    return teams


def _teams_by_abbr(teams: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["abbr"]: row for row in teams.values() if row.get("abbr")}


def _opponent_for_team(team: str, teams_by_abbr: dict[str, dict[str, str]]) -> str:
    candidates = [abbr for abbr in teams_by_abbr if abbr != team]
    return candidates[0] if len(candidates) == 1 else ""


def _boxscore_player_blocks(summary: dict[str, Any]) -> list[dict[str, Any]]:
    players = summary.get("boxscore", {}).get("players", [])
    if not isinstance(players, list):
        return []
    return [row for row in players if isinstance(row, dict)]


def _stat_group(team_block: dict[str, Any], group_type: str) -> dict[str, Any]:
    groups = team_block.get("statistics", [])
    if not isinstance(groups, list):
        return {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        if _clean_str(group.get("type")).lower() == group_type:
            return group
        if _clean_str(group.get("name")).lower() == group_type:
            return group
        if _clean_str(group.get("displayName")).lower() == group_type:
            return group
    return {}


def _stats_by_label(labels: list[str], stats: Any) -> dict[str, str]:
    if not isinstance(stats, list):
        return {}
    out: dict[str, str] = {}
    for label, value in zip(labels, stats, strict=False):
        out[str(label).upper()] = _clean_str(value)
    return out


def _pitcher_stats_text(stats: dict[str, str]) -> str:
    era = stats.get("ERA", "")
    if era:
        return f"{era} ERA"
    return ""


def _probable_stats_text(probable: dict[str, Any]) -> str:
    stats = probable.get("statistics", [])
    if not isinstance(stats, list):
        return _clean_str(probable.get("record"))
    for stat in stats:
        if isinstance(stat, dict) and _clean_str(stat.get("abbreviation")).upper() == "ERA":
            era = _clean_str(stat.get("displayValue"))
            if era:
                return f"{era} ERA"
    return _clean_str(probable.get("record"))


def _venue_name(summary: dict[str, Any], *, competition: dict[str, Any]) -> str:
    game_info = summary.get("gameInfo", {})
    venue = game_info.get("venue", {}) if isinstance(game_info, dict) else {}
    if not isinstance(venue, dict) or not venue:
        venue = competition.get("venue", {}) if isinstance(competition, dict) else {}
    return _clean_str(venue.get("fullName") or venue.get("name")) if isinstance(venue, dict) else ""


def _weather_text(summary: dict[str, Any]) -> str:
    game_info = summary.get("gameInfo", {})
    weather = game_info.get("weather", {}) if isinstance(game_info, dict) else {}
    if isinstance(weather, dict):
        display = _clean_str(weather.get("displayValue") or weather.get("temperature"))
        if display:
            return display
    return ""


def _umpire_text(summary: dict[str, Any]) -> str:
    game_info = summary.get("gameInfo", {})
    officials = game_info.get("officials", []) if isinstance(game_info, dict) else []
    if not isinstance(officials, list):
        return ""
    for official in officials:
        if not isinstance(official, dict):
            continue
        position = official.get("position", {})
        position_text = " ".join(
            _clean_str(position.get(key))
            for key in ("name", "displayName")
            if isinstance(position, dict)
        ).lower()
        if "home plate" in position_text:
            name = " ".join(_clean_str(official.get("displayName")).split())
            return f"Umpire: {name}" if name else ""
    return ""


def _status_text(competition: dict[str, Any]) -> str:
    status = competition.get("status", {}) if isinstance(competition, dict) else {}
    if isinstance(status, dict):
        type_row = status.get("type", {})
        if isinstance(type_row, dict):
            return _clean_str(type_row.get("description") or type_row.get("state"))
    return ""


def _position_abbr(value: Any) -> str:
    if isinstance(value, dict):
        return _clean_str(value.get("abbreviation") or value.get("name"))
    return _clean_str(value)


def _throws_abbr(value: Any) -> str:
    text = _clean_str(value).upper()
    if text in {"R", "L"}:
        return text
    if text.startswith("R"):
        return "R"
    if text.startswith("L"):
        return "L"
    return text


def _date_only(value: Any) -> str:
    text = _clean_str(value)
    return text[:10] if len(text) >= 10 else ""


def _team(value: Any) -> str:
    return canonical_team_abbr(value)


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _clean_str(value: Any) -> str:
    return str(value or "").strip()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return str(path)


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
