"""Runtime artifact writer for MLB umpire profile context."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

from mlb.matchups.umpire_matrix import load_umpire_profiles
from mlb.runtime.paths import ensure_mlb_dirs
from mlb.runtime.results import RuntimeCommandResult

UMPIRE_PROFILE_COLUMNS = (
    "umpire",
    "era",
    "rating",
    "rating_score",
    "era_score",
    "umpire_run_score",
    "confidence",
    "source",
    "flags",
)


def prepare_umpires_result(
    *,
    source_path: Path,
    root: Path | None = None,
    run_id: str | None = None,
) -> RuntimeCommandResult:
    manifest = prepare_umpire_profile_artifacts(source_path=source_path, root=root, run_id=run_id)
    lines = [
        "Prepared MLB umpire profile artifacts:",
        f"  run_id: {manifest['run_id']}",
        f"  source: {manifest['source_path']}",
        f"  profile_count: {manifest['profile_count']}",
        f"  csv: {manifest['csv_path']}",
        f"  json: {manifest['json_path']}",
        f"  manifest: {manifest['manifest_path']}",
    ]
    return RuntimeCommandResult(name="prepare_umpires", payload=manifest, lines=tuple(lines))


def prepare_umpire_profile_artifacts(
    *,
    source_path: Path,
    root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    paths = ensure_mlb_dirs(root)
    resolved_run_id = run_id or source_path.stem
    profiles = load_umpire_profiles(source_path)
    rows = [profile.to_dict() for profile in profiles]

    output_dir = paths.staged / "umpires" / resolved_run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "umpire_profiles.csv"
    json_path = output_dir / "umpire_profiles.json"
    manifest_path = output_dir / "umpire_profiles_manifest.json"

    _write_csv(csv_path, rows)
    json_path.write_text(
        json.dumps({"run_id": resolved_run_id, "profile_count": len(rows), "rows": rows}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    manifest = {
        "run_id": resolved_run_id,
        "source_path": str(source_path),
        "profile_count": len(rows),
        "columns": list(UMPIRE_PROFILE_COLUMNS),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
        "latest_csv_path": str(paths.staged / "umpires" / "latest.csv"),
        "latest_json_path": str(paths.staged / "umpires" / "latest.json"),
        "latest_manifest_path": str(paths.staged / "umpires" / "latest_manifest.json"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    _copy_latest(csv_path, paths.staged / "umpires" / "latest.csv")
    _copy_latest(json_path, paths.staged / "umpires" / "latest.json")
    _copy_latest(manifest_path, paths.staged / "umpires" / "latest_manifest.json")
    return manifest


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=UMPIRE_PROFILE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in UMPIRE_PROFILE_COLUMNS})


def _copy_latest(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _csv_value(value: Any) -> Any:
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(value, sort_keys=True)
    return value
