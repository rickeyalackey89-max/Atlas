"""Source fetch and normalization operations for Atlas MLB."""

from __future__ import annotations

import json
import os
import re
import time as time_module
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from mlb.fetchers.espn_injuries import fetch_espn_mlb_injuries, normalize_espn_injury_payload
from mlb.fetchers.historical_backfill.espn_game_context import fetch_espn_game_context
from mlb.fetchers.historical_backfill.espn_gamelogs import (
    fetch_espn_player_gamelog,
    fetch_espn_player_gamelogs_bulk,
)
from mlb.fetchers.draftkings import (
    DRAFTKINGS_MLB_PICK6_SOURCE,
    DRAFTKINGS_MLB_PICK6_SPORT_LEAGUE_KEY,
    fetch_draftkings_mlb_live,
    fetch_draftkings_mlb_pick6,
)
from mlb.fetchers.bettingpros import (
    BETTINGPROS_MLB_PROPS_SOURCE,
    fetch_bettingpros_mlb_props,
    parse_bettingpros_book_ids,
    parse_bettingpros_market_ids,
)
from mlb.fetchers.historical_backfill.baseball_reference import (
    fetch_baseball_reference_boxscore,
    fetch_baseball_reference_boxscores_bulk,
)
from mlb.fetchers.baseball_savant import (
    fetch_baseball_savant_context,
    parse_baseball_savant_pages,
)
from mlb.fetchers.historical_backfill.umpscorecards import fetch_umpscorecards_games
from mlb.fetchers.oddsapi import (
    fetch_oddsapi_mlb_historical_props,
    fetch_oddsapi_mlb_live_props,
    parse_bookmakers,
    parse_markets,
)
from mlb.fetchers.historical_backfill.parlayapi import (
    PARLAYAPI_HISTORICAL_CLOSING_PROPS_SOURCE,
    fetch_parlayapi_mlb_historical_closing_props,
    parse_parlayapi_markets,
)
from mlb.fetchers.prizepicks import fetch_prizepicks_all_sports_board, fetch_prizepicks_mlb_board
from mlb.fetchers.rotowire import fetch_rotowire_mlb_context, parse_rotowire_pages
from mlb.fetchers.statsapi import (
    fetch_statsapi_boxscore,
    fetch_statsapi_boxscores_bulk,
    fetch_statsapi_player_gamelog,
    fetch_statsapi_player_gamelogs_bulk,
    fetch_statsapi_roster,
    fetch_statsapi_rosters_bulk,
    fetch_statsapi_schedule,
    fetch_statsapi_teams,
    fetch_statsapi_transactions,
)
from mlb.fetchers.historical_backfill.wunderground_history import fetch_wunderground_history_weather
from mlb.normalizers.oddsapi import write_oddsapi_mlb_normalization
from mlb.normalizers.parlayapi import write_parlayapi_mlb_normalization
from mlb.normalizers.baseball_reference import write_baseball_reference_boxscore_normalization
from mlb.normalizers.baseball_savant import write_baseball_savant_normalization
from mlb.normalizers.covers_weather import write_covers_mlb_weather_normalization
from mlb.normalizers.cbs_injuries import write_cbs_mlb_injury_backfill
from mlb.normalizers.draftkings_pick6 import write_draftkings_pick6_normalization
from mlb.normalizers.bettingpros import write_bettingpros_mlb_normalization
from mlb.normalizers.espn_game_context import write_espn_game_context_normalization
from mlb.normalizers.espn_gamelogs import write_espn_gamelogs_normalization
from mlb.normalizers.prizepicks import (
    write_prizepicks_board_normalization,
    write_prizepicks_csv_normalization,
)
from mlb.normalizers.rotowire import write_rotowire_mlb_normalization
from mlb.normalizers.statsapi import normalize_statsapi_schedule, write_statsapi_normalization
from mlb.normalizers.wunderground_history import write_wunderground_history_weather_normalization
from mlb.runtime.advanced_context import prepare_advanced_profile_artifacts
from mlb.runtime.ballparks import prepare_ballpark_profile_artifacts
from mlb.runtime.engine_inputs import publish_engine_board
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.runtime.results import RuntimeCommandResult
from mlb.runtime.umpires import prepare_umpire_profile_artifacts
from mlb.sources.catalog import SOURCE_DESCRIPTIONS, SOURCE_NAMES
from mlb.sources.snapshots import (
    load_snapshot_manifest,
    load_snapshot_payload,
    timestamp_id,
    utc_now,
    write_raw_snapshot,
)

_LEGACY_PRIZEPICKS_FILENAME = re.compile(r"^prizepicks_(?P<date>\d{8})_(?P<time>\d{6})\.json$")
_PRIZEPICKS_CSV_FILENAME = re.compile(
    r"^prizepicks_(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}-\d{2}-\d{2})Z(?: \(\d+\))?\.csv$"
)


def source_catalog_result() -> RuntimeCommandResult:
    payload = {
        "sources": [
            {
                "key": key,
                "name": SOURCE_NAMES[key],
                "description": SOURCE_DESCRIPTIONS.get(key, ""),
            }
            for key in SOURCE_NAMES
        ]
    }
    lines = ["MLB sources:"]
    lines.extend(f"  - {item['key']}: {item['name']}" for item in payload["sources"])
    return RuntimeCommandResult(name="sources", payload=payload, lines=tuple(lines))


def fetch_prizepicks_result(
    *,
    root: Path | None = None,
    state_code: str = "MO",
    normalize: bool = True,
    include_all_sports: bool = True,
    publish_engine_input: bool = True,
) -> RuntimeCommandResult:
    pulled_at = utc_now()
    fetch_group_id = f"prizepicks_{timestamp_id(pulled_at)}"
    all_sports_snapshot = None
    if include_all_sports:
        all_sports_snapshot = fetch_prizepicks_all_sports_board(
            root=root,
            state_code=state_code,
            pulled_at=pulled_at,
            fetch_group_id=fetch_group_id,
        )

    snapshot = fetch_prizepicks_mlb_board(
        root=root,
        state_code=state_code,
        pulled_at=pulled_at,
        fetch_group_id=fetch_group_id,
    )
    manifest_path = snapshot.request.get("manifest_path")
    payload: dict[str, Any] = {
        "source": snapshot.source,
        "fetch_group_id": fetch_group_id,
        "snapshot_id": snapshot.request.get("snapshot_id"),
        "payload_path": snapshot.path,
        "manifest_path": manifest_path,
        "checksum": snapshot.checksum,
        "all_sports_snapshot": None,
        "normalized": None,
        "engine_input": None,
    }
    lines = []
    if all_sports_snapshot is not None:
        all_sports_manifest = load_snapshot_manifest(Path(all_sports_snapshot.path))
        payload["all_sports_snapshot"] = {
            "source": all_sports_snapshot.source,
            "snapshot_id": all_sports_snapshot.request.get("snapshot_id"),
            "payload_path": all_sports_snapshot.path,
            "manifest_path": all_sports_snapshot.request.get("manifest_path"),
            "checksum": all_sports_snapshot.checksum,
            "record_count": all_sports_manifest.get("record_count"),
        }
        lines.extend(
            [
                "Fetched PrizePicks all-sports snapshot:",
                f"  fetch_group_id: {fetch_group_id}",
                f"  snapshot_id: {payload['all_sports_snapshot']['snapshot_id']}",
                f"  payload: {all_sports_snapshot.path}",
                f"  record_count: {payload['all_sports_snapshot']['record_count']}",
            ]
        )
    lines.extend(
        [
            "Fetched PrizePicks MLB snapshot:",
            f"  fetch_group_id: {fetch_group_id}",
            f"  snapshot_id: {payload['snapshot_id']}",
            f"  payload: {snapshot.path}",
        ]
    )
    if normalize:
        normalized = write_prizepicks_board_normalization(Path(snapshot.path), root=root)
        payload["normalized"] = {
            "run_id": normalized.run_id,
            "output_dir": str(normalized.output_dir),
            "normalized_count": len(normalized.rows),
            "rejected_count": len(normalized.rejects),
        }
        lines.extend(
            [
                "Normalized PrizePicks board:",
                f"  run_id: {normalized.run_id}",
                f"  normalized_count: {len(normalized.rows)}",
                f"  rejected_count: {len(normalized.rejects)}",
            ]
        )
        if publish_engine_input:
            engine_input = publish_engine_board(normalized_dir=normalized.output_dir, root=root)
            payload["engine_input"] = engine_input
            lines.extend(
                [
                    "Published MLB engine board inputs:",
                    f"  row_count: {engine_input['row_count']}",
                    f"  csv: {engine_input['csv_path']}",
                    f"  json: {engine_input['json_path']}",
                ]
            )
    return RuntimeCommandResult(name="fetch_prizepicks", payload=payload, lines=tuple(lines))


def normalize_board_result(
    *,
    snapshot_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    resolved_snapshot = snapshot_path or latest_snapshot_path("prizepicks", root=root)
    normalized = write_prizepicks_board_normalization(resolved_snapshot, root=root, run_id=run_id)
    payload = {
        "source": "prizepicks",
        "snapshot_path": str(resolved_snapshot),
        "run_id": normalized.run_id,
        "output_dir": str(normalized.output_dir),
        "normalized_count": len(normalized.rows),
        "rejected_count": len(normalized.rejects),
    }
    lines = [
        "Normalized PrizePicks board:",
        f"  snapshot: {resolved_snapshot}",
        f"  run_id: {normalized.run_id}",
        f"  normalized_count: {len(normalized.rows)}",
        f"  rejected_count: {len(normalized.rejects)}",
    ]
    return RuntimeCommandResult(name="normalize_board", payload=payload, lines=tuple(lines))


def fetch_injuries_result(
    *,
    root: Path | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    snapshot = fetch_espn_mlb_injuries(root=root)
    payload: dict[str, Any] = {
        "source": snapshot.source,
        "snapshot_id": snapshot.request.get("snapshot_id"),
        "payload_path": snapshot.path,
        "manifest_path": snapshot.request.get("manifest_path"),
        "checksum": snapshot.checksum,
        "normalized": None,
    }
    lines = [
        "Fetched ESPN MLB injuries snapshot:",
        f"  snapshot_id: {payload['snapshot_id']}",
        f"  payload: {snapshot.path}",
    ]
    if normalize:
        normalized = normalize_injuries_snapshot(Path(snapshot.path), root=root)
        payload["normalized"] = normalized
        lines.extend(
            [
                "Normalized ESPN MLB injuries:",
                f"  run_id: {normalized['run_id']}",
                f"  injury_count: {normalized['injury_count']}",
            ]
        )
    return RuntimeCommandResult(name="fetch_injuries", payload=payload, lines=tuple(lines))


def fetch_rotowire_result(
    *,
    root: Path | None = None,
    game_date: str | None = None,
    pages: str | tuple[str, ...] | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    resolved_pages = parse_rotowire_pages(pages)
    snapshot = fetch_rotowire_mlb_context(root=root, game_date=game_date, pages=resolved_pages)
    manifest = load_snapshot_manifest(Path(snapshot.path))
    payload: dict[str, Any] = {
        "source": snapshot.source,
        "snapshot_id": snapshot.request.get("snapshot_id"),
        "payload_path": snapshot.path,
        "manifest_path": snapshot.request.get("manifest_path"),
        "checksum": snapshot.checksum,
        "record_count": manifest.get("record_count"),
        "request": snapshot.request,
        "normalized": None,
    }
    lines = [
        "Fetched Rotowire MLB context snapshot:",
        f"  snapshot_id: {payload['snapshot_id']}",
        f"  game_date: {game_date or '(current Rotowire page)'}",
        f"  pages: {', '.join(snapshot.request.get('pages') or [])}",
        f"  payload: {snapshot.path}",
    ]
    if normalize:
        normalized = write_rotowire_mlb_normalization(Path(snapshot.path), root=root)
        payload["normalized"] = normalized
        counts = normalized["row_counts"]
        lines.extend(
            [
                "Normalized Rotowire MLB context:",
                f"  run_id: {normalized['run_id']}",
                f"  daily_lineups: {counts.get('daily_lineups', 0)}",
                f"  pitchers: {counts.get('pitchers', 0)}",
                f"  bullpens: {counts.get('bullpens', 0)}",
                f"  hitter_context: {counts.get('hitter_context', 0)}",
                f"  environment: {counts.get('environment', 0)}",
            ]
        )
    return RuntimeCommandResult(name="fetch_rotowire", payload=payload, lines=tuple(lines))


def fetch_espn_game_context_result(
    *,
    root: Path | None = None,
    game_date: str,
    normalize: bool = True,
) -> RuntimeCommandResult:
    snapshot = fetch_espn_game_context(root=root, game_date=game_date)
    manifest = load_snapshot_manifest(Path(snapshot.path))
    payload: dict[str, Any] = {
        "source": snapshot.source,
        "snapshot_id": snapshot.request.get("snapshot_id"),
        "payload_path": snapshot.path,
        "manifest_path": snapshot.request.get("manifest_path"),
        "checksum": snapshot.checksum,
        "record_count": manifest.get("record_count"),
        "request": snapshot.request,
        "normalized": None,
    }
    lines = [
        "Fetched ESPN MLB game context snapshot:",
        f"  snapshot_id: {payload['snapshot_id']}",
        f"  game_date: {game_date}",
        f"  events: {len(snapshot.request.get('event_ids') or [])}",
        f"  payload: {snapshot.path}",
    ]
    if normalize:
        normalized = write_espn_game_context_normalization(Path(snapshot.path), root=root)
        payload["normalized"] = normalized
        counts = normalized["row_counts"]
        lines.extend(
            [
                "Normalized ESPN MLB game context:",
                f"  run_id: {normalized['run_id']}",
                f"  context_timing: {normalized['context_timing']}",
                f"  batting_orders: {counts.get('batting_orders', 0)}",
                f"  pitchers: {counts.get('pitchers', 0)}",
                f"  environment: {counts.get('environment', 0)}",
            ]
        )
    return RuntimeCommandResult(name="fetch_espn_game_context", payload=payload, lines=tuple(lines))


def fetch_espn_gamelog_result(
    *,
    athlete_id: str,
    season: int,
    root: Path | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    snapshot = fetch_espn_player_gamelog(athlete_id=athlete_id, season=season, root=root)
    return _espn_gamelog_fetch_result(
        snapshot_path=Path(snapshot.path),
        kind="espn_player_gamelog",
        normalize=normalize,
        root=root,
    )


def fetch_espn_gamelogs_bulk_result(
    *,
    athlete_ids: tuple[str, ...] = (),
    season: int,
    limit: int = 0,
    root: Path | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    paths = ensure_mlb_dirs(root)
    players = _espn_gamelog_players(paths=paths, athlete_ids=athlete_ids)
    if limit > 0:
        players = players[:limit]
    if not players:
        raise ValueError(
            "No ESPN athlete IDs found for bulk game logs. Pass --athlete-ids or fetch/normalize ESPN game context first."
        )
    snapshot = fetch_espn_player_gamelogs_bulk(players=players, season=season, root=root)
    result = _espn_gamelog_fetch_result(
        snapshot_path=Path(snapshot.path),
        kind="espn_player_gamelogs_bulk",
        normalize=normalize,
        root=root,
    )
    result.payload["player_count"] = len(players)
    return result


def fetch_baseball_reference_boxscore_result(
    *,
    root: Path | None = None,
    url: str,
    game_date: str | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    snapshot = fetch_baseball_reference_boxscore(root=root, url=url, game_date=game_date)
    manifest = load_snapshot_manifest(Path(snapshot.path))
    payload: dict[str, Any] = {
        "source": snapshot.source,
        "snapshot_id": snapshot.request.get("snapshot_id"),
        "payload_path": snapshot.path,
        "manifest_path": snapshot.request.get("manifest_path"),
        "checksum": snapshot.checksum,
        "record_count": manifest.get("record_count"),
        "request": snapshot.request,
        "normalized": None,
    }
    lines = [
        "Fetched Baseball Reference boxscore context snapshot:",
        f"  snapshot_id: {payload['snapshot_id']}",
        f"  game_date: {game_date or '(from boxscore page)'}",
        f"  url: {url}",
        f"  payload: {snapshot.path}",
    ]
    if normalize:
        normalized = write_baseball_reference_boxscore_normalization(Path(snapshot.path), root=root)
        payload["normalized"] = normalized
        counts = normalized["row_counts"]
        lines.extend(
            [
                "Normalized Baseball Reference boxscore context:",
                f"  run_id: {normalized['run_id']}",
                f"  context_timing: {normalized['context_timing']}",
                f"  lineup_content_timing: {normalized['lineup_content_timing']}",
                f"  batting_orders: {counts.get('batting_orders', 0)}",
                f"  pitchers: {counts.get('pitchers', 0)}",
            ]
        )
    return RuntimeCommandResult(name="fetch_baseball_reference_boxscore", payload=payload, lines=tuple(lines))


def fetch_baseball_reference_boxscores_bulk_result(
    *,
    start_date: date,
    end_date: date,
    root: Path | None = None,
    normalize: bool = True,
    delay_s: float | None = None,
    limit: int | None = None,
) -> RuntimeCommandResult:
    paths = ensure_mlb_dirs(root)
    games = _schedule_games_for_range(paths=paths, start_date=start_date, end_date=end_date, root=root)
    snapshot = fetch_baseball_reference_boxscores_bulk(
        games=games,
        root=root,
        delay_s=delay_s,
        limit=limit,
    )
    payload: dict[str, Any] = {
        "snapshot_path": snapshot.path,
        "checksum": snapshot.checksum,
        "request": snapshot.request,
        "game_count": len(games),
    }
    lines = [
        "Fetched Baseball Reference bulk boxscore context:",
        f"  date_range: {start_date.isoformat()} to {end_date.isoformat()}",
        f"  schedule_games: {len(games)}",
        f"  fetched_pages: {snapshot.request.get('fetched_game_count', 0)}",
        f"  snapshot: {snapshot.path}",
    ]
    if normalize:
        normalized = write_baseball_reference_boxscore_normalization(Path(snapshot.path), root=root)
        payload["normalized"] = normalized
        counts = normalized["row_counts"]
        lines.extend(
            [
                "Normalized Baseball Reference bulk boxscore context:",
                f"  run_id: {normalized['run_id']}",
                f"  batting_orders: {counts.get('batting_orders', 0)}",
                f"  pitchers: {counts.get('pitchers', 0)}",
                f"  raw_games: {counts.get('raw_games', 0)}",
            ]
        )
    return RuntimeCommandResult(name="fetch_baseball_reference_boxscores_bulk", payload=payload, lines=tuple(lines))


def fetch_wunderground_history_result(
    *,
    start_date: date,
    end_date: date,
    root: Path | None = None,
    normalize: bool = True,
    api_key: str | None = None,
    weather_url_source: Path | None = None,
    delay_s: float | None = None,
    limit: int | None = None,
) -> RuntimeCommandResult:
    paths = ensure_mlb_dirs(root)
    games = _schedule_games_for_range(paths=paths, start_date=start_date, end_date=end_date, root=root)
    snapshot = fetch_wunderground_history_weather(
        games=games,
        api_key=api_key,
        weather_url_source=weather_url_source,
        root=root,
        delay_s=delay_s,
        limit=limit,
    )
    payload: dict[str, Any] = {
        "snapshot_path": snapshot.path,
        "checksum": snapshot.checksum,
        "request": snapshot.request,
        "game_count": len(games),
    }
    lines = [
        "Fetched Wunderground historical weather:",
        f"  date_range: {start_date.isoformat()} to {end_date.isoformat()}",
        f"  schedule_games: {len(games)}",
        f"  api_requests: {snapshot.request.get('api_request_count', 0)}",
        f"  fetched_games: {snapshot.request.get('fetched_game_count', 0)}",
        f"  snapshot: {snapshot.path}",
    ]
    if normalize:
        normalized = write_wunderground_history_weather_normalization(Path(snapshot.path), root=root)
        payload["normalized"] = normalized
        lines.extend(
            [
                "Normalized Wunderground historical weather:",
                f"  run_id: {normalized['run_id']}",
                f"  game_dates: {', '.join(normalized.get('game_dates') or [])}",
                f"  environment: {normalized['row_counts'].get('environment', 0)}",
                f"  warnings: {len(normalized.get('parse_warnings') or [])}",
            ]
        )
    return RuntimeCommandResult(name="fetch_wunderground_history", payload=payload, lines=tuple(lines))


def fetch_baseball_savant_result(
    *,
    root: Path | None = None,
    game_date: str | None = None,
    season: int = 2026,
    pages: str | tuple[str, ...] | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    resolved_pages = parse_baseball_savant_pages(pages)
    snapshot = fetch_baseball_savant_context(
        root=root,
        game_date=game_date,
        season=season,
        pages=resolved_pages,
    )
    manifest = load_snapshot_manifest(Path(snapshot.path))
    payload: dict[str, Any] = {
        "source": snapshot.source,
        "snapshot_id": snapshot.request.get("snapshot_id"),
        "payload_path": snapshot.path,
        "manifest_path": snapshot.request.get("manifest_path"),
        "checksum": snapshot.checksum,
        "record_count": manifest.get("record_count"),
        "request": snapshot.request,
        "normalized": None,
        "prepared": None,
    }
    lines = [
        "Fetched Baseball Savant MLB context snapshot:",
        f"  snapshot_id: {payload['snapshot_id']}",
        f"  game_date: {game_date or '(schedule default)'}",
        f"  season: {season}",
        f"  pages: {', '.join(snapshot.request.get('pages') or [])}",
        f"  payload: {snapshot.path}",
    ]
    if normalize:
        normalized = write_baseball_savant_normalization(Path(snapshot.path), root=root)
        prepared = _prepare_baseball_savant_contracts(normalized, root=root)
        payload["normalized"] = normalized
        payload["prepared"] = prepared
        counts = normalized["row_counts"]
        lines.extend(
            [
                "Normalized Baseball Savant context:",
                f"  run_id: {normalized['run_id']}",
                f"  advanced_profiles: {counts.get('advanced_profiles', 0)}",
                f"  ballparks: {counts.get('ballparks', 0)}",
                f"  schedule: {counts.get('schedule', 0)}",
            ]
        )
        if prepared:
            lines.extend(
                [
                    "Prepared Baseball Savant contract artifacts:",
                    f"  advanced_profile_count: {prepared.get('advanced_profiles', {}).get('row_count', 0)}",
                    f"  ballpark_profile_count: {prepared.get('ballparks', {}).get('profile_count', 0)}",
                ]
            )
    return RuntimeCommandResult(name="fetch_baseball_savant", payload=payload, lines=tuple(lines))


def fetch_umpscorecards_result(
    *,
    root: Path | None = None,
    start_date: str,
    end_date: str,
    season_type: str = "R",
    normalize: bool = True,
) -> RuntimeCommandResult:
    snapshot = fetch_umpscorecards_games(
        root=root,
        start_date=start_date,
        end_date=end_date,
        season_type=season_type,
    )
    manifest = load_snapshot_manifest(Path(snapshot.path))
    payload: dict[str, Any] = {
        "source": snapshot.source,
        "snapshot_id": snapshot.request.get("snapshot_id"),
        "payload_path": snapshot.path,
        "manifest_path": snapshot.request.get("manifest_path"),
        "checksum": snapshot.checksum,
        "record_count": manifest.get("record_count"),
        "request": snapshot.request,
        "prepared": None,
    }
    lines = [
        "Fetched UmpScorecards MLB game scorecards:",
        f"  snapshot_id: {payload['snapshot_id']}",
        f"  date_range: {start_date} to {end_date}",
        f"  season_type: {season_type}",
        f"  row_count: {payload['record_count']}",
        f"  payload: {snapshot.path}",
    ]
    if normalize:
        prepared = prepare_umpire_profile_artifacts(
            source_path=Path(snapshot.path),
            root=root,
            run_id=f"{payload['snapshot_id']}_umpires",
        )
        payload["prepared"] = prepared
        lines.extend(
            [
                "Prepared UmpScorecards umpire profile artifacts:",
                f"  profile_count: {prepared['profile_count']}",
                f"  csv: {prepared['csv_path']}",
                f"  json: {prepared['json_path']}",
            ]
        )
    return RuntimeCommandResult(name="fetch_umpscorecards", payload=payload, lines=tuple(lines))


def fetch_draftkings_live_result(
    *,
    root: Path | None = None,
    site: str = "dkusnj",
) -> RuntimeCommandResult:
    snapshot = fetch_draftkings_mlb_live(root=root, site=site)
    manifest = load_snapshot_manifest(Path(snapshot.path))
    request = manifest.get("request", {})
    payload = {
        "source": "draftkings_mlb_live",
        "snapshot_id": manifest.get("snapshot_id"),
        "payload_path": snapshot.path,
        "manifest_path": snapshot.request.get("manifest_path"),
        "checksum": manifest.get("checksum_sha256"),
        "request": request,
    }
    lines = [
        "Fetched DraftKings MLB live snapshot:",
        f"  snapshot_id: {payload['snapshot_id']}",
        f"  payload: {snapshot.path}",
        f"  site: {request.get('site')}",
        f"  subcategories: {request.get('subcategory_count')}",
        f"  offers: {request.get('offer_count')}",
        f"  outcomes: {request.get('outcome_count')}",
    ]
    return RuntimeCommandResult(name="fetch_draftkings_live", payload=payload, lines=tuple(lines))


def fetch_draftkings_pick6_result(
    *,
    root: Path | None = None,
    sport_league_key: str = DRAFTKINGS_MLB_PICK6_SPORT_LEAGUE_KEY,
    normalize: bool = True,
) -> RuntimeCommandResult:
    snapshot = fetch_draftkings_mlb_pick6(root=root, sport_league_key=sport_league_key)
    manifest = load_snapshot_manifest(Path(snapshot.path))
    request = manifest.get("request", {})
    payload: dict[str, Any] = {
        "source": DRAFTKINGS_MLB_PICK6_SOURCE,
        "snapshot_id": manifest.get("snapshot_id"),
        "payload_path": snapshot.path,
        "manifest_path": snapshot.request.get("manifest_path"),
        "checksum": manifest.get("checksum_sha256"),
        "request": request,
        "normalized": None,
    }
    lines = [
        "Fetched DraftKings Pick6 MLB snapshot:",
        f"  snapshot_id: {payload['snapshot_id']}",
        f"  payload: {snapshot.path}",
        f"  sport_league_key: {request.get('sport_league_key')}",
        f"  pick_groups: {request.get('pick_group_count')}",
        f"  categories: {request.get('category_count')}",
        f"  pickcards: {request.get('pickcard_count')}",
        f"  active_markets: {request.get('active_market_count')}",
    ]
    if normalize:
        normalized = write_draftkings_pick6_normalization(Path(snapshot.path), root=root)
        payload["normalized"] = normalized
        lines.extend(
            [
                "Normalized DraftKings Pick6 MLB props:",
                f"  run_id: {normalized['run_id']}",
                f"  row_count: {normalized['row_count']}",
                f"  compatible_row_count: {normalized.get('compatible_row_count', 0)}",
                f"  rejected_count: {normalized['rejected_count']}",
            ]
        )
    return RuntimeCommandResult(name="fetch_draftkings_pick6", payload=payload, lines=tuple(lines))


def fetch_bettingpros_props_result(
    *,
    game_date: date,
    root: Path | None = None,
    include_offers: bool = False,
    markets: str | tuple[str, ...] | None = None,
    book_ids: str | tuple[str, ...] | None = None,
    offer_workers: int = 4,
    max_offer_pages: int = 0,
    normalize: bool = True,
) -> RuntimeCommandResult:
    resolved_markets = parse_bettingpros_market_ids(markets)
    resolved_book_ids = parse_bettingpros_book_ids(book_ids)
    snapshot = fetch_bettingpros_mlb_props(
        game_date=game_date,
        root=root,
        include_offers=include_offers,
        market_ids=resolved_markets,
        book_ids=resolved_book_ids,
        offer_workers=offer_workers,
        max_offer_pages=max_offer_pages,
    )
    manifest = load_snapshot_manifest(Path(snapshot.path))
    request = manifest.get("request", {})
    payload: dict[str, Any] = {
        "source": BETTINGPROS_MLB_PROPS_SOURCE,
        "snapshot_id": manifest.get("snapshot_id"),
        "payload_path": snapshot.path,
        "manifest_path": snapshot.request.get("manifest_path"),
        "checksum": manifest.get("checksum_sha256"),
        "request": request,
        "normalized": None,
    }
    lines = [
        "Fetched BettingPros MLB props snapshot:",
        f"  snapshot_id: {payload['snapshot_id']}",
        f"  game_date: {game_date.isoformat()}",
        f"  props: {request.get('prop_count')}",
        f"  events: {request.get('event_count')}",
        f"  markets: {request.get('market_count')}",
        f"  offers: {request.get('offer_count')}",
        f"  offers_complete: {request.get('offers_complete')}",
        f"  payload: {snapshot.path}",
    ]
    if normalize:
        normalized = write_bettingpros_mlb_normalization(Path(snapshot.path), root=root)
        payload["normalized"] = normalized
        lines.extend(
            [
                "Normalized BettingPros MLB props:",
                f"  run_id: {normalized['run_id']}",
                f"  row_count: {normalized['row_count']}",
                f"  rejected_count: {normalized['rejected_count']}",
            ]
        )
    return RuntimeCommandResult(name="fetch_bettingpros_props", payload=payload, lines=tuple(lines))


def fetch_oddsapi_live_result(
    *,
    api_key: str | None = None,
    root: Path | None = None,
    regions: str = "us",
    bookmakers: str | tuple[str, ...] | None = None,
    markets: str | tuple[str, ...] | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    resolved_markets = parse_markets(markets)
    resolved_bookmakers = parse_bookmakers(bookmakers)
    snapshot = fetch_oddsapi_mlb_live_props(
        api_key=_resolve_oddsapi_key(api_key, root=root),
        root=root,
        regions=regions,
        bookmakers=resolved_bookmakers,
        markets=resolved_markets,
    )
    return _oddsapi_fetch_result(snapshot_path=Path(snapshot.path), normalize=normalize, root=root)


def fetch_oddsapi_historical_result(
    *,
    snapshot_date: date,
    api_key: str | None = None,
    root: Path | None = None,
    snapshot_time_utc: time = time(18, 0),
    regions: str = "us",
    bookmakers: str | tuple[str, ...] | None = None,
    markets: str | tuple[str, ...] | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    resolved_markets = parse_markets(markets)
    resolved_bookmakers = parse_bookmakers(bookmakers)
    snapshot = fetch_oddsapi_mlb_historical_props(
        api_key=_resolve_oddsapi_key(api_key, root=root),
        snapshot_date=snapshot_date,
        root=root,
        snapshot_time_utc=snapshot_time_utc,
        regions=regions,
        bookmakers=resolved_bookmakers,
        markets=resolved_markets,
    )
    return _oddsapi_fetch_result(snapshot_path=Path(snapshot.path), normalize=normalize, root=root)


def fetch_parlayapi_historical_result(
    *,
    snapshot_date: date,
    api_key: str | None = None,
    root: Path | None = None,
    snapshot_time_utc: time = time(18, 0),
    bookmakers: str | None = None,
    markets: str | tuple[str, ...] | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    resolved_markets = parse_parlayapi_markets(markets)
    snapshot = fetch_parlayapi_mlb_historical_closing_props(
        api_key=_resolve_parlayapi_key(api_key, root=root),
        snapshot_date=snapshot_date,
        root=root,
        snapshot_time_utc=snapshot_time_utc,
        bookmakers=bookmakers or None,
        markets=resolved_markets,
    )
    return _parlayapi_fetch_result(snapshot_path=Path(snapshot.path), normalize=normalize, root=root)


def normalize_oddsapi_result(
    *,
    snapshot_path: Path | None = None,
    source: str = "oddsapi_mlb_live",
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    resolved_snapshot = snapshot_path or latest_snapshot_path(source, root=root)
    normalized = write_oddsapi_mlb_normalization(resolved_snapshot, root=root, run_id=run_id)
    lines = [
        "Normalized OddsAPI MLB props:",
        f"  snapshot: {resolved_snapshot}",
        f"  run_id: {normalized['run_id']}",
        f"  row_count: {normalized['row_count']}",
        f"  compatible_row_count: {normalized.get('compatible_row_count', 0)}",
        f"  rejected_count: {normalized['rejected_count']}",
    ]
    return RuntimeCommandResult(name="normalize_oddsapi", payload=normalized, lines=tuple(lines))


def normalize_parlayapi_result(
    *,
    snapshot_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    resolved_snapshot = snapshot_path or latest_snapshot_path(PARLAYAPI_HISTORICAL_CLOSING_PROPS_SOURCE, root=root)
    normalized = write_parlayapi_mlb_normalization(resolved_snapshot, root=root, run_id=run_id)
    lines = [
        "Normalized ParlayAPI MLB historical closing props:",
        f"  snapshot: {resolved_snapshot}",
        f"  run_id: {normalized['run_id']}",
        f"  row_count: {normalized['row_count']}",
        f"  rejected_count: {normalized['rejected_count']}",
    ]
    return RuntimeCommandResult(name="normalize_parlayapi", payload=normalized, lines=tuple(lines))


def normalize_draftkings_pick6_result(
    *,
    snapshot_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    resolved_snapshot = snapshot_path or latest_snapshot_path(DRAFTKINGS_MLB_PICK6_SOURCE, root=root)
    normalized = write_draftkings_pick6_normalization(resolved_snapshot, root=root, run_id=run_id)
    lines = [
        "Normalized DraftKings Pick6 MLB props:",
        f"  snapshot: {resolved_snapshot}",
        f"  run_id: {normalized['run_id']}",
        f"  row_count: {normalized['row_count']}",
        f"  rejected_count: {normalized['rejected_count']}",
    ]
    return RuntimeCommandResult(name="normalize_draftkings_pick6", payload=normalized, lines=tuple(lines))


def normalize_bettingpros_result(
    *,
    snapshot_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    resolved_snapshot = snapshot_path or latest_snapshot_path(BETTINGPROS_MLB_PROPS_SOURCE, root=root)
    normalized = write_bettingpros_mlb_normalization(resolved_snapshot, root=root, run_id=run_id)
    lines = [
        "Normalized BettingPros MLB props:",
        f"  snapshot: {resolved_snapshot}",
        f"  run_id: {normalized['run_id']}",
        f"  row_count: {normalized['row_count']}",
        f"  rejected_count: {normalized['rejected_count']}",
    ]
    return RuntimeCommandResult(name="normalize_bettingpros", payload=normalized, lines=tuple(lines))


def normalize_rotowire_result(
    *,
    snapshot_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    resolved_snapshot = snapshot_path or latest_snapshot_path("rotowire_mlb_context", root=root)
    normalized = write_rotowire_mlb_normalization(resolved_snapshot, root=root, run_id=run_id)
    counts = normalized["row_counts"]
    lines = [
        "Normalized Rotowire MLB context:",
        f"  snapshot: {resolved_snapshot}",
        f"  run_id: {normalized['run_id']}",
        f"  daily_lineups: {counts.get('daily_lineups', 0)}",
        f"  pitchers: {counts.get('pitchers', 0)}",
        f"  bullpens: {counts.get('bullpens', 0)}",
        f"  hitter_context: {counts.get('hitter_context', 0)}",
        f"  environment: {counts.get('environment', 0)}",
    ]
    return RuntimeCommandResult(name="normalize_rotowire", payload=normalized, lines=tuple(lines))


def normalize_covers_weather_result(
    *,
    source_path: Path,
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    normalized = write_covers_mlb_weather_normalization(source_path, root=root, run_id=run_id)
    counts = normalized["row_counts"]
    game_dates = normalized.get("game_dates") or []
    lines = [
        "Normalized Covers MLB weather:",
        f"  source: {source_path}",
        f"  run_id: {normalized['run_id']}",
        f"  game_dates: {', '.join(game_dates) if game_dates else '(none)'}",
        f"  environment: {counts.get('environment', 0)}",
        f"  environment_path: {normalized['artifacts']['environment']}",
    ]
    return RuntimeCommandResult(name="normalize_covers_weather", payload=normalized, lines=tuple(lines))


def normalize_espn_game_context_result(
    *,
    snapshot_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    resolved_snapshot = snapshot_path or latest_snapshot_path("espn_game_context", root=root)
    normalized = write_espn_game_context_normalization(resolved_snapshot, root=root, run_id=run_id)
    counts = normalized["row_counts"]
    lines = [
        "Normalized ESPN MLB game context:",
        f"  snapshot: {resolved_snapshot}",
        f"  run_id: {normalized['run_id']}",
        f"  context_timing: {normalized['context_timing']}",
        f"  batting_orders: {counts.get('batting_orders', 0)}",
        f"  pitchers: {counts.get('pitchers', 0)}",
        f"  environment: {counts.get('environment', 0)}",
    ]
    return RuntimeCommandResult(name="normalize_espn_game_context", payload=normalized, lines=tuple(lines))


def normalize_baseball_reference_boxscore_result(
    *,
    snapshot_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    resolved_snapshot = snapshot_path or latest_snapshot_path("baseball_reference_boxscore_context", root=root)
    normalized = write_baseball_reference_boxscore_normalization(resolved_snapshot, root=root, run_id=run_id)
    counts = normalized["row_counts"]
    lines = [
        "Normalized Baseball Reference boxscore context:",
        f"  snapshot: {resolved_snapshot}",
        f"  run_id: {normalized['run_id']}",
        f"  context_timing: {normalized['context_timing']}",
        f"  lineup_content_timing: {normalized['lineup_content_timing']}",
        f"  batting_orders: {counts.get('batting_orders', 0)}",
        f"  pitchers: {counts.get('pitchers', 0)}",
    ]
    return RuntimeCommandResult(name="normalize_baseball_reference_boxscore", payload=normalized, lines=tuple(lines))


def normalize_wunderground_history_result(
    *,
    snapshot_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    resolved_snapshot = snapshot_path or latest_snapshot_path("wunderground_history_weather", root=root)
    normalized = write_wunderground_history_weather_normalization(resolved_snapshot, root=root, run_id=run_id)
    lines = [
        "Normalized Wunderground historical weather:",
        f"  snapshot: {resolved_snapshot}",
        f"  run_id: {normalized['run_id']}",
        f"  context_timing: {normalized['context_timing']}",
        f"  weather_content_timing: {normalized['weather_content_timing']}",
        f"  environment: {normalized['row_counts'].get('environment', 0)}",
    ]
    return RuntimeCommandResult(name="normalize_wunderground_history", payload=normalized, lines=tuple(lines))


def normalize_baseball_savant_result(
    *,
    snapshot_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    resolved_snapshot = snapshot_path or latest_snapshot_path("baseball_savant_context", root=root)
    normalized = write_baseball_savant_normalization(resolved_snapshot, root=root, run_id=run_id)
    prepared = _prepare_baseball_savant_contracts(normalized, root=root)
    counts = normalized["row_counts"]
    lines = [
        "Normalized Baseball Savant MLB context:",
        f"  snapshot: {resolved_snapshot}",
        f"  run_id: {normalized['run_id']}",
        f"  advanced_profiles: {counts.get('advanced_profiles', 0)}",
        f"  ballparks: {counts.get('ballparks', 0)}",
        f"  schedule: {counts.get('schedule', 0)}",
    ]
    if prepared:
        lines.extend(
            [
                "Prepared Baseball Savant contract artifacts:",
                f"  advanced_profile_count: {prepared.get('advanced_profiles', {}).get('row_count', 0)}",
                f"  ballpark_profile_count: {prepared.get('ballparks', {}).get('profile_count', 0)}",
            ]
        )
    return RuntimeCommandResult(
        name="normalize_baseball_savant",
        payload={**normalized, "prepared": prepared},
        lines=tuple(lines),
    )


def backfill_oddsapi_result(
    *,
    start_date: date,
    end_date: date,
    api_key: str | None = None,
    root: Path | None = None,
    regions: str = "us",
    bookmakers: str | tuple[str, ...] | None = None,
    markets: str | tuple[str, ...] | None = None,
    snapshot_time_utc: time = time(18, 0),
    dry_run: bool = False,
    force: bool = False,
    assumed_games_per_day: int = 15,
    request_pause_seconds: float = 0.15,
) -> RuntimeCommandResult:
    if start_date > end_date:
        raise ValueError("start_date must be before or equal to end_date")
    resolved_markets = parse_markets(markets)
    resolved_bookmakers = parse_bookmakers(bookmakers)
    dates = _date_range(start_date, end_date)
    estimate = _estimate_oddsapi_historical_credits(
        date_count=len(dates),
        market_count=len(resolved_markets),
        region_count=len([region for region in regions.split(",") if region.strip()]),
        assumed_games_per_day=assumed_games_per_day,
    )
    payload: dict[str, Any] = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "date_count": len(dates),
        "regions": regions,
        "bookmakers": resolved_bookmakers,
        "markets": resolved_markets,
        "market_count": len(resolved_markets),
        "snapshot_time_utc": snapshot_time_utc.isoformat(),
        "dry_run": dry_run,
        "force": force,
        "estimated_credits_upper_bound": estimate,
        "imported": [],
        "skipped": [],
    }
    lines = [
        "OddsAPI MLB historical backfill:",
        f"  date_range: {start_date.isoformat()} to {end_date.isoformat()}",
        f"  dates: {len(dates)}",
        f"  bookmakers: {','.join(resolved_bookmakers) if resolved_bookmakers else 'all'}",
        f"  markets: {len(resolved_markets)}",
        f"  estimated_credits_upper_bound: {estimate}",
    ]
    if dry_run:
        lines.append("  dry_run: true")
        return RuntimeCommandResult(name="backfill_oddsapi", payload=payload, lines=tuple(lines))

    key = _resolve_oddsapi_key(api_key, root=root)
    paths = ensure_mlb_dirs(root)
    for current_date in dates:
        existing = sorted((paths.raw / "oddsapi_mlb_historical" / current_date.isoformat()).glob("*/payload.json"))
        if existing and not force:
            payload["skipped"].append({"date": current_date.isoformat(), "reason": "existing_snapshot"})
            continue
        snapshot = fetch_oddsapi_mlb_historical_props(
            api_key=key,
            snapshot_date=current_date,
            root=root,
            snapshot_time_utc=snapshot_time_utc,
            regions=regions,
            bookmakers=resolved_bookmakers,
            markets=resolved_markets,
        )
        normalized = write_oddsapi_mlb_normalization(Path(snapshot.path), root=root)
        payload["imported"].append(
            {
                "date": current_date.isoformat(),
                "snapshot_id": snapshot.request.get("snapshot_id"),
                "payload_path": snapshot.path,
                "row_count": normalized["row_count"],
                "rejected_count": normalized["rejected_count"],
            }
        )
        if request_pause_seconds > 0:
            time_module.sleep(request_pause_seconds)

    lines.extend(
        [
            f"  imported_count: {len(payload['imported'])}",
            f"  skipped_count: {len(payload['skipped'])}",
        ]
    )
    return RuntimeCommandResult(name="backfill_oddsapi", payload=payload, lines=tuple(lines))


def backfill_parlayapi_result(
    *,
    start_date: date,
    end_date: date,
    api_key: str | None = None,
    root: Path | None = None,
    markets: str | tuple[str, ...] | None = None,
    bookmakers: str | None = None,
    snapshot_time_utc: time = time(18, 0),
    dry_run: bool = False,
    force: bool = False,
    request_pause_seconds: float = 0.15,
) -> RuntimeCommandResult:
    if start_date > end_date:
        raise ValueError("start_date must be before or equal to end_date")
    resolved_markets = parse_parlayapi_markets(markets)
    dates = _date_range(start_date, end_date)
    estimate = len(dates) * len(resolved_markets) * 10
    payload: dict[str, Any] = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "date_count": len(dates),
        "bookmakers": bookmakers or "",
        "markets": resolved_markets,
        "market_count": len(resolved_markets),
        "snapshot_time_utc": snapshot_time_utc.isoformat(),
        "dry_run": dry_run,
        "force": force,
        "estimated_credits": estimate,
        "imported": [],
        "skipped": [],
    }
    lines = [
        "ParlayAPI MLB historical closing-prop backfill:",
        f"  date_range: {start_date.isoformat()} to {end_date.isoformat()}",
        f"  dates: {len(dates)}",
        f"  markets: {len(resolved_markets)}",
        f"  estimated_credits: {estimate}",
    ]
    if dry_run:
        lines.append("  dry_run: true")
        return RuntimeCommandResult(name="backfill_parlayapi", payload=payload, lines=tuple(lines))

    key = _resolve_parlayapi_key(api_key, root=root)
    paths = ensure_mlb_dirs(root)
    for current_date in dates:
        existing = sorted(
            (paths.raw / PARLAYAPI_HISTORICAL_CLOSING_PROPS_SOURCE / current_date.isoformat()).glob("*/payload.json")
        )
        if existing and not force:
            payload["skipped"].append({"date": current_date.isoformat(), "reason": "existing_snapshot"})
            continue
        snapshot = fetch_parlayapi_mlb_historical_closing_props(
            api_key=key,
            snapshot_date=current_date,
            root=root,
            snapshot_time_utc=snapshot_time_utc,
            bookmakers=bookmakers or None,
            markets=resolved_markets,
        )
        normalized = write_parlayapi_mlb_normalization(Path(snapshot.path), root=root)
        payload["imported"].append(
            {
                "date": current_date.isoformat(),
                "snapshot_id": snapshot.request.get("snapshot_id"),
                "payload_path": snapshot.path,
                "row_count": normalized["row_count"],
                "rejected_count": normalized["rejected_count"],
            }
        )
        if request_pause_seconds > 0:
            time_module.sleep(request_pause_seconds)

    lines.extend(
        [
            f"  imported_count: {len(payload['imported'])}",
            f"  skipped_count: {len(payload['skipped'])}",
        ]
    )
    return RuntimeCommandResult(name="backfill_parlayapi", payload=payload, lines=tuple(lines))


def backfill_bettingpros_result(
    *,
    start_date: date,
    end_date: date,
    root: Path | None = None,
    include_offers: bool = False,
    markets: str | tuple[str, ...] | None = None,
    book_ids: str | tuple[str, ...] | None = None,
    offer_workers: int = 4,
    max_offer_pages: int = 0,
    dry_run: bool = False,
    force: bool = False,
    normalize: bool = True,
    request_pause_seconds: float = 0.15,
) -> RuntimeCommandResult:
    if start_date > end_date:
        raise ValueError("start_date must be before or equal to end_date")
    resolved_markets = parse_bettingpros_market_ids(markets)
    resolved_book_ids = parse_bettingpros_book_ids(book_ids)
    dates = _date_range(start_date, end_date)
    payload: dict[str, Any] = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "date_count": len(dates),
        "include_offers": include_offers,
        "markets": resolved_markets,
        "market_count": len(resolved_markets),
        "book_ids": resolved_book_ids,
        "offer_workers": offer_workers,
        "max_offer_pages": max_offer_pages,
        "dry_run": dry_run,
        "force": force,
        "normalize": normalize,
        "imported": [],
        "skipped": [],
    }
    lines = [
        "BettingPros MLB props backfill:",
        f"  date_range: {start_date.isoformat()} to {end_date.isoformat()}",
        f"  dates: {len(dates)}",
        f"  markets: {len(resolved_markets)}",
        f"  include_offers: {include_offers}",
        "  estimated_credits: 0",
    ]
    if dry_run:
        lines.append("  dry_run: true")
        return RuntimeCommandResult(name="backfill_bettingpros", payload=payload, lines=tuple(lines))

    paths = ensure_mlb_dirs(root)
    for current_date in dates:
        existing = _existing_bettingpros_normalization(paths, current_date)
        if existing and not force:
            payload["skipped"].append(
                {
                    "date": current_date.isoformat(),
                    "reason": "existing_normalization",
                    "output_dir": str(existing),
                }
            )
            continue
        snapshot = fetch_bettingpros_mlb_props(
            game_date=current_date,
            root=root,
            include_offers=include_offers,
            market_ids=resolved_markets,
            book_ids=resolved_book_ids,
            offer_workers=offer_workers,
            max_offer_pages=max_offer_pages,
        )
        normalized = None
        if normalize:
            normalized = write_bettingpros_mlb_normalization(Path(snapshot.path), root=root)
        payload["imported"].append(
            {
                "date": current_date.isoformat(),
                "snapshot_id": snapshot.request.get("snapshot_id"),
                "payload_path": snapshot.path,
                "row_count": normalized["row_count"] if normalized else None,
                "rejected_count": normalized["rejected_count"] if normalized else None,
                "normalized_output_dir": normalized["output_dir"] if normalized else "",
            }
        )
        if request_pause_seconds > 0:
            time_module.sleep(request_pause_seconds)

    lines.extend(
        [
            f"  imported_count: {len(payload['imported'])}",
            f"  skipped_count: {len(payload['skipped'])}",
        ]
    )
    return RuntimeCommandResult(name="backfill_bettingpros", payload=payload, lines=tuple(lines))


def backfill_baseball_savant_result(
    *,
    start_date: date,
    end_date: date,
    root: Path | None = None,
    season: int = 2026,
    pages: str | tuple[str, ...] | None = None,
    dry_run: bool = False,
    force: bool = False,
    request_pause_seconds: float = 0.15,
) -> RuntimeCommandResult:
    """Backfill date-safe season-to-date advanced player profile snapshots."""

    if start_date > end_date:
        raise ValueError("start_date must be before or equal to end_date")
    resolved_pages = parse_baseball_savant_pages(pages) or ("statcast_search_batter", "statcast_search_pitcher")
    dates = _date_range(start_date, end_date)
    payload: dict[str, Any] = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "date_count": len(dates),
        "season": season,
        "pages": resolved_pages,
        "dry_run": dry_run,
        "force": force,
        "imported": [],
        "skipped": [],
    }
    lines = [
        "Baseball Savant date-safe profile backfill:",
        f"  date_range: {start_date.isoformat()} to {end_date.isoformat()}",
        f"  dates: {len(dates)}",
        f"  season: {season}",
        f"  pages: {', '.join(resolved_pages)}",
        "  estimated_credits: 0",
    ]
    if dry_run:
        lines.append("  dry_run: true")
        return RuntimeCommandResult(name="backfill_baseball_savant", payload=payload, lines=tuple(lines))

    paths = ensure_mlb_dirs(root)
    for current_date in dates:
        existing = _existing_advanced_profiles(paths, current_date)
        if existing and not force:
            payload["skipped"].append(
                {
                    "date": current_date.isoformat(),
                    "reason": "existing_advanced_profile_snapshot",
                    "output_dir": str(existing),
                }
            )
            continue
        run_id = f"baseball_savant_asof_{current_date.strftime('%Y%m%d')}"
        snapshot = fetch_baseball_savant_context(
            root=root,
            game_date=current_date.isoformat(),
            season=season,
            pages=resolved_pages,
        )
        normalized = write_baseball_savant_normalization(Path(snapshot.path), root=root, run_id=run_id)
        prepared = _prepare_baseball_savant_contracts(normalized, root=root)
        advanced_profiles = prepared.get("advanced_profiles", {})
        payload["imported"].append(
            {
                "date": current_date.isoformat(),
                "snapshot_id": snapshot.request.get("snapshot_id"),
                "payload_path": snapshot.path,
                "normalized_output_dir": normalized["output_dir"],
                "advanced_profile_count": advanced_profiles.get("row_count", 0),
                "advanced_profiles_path": advanced_profiles.get("json_path", ""),
                "parse_warnings": normalized.get("parse_warnings", []),
            }
        )
        if request_pause_seconds > 0:
            time_module.sleep(request_pause_seconds)

    lines.extend(
        [
            f"  imported_count: {len(payload['imported'])}",
            f"  skipped_count: {len(payload['skipped'])}",
        ]
    )
    return RuntimeCommandResult(name="backfill_baseball_savant", payload=payload, lines=tuple(lines))


def backfill_cbs_injuries_result(
    *,
    source_path: Path,
    start_date: date | None = None,
    end_date: date | None = None,
    root: Path | None = None,
    run_id_prefix: str = "cbs_injuries",
) -> RuntimeCommandResult:
    manifest = write_cbs_mlb_injury_backfill(
        source_path,
        root=root,
        start_date=start_date,
        end_date=end_date,
        run_id_prefix=run_id_prefix,
    )
    lines = [
        "Backfilled CBS MLB injury snapshots:",
        f"  source: {source_path}",
        f"  date_range: {manifest['start_date']} to {manifest['end_date']}",
        f"  dates: {manifest['date_count']}",
        f"  injury_rows: {manifest['injury_count']}",
        f"  empty_snapshots: {manifest['empty_snapshot_count']}",
    ]
    if manifest["written"]:
        lines.append(f"  first_run: {manifest['written'][0]['run_id']}")
        lines.append(f"  last_run: {manifest['written'][-1]['run_id']}")
    return RuntimeCommandResult(name="backfill_cbs_injuries", payload=manifest, lines=tuple(lines))


def fetch_statsapi_teams_result(
    *,
    season: int,
    sport_ids: tuple[int, ...],
    root: Path | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    snapshot = fetch_statsapi_teams(season=season, sport_ids=sport_ids, root=root)
    return _statsapi_fetch_result(snapshot_path=Path(snapshot.path), kind="statsapi_teams", normalize=normalize, root=root)


def fetch_statsapi_roster_result(
    *,
    team_id: int,
    season: int,
    root: Path | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    snapshot = fetch_statsapi_roster(team_id=team_id, season=season, root=root)
    return _statsapi_fetch_result(snapshot_path=Path(snapshot.path), kind="statsapi_rosters", normalize=normalize, root=root)


def fetch_statsapi_rosters_bulk_result(
    *,
    season: int,
    sport_ids: tuple[int, ...],
    root: Path | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    paths = ensure_mlb_dirs(root)
    team_rows = _latest_staged_jsonl_rows(paths.staged / "statsapi_teams", "statsapi_teams.jsonl")
    if not team_rows:
        raise FileNotFoundError(
            "No staged StatsAPI teams found. Run `atlas-mlb fetch statsapi-teams --season "
            f"{season}` before fetching bulk rosters."
        )
    selected_teams = [
        row
        for row in team_rows
        if _safe_int(row.get("team_id")) is not None
        and (not sport_ids or _safe_int(row.get("sport_id")) in set(sport_ids))
    ]
    if not selected_teams:
        raise ValueError(f"No staged StatsAPI teams matched sport_ids={sport_ids}")
    snapshot = fetch_statsapi_rosters_bulk(teams=selected_teams, season=season, root=root)
    result = _statsapi_fetch_result(
        snapshot_path=Path(snapshot.path),
        kind="statsapi_rosters_bulk",
        normalize=normalize,
        root=root,
    )
    result.payload["team_count"] = len(selected_teams)
    return result


def fetch_statsapi_schedule_result(
    *,
    sport_id: int,
    start_date: str,
    end_date: str,
    root: Path | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    snapshot = fetch_statsapi_schedule(sport_id=sport_id, start_date=start_date, end_date=end_date, root=root)
    return _statsapi_fetch_result(snapshot_path=Path(snapshot.path), kind="statsapi_schedule", normalize=normalize, root=root)


def fetch_statsapi_boxscore_result(
    *,
    game_pk: int,
    root: Path | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    snapshot = fetch_statsapi_boxscore(game_pk=game_pk, root=root)
    return _statsapi_fetch_result(snapshot_path=Path(snapshot.path), kind="statsapi_boxscore", normalize=normalize, root=root)


def fetch_statsapi_boxscores_bulk_result(
    *,
    sport_id: int,
    start_date: str,
    end_date: str,
    game_pks: tuple[int, ...] = (),
    root: Path | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    resolved_game_pks = list(game_pks)
    schedule_payload_path = ""
    game_contexts: dict[int, dict[str, Any]] = {}
    if not resolved_game_pks:
        schedule_snapshot = fetch_statsapi_schedule(
            sport_id=sport_id,
            start_date=start_date,
            end_date=end_date,
            root=root,
        )
        schedule_payload_path = str(schedule_snapshot.path)
        schedule_payload = load_snapshot_payload(Path(schedule_snapshot.path))
        schedule_rows = normalize_statsapi_schedule(schedule_payload)
        resolved_game_pks = [int(row["game_pk"]) for row in schedule_rows if _safe_int(row.get("game_pk")) is not None]
        game_contexts = {int(row["game_pk"]): row for row in schedule_rows if _safe_int(row.get("game_pk")) is not None}
    if not resolved_game_pks:
        raise ValueError("No StatsAPI game IDs found for boxscore bulk fetch")
    snapshot = fetch_statsapi_boxscores_bulk(game_pks=resolved_game_pks, game_contexts=game_contexts, root=root)
    result = _statsapi_fetch_result(
        snapshot_path=Path(snapshot.path),
        kind="statsapi_boxscores_bulk",
        normalize=normalize,
        root=root,
    )
    result.payload["game_count"] = len(set(resolved_game_pks))
    result.payload["schedule_payload_path"] = schedule_payload_path
    return result


def fetch_statsapi_gamelog_result(
    *,
    person_id: int,
    group: str,
    season: int,
    root: Path | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    snapshot = fetch_statsapi_player_gamelog(person_id=person_id, group=group, season=season, root=root)
    return _statsapi_fetch_result(snapshot_path=Path(snapshot.path), kind="statsapi_player_gamelog", normalize=normalize, root=root)


def fetch_statsapi_gamelogs_bulk_result(
    *,
    group: str,
    season: int,
    person_ids: tuple[int, ...] = (),
    limit: int = 0,
    root: Path | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    paths = ensure_mlb_dirs(root)
    players = _statsapi_gamelog_players(paths=paths, person_ids=person_ids)
    if limit > 0:
        players = players[:limit]
    if not players:
        raise ValueError(
            "No StatsAPI player IDs found for bulk game logs. Pass --person-ids or build roster context first."
        )
    snapshot = fetch_statsapi_player_gamelogs_bulk(players=players, group=group, season=season, root=root)
    result = _statsapi_fetch_result(
        snapshot_path=Path(snapshot.path),
        kind="statsapi_player_gamelogs_bulk",
        normalize=normalize,
        root=root,
    )
    result.payload["player_count"] = len(players)
    return result


def normalize_espn_gamelogs_result(
    *,
    kind: str,
    snapshot_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    resolved_snapshot = snapshot_path or latest_snapshot_path(kind, root=root)
    normalized = write_espn_gamelogs_normalization(resolved_snapshot, root=root, run_id=run_id)
    lines = [
        f"Normalized {kind}:",
        f"  run_id: {normalized['run_id']}",
        f"  row_count: {normalized['row_count']}",
        f"  output_dir: {normalized['output_dir']}",
    ]
    return RuntimeCommandResult(name=f"normalize_{kind}", payload=normalized, lines=tuple(lines))


def fetch_statsapi_transactions_result(
    *,
    sport_id: int,
    start_date: str,
    end_date: str,
    root: Path | None = None,
    normalize: bool = True,
) -> RuntimeCommandResult:
    snapshot = fetch_statsapi_transactions(
        sport_id=sport_id,
        start_date=start_date,
        end_date=end_date,
        root=root,
    )
    return _statsapi_fetch_result(
        snapshot_path=Path(snapshot.path),
        kind="statsapi_transactions",
        normalize=normalize,
        root=root,
    )


def normalize_statsapi_result(
    *,
    kind: str,
    snapshot_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    resolved_snapshot = snapshot_path or latest_snapshot_path(kind, root=root)
    normalized = write_statsapi_normalization(resolved_snapshot, kind=kind, root=root, run_id=run_id)
    lines = [
        f"Normalized {kind}:",
        f"  snapshot: {resolved_snapshot}",
        f"  run_id: {normalized['run_id']}",
        f"  row_count: {normalized['row_count']}",
    ]
    return RuntimeCommandResult(name=f"normalize_{kind}", payload=normalized, lines=tuple(lines))


def import_legacy_prizepicks_raw_result(
    *,
    source_dir: Path,
    start_date: date,
    end_date: date,
    root: Path | None = None,
    source_name: str = "legacy_prizepicks_nba",
) -> RuntimeCommandResult:
    """Import legacy Atlas PrizePicks JSON files into MLB-dev raw snapshot storage."""

    if start_date > end_date:
        raise ValueError("start_date must be before or equal to end_date")
    if not source_dir.exists():
        raise FileNotFoundError(f"Legacy PrizePicks source directory not found: {source_dir}")

    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for path in sorted(source_dir.glob("prizepicks_*.json")):
        match = _LEGACY_PRIZEPICKS_FILENAME.match(path.name)
        if not match:
            skipped.append({"path": str(path), "reason": "filename_pattern_mismatch"})
            continue

        file_date = datetime.strptime(match.group("date"), "%Y%m%d").date()
        if file_date < start_date or file_date > end_date:
            continue

        try:
            payload_text = path.read_text(encoding="utf-8")
            payload = json.loads(payload_text)
        except (OSError, json.JSONDecodeError) as exc:
            skipped.append({"path": str(path), "reason": exc.__class__.__name__})
            continue

        filename_dt = datetime.strptime(match.group("date") + match.group("time"), "%Y%m%d%H%M%S")
        pulled_at = filename_dt.replace(tzinfo=timezone.utc)
        snapshot = write_raw_snapshot(
            source=source_name,
            payload=payload,
            payload_text=payload_text,
            pulled_at=pulled_at,
            root=root,
            request={
                "legacy_source": "Atlas production PrizePicks raw",
                "legacy_source_path": str(path),
                "legacy_filename": path.name,
                "legacy_filename_date": file_date.isoformat(),
                "timestamp_assumption": (
                    "Legacy filename timestamp is preserved as the deterministic snapshot timestamp. "
                    "The original filename remains the audit source of truth."
                ),
                "usage_note": (
                    "Imported as a PrizePicks JSON format fixture. This source is intentionally separate "
                    "from live MLB PrizePicks snapshots."
                ),
            },
        )
        imported.append(
            {
                "legacy_path": str(path),
                "snapshot_id": snapshot.request["snapshot_id"],
                "payload_path": snapshot.path,
                "record_count": _payload_record_count(payload),
                "checksum": snapshot.checksum,
            }
        )

    total_records = sum(int(item["record_count"]) for item in imported)
    payload = {
        "source_name": source_name,
        "source_dir": str(source_dir),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "imported_count": len(imported),
        "skipped_count": len(skipped),
        "total_records": total_records,
        "imported": imported,
        "skipped": skipped,
        "note": (
            "These are legacy Atlas PrizePicks raw files. They are isolated from live MLB PrizePicks snapshots "
            "so normalize board continues to use MLB-only source data."
        ),
    }
    lines = [
        "Imported legacy Atlas PrizePicks raw files:",
        f"  source: {source_name}",
        f"  source_dir: {source_dir}",
        f"  date_range: {start_date.isoformat()} to {end_date.isoformat()}",
        f"  imported_count: {len(imported)}",
        f"  skipped_count: {len(skipped)}",
        f"  total_records: {total_records}",
    ]
    if imported:
        lines.append(f"  first_payload: {imported[0]['payload_path']}")
        lines.append(f"  last_payload: {imported[-1]['payload_path']}")
    return RuntimeCommandResult(name="import_legacy_prizepicks_raw", payload=payload, lines=tuple(lines))


def import_prizepicks_csv_result(
    *,
    source_dir: Path,
    start_date: date,
    end_date: date,
    root: Path | None = None,
    publish_engine_input: bool = True,
) -> RuntimeCommandResult:
    """Import GitHub-exported PrizePicks CSV files as normalized MLB board artifacts."""

    if start_date > end_date:
        raise ValueError("start_date must be before or equal to end_date")
    if not source_dir.exists():
        raise FileNotFoundError(f"PrizePicks CSV source directory not found: {source_dir}")

    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for path in sorted(source_dir.rglob("prizepicks_*.csv")):
        match = _PRIZEPICKS_CSV_FILENAME.match(path.name)
        if not match:
            skipped.append({"path": str(path), "reason": "filename_pattern_mismatch"})
            continue

        file_date = date.fromisoformat(match.group("date"))
        if file_date < start_date or file_date > end_date:
            continue

        try:
            normalized = write_prizepicks_csv_normalization(path, root=root)
        except (OSError, ValueError) as exc:
            skipped.append({"path": str(path), "reason": exc.__class__.__name__})
            continue

        engine_input = None
        if publish_engine_input:
            engine_input = publish_engine_board(normalized_dir=normalized.output_dir, root=root)

        metadata = normalized.metadata or {}
        imported.append(
            {
                "csv_path": str(path),
                "file_date": file_date.isoformat(),
                "run_id": normalized.run_id,
                "snapshot_id": normalized.snapshot_id,
                "normalized_dir": str(normalized.output_dir),
                "normalized_count": len(normalized.rows),
                "rejected_count": len(normalized.rejects),
                "source_row_count": metadata.get("source_row_count", 0),
                "mlb_row_count": metadata.get("mlb_row_count", 0),
                "duplicate_projection_count": metadata.get("duplicate_projection_count", 0),
                "engine_input": engine_input,
            }
        )

    total_normalized = sum(int(item["normalized_count"]) for item in imported)
    total_engine_rows = sum(
        int((item.get("engine_input") or {}).get("row_count") or 0)
        for item in imported
    )
    payload = {
        "source_dir": str(source_dir),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "imported_count": len(imported),
        "skipped_count": len(skipped),
        "total_normalized": total_normalized,
        "total_engine_rows": total_engine_rows,
        "publish_engine_input": publish_engine_input,
        "imported": imported,
        "skipped": skipped,
    }
    lines = [
        "Imported GitHub PrizePicks CSV files:",
        f"  source_dir: {source_dir}",
        f"  date_range: {start_date.isoformat()} to {end_date.isoformat()}",
        f"  imported_count: {len(imported)}",
        f"  skipped_count: {len(skipped)}",
        f"  total_normalized: {total_normalized}",
    ]
    if publish_engine_input:
        lines.append(f"  total_engine_rows: {total_engine_rows}")
    if imported:
        lines.append(f"  first_run: {imported[0]['run_id']}")
        lines.append(f"  last_run: {imported[-1]['run_id']}")
    return RuntimeCommandResult(name="import_prizepicks_csv", payload=payload, lines=tuple(lines))


def normalize_injuries_result(
    *,
    snapshot_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    resolved_snapshot = snapshot_path or latest_snapshot_path("espn_injuries", root=root)
    normalized = normalize_injuries_snapshot(resolved_snapshot, root=root, run_id=run_id)
    lines = [
        "Normalized ESPN MLB injuries:",
        f"  snapshot: {resolved_snapshot}",
        f"  run_id: {normalized['run_id']}",
        f"  injury_count: {normalized['injury_count']}",
    ]
    return RuntimeCommandResult(name="normalize_injuries", payload=normalized, lines=tuple(lines))


def normalize_injuries_snapshot(
    snapshot_path: Path,
    *,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    payload = load_snapshot_payload(snapshot_path)
    manifest = load_snapshot_manifest(snapshot_path)
    injuries = normalize_espn_injury_payload(payload)
    resolved_run_id = run_id or str(manifest.get("snapshot_id") or "espn_injuries")
    paths = ensure_mlb_dirs(root)
    output_dir = paths.staged / "injuries" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    injuries_path = output_dir / "injuries.jsonl"
    manifest_path = output_dir / "normalize_manifest.json"
    injuries_path.write_text(
        "\n".join(json.dumps(asdict(injury), sort_keys=True) for injury in injuries) + ("\n" if injuries else ""),
        encoding="utf-8",
    )
    normalized_manifest = {
        "run_id": resolved_run_id,
        "snapshot_id": manifest.get("snapshot_id", ""),
        "source": "espn_injuries",
        "injury_count": len(injuries),
        "injuries_path": str(injuries_path),
        "output_dir": str(output_dir),
    }
    manifest_path.write_text(json.dumps(normalized_manifest, indent=2, sort_keys=True), encoding="utf-8")
    return normalized_manifest


def _statsapi_fetch_result(
    *,
    snapshot_path: Path,
    kind: str,
    normalize: bool,
    root: Path | None,
) -> RuntimeCommandResult:
    manifest = load_snapshot_manifest(snapshot_path)
    payload: dict[str, Any] = {
        "source": kind,
        "snapshot_id": manifest.get("snapshot_id"),
        "payload_path": str(snapshot_path),
        "manifest_path": str(snapshot_path.parent / "manifest.json"),
        "checksum": manifest.get("checksum_sha256"),
        "normalized": None,
    }
    lines = [
        f"Fetched {kind} snapshot:",
        f"  snapshot_id: {payload['snapshot_id']}",
        f"  payload: {snapshot_path}",
    ]
    if normalize:
        normalized = write_statsapi_normalization(snapshot_path, kind=kind, root=root)
        payload["normalized"] = normalized
        lines.extend(
            [
                f"Normalized {kind}:",
                f"  run_id: {normalized['run_id']}",
                f"  row_count: {normalized['row_count']}",
            ]
        )
    return RuntimeCommandResult(name=f"fetch_{kind}", payload=payload, lines=tuple(lines))


def _espn_gamelog_fetch_result(
    *,
    snapshot_path: Path,
    kind: str,
    normalize: bool,
    root: Path | None,
) -> RuntimeCommandResult:
    manifest = load_snapshot_manifest(snapshot_path)
    payload: dict[str, Any] = {
        "source": kind,
        "snapshot_id": manifest.get("snapshot_id"),
        "payload_path": str(snapshot_path),
        "manifest_path": str(snapshot_path.parent / "manifest.json"),
        "checksum": manifest.get("checksum_sha256"),
        "normalized": None,
    }
    lines = [
        f"Fetched {kind} snapshot:",
        f"  snapshot_id: {payload['snapshot_id']}",
        f"  payload: {snapshot_path}",
    ]
    if normalize:
        normalized = write_espn_gamelogs_normalization(snapshot_path, root=root)
        payload["normalized"] = normalized
        lines.extend(
            [
                f"Normalized {kind}:",
                f"  run_id: {normalized['run_id']}",
                f"  row_count: {normalized['row_count']}",
            ]
        )
    return RuntimeCommandResult(name=f"fetch_{kind}", payload=payload, lines=tuple(lines))


def _oddsapi_fetch_result(
    *,
    snapshot_path: Path,
    normalize: bool,
    root: Path | None,
) -> RuntimeCommandResult:
    manifest = load_snapshot_manifest(snapshot_path)
    source = str(manifest.get("source") or "oddsapi_mlb_live")
    payload: dict[str, Any] = {
        "source": source,
        "snapshot_id": manifest.get("snapshot_id"),
        "payload_path": str(snapshot_path),
        "manifest_path": str(snapshot_path.parent / "manifest.json"),
        "checksum": manifest.get("checksum_sha256"),
        "record_count": manifest.get("record_count"),
        "request": manifest.get("request", {}),
        "normalized": None,
    }
    lines = [
        "Fetched OddsAPI MLB props snapshot:",
        f"  source: {source}",
        f"  snapshot_id: {payload['snapshot_id']}",
        f"  payload: {snapshot_path}",
        f"  bookmakers: {payload['request'].get('bookmakers') or 'all'}",
        f"  event_odds_count: {payload['request'].get('event_odds_count')}",
    ]
    if normalize:
        normalized = write_oddsapi_mlb_normalization(snapshot_path, root=root)
        payload["normalized"] = normalized
        lines.extend(
            [
                "Normalized OddsAPI MLB props:",
                f"  run_id: {normalized['run_id']}",
                f"  row_count: {normalized['row_count']}",
                f"  rejected_count: {normalized['rejected_count']}",
            ]
        )
    return RuntimeCommandResult(name=f"fetch_{source}", payload=payload, lines=tuple(lines))


def _parlayapi_fetch_result(
    *,
    snapshot_path: Path,
    normalize: bool,
    root: Path | None,
) -> RuntimeCommandResult:
    manifest = load_snapshot_manifest(snapshot_path)
    source = str(manifest.get("source") or PARLAYAPI_HISTORICAL_CLOSING_PROPS_SOURCE)
    payload: dict[str, Any] = {
        "source": source,
        "snapshot_id": manifest.get("snapshot_id"),
        "payload_path": str(snapshot_path),
        "manifest_path": str(snapshot_path.parent / "manifest.json"),
        "checksum": manifest.get("checksum_sha256"),
        "record_count": manifest.get("record_count"),
        "request": manifest.get("request", {}),
        "normalized": None,
    }
    lines = [
        "Fetched ParlayAPI MLB historical closing props snapshot:",
        f"  source: {source}",
        f"  snapshot_id: {payload['snapshot_id']}",
        f"  payload: {snapshot_path}",
        f"  markets: {payload['request'].get('markets')}",
        f"  market_call_count: {payload['request'].get('market_call_count')}",
    ]
    if normalize:
        normalized = write_parlayapi_mlb_normalization(snapshot_path, root=root)
        payload["normalized"] = normalized
        lines.extend(
            [
                "Normalized ParlayAPI MLB historical closing props:",
                f"  run_id: {normalized['run_id']}",
                f"  row_count: {normalized['row_count']}",
                f"  rejected_count: {normalized['rejected_count']}",
            ]
        )
    return RuntimeCommandResult(name=f"fetch_{source}", payload=payload, lines=tuple(lines))


def _prepare_baseball_savant_contracts(normalized: dict[str, Any], *, root: Path | None) -> dict[str, Any]:
    artifacts = normalized.get("artifacts") or {}
    prepared: dict[str, Any] = {}
    advanced_source = artifacts.get("advanced_profiles_json")
    if advanced_source:
        prepared["advanced_profiles"] = prepare_advanced_profile_artifacts(
            source_path=Path(advanced_source),
            root=root,
            run_id=f"{normalized['run_id']}_advanced_profiles",
        )
    ballpark_source = artifacts.get("ballparks_json")
    if ballpark_source:
        prepared["ballparks"] = prepare_ballpark_profile_artifacts(
            source_path=Path(ballpark_source),
            root=root,
            run_id=f"{normalized['run_id']}_ballparks",
        )
    return prepared


def latest_snapshot_path(source: str, *, root: Path | None = None) -> Path:
    paths = ensure_mlb_dirs(root)
    candidates = sorted((paths.raw / source).glob("*/*/payload.json"))
    if not candidates:
        raise FileNotFoundError(f"No raw {source} snapshots found under {paths.raw / source}")
    return candidates[-1]


def _schedule_games_for_range(
    *,
    paths,
    start_date: date,
    end_date: date,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    rows = _all_staged_schedule_rows(paths=paths, start_date=start_date, end_date=end_date)
    present_dates = {_date_from_schedule_row(row) for row in rows}
    requested_dates = {
        (start_date + timedelta(days=offset)).isoformat()
        for offset in range((end_date - start_date).days + 1)
    }
    if not requested_dates.issubset(present_dates):
        snapshot = fetch_statsapi_schedule(
            sport_id=1,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            root=root,
        )
        write_statsapi_normalization(Path(snapshot.path), kind="statsapi_schedule", root=root)
        rows = _all_staged_schedule_rows(paths=paths, start_date=start_date, end_date=end_date)

    games_by_pk: dict[int, dict[str, Any]] = {}
    fallback_key = 0
    for row in rows:
        if _safe_int(row.get("sport_id")) not in (None, 1):
            continue
        game_date = _date_from_schedule_row(row)
        if not game_date or not (start_date.isoformat() <= game_date <= end_date.isoformat()):
            continue
        status = str(row.get("status") or "").lower()
        if "postponed" in status or "cancel" in status:
            continue
        game_pk = _safe_int(row.get("game_pk"))
        key = game_pk if game_pk is not None else -1 - fallback_key
        fallback_key += 1
        games_by_pk[key] = {
            "game_pk": game_pk,
            "official_date": game_date,
            "game_date": str(row.get("game_date") or ""),
            "game_number": _safe_int(row.get("game_number")) or 1,
            "double_header": str(row.get("double_header") or ""),
            "away_team_id": _safe_int(row.get("away_team_id")),
            "away_team_name": str(row.get("away_team_name") or ""),
            "home_team_id": _safe_int(row.get("home_team_id")),
            "home_team_name": str(row.get("home_team_name") or ""),
            "venue_id": _safe_int(row.get("venue_id")),
            "venue_name": str(row.get("venue_name") or ""),
            "status": str(row.get("status") or ""),
        }
    return sorted(games_by_pk.values(), key=lambda row: (row["official_date"], str(row.get("game_date") or ""), row.get("game_pk") or 0))


def _all_staged_schedule_rows(*, paths, start_date: date, end_date: date) -> list[dict[str, Any]]:
    base = paths.staged / "statsapi_schedule"
    if not base.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(base.glob("*/statsapi_schedule.jsonl")):
        for row in _load_jsonl(path):
            game_date = _date_from_schedule_row(row)
            if game_date and start_date.isoformat() <= game_date <= end_date.isoformat():
                rows.append(row)
    return rows


def _date_from_schedule_row(row: Mapping[str, Any]) -> str:
    value = str(row.get("official_date") or row.get("officialDate") or row.get("game_date") or row.get("gameDate") or "")
    if not value:
        return ""
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return ""


def _payload_record_count(payload: dict[str, Any]) -> int:
    data = payload.get("data")
    return len(data) if isinstance(data, list) else 0


def _latest_staged_jsonl_rows(root: Path, rows_name: str) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    candidates = sorted(root.glob(f"*/{rows_name}"), key=lambda path: (path.stat().st_mtime, path.parent.name))
    if not candidates:
        return []
    rows: list[dict[str, Any]] = []
    for line in candidates[-1].read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _statsapi_gamelog_players(*, paths, person_ids: tuple[int, ...]) -> list[dict[str, Any]]:
    if person_ids:
        return [{"person_id": person_id} for person_id in sorted({_safe_int(value) for value in person_ids if _safe_int(value)})]

    context_rows = _latest_feature_rows(paths.features / "roster_context", "roster_context.json")
    players = [
        {
            "person_id": _safe_int(row.get("statsapi_person_id")),
            "player_name": row.get("player_name"),
            "team_abbreviation": row.get("statsapi_roster_team_abbreviation") or row.get("player_team"),
            "position": row.get("statsapi_player_position"),
        }
        for row in context_rows
        if _safe_int(row.get("statsapi_person_id")) is not None
    ]
    if not players:
        roster_rows = _latest_staged_jsonl_rows(paths.staged / "statsapi_rosters_bulk", "statsapi_rosters_bulk.jsonl")
        players = [
            {
                "person_id": _safe_int(row.get("person_id")),
                "player_name": row.get("player_name"),
                "team_id": row.get("team_id"),
                "team_abbreviation": row.get("team_abbreviation"),
                "position": row.get("primary_position"),
            }
            for row in roster_rows
            if _safe_int(row.get("person_id")) is not None
        ]

    resolved: list[dict[str, Any]] = []
    seen: set[int] = set()
    for player in players:
        person_id = _safe_int(player.get("person_id"))
        if person_id is None or person_id in seen:
            continue
        seen.add(person_id)
        resolved.append({**player, "person_id": person_id})
    return resolved


def _espn_gamelog_players(*, paths, athlete_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    if athlete_ids:
        return [{"espn_player_id": athlete_id} for athlete_id in sorted({str(value).strip() for value in athlete_ids if str(value).strip()})]

    players: list[dict[str, Any]] = []
    for root, rows_name in (
        (paths.staged / "espn_game_context", "batting_orders.jsonl"),
        (paths.staged / "espn_game_context", "pitchers.jsonl"),
    ):
        if not root.exists():
            continue
        for path in sorted(root.glob(f"*/{rows_name}"), key=lambda item: (item.stat().st_mtime, item.parent.name)):
            for row in _load_jsonl(path):
                espn_id = str(row.get("espn_player_id") or row.get("rotowire_player_id") or "").strip()
                if not espn_id:
                    continue
                players.append(
                    {
                        "espn_player_id": espn_id,
                        "player_name": row.get("player_name") or row.get("pitcher_name"),
                        "team_abbreviation": row.get("team_abbr"),
                        "position": row.get("position"),
                    }
                )

    resolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for player in players:
        espn_id = str(player.get("espn_player_id") or "").strip()
        if not espn_id or espn_id in seen:
            continue
        seen.add(espn_id)
        resolved.append(player)
    return resolved


def _latest_feature_rows(root: Path, json_name: str) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    latest = root / "latest.json"
    candidates = [latest] if latest.exists() else []
    candidates.extend(sorted(root.glob(f"*/{json_name}"), key=lambda path: (path.stat().st_mtime, path.parent.name)))
    if not candidates:
        return []
    try:
        payload = json.loads(candidates[-1].read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    rows = payload.get("rows", [])
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_oddsapi_key(api_key: str | None = None, *, root: Path | None = None) -> str:
    key = (api_key or "").strip()
    if key:
        return key

    for env_name in ("ODDSAPI_KEY", "ODDS_API_KEY"):
        key = os.environ.get(env_name, "").strip()
        if key:
            return key

    explicit_key_file = os.environ.get("ODDSAPI_KEY_FILE", "").strip()
    candidate_paths = [Path(explicit_key_file)] if explicit_key_file else []
    paths = ensure_mlb_dirs(root)
    candidate_paths.extend(
        [
            paths.repo_root / "ODDSAPI_MLB.txt",
            paths.repo_root / "OddAPItoken.txt",
            paths.repo_root.parent / "OddAPItoken.txt",
        ]
    )
    for path in candidate_paths:
        try:
            if path.exists() and path.is_file():
                key = path.read_text(encoding="utf-8").strip()
                if key:
                    return key
        except OSError:
            continue

    if not key:
        raise RuntimeError("ODDSAPI_KEY or ODDSAPI_MLB.txt is required for OddsAPI fetches")
    return key


def _resolve_parlayapi_key(api_key: str | None = None, *, root: Path | None = None) -> str:
    key = (api_key or "").strip()
    if key:
        return key

    for env_name in ("PARLAYAPI_KEY", "PARLAY_API_KEY"):
        key = os.environ.get(env_name, "").strip()
        if key:
            return key

    explicit_key_file = os.environ.get("PARLAYAPI_KEY_FILE", "").strip()
    candidate_paths = [Path(explicit_key_file)] if explicit_key_file else []
    paths = ensure_mlb_dirs(root)
    candidate_paths.extend(
        [
            paths.repo_root / "ParlayAPI.txt",
            paths.repo_root.parent / "ParlayAPI.txt",
        ]
    )
    for path in candidate_paths:
        try:
            if path.exists() and path.is_file():
                for line in path.read_text(encoding="utf-8").splitlines():
                    candidate = line.strip()
                    if candidate:
                        return candidate
        except OSError:
            continue

    raise RuntimeError("PARLAYAPI_KEY or ParlayAPI.txt is required for ParlayAPI fetches")


def _date_range(start_date: date, end_date: date) -> list[date]:
    days = (end_date - start_date).days
    return [start_date + timedelta(days=offset) for offset in range(days + 1)]


def _existing_bettingpros_normalization(paths, game_date: date) -> Path | None:
    staged_root = paths.staged / "oddsapi"
    if not staged_root.exists():
        return None
    date_key = game_date.strftime("%Y%m%d")
    candidates = sorted(staged_root.glob(f"*{date_key}*/normalize_manifest.json"))
    for manifest_path in reversed(candidates):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("source") == BETTINGPROS_MLB_PROPS_SOURCE and (manifest_path.parent / "oddsapi_props.jsonl").exists():
            return manifest_path.parent
    return None


def _existing_advanced_profiles(paths, game_date: date) -> Path | None:
    staged_root = paths.staged / "advanced_profiles"
    if not staged_root.exists():
        return None
    date_key = game_date.strftime("%Y%m%d")
    candidates = sorted(staged_root.glob(f"*{date_key}*/advanced_profiles.json"))
    return candidates[-1].parent if candidates else None


def _estimate_oddsapi_historical_credits(
    *,
    date_count: int,
    market_count: int,
    region_count: int,
    assumed_games_per_day: int,
) -> int:
    event_lookup_cost = date_count
    event_odds_cost = date_count * assumed_games_per_day * 10 * market_count * max(region_count, 1)
    return event_lookup_cost + event_odds_cost
