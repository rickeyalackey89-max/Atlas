from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _utc_compact() -> str:
    # 20260216_073015Z
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")


def _today_dashed_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _repo_root_from_here() -> Path:
    # Conservative: respect repo layout from any entrypoint
    # Falls back to CWD if not sure.
    return Path.cwd()


@dataclass(frozen=True)
class ArchiveIds:
    run_id: Optional[str]
    snapshot_id: str
    date_dashed: str


def resolve_archive_ids(*, run_id: Optional[str] = None, snapshot_id: Optional[str] = None, date_dashed: Optional[str] = None) -> ArchiveIds:
    rid = run_id or os.environ.get("ATLAS_RUN_ID") or None
    sid = snapshot_id or os.environ.get("ATLAS_SNAPSHOT_ID") or _utc_compact()
    dd = date_dashed or os.environ.get("ATLAS_ASOF_DATE_DASHED") or _today_dashed_utc()
    return ArchiveIds(run_id=rid, snapshot_id=sid, date_dashed=dd)


def archive_json_pair(
    *,
    repo_root: Path,
    iael_invalidations_latest: Path,
    iael_status_latest: Path,
    ids: ArchiveIds,
) -> dict:
    """
    Archives IAEL latest jsons into:
      data/archives/iael/YYYY/YYYY-MM-DD/<snapshot_id>/{injury_invalidations.json,status.json}
    Also optionally pins into:
      data/archives/pins/<run_id>/
    """
    year = ids.date_dashed[0:4]
    base = repo_root / "data" / "archives"

    iael_snap_dir = base / "iael" / year / ids.date_dashed / ids.snapshot_id
    iael_snap_dir.mkdir(parents=True, exist_ok=True)

    inv_dst = iael_snap_dir / "injury_invalidations.json"
    st_dst = iael_snap_dir / "status.json"

    res = {
        "run_id": ids.run_id,
        "snapshot_id": ids.snapshot_id,
        "date": ids.date_dashed,
        "iael_snapshot_dir": str(iael_snap_dir),
        "invalidations_src": str(iael_invalidations_latest),
        "status_src": str(iael_status_latest),
        "invalidations_dst": str(inv_dst),
        "status_dst": str(st_dst),
        "pinned": False,
        "pin_dir": None,
        "errors": [],
    }

    try:
        if iael_invalidations_latest.exists():
            shutil.copy2(iael_invalidations_latest, inv_dst)
        else:
            res["errors"].append(f"missing: {iael_invalidations_latest}")

        if iael_status_latest.exists():
            shutil.copy2(iael_status_latest, st_dst)
        else:
            res["errors"].append(f"missing: {iael_status_latest}")
    except Exception as e:
        res["errors"].append(f"copy_failed: {e!r}")

    # Optional pin
    if ids.run_id:
        pin_dir = base / "pins" / ids.run_id
        pin_dir.mkdir(parents=True, exist_ok=True)
        try:
            if inv_dst.exists():
                shutil.copy2(inv_dst, pin_dir / "injury_invalidations.json")
            if st_dst.exists():
                shutil.copy2(st_dst, pin_dir / "status.json")
            # Write a tiny manifest for the pin
            (pin_dir / "pin_manifest.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
            res["pinned"] = True
            res["pin_dir"] = str(pin_dir)
        except Exception as e:
            res["errors"].append(f"pin_failed: {e!r}")

    # Write snapshot manifest
    try:
        (iael_snap_dir / "iael_manifest.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    except Exception as e:
        res["errors"].append(f"manifest_failed: {e!r}")

    return res


def archive_raw_json(
    *,
    repo_root: Path,
    raw_json_path: Path,
    ids: ArchiveIds,
    dst_name: Optional[str] = None,
) -> dict:
    """
    Archives PrizePicks raw json into:
      data/archives/raw/YYYY/YYYY-MM-DD/<snapshot_id>/<dst_name or original>
    And optionally pins into:
      data/archives/pins/<run_id>/prizepicks_raw.json
    """
    year = ids.date_dashed[0:4]
    base = repo_root / "data" / "archives"

    raw_snap_dir = base / "raw" / year / ids.date_dashed / ids.snapshot_id
    raw_snap_dir.mkdir(parents=True, exist_ok=True)

    dst = raw_snap_dir / (dst_name or raw_json_path.name)
    res = {
        "run_id": ids.run_id,
        "snapshot_id": ids.snapshot_id,
        "date": ids.date_dashed,
        "raw_snapshot_dir": str(raw_snap_dir),
        "raw_src": str(raw_json_path),
        "raw_dst": str(dst),
        "pinned": False,
        "pin_dir": None,
        "errors": [],
    }

    try:
        if raw_json_path.exists():
            shutil.copy2(raw_json_path, dst)
        else:
            res["errors"].append(f"missing: {raw_json_path}")
    except Exception as e:
        res["errors"].append(f"copy_failed: {e!r}")

    if ids.run_id:
        pin_dir = base / "pins" / ids.run_id
        pin_dir.mkdir(parents=True, exist_ok=True)
        try:
            if dst.exists():
                shutil.copy2(dst, pin_dir / "prizepicks_raw.json")
            res["pinned"] = True
            res["pin_dir"] = str(pin_dir)
        except Exception as e:
            res["errors"].append(f"pin_failed: {e!r}")

    try:
        (raw_snap_dir / "raw_manifest.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    except Exception as e:
        res["errors"].append(f"manifest_failed: {e!r}")

    return res