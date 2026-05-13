#!/usr/bin/env python3
"""Robust 6AM eval backfill runner.

The scheduled CMD wrapper should not enumerate run folders with batch wildcards.
This helper owns the prior-day run discovery and writes eval_legs.csv for every
eligible run folder in both output and telemetry archives.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.create_eval_leg_backtestv2 import load_gamelogs, process_run  # noqa: E402


@dataclass(frozen=True)
class EvalBackfillItem:
    run_dir: str
    root_name: str
    status: str
    rows: int | None = None
    matched_rows: int | None = None
    unmatched_rows: int | None = None
    output_path: str | None = None
    report_path: str | None = None
    reason: str | None = None


def discover_run_dirs(*, atlas_root: Path, game_date: date) -> list[tuple[str, Path]]:
    prefix = game_date.strftime("%Y%m%d")
    roots = (
        ("output_runs", atlas_root / "data" / "output" / "runs"),
        ("telemetry_live_runs", atlas_root / "data" / "telemetry" / "live_runs"),
    )
    discovered: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for root_name, root in roots:
        if not root.exists():
            continue
        for run_dir in sorted(root.iterdir(), key=lambda path: path.name):
            if not run_dir.is_dir() or not run_dir.name.startswith(f"{prefix}_"):
                continue
            resolved = run_dir.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            discovered.append((root_name, run_dir))
    return discovered


def backfill_eval_legs(
    *,
    atlas_root: Path,
    game_date: date,
    gamelogs_path: Path,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    gamelogs = load_gamelogs(gamelogs_path)
    items: list[EvalBackfillItem] = []

    for root_name, run_dir in discover_run_dirs(atlas_root=atlas_root, game_date=game_date):
        scored_path = run_dir / "scored_legs_deduped.csv"
        eval_path = run_dir / "eval_legs.csv"
        if not scored_path.exists():
            items.append(
                EvalBackfillItem(
                    run_dir=str(run_dir),
                    root_name=root_name,
                    status="skipped",
                    reason="missing_scored_legs_deduped",
                )
            )
            continue
        if eval_path.exists() and not force:
            items.append(
                EvalBackfillItem(
                    run_dir=str(run_dir),
                    root_name=root_name,
                    status="skipped",
                    reason="eval_exists",
                    output_path=str(eval_path),
                )
            )
            continue

        try:
            result = process_run(run_dir, gamelogs, write=not dry_run, output_name="eval_legs.csv")
            items.append(
                EvalBackfillItem(
                    run_dir=result.run_dir,
                    root_name=root_name,
                    status="dry_run" if dry_run else "written",
                    rows=result.rows,
                    matched_rows=result.matched_rows,
                    unmatched_rows=result.unmatched_rows,
                    output_path=result.output_path,
                    report_path=result.report_path,
                )
            )
        except Exception as exc:  # Keep processing other runs; report failures explicitly.
            items.append(
                EvalBackfillItem(
                    run_dir=str(run_dir),
                    root_name=root_name,
                    status="failed",
                    reason=str(exc),
                )
            )

    rows_total = sum(item.rows or 0 for item in items if item.status in {"written", "dry_run"})
    matched_total = sum(item.matched_rows or 0 for item in items if item.status in {"written", "dry_run"})
    failed = [item for item in items if item.status == "failed"]
    payload = {
        "date": game_date.isoformat(),
        "date_tag": game_date.strftime("%Y%m%d"),
        "atlas_root": str(atlas_root),
        "gamelogs_path": str(gamelogs_path),
        "dry_run": dry_run,
        "force": force,
        "discovered_count": len(items),
        "written_count": sum(1 for item in items if item.status == "written"),
        "dry_run_count": sum(1 for item in items if item.status == "dry_run"),
        "skipped_count": sum(1 for item in items if item.status == "skipped"),
        "failed_count": len(failed),
        "rows_total": rows_total,
        "matched_rows_total": matched_total,
        "match_rate_total": float(matched_total / rows_total) if rows_total else None,
        "items": [asdict(item) for item in items],
    }
    return payload


def _default_game_date() -> date:
    return date.today() - timedelta(days=1)


def _parse_date(value: str | None) -> date:
    if not value:
        return _default_game_date()
    return date.fromisoformat(value)


def _print_human_summary(payload: dict) -> None:
    print(
        "[6AM_EVAL] "
        f"date={payload['date']} discovered={payload['discovered_count']} "
        f"written={payload['written_count']} skipped={payload['skipped_count']} "
        f"failed={payload['failed_count']} rows={payload['rows_total']} "
        f"match_rate={payload['match_rate_total']}"
    )
    for item in payload["items"]:
        status = item["status"]
        reason = item.get("reason")
        suffix = f" reason={reason}" if reason else ""
        rows = item.get("rows")
        rows_text = f" rows={rows}" if rows is not None else ""
        print(f"[6AM_EVAL] {status}: {item['run_dir']}{rows_text}{suffix}")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill prior-day eval_legs.csv for Atlas 6AM eval")
    parser.add_argument("--date", help="Game date to backfill, YYYY-MM-DD. Defaults to yesterday.")
    parser.add_argument("--atlas-root", default=str(PROJECT_ROOT), help="Atlas repository root")
    parser.add_argument(
        "--gamelogs-path",
        default=str(PROJECT_ROOT / "data" / "gamelogs" / "nba_gamelogs.csv"),
        help="Path to nba_gamelogs.csv",
    )
    parser.add_argument("--force", action="store_true", help="Rewrite eval_legs.csv even when it exists")
    parser.add_argument("--dry-run", action="store_true", help="Compute reports without writing eval files")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args(list(argv) if argv is not None else None)

    payload = backfill_eval_legs(
        atlas_root=Path(args.atlas_root),
        game_date=_parse_date(args.date),
        gamelogs_path=Path(args.gamelogs_path),
        force=args.force,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_human_summary(payload)

    if payload["failed_count"]:
        return 1
    if payload["discovered_count"] == 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
