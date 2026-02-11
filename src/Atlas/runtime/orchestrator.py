from __future__ import annotations

import subprocess
import sys
import time
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from Atlas.runtime.paths import find_repo_root
from typing import List, Optional


# Project root = 3 parents up from this file
PROJECT_ROOT = find_repo_root(Path(__file__))
TOOLS_DIR = PROJECT_ROOT / "tools"
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = DATA_DIR / "output"
RUNS_DIR = OUTPUT_DIR / "runs"


# -----------------------------
# Helpers
# -----------------------------

@dataclass
class CmdResult:
    ok: bool
    returncode: int
    cmd: List[str]


def _now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _run(cmd: List[str], title: str, check: bool = True, extra_env: dict[str, str] | None = None) -> CmdResult:
    print("\n" + "=" * 72)
    print(f"[{title}] {_now_stamp()}")
    print("CMD:", " ".join(cmd))
    print("=" * 72)

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    p = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env)
    ok = (p.returncode == 0)
    if check and not ok:
        raise SystemExit(p.returncode)
    return CmdResult(ok=ok, returncode=p.returncode, cmd=cmd)


def _py() -> str:
    return sys.executable


# -----------------------------
# Pipeline steps
# -----------------------------

def fetch_raw_only(max_attempts: int = 3, sleep_s: float = 1.0) -> None:
    script = TOOLS_DIR / "fetch_prizepicks_today.py"
    if not script.exists():
        raise FileNotFoundError(f"Missing tool: {script}")

    last_err: Optional[int] = None
    for i in range(1, max_attempts + 1):
        print("\n" + "=" * 72)
        print(f"[FETCH (fresh PrizePicks data) [Atlas raw-only] attempt {i}/{max_attempts}] {_now_stamp()}")
        print("=" * 72)

        cmd = [_py(), str(script), "--raw-only"]
        p = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
        if p.returncode == 0:
            return
        last_err = p.returncode
        if i < max_attempts:
            time.sleep(float(sleep_s))

    raise SystemExit(last_err or 1)


def rebuild_today() -> None:
    script = TOOLS_DIR / "rebuild_today_from_any_raw.py"
    if not script.exists():
        raise FileNotFoundError(f"Missing tool: {script}")
    _run([_py(), str(script)], "REBUILD (canonical today.csv)")


def model_all() -> None:
    # Run legacy model as a proper package module so relative imports work.
    # Ensure src/ is on PYTHONPATH for the subprocess.
    src_dir = str(PROJECT_ROOT / "src")

    existing = os.environ.get("PYTHONPATH", "")
    py_path = src_dir if not existing else (src_dir + os.pathsep + existing)

    _run(
        [_py(), "-m", "Atlas.legacy.main"],
        "MODEL (all)",
        extra_env={"PYTHONPATH": py_path},
    )


def filter_latest_for_tags(*, scheduled: bool) -> None:
    script = TOOLS_DIR / "filter_recommendations_live.py"
    if not script.exists():
        raise FileNotFoundError(f"Missing tool: {script}")

    tags = ["all", "early", "main", "late"]

    print("\n" + "=" * 72)
    print(f"[TAGS: Updating latest folders for: {', '.join(tags)}] {_now_stamp()}")
    print("=" * 72)

    bucket_min_minutes = 0 if scheduled else 30

    # all
    _run(
        [
            _py(),
            str(script),
            "--tag",
            "all",
            "--min-minutes-to-start",
            "0",
            "--match-mode",
            "any",
        ],
        "FILTER (live placeable/all)",
    )

    # buckets
    for tag in ["early", "main", "late"]:
        _run(
            [
                _py(),
                str(script),
                "--tag",
                tag,
                "--min-minutes-to-start",
                str(bucket_min_minutes),
                "--match-mode",
                "strict",
            ],
            f"FILTER (live placeable/{tag})",
            check=True,
        )


# -----------------------------
# Public orchestration API
# -----------------------------

def run_today(*, scheduled: bool = False) -> None:

    fetch_raw_only(max_attempts=3, sleep_s=1.0)

    rebuild_today()

    model_all()

    print("\n" + "=" * 72)
    print(f"[FETCH (live board before finalize/all) SKIPPED] {_now_stamp()}")
    print("=" * 72)
    print("Atlas: reuse last raw fetched at start of run (no second fetch).")

    _run([_py(), str(TOOLS_DIR / "rebuild_today_from_any_raw.py")], "REBUILD (live board snapshot)")

    filter_latest_for_tags(scheduled=scheduled)

    print("\n" + "=" * 72)
    print(f"[DONE] {_now_stamp()}")
    print("=" * 72)
    print("Atlas run complete. latest/{all,early,main,late} updated.")