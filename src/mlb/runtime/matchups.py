"""Runtime artifact writer for MLB matchup matrix context."""

from __future__ import annotations

import csv
import json
import re
import shutil
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from mlb.matchups.bullpen_matrix import build_bullpen_context
from mlb.matchups.environment_matrix import build_environment_context
from mlb.matchups.hitter_context import build_hitter_matchup_context
from mlb.matchups.lineup_matrix import build_lineup_context
from mlb.matchups.pitcher_matrix import build_pitcher_context
from mlb.matchups.pitcher_prop_context import build_pitcher_prop_context
from mlb.matchups.schemas import (
    HITTER_MATCHUP_CONTEXT_COLUMNS,
    MATCHUP_MATRIX_VERSION,
    PITCHER_PROP_CONTEXT_COLUMNS,
)
from mlb.domain.teams import canonical_team_abbr
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.runtime.results import RuntimeCommandResult

_COMPASS_BEARINGS = {
    "N": 0.0,
    "NNE": 22.5,
    "NE": 45.0,
    "ENE": 67.5,
    "E": 90.0,
    "ESE": 112.5,
    "SE": 135.0,
    "SSE": 157.5,
    "S": 180.0,
    "SSW": 202.5,
    "SW": 225.0,
    "WSW": 247.5,
    "W": 270.0,
    "WNW": 292.5,
    "NW": 315.0,
    "NNW": 337.5,
}


def build_matchups_result(
    *,
    engine_board_path: Path | None = None,
    player_history_context_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    game_date: str | None = None,
    directions: tuple[str, ...] = ("over", "under"),
) -> RuntimeCommandResult:
    manifest = build_matchup_context_artifacts(
        engine_board_path=engine_board_path,
        player_history_context_path=player_history_context_path,
        root=root,
        run_id=run_id,
        game_date=game_date,
        directions=directions,
    )
    lines = [
        "Built MLB matchup context artifacts:",
        f"  run_id: {manifest['run_id']}",
        f"  source_run_id: {manifest['source_run_id']}",
        f"  game_date: {manifest['game_date'] or 'all'}",
        f"  source_row_count: {manifest['source_row_count']}",
        f"  context_row_count: {manifest['row_count']}",
        f"  directions: {', '.join(manifest['directions'])}",
        f"  missing_context_rate: {manifest['missing_context_rate']}",
        f"  csv: {manifest['csv_path']}",
        f"  json: {manifest['json_path']}",
        f"  manifest: {manifest['manifest_path']}",
    ]
    return RuntimeCommandResult(name="build_matchups", payload=manifest, lines=tuple(lines))


def build_matchup_context_artifacts(
    *,
    engine_board_path: Path | None = None,
    player_history_context_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    game_date: str | None = None,
    directions: tuple[str, ...] = ("over", "under"),
) -> dict[str, Any]:
    """Build the probability-ready hitter matchup context artifact."""

    paths = ensure_mlb_dirs(root)
    source_path = engine_board_path or latest_engine_board_path(root=root)
    engine_board = _load_json(source_path)
    source_run_id = str(engine_board.get("run_id") or source_path.parent.name)
    source_rows = [row for row in engine_board.get("rows", []) if isinstance(row, dict)]
    filtered_rows = _filter_rows_by_date(source_rows, game_date)
    prop_rows = _expand_direction_rows(filtered_rows, directions=directions)
    resolved_run_id = run_id or game_date or source_run_id
    source_context = _build_component_contexts(
        paths=paths,
        prop_rows=filtered_rows,
        game_date=game_date,
        player_history_context_path=player_history_context_path,
    )

    lineup_contexts = build_lineup_context(source_context["lineups"])
    pitcher_contexts = build_pitcher_context(source_context["pitchers"])
    bullpen_contexts = build_bullpen_context(source_context["bullpens"])
    environment_contexts = build_environment_context(source_context["environments"])

    hitter_contexts = build_hitter_matchup_context(
        prop_rows,
        lineup_contexts=lineup_contexts,
        pitcher_contexts=pitcher_contexts,
        bullpen_contexts=bullpen_contexts,
        environment_contexts=environment_contexts,
        run_id=resolved_run_id,
    )
    rows = [context.to_dict() for context in hitter_contexts]
    pitcher_prop_contexts = build_pitcher_prop_context(
        prop_rows,
        pitcher_rows=source_context.get("pitchers", ()),
        bullpen_rows=source_context.get("raw_bullpens", ()),
        environment_rows=(context.to_dict() for context in environment_contexts),
        lineup_rows=source_context.get("lineups", ()),
        player_history_rows=source_context.get("player_history_rows", ()),
        advanced_profile_rows=source_context.get("advanced_profiles", ()),
        run_id=resolved_run_id,
    )
    pitcher_prop_rows = [context.to_dict() for context in pitcher_prop_contexts]

    output_dir = paths.features / "matchups" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "hitter_matchup_context.csv"
    json_path = output_dir / "hitter_matchup_context.json"
    pitcher_csv_path = output_dir / "pitcher_prop_context.csv"
    pitcher_json_path = output_dir / "pitcher_prop_context.json"
    manifest_path = output_dir / "matchup_manifest.json"

    _write_csv(csv_path, rows, columns=HITTER_MATCHUP_CONTEXT_COLUMNS)
    json_path.write_text(
        json.dumps(
            {
                "run_id": resolved_run_id,
                "source_run_id": source_run_id,
                "matchup_matrix_version": MATCHUP_MATRIX_VERSION,
                "row_count": len(rows),
                "rows": rows,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    _write_csv(pitcher_csv_path, pitcher_prop_rows, columns=PITCHER_PROP_CONTEXT_COLUMNS)
    pitcher_json_path.write_text(
        json.dumps(
            {
                "run_id": resolved_run_id,
                "source_run_id": source_run_id,
                "matchup_matrix_version": MATCHUP_MATRIX_VERSION,
                "row_count": len(pitcher_prop_rows),
                "rows": pitcher_prop_rows,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    manifest = {
        "run_id": resolved_run_id,
        "source_run_id": source_run_id,
        "source_engine_board_path": str(source_path),
        "game_date": game_date or "",
        "source_row_count": len(filtered_rows),
        "row_count": len(rows),
        "directions": list(directions),
        "matchup_matrix_version": MATCHUP_MATRIX_VERSION,
        "component_sources": {
            "lineup": source_context["sources"]["lineup"],
            "pitcher": source_context["sources"]["pitcher"],
            "bullpen": source_context["sources"]["bullpen"],
            "environment": source_context["sources"]["environment"],
            "context_source": source_context["sources"].get("context_source", "missing"),
            "reconstructed_pregame_lineup": source_context["sources"].get(
                "reconstructed_pregame_lineup",
                "missing",
            ),
            "umpire": source_context["sources"]["umpire"],
            "ballpark": source_context["sources"]["ballpark"],
            "advanced_pitcher": source_context["sources"].get("advanced_pitcher", "missing"),
            "player_history": source_context["sources"].get("player_history", "missing"),
            "bullpen_fallback": source_context["sources"].get("bullpen_fallback", "missing"),
            "wind_factors": source_context["sources"].get("wind_factors", "missing"),
        },
        "reconstructed_pregame_lineup_context": bool(
            source_context["sources"].get("reconstructed_pregame_lineup_context", False)
        ),
        "missing_context_rate": _missing_context_rate(rows),
        "missing_context_counts": _missing_context_counts(rows),
        "pitcher_prop_row_count": len(pitcher_prop_rows),
        "pitcher_prop_missing_context_rate": _missing_context_rate(
            pitcher_prop_rows,
            missing_prefixes=("missing_",),
        ),
        "pitcher_prop_thin_context_count": _flag_count(
            pitcher_prop_rows,
            "pitcher_prop_era_only_context",
        ),
        "pitcher_prop_missing_context_counts": _missing_context_counts(pitcher_prop_rows),
        "columns": list(HITTER_MATCHUP_CONTEXT_COLUMNS),
        "pitcher_prop_columns": list(PITCHER_PROP_CONTEXT_COLUMNS),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "pitcher_prop_csv_path": str(pitcher_csv_path),
        "pitcher_prop_json_path": str(pitcher_json_path),
        "manifest_path": str(manifest_path),
        "latest_csv_path": str(paths.features / "matchups" / "latest.csv"),
        "latest_json_path": str(paths.features / "matchups" / "latest.json"),
        "latest_pitcher_prop_csv_path": str(paths.features / "matchups" / "latest_pitcher_prop_context.csv"),
        "latest_pitcher_prop_json_path": str(paths.features / "matchups" / "latest_pitcher_prop_context.json"),
        "latest_manifest_path": str(paths.features / "matchups" / "latest_manifest.json"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    _copy_latest(csv_path, paths.features / "matchups" / "latest.csv")
    _copy_latest(json_path, paths.features / "matchups" / "latest.json")
    _copy_latest(pitcher_csv_path, paths.features / "matchups" / "latest_pitcher_prop_context.csv")
    _copy_latest(pitcher_json_path, paths.features / "matchups" / "latest_pitcher_prop_context.json")
    _copy_latest(manifest_path, paths.features / "matchups" / "latest_manifest.json")
    return manifest


def latest_engine_board_path(*, root: Path | None = None) -> Path:
    paths = ensure_mlb_dirs(root)
    latest = paths.staged / "engine_board" / "latest.json"
    if latest.exists():
        return latest
    candidates = sorted(
        (paths.staged / "engine_board").glob("*/engine_board.json"),
        key=lambda path: path.stat().st_mtime,
    )
    if not candidates:
        raise FileNotFoundError(f"No engine-board JSON found under {paths.staged / 'engine_board'}")
    return candidates[-1]


def _expand_direction_rows(rows: list[dict[str, Any]], *, directions: tuple[str, ...]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for row in rows:
        for direction in directions:
            expanded_row = dict(row)
            expanded_row["direction"] = direction
            expanded_row["game_id"] = _canonical_game_id(
                expanded_row.get("game_date"),
                expanded_row.get("player_team") or expanded_row.get("team"),
                expanded_row.get("opponent") or expanded_row.get("opp"),
            )
            expanded_row["team"] = str(expanded_row.get("player_team") or expanded_row.get("team") or "").upper()
            expanded.append(expanded_row)
    return expanded


def _build_component_contexts(
    *,
    paths,
    prop_rows: list[dict[str, Any]],
    game_date: str | None,
    player_history_context_path: Path | None = None,
) -> dict[str, Any]:
    rotowire_dirs = _rotowire_context_dirs(paths=paths, game_date=game_date, prop_rows=prop_rows)
    covers_weather_dirs = _covers_weather_context_dirs(paths=paths, game_date=game_date, prop_rows=prop_rows)
    wunderground_weather_dirs = _wunderground_history_context_dirs(paths=paths, game_date=game_date, prop_rows=prop_rows)
    baseball_reference_dirs = _baseball_reference_context_dirs(paths=paths, game_date=game_date, prop_rows=prop_rows)
    espn_dirs = _espn_game_context_dirs(paths=paths, game_date=game_date, prop_rows=prop_rows)
    game_start_index = _prop_game_start_index(prop_rows)
    ballpark_profile_path = _latest_json_by_date(paths.staged / "ballparks", "ballpark_profiles.json", game_date)
    if not ballpark_profile_path and not game_date:
        latest_ballpark_path = paths.staged / "ballparks" / "latest.json"
        ballpark_profile_path = latest_ballpark_path if latest_ballpark_path.exists() else None
    ballpark_profiles = _latest_rows(ballpark_profile_path) if ballpark_profile_path else []
    advanced_profile_path = _latest_json_by_date(paths.staged / "advanced_profiles", "advanced_profiles.json", game_date)
    if player_history_context_path and player_history_context_path.exists():
        resolved_player_history_path = player_history_context_path
    else:
        resolved_player_history_path = _latest_json_by_date(
            paths.features / "player_history_context",
            "player_history_context.json",
            game_date,
        )
    umpire_profile_path = _latest_json_by_date(paths.staged / "umpires", "umpire_profiles.json", game_date)
    umpire_profiles = _latest_rows(umpire_profile_path) if umpire_profile_path else []
    advanced_profiles = _latest_rows(advanced_profile_path) if advanced_profile_path else []
    player_history_rows: list[dict[str, Any]] = _latest_rows(resolved_player_history_path) if resolved_player_history_path else []
    wind_factors = _latest_json(paths.staged / "wind_factors" / "latest.json")

    batting_orders = _load_context_jsonl_many(
        rotowire_dirs,
        "batting_orders.jsonl",
        game_start_index=game_start_index,
        allow_reconstructed_pregame=True,
    )
    lineup_dirs = rotowire_dirs
    if not batting_orders and baseball_reference_dirs:
        batting_orders = _load_context_jsonl_many(
            baseball_reference_dirs,
            "batting_orders.jsonl",
            game_start_index=game_start_index,
            allow_reconstructed_pregame=True,
        )
        lineup_dirs = baseball_reference_dirs
    if espn_dirs:
        espn_batting_orders = _load_context_jsonl_many(
            espn_dirs,
            "batting_orders.jsonl",
            game_start_index=game_start_index,
            allow_reconstructed_pregame=True,
        )
        if not batting_orders and espn_batting_orders:
            batting_orders = espn_batting_orders
            lineup_dirs = espn_dirs
        elif batting_orders and espn_batting_orders:
            merged_batting_orders = _merge_context_rows(
                primary=batting_orders,
                fallback=espn_batting_orders,
                key_fn=_lineup_context_key,
            )
            if len(merged_batting_orders) > len(batting_orders):
                batting_orders = merged_batting_orders
                lineup_dirs = _merge_dirs(lineup_dirs, espn_dirs)

    pitchers = _load_context_jsonl_many(
        rotowire_dirs,
        "pitchers.jsonl",
        game_start_index=game_start_index,
        allow_reconstructed_pregame=True,
    )
    pitcher_dirs = rotowire_dirs
    if not pitchers and baseball_reference_dirs:
        pitchers = _load_context_jsonl_many(
            baseball_reference_dirs,
            "pitchers.jsonl",
            game_start_index=game_start_index,
            allow_reconstructed_pregame=True,
        )
        pitcher_dirs = baseball_reference_dirs
    if espn_dirs:
        espn_pitchers = _load_context_jsonl_many(
            espn_dirs,
            "pitchers.jsonl",
            game_start_index=game_start_index,
            allow_reconstructed_pregame=True,
        )
        if not pitchers and espn_pitchers:
            pitchers = espn_pitchers
            pitcher_dirs = espn_dirs
        elif pitchers and espn_pitchers:
            merged_pitchers = _merge_context_rows(
                primary=pitchers,
                fallback=espn_pitchers,
                key_fn=_pitcher_context_key,
            )
            if len(merged_pitchers) > len(pitchers):
                pitchers = merged_pitchers
                pitcher_dirs = _merge_dirs(pitcher_dirs, espn_dirs)

    environments = _load_context_jsonl_many(
        rotowire_dirs,
        "environment.jsonl",
        game_start_index=game_start_index,
    )
    environment_dirs = rotowire_dirs
    if not environments and covers_weather_dirs:
        environments = _load_context_jsonl_many(
            covers_weather_dirs,
            "environment.jsonl",
            game_start_index=game_start_index,
        )
        environment_dirs = covers_weather_dirs
    if not environments and wunderground_weather_dirs:
        environments = _load_context_jsonl_many(
            wunderground_weather_dirs,
            "environment.jsonl",
            game_start_index=game_start_index,
            allow_historical_weather=True,
        )
        environment_dirs = wunderground_weather_dirs
    if not environments and espn_dirs:
        environments = _load_context_jsonl_many(
            espn_dirs,
            "environment.jsonl",
            game_start_index=game_start_index,
        )
        environment_dirs = espn_dirs

    bullpens = _load_context_jsonl_many(
        rotowire_dirs,
        "bullpens.jsonl",
        game_start_index=game_start_index,
    )
    bullpen_dirs = rotowire_dirs
    if not bullpens and espn_dirs and not pitchers:
        bullpens = _load_context_jsonl_many(
            espn_dirs,
            "bullpens.jsonl",
            game_start_index=game_start_index,
        )
        bullpen_dirs = espn_dirs
    statsapi_bullpen_inputs = _statsapi_bullpen_inputs(paths=paths, prop_rows=prop_rows, game_date=game_date)

    if not (batting_orders or pitchers or environments or statsapi_bullpen_inputs):
        return {
            "lineups": (),
            "pitchers": (),
            "bullpens": _neutral_bullpens_from_board(prop_rows),
            "environments": (),
            "raw_pitchers": (),
            "raw_bullpens": (),
            "player_history_rows": (),
            "advanced_profiles": (),
            "sources": {
                "lineup": "missing_rotowire_context",
                "pitcher": "missing_rotowire_context",
                "bullpen": "neutral_missing_source",
                "environment": "missing_rotowire_context",
                "umpire": "missing",
                "ballpark": "missing",
                "advanced_pitcher": "missing",
                "player_history": "missing",
                "bullpen_fallback": "missing",
                "wind_factors": "missing",
                "reconstructed_pregame_lineup": "missing",
                "reconstructed_pregame_lineup_context": False,
            },
        }

    bullpen_inputs = _bullpen_inputs_from_rotowire(bullpens=bullpens, pitchers=pitchers)
    if statsapi_bullpen_inputs:
        bullpen_inputs = _merge_bullpen_inputs(primary=bullpen_inputs, fallback=statsapi_bullpen_inputs)
    reconstructed_pregame_sources = _reconstructed_pregame_sources(
        [*(lineup_dirs if batting_orders else []), *(pitcher_dirs if pitchers else [])],
    )
    reconstructed_pregame_used = bool(reconstructed_pregame_sources)
    return {
        "lineups": _lineup_inputs_from_rotowire(batting_orders, player_history_rows=player_history_rows),
        "pitchers": _pitcher_inputs_from_rotowire(
            pitchers,
            advanced_profiles=advanced_profiles,
        ),
        "bullpens": bullpen_inputs,
        "environments": _environment_inputs_from_rotowire(
            environments,
            umpire_profiles=umpire_profiles,
            ballpark_profiles=ballpark_profiles,
            wind_factors=wind_factors,
        ),
        "raw_pitchers": pitchers,
        "raw_bullpens": bullpens if bullpens else statsapi_bullpen_inputs,
        "player_history_rows": player_history_rows,
        "advanced_profiles": advanced_profiles,
        "sources": {
            "lineup": _source_label(lineup_dirs, "batting_orders.jsonl") if batting_orders else "missing_context",
            "pitcher": _source_label(pitcher_dirs, "pitchers.jsonl") if pitchers else "missing_context",
            "bullpen": (
                _source_label(bullpen_dirs, "bullpens.jsonl")
                if bullpens
                else (
                    str(paths.staged / "statsapi_boxscores_bulk")
                    if statsapi_bullpen_inputs
                    else "neutral_missing_source"
                )
            ),
            "environment": (
                _source_label(environment_dirs, "environment.jsonl") if environments else "missing_context"
            ),
            "context_source": _combined_context_source(
                lineup_dirs=lineup_dirs if batting_orders else [],
                pitcher_dirs=pitcher_dirs if pitchers else [],
                environment_dirs=environment_dirs if environments else [],
            ),
            "reconstructed_pregame_lineup": (
                "+".join(sorted(reconstructed_pregame_sources)) if reconstructed_pregame_used else "missing"
            ),
            "reconstructed_pregame_lineup_context": reconstructed_pregame_used,
            "umpire": str(umpire_profile_path) if umpire_profiles and umpire_profile_path else "missing",
            "ballpark": str(ballpark_profile_path) if ballpark_profiles and ballpark_profile_path else "missing",
            "advanced_pitcher": (
                str(advanced_profile_path) if advanced_profiles and advanced_profile_path else "missing"
            ),
            "player_history": str(resolved_player_history_path) if player_history_rows and resolved_player_history_path else "missing",
            "bullpen_fallback": (
                "statsapi_boxscore_history" if statsapi_bullpen_inputs else "missing"
            ),
            "wind_factors": str(paths.staged / "wind_factors" / "latest.json") if wind_factors else "missing",
        },
    }


def _rotowire_context_dirs(*, paths, game_date: str | None, prop_rows: list[dict[str, Any]]) -> list[Path]:
    base = paths.staged / "rotowire_context"
    candidates = sorted(base.glob("*/normalize_manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return []

    requested_dates = _requested_context_dates(game_date=game_date, prop_rows=prop_rows)
    if not requested_dates:
        return [candidates[0].parent]

    dirs_by_date: dict[str, Path] = {}
    for manifest_path in candidates:
        manifest = _load_json(manifest_path)
        manifest_date = _str(manifest.get("game_date"))
        if (
            manifest_date in requested_dates
            and manifest_date not in dirs_by_date
            and _manifest_available_for_replay_context(
                manifest,
                manifest_path=manifest_path,
                target_date=manifest_date,
                prop_rows=prop_rows,
            )
        ):
            dirs_by_date[manifest_date] = manifest_path.parent
        if len(dirs_by_date) == len(requested_dates):
            break
    return [dirs_by_date[date] for date in sorted(dirs_by_date)]


def _espn_game_context_dirs(*, paths, game_date: str | None, prop_rows: list[dict[str, Any]]) -> list[Path]:
    base = paths.staged / "espn_game_context"
    candidates = sorted(base.glob("*/normalize_manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return []

    requested_dates = _requested_context_dates(game_date=game_date, prop_rows=prop_rows)
    if not requested_dates:
        return [candidates[0].parent]

    dirs_by_date: dict[str, Path] = {}
    for manifest_path in candidates:
        manifest = _load_json(manifest_path)
        manifest_date = _str(manifest.get("game_date"))
        if (
            manifest_date in requested_dates
            and manifest_date not in dirs_by_date
            and _manifest_available_for_replay_context(
                manifest,
                manifest_path=manifest_path,
                target_date=manifest_date,
                prop_rows=prop_rows,
            )
        ):
            dirs_by_date[manifest_date] = manifest_path.parent
        if len(dirs_by_date) == len(requested_dates):
            break
    return [dirs_by_date[date] for date in sorted(dirs_by_date)]


def _baseball_reference_context_dirs(*, paths, game_date: str | None, prop_rows: list[dict[str, Any]]) -> list[Path]:
    base = paths.staged / "baseball_reference_boxscore_context"
    candidates = sorted(base.glob("*/normalize_manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return []

    requested_dates = _requested_context_dates(game_date=game_date, prop_rows=prop_rows)
    if not requested_dates:
        for manifest_path in candidates:
            manifest = _load_json(manifest_path)
            if _is_reconstructed_pregame_context(manifest):
                return [manifest_path.parent]
        return []

    dirs_by_date: dict[str, Path] = {}
    for manifest_path in candidates:
        manifest = _load_json(manifest_path)
        if not _is_reconstructed_pregame_context(manifest):
            continue
        manifest_dates = {_str(manifest.get("game_date"))}
        manifest_dates.update(_str(value) for value in manifest.get("game_dates", []) if _str(value))
        for date in requested_dates:
            if date in manifest_dates and date not in dirs_by_date:
                dirs_by_date[date] = manifest_path.parent
        if len(dirs_by_date) == len(requested_dates):
            break

    unique_dirs: list[Path] = []
    for date in sorted(dirs_by_date):
        directory = dirs_by_date[date]
        if directory not in unique_dirs:
            unique_dirs.append(directory)
    return unique_dirs


def _covers_weather_context_dirs(*, paths, game_date: str | None, prop_rows: list[dict[str, Any]]) -> list[Path]:
    base = paths.staged / "covers_weather"
    candidates = sorted(base.glob("*/normalize_manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return []

    requested_dates = _requested_context_dates(game_date=game_date, prop_rows=prop_rows)
    if not requested_dates:
        return [candidates[0].parent]

    dirs_by_date: dict[str, Path] = {}
    for manifest_path in candidates:
        manifest = _load_json(manifest_path)
        manifest_dates = {_str(manifest.get("game_date"))}
        manifest_dates.update(_str(value) for value in manifest.get("game_dates", []) if _str(value))
        for date in requested_dates:
            if (
                date in manifest_dates
                and date not in dirs_by_date
                and _manifest_available_for_replay_context(
                    manifest,
                    manifest_path=manifest_path,
                    target_date=date,
                    prop_rows=prop_rows,
                )
            ):
                dirs_by_date[date] = manifest_path.parent
        if len(dirs_by_date) == len(requested_dates):
            break
    unique_dirs: list[Path] = []
    for date in sorted(dirs_by_date):
        directory = dirs_by_date[date]
        if directory not in unique_dirs:
            unique_dirs.append(directory)
    return unique_dirs


def _wunderground_history_context_dirs(*, paths, game_date: str | None, prop_rows: list[dict[str, Any]]) -> list[Path]:
    base = paths.staged / "wunderground_history_weather"
    candidates = sorted(base.glob("*/normalize_manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return []

    requested_dates = _requested_context_dates(game_date=game_date, prop_rows=prop_rows)
    if not requested_dates:
        for manifest_path in candidates:
            manifest = _load_json(manifest_path)
            if _is_historical_weather_context(manifest):
                return [manifest_path.parent]
        return []

    dirs_by_date: dict[str, Path] = {}
    for manifest_path in candidates:
        manifest = _load_json(manifest_path)
        if not _is_historical_weather_context(manifest):
            continue
        manifest_dates = {_str(manifest.get("game_date"))}
        manifest_dates.update(_str(value) for value in manifest.get("game_dates", []) if _str(value))
        for date in requested_dates:
            if date in manifest_dates and date not in dirs_by_date:
                dirs_by_date[date] = manifest_path.parent
        if len(dirs_by_date) == len(requested_dates):
            break

    unique_dirs: list[Path] = []
    for date in sorted(dirs_by_date):
        directory = dirs_by_date[date]
        if directory not in unique_dirs:
            unique_dirs.append(directory)
    return unique_dirs


def _requested_context_dates(*, game_date: str | None, prop_rows: list[dict[str, Any]]) -> set[str]:
    if game_date:
        return {_str(game_date)}
    return {_str(row.get("game_date")) for row in prop_rows if _str(row.get("game_date"))}


def _manifest_available_on_or_before(manifest: dict[str, Any], *, manifest_path: Path, target_date: str) -> bool:
    source_date = _date_key(manifest.get("snapshot_id") or manifest.get("run_id") or manifest_path.parent.name)
    target = _date_key(target_date)
    return bool(source_date and target and source_date <= target)


def _manifest_available_for_replay_context(
    manifest: dict[str, Any],
    *,
    manifest_path: Path,
    target_date: str,
    prop_rows: list[dict[str, Any]],
) -> bool:
    if _is_reconstructed_pregame_context(manifest):
        return True

    if _is_postgame_context(manifest):
        return False

    snapshot_time = _snapshot_time_utc(manifest, manifest_path=manifest_path)
    latest_start = _latest_game_start_utc(prop_rows, target_date=target_date)
    if snapshot_time and latest_start:
        return snapshot_time <= latest_start

    return _manifest_available_on_or_before(manifest, manifest_path=manifest_path, target_date=target_date)


def _is_postgame_context(manifest: dict[str, Any]) -> bool:
    timing = _str(manifest.get("context_timing") or manifest.get("slate_status")).lower()
    return "postgame" in timing


def _is_reconstructed_pregame_context(payload: dict[str, Any]) -> bool:
    timing = _str(payload.get("context_timing") or payload.get("slate_status")).lower()
    content_timing = _str(payload.get("lineup_content_timing")).lower()
    source = _str(payload.get("source")).lower()
    if "postgame" in timing:
        return False
    if content_timing != "pregame_starting_lineup":
        return False
    if source == "rotowire_mlb_context" and payload.get("historical_date_query_verified") is not True:
        return False
    return "pregame" in timing or source == "baseball_reference_boxscore_context"


def _is_historical_weather_context(payload: dict[str, Any]) -> bool:
    timing = _str(payload.get("context_timing") or payload.get("slate_status")).lower()
    content_timing = _str(payload.get("weather_content_timing")).lower()
    source = _str(payload.get("source")).lower()
    if "postgame" in timing:
        return False
    return (
        source == "wunderground_history_weather"
        and "historical" in timing
        and content_timing == "observed_game_time_weather"
    )


def _latest_json_by_date(root: Path, rows_name: str, game_date: str | None) -> Path | None:
    if not root.exists():
        return None
    candidates = sorted(root.glob(f"*/{rows_name}"), key=lambda path: (path.stat().st_mtime, path.parent.name))
    if not candidates:
        return None
    if not game_date:
        return candidates[-1]
    target = _date_key(game_date)
    eligible = [
        path
        for path in candidates
        if (source_date := _date_key(path.parent.name)) and source_date <= target and _json_rows_count(path) > 0
    ]
    if eligible:
        return eligible[-1]
    if root.name == "ballparks":
        static_baseline = root / "baseball_savant_ballparks_latest_nonzero_v1" / rows_name
        if static_baseline.exists() and _json_rows_count(static_baseline) > 0:
            return static_baseline
    return None


def _lineup_inputs_from_rotowire(
    rows: list[dict[str, Any]],
    *,
    player_history_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    player_history_index = _player_history_index(player_history_rows or [])
    for row in rows:
        game_date = _str(row.get("game_date"))
        team = _team(row.get("team_abbr"))
        opponent = _team(row.get("opponent_abbr"))
        player_name = _str(row.get("player_name") or row.get("display_name"))
        if not (game_date and team and opponent and player_name):
            continue
        slot = _optional_int(row.get("batting_order"))
        lineup_status = _str(row.get("lineup_status_key") or row.get("lineup_status")).lower()
        lineup_probability = 1.0 if "confirmed" in lineup_status else 0.72
        plate_appearances = _projected_pa(slot)
        history = _find_player_history(row, player_history_index)
        if history:
            history_projection = _float(history.get("plate_appearance_projection"), 0.0)
            history_confidence = _clamp(_float(history.get("history_context_confidence"), 0.0), 0.0, 1.0)
            if history_projection > 0:
                history_weight = _clamp(0.25 + 0.25 * history_confidence, 0.25, 0.50)
                plate_appearances = round(
                    (1.0 - history_weight) * plate_appearances + history_weight * history_projection,
                    4,
                )
        inputs.append(
            {
                "game_id": _canonical_game_id(game_date, team, opponent),
                "game_date": game_date,
                "player_id": _str(row.get("rotowire_player_id")) or _name_key(player_name),
                "player_name": player_name,
                "team": team,
                "opponent": opponent,
                "batting_order_slot": slot,
                "lineup_probability": lineup_probability,
                "projected_plate_appearances": plate_appearances,
                "protection_score": _protection_score(slot),
                "run_context_score": _run_context_score(slot),
                "rbi_context_score": _rbi_context_score(slot),
                "pinch_hit_risk": 0.03 if lineup_probability >= 1.0 else 0.12,
            }
        )
    return inputs


def _player_history_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        if not row.get("player_history_context_available"):
            continue
        game_date = _str(row.get("game_date"))
        player_key = _compact_name_key(row.get("player_name"))
        team = _team(row.get("player_team"))
        if game_date and player_key and team:
            index[(game_date, player_key, team)] = row
    return index


def _find_player_history(row: dict[str, Any], index: dict[tuple[str, str, str], dict[str, Any]]) -> dict[str, Any] | None:
    game_date = _str(row.get("game_date"))
    player_key = _compact_name_key(row.get("player_name") or row.get("display_name"))
    team = _team(row.get("team_abbr") or row.get("team"))
    if not (game_date and player_key and team):
        return None
    return index.get((game_date, player_key, team))


def _pitcher_inputs_from_rotowire(
    rows: list[dict[str, Any]],
    *,
    advanced_profiles: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    profile_index = _pitcher_profile_index(advanced_profiles or [])
    for row in rows:
        game_date = _str(row.get("game_date"))
        pitcher_team = _team(row.get("team_abbr"))
        hitter_team = _team(row.get("opponent_abbr"))
        if not (game_date and pitcher_team and hitter_team):
            continue
        era = _parse_era(row.get("pitcher_stats"))
        era_delta = _clamp((era - 4.20) / 4.0, -0.35, 0.35) if era is not None else 0.0
        profile = _find_pitcher_profile(row, profile_index)
        profile_scores = _pitcher_profile_scores(profile)
        if profile_scores["available"]:
            strikeout_pressure_score = _blend_profile_with_era(
                profile_scores["strikeout_pressure_score"],
                _clamp(-0.70 * era_delta, -0.25, 0.25),
                era,
                profile_scores["confidence"],
            )
            contact_allow_score = _blend_profile_with_era(
                profile_scores["contact_allow_score"],
                era_delta,
                era,
                profile_scores["confidence"],
            )
            power_allow_score = _blend_profile_with_era(
                profile_scores["power_allow_score"],
                _clamp(0.80 * era_delta, -0.30, 0.30),
                era,
                profile_scores["confidence"],
            )
            walk_allow_score = _blend_profile_with_era(
                profile_scores["walk_allow_score"],
                _clamp(0.40 * era_delta, -0.18, 0.18),
                era,
                profile_scores["confidence"],
            )
            confidence = max(profile_scores["confidence"], 0.72 if era is not None else 0.0)
            flags = tuple(
                flag
                for flag in (
                    "advanced_pitcher_profile_applied",
                    "pitcher_era_blended_with_advanced_profile" if era is not None else "",
                    *profile_scores["flags"],
                )
                if flag
            )
        else:
            strikeout_pressure_score = _clamp(-0.70 * era_delta, -0.25, 0.25)
            contact_allow_score = era_delta
            power_allow_score = _clamp(0.80 * era_delta, -0.30, 0.30)
            walk_allow_score = _clamp(0.40 * era_delta, -0.18, 0.18)
            confidence = 0.72 if era is not None else 0.35
            flags = () if era is not None else ("pitcher_era_missing",)
        inputs.append(
            {
                "game_id": _canonical_game_id(game_date, hitter_team, pitcher_team),
                "game_date": game_date,
                "hitter_team": hitter_team,
                "opponent": pitcher_team,
                "team_abbr": pitcher_team,
                "opponent_abbr": hitter_team,
                "pitching_team": pitcher_team,
                "pitching_opponent": hitter_team,
                "starter_pitcher_id": _str(row.get("rotowire_player_id")),
                "starter_pitcher_name": _str(row.get("pitcher_name")),
                "pitcher_name": _str(row.get("pitcher_name")),
                "starter_hand": _str(row.get("throws")).upper(),
                "throws": _str(row.get("throws")).upper(),
                "starter_era": era if era is not None else "",
                "strikeout_pressure_score": strikeout_pressure_score,
                "contact_allow_score": contact_allow_score,
                "power_allow_score": power_allow_score,
                "walk_allow_score": walk_allow_score,
                "confidence": confidence,
                "flags": flags,
            }
        )
    return inputs


def _pitcher_profile_index(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_id: dict[str, dict[str, Any]] = {}
    by_name_team: dict[tuple[str, str], dict[str, Any]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if _str(row.get("profile_role")).lower() != "pitcher":
            continue
        for key in ("statsapi_person_id", "player_id"):
            value = _str(row.get(key))
            if value:
                by_id[value] = row
        name_key = _compact_name_key(row.get("player_name_key") or row.get("player_name"))
        team = _team(row.get("player_team"))
        if name_key and team:
            by_name_team[(name_key, team)] = row
        if name_key:
            by_name.setdefault(name_key, []).append(row)
    return {"by_id": by_id, "by_name_team": by_name_team, "by_name": by_name}


def _find_pitcher_profile(row: dict[str, Any], index: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("statsapi_person_id", "mlb_player_id", "player_id"):
        value = _str(row.get(key))
        if value and value in index["by_id"]:
            return index["by_id"][value]
    name_key = _compact_name_key(row.get("pitcher_name"))
    team = _team(row.get("team_abbr"))
    if name_key and team:
        profile = index["by_name_team"].get((name_key, team))
        if profile:
            return profile
    candidates = index["by_name"].get(name_key, []) if name_key else []
    return candidates[0] if len(candidates) == 1 else None


def _pitcher_profile_scores(profile: dict[str, Any] | None) -> dict[str, Any]:
    if not profile:
        return {
            "available": False,
            "strikeout_pressure_score": 0.0,
            "contact_allow_score": 0.0,
            "power_allow_score": 0.0,
            "walk_allow_score": 0.0,
            "confidence": 0.0,
            "flags": ("advanced_pitcher_profile_missing",),
        }
    sample_bf = _int(profile.get("sample_bf"))
    confidence = _clamp(sample_bf / 280.0, 0.35, 0.88) if sample_bf else 0.35
    xwoba_score = _score_metric(profile.get("xwoba"), center=0.320, scale=0.080)
    xba_score = _score_metric(profile.get("xba"), center=0.245, scale=0.060)
    xslg_score = _score_metric(profile.get("xslg"), center=0.410, scale=0.150)
    xera_score = _score_metric(profile.get("xera"), center=4.20, scale=2.25)
    barrel_score = _score_metric(profile.get("barrel_rate"), center=0.075, scale=0.060)
    hard_hit_score = _score_metric(profile.get("hard_hit_rate"), center=0.380, scale=0.150)
    avg_ev_score = _score_metric(profile.get("avg_exit_velocity"), center=88.5, scale=4.0)
    k_score = _score_metric(profile.get("k_rate"), center=0.220, scale=0.100)
    whiff_score = _score_metric(profile.get("whiff_rate"), center=0.240, scale=0.120)
    contact_score = _score_metric(profile.get("contact_rate"), center=0.760, scale=0.120)
    bb_score = _score_metric(profile.get("bb_rate"), center=0.085, scale=0.060)
    flags = tuple(_tuple_flags(profile.get("flags")))
    return {
        "available": True,
        "strikeout_pressure_score": round(_clamp(_mean((k_score, whiff_score, -0.35 * contact_score)), -1.0, 1.0), 6),
        "contact_allow_score": round(_clamp(_mean((xwoba_score, xba_score, contact_score, 0.45 * xera_score)), -1.0, 1.0), 6),
        "power_allow_score": round(
            _clamp(_mean((xslg_score, barrel_score, hard_hit_score, avg_ev_score)), -1.0, 1.0),
            6,
        ),
        "walk_allow_score": round(_clamp(bb_score, -1.0, 1.0), 6),
        "confidence": round(confidence, 6),
        "flags": flags,
    }


def _blend_profile_with_era(profile_score: float, era_score: float, era: float | None, confidence: float) -> float:
    if era is None:
        return round(_clamp(profile_score, -1.0, 1.0), 6)
    profile_weight = _clamp(confidence, 0.35, 0.88)
    blended = profile_weight * profile_score + (1.0 - profile_weight) * era_score
    return round(_clamp(blended, -1.0, 1.0), 6)


def _bullpen_inputs_from_rotowire(
    *,
    bullpens: list[dict[str, Any]],
    pitchers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not bullpens:
        return _neutral_bullpens_from_rotowire(pitchers)

    by_team = {_team(row.get("team_abbr") or row.get("team")): row for row in bullpens}
    inputs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in pitchers:
        game_date = _str(row.get("game_date"))
        pitcher_team = _team(row.get("team_abbr"))
        hitter_team = _team(row.get("opponent_abbr"))
        key = (game_date, hitter_team, pitcher_team)
        if not all(key) or key in seen:
            continue
        seen.add(key)
        bullpen = by_team.get(pitcher_team)
        if not bullpen:
            inputs.append(
                {
                    "game_id": _canonical_game_id(game_date, hitter_team, pitcher_team),
                    "hitter_team": hitter_team,
                    "opponent": pitcher_team,
                    "confidence": 0.20,
                    "flags": ("bullpen_context_missing_source",),
                }
            )
            continue
        inputs.append(
            {
                "game_id": _canonical_game_id(game_date, hitter_team, pitcher_team),
                "hitter_team": hitter_team,
                "opponent": pitcher_team,
                "bullpen_fatigue_score": _float(bullpen.get("bullpen_fatigue_score"), 0.0),
                "bullpen_quality_score": _float(bullpen.get("bullpen_quality_score"), 0.0),
                "late_game_run_score": _float(bullpen.get("late_game_run_score"), 0.0),
                "handedness_balance_score": _float(bullpen.get("handedness_balance_score"), 0.0),
                "confidence": _float(bullpen.get("confidence"), 0.0),
                "flags": _tuple_flags(bullpen.get("flags")),
            }
        )
    return inputs


def _merge_bullpen_inputs(
    *,
    primary: list[dict[str, Any]],
    fallback: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fallback_by_key = {(_str(row.get("game_id")), _team(row.get("hitter_team"))): row for row in fallback}
    if not primary:
        return fallback
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in primary:
        key = (_str(row.get("game_id")), _team(row.get("hitter_team")))
        seen.add(key)
        flags = _tuple_flags(row.get("flags"))
        if any("missing_source" in flag or "missing" in flag for flag in flags) and key in fallback_by_key:
            merged.append(fallback_by_key[key])
        else:
            merged.append(row)
    for key, row in fallback_by_key.items():
        if key not in seen:
            merged.append(row)
    return merged


def _statsapi_bullpen_inputs(
    *,
    paths,
    prop_rows: list[dict[str, Any]],
    game_date: str | None,
) -> list[dict[str, Any]]:
    target_rows = _filter_rows_by_date(prop_rows, game_date)
    if not target_rows:
        return []
    team_lookup = _statsapi_team_lookup(paths)
    if not team_lookup["by_id"]:
        return []
    schedule_by_game = _statsapi_schedule_by_game(paths)
    workloads = _statsapi_bullpen_workloads(paths, team_lookup=team_lookup, schedule_by_game=schedule_by_game)
    if not workloads:
        return []
    inputs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in target_rows:
        target_date = _date_key(row.get("game_date"))
        hitter_team = _team(row.get("player_team") or row.get("team"))
        opponent = _team(row.get("opponent") or row.get("opp"))
        if not (target_date and hitter_team and opponent):
            continue
        key = (target_date, hitter_team, opponent)
        if key in seen:
            continue
        seen.add(key)
        workload = _bullpen_workload_for_team(workloads.get(opponent, []), target_date=target_date)
        if not workload:
            continue
        fatigue_score = _bullpen_fatigue_score(workload)
        inputs.append(
            {
                "game_id": _canonical_game_id(target_date, hitter_team, opponent),
                "game_date": target_date,
                "team_abbr": opponent,
                "team": opponent,
                "hitter_team": hitter_team,
                "opponent": opponent,
                "bullpen_fatigue_score": fatigue_score,
                "bullpen_quality_score": 0.0,
                "late_game_run_score": 0.0,
                "handedness_balance_score": 0.0,
                "confidence": _clamp(0.35 + 0.04 * workload["appearance_count"], 0.35, 0.68),
                "flags": ("statsapi_boxscore_bullpen_workload",),
            }
        )
    return inputs


def _statsapi_bullpen_workloads(
    paths,
    *,
    team_lookup: dict[str, Any],
    schedule_by_game: dict[int, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for root, rows_name in (
        (paths.staged / "statsapi_boxscore", "statsapi_boxscore.jsonl"),
        (paths.staged / "statsapi_boxscores_bulk", "statsapi_boxscores_bulk.jsonl"),
    ):
        if not root.exists():
            continue
        for path in sorted(root.glob(f"*/{rows_name}"), key=lambda item: (item.stat().st_mtime, item.parent.name)):
            rows.extend(_load_jsonl(path))
    workloads: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[int, int, int]] = set()
    for row in rows:
        pitching_stats = row.get("pitching_stats") if isinstance(row.get("pitching_stats"), dict) else {}
        if not pitching_stats or row.get("is_pitching_starter"):
            continue
        game_pk = _int(row.get("game_pk"))
        person_id = _int(row.get("person_id"))
        team_id = _int(row.get("team_id"))
        key = (game_pk, team_id, person_id)
        if not (game_pk and team_id and person_id) or key in seen:
            continue
        seen.add(key)
        schedule = schedule_by_game.get(game_pk, {})
        row_date = _date_key(row.get("official_date") or row.get("game_date") or schedule.get("official_date"))
        team = team_lookup["by_id"].get(team_id) or _team(row.get("team_name"))
        if not (row_date and team):
            continue
        workloads.setdefault(team, []).append(
            {
                "date": row_date,
                "game_pk": game_pk,
                "person_id": person_id,
                "pitches": _pitch_count(pitching_stats),
                "outs": _outs_recorded(pitching_stats),
            }
        )
    return workloads


def _bullpen_workload_for_team(rows: list[dict[str, Any]], *, target_date: str) -> dict[str, Any] | None:
    target = _parse_date(target_date)
    if not target:
        return None
    recent = []
    for row in rows:
        row_date = _parse_date(row.get("date"))
        if row_date and 1 <= (target - row_date).days <= 3:
            recent.append(row)
    if not recent:
        return None
    pitches = sum(_float(row.get("pitches"), 0.0) for row in recent)
    appearances = len(recent)
    last_day_pitchers = {
        _int(row.get("person_id"))
        for row in recent
        if (_parse_date(row.get("date")) and (target - _parse_date(row.get("date"))).days == 1)
    }
    two_day_pitchers = {
        _int(row.get("person_id"))
        for row in recent
        if (_parse_date(row.get("date")) and (target - _parse_date(row.get("date"))).days == 2)
    }
    return {
        "pitch_count": pitches,
        "appearance_count": appearances,
        "back_to_back_pitcher_count": len(last_day_pitchers & two_day_pitchers),
    }


def _bullpen_fatigue_score(workload: dict[str, Any]) -> float:
    pitches = _float(workload.get("pitch_count"), 0.0)
    appearances = _float(workload.get("appearance_count"), 0.0)
    back_to_back = _float(workload.get("back_to_back_pitcher_count"), 0.0)
    score = (pitches - 95.0) / 155.0 + (appearances - 6.0) / 12.0 + min(back_to_back, 3.0) * 0.08
    return round(_clamp(score, -0.25, 0.85), 6)


def _statsapi_team_lookup(paths) -> dict[str, Any]:
    rows = _load_jsonl_many(_latest_jsonl_dirs(paths.staged / "statsapi_teams", "statsapi_teams.jsonl"), "statsapi_teams.jsonl")
    by_id: dict[int, str] = {}
    by_key: dict[str, int] = {}
    for row in rows:
        if str(row.get("level") or "").upper() != "MLB":
            continue
        team_id = _int(row.get("team_id"))
        team = _team(row.get("team_abbreviation") or row.get("team_name"))
        if team_id and team:
            by_id[team_id] = team
            for value in (row.get("team_abbreviation"), row.get("team_name"), row.get("team_short_name"), row.get("club_name")):
                key = _compact_name_key(value)
                if key:
                    by_key[key] = team_id
    return {"by_id": by_id, "by_key": by_key}


def _statsapi_schedule_by_game(paths) -> dict[int, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for directory in _latest_jsonl_dirs(paths.staged / "statsapi_schedule", "statsapi_schedule.jsonl", all_dirs=True):
        rows.extend(_load_jsonl(directory / "statsapi_schedule.jsonl"))
    return {_int(row.get("game_pk")): row for row in rows if _int(row.get("game_pk"))}


def _latest_jsonl_dirs(root: Path, rows_name: str, *, all_dirs: bool = False) -> list[Path]:
    if not root.exists():
        return []
    candidates = sorted(root.glob(f"*/{rows_name}"), key=lambda item: (item.stat().st_mtime, item.parent.name))
    if not candidates:
        return []
    if all_dirs:
        return [path.parent for path in candidates]
    return [candidates[-1].parent]


def _pitch_count(stats: dict[str, Any]) -> float:
    for key in ("numberOfPitches", "pitchesThrown", "pitches"):
        value = stats.get(key)
        if value not in (None, ""):
            return _float(value, 0.0)
    return 0.0


def _outs_recorded(stats: dict[str, Any]) -> float:
    outs = _float(stats.get("outs"), 0.0)
    if outs:
        return outs
    innings = _str(stats.get("inningsPitched"))
    if "." in innings:
        whole, fraction = innings.split(".", 1)
        return _float(whole, 0.0) * 3 + _float(fraction[:1], 0.0)
    return _float(innings, 0.0) * 3


def _neutral_bullpens_from_rotowire(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        game_date = _str(row.get("game_date"))
        pitcher_team = _team(row.get("team_abbr"))
        hitter_team = _team(row.get("opponent_abbr"))
        key = (game_date, hitter_team, pitcher_team)
        if not all(key) or key in seen:
            continue
        seen.add(key)
        inputs.append(
            {
                "game_id": _canonical_game_id(game_date, hitter_team, pitcher_team),
                "hitter_team": hitter_team,
                "opponent": pitcher_team,
                "confidence": 0.20,
                "flags": ("bullpen_context_missing_source",),
            }
        )
    return inputs


def _neutral_bullpens_from_board(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        game_date = _str(row.get("game_date"))
        team = _team(row.get("player_team") or row.get("team"))
        opponent = _team(row.get("opponent") or row.get("opp"))
        key = (game_date, team, opponent)
        if not all(key) or key in seen:
            continue
        seen.add(key)
        inputs.append(
            {
                "game_id": _canonical_game_id(game_date, team, opponent),
                "hitter_team": team,
                "opponent": opponent,
                "confidence": 0.20,
                "flags": ("bullpen_context_missing_source",),
            }
        )
    return inputs


def _environment_inputs_from_rotowire(
    rows: list[dict[str, Any]],
    *,
    umpire_profiles: list[dict[str, Any]],
    ballpark_profiles: list[dict[str, Any]],
    wind_factors: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    umpires = {_name_key(row.get("umpire")): row for row in umpire_profiles}
    parks = {_team(row.get("team")): row for row in ballpark_profiles if _team(row.get("team"))}
    for row in rows:
        game_date = _str(row.get("game_date"))
        away = _team(row.get("away_team_abbr"))
        home = _team(row.get("home_team_abbr"))
        if not (game_date and away and home):
            continue
        umpire = _parse_umpire(row.get("umpire_text"), umpires=umpires)
        park = parks.get(home, {})
        for team, opponent in ((away, home), (home, away)):
            weather = _weather_scores(row.get("weather_text"), home_team=home, wind_factors=wind_factors)
            inputs.append(
                {
                    "game_id": _canonical_game_id(game_date, team, opponent),
                    "game_date": game_date,
                    "team": team,
                    "opponent": opponent,
                    "park_id": _str(park.get("park_id")),
                    "park_run_factor": _float(park.get("park_run_factor"), 1.0),
                    "park_hr_factor": _float(park.get("park_hr_factor"), 1.0),
                    "park_hit_factor": _float(park.get("park_hit_factor"), 1.0),
                    "park_extra_base_factor": _float(park.get("park_extra_base_factor"), 1.0),
                    "park_factor_confidence": _float(park.get("confidence"), 0.0),
                    "weather_run_score": weather["weather_run_score"],
                    "wind_carry_score": weather["wind_carry_score"],
                    "home_plate_umpire": umpire["home_plate_umpire"],
                    "umpire_era": umpire["umpire_era"],
                    "umpire_rating": umpire["umpire_rating"],
                    "umpire_run_score": umpire["umpire_run_score"],
                    "umpire_confidence": umpire["umpire_confidence"],
                    "confidence": _environment_confidence(umpire["umpire_confidence"], weather["confidence"], park),
                    "flags": tuple(flag for flag in (*weather["flags"], umpire["flag"]) if flag),
                }
            )
    return inputs


def _latest_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = _load_json(path)
    rows = payload.get("rows", [])
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _latest_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = _load_json(path)
    return payload if isinstance(payload, dict) else {}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _load_jsonl_many(directories: list[Path], filename: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for directory in directories:
        rows.extend(_load_jsonl(directory / filename))
    return rows


def _merge_context_rows(
    *,
    primary: list[dict[str, Any]],
    fallback: list[dict[str, Any]],
    key_fn,
) -> list[dict[str, Any]]:
    merged = list(primary)
    seen = {key for row in primary if (key := key_fn(row))}
    for row in fallback:
        key = key_fn(row)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def _lineup_context_key(row: dict[str, Any]) -> tuple[str, str, str] | None:
    game_date = _date_key(row.get("game_date"))
    team = _team(row.get("team_abbr") or row.get("team"))
    player = _compact_name_key(row.get("player_name") or row.get("display_name"))
    if not (game_date and team and player):
        return None
    return (game_date, team, player)


def _pitcher_context_key(row: dict[str, Any]) -> tuple[str, str] | None:
    game_date = _date_key(row.get("game_date"))
    team = _team(row.get("team_abbr") or row.get("team"))
    if not (game_date and team):
        return None
    return (game_date, team)


def _merge_dirs(primary: list[Path], fallback: list[Path]) -> list[Path]:
    merged = list(primary)
    for directory in fallback:
        if directory not in merged:
            merged.append(directory)
    return merged


def _load_context_jsonl_many(
    directories: list[Path],
    filename: str,
    *,
    game_start_index: dict[tuple[str, str, str], datetime],
    allow_reconstructed_pregame: bool = False,
    allow_historical_weather: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for directory in directories:
        manifest_path = directory / "normalize_manifest.json"
        manifest = _load_json(manifest_path) if manifest_path.exists() else {}
        fallback_snapshot_time = _snapshot_time_utc(manifest, manifest_path=manifest_path)
        manifest_reconstructed = _is_reconstructed_pregame_context(manifest)
        for row in _load_jsonl(directory / filename):
            if _context_row_available_for_replay(
                row,
                game_start_index=game_start_index,
                fallback_snapshot_time=fallback_snapshot_time,
                allow_reconstructed_pregame=allow_reconstructed_pregame,
                fallback_reconstructed_pregame=manifest_reconstructed,
                allow_historical_weather=allow_historical_weather,
            ):
                rows.append(row)
    return rows


def _context_row_available_for_replay(
    row: dict[str, Any],
    *,
    game_start_index: dict[tuple[str, str, str], datetime],
    fallback_snapshot_time: datetime | None,
    allow_reconstructed_pregame: bool = False,
    fallback_reconstructed_pregame: bool = False,
    allow_historical_weather: bool = False,
) -> bool:
    if _is_postgame_context(row) or _row_indicates_started(row):
        return False
    if allow_reconstructed_pregame and (
        fallback_reconstructed_pregame or _is_reconstructed_pregame_context(row)
    ):
        return True
    if allow_historical_weather and _is_historical_weather_context(row):
        return True

    snapshot_time = _snapshot_time_utc(row) or fallback_snapshot_time
    if not snapshot_time:
        return True

    game_key = _context_row_game_key(row)
    game_start = game_start_index.get(game_key) if game_key else None
    if game_start:
        return snapshot_time <= game_start

    row_date = _date_key(row.get("game_date") or row.get("official_date"))
    if row_date and snapshot_time.date().isoformat() > row_date:
        return False
    return True


def _row_indicates_started(row: dict[str, Any]) -> bool:
    value = row.get("game_started")
    if isinstance(value, bool):
        return value
    if _str(value).lower() in {"true", "1", "yes"}:
        return True
    slate_status = _str(row.get("slate_status") or row.get("status")).lower()
    return "has-started" in slate_status or "postgame" in slate_status


def _prop_game_start_index(prop_rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], datetime]:
    index: dict[tuple[str, str, str], datetime] = {}
    for row in prop_rows:
        game_date = _date_key(row.get("game_date"))
        start_time = _parse_utc_datetime(
            row.get("start_time_utc")
            or row.get("game_start_utc")
            or row.get("commence_time")
            or row.get("start_time")
        )
        team = _team(row.get("player_team") or row.get("team"))
        opponent = _team(row.get("opponent") or row.get("opp"))
        game_key = _game_key(game_date, team, opponent)
        if not (game_key and start_time):
            continue
        existing = index.get(game_key)
        index[game_key] = min(existing, start_time) if existing else start_time
    return index


def _latest_game_start_utc(prop_rows: list[dict[str, Any]], *, target_date: str) -> datetime | None:
    starts = [
        _parse_utc_datetime(
            row.get("start_time_utc")
            or row.get("game_start_utc")
            or row.get("commence_time")
            or row.get("start_time")
        )
        for row in prop_rows
        if _date_key(row.get("game_date")) == _date_key(target_date)
    ]
    valid_starts = [start for start in starts if start is not None]
    return max(valid_starts) if valid_starts else None


def _context_row_game_key(row: dict[str, Any]) -> tuple[str, str, str] | None:
    game_date = _date_key(row.get("game_date") or row.get("official_date"))
    away = _team(row.get("away_team_abbr") or row.get("away_team"))
    home = _team(row.get("home_team_abbr") or row.get("home_team"))
    if away and home:
        return _game_key(game_date, away, home)

    team = _team(row.get("team_abbr") or row.get("team") or row.get("player_team"))
    opponent = _team(row.get("opponent_abbr") or row.get("opponent") or row.get("opp"))
    return _game_key(game_date, team, opponent)


def _game_key(game_date: str, team: str, opponent: str) -> tuple[str, str, str] | None:
    if not (game_date and team and opponent):
        return None
    teams = tuple(sorted((team, opponent)))
    return (game_date, teams[0], teams[1])


def _snapshot_time_utc(manifest: dict[str, Any], *, manifest_path: Path | None = None) -> datetime | None:
    candidates: list[Any] = [
        manifest.get("pulled_at_utc"),
        manifest.get("fetched_at_utc"),
        manifest.get("generated_at_utc"),
        manifest.get("generated_at"),
        manifest.get("snapshot_id"),
        manifest.get("run_id"),
    ]
    if manifest_path is not None:
        candidates.extend([manifest_path.parent.name, manifest_path.name])

    for value in candidates:
        parsed = _parse_utc_datetime(value)
        if parsed:
            return parsed
    return None


def _parse_utc_datetime(value: Any) -> datetime | None:
    text = _str(value)
    if not text:
        return None

    compact = re.search(r"(20\d{2})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", text)
    if compact:
        try:
            return datetime(
                int(compact.group(1)),
                int(compact.group(2)),
                int(compact.group(3)),
                int(compact.group(4)),
                int(compact.group(5)),
                int(compact.group(6)),
                tzinfo=timezone.utc,
            )
        except ValueError:
            return None

    iso_text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _source_label(directories: list[Path], filename: str) -> str:
    paths = [str(directory / filename) for directory in directories]
    return paths[0] if len(paths) == 1 else json.dumps(paths)


def _json_rows_count(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if isinstance(rows, list):
        return len(rows)
    try:
        return int(payload.get("profile_count") or payload.get("row_count") or 0) if isinstance(payload, dict) else 0
    except (TypeError, ValueError):
        return 0


def _combined_context_source(
    *,
    lineup_dirs: list[Path],
    pitcher_dirs: list[Path],
    environment_dirs: list[Path],
) -> str:
    labels = {
        _context_source_name(directory)
        for directories in (lineup_dirs, pitcher_dirs, environment_dirs)
        for directory in directories
    }
    labels.discard("")
    if not labels:
        return "missing"
    return "+".join(sorted(labels))


def _dirs_include_source(directories: list[Path], source_name: str) -> bool:
    return any(_context_source_name(directory) == source_name for directory in directories)


def _reconstructed_pregame_sources(directories: list[Path]) -> set[str]:
    sources: set[str] = set()
    for directory in directories:
        manifest_path = directory / "normalize_manifest.json"
        manifest = _load_json(manifest_path) if manifest_path.exists() else {}
        if _is_reconstructed_pregame_context(manifest):
            source = _context_source_name(directory)
            if source:
                sources.add(source)
    return sources


def _context_source_name(directory: Path) -> str:
    parts = directory.parts
    for source in (
        "rotowire_context",
        "covers_weather",
        "wunderground_history_weather",
        "baseball_reference_boxscore_context",
        "espn_game_context",
    ):
        if source in parts:
            return source
    return directory.parent.name


def _canonical_game_id(game_date: Any, team: Any, opponent: Any) -> str:
    return f"{_str(game_date)}|{_team(team)}|{_team(opponent)}"


def _projected_pa(slot: int | None) -> float:
    if slot is None:
        return 4.05
    values = {1: 4.75, 2: 4.65, 3: 4.55, 4: 4.45, 5: 4.35, 6: 4.20, 7: 4.05, 8: 3.90, 9: 3.75}
    return values.get(slot, 4.05)


def _protection_score(slot: int | None) -> float:
    if slot in {2, 3, 4, 5}:
        return 0.20
    if slot in {1, 6}:
        return 0.08
    if slot in {8, 9}:
        return -0.12
    return 0.0


def _run_context_score(slot: int | None) -> float:
    if slot in {1, 2, 3}:
        return 0.24
    if slot in {4, 5}:
        return 0.08
    if slot in {8, 9}:
        return -0.10
    return 0.0


def _rbi_context_score(slot: int | None) -> float:
    if slot in {3, 4, 5}:
        return 0.24
    if slot in {6, 7}:
        return 0.08
    if slot in {1, 9}:
        return -0.08
    return 0.0


def _parse_era(value: Any) -> float | None:
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s+ERA", _str(value), flags=re.IGNORECASE)
    if not match:
        return None
    return _float(match.group(1), 0.0)


def _weather_scores(
    value: Any,
    *,
    home_team: str = "",
    wind_factors: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = _str(value)
    temp_match = re.search(r"(\d+(?:\.\d+)?)\s*°", text)
    wind_match = re.search(r"Wind\s+(\d+(?:\.\d+)?)\s+mph(?:\s+([A-Z-]+))?", text, flags=re.IGNORECASE)
    temp = _float(temp_match.group(1), 70.0) if temp_match else 70.0
    wind = _float(wind_match.group(1), 0.0) if wind_match else 0.0
    direction = (wind_match.group(2).upper() if wind_match and wind_match.group(2) else "")
    temp_score = _clamp((temp - 70.0) / 180.0, -0.05, 0.05)
    wind_factor_scores = _wind_factor_scores(
        wind_speed=wind,
        direction=direction,
        home_team=home_team,
        wind_factors=wind_factors or {},
    )
    weather_run_score = _clamp(temp_score + wind_factor_scores["run_score"], -0.08, 0.08)
    wind_carry_score = wind_factor_scores["hr_score"]
    if not wind_factor_scores["available"] and wind >= 12.0:
        wind_carry_score = 0.018 if direction not in {"R-L", "L-R"} else 0.006
    flags: list[str] = []
    if not text:
        flags.append("weather_context_missing")
    flags.extend(wind_factor_scores["flags"])
    return {
        "weather_run_score": round(weather_run_score, 6),
        "wind_carry_score": round(wind_carry_score, 6),
        "confidence": _clamp(0.70 if wind_factor_scores["available"] else (0.55 if text else 0.0), 0.0, 1.0),
        "flags": tuple(flags),
    }


def _wind_factor_scores(
    *,
    wind_speed: float,
    direction: str,
    home_team: str,
    wind_factors: dict[str, Any],
) -> dict[str, Any]:
    classification = _wind_direction_class(direction)
    orientation_applied = False
    if not classification:
        classification = _park_orientation_wind_direction_class(
            direction=direction,
            home_team=home_team,
            wind_factors=wind_factors,
        )
        orientation_applied = bool(classification)
    bucket = _wind_bucket(wind_speed)
    flags: list[str] = []
    if not wind_factors:
        return {"available": False, "run_score": 0.0, "hr_score": 0.0, "flags": ()}
    if not classification or not bucket:
        return {
            "available": False,
            "run_score": 0.0,
            "hr_score": 0.0,
            "flags": ("wind_factor_direction_unmapped",),
        }

    league_lookup = _league_wind_lookup(wind_factors)
    class_key, direction_key = classification
    run_row = league_lookup.get(("runs_per_game", class_key, bucket, direction_key))
    hr_row = league_lookup.get(("hr_per_game", class_key, bucket, direction_key))
    if not (run_row and hr_row):
        return {
            "available": False,
            "run_score": 0.0,
            "hr_score": 0.0,
            "flags": ("wind_factor_bucket_missing",),
        }

    run_score = _clamp(_float(run_row.get("delta"), 0.0) / 18.0, -0.045, 0.045)
    hr_score = _clamp(_float(hr_row.get("delta"), 0.0) / 4.0, -0.040, 0.040)
    park_score = _park_wind_score(
        wind_factors=wind_factors,
        home_team=home_team,
        wind_speed=wind_speed,
        direction_class=class_key,
    )
    hr_score = _clamp(hr_score + park_score, -0.080, 0.080)
    flags.append("wind_factor_applied")
    if orientation_applied:
        flags.append("park_orientation_wind_direction_applied")
    if park_score:
        flags.append("park_wind_factor_applied")
    return {
        "available": True,
        "run_score": run_score,
        "hr_score": hr_score,
        "flags": tuple(flags),
    }


def _league_wind_lookup(wind_factors: dict[str, Any]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    rows = wind_factors.get("league_wind_effects", [])
    if not isinstance(rows, list):
        return {}
    lookup: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        lookup[
            (
                _str(row.get("metric")),
                _str(row.get("wind_class")),
                _str(row.get("wind_bucket")),
                _str(row.get("direction_key")),
            )
        ] = row
    return lookup


def _park_wind_score(
    *,
    wind_factors: dict[str, Any],
    home_team: str,
    wind_speed: float,
    direction_class: str,
) -> float:
    team = _team(home_team)
    rows = wind_factors.get("park_wind_effects", [])
    if not team or not isinstance(rows, list):
        return 0.0
    park = next((row for row in rows if isinstance(row, dict) and _team(row.get("team")) == team), None)
    if not park:
        return 0.0
    if wind_speed <= 5:
        speed_weight = 0.30
    elif wind_speed <= 10:
        speed_weight = 0.65
    else:
        speed_weight = 1.0
    direction_weight = 0.55 if direction_class == "across" else 1.0
    return round(_clamp(_float(park.get("net_hr_wind"), 0.0) / 900.0, -0.07, 0.07) * speed_weight * direction_weight, 6)


def _park_orientation_wind_direction_class(
    *,
    direction: str,
    home_team: str,
    wind_factors: dict[str, Any],
) -> tuple[str, str] | None:
    wind_degrees = _compass_degrees(direction)
    if wind_degrees is None:
        return None
    park = _park_wind_profile(wind_factors=wind_factors, home_team=home_team)
    if not park:
        return None
    candidates = [
        (park.get("wind_out_from_direction"), ("out", "to_center")),
        (park.get("wind_in_from_direction"), ("in", "from_center")),
        (park.get("crosswind_lf_to_rf_from_direction"), ("across", "left_to_right")),
        (park.get("crosswind_rf_to_lf_from_direction"), ("across", "right_to_left")),
    ]
    best: tuple[float, tuple[str, str]] | None = None
    for source_direction, classification in candidates:
        source_degrees = _compass_degrees(source_direction)
        if source_degrees is None:
            continue
        distance = _angular_distance(wind_degrees, source_degrees)
        if best is None or distance < best[0]:
            best = (distance, classification)
    if best is None or best[0] > 45.0:
        return None
    return best[1]


def _park_wind_profile(*, wind_factors: dict[str, Any], home_team: str) -> dict[str, Any]:
    team = _team(home_team)
    rows = wind_factors.get("park_wind_effects", [])
    if not team or not isinstance(rows, list):
        return {}
    return next((row for row in rows if isinstance(row, dict) and _team(row.get("team")) == team), {})


def _wind_direction_class(direction: str) -> tuple[str, str] | None:
    normalized = direction.upper().replace(" ", "")
    if normalized in {"OUT", "TOCENTER", "CENTER"}:
        return ("out", "to_center")
    if normalized in {"IN", "FROMCENTER", "TOWARDHOME", "HOME"}:
        return ("in", "from_center")
    if normalized in {"L-R", "LR", "LEFT-RIGHT", "LEFTTORIGHT"}:
        return ("across", "left_to_right")
    if normalized in {"R-L", "RL", "RIGHT-LEFT", "RIGHTTOLEFT"}:
        return ("across", "right_to_left")
    if normalized in {"TOLEFT", "OUTLEFT"}:
        return ("out", "to_left")
    if normalized in {"TORIGHT", "OUTRIGHT"}:
        return ("out", "to_right")
    if normalized in {"FROMLEFT", "INLEFT"}:
        return ("in", "from_left")
    if normalized in {"FROMRIGHT", "INRIGHT"}:
        return ("in", "from_right")
    return None


def _compass_degrees(direction: Any) -> float | None:
    normalized = re.sub(r"[^A-Z]", "", str(direction or "").upper())
    value = _COMPASS_BEARINGS.get(normalized)
    return float(value) if value is not None else None


def _angular_distance(left: float, right: float) -> float:
    distance = abs(float(left) - float(right)) % 360.0
    return min(distance, 360.0 - distance)


def _wind_bucket(wind_speed: float) -> str:
    if wind_speed <= 5:
        return "0 to 5 mph"
    if wind_speed <= 10:
        return "6 to 10 mph"
    if wind_speed <= 15:
        return "11 to 15 mph"
    return "16+ mph"


def _parse_umpire(value: Any, *, umpires: dict[str, dict[str, Any]]) -> dict[str, Any]:
    text = _str(value)
    name_match = re.search(r"Umpire:\s*(.*?)\s+\d+(?:\.\d+)?\s+R/G", text, flags=re.IGNORECASE)
    runs_match = re.search(r"(\d+(?:\.\d+)?)\s+R/G", text, flags=re.IGNORECASE)
    name = name_match.group(1).strip() if name_match else ""
    if not name:
        plain_name_match = re.search(r"Umpire:\s*([^|,]+)", text, flags=re.IGNORECASE)
        name = " ".join(plain_name_match.group(1).split()) if plain_name_match else ""
    profile = umpires.get(_name_key(name), {})
    if profile:
        return {
            "home_plate_umpire": _str(profile.get("umpire")) or name,
            "umpire_era": _float(profile.get("era"), 0.0),
            "umpire_rating": _str(profile.get("rating")),
            "umpire_run_score": _float(profile.get("umpire_run_score"), 0.0),
            "umpire_confidence": _float(profile.get("confidence"), 0.0),
            "flag": "",
        }
    if runs_match:
        runs_per_game = _float(runs_match.group(1), 8.7)
        return {
            "home_plate_umpire": name,
            "umpire_era": 0.0,
            "umpire_rating": "",
            "umpire_run_score": round(_clamp((runs_per_game - 8.7) / 18.0, -0.06, 0.06), 6),
            "umpire_confidence": 0.45,
            "flag": "umpire_profile_missing",
        }
    return {
        "home_plate_umpire": name,
        "umpire_era": 0.0,
        "umpire_rating": "",
        "umpire_run_score": 0.0,
        "umpire_confidence": 0.0,
        "flag": "umpire_context_missing",
    }


def _environment_confidence(umpire_confidence: float, weather_confidence: float, park: dict[str, Any]) -> float:
    park_confidence = _float(park.get("confidence"), 0.0)
    values = [umpire_confidence, weather_confidence]
    if park_confidence:
        values.append(park_confidence)
    return round(sum(values) / len(values), 6) if values else 0.0


def _filter_rows_by_date(rows: list[dict[str, Any]], game_date: str | None) -> list[dict[str, Any]]:
    if not game_date:
        return rows
    return [row for row in rows if str(row.get("game_date") or "") == game_date]


def _write_csv(path: Path, rows: list[dict[str, Any]], *, columns: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in columns})


def _missing_context_rate(rows: list[dict[str, Any]], *, missing_prefixes: tuple[str, ...] | None = None) -> float | None:
    if not rows:
        return None
    missing = sum(1 for row in rows if _has_missing_context(row, missing_prefixes=missing_prefixes))
    return round(missing / len(rows), 6)


def _has_missing_context(row: dict[str, Any], *, missing_prefixes: tuple[str, ...] | None) -> bool:
    flags = row.get("missing_context_flags") or ()
    if not missing_prefixes:
        return bool(flags)
    return any(str(flag).startswith(missing_prefixes) for flag in flags)


def _missing_context_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        flags = row.get("missing_context_flags") or ()
        for flag in flags:
            counts[str(flag)] = counts.get(str(flag), 0) + 1
    return dict(sorted(counts.items()))


def _flag_count(rows: list[dict[str, Any]], flag_name: str) -> int:
    return sum(1 for row in rows for flag in (row.get("missing_context_flags") or ()) if str(flag) == flag_name)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _copy_latest(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _csv_value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True)
    return value


def _str(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return canonical_team_abbr(value)


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _date_key(value: Any) -> str:
    match = re.search(r"(20\d{2})-?(\d{2})-?(\d{2})", _str(value))
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else ""


def _parse_date(value: Any) -> date | None:
    key = _date_key(value)
    if not key:
        return None
    try:
        return date.fromisoformat(key)
    except ValueError:
        return None


def _name_key(value: Any) -> str:
    return " ".join(_str(value).casefold().replace(".", "").split())


def _compact_name_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _str(value).casefold())
    ascii_text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", ascii_text)


def _tuple_flags(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _score_metric(value: Any, *, center: float, scale: float) -> float:
    number = _float(value, 0.0)
    if number == 0.0:
        return 0.0
    return _clamp((number - center) / scale, -1.0, 1.0)


def _mean(values: tuple[float, ...]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
