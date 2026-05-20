"""Compact generated MLB artifacts while preserving audit manifests.

This script is intentionally conservative:
- raw source snapshots are never touched
- model artifacts are never touched
- live runs are kept by default
- dry-run is the default; pass --apply to delete bulky generated rows

The archive summary is small JSON that records deleted paths, byte counts, and
checksums for small manifest/eval/config files that should remain auditable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


KEEP_NAMES = {
    "aggregate_members.csv",
    "aggregate_summary.json",
    "aggregate_slips.csv",
    "best_config.json",
    "latest_eval_manifest.json",
    "latest_eval_slips.csv",
    "latest_eval_slips.json",
    "latest_eval_summary.json",
    "latest_slip_eval.json",
    "manifest.json",
    "operator_report.md",
    "publish_decision.json",
    "run_manifest.json",
    "score_manifest.json",
    "simulation_manifest.json",
    "slip_builder_family_label_eligible_summary.csv",
    "slip_builder_family_label_summary.csv",
    "slip_builder_family_summary.csv",
    "slip_builder_leg_segment_summary.csv",
    "slip_builder_slip_rows.csv",
    "slips_manifest.json",
    "source_selection_manifest.json",
    "tuned_best_config.json",
}

KEEP_SUFFIXES = (
    "_manifest.json",
    ".run.json",
    ".eval.json",
    ".error.txt",
)

DROP_SUFFIXES = (
    ".csv",
    ".json",
    ".jsonl",
    ".parquet",
)

DEFAULT_TARGETS = ("features", "staged", "test_runs", "eval")


@dataclass
class ArchiveItem:
    path: str
    size_bytes: int
    sha256: str | None = None
    archive_path: str | None = None


def main() -> int:
    parser = argparse.ArgumentParser(description="Compact generated MLB artifacts")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--targets", nargs="*", default=list(DEFAULT_TARGETS), choices=DEFAULT_TARGETS)
    parser.add_argument("--archive-id", default="")
    parser.add_argument("--apply", action="store_true", help="Delete generated artifacts after writing archive manifest")
    parser.add_argument("--include-live-runs", action="store_true", help="Also compact data/mlb/live_runs")
    parser.add_argument("--max-keep-bytes", type=int, default=2_000_000)
    args = parser.parse_args()

    root = args.root.resolve()
    data_root = root / "data" / "mlb"
    if not data_root.exists():
        raise SystemExit(f"Missing MLB data root: {data_root}")

    archive_id = args.archive_id or datetime.now(timezone.utc).strftime("artifact_compaction_%Y%m%dT%H%M%SZ")
    archive_root = data_root / "archives" / "compacted_artifacts" / archive_id
    archive_root.mkdir(parents=True, exist_ok=True)

    target_dirs = [data_root / target for target in args.targets]
    if args.include_live_runs:
        target_dirs.append(data_root / "live_runs")

    keep_items: list[ArchiveItem] = []
    delete_items: list[ArchiveItem] = []
    for target_dir in target_dirs:
        if not target_dir.exists():
            continue
        for path in _iter_files(target_dir):
            rel = path.relative_to(root).as_posix()
            size = path.stat().st_size
            if _should_keep_small_audit_file(path, size=size, max_keep_bytes=args.max_keep_bytes):
                item = ArchiveItem(path=rel, size_bytes=size, sha256=_sha256(path))
                if args.apply:
                    item.archive_path = _copy_to_archive(root=root, archive_root=archive_root, path=path)
                keep_items.append(item)
            elif _should_delete_generated_file(path):
                delete_items.append(ArchiveItem(path=rel, size_bytes=size))

    deleted_bytes = sum(item.size_bytes for item in delete_items)
    kept_bytes = sum(item.size_bytes for item in keep_items)
    manifest = {
        "archive_id": archive_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "apply": bool(args.apply),
        "root": str(root),
        "targets": [str(path.relative_to(root).as_posix()) for path in target_dirs if path.exists()],
        "policy": {
            "raw_touched": False,
            "model_touched": False,
            "live_runs_included": bool(args.include_live_runs),
            "max_keep_bytes": args.max_keep_bytes,
        },
        "summary": {
            "audit_file_count": len(keep_items),
            "audit_bytes": kept_bytes,
            "delete_file_count": len(delete_items),
            "delete_bytes": deleted_bytes,
            "delete_gb": round(deleted_bytes / (1024**3), 3),
        },
        "audit_files": [asdict(item) for item in keep_items],
        "delete_files": [asdict(item) for item in delete_items],
    }
    manifest_path = archive_root / "compaction_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    if args.apply:
        for item in delete_items:
            path = root / item.path
            if path.exists():
                path.unlink()
        _remove_empty_dirs(target_dirs)

    print(json.dumps({"manifest": str(manifest_path), **manifest["summary"]}, indent=2, sort_keys=True))
    return 0


def _iter_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file():
            yield path


def _should_keep_small_audit_file(path: Path, *, size: int, max_keep_bytes: int) -> bool:
    if size > max_keep_bytes:
        return False
    name = path.name
    if name in KEEP_NAMES:
        return True
    return any(name.endswith(suffix) for suffix in KEEP_SUFFIXES)


def _should_delete_generated_file(path: Path) -> bool:
    name = path.name
    if name in KEEP_NAMES or any(name.endswith(suffix) for suffix in KEEP_SUFFIXES):
        return False
    return path.suffix.lower() in DROP_SUFFIXES


def _copy_to_archive(*, root: Path, archive_root: Path, path: Path) -> str:
    rel = path.relative_to(root)
    target = archive_root / "files" / rel
    if len(str(target)) > 240:
        target = archive_root / "files_flat" / f"{_sha256_text(rel.as_posix())}_{path.name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return target.relative_to(archive_root).as_posix()


def _remove_empty_dirs(target_dirs: list[Path]) -> None:
    for target_dir in target_dirs:
        if not target_dir.exists():
            continue
        for path in sorted((p for p in target_dir.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            try:
                path.rmdir()
            except OSError:
                pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


if __name__ == "__main__":
    raise SystemExit(main())
