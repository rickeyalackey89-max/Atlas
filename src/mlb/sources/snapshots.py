"""Raw snapshot helpers for Atlas MLB sources."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mlb.contracts import RawSnapshot
from mlb.runtime.paths import ensure_mlb_dirs


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp_id(value: datetime | None = None) -> str:
    dt = value or utc_now()
    return dt.strftime("%Y%m%dT%H%M%SZ")


def write_raw_snapshot(
    *,
    source: str,
    payload: dict[str, Any],
    request: dict[str, Any],
    root: Path | None = None,
    payload_text: str | None = None,
    pulled_at: datetime | None = None,
) -> RawSnapshot:
    """Write a raw source payload and colocated manifest."""

    paths = ensure_mlb_dirs(root)
    pulled = pulled_at or utc_now()
    stamp = timestamp_id(pulled)
    snapshot_id = f"{source}_{stamp}"
    out_dir = paths.raw / source / pulled.strftime("%Y-%m-%d") / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    payload_body = payload_text if payload_text is not None else json.dumps(payload, indent=2, sort_keys=True)
    payload_bytes = payload_body.encode("utf-8")
    checksum = hashlib.sha256(payload_bytes).hexdigest()

    payload_path = out_dir / "payload.json"
    manifest_path = out_dir / "manifest.json"
    payload_path.write_bytes(payload_bytes)

    manifest = {
        "snapshot_id": snapshot_id,
        "source": source,
        "sport": "mlb",
        "pulled_at_utc": pulled.isoformat().replace("+00:00", "Z"),
        "payload_path": str(payload_path),
        "checksum_sha256": checksum,
        "request": request,
        "record_count": _record_count(payload),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    return RawSnapshot(
        source=source,
        pulled_at_utc=manifest["pulled_at_utc"],
        path=str(payload_path),
        checksum=checksum,
        request={**request, "snapshot_id": snapshot_id, "manifest_path": str(manifest_path)},
    )


def load_snapshot_payload(path: Path) -> dict[str, Any]:
    """Load a payload from a payload path, manifest path, or snapshot directory."""

    resolved = path.resolve()
    if resolved.is_dir():
        payload_path = resolved / "payload.json"
    elif resolved.name == "manifest.json":
        manifest = json.loads(resolved.read_text(encoding="utf-8"))
        payload_path = Path(str(manifest["payload_path"]))
    else:
        payload_path = resolved
    return json.loads(payload_path.read_text(encoding="utf-8"))


def load_snapshot_manifest(path: Path) -> dict[str, Any]:
    """Load a manifest next to a payload path or from a snapshot directory."""

    resolved = path.resolve()
    if resolved.is_dir():
        manifest_path = resolved / "manifest.json"
    elif resolved.name == "manifest.json":
        manifest_path = resolved
    else:
        manifest_path = resolved.parent / "manifest.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _record_count(payload: dict[str, Any]) -> int:
    if isinstance(payload.get("data"), list):
        return len(payload["data"])
    if isinstance(payload.get("rows"), list):
        return len(payload["rows"])
    if isinstance(payload.get("props"), list):
        return len(payload["props"])
    if isinstance(payload.get("injuries"), list):
        return sum(len(team.get("injuries", []) or []) for team in payload["injuries"])
    return 0
