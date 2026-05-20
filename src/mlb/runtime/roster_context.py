"""Runtime artifact writer for MLB StatsAPI roster context.

This layer attaches durable player identity to PrizePicks board rows. It is
still report-only: the probability engine can read these fields later, but this
module only stages player IDs, handedness, roster status, and position with
coverage diagnostics.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

from mlb.domain.teams import canonical_team_abbr, compact_team_key
from mlb.runtime.engine_inputs import _load_json
from mlb.runtime.market_context import latest_engine_board_path
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.runtime.results import RuntimeCommandResult
from mlb.runtime.season_gamelogs import load_season_gamelog_rows

ROSTER_CONTEXT_VERSION = "statsapi_roster_context_v0"
MIN_FULL_SLATE_ROSTER_ROWS = 200

ROSTER_CONTEXT_COLUMNS = (
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
    "roster_context_available",
    "statsapi_person_id",
    "statsapi_roster_team_id",
    "statsapi_roster_team_abbreviation",
    "statsapi_roster_team_name",
    "statsapi_roster_level",
    "statsapi_parent_org_id",
    "statsapi_parent_org_name",
    "statsapi_player_position",
    "statsapi_bats",
    "statsapi_throws",
    "statsapi_roster_status",
    "statsapi_roster_source_dir",
    "roster_context_flags",
)


def build_roster_context_result(
    *,
    engine_board_path: Path | None = None,
    statsapi_context_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    game_date: str | None = None,
) -> RuntimeCommandResult:
    manifest = build_roster_context_artifacts(
        engine_board_path=engine_board_path,
        statsapi_context_path=statsapi_context_path,
        root=root,
        run_id=run_id,
        game_date=game_date,
    )
    lines = [
        "Built MLB roster context artifacts:",
        f"  run_id: {manifest['run_id']}",
        f"  source_run_id: {manifest['source_run_id']}",
        f"  roster_source_row_count: {manifest['roster_source_row_count']}",
        f"  row_count: {manifest['row_count']}",
        f"  coverage_rate: {manifest['coverage_rate']}",
        f"  csv: {manifest['csv_path']}",
        f"  json: {manifest['json_path']}",
        f"  manifest: {manifest['manifest_path']}",
    ]
    return RuntimeCommandResult(name="build_roster_context", payload=manifest, lines=tuple(lines))


def build_roster_context_artifacts(
    *,
    engine_board_path: Path | None = None,
    statsapi_context_path: Path | None = None,
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

    roster_source = _select_roster_source(paths.staged, game_date=game_date)
    roster_source_dir = roster_source["path"] if roster_source else None
    roster_rows = _load_jsonl(roster_source_dir / f"{roster_source_dir.parent.name}.jsonl") if roster_source_dir else []
    history_identity_rows = _load_history_identity_rows(paths, game_date=game_date)
    statsapi_rows = _load_context_rows(statsapi_context_path)
    roster_index = _index_rosters(roster_rows)
    history_identity_index = _index_history_identity(history_identity_rows, game_date=game_date)

    rows = [
        _roster_context_row(
            row,
            run_id=resolved_run_id,
            roster=_match_roster(
                row,
                roster_index,
                statsapi_rows.get(_matchup_key(row)),
                history_identity_index=history_identity_index,
            ),
            roster_source_dir=roster_source_dir,
        )
        for row in filtered_rows
    ]

    output_dir = paths.features / "roster_context" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "roster_context.csv"
    json_path = output_dir / "roster_context.json"
    manifest_path = output_dir / "roster_context_manifest.json"
    _write_csv(csv_path, rows)
    json_path.write_text(
        json.dumps(
            {
                "run_id": resolved_run_id,
                "source_run_id": source_run_id,
                "roster_context_version": ROSTER_CONTEXT_VERSION,
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
        "statsapi_context_path": str(statsapi_context_path) if statsapi_context_path else "",
        "game_date": game_date or "",
        "source_row_count": len(filtered_rows),
        "row_count": len(rows),
        "roster_context_version": ROSTER_CONTEXT_VERSION,
        "roster_source_dir": str(roster_source_dir) if roster_source_dir else "",
        "roster_source_selection": (
            str(roster_source.get("selection_label") or "") if roster_source else _source_selection_label(None, game_date=game_date)
        ),
        "roster_source_type": str(roster_source.get("source_type") or "") if roster_source else "",
        "roster_source_snapshot_date": str(roster_source.get("snapshot_date") or "") if roster_source else "",
        "roster_source_is_post_date_identity_fallback": False,
        "roster_source_row_count": len(roster_rows),
        "history_identity_source_row_count": len(history_identity_rows),
        "coverage_rate": _true_rate(row["roster_context_available"] for row in rows),
        "coverage_by_market": _true_rate_by_key(rows, key="market", value="roster_context_available"),
        "coverage_by_tier": _true_rate_by_key(rows, key="tier", value="roster_context_available"),
        "roster_context_flag_counts": _flag_counts(row["roster_context_flags"] for row in rows),
        "position_counts": _counts(row["statsapi_player_position"] for row in rows if row["roster_context_available"]),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
        "latest_csv_path": str(paths.features / "roster_context" / "latest.csv"),
        "latest_json_path": str(paths.features / "roster_context" / "latest.json"),
        "latest_manifest_path": str(paths.features / "roster_context" / "latest_manifest.json"),
        "columns": list(ROSTER_CONTEXT_COLUMNS),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _copy_latest(csv_path, paths.features / "roster_context" / "latest.csv")
    _copy_latest(json_path, paths.features / "roster_context" / "latest.json")
    _copy_latest(manifest_path, paths.features / "roster_context" / "latest_manifest.json")
    return manifest


def _roster_context_row(
    row: dict[str, Any],
    *,
    run_id: str,
    roster: dict[str, Any] | None,
    roster_source_dir: Path | None,
) -> dict[str, Any]:
    flags: list[str] = []
    if roster_source_dir is None:
        flags.append("no_statsapi_roster_snapshot_available")
    if not roster:
        flags.append("missing_statsapi_roster_context")
        roster = {}
    else:
        flags.append(str(roster.get("_match_flag") or "statsapi_roster_match"))
    return {
        "run_id": run_id,
        "source_projection_id": str(row.get("source_projection_id") or ""),
        "event_id": str(row.get("event_id") or ""),
        "player_id": str(row.get("player_id") or ""),
        "player_name": str(row.get("player_name") or ""),
        "player_team": str(row.get("player_team") or ""),
        "opponent": str(row.get("opponent") or ""),
        "game_date": str(row.get("game_date") or ""),
        "market": str(row.get("market") or ""),
        "line": _float(row.get("line")),
        "tier": str(row.get("tier") or "STANDARD").upper() or "STANDARD",
        "roster_context_available": bool(roster.get("person_id")),
        "statsapi_person_id": _int(roster.get("person_id")),
        "statsapi_roster_team_id": _int(roster.get("team_id")),
        "statsapi_roster_team_abbreviation": str(roster.get("team_abbreviation") or ""),
        "statsapi_roster_team_name": str(roster.get("team_name") or ""),
        "statsapi_roster_level": str(roster.get("level") or ""),
        "statsapi_parent_org_id": _int(roster.get("parent_org_id")),
        "statsapi_parent_org_name": str(roster.get("parent_org_name") or ""),
        "statsapi_player_position": str(roster.get("primary_position") or ""),
        "statsapi_bats": str(roster.get("bats") or ""),
        "statsapi_throws": str(roster.get("throws") or ""),
        "statsapi_roster_status": str(roster.get("status") or ""),
        "statsapi_roster_source_dir": str(roster_source_dir) if roster_source_dir else "",
        "roster_context_flags": tuple(flag for flag in flags if flag),
    }


def _index_rosters(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_name_team_id: dict[tuple[str, int], dict[str, Any]] = {}
    by_name_team_key: dict[tuple[str, str], dict[str, Any]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        name_key = _name_key(row.get("player_name"))
        if not name_key:
            continue
        team_id = _int(row.get("team_id"))
        if team_id:
            by_name_team_id[(name_key, team_id)] = row
        for team_key in _team_keys(row):
            by_name_team_key[(name_key, team_key)] = row
        by_name.setdefault(name_key, []).append(row)
    return {
        "by_name_team_id": by_name_team_id,
        "by_name_team_key": by_name_team_key,
        "by_name": by_name,
    }


def _load_history_identity_rows(paths, *, game_date: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend(load_season_gamelog_rows(root=paths.repo_root))
    for root, rows_name in (
        (paths.staged / "statsapi_player_gamelog", "statsapi_player_gamelog.jsonl"),
        (paths.staged / "statsapi_player_gamelogs_bulk", "statsapi_player_gamelogs_bulk.jsonl"),
        (paths.staged / "statsapi_boxscores_bulk", "statsapi_boxscores_bulk.jsonl"),
        (paths.staged / "espn_player_gamelog", "espn_player_gamelog.jsonl"),
        (paths.staged / "espn_player_gamelogs_bulk", "espn_player_gamelogs_bulk.jsonl"),
    ):
        if not root.exists():
            continue
        for path in sorted(root.glob(f"*/{rows_name}"), key=lambda item: (item.stat().st_mtime, item.parent.name)):
            rows.extend(_load_jsonl(path))
    return [_history_identity_row(row) for row in rows if _is_prior_identity_row(row, game_date=game_date)]


def _is_prior_identity_row(row: dict[str, Any], *, game_date: str | None) -> bool:
    if not _int(row.get("person_id")) or not _name_key(row.get("player_name")):
        return False
    if not game_date:
        return True
    row_date = _date_key(row.get("official_date") or row.get("game_date"))
    target_date = _date_key(game_date)
    return bool(row_date and target_date and row_date < target_date)


def _history_identity_row(row: dict[str, Any]) -> dict[str, Any]:
    team_abbreviation = str(row.get("team_abbreviation") or row.get("player_team") or "").upper()
    team_name = str(row.get("team_name") or "")
    if not team_abbreviation and team_name:
        team_abbreviation = canonical_team_abbr(team_name) or ""
    return {
        "person_id": _int(row.get("person_id")),
        "team_id": _int(row.get("team_id")),
        "team_name": team_name,
        "team_abbreviation": team_abbreviation,
        "team_short_name": str(row.get("team_short_name") or row.get("club_name") or team_name),
        "club_name": str(row.get("club_name") or row.get("team_short_name") or team_name),
        "level": "MLB",
        "parent_org_id": _int(row.get("parent_org_id")),
        "parent_org_name": str(row.get("parent_org_name") or ""),
        "player_name": str(row.get("player_name") or ""),
        "primary_position": str(row.get("primary_position") or row.get("player_position") or row.get("position") or ""),
        "status": str(row.get("status") or "PriorHistoryIdentity"),
        "bats": str(row.get("bats") or ""),
        "throws": str(row.get("throws") or ""),
        "_history_identity_date": _date_key(row.get("official_date") or row.get("game_date")),
    }


def _index_history_identity(rows: list[dict[str, Any]], *, game_date: str | None) -> dict[str, Any]:
    del game_date
    by_name_team_id: dict[tuple[str, int], dict[str, Any]] = {}
    by_name_team_key: dict[tuple[str, str], dict[str, Any]] = {}
    by_name_person: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        name_key = _name_key(row.get("player_name"))
        person_id = _int(row.get("person_id"))
        if not name_key or not person_id:
            continue
        team_id = _int(row.get("team_id"))
        if team_id:
            _set_latest_identity(by_name_team_id, (name_key, team_id), row)
        for team_key in _team_keys(row):
            _set_latest_identity(by_name_team_key, (name_key, team_key), row)
        _set_latest_identity(by_name_person, (name_key, person_id), row)
    by_name: dict[str, list[dict[str, Any]]] = {}
    for (name_key, _person_id), row in by_name_person.items():
        by_name.setdefault(name_key, []).append(row)
    return {
        "by_name_team_id": by_name_team_id,
        "by_name_team_key": by_name_team_key,
        "by_name": by_name,
    }


def _set_latest_identity(target: dict[Any, dict[str, Any]], key: Any, row: dict[str, Any]) -> None:
    current = target.get(key)
    if current is None or str(row.get("_history_identity_date") or "") >= str(current.get("_history_identity_date") or ""):
        target[key] = row


def _match_roster(
    row: dict[str, Any],
    roster_index: dict[str, Any],
    statsapi_context: dict[str, Any] | None,
    *,
    history_identity_index: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    name_key = _name_key(row.get("player_name"))
    if not name_key:
        return None
    team_id = _int(statsapi_context.get("team_id")) if statsapi_context else 0
    if team_id:
        roster = roster_index["by_name_team_id"].get((name_key, team_id))
        if roster:
            return {**roster, "_match_flag": "player_name_statsapi_team_id_match"}

    board_team_key = _team_key(row.get("player_team"))
    if board_team_key:
        roster = roster_index["by_name_team_key"].get((name_key, board_team_key))
        if roster:
            return {**roster, "_match_flag": "player_name_team_abbreviation_match"}

    candidates = roster_index["by_name"].get(name_key, [])
    if len(candidates) == 1:
        return {**candidates[0], "_match_flag": "unique_player_name_match"}
    history_match = _match_history_identity(row, history_identity_index or {}, team_id=team_id)
    if history_match:
        return history_match
    return None


def _match_history_identity(
    row: dict[str, Any],
    history_identity_index: dict[str, Any],
    *,
    team_id: int,
) -> dict[str, Any] | None:
    name_key = _name_key(row.get("player_name"))
    if not name_key:
        return None
    if team_id:
        match = history_identity_index.get("by_name_team_id", {}).get((name_key, team_id))
        if match:
            return {**match, "_match_flag": "player_name_prior_history_team_id_match"}

    board_team_key = _team_key(row.get("player_team"))
    if board_team_key:
        match = history_identity_index.get("by_name_team_key", {}).get((name_key, board_team_key))
        if match:
            return {**match, "_match_flag": "player_name_prior_history_team_match"}

    candidates = history_identity_index.get("by_name", {}).get(name_key, [])
    if len(candidates) == 1:
        return {**candidates[0], "_match_flag": "unique_player_name_prior_history_match"}
    return None


def _select_roster_source(staged_root: Path, *, game_date: str | None) -> dict[str, Any] | None:
    candidates = _roster_source_candidates(staged_root)
    if not candidates:
        return None
    if not game_date:
        return _with_selection_label(
            sorted(candidates, key=_roster_candidate_sort_key)[-1],
            "latest_available_source",
        )

    target = _date_key(game_date)
    eligible = [
        candidate for candidate in candidates if candidate["snapshot_date"] and candidate["snapshot_date"] <= target
    ]
    usable_eligible = [
        candidate for candidate in eligible if int(candidate["row_count"]) >= MIN_FULL_SLATE_ROSTER_ROWS
    ]
    if usable_eligible:
        selected = sorted(usable_eligible, key=_roster_candidate_sort_key)[-1]
        return _with_selection_label(selected, _source_selection_label(selected["path"], game_date=game_date))

    if eligible:
        selected = sorted(eligible, key=_roster_candidate_sort_key)[-1]
        return _with_selection_label(selected, _source_selection_label(selected["path"], game_date=game_date))
    return None


def _roster_source_candidates(staged_root: Path) -> list[dict[str, Any]]:
    specs = (
        ("statsapi_rosters_bulk", "statsapi_rosters_bulk.jsonl"),
        ("statsapi_rosters", "statsapi_rosters.jsonl"),
    )
    candidates: list[dict[str, Any]] = []
    for source_type, rows_name in specs:
        root = staged_root / source_type
        if not root.exists():
            continue
        for rows_path in root.glob(f"*/{rows_name}"):
            snapshot_date = _snapshot_date_key(rows_path.parent)
            candidates.append(
                {
                    "path": rows_path.parent,
                    "source_type": source_type,
                    "snapshot_date": snapshot_date,
                    "row_count": _jsonl_line_count(rows_path),
                    "mtime": rows_path.parent.stat().st_mtime,
                    "name": rows_path.parent.name,
                }
            )
    return candidates


def _with_selection_label(
    candidate: dict[str, Any],
    selection_label: str,
    *,
    post_date_identity_fallback: bool = False,
) -> dict[str, Any]:
    selected = dict(candidate)
    selected["selection_label"] = selection_label
    selected["post_date_identity_fallback"] = post_date_identity_fallback
    return selected


def _roster_candidate_sort_key(candidate: dict[str, Any]) -> tuple[str, int, float, str]:
    source_priority = 1 if candidate["source_type"] == "statsapi_rosters_bulk" else 0
    return (
        str(candidate["snapshot_date"]),
        source_priority,
        float(candidate["mtime"]),
        str(candidate["name"]),
    )


def _source_dir_for_date(root: Path, rows_name: str, *, game_date: str | None) -> Path | None:
    if not root.exists():
        return None
    candidates = [path.parent for path in root.glob(f"*/{rows_name}")]
    if not candidates:
        return None
    if game_date:
        target = _date_key(game_date)
        eligible = [
            path
            for path in candidates
            if (snapshot_date := _snapshot_date_key(path)) and snapshot_date <= target
        ]
        if not eligible:
            return None
        return sorted(eligible, key=lambda path: (_snapshot_date_key(path), path.stat().st_mtime, path.name))[-1]
    return sorted(candidates, key=lambda path: (path.stat().st_mtime, path.name))[-1]


def _source_selection_label(source_dir: Path | None, *, game_date: str | None) -> str:
    if source_dir is None:
        return "missing_date_safe_source" if game_date else "missing_source"
    if not game_date:
        return "latest_available_source"
    source_date = _snapshot_date_key(source_dir)
    if source_date == _date_key(game_date):
        return "date_matched_source"
    return "latest_on_or_before_date_source"


def _snapshot_date_key(path: Path) -> str:
    for candidate in (path.name, path.parent.name):
        match = re.search(r"(20\d{6})", candidate)
        if match:
            return _date_key(match.group(1))
    return ""


def _date_key(value: Any) -> str:
    text = str(value or "")
    match = re.search(r"(20\d{2})-?(\d{2})-?(\d{2})", text)
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else ""


def _load_context_rows(path: Path | None) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    payload = _load_json(path)
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        return {}
    return {_matchup_key(row): row for row in rows if isinstance(row, dict)}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
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


def _jsonl_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            count += 1
    return count


def _filter_rows_by_date(rows: list[dict[str, Any]], game_date: str | None) -> list[dict[str, Any]]:
    if not game_date:
        return rows
    return [row for row in rows if str(row.get("game_date") or "") == game_date]


def _team_keys(row: dict[str, Any]) -> set[str]:
    keys = {
        _team_key(row.get("team_abbreviation")),
        _team_key(row.get("team_name")),
        _team_key(row.get("team_short_name")),
        _team_key(row.get("club_name")),
    }
    return {key for key in keys if key}


def _team_key(value: Any) -> str:
    return canonical_team_abbr(value) or compact_team_key(value)


def _name_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def _matchup_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("source_projection_id") or "").strip(),
        str(row.get("market") or "").strip(),
        _line_key(row.get("line")),
        str(row.get("tier") or "STANDARD").strip().upper() or "STANDARD",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=ROSTER_CONTEXT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in ROSTER_CONTEXT_COLUMNS})


def _copy_latest(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _true_rate(values) -> float | None:
    collected = [bool(value) for value in values]
    if not collected:
        return None
    return round(sum(1 for value in collected if value) / len(collected), 6)


def _true_rate_by_key(rows: list[dict[str, Any]], *, key: str, value: str) -> dict[str, float | None]:
    groups: dict[str, list[bool]] = {}
    for row in rows:
        groups.setdefault(str(row.get(key) or ""), []).append(bool(row.get(value)))
    return {group: _true_rate(values) for group, values in sorted(groups.items())}


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


def _csv_value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True)
    return value


def _line_key(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
