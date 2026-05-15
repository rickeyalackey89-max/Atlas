#!/usr/bin/env python3
"""Wait until first tip minus a lead window, then run Atlas live.

Default behavior:
- Reads NBA start times from data/board/today.csv, falling back to fetch_board.csv.
- Finds the first future game on the local slate.
- Runs scripts/run_iael_530pm.cmd 20 minutes before that first tip.

This script is intended for Windows Task Scheduler or a long-running terminal.
It does not change model logic; it only moves the production run closer to the
best available pre-tip injury report.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
LOCAL_TZ = ZoneInfo("America/Chicago")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lead-minutes", type=int, default=20)
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--board", default="")
    parser.add_argument("--run-cmd", default=str(ROOT / "scripts" / "run_iael_530pm.cmd"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-wait", action="store_true", help="Print target time and exit unless already due.")
    args = parser.parse_args()

    board_path = _resolve_board(args.board)
    first_tip = _first_tip(board_path)
    target = first_tip - timedelta(minutes=max(0, int(args.lead_minutes)))
    now = datetime.now(LOCAL_TZ)

    print(f"[FIRST_TIP] board={board_path}")
    print(f"[FIRST_TIP] first_tip={first_tip.strftime('%Y-%m-%d %I:%M:%S %p %Z')}")
    print(f"[FIRST_TIP] target_run={target.strftime('%Y-%m-%d %I:%M:%S %p %Z')} lead_minutes={args.lead_minutes}")

    if args.dry_run:
        return 0

    if now < target:
        if args.no_wait:
            return 0
        seconds = max(0.0, (target - now).total_seconds())
        print(f"[FIRST_TIP] waiting {seconds / 60.0:.1f} minutes")
        _sleep_until(target, int(args.poll_seconds))
    else:
        print("[FIRST_TIP] target is already due; running now")

    return _run_command(args.run_cmd)


def _resolve_board(value: str) -> Path:
    candidates = []
    if value:
        candidates.append(Path(value))
    candidates.extend(
        [
            ROOT / "data" / "board" / "today.csv",
            ROOT / "data" / "board" / "fetch_board.csv",
        ]
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("No board file found. Run a PrizePicks fetch first.")


def _first_tip(board_path: Path) -> datetime:
    df = pd.read_csv(board_path, low_memory=False)
    if df.empty or "start_time" not in df.columns:
        raise RuntimeError(f"{board_path} has no start_time data")

    starts = pd.to_datetime(df["start_time"], errors="coerce", utc=True).dropna()
    if starts.empty:
        raise RuntimeError(f"{board_path} has no parseable start_time values")

    now = datetime.now(LOCAL_TZ)
    local_starts = sorted(ts.to_pydatetime().astimezone(LOCAL_TZ) for ts in starts)
    today_starts = [ts for ts in local_starts if ts.date() == now.date()]
    future_starts = [ts for ts in today_starts if ts >= now - timedelta(minutes=5)]
    if future_starts:
        return future_starts[0]
    if today_starts:
        return today_starts[0]
    return local_starts[0]


def _sleep_until(target: datetime, poll_seconds: int) -> None:
    poll = max(5, int(poll_seconds))
    while True:
        now = datetime.now(LOCAL_TZ)
        remaining = (target - now).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(float(poll), remaining))


def _run_command(command: str) -> int:
    path = Path(command)
    if path.suffix.lower() == ".cmd":
        cmd = ["cmd.exe", "/c", str(path)]
    else:
        cmd = command
    print(f"[FIRST_TIP] running={command}")
    completed = subprocess.run(cmd, cwd=ROOT, shell=isinstance(cmd, str))
    return int(completed.returncode)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("[FIRST_TIP] interrupted", file=sys.stderr)
        raise SystemExit(130)
