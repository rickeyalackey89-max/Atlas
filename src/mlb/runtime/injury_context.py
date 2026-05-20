"""Runtime artifact writer for MLB injury context.

The injury context is intentionally report-only at this stage. It attaches the
latest staged ESPN injury rows to the current PrizePicks board so runs can
audit injury coverage before probability penalties are introduced.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

from mlb.domain.teams import canonical_team_abbr
from mlb.runtime.engine_inputs import _load_json
from mlb.runtime.market_context import latest_engine_board_path
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.runtime.results import RuntimeCommandResult

INJURY_CONTEXT_VERSION = "espn_injury_context_v0"

INJURY_CONTEXT_COLUMNS = (
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
    "injury_context_available",
    "injury_status",
    "injury_report_date",
    "injury_player_id",
    "injury_position",
    "injury_risk_score",
    "injury_context_flags",
)


def build_injury_context_result(
    *,
    engine_board_path: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    game_date: str | None = None,
) -> RuntimeCommandResult:
    manifest = build_injury_context_artifacts(
        engine_board_path=engine_board_path,
        root=root,
        run_id=run_id,
        game_date=game_date,
    )
    lines = [
        "Built MLB injury context artifacts:",
        f"  run_id: {manifest['run_id']}",
        f"  source_run_id: {manifest['source_run_id']}",
        f"  injury_source_row_count: {manifest['injury_source_row_count']}",
        f"  row_count: {manifest['row_count']}",
        f"  coverage_rate: {manifest['coverage_rate']}",
        f"  csv: {manifest['csv_path']}",
        f"  json: {manifest['json_path']}",
        f"  manifest: {manifest['manifest_path']}",
    ]
    return RuntimeCommandResult(name="build_injury_context", payload=manifest, lines=tuple(lines))


def build_injury_context_artifacts(
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
    injury_source_dir = _injury_source_dir(paths.staged / "injuries", game_date=game_date)
    injury_rows = _load_injury_rows(injury_source_dir)
    injury_index = _index_injuries(injury_rows)

    rows = [
        _injury_context_row(
            row,
            run_id=resolved_run_id,
            injury_row=_match_injury(row, injury_index),
            source_available=injury_source_dir is not None,
        )
        for row in filtered_rows
    ]

    output_dir = paths.features / "injury_context" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "injury_context.csv"
    json_path = output_dir / "injury_context.json"
    manifest_path = output_dir / "injury_context_manifest.json"
    _write_csv(csv_path, rows)
    json_path.write_text(
        json.dumps(
            {
                "run_id": resolved_run_id,
                "source_run_id": source_run_id,
                "injury_context_version": INJURY_CONTEXT_VERSION,
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
        "source_row_count": len(filtered_rows),
        "row_count": len(rows),
        "injury_context_version": INJURY_CONTEXT_VERSION,
        "injury_source_dir": str(injury_source_dir) if injury_source_dir else "",
        "injury_source_selection": _source_selection_label(injury_source_dir, game_date=game_date),
        "injury_source_row_count": len(injury_rows),
        "coverage_rate": _true_rate(row["injury_context_available"] for row in rows),
        "coverage_by_market": _true_rate_by_key(rows, key="market", value="injury_context_available"),
        "coverage_by_tier": _true_rate_by_key(rows, key="tier", value="injury_context_available"),
        "injury_status_counts": _counts(row["injury_status"] for row in rows if row["injury_context_available"]),
        "injury_context_flag_counts": _flag_counts(row["injury_context_flags"] for row in rows),
        "injury_risk_score_mean": _mean(
            row["injury_risk_score"] for row in rows if row["injury_context_available"]
        ),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
        "latest_csv_path": str(paths.features / "injury_context" / "latest.csv"),
        "latest_json_path": str(paths.features / "injury_context" / "latest.json"),
        "latest_manifest_path": str(paths.features / "injury_context" / "latest_manifest.json"),
        "columns": list(INJURY_CONTEXT_COLUMNS),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _copy_latest(csv_path, paths.features / "injury_context" / "latest.csv")
    _copy_latest(json_path, paths.features / "injury_context" / "latest.json")
    _copy_latest(manifest_path, paths.features / "injury_context" / "latest_manifest.json")
    return manifest


def _injury_context_row(
    row: dict[str, Any],
    *,
    run_id: str,
    injury_row: dict[str, Any] | None,
    source_available: bool,
) -> dict[str, Any]:
    flags: list[str] = []
    if not source_available:
        flags.append("no_injury_snapshot_available")
    if not injury_row:
        flags.append("no_injury_listing")
    else:
        flags.append(str(injury_row.get("_match_flag") or "injury_context_match"))
        flags.append("player_on_injury_report")
        flags.append(_status_flag(injury_row.get("status")))

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
        "injury_context_available": injury_row is not None,
        "injury_status": str(injury_row.get("status") or "") if injury_row else "",
        "injury_report_date": str(injury_row.get("report_date") or "") if injury_row else "",
        "injury_player_id": str(injury_row.get("player_id") or "") if injury_row else "",
        "injury_position": str(injury_row.get("position") or "") if injury_row else "",
        "injury_risk_score": _injury_risk_score(injury_row.get("status")) if injury_row else 0.0,
        "injury_context_flags": tuple(flag for flag in flags if flag),
    }


def _injury_source_dir(root: Path, *, game_date: str | None) -> Path | None:
    if not root.exists():
        return None
    candidates = [path.parent for path in root.glob("*/injuries.jsonl")]
    if not candidates:
        return None
    if not game_date:
        return sorted(candidates, key=lambda path: path.stat().st_mtime)[-1]

    target = _date_key(game_date)
    eligible = [
        path
        for path in candidates
        if (snapshot_date := _snapshot_date_key(path)) and snapshot_date <= target
    ]
    if not eligible:
        return None
    return sorted(eligible, key=lambda path: _date_safe_injury_sort_key(path, target=target))[-1]


def _load_injury_rows(source_dir: Path | None) -> list[dict[str, Any]]:
    if source_dir is None:
        return []
    return _load_jsonl(source_dir / "injuries.jsonl")


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
    manifest_path = path / "normalize_manifest.json"
    if not manifest_path.exists():
        manifest_path = path / "manifest.json"
    if manifest_path.exists():
        manifest = _load_json(manifest_path)
        for key in ("game_date", "snapshot_id", "run_id"):
            value = _date_key(manifest.get(key))
            if value:
                return value
    return ""


def _date_safe_injury_sort_key(path: Path, *, target: str) -> tuple[str, int, int, float, str]:
    snapshot_date = _snapshot_date_key(path)
    return (
        snapshot_date,
        1 if snapshot_date == target else 0,
        1 if "cbs_injuries" in path.name.lower() else 0,
        path.stat().st_mtime,
        path.name,
    )


def _date_key(value: Any) -> str:
    text = str(value or "")
    match = re.search(r"(20\d{2})-?(\d{2})-?(\d{2})", text)
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else ""


def _index_injuries(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_player_team: dict[tuple[str, str], dict[str, Any]] = {}
    by_player: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        player_key = _player_key(row.get("player_name"))
        team_key = _team_key(row.get("team"))
        if not player_key:
            continue
        enriched = dict(row)
        by_player.setdefault(player_key, []).append(enriched)
        if team_key:
            by_player_team[(player_key, team_key)] = enriched
    return {"by_player_team": by_player_team, "by_player": by_player}


def _match_injury(row: dict[str, Any], index: dict[str, Any]) -> dict[str, Any] | None:
    player_key = _player_key(row.get("player_name"))
    team_key = _team_key(row.get("player_team"))
    if not player_key:
        return None
    by_player_team = index.get("by_player_team", {})
    exact = by_player_team.get((player_key, team_key))
    if exact:
        return {**exact, "_match_flag": "exact_player_team_injury_match"}
    matches = index.get("by_player", {}).get(player_key, [])
    if len(matches) == 1:
        return {**matches[0], "_match_flag": "player_only_injury_match"}
    return None


def _filter_rows_by_date(rows: list[dict[str, Any]], game_date: str | None) -> list[dict[str, Any]]:
    if not game_date:
        return rows
    return [row for row in rows if str(row.get("game_date") or "") == game_date]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=INJURY_CONTEXT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in INJURY_CONTEXT_COLUMNS})


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


def _player_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _team_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", canonical_team_abbr(value).lower())


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _status_flag(value: Any) -> str:
    status = str(value or "").strip().lower()
    if not status:
        return "injury_status_unknown"
    if any(token in status for token in ("out", "injured", "il", "10-day", "15-day", "60-day")):
        return "injury_status_unavailable_or_il"
    if any(token in status for token in ("day", "questionable", "probable", "doubtful")):
        return "injury_status_uncertain"
    return "injury_status_reported"


def _injury_risk_score(value: Any) -> float:
    flag = _status_flag(value)
    if flag == "injury_status_unavailable_or_il":
        return 1.0
    if flag == "injury_status_uncertain":
        return 0.45
    if flag == "injury_status_reported":
        return 0.25
    return 0.0


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


def _mean(values) -> float | None:
    collected = [float(value) for value in values]
    if not collected:
        return None
    return round(sum(collected) / len(collected), 6)
