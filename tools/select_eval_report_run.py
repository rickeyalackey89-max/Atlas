#!/usr/bin/env python3
"""
Select the canonical Atlas run used for prior-day eval reporting.

Weekend game dates use the 2:30 PM report. Weekday game dates use the
5:30 PM report. The selector chooses the timestamped run closest to the
target time, preferring an earlier run on exact ties.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_DIR = PROJECT_ROOT / "data" / "output" / "runs"


def _parse_run_time(run_dir: Path) -> time | None:
    name = run_dir.name
    if len(name) != 15 or name[8] != "_":
        return None
    try:
        return datetime.strptime(name[9:], "%H%M%S").time()
    except ValueError:
        return None


def target_report_time(game_date: date) -> time:
    """Return the canonical report time for a game date."""
    if game_date.weekday() >= 5:
        return time(14, 30)
    return time(17, 30)


def select_report_run(
    *,
    game_date: date,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    require_eval: bool = False,
) -> Path | None:
    """Select the timestamped run closest to the required report time."""
    prefix = game_date.strftime("%Y%m%d")
    target = target_report_time(game_date)
    target_seconds = target.hour * 3600 + target.minute * 60 + target.second

    candidates: list[tuple[Path, int]] = []
    if not runs_dir.exists():
        return None

    for run_dir in runs_dir.iterdir():
        run_time = _parse_run_time(run_dir)
        if not run_dir.is_dir() or run_time is None or not run_dir.name.startswith(prefix):
            continue
        if require_eval and not (run_dir / "eval_legs.csv").exists():
            continue
        run_seconds = run_time.hour * 3600 + run_time.minute * 60 + run_time.second
        candidates.append((run_dir, run_seconds))

    if not candidates:
        return None

    return min(candidates, key=lambda item: (abs(item[1] - target_seconds), item[1] > target_seconds, item[1]))[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Select canonical Atlas eval report run")
    parser.add_argument("--date", required=True, help="Game date in YYYY-MM-DD format")
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR), help="Atlas data/output/runs directory")
    parser.add_argument("--require-eval", action="store_true", help="Only select runs that already have eval_legs.csv")
    parser.add_argument("--format", choices=("path", "name", "json"), default="path")
    args = parser.parse_args()

    try:
        game_date = date.fromisoformat(args.date)
    except ValueError:
        print(f"[SELECT_REPORT_RUN] invalid date: {args.date}", file=sys.stderr)
        return 2

    runs_dir = Path(args.runs_dir)
    selected = select_report_run(game_date=game_date, runs_dir=runs_dir, require_eval=args.require_eval)
    if selected is None:
        print(f"[SELECT_REPORT_RUN] no matching run for {game_date.isoformat()} in {runs_dir}", file=sys.stderr)
        return 1

    if args.format == "name":
        print(selected.name)
    elif args.format == "json":
        print(json.dumps({
            "date": game_date.isoformat(),
            "target_time": target_report_time(game_date).strftime("%H:%M:%S"),
            "run_id": selected.name,
            "run_dir": str(selected),
        }))
    else:
        print(selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
