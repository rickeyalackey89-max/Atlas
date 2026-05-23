#!/usr/bin/env python3
"""Wait until first tip minus a lead window, then run Atlas live.

Default behavior:
- Refreshes the live PrizePicks board, then reads NBA start times from
  data/board/fetch_board.csv, falling back to today.csv.
- Finds the first future game on the local slate.
- Runs the root Atlas live wrapper for NBA 20 minutes before that first tip.

This script is intended for Windows Task Scheduler or a long-running terminal.
It does not change model logic; it only moves the production run closer to the
best available pre-tip injury report.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
ATLAS_ROOT = ROOT.parent
LOCAL_TZ = ZoneInfo("America/Chicago")
DEFAULT_RUN_CMD = str(ATLAS_ROOT / "run-live-sports.cmd")
DEFAULT_RUN_ARGS = ["-WindowLabel", "firsttip", "-RunNBA", "-ContinueOnError"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lead-minutes", type=int, default=20)
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--board", default="")
    parser.add_argument("--run-cmd", default=DEFAULT_RUN_CMD)
    parser.add_argument(
        "--run-arg",
        action="append",
        default=None,
        help="Argument to pass to --run-cmd. Repeat for multiple args. Defaults to NBA live root wrapper args.",
    )
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        help="Do not refresh PrizePicks board before calculating first tip.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-wait", action="store_true", help="Print target time and exit unless already due.")
    args = parser.parse_args()

    if not args.skip_refresh:
        _refresh_board()

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

    run_args = args.run_arg if args.run_arg is not None else DEFAULT_RUN_ARGS
    return _run_command(args.run_cmd, run_args)


def _refresh_board() -> None:
    """Refresh the live board so first-tip timing is based on today's slate."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    steps = [
        [sys.executable, str(ROOT / "tools" / "fetch_apis.py"), "--raw-only"],
        [sys.executable, str(ROOT / "tools" / "rebuild_today_from_any_raw.py")],
    ]
    for cmd in steps:
        if not Path(cmd[1]).is_file():
            raise FileNotFoundError(f"Missing board refresh tool: {cmd[1]}")
        print(f"[FIRST_TIP] refreshing board: {' '.join(cmd)}")
        completed = subprocess.run(cmd, cwd=ROOT, env=env)
        if completed.returncode != 0:
            raise RuntimeError(f"Board refresh failed with exit code {completed.returncode}")


def _resolve_board(value: str) -> Path:
    candidates = []
    if value:
        candidates.append(Path(value))
    candidates.extend(
        [
            ROOT / "data" / "board" / "fetch_board.csv",
            ROOT / "data" / "board" / "today.csv",
        ]
    )
    for path in candidates:
        if path.is_file() and _has_parseable_start_time(path):
            return path
    raise FileNotFoundError("No board file with parseable start_time found. Run a PrizePicks fetch/rebuild first.")


def _has_parseable_start_time(path: Path) -> bool:
    try:
        df = pd.read_csv(path, nrows=25, low_memory=False)
    except Exception:
        return False
    if df.empty or "start_time" not in df.columns:
        return False
    return bool(pd.to_datetime(df["start_time"], errors="coerce", utc=True).notna().any())


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


def _run_command(command: str, args: list[str]) -> int:
    path = Path(command)
    if path.suffix.lower() == ".cmd":
        cmd = ["cmd.exe", "/c", str(path), *args]
    else:
        cmd = [command, *args]
    print(f"[FIRST_TIP] running={' '.join(cmd)}")
    completed = subprocess.run(cmd, cwd=ATLAS_ROOT)
    return int(completed.returncode)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("[FIRST_TIP] interrupted", file=sys.stderr)
        raise SystemExit(130)
