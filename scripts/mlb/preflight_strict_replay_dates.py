"""Strict MLB replay preflight.

This script does not score, replay, train, or mutate model artifacts. It checks
whether each requested date has enough date-safe source coverage to be eligible
for strict-fidelity single replay or corpus replay.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import audit_backfill_readiness as readiness  # noqa: E402


DEFAULT_START = "2026-04-26"
DEFAULT_END = "2026-05-20"
MIN_PRIOR_IDENTITY_ROWS = 5000
MIN_ROSTER_ROWS = 700


def _date_range(start: str, end: str) -> list[str]:
    start_date = datetime.strptime(start, readiness.DATE_FMT).date()
    end_date = datetime.strptime(end, readiness.DATE_FMT).date()
    dates: list[str] = []
    current = start_date
    while current <= end_date:
        dates.append(current.strftime(readiness.DATE_FMT))
        current += timedelta(days=1)
    return dates


def _normalize_dates(args: argparse.Namespace) -> list[str]:
    if args.dates:
        return [str(item).strip() for item in args.dates if str(item).strip()]
    return _date_range(args.start, args.end)


def _strict_failures(row: dict[str, Any]) -> list[str]:
    failures = list(row.get("hard_blockers") or [])

    if not row.get("recommended_replay_snapshot"):
        failures.append("missing_recommended_replay_snapshot")

    market_rows = int(row.get("staged_market_rows") or 0)
    market_sources = row.get("market_source_counts") or {}
    if market_rows <= 0:
        failures.append("missing_normalized_market_rows")
    if market_rows > 0 and not market_sources:
        failures.append("missing_market_source_stamp")

    if int(row.get("statsapi_schedule_games") or 0) <= 0:
        failures.append("missing_statsapi_schedule_for_date")

    if int(row.get("fidelity_context_rows") or 0) <= 0:
        failures.append("missing_pregame_lineup_pitcher_environment_context")
    if int(row.get("weather_context_rows") or 0) <= 0:
        failures.append("missing_weather_environment_context")

    if int(row.get("injury_dirs") or 0) <= 0:
        failures.append("missing_date_safe_injury_context_snapshot")

    roster_rows = int(row.get("roster_rows_total") or 0)
    prior_rows = int(row.get("prior_history_identity_rows") or 0)
    if prior_rows <= 0:
        failures.append("missing_prior_player_history_context")
    if roster_rows < MIN_ROSTER_ROWS and prior_rows < MIN_PRIOR_IDENTITY_ROWS:
        failures.append(
            f"thin_roster_identity rows={roster_rows} prior_history_rows={prior_rows}"
        )

    if int(row.get("advanced_profile_rows") or 0) <= 0 and int(row.get("baseball_savant_rows") or 0) <= 0:
        failures.append("missing_advanced_profile_or_savant_context")

    if int(row.get("ballpark_rows") or 0) <= 0 and int(row.get("wind_factor_rows") or 0) <= 0:
        failures.append("missing_ballpark_or_wind_context")

    # Excluded post-start/postgame source rows may exist in staged archives. They
    # are not a blocker unless no valid pregame/fidelity rows remain.

    # Keep historical umpire context as a warning until a true date-safe source is added.
    return sorted(set(str(item) for item in failures if str(item).strip()))


def audit_dates(root: Path, dates: list[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for date_text in dates:
        day = datetime.strptime(date_text, readiness.DATE_FMT).date()
        row = readiness.audit_date(root, day)
        failures = _strict_failures(row)
        row["strict_preflight_status"] = "PASS" if not failures else "FAIL"
        row["strict_preflight_failures"] = failures
        rows.append(row)

    failed = [row for row in rows if row["strict_preflight_status"] != "PASS"]
    passed = [row for row in rows if row["strict_preflight_status"] == "PASS"]
    return {
        "schema_version": "mlb_strict_replay_preflight_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "root": str(root),
        "requested_dates": dates,
        "verdict": "PASS" if not failed else "FAIL",
        "pass_count": len(passed),
        "fail_count": len(failed),
        "passed_dates": [row["date"] for row in passed],
        "failed_dates": [row["date"] for row in failed],
        "rows": rows,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    import csv

    fieldnames = [
        "date",
        "strict_preflight_status",
        "strict_preflight_failures",
        "recommended_replay_snapshot",
        "prizepicks_mlb_snapshots",
        "prizepicks_github_csv_imports",
        "prizepicks_github_mlb_rows",
        "staged_market_rows",
        "market_source_counts",
        "injury_dirs",
        "injury_rows",
        "roster_rows_total",
        "prior_history_identity_rows",
        "statsapi_schedule_games",
        "fidelity_context_rows",
        "weather_context_rows",
        "postgame_context_rows",
        "post_start_context_rows",
        "baseball_savant_rows",
        "advanced_profile_rows",
        "ballpark_rows",
        "wind_factor_rows",
        "umpire_rows",
        "warnings",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = {name: row.get(name, "") for name in fieldnames}
            out["strict_preflight_failures"] = ";".join(row.get("strict_preflight_failures") or [])
            out["warnings"] = ";".join(row.get("warnings") or [])
            out["market_source_counts"] = json.dumps(row.get("market_source_counts") or {}, sort_keys=True)
            writer.writerow(out)


def _write_md(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# MLB Strict Replay Preflight",
        "",
        f"Generated UTC: {payload['generated_at_utc']}",
        f"Verdict: **{payload['verdict']}**",
        f"Passed: {payload['pass_count']} / {len(payload['requested_dates'])}",
        "",
        "| Date | Status | Market Rows | Sources | Fidelity Ctx | Weather Ctx | Roster/Prior IDs | Advanced | Ballpark/Wind | Failures |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in payload["rows"]:
        failures = ", ".join(row.get("strict_preflight_failures") or []) or "-"
        sources = ", ".join((row.get("market_source_counts") or {}).keys()) or "-"
        roster_prior = f"{row.get('roster_rows_total', 0)}/{row.get('prior_history_identity_rows', 0)}"
        advanced = int(row.get("advanced_profile_rows") or 0) + int(row.get("baseball_savant_rows") or 0)
        park = int(row.get("ballpark_rows") or 0) + int(row.get("wind_factor_rows") or 0)
        lines.append(
            f"| {row['date']} | {row['strict_preflight_status']} | {row.get('staged_market_rows', 0)} | "
            f"{sources} | {row.get('fidelity_context_rows', 0)} | {row.get('weather_context_rows', 0)} | "
            f"{roster_prior} | {advanced} | {park} | {failures} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight MLB strict replay dates before corpus/CAT work.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--dates", nargs="*", default=None, help="Explicit YYYY-MM-DD dates.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Defaults to data/mlb/audits/strict_replay_preflight.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    dates = _normalize_dates(args)
    payload = audit_dates(root, dates)

    output_dir = args.output_dir or root / "data" / "mlb" / "audits" / "strict_replay_preflight"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"strict_replay_preflight_{stamp}.json"
    csv_path = output_dir / f"strict_replay_preflight_{stamp}.csv"
    md_path = output_dir / f"strict_replay_preflight_{stamp}.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_csv(csv_path, payload["rows"])
    _write_md(md_path, payload)
    (output_dir / "strict_replay_preflight_latest.json").write_text(
        json_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (output_dir / "strict_replay_preflight_latest.csv").write_text(
        csv_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (output_dir / "strict_replay_preflight_latest.md").write_text(
        md_path.read_text(encoding="utf-8"), encoding="utf-8"
    )

    print(
        f"[MLB_STRICT_PREFLIGHT] verdict={payload['verdict']} "
        f"pass={payload['pass_count']} fail={payload['fail_count']}"
    )
    for row in payload["rows"]:
        failures = ", ".join(row.get("strict_preflight_failures") or [])
        suffix = f" failures=[{failures}]" if failures else ""
        print(f"  {row['date']} {row['strict_preflight_status']}{suffix}")
    print(f"[MLB_STRICT_PREFLIGHT] json={json_path}")
    print(f"[MLB_STRICT_PREFLIGHT] csv={csv_path}")
    print(f"[MLB_STRICT_PREFLIGHT] md={md_path}")
    return 0 if payload["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
