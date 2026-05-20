"""Normalize manually captured CBS MLB injury reports for replay snapshots."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from mlb.contracts import InjuryStatus
from mlb.domain.teams import canonical_team_abbr
from mlb.runtime.paths import ensure_mlb_dirs

CBS_MLB_INJURIES_SOURCE = "cbs_mlb_injuries"

_DATE_HEADER_RE = re.compile(r"^[A-Za-z]+,\s+[A-Za-z]+\s+\d{1,2},\s+20\d{2}$")
_TEAM_RE = re.compile(r"^[A-Z]{2,4}$")
_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def write_cbs_mlb_injury_backfill(
    source_path: Path,
    *,
    root: Path | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    run_id_prefix: str = "cbs_injuries",
) -> dict[str, Any]:
    """Write one date-safe staged injury snapshot per report date.

    Missing dates in the requested range are written as empty snapshots. That
    keeps replay selection from carrying an older injury report into a date the
    captured CBS archive says had no report.
    """

    text = source_path.read_text(encoding="utf-8-sig")
    reports = parse_cbs_mlb_injury_text(text)
    report_dates = sorted(reports)
    if not report_dates and (start_date is None or end_date is None):
        raise ValueError("CBS injury report did not contain any dated sections")
    resolved_start = start_date or report_dates[0]
    resolved_end = end_date or report_dates[-1]
    if resolved_start > resolved_end:
        raise ValueError("start_date must be before or equal to end_date")

    paths = ensure_mlb_dirs(root)
    written: list[dict[str, Any]] = []
    for current_date in _date_range(resolved_start, resolved_end):
        rows = reports.get(current_date, [])
        run_id = f"{run_id_prefix}_{current_date.strftime('%Y%m%d')}"
        output_dir = paths.staged / "injuries" / run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        injuries_path = output_dir / "injuries.jsonl"
        manifest_path = output_dir / "normalize_manifest.json"
        injuries_path.write_text(
            "\n".join(json.dumps(asdict(row), sort_keys=True) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )
        manifest = {
            "run_id": run_id,
            "source": CBS_MLB_INJURIES_SOURCE,
            "source_path": str(source_path),
            "game_date": current_date.isoformat(),
            "report_date": current_date.isoformat(),
            "injury_count": len(rows),
            "injuries_path": str(injuries_path),
            "output_dir": str(output_dir),
            "empty_snapshot": len(rows) == 0,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        written.append(manifest)

    return {
        "source": CBS_MLB_INJURIES_SOURCE,
        "source_path": str(source_path),
        "start_date": resolved_start.isoformat(),
        "end_date": resolved_end.isoformat(),
        "date_count": len(written),
        "report_date_count": len(report_dates),
        "injury_count": sum(item["injury_count"] for item in written),
        "empty_snapshot_count": sum(1 for item in written if item["empty_snapshot"]),
        "written": written,
    }


def parse_cbs_mlb_injury_text(text: str) -> dict[date, list[InjuryStatus]]:
    reports: dict[date, list[InjuryStatus]] = {}
    current_date: date | None = None
    current_team = ""

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _DATE_HEADER_RE.match(line):
            current_date = datetime.strptime(line, "%A, %B %d, %Y").date()
            reports.setdefault(current_date, [])
            current_team = ""
            continue
        if current_date is None:
            continue
        if line.lower() in {"mlb injuries", "team\tplayer\tposition\tinjury\tinjury status", "team logo"}:
            continue
        if "\t" not in line and _TEAM_RE.match(line):
            current_team = canonical_team_abbr(line)
            continue

        parts = [part.strip() for part in line.split("\t")]
        if len(parts) < 4 or not current_team:
            continue
        player_name, position, injury, status = parts[0], parts[1], parts[2], " ".join(parts[3:])
        if not player_name or not status:
            continue
        reports[current_date].append(
            InjuryStatus(
                source=CBS_MLB_INJURIES_SOURCE,
                pulled_at_utc="",
                player_name=player_name,
                team=current_team,
                status=status,
                estimated_return=_estimated_return_date(status, report_date=current_date),
                comment=injury,
                player_id="",
                position=position,
                report_date=current_date.isoformat(),
            )
        )

    return reports


def _estimated_return_date(status: str, *, report_date: date) -> str | None:
    match = re.search(
        r"\b("
        r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
        r")\s+(\d{1,2})\b",
        status,
        re.I,
    )
    if not match:
        return None
    month = _MONTHS.get(match.group(1).lower())
    if month is None:
        return None
    try:
        parsed = date(report_date.year, month, int(match.group(2)))
    except ValueError:
        return None
    if parsed < report_date - timedelta(days=7):
        parsed = date(report_date.year + 1, month, int(match.group(2)))
    return parsed.isoformat()


def _date_range(start_date: date, end_date: date) -> tuple[date, ...]:
    return tuple(start_date + timedelta(days=offset) for offset in range((end_date - start_date).days + 1))
