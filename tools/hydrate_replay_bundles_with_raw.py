#!/usr/bin/env python
"""Add date-pinned PrizePicks raw JSON snapshots into existing replay bundles.

This is a safe migration tool for older FULL_RUN bundles that had today.csv and
market/context inputs but did not carry the original raw PrizePicks payload.
It rewrites each selected zip with an additional data/raw/<snapshot>.json entry
and updates manifest.json. The original zip is copied once to
data/bundles/_prehydrate_backups before replacement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
BUNDLES_DIR = ROOT / "data" / "bundles"
RAW_DIR = ROOT / "data" / "raw"
BACKUP_DIR = BUNDLES_DIR / "_prehydrate_backups"


DEFAULT_DATES = [
    "20260430",
    "20260501",
    "20260502",
    "20260503",
    "20260504",
    "20260505",
    "20260506",
    "20260507",
    "20260508",
    "20260509",
    "20260510",
    "20260511",
    "20260512",
    "20260513",
    "20260515",
    "20260517",
    "20260518",
    "20260520",
]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _bundle_dt(path: Path) -> datetime | None:
    m = re.search(r"atlas_bundle_(\d{8})_(\d{6})", path.name)
    if not m:
        return None
    return datetime.strptime("".join(m.groups()), "%Y%m%d%H%M%S").replace(tzinfo=ZoneInfo("America/Chicago"))


def _raw_dt(path: Path) -> datetime | None:
    m = re.search(r"prizepicks_(\d{8})_(\d{6})", path.name)
    if not m:
        return None
    return datetime.strptime("".join(m.groups()), "%Y%m%d%H%M%S").replace(tzinfo=ZoneInfo("America/Chicago"))


def _bundle_has_data_raw(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path, "r") as z:
            return any(name.lower().startswith("data/raw/") and name.lower().endswith(".json") for name in z.namelist())
    except Exception:
        return False


def _choose_raw_for_bundle(bundle: Path, raws: list[Path]) -> Path | None:
    bdt = _bundle_dt(bundle)
    if bdt is None:
        return None
    candidates: list[tuple[float, Path]] = []
    for raw in raws:
        rdt = _raw_dt(raw)
        if rdt is None:
            continue
        # Strict replay should not hydrate a bundle with a board captured after
        # the bundle/run time. Later snapshots can carry changed lines/slates.
        if rdt <= bdt:
            candidates.append(((bdt - rdt).total_seconds(), raw))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _copy_zip_with_raw(bundle: Path, raw: Path, dry_run: bool) -> str:
    arcname = f"data/raw/{raw.name}"
    if dry_run:
        return "dry_run"

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / bundle.name
    if not backup.exists():
        shutil.copy2(bundle, backup)

    raw_sha = _sha256_file(raw)
    raw_bytes = int(raw.stat().st_size)

    fd, tmp_name = tempfile.mkstemp(prefix=bundle.stem + "_", suffix=".zip", dir=str(bundle.parent))
    os.close(fd)
    Path(tmp_name).unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(bundle, "r") as src_zip, zipfile.ZipFile(tmp_name, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as dst_zip:
            manifest: dict = {}
            for info in src_zip.infolist():
                if info.filename == "manifest.json":
                    try:
                        manifest = json.loads(src_zip.read(info).decode("utf-8"))
                    except Exception:
                        manifest = {}
                    continue
                if info.filename == arcname:
                    continue
                dst_zip.writestr(info, src_zip.read(info.filename))

            dst_zip.write(raw, arcname)

            files = manifest.setdefault("files", {})
            files[arcname] = {"sha256": raw_sha, "bytes": raw_bytes}
            paths = manifest.setdefault("paths", {})
            paths["raw_snapshot"] = str(raw.resolve())
            paths["raw_snapshot_arc"] = arcname
            manifest.setdefault("hydration", {})
            manifest["hydration"].update(
                {
                    "raw_added": True,
                    "raw_snapshot": str(raw.resolve()),
                    "raw_snapshot_arc": arcname,
                    "backup": str(backup.resolve()),
                }
            )
            dst_zip.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        Path(tmp_name).replace(bundle)
    finally:
        Path(tmp_name).unlink(missing_ok=True)
    return str(backup)


def hydrate_dates(dates: list[str], dry_run: bool) -> dict:
    results = []
    for date in dates:
        bundles = sorted(BUNDLES_DIR.glob(f"atlas_bundle_{date}_*.zip"))
        bundles = [b for b in bundles if "DEAD_PERIOD" not in b.name and "TEST" not in b.name]
        raws = sorted(RAW_DIR.glob(f"prizepicks_{date}_*.json"))
        for bundle in bundles:
            if _bundle_has_data_raw(bundle):
                results.append({"date": date, "bundle": str(bundle), "status": "already_hydrated"})
                continue
            raw = _choose_raw_for_bundle(bundle, raws)
            if raw is None:
                results.append({"date": date, "bundle": str(bundle), "status": "skipped_no_prior_raw"})
                continue
            backup = _copy_zip_with_raw(bundle, raw, dry_run=dry_run)
            results.append(
                {
                    "date": date,
                    "bundle": str(bundle),
                    "raw": str(raw),
                    "status": "hydrated" if not dry_run else "would_hydrate",
                    "backup": backup,
                }
            )
    hydrated = sum(1 for r in results if r["status"] in {"hydrated", "would_hydrate"})
    skipped = sum(1 for r in results if r["status"].startswith("skipped"))
    return {"dates": dates, "dry_run": dry_run, "hydrated_count": hydrated, "skipped_count": skipped, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Hydrate old replay bundles with date-pinned raw PrizePicks snapshots.")
    parser.add_argument("--dates", nargs="*", default=DEFAULT_DATES)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    payload = hydrate_dates([d.strip() for d in args.dates if d.strip()], dry_run=args.dry_run)
    out_path = Path(args.out) if args.out else ROOT / "data" / "model" / "candidates" / f"bundle_raw_hydration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print(f"[HYDRATE] dry_run={payload['dry_run']} hydrated={payload['hydrated_count']} skipped={payload['skipped_count']}")
    for row in payload["results"]:
        if row["status"] in {"hydrated", "would_hydrate", "skipped_no_prior_raw"}:
            print(f"  {row['date']} {row['status']} {Path(row['bundle']).name} raw={Path(row.get('raw', '')).name if row.get('raw') else ''}")
    print(f"[HYDRATE] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
