"""Runtime artifact writer for MLB StatsAPI schedule/team context.

This context layer is report-only. It attaches StatsAPI game identifiers,
venue, status, and team IDs to the current PrizePicks board so later replay,
boxscore, weather, and ballpark joins can use one canonical game identity.
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

from mlb.domain.teams import canonical_team_abbr, compact_team_key
from mlb.runtime.engine_inputs import _load_json
from mlb.runtime.market_context import latest_engine_board_path
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.runtime.results import RuntimeCommandResult

STATSAPI_CONTEXT_VERSION = "statsapi_schedule_context_v0"

STATSAPI_CONTEXT_COLUMNS = (
    "run_id",
    "source_projection_id",
    "event_id",
    "player_id",
    "player_name",
    "player_team",
    "opponent",
    "game_date",
    "market",
    "line",
    "tier",
    "statsapi_context_available",
    "game_pk",
    "statsapi_game_status",
    "statsapi_game_date_utc",
    "official_date",
    "venue_id",
    "venue_name",
    "team_id",
    "opponent_id",
    "is_home",
    "home_team_id",
    "home_team_name",
    "away_team_id",
    "away_team_name",
    "series_description",
    "statsapi_schedule_source_dir",
    "statsapi_team_source_dir",
    "statsapi_context_flags",
)


def build_statsapi_context_result(
    *,
    engine_board_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    game_date: str | None = None,
) -> RuntimeCommandResult:
    manifest = build_statsapi_context_artifacts(
        engine_board_path=engine_board_path,
        root=root,
        run_id=run_id,
        game_date=game_date,
    )
    lines = [
        "Built MLB StatsAPI context artifacts:",
        f"  run_id: {manifest['run_id']}",
        f"  source_run_id: {manifest['source_run_id']}",
        f"  schedule_source_row_count: {manifest['schedule_source_row_count']}",
        f"  team_source_row_count: {manifest['team_source_row_count']}",
        f"  row_count: {manifest['row_count']}",
        f"  coverage_rate: {manifest['coverage_rate']}",
        f"  csv: {manifest['csv_path']}",
        f"  json: {manifest['json_path']}",
        f"  manifest: {manifest['manifest_path']}",
    ]
    return RuntimeCommandResult(name="build_statsapi_context", payload=manifest, lines=tuple(lines))


def build_statsapi_context_artifacts(
    *,
    engine_board_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    game_date: str | None = None,
) -> dict[str, Any]:
    paths = ensure_mlb_dirs(root)
    source_path = engine_board_path or latest_engine_board_path(root=root)
    engine_board = _load_json(source_path)
    source_run_id = str(engine_board.get("run_id") or source_path.parent.name)
    source_rows = [row for row in engine_board.get("rows", []) if isinstance(row, dict)]
    filtered_rows = _filter_rows_by_date(source_rows, game_date)
    resolved_run_id = run_id or game_date or source_run_id
    dates = sorted({str(row.get("game_date") or "") for row in filtered_rows if row.get("game_date")})

    schedule_source_dirs = _statsapi_schedule_dirs_by_date(paths.staged / "statsapi_schedule", dates)
    team_source_dir = _latest_source_dir(paths.staged / "statsapi_teams", "statsapi_teams.jsonl")
    schedule_rows = _load_schedule_rows(schedule_source_dirs)
    team_rows = _load_jsonl(team_source_dir / "statsapi_teams.jsonl") if team_source_dir else []
    team_index = _index_teams(team_rows)
    schedule_index = _index_schedule(schedule_rows, team_index)

    rows = [
        _statsapi_context_row(
            row,
            run_id=resolved_run_id,
            context=_match_schedule(row, schedule_index, team_index),
            schedule_sources=schedule_source_dirs,
            team_source_dir=team_source_dir,
        )
        for row in filtered_rows
    ]

    output_dir = paths.features / "statsapi_context" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "statsapi_context.csv"
    json_path = output_dir / "statsapi_context.json"
    manifest_path = output_dir / "statsapi_context_manifest.json"
    _write_csv(csv_path, rows)
    json_path.write_text(
        json.dumps(
            {
                "run_id": resolved_run_id,
                "source_run_id": source_run_id,
                "statsapi_context_version": STATSAPI_CONTEXT_VERSION,
                "row_count": len(rows),
                "rows": rows,
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
        "dates": dates,
        "source_row_count": len(filtered_rows),
        "row_count": len(rows),
        "statsapi_context_version": STATSAPI_CONTEXT_VERSION,
        "schedule_source_dirs_by_date": {
            date: str(path) for date, path in sorted(schedule_source_dirs.items())
        },
        "schedule_source_row_count": len(schedule_rows),
        "team_source_dir": str(team_source_dir) if team_source_dir else "",
        "team_source_row_count": len(team_rows),
        "coverage_rate": _true_rate(row["statsapi_context_available"] for row in rows),
        "coverage_by_market": _true_rate_by_key(rows, key="market", value="statsapi_context_available"),
        "coverage_by_tier": _true_rate_by_key(rows, key="tier", value="statsapi_context_available"),
        "statsapi_context_flag_counts": _flag_counts(row["statsapi_context_flags"] for row in rows),
        "venue_counts": _counts(row["venue_name"] for row in rows if row["statsapi_context_available"]),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
        "latest_csv_path": str(paths.features / "statsapi_context" / "latest.csv"),
        "latest_json_path": str(paths.features / "statsapi_context" / "latest.json"),
        "latest_manifest_path": str(paths.features / "statsapi_context" / "latest_manifest.json"),
        "columns": list(STATSAPI_CONTEXT_COLUMNS),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _copy_latest(csv_path, paths.features / "statsapi_context" / "latest.csv")
    _copy_latest(json_path, paths.features / "statsapi_context" / "latest.json")
    _copy_latest(manifest_path, paths.features / "statsapi_context" / "latest_manifest.json")
    return manifest


def _statsapi_context_row(
    row: dict[str, Any],
    *,
    run_id: str,
    context: dict[str, Any] | None,
    schedule_sources: dict[str, Path],
    team_source_dir: Path | None,
) -> dict[str, Any]:
    flags: list[str] = []
    game_date = str(row.get("game_date") or "")
    schedule_source_dir = schedule_sources.get(game_date)
    if not schedule_source_dir:
        flags.append("no_statsapi_schedule_snapshot_for_date")
    if not team_source_dir:
        flags.append("no_statsapi_team_snapshot_available")
    if not context:
        flags.append("missing_statsapi_game_context")
        context = {}
    else:
        flags.append(str(context.get("_match_flag") or "statsapi_game_match"))

    return {
        "run_id": run_id,
        "source_projection_id": str(row.get("source_projection_id") or ""),
        "event_id": str(row.get("event_id") or ""),
        "player_id": str(row.get("player_id") or ""),
        "player_name": str(row.get("player_name") or ""),
        "player_team": str(row.get("player_team") or ""),
        "opponent": str(row.get("opponent") or ""),
        "game_date": game_date,
        "market": str(row.get("market") or ""),
        "line": _float(row.get("line")),
        "tier": str(row.get("tier") or "STANDARD").upper() or "STANDARD",
        "statsapi_context_available": bool(context.get("game_pk")),
        "game_pk": _int(context.get("game_pk")),
        "statsapi_game_status": str(context.get("status") or ""),
        "statsapi_game_date_utc": str(context.get("game_date") or ""),
        "official_date": str(context.get("official_date") or ""),
        "venue_id": _int(context.get("venue_id")),
        "venue_name": str(context.get("venue_name") or ""),
        "team_id": _int(context.get("_team_id")),
        "opponent_id": _int(context.get("_opponent_id")),
        "is_home": bool(context.get("_is_home")) if context.get("game_pk") else False,
        "home_team_id": _int(context.get("home_team_id")),
        "home_team_name": str(context.get("home_team_name") or ""),
        "away_team_id": _int(context.get("away_team_id")),
        "away_team_name": str(context.get("away_team_name") or ""),
        "series_description": str(context.get("series_description") or ""),
        "statsapi_schedule_source_dir": str(schedule_source_dir) if schedule_source_dir else "",
        "statsapi_team_source_dir": str(team_source_dir) if team_source_dir else "",
        "statsapi_context_flags": tuple(flag for flag in flags if flag),
    }


def _statsapi_schedule_dirs_by_date(root: Path, dates: list[str]) -> dict[str, Path]:
    if not root.exists() or not dates:
        return {}
    candidates: dict[str, list[Path]] = {date: [] for date in dates}
    for rows_path in root.glob("*/statsapi_schedule.jsonl"):
        rows = _load_jsonl(rows_path)
        row_dates = {str(row.get("official_date") or "") for row in rows}
        for date in dates:
            if date in row_dates:
                candidates.setdefault(date, []).append(rows_path.parent)
    return {
        date: sorted(paths, key=lambda path: (path.stat().st_mtime, path.name))[-1]
        for date, paths in candidates.items()
        if paths
    }


def _latest_source_dir(root: Path, rows_name: str) -> Path | None:
    if not root.exists():
        return None
    candidates = [path.parent for path in root.glob(f"*/{rows_name}")]
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: (path.stat().st_mtime, path.name))[-1]


def _load_schedule_rows(source_dirs: dict[str, Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_dir in sorted(set(source_dirs.values()), key=lambda path: str(path)):
        rows.extend(_load_jsonl(source_dir / "statsapi_schedule.jsonl"))
    return rows


def _index_teams(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("level") or "").upper() != "MLB":
            continue
        for value in (
            row.get("team_abbreviation"),
            row.get("team_name"),
            row.get("team_short_name"),
            row.get("club_name"),
        ):
            key = _team_key(value)
            if key:
                index[key] = row
    return index


def _index_schedule(
    rows: list[dict[str, Any]],
    team_index: dict[str, dict[str, Any]],
) -> dict[tuple[str, int, int], dict[str, Any]]:
    index: dict[tuple[str, int, int], dict[str, Any]] = {}
    for row in rows:
        date = str(row.get("official_date") or "")
        away_id = _int(row.get("away_team_id"))
        home_id = _int(row.get("home_team_id"))
        if date and away_id and home_id:
            index[(date, away_id, home_id)] = row
            index[(date, home_id, away_id)] = row
        # Defensive fallback in case a source omitted IDs but retained names.
        away_team = team_index.get(_team_key(row.get("away_team_name")))
        home_team = team_index.get(_team_key(row.get("home_team_name")))
        away_fallback_id = _int(away_team.get("team_id") if away_team else None)
        home_fallback_id = _int(home_team.get("team_id") if home_team else None)
        if date and away_fallback_id and home_fallback_id:
            index.setdefault((date, away_fallback_id, home_fallback_id), row)
            index.setdefault((date, home_fallback_id, away_fallback_id), row)
    return index


def _match_schedule(
    row: dict[str, Any],
    schedule_index: dict[tuple[str, int, int], dict[str, Any]],
    team_index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    date = str(row.get("game_date") or "")
    team = team_index.get(_team_key(row.get("player_team")))
    opponent = team_index.get(_team_key(row.get("opponent")))
    team_id = _int(team.get("team_id") if team else None)
    opponent_id = _int(opponent.get("team_id") if opponent else None)
    if not date or not team_id or not opponent_id:
        return None
    schedule = schedule_index.get((date, team_id, opponent_id))
    if not schedule:
        return None
    home_id = _int(schedule.get("home_team_id"))
    away_id = _int(schedule.get("away_team_id"))
    is_home = team_id == home_id
    if team_id not in {home_id, away_id} or opponent_id not in {home_id, away_id}:
        return None
    return {
        **schedule,
        "_team_id": team_id,
        "_opponent_id": opponent_id,
        "_is_home": is_home,
        "_match_flag": "date_team_opponent_statsapi_match",
    }


def _filter_rows_by_date(rows: list[dict[str, Any]], game_date: str | None) -> list[dict[str, Any]]:
    if not game_date:
        return rows
    return [row for row in rows if str(row.get("game_date") or "") == game_date]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=STATSAPI_CONTEXT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in STATSAPI_CONTEXT_COLUMNS})


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _copy_latest(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _csv_value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True)
    return value


def _team_key(value: Any) -> str:
    return canonical_team_abbr(value) or compact_team_key(value)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, AttributeError):
        return 0


def _true_rate(values) -> float | None:
    collected = [bool(value) for value in values]
    if not collected:
        return None
    return round(sum(1 for value in collected if value) / len(collected), 6)


def _true_rate_by_key(rows: list[dict[str, Any]], *, key: str, value: str) -> dict[str, float]:
    grouped: dict[str, list[bool]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key) or ""), []).append(bool(row.get(value)))
    return {
        group: round(sum(1 for item in values if item) / len(values), 6)
        for group, values in sorted(grouped.items())
        if values
    }


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _flag_counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        for flag in _tuple_flags(value):
            counts[flag] = counts.get(flag, 0) + 1
    return dict(sorted(counts.items()))


def _tuple_flags(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("["):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return (value,)
            return _tuple_flags(decoded)
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),)
