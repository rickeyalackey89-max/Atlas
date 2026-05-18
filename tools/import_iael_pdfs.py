#!/usr/bin/env python
"""
Import local NBA injury report PDFs into Atlas replay artifacts.

This is for historical strict replays where the official PDF was saved
manually under data/import/Injuries. It writes the same artifact shapes
that live IAEL produces:

  data/output/injury/normalized/<date>_<label>.json
  data/archives/iael/2026/<date>/<timestamp>/injury_invalidations.json
  data/archives/iael/2026/<date>/<timestamp>/status.json
  data/archives/iael/2026/<date>/<timestamp>/iael_manifest.json

QUESTIONABLE players are preserved as soft context only. OUT and DOUBTFUL
remain hard invalidations.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

INJURY_SCRIPT = ROOT / "scripts" / "dev" / "adhoc" / "injury" / "injury_pull_and_parse.py"
INPUT_DIR = ROOT / "data" / "import" / "Injuries"
RAW_DIR = ROOT / "data" / "output" / "injury" / "raw"
NORM_DIR = ROOT / "data" / "output" / "injury" / "normalized"
IAEL_BASE = ROOT / "data" / "archives" / "iael" / "2026"

PDF_NAME_RE = re.compile(
    r"^Injury-Report_(?P<date>\d{4}-\d{2}-\d{2})_(?P<hour>\d{2})_(?P<minute>\d{2})(?P<ampm>AM|PM)\.pdf$",
    re.IGNORECASE,
)


def _load_live_parser():
    spec = importlib.util.spec_from_file_location("atlas_live_injury_parser", INJURY_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load injury parser: {INJURY_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _parse_pdf_name(path: Path) -> tuple[str, str, str]:
    match = PDF_NAME_RE.match(path.name)
    if not match:
        raise ValueError(f"Unexpected injury PDF name: {path.name}")

    report_date = match.group("date")
    hour_s = match.group("hour")
    minute_s = match.group("minute")
    ampm = match.group("ampm").upper()
    report_label = f"{hour_s}:{minute_s}{ampm}"

    hour = int(hour_s)
    minute = int(minute_s)
    if ampm == "AM":
        hour24 = 0 if hour == 12 else hour
    else:
        hour24 = 12 if hour == 12 else hour + 12
    archive_stamp = f"{report_date.replace('-', '')}_{hour24:02d}{minute:02d}00Z"
    return report_date, report_label, archive_stamp


def _build_invalidations(report_date: str, report_label: str, pulled_at: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    invalidated = sorted(
        {
            f"{r.get('team', '')}|{r.get('player', '')}|{r.get('status', '')}"
            for r in rows
            if r.get("hard_invalid")
        }
    )
    return {
        "report_date": report_date,
        "report_label": report_label,
        "pulled_at_local": pulled_at,
        "invalidated_players_count": len(invalidated),
        "invalidated_players": [
            {
                "team": item.split("|")[0],
                "player": item.split("|")[1],
                "status": item.split("|")[2],
                "reason": "",
            }
            for item in invalidated
        ],
        "policy": "Remove OUT/DOUBTFUL from eligibility. QUESTIONABLE retained as soft context.",
        "source": "local_imported_pdf",
    }


def _build_status(report_date: str, report_label: str, pulled_at: str, pdf_hash: str, source_pdf: Path) -> dict[str, Any]:
    return {
        "report_datetime_local": f"{report_date} {report_label}",
        "pulled_at_local": pulled_at,
        "source": "local NBA injury report PDF import",
        "source_url": "",
        "source_pdf": str(source_pdf),
        "pdf_sha1": pdf_hash,
        "post_iael": True,
        "post_line_recon": False,
        "dead_period": False,
        "notes": "Historical IAEL import. QUESTIONABLE is soft context only.",
    }


def import_pdf(pdf_path: Path, parser: Any, *, dry_run: bool = False) -> dict[str, Any]:
    report_date, report_label, archive_stamp = _parse_pdf_name(pdf_path)
    pulled_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    pdf_hash = _sha1(pdf_path)

    raw_pdf_path = RAW_DIR / f"{report_date}_{report_label.replace(':', '_')}.pdf"
    txt_path = RAW_DIR / f"{pdf_hash}.txt"

    if not dry_run:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf_path, raw_pdf_path)
        parser.pdf_to_txt(raw_pdf_path, txt_path)
    elif not txt_path.exists():
        # Parser cannot run without text; dry-run can still report intended paths.
        pass

    if dry_run and not txt_path.exists():
        rows_raw: list[dict[str, str]] = []
    else:
        rows_raw = parser.parse_txt_rows_text(txt_path)

    normalized: list[dict[str, Any]] = []
    for row in rows_raw:
        status = parser.normalize_status(row.get("status", ""))
        normalized.append(
            {
                "report_date": report_date,
                "report_label": report_label,
                "team": row.get("team", ""),
                "player": row.get("player", ""),
                "status": status,
                "reason": (row.get("reason") or "").strip(),
                "game_date": row.get("game_date", ""),
                "hard_invalid": status in parser.HARD_INVALID,
                "tag_probable": status in parser.TAG_ONLY,
                "out_frac": parser.status_to_out_frac(status),
            }
        )

    norm_path = NORM_DIR / f"{report_date}_{report_label.replace(':', '_')}.json"
    archive_dir = IAEL_BASE / report_date / archive_stamp

    normalized_payload = {
        "report_date": report_date,
        "report_label": report_label,
        "source_url": "",
        "source_pdf": str(pdf_path),
        "pulled_at_local": pulled_at,
        "pdf_sha1": pdf_hash,
        "rows": normalized,
    }
    invalidations = _build_invalidations(report_date, report_label, pulled_at, normalized)
    status = _build_status(report_date, report_label, pulled_at, pdf_hash, pdf_path)
    manifest = {
        "source": "local_imported_pdf",
        "source_pdf": str(pdf_path),
        "report_date": report_date,
        "report_label": report_label,
        "pdf_sha1": pdf_hash,
        "normalized_path": str(norm_path),
        "rows": len(normalized),
        "hard_invalidations": invalidations["invalidated_players_count"],
        "questionable_rows": sum(1 for r in normalized if r.get("status") == "QUESTIONABLE"),
    }

    if not dry_run:
        _write_json(norm_path, normalized_payload)
        _write_json(archive_dir / "injury_invalidations.json", invalidations)
        _write_json(archive_dir / "status.json", status)
        _write_json(archive_dir / "iael_manifest.json", manifest)

    return {
        **manifest,
        "archive_dir": str(archive_dir),
        "dry_run": dry_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import local NBA injury PDFs for historical IAEL replays.")
    parser.add_argument("--input-dir", type=Path, default=INPUT_DIR)
    parser.add_argument("--dates", nargs="*", help="Optional YYYYMMDD dates to import.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    wanted = {d.replace("-", "") for d in args.dates} if args.dates else None
    pdfs = sorted(args.input_dir.glob("Injury-Report_*.pdf"))
    if wanted:
        pdfs = [p for p in pdfs if any(d in p.name.replace("-", "") for d in wanted)]

    if not pdfs:
        print(f"[IAEL_IMPORT] No PDFs found under {args.input_dir}")
        return 1

    live_parser = _load_live_parser()
    results = []
    for pdf in pdfs:
        result = import_pdf(pdf, live_parser, dry_run=args.dry_run)
        results.append(result)
        print(
            "[IAEL_IMPORT] "
            f"{result['report_date']} {result['report_label']} "
            f"rows={result['rows']} hard={result['hard_invalidations']} "
            f"questionable={result['questionable_rows']} -> {Path(result['archive_dir']).relative_to(ROOT)}"
        )

    summary_path = ROOT / "data" / "archives" / "iael" / "local_import_summary.json"
    if not args.dry_run:
        _write_json(summary_path, {"imported_at": dt.datetime.now().isoformat(), "results": results})
        print(f"[IAEL_IMPORT] Summary -> {summary_path.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
