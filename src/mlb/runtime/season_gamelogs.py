"""Running MLB season game-log store."""

from __future__ import annotations

import csv
import json
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

from mlb.domain.teams import canonical_team_abbr
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.runtime.results import RuntimeCommandResult

SEASON_GAMELOG_VERSION = "atlas_mlb_season_gamelogs_v0"

SEASON_GAMELOG_COLUMNS = (
    "source",
    "season",
    "group",
    "game_date",
    "game_pk",
    "game_id",
    "espn_event_id",
    "person_id",
    "espn_player_id",
    "player_name",
    "player_team",
    "player_position",
    "team_id",
    "team_name",
    "team_abbreviation",
    "opponent_id",
    "opponent_name",
    "opponent_abbreviation",
    "is_home",
    "is_pitching_starter",
    "stat",
    "batting_stats",
    "pitching_stats",
)

_SOURCE_PRIORITY = {
    "statsapi_boxscores_bulk": 50,
    "statsapi_boxscore": 50,
    "statsapi_player_gamelogs_bulk": 40,
    "statsapi_player_gamelog": 40,
    "espn_player_gamelogs_bulk": 30,
    "espn_player_gamelog": 30,
    "espn_game_context": 20,
}


def refresh_season_gamelogs_result(
    *,
    season: int = 2026,
    through_date: str | None = None,
    root: Path | None = None,
) -> RuntimeCommandResult:
    manifest = refresh_season_gamelogs(season=season, through_date=through_date, root=root)
    lines = [
        "Refreshed MLB season gamelog store:",
        f"  season: {manifest['season']}",
        f"  through_date: {manifest['through_date'] or 'all staged dates'}",
        f"  row_count: {manifest['row_count']}",
        f"  dates: {manifest['date_min'] or 'none'} to {manifest['date_max'] or 'none'}",
        f"  jsonl: {manifest['jsonl_path']}",
        f"  csv: {manifest['csv_path']}",
    ]
    return RuntimeCommandResult(name="refresh_season_gamelogs", payload=manifest, lines=tuple(lines))


def refresh_season_gamelogs(
    *,
    season: int = 2026,
    through_date: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    paths = ensure_mlb_dirs(root)
    rows: list[dict[str, Any]] = []
    rows.extend(_load_staged_gamelog_rows(paths=paths, season=season))
    rows.extend(_load_staged_boxscore_rows(paths=paths, season=season))
    return write_season_gamelogs(rows, season=season, through_date=through_date, root=root)


def append_boxscore_rows_to_season_gamelogs(
    *,
    boxscore_rows: list[dict[str, Any]],
    season: int,
    root: Path | None = None,
) -> dict[str, Any]:
    paths = ensure_mlb_dirs(root)
    rows = _load_existing_rows(paths=paths, season=season)
    rows.extend(_rows_from_boxscores(boxscore_rows, season=season, source="statsapi_boxscores_bulk"))
    return write_season_gamelogs(rows, season=season, root=root)


def load_season_gamelog_rows(*, root: Path | None = None, season: int | None = None) -> list[dict[str, Any]]:
    paths = ensure_mlb_dirs(root)
    candidates = []
    if season:
        candidates.append(paths.data_root / "season_gamelogs" / f"mlb_{season}_gamelogs.jsonl")
    candidates.append(paths.data_root / "season_gamelogs" / "latest.jsonl")
    for path in candidates:
        if path.exists():
            return _load_jsonl(path)
    return []


def write_season_gamelogs(
    rows: list[dict[str, Any]],
    *,
    season: int,
    through_date: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    paths = ensure_mlb_dirs(root)
    output_dir = paths.data_root / "season_gamelogs"
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_rows = [_normalize_row(row, season=season) for row in rows]
    if through_date:
        normalized_rows = [row for row in normalized_rows if str(row.get("game_date") or "") <= through_date]
    resolved_rows = _dedupe_rows(normalized_rows)
    resolved_rows = sorted(
        resolved_rows,
        key=lambda row: (
            str(row.get("game_date") or ""),
            str(row.get("player_name") or ""),
            str(row.get("group") or ""),
            int(row.get("game_pk") or 0),
            str(row.get("espn_event_id") or ""),
        ),
    )
    jsonl_path = output_dir / f"mlb_{season}_gamelogs.jsonl"
    csv_path = output_dir / f"mlb_{season}_gamelogs.csv"
    manifest_path = output_dir / f"mlb_{season}_gamelogs_manifest.json"
    _write_jsonl(jsonl_path, resolved_rows)
    _write_csv(csv_path, resolved_rows)

    dates = sorted({str(row.get("game_date") or "") for row in resolved_rows if row.get("game_date")})
    manifest = {
        "season_gamelog_version": SEASON_GAMELOG_VERSION,
        "season": season,
        "through_date": through_date or "",
        "row_count": len(resolved_rows),
        "date_min": dates[0] if dates else "",
        "date_max": dates[-1] if dates else "",
        "source_counts": _counts(str(row.get("source") or "") for row in resolved_rows),
        "group_counts": _counts(str(row.get("group") or "") for row in resolved_rows),
        "jsonl_path": str(jsonl_path),
        "csv_path": str(csv_path),
        "manifest_path": str(manifest_path),
        "latest_jsonl_path": str(output_dir / "latest.jsonl"),
        "latest_csv_path": str(output_dir / "latest.csv"),
        "latest_manifest_path": str(output_dir / "latest_manifest.json"),
        "columns": list(SEASON_GAMELOG_COLUMNS),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _copy_latest(jsonl_path, output_dir / "latest.jsonl")
    _copy_latest(csv_path, output_dir / "latest.csv")
    _copy_latest(manifest_path, output_dir / "latest_manifest.json")
    return manifest


def _load_existing_rows(*, paths, season: int) -> list[dict[str, Any]]:
    path = paths.data_root / "season_gamelogs" / f"mlb_{season}_gamelogs.jsonl"
    return _load_jsonl(path)


def _load_staged_gamelog_rows(*, paths, season: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for root, filename, source in (
        (paths.staged / "statsapi_player_gamelog", "statsapi_player_gamelog.jsonl", "statsapi_player_gamelog"),
        (
            paths.staged / "statsapi_player_gamelogs_bulk",
            "statsapi_player_gamelogs_bulk.jsonl",
            "statsapi_player_gamelogs_bulk",
        ),
        (paths.staged / "espn_player_gamelog", "espn_player_gamelog.jsonl", "espn_player_gamelog"),
        (
            paths.staged / "espn_player_gamelogs_bulk",
            "espn_player_gamelogs_bulk.jsonl",
            "espn_player_gamelogs_bulk",
        ),
    ):
        if not root.exists():
            continue
        for path in sorted(root.glob(f"*/{filename}"), key=lambda item: (item.stat().st_mtime, item.parent.name)):
            for row in _load_jsonl(path):
                if _int(row.get("season")) in {0, season}:
                    rows.append({**row, "source": row.get("source") or source})
    return rows


def _load_staged_boxscore_rows(*, paths, season: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for root, filename, source in (
        (paths.staged / "statsapi_boxscores_bulk", "statsapi_boxscores_bulk.jsonl", "statsapi_boxscores_bulk"),
        (paths.staged / "statsapi_boxscore", "statsapi_boxscore.jsonl", "statsapi_boxscore"),
    ):
        if not root.exists():
            continue
        for path in sorted(root.glob(f"*/{filename}"), key=lambda item: (item.stat().st_mtime, item.parent.name)):
            rows.extend(_rows_from_boxscores(_load_jsonl(path), season=season, source=source))
    return rows


def _rows_from_boxscores(rows: list[dict[str, Any]], *, season: int, source: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        batting = row.get("batting_stats") if isinstance(row.get("batting_stats"), dict) else {}
        pitching = row.get("pitching_stats") if isinstance(row.get("pitching_stats"), dict) else {}
        base = {
            "source": source,
            "season": season,
            "game_date": str(row.get("official_date") or row.get("game_date") or ""),
            "game_pk": _int(row.get("game_pk")),
            "game_id": str(row.get("game_id") or row.get("game_pk") or ""),
            "person_id": _int(row.get("person_id")),
            "espn_player_id": str(row.get("espn_player_id") or ""),
            "player_name": str(row.get("player_name") or ""),
            "player_team": canonical_team_abbr(row.get("team_abbreviation") or row.get("team_name")),
            "player_position": str(row.get("position") or row.get("player_position") or ""),
            "team_id": _int(row.get("team_id")),
            "team_name": str(row.get("team_name") or ""),
            "team_abbreviation": canonical_team_abbr(row.get("team_abbreviation") or row.get("team_name")),
            "opponent_id": _int(row.get("opponent_id")),
            "opponent_name": str(row.get("opponent_name") or ""),
            "opponent_abbreviation": canonical_team_abbr(row.get("opponent_abbreviation") or row.get("opponent_name")),
            "is_home": bool(row.get("is_home")),
        }
        if batting:
            out.append({**base, "group": "hitting", "stat": batting, "batting_stats": batting, "pitching_stats": {}})
        if pitching:
            out.append(
                {
                    **base,
                    "group": "pitching",
                    "stat": pitching,
                    "batting_stats": {},
                    "pitching_stats": pitching,
                    "is_pitching_starter": bool(row.get("is_pitching_starter")),
                }
            )
    return out


def _normalize_row(row: dict[str, Any], *, season: int) -> dict[str, Any]:
    group = str(row.get("group") or "").lower()
    stat = row.get("stat") if isinstance(row.get("stat"), dict) else {}
    batting = row.get("batting_stats") if isinstance(row.get("batting_stats"), dict) else {}
    pitching = row.get("pitching_stats") if isinstance(row.get("pitching_stats"), dict) else {}
    if not group:
        group = "pitching" if pitching else "hitting"
    if not stat:
        stat = pitching if group == "pitching" else batting
    if group == "hitting" and not batting:
        batting = stat
    if group == "pitching" and not pitching:
        pitching = stat
    team_abbr = canonical_team_abbr(row.get("team_abbreviation") or row.get("player_team") or row.get("team_name"))
    opponent_abbr = canonical_team_abbr(row.get("opponent_abbreviation") or row.get("opponent") or row.get("opponent_name"))
    return {
        "source": str(row.get("source") or ""),
        "season": _int(row.get("season")) or season,
        "group": group,
        "game_date": str(row.get("game_date") or row.get("official_date") or ""),
        "game_pk": _int(row.get("game_pk")),
        "game_id": str(row.get("game_id") or row.get("game_pk") or ""),
        "espn_event_id": str(row.get("espn_event_id") or ""),
        "person_id": _int(row.get("person_id")),
        "espn_player_id": str(row.get("espn_player_id") or ""),
        "player_name": str(row.get("player_name") or ""),
        "player_team": team_abbr,
        "player_position": str(row.get("player_position") or ""),
        "team_id": _int(row.get("team_id")),
        "team_name": str(row.get("team_name") or ""),
        "team_abbreviation": team_abbr,
        "opponent_id": _int(row.get("opponent_id")),
        "opponent_name": str(row.get("opponent_name") or ""),
        "opponent_abbreviation": opponent_abbr,
        "is_home": bool(row.get("is_home")),
        "is_pitching_starter": bool(row.get("is_pitching_starter")),
        "stat": stat,
        "batting_stats": batting,
        "pitching_stats": pitching,
    }


def _dedupe_rows(rows: Any) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = (
            str(row.get("game_date") or ""),
            str(row.get("group") or ""),
            _name_key(row.get("player_name")),
            str(row.get("team_abbreviation") or row.get("player_team") or ""),
            str(row.get("opponent_abbreviation") or ""),
        )
        if not all(key[:3]):
            continue
        existing = by_key.get(key)
        if existing is None or _source_priority(row) >= _source_priority(existing):
            by_key[key] = row
    return list(by_key.values())


def _source_priority(row: dict[str, Any]) -> int:
    return _SOURCE_PRIORITY.get(str(row.get("source") or ""), 0)


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


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=SEASON_GAMELOG_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in SEASON_GAMELOG_COLUMNS})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True)
    return value


def _copy_latest(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _name_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
