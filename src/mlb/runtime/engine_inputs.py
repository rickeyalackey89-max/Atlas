"""Engine input publishers for Atlas MLB.

These publishers create internal model-read surfaces from normalized source
contracts. They do not publish externally.
"""

from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - defensive fallback for stripped Python installs
    ZoneInfo = None  # type: ignore[assignment]

from mlb.runtime.paths import ensure_mlb_dirs
from mlb.runtime.results import RuntimeCommandResult

ENGINE_BOARD_COLUMNS = (
    "snapshot_id",
    "source_projection_id",
    "event_id",
    "league",
    "game_date",
    "start_time_utc",
    "player_id",
    "player_name",
    "player_team",
    "opponent",
    "market",
    "source_market",
    "line",
    "tier",
    "status",
    "player_position",
    "is_live",
    "is_combo",
    "updated_at",
    "pulled_at_utc",
)


def publish_engine_board_result(
    *,
    normalized_dir: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    game_date: str | None = None,
    include_all_dates: bool = False,
    exclude_started_games: bool = False,
) -> RuntimeCommandResult:
    published = publish_engine_board(
        normalized_dir=normalized_dir,
        root=root,
        run_id=run_id,
        game_date=game_date,
        include_all_dates=include_all_dates,
        exclude_started_games=exclude_started_games,
    )
    lines = [
        "Published MLB engine board inputs:",
        f"  run_id: {published['run_id']}",
        f"  game_date_filter: {published['game_date_filter'] or 'all'}",
        f"  row_count: {published['row_count']}",
        f"  source_row_count: {published['source_row_count']}",
        f"  csv: {published['csv_path']}",
        f"  json: {published['json_path']}",
        f"  manifest: {published['manifest_path']}",
    ]
    return RuntimeCommandResult(name="publish_engine_board", payload=published, lines=tuple(lines))


def publish_engine_board(
    *,
    normalized_dir: Path | None = None,
    root: Path | None = None,
    run_id: str | None = None,
    game_date: str | None = None,
    include_all_dates: bool = False,
    exclude_started_games: bool = False,
    as_of_utc: datetime | None = None,
) -> dict[str, Any]:
    paths = ensure_mlb_dirs(root)
    source_dir = normalized_dir or latest_normalized_board_dir(root=root)
    normalize_manifest = _load_json(source_dir / "normalize_manifest.json")
    rows = _load_jsonl(source_dir / "normalized_board.jsonl")
    target_game_date = "" if include_all_dates else (game_date or _infer_target_game_date(rows, normalize_manifest))
    date_filtered_rows = (
        rows
        if include_all_dates
        else [row for row in rows if str(row.get("game_date") or "") == str(target_game_date)]
    )
    resolved_as_of_utc = as_of_utc or datetime.now(timezone.utc)
    started_filtered_rows = (
        _filter_unstarted_rows(date_filtered_rows, as_of_utc=resolved_as_of_utc)
        if exclude_started_games
        else date_filtered_rows
    )
    sorted_rows = sorted(
        started_filtered_rows,
        key=lambda row: (
            str(row.get("game_date") or ""),
            str(row.get("start_time_utc") or ""),
            str(row.get("player_name") or ""),
            str(row.get("market") or ""),
            float(row.get("line") or 0.0),
            str(row.get("tier") or ""),
        ),
    )
    resolved_run_id = run_id or str(normalize_manifest.get("run_id") or source_dir.name)
    output_dir = paths.staged / "engine_board" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "engine_board.csv"
    json_path = output_dir / "engine_board.json"
    manifest_path = output_dir / "engine_board_manifest.json"
    _write_csv(csv_path, sorted_rows)
    json_payload = {
        "run_id": resolved_run_id,
        "source": "prizepicks",
        "snapshot_id": normalize_manifest.get("snapshot_id", ""),
        "source_row_count": len(rows),
        "row_count": len(sorted_rows),
        "game_date_filter": target_game_date,
        "date_filter_policy": "all_dates" if include_all_dates else "target_game_date",
        "date_counts_before_filter": _counts_by(rows, "game_date"),
        "date_counts_after_filter": _counts_by(sorted_rows, "game_date"),
        "exclude_started_games": exclude_started_games,
        "as_of_utc": resolved_as_of_utc.isoformat().replace("+00:00", "Z"),
        "dropped_started_or_live_count": len(date_filtered_rows) - len(sorted_rows),
        "rows": sorted_rows,
    }
    json_path.write_text(json.dumps(json_payload, indent=2, sort_keys=True), encoding="utf-8")
    manifest = {
        "run_id": resolved_run_id,
        "source": "prizepicks",
        "snapshot_id": normalize_manifest.get("snapshot_id", ""),
        "normalized_dir": str(source_dir),
        "normalized_manifest_path": str(source_dir / "normalize_manifest.json"),
        "source_row_count": len(rows),
        "row_count": len(sorted_rows),
        "game_date_filter": target_game_date,
        "date_filter_policy": "all_dates" if include_all_dates else "target_game_date",
        "date_counts_before_filter": _counts_by(rows, "game_date"),
        "date_counts_after_filter": _counts_by(sorted_rows, "game_date"),
        "exclude_started_games": exclude_started_games,
        "as_of_utc": resolved_as_of_utc.isoformat().replace("+00:00", "Z"),
        "dropped_by_date_filter_count": len(rows) - len(date_filtered_rows),
        "dropped_started_or_live_count": len(date_filtered_rows) - len(sorted_rows),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
        "latest_csv_path": str(paths.staged / "engine_board" / "latest.csv"),
        "latest_json_path": str(paths.staged / "engine_board" / "latest.json"),
        "latest_manifest_path": str(paths.staged / "engine_board" / "latest_manifest.json"),
        "columns": list(ENGINE_BOARD_COLUMNS),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    _copy_latest(csv_path, paths.staged / "engine_board" / "latest.csv")
    _copy_latest(json_path, paths.staged / "engine_board" / "latest.json")
    _copy_latest(manifest_path, paths.staged / "engine_board" / "latest_manifest.json")
    return manifest


def _filter_unstarted_rows(rows: list[dict[str, Any]], *, as_of_utc: datetime) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for row in rows:
        if _truthy(row.get("is_live")):
            continue
        start = _parse_utc_datetime(row.get("start_time_utc"))
        if start is not None and start <= as_of_utc:
            continue
        kept.append(row)
    return kept


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _parse_utc_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _infer_target_game_date(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> str:
    snapshot_date = _snapshot_local_date(rows, manifest)
    if snapshot_date:
        return snapshot_date
    dates = sorted({str(row.get("game_date") or "") for row in rows if row.get("game_date")})
    return dates[0] if dates else ""


def _snapshot_local_date(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> str:
    for row in rows:
        local_date = _local_date_from_timestamp(row.get("pulled_at_utc"))
        if local_date:
            return local_date
    snapshot_id = str(manifest.get("snapshot_id") or "")
    match = re.search(r"(\d{8}T\d{6}Z)", snapshot_id)
    if match:
        local_date = _local_date_from_timestamp(match.group(1))
        if local_date:
            return local_date
    match = re.search(r"(\d{8})", snapshot_id)
    if match:
        raw = match.group(1)
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return ""


def _local_date_from_timestamp(value: Any) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        if re.fullmatch(r"\d{8}T\d{6}Z", text):
            parsed = datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    central = ZoneInfo("America/Chicago") if ZoneInfo else timezone(timedelta(hours=-5))
    return parsed.astimezone(central).date().isoformat()


def latest_normalized_board_dir(*, root: Path | None = None) -> Path:
    paths = ensure_mlb_dirs(root)
    candidates = sorted(
        (paths.staged / "board").glob("*/normalize_manifest.json"),
        key=lambda path: path.stat().st_mtime,
    )
    if not candidates:
        raise FileNotFoundError(f"No normalized board manifests found under {paths.staged / 'board'}")
    return candidates[-1].parent


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=ENGINE_BOARD_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in ENGINE_BOARD_COLUMNS})


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _counts_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _csv_value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True)
    return value
